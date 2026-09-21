"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.contas import servico
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.painel import acesso, admin
from tf2price.painel import sessao as ses

if TYPE_CHECKING:
    from tf2price.painel.consulta import Contexto

# O nome só pode ser <digitos>.webp. Conferir com expressão regular em vez de
# juntar caminho e torcer: esta rota recebe texto de fora. `fullmatch`, não
# `match`: `$` sozinho aceita uma quebra de linha final, `match` não ancora no
# começo, e ambos juntos deixariam passar coisa como "13.webp\n".
_NOME_DE_ARTE = re.compile(r"^\d{1,7}\.webp$")


def criar_app(engine: Engine, contexto: "Contexto | None" = None) -> FastAPI:
    app = FastAPI(title="Painel de Unusual")
    app.state.engine = engine
    app.state.contexto = contexto

    @app.exception_handler(ses.PrecisaEntrar)
    def _sem_sessao(request: Request, _exc: ses.PrecisaEntrar) -> Response:
        # Fragmento HTMX não pode receber 303: o swap engoliria a página de
        # entrar dentro do alvo. HX-Redirect tira o navegador da página.
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/entrar"})
        return RedirectResponse("/entrar", status_code=303)

    @app.exception_handler(ses.PrecisaSerAdmin)
    def _sem_permissao(request: Request, _exc: ses.PrecisaSerAdmin) -> Response:
        return HTMLResponse("Esta página é só do administrador.", status_code=403)

    app.include_router(acesso.ROTEADOR)
    app.include_router(admin.ROTEADOR)

    if contexto is not None:
        from tf2price.painel.consulta import ROTEADOR

        app.include_router(ROTEADOR)

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


def aquecer(contexto: "Contexto") -> None:
    """Puxa cotação e índice para a memória do processo, fora da requisição.

    As duas nascem vazias e se preenchem na primeira necessidade. Quem pagava
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
    """
    for nome, fonte in (("cotação", contexto.cotacao), ("índice", contexto.indice)):
        inicio = time.monotonic()
        try:
            veio = fonte.obter() is not None
        except Exception as erro:  # pragma: no cover - `obter` já captura
            print(f"[aquecimento] {nome}: {type(erro).__name__}: {erro}", flush=True)
            continue
        estado = "ok" if veio else "falhou; a tela pede de novo sob demanda"
        print(
            f"[aquecimento] {nome}: {estado} em {time.monotonic() - inicio:.1f}s",
            flush=True,
        )


def aquecer_em_segundo_plano(contexto: "Contexto") -> threading.Thread:
    """Aquece sem segurar a subida.

    `daemon=True` de propósito: o backoff da Steam pode levar um minuto, e
    um encerramento não deve ficar esperando por ele.
    """
    thread = threading.Thread(
        target=aquecer, args=(contexto,), name="aquecimento", daemon=True
    )
    thread.start()
    return thread


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

    contexto = construir_contexto()
    aquecer_em_segundo_plano(contexto)
    uvicorn.run(criar_app(engine, contexto), host="127.0.0.1", port=8000)


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
    contexto = construir_contexto()
    # Em segundo plano, e antes de a primeira pessoa chegar: é a diferença
    # entre o processo esperar pelos terceiros e alguém esperar olhando uma
    # página em branco.
    aquecer_em_segundo_plano(contexto)
    return criar_app(engine, contexto)


if __name__ == "__main__":
    servir()
