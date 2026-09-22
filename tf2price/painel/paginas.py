from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.consulta import idade_por_extenso, linhas_acompanhadas
from tf2price.painel.templates import TEMPLATES
from tf2price.painel.varredura import ha_quanto_tempo
from tf2price.preco.referencia import montar_referencia, motivo_sem_referencia

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])


def _estado(request: Request, usuario: Usuario) -> dict:
    contexto = request.app.state.contexto
    engine = request.app.state.engine
    agora = db.agora()
    cotacao = contexto.cotacao.obter(engine)
    indice = contexto.indice.em_memoria()
    ptax = contexto.ptax.obter(engine)
    referencia = montar_referencia(indice, ptax)
    with engine.begin() as conn:
        linhas = linhas_acompanhadas(
            conn, referencia.brl if referencia else None, indice, usuario.id, agora
        )
    return {
        "usuario": usuario,
        # A cotação da Steam só converte listagens em dólar; a Sources mostra
        # a taxa dela com a idade.
        "cotacao": cotacao,
        "cotacao_idade": (
            idade_por_extenso(cotacao.buscado_em, agora) if cotacao else None
        ),
        "referencia": referencia,
        "sem_referencia": motivo_sem_referencia(indice, ptax),
        "bptf_idade": (
            ha_quanto_tempo(referencia.bptf_carregado_em, agora) if referencia else None
        ),
        "indice_pronto": indice is not None,
        "linhas": linhas,
    }


def renderizar_overview(request: Request, usuario: Usuario):
    """O Overview de quem está logado. `/` é de `publico.py`, que decide
    entre isto e a landing; aqui fica só a montagem da página."""
    estado = _estado(request, usuario)
    estado["recentes"] = list(reversed(estado["linhas"]))[:5]
    return TEMPLATES.TemplateResponse(
        request=request, name="overview.html", context=estado
    )


@ROTEADOR.get("/cases/new", response_class=HTMLResponse)
def new_case(
    request: Request,
    nome: str = "",
    efeito: str = "",
    usuario: Usuario = Depends(ses.usuario_obrigatorio),
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="new_case.html",
        context={
            **_estado(request, usuario),
            "initial_name": nome,
            "initial_effect": efeito,
        },
    )


@ROTEADOR.get("/cases", response_class=HTMLResponse)
def case_files(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    return TEMPLATES.TemplateResponse(
        request=request, name="case_files.html", context=_estado(request, usuario)
    )


@ROTEADOR.get("/sources", response_class=HTMLResponse)
def sources(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    return TEMPLATES.TemplateResponse(
        request=request, name="sources.html", context=_estado(request, usuario)
    )
