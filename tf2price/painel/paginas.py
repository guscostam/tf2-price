from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.consulta import idade_por_extenso, linhas_acompanhadas
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])


def _estado(request: Request, usuario: Usuario) -> dict:
    contexto = request.app.state.contexto
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    indice = contexto.indice.em_memoria()
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, cotacao, indice, usuario.id, agora)
    return {
        "usuario": usuario,
        "cotacao": cotacao,
        "cotacao_idade": (
            idade_por_extenso(cotacao.buscado_em, agora) if cotacao else None
        ),
        "indice_pronto": indice is not None,
        "linhas": linhas,
    }


@ROTEADOR.get("/", response_class=HTMLResponse)
def overview(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
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
