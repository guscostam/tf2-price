"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.contas import permissoes, servico
from tf2price.contas import repositorio as repo_contas
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.painel import acesso, admin, publico
from tf2price.painel import sessao as ses
from tf2price.painel.limite import LimitePorChave
from tf2price.saneamento import mensagem_saneada
from tf2price.varredura import repositorio as varredura_repo
from tf2price.varredura.agendador import (
    Agendador,
    construir_agendador,
    iniciar_em_segundo_plano,
)

if TYPE_CHECKING:
    from tf2price.painel.consulta import Contexto

# O nome só pode ser <digitos>.webp. Conferir com expressão regular em vez de
# juntar caminho e torcer: esta rota recebe texto de fora. `fullmatch`, não
# `match`: `$` sozinho aceita uma quebra de linha final, `match` não ancora no
# começo, e ambos juntos deixariam passar coisa como "13.webp\n".
_NOME_DE_ARTE = re.compile(r"^\d{1,7}\.webp$")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def criar_app(
    engine: Engine,
    contexto: "Contexto | None" = None,
    agendador: Agendador | None = None,
    superadmin: str | None = None,
) -> FastAPI:
    app = FastAPI(title="briefcase.tf")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.engine = engine
    app.state.contexto = contexto
    # None nos testes e em qualquer app sem contexto: a página e o admin
    # dizem que a varredura não roda neste processo.
    app.state.agendador = agendador
    # Nome da conta dona do painel (`SUPERADMIN`). None: ninguém promove nem
    # rebaixa admins, e nenhum admin fica exposto — ver `contas/permissoes`.
    app.state.superadmin = superadmin
    app.state.limite_pedidos = LimitePorChave(
        maximo=publico.PEDIDOS_POR_IP, janela_s=publico.JANELA_DOS_PEDIDOS_S
    )

    @app.exception_handler(ses.PrecisaEntrar)
    def _sem_sessao(request: Request, _exc: ses.PrecisaEntrar) -> Response:
        # Fragmento HTMX não pode receber 303: o swap engoliria a página de
        # entrar dentro do alvo. HX-Redirect tira o navegador da página.
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/entrar"})
        return RedirectResponse("/entrar", status_code=303)

    @app.exception_handler(ses.PrecisaSerAdmin)
    def _sem_permissao(request: Request, _exc: ses.PrecisaSerAdmin) -> Response:
        return HTMLResponse("This page is restricted to administrators.", status_code=403)

    app.include_router(acesso.ROTEADOR)
    app.include_router(admin.ROTEADOR)
    app.include_router(publico.ROTEADOR)

    if contexto is not None:
        from tf2price.painel import consulta, paginas, varredura

        app.include_router(paginas.ROTEADOR)
        app.include_router(consulta.ROTEADOR)
        app.include_router(varredura.ROTEADOR)

    @app.get("/arte/{nome}")
    def servir_arte(nome: str) -> Response:
        if not _NOME_DE_ARTE.fullmatch(nome):
            return Response(status_code=404)
        arquivo = arte_dos_efeitos.DIRETORIO / nome
        if not arquivo.is_file():
            return Response(status_code=404)
        # A arte de um efeito nunca muda: cache longo evita pedir de novo a
        # cada avaliação aberta.
        return FileResponse(
            arquivo,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    return app


def aquecer(contexto: "Contexto", engine: Engine) -> None:
    """Puxa cotação, PTAX e índice para a memória do processo, fora da requisição.

    As três nascem vazias e se preenchem na primeira necessidade. Quem pagava
    esse primeiro carregamento era a primeira pessoa a abrir o painel depois
    de cada deploy, de dentro do `GET /`, olhando uma página em branco —
    medido em 21/09/2026: ~3,5s no caminho bom (duas requisições à Steam
    espaçadas de 1s, mais 5 MB de IGetPrices da bp.tf) e de 31 a 62 segundos
    por requisição se a Steam responder 429, porque aí entra o backoff.

    Carregar na subida não é o mesmo que carregar no import: `obter()` engole
    a exceção e registra no log (resistir a terceiro fora do ar é o objetivo
    daquelas classes), então um CDN ou uma API caída continua não impedindo o
    serviço de subir — que foi a razão de elas existirem. O `try` é só para
    um erro que nasça fora do deles.

    Sequencial, num thread só: as duas requisições da cotação compartilham o
    espaçamento do `RateLimiter`, e buscar em paralelo não as faria chegar
    mais rápido.

    A cotação recebe `engine` e `quando` porque hoje ela passa pelo banco
    antes de pensar em rede — num processo recém-subido com cotação guardada
    recente, este aquecimento nem fala com a Steam.
    """
    _aquece("cotação", lambda: contexto.cotacao.renovar(engine, db.agora()))
    _aquece("PTAX", lambda: contexto.ptax.renovar(engine, db.agora()))
    _aquece("índice", contexto.indice.obter)


def _aquece(nome: str, buscar) -> None:
    inicio = time.monotonic()
    try:
        veio = buscar() is not None
    except Exception as erro:  # pragma: no cover - `obter` já captura
        print(f"[aquecimento] {nome}: {type(erro).__name__}: {erro}", flush=True)
        return
    estado = "ok" if veio else "falhou; a tela pede de novo sob demanda"
    print(
        f"[aquecimento] {nome}: {estado} em {time.monotonic() - inicio:.1f}s",
        flush=True,
    )


# De quanto em quanto tempo o fundo acorda para ver se a cotação ou a PTAX
# envelheceram. Não é a frequência das requisições à Steam nem ao BC:
# `renovar` volta na hora se o que há ainda é recente (15 min para a cotação
# da Steam, 1 h para a PTAX) ou se a calma dos 300s está de pé. Acordar de
# minuto em minuto só garante que a renovação aconteça pouco depois de a
# validade mais curta (a da Steam) vencer, e não até um ciclo inteiro depois.
PERIODO_DO_RENOVO_S = 60.0


def manter_quente(
    contexto: "Contexto",
    engine: Engine,
    *,
    periodo_s: float = PERIODO_DO_RENOVO_S,
    parar: threading.Event | None = None,
) -> None:
    """Aquece uma vez e depois renova a cotação e a PTAX enquanto o processo viver.

    Este ciclo existe porque `CotacaoSobDemanda.obter` deixou de ir à rede:
    sem alguem renovando por fora, a cotação congelaria no valor da subida e
    envelheceria para sempre. O índice não entra no ciclo — ele não tem
    validade nenhuma hoje, e inventar uma aqui seria decidir de lado.

    `parar` é para o teste: sem ele, o laço não tem fim (o que é o certo num
    thread daemon, que morre com o processo).
    """
    aquecer(contexto, engine)
    parar = parar or threading.Event()
    while not parar.wait(periodo_s):
        # Cada `renovar` só engole a falha do terceiro (Steam/BC); uma leitura
        # ou escrita do NOSSO banco pode levantar (um soluço do Postgres, por
        # exemplo), e sem o `try` aqui essa exceção mataria o thread daemon —
        # ninguém mais renovaria nada até reiniciar o processo. Cada chamada
        # tem o seu próprio `try`, então uma falha no banco de uma não impede
        # a outra: independente da cotação, uma Steam limitando não impede a
        # PTAX, nem o contrário.
        try:
            contexto.cotacao.renovar(engine, db.agora())
        except Exception as erro:
            print(
                f"[renovo] cotação: {type(erro).__name__}: {mensagem_saneada(erro)}",
                flush=True,
            )
        try:
            contexto.ptax.renovar(engine, db.agora())
        except Exception as erro:
            print(
                f"[renovo] PTAX: {type(erro).__name__}: {mensagem_saneada(erro)}",
                flush=True,
            )


def aquecer_em_segundo_plano(
    contexto: "Contexto", engine: Engine
) -> threading.Thread:
    """Aquece e mantem quente sem segurar a subida.

    `daemon=True` de propósito, por duas razões: o backoff da Steam pode
    levar um minuto, e o laço de `manter_quente` não termina — um
    encerramento não pode ficar esperando nenhum dos dois.
    """
    thread = threading.Thread(
        target=manter_quente, args=(contexto, engine), name="aquecimento", daemon=True
    )
    thread.start()
    return thread


def preparar_varredura(
    engine: Engine,
    contexto: "Contexto | None",
    iniciar: Callable[[Agendador], object] = iniciar_em_segundo_plano,
) -> Agendador:
    """Fecha rodadas que um processo anterior deixou abertas e sobe o agendador.

    Uma rodada sem fim no banco é de um processo que morreu no meio dela
    (deploy, reinício). Não há retomada: `funda_em` por nome faz a próxima
    rodada pular o que já foi lido.
    """
    with engine.begin() as conn:
        fechadas = varredura_repo.fechar_abertas(conn, db.agora())
    if fechadas:
        print(f"[varredura] {fechadas} rodada(s) interrompida(s) por reinício", flush=True)
    agendador = construir_agendador(engine, contexto)
    iniciar(agendador)
    return agendador


_SEM_GESTAO = "ninguém pode promover ou rebaixar administradores"


def aviso_do_superadmin(engine: Engine, nome: str | None) -> str | None:
    """A linha do log quando `SUPERADMIN` não serve, ou None quando serve.

    Não é erro fatal: sem superadmin o painel funciona e nenhum admin fica
    exposto — só não há quem promova ou rebaixe. Na primeira subida, antes
    de a conta nascer pelo convite de partida, o aviso é esperado; a conta
    vale como superadmin assim que existir, sem reiniciar.
    """
    if not nome:
        return f"[superadmin] SUPERADMIN ausente: {_SEM_GESTAO}"
    with engine.begin() as conn:
        usuario = repo_contas.usuario_por_nome(conn, nome)
    if usuario is None or not permissoes.eh_superadmin(usuario, nome):
        return f'[superadmin] "{nome}" não é um admin ativo: {_SEM_GESTAO}'
    return None


def preparar_superadmin(engine: Engine) -> str | None:
    """Lê `SUPERADMIN`, avisa no log se ela não serve e devolve o nome."""
    nome = (os.getenv("SUPERADMIN") or "").strip() or None
    aviso = aviso_do_superadmin(engine, nome)
    if aviso:
        print(aviso, flush=True)
    return nome


def servir() -> None:
    """Ponto de entrada: python -m tf2price.painel.app"""
    import uvicorn
    from dotenv import load_dotenv

    from tf2price.painel.consulta import construir_contexto

    # `DATABASE_URL` mora no `.env` em desenvolvimento local, e `db.criar_engine`
    # lê a variável de ambiente diretamente — sem isto, ela nunca chegaria a
    # existir antes da leitura, porque `construir_contexto` só carrega o
    # `.env` depois.
    load_dotenv(".env")

    engine = db.criar_engine()
    db.criar_schema(engine)
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    if token:
        print(f"[partida] nenhum usuário ainda. Convite de administrador: /convite/{token}")
    superadmin = preparar_superadmin(engine)

    contexto = construir_contexto()
    aquecer_em_segundo_plano(contexto, engine)
    agendador = preparar_varredura(engine, contexto)
    uvicorn.run(
        criar_app(engine, contexto, agendador, superadmin=superadmin),
        host="127.0.0.1",
        port=8000,
    )


def construir_aplicacao() -> FastAPI:
    """Aplicação de produção: schema, convite de partida, contexto e aquecimento.

    É fábrica, e não uma variável de módulo, porque monta o que fala com
    terceiros: criar a aplicação no import faria qualquer `import
    tf2price.painel.app` — inclusive o de um teste — sair para a rede. Isso
    valia por `construir_contexto`, que hoje já não toca a rede, e voltou a
    valer literalmente com o aquecimento, que sai.
    """
    from dotenv import load_dotenv

    from tf2price.painel.consulta import construir_contexto

    # Mesma razão do load_dotenv em `servir`: `db.criar_engine` lê
    # `DATABASE_URL` do ambiente antes de `construir_contexto` ter chance de
    # carregar o `.env`. Em produção (Railway) as variáveis já vêm do
    # ambiente e esta chamada não faz nada.
    load_dotenv(".env")

    engine = db.criar_engine()
    db.criar_schema(engine)
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    if token:
        # Primeiro acesso: o link sai no log, uma vez, e vale 24 horas.
        print(f"[partida] convite de administrador: /convite/{token}", flush=True)
    superadmin = preparar_superadmin(engine)
    contexto = construir_contexto()
    # Em segundo plano, e antes de a primeira pessoa chegar: é a diferença
    # entre o processo esperar pelos terceiros e alguém esperar olhando uma
    # página em branco.
    aquecer_em_segundo_plano(contexto, engine)
    agendador = preparar_varredura(engine, contexto)
    return criar_app(engine, contexto, agendador, superadmin=superadmin)


if __name__ == "__main__":
    servir()
