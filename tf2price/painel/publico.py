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


def _sem_porta(valor: str) -> str:
    """Extrai o host de um item do X-Forwarded-For, do mesmo jeito que
    `uvicorn.middleware.proxy_headers._parse_host_port`: IP nu,
    `host:porta` e `[ipv6]:porta`. Qualquer formato fora desses três volta
    sem alteração, para nunca inventar um host que não estava lá.
    """
    if valor.startswith("["):
        fim = valor.find("]")
        if fim == -1:
            return valor
        host = valor[1:fim]
        resto = valor[fim + 1 :]
        if not resto:
            return host
        if not resto.startswith(":"):
            return valor
        try:
            int(resto[1:])
        except ValueError:
            return host
        return host
    if valor.count(":") == 1:
        host, porta = valor.rsplit(":", 1)
        try:
            int(porta)
        except ValueError:
            return valor
        return host
    return valor


def chave_do_cliente(request: Request) -> str:
    """Escolhe a chave do freio de pedidos a partir do IP do cliente.

    Junta todas as linhas do cabeçalho X-Forwarded-For (pode vir mais de
    uma) e usa o último item não vazio: o Railway é o único proxy na frente
    do app e acrescenta o IP que ele viu como último item da lista; itens
    anteriores vêm do próprio cliente e podem ser forjados. Se um dia
    houver outro proxy antes do Railway, esta função precisa mudar.

    Sem o cabeçalho, usa `request.client.host`: o middleware de proxy do
    uvicorn só reescreve `request.client` quando há X-Forwarded-For, então
    sem ele o valor ainda é o endereço real da conexão. Com o cabeçalho
    presente mas um último item que não é IP válido, a chave fixa
    "invalido" agrupa esse tráfego num balde só — nunca cai em
    `request.client.host` nesse caso: com `--forwarded-allow-ips=*` esse
    campo já foi reescrito pelo *primeiro* item do cabeçalho, que é
    controlado pelo cliente.
    """
    linhas = request.headers.getlist("x-forwarded-for")
    if not linhas:
        return request.client.host if request.client else "desconhecido"
    itens = [item.strip() for item in ",".join(linhas).split(",") if item.strip()]
    if not itens:
        return "invalido"
    texto = _sem_porta(itens[-1])
    try:
        endereco = ipaddress.ip_address(texto)
    except ValueError:
        return "invalido"
    if endereco.version == 6:
        mapeado = endereco.ipv4_mapped
        if mapeado is not None:
            # ::ffff:1.2.3.4 é só um IPv4 disfarçado; usa o endereço real.
            return str(mapeado)
        # Um cliente IPv6 costuma controlar a /64 inteira, não só um
        # endereço; monta a rede a partir do valor já resolvido (não do
        # texto), para que uma zona (`%eth0`) não vaze para a chave.
        rede = ipaddress.ip_network((int(endereco), 64), strict=False)
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
