"""Rotas públicas: a landing em `/` e o pedido de acesso.

`/` é a porta de entrada dos dois públicos. Sem sessão, a landing; com sessão,
o Overview de sempre, na mesma URL, para que os redirecionamentos existentes
para `/` continuem levando quem está logado ao painel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter()


def renderizar_landing(
    request: Request,
    *,
    estado: str = "formulario",
    valores: dict[str, str] | None = None,
    erros: dict[str, str] | None = None,
    status_code: int = 200,
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="landing.html",
        context={"estado": estado, "valores": valores or {}, "erros": erros or {}},
        status_code=status_code,
    )


@ROTEADOR.get("/", response_class=HTMLResponse)
def raiz(
    request: Request,
    requested: str = "",
    usuario: Usuario | None = Depends(ses.usuario_opcional),
):
    # Sem `Contexto` (montagem dos testes de autenticação) não há Overview.
    if usuario is not None and request.app.state.contexto is not None:
        # Import tardio pelo mesmo motivo de `criar_app`: `paginas` puxa a
        # consulta inteira, que só existe quando há `Contexto`.
        from tf2price.painel import paginas

        return paginas.renderizar_overview(request, usuario)
    return renderizar_landing(
        request, estado="enviado" if requested == "1" else "formulario"
    )
