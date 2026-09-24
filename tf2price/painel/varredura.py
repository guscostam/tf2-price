"""A página da varredura: todas as listagens de cosméticos Unusual.

A rota só lê o banco e a memória. Ela nunca vai à Steam nem à backpack.tf:
quem busca é a rodada, no fundo, e o índice é o que o aquecimento carregou.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.consulta import idade_por_extenso
from tf2price.painel.templates import TEMPLATES
from tf2price.preco.referencia import montar_referencia, motivo_sem_referencia
from tf2price.varredura import leitura
from tf2price.varredura import repositorio as repo
from tf2price.varredura import vendas_repo

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])

# Os motivos são gravados em português (são dado); a tela é em inglês.
ROTULO_DA_PARADA: dict[str | None, str] = {
    None: "Running",
    repo.MOTIVO_OK: "Completed",
    repo.MOTIVO_429: "Stopped: Steam rate limit",
    repo.MOTIVO_ERRO: "Stopped: error",
    repo.MOTIVO_INTERROMPIDA: "Interrupted by a restart",
    repo.MOTIVO_CANCELADA: "Stopped by admin",
}


def _ha(idade: str) -> str:
    """"5 min" -> "5 min ago"; "now" -> "just now" (e não "now ago")."""
    return "just now" if idade == "now" else f"{idade} ago"


def ha_quanto_tempo(quando, agora) -> str:
    """"5 min ago", "just now": a mesma frase do /scan, para o admin."""
    return _ha(idade_por_extenso(quando, agora))


@ROTEADOR.get("/scan", response_class=HTMLResponse)
def scan(
    request: Request,
    aba: str = "todas",
    q: str = "",
    efeito: str = "",
    preco_min: str = "",
    preco_max: str = "",
    idade_max: str = str(leitura.IDADE_MAX_BPTF_PADRAO),
    ordem: str = "resultado",
    pagina: str = "1",
    usuario: Usuario = Depends(ses.usuario_obrigatorio),
):
    filtros = leitura.filtros_da_query(
        aba=aba, q=q, efeito=efeito, preco_min=preco_min, preco_max=preco_max,
        idade_max=idade_max, ordem=ordem, pagina=pagina,
    )
    engine = request.app.state.engine
    contexto = request.app.state.contexto
    agora = db.agora()
    indice = contexto.indice.em_memoria()
    ptax = contexto.ptax.obter(engine)
    referencia = montar_referencia(indice, ptax)
    with engine.begin() as conn:
        listagens = repo.listar_listagens(
            conn, texto=filtros.texto, efeito=filtros.efeito,
            preco_min=filtros.preco_min, preco_max=filtros.preco_max,
        )
        efeitos = repo.efeitos_varridos(conn)
        config = repo.ler_config(conn)
        ultima = repo.ultima_rodada(conn)
        completa = repo.ultima_completa(conn)
        cobertura = repo.cobertura(conn)
        vendas_por_par = vendas_repo.ler_todas(conn)
    resultado = leitura.montar(
        listagens, indice, referencia.brl if referencia else None, filtros, time.time(),
        vendas_por_par=vendas_por_par,
    )
    agendador = request.app.state.agendador
    contexto_da_tela = {
        "usuario": usuario,
        "filtros": filtros,
        "pagina": resultado,
        "efeitos": efeitos,
        "config": config,
        "ultima": ultima,
        "completa": completa,
        "cobertura": cobertura,
        "rodando": bool(agendador and agendador.rodando),
        "referencia": referencia,
        "sem_referencia": motivo_sem_referencia(indice, ptax),
        "motivo_429": repo.MOTIVO_429,
        "idade": lambda quando: idade_por_extenso(quando, agora),
        "ha": lambda quando: _ha(idade_por_extenso(quando, agora)),
    }
    # Na restauração do histórico (hx-push-url sem cache), o htmx manda
    # HX-Request junto e troca o <body> inteiro: precisa da página toda.
    so_a_tabela = bool(request.headers.get("HX-Request")) and not request.headers.get(
        "HX-History-Restore-Request"
    )
    nome = "_scan_tabela.html" if so_a_tabela else "scan.html"
    resposta = TEMPLATES.TemplateResponse(request=request, name=nome, context=contexto_da_tela)
    # A mesma URL devolve página ou fragmento: sem Vary, o Voltar do
    # navegador pode servir o fragmento em cache como se fosse a página.
    resposta.headers["Vary"] = "HX-Request"
    return resposta
