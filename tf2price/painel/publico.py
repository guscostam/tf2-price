"""Rotas públicas: a landing em `/` e o pedido de acesso.

`/` é a porta de entrada dos dois públicos. Sem sessão, a landing; com sessão,
o Overview de sempre, na mesma URL, para que os redirecionamentos existentes
para `/` continuem levando quem está logado ao painel.
"""

from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from tf2price import db
from tf2price.contas import pedidos
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter()

PEDIDOS_POR_IP = 3
JANELA_DOS_PEDIDOS_S = 3600
_CONFIRMADO = "/?requested=1#access"


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


def chave_do_cliente(request: Request) -> str:
    """Escolhe a chave do freio de pedidos a partir do IP do cliente.

    Usa o último item do `X-Forwarded-For`, não o primeiro: o Railway é o
    único proxy na frente do app e acrescenta o IP que ele viu como último
    item da lista; itens anteriores vêm do próprio cliente e podem ser
    forjados. Se um dia houver outro proxy antes do Railway, esta função
    precisa mudar.
    """
    xff = request.headers.get("x-forwarded-for", "")
    itens = [item.strip() for item in xff.split(",") if item.strip()]
    if itens:
        texto = itens[-1]
    else:
        texto = request.client.host if request.client else "desconhecido"
    try:
        endereco = ipaddress.ip_address(texto)
    except ValueError:
        # Não é um IP válido: nunca usa o texto forjado como chave.
        return request.client.host if request.client else "desconhecido"
    if endereco.version == 6:
        # Um cliente IPv6 costuma controlar a /64 inteira, não só um endereço.
        rede = ipaddress.ip_network(f"{texto}/64", strict=False)
        return str(rede)
    return str(endereco)


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


@ROTEADOR.post("/access-request", dependencies=[Depends(ses.mesma_origem)])
def pedir_acesso(
    request: Request,
    perfil_steam: str = Form(""),
    contato: str = Form(""),
    observacao: str = Form(""),
    website: str = Form(""),
) -> Response:
    if not request.app.state.limite_pedidos.permitir(chave_do_cliente(request)):
        return renderizar_landing(request, estado="limite", status_code=429)
    if website:
        # Honeypot: só robô preenche. Responde como sucesso para não ensinar.
        return RedirectResponse(_CONFIRMADO, status_code=303)
    pedido, erros = pedidos.validar_pedido(perfil_steam, contato, observacao)
    if pedido is None:
        return renderizar_landing(
            request,
            valores={
                "perfil_steam": perfil_steam,
                "contato": contato,
                "observacao": observacao,
            },
            erros=erros,
            status_code=422,
        )
    with request.app.state.engine.begin() as conn:
        resultado = pedidos.registrar_pedido(conn, pedido, db.agora())
    if resultado is pedidos.Resultado.FECHADO:
        return renderizar_landing(request, estado="fechado", status_code=503)
    # GRAVADO e DUPLICADO respondem igual: a página não revela quem já pediu.
    return RedirectResponse(_CONFIRMADO, status_code=303)
