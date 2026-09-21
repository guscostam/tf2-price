"""Rotas de acesso: entrar, sair e resgatar convite."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.contas.senhas import SenhaCurta
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter()


def _account_error_message(error: Exception) -> str:
    if isinstance(error, servico.CredenciaisInvalidas):
        return "Incorrect username or password."
    if isinstance(error, servico.ContaBloqueada):
        return "Too many attempts. Wait a few minutes before trying again."
    if isinstance(error, servico.ContaInativa):
        return "This account is disabled."
    if isinstance(error, SenhaCurta):
        return "Password must contain at least 10 characters."
    if isinstance(error, servico.NomeEmUso):
        mensagens = {
            "escolha um nome": "Choose a username.",
            "esse nome já está em uso": "That username is already in use.",
        }
        texto = str(error)
        if texto.startswith("esse nome é longo demais"):
            return "Username is too long. The maximum is 60 characters."
        return mensagens.get(texto, "The account could not be created.")
    return "The request could not be completed."


@ROTEADOR.get("/entrar", response_class=HTMLResponse)
def tela_entrar(request: Request):
    return TEMPLATES.TemplateResponse(
        request=request, name="entrar.html", context={"erro": None}
    )


@ROTEADOR.post("/entrar", dependencies=[Depends(ses.mesma_origem)])
def fazer_entrar(
    request: Request,
    nome: str = Form(...),
    senha: str = Form(...),
    conn: Connection = Depends(ses.conexao),
) -> Response:
    try:
        token = servico.entrar(conn, nome=nome, senha=senha, quando=db.agora())
    except servico.ErroDeConta as erro:
        return TEMPLATES.TemplateResponse(
            request=request, name="entrar.html",
            context={"erro": _account_error_message(erro)},
        )
    resposta = RedirectResponse("/", status_code=303)
    ses.gravar_cookie(resposta, request, token)
    return resposta


@ROTEADOR.post("/sair", dependencies=[Depends(ses.mesma_origem)])
def fazer_sair(
    request: Request, conn: Connection = Depends(ses.conexao)
) -> Response:
    servico.sair(conn, request.cookies.get(ses.NOME_COOKIE, ""))
    resposta = RedirectResponse("/entrar", status_code=303)
    ses.apagar_cookie(resposta)
    return resposta


def _convite_aberto(conn: Connection, token: str):
    """Convite utilizável, ou None. Não diz por que não serve."""
    convite = repo.convite_por_hash(conn, tokens.hash_de(token))
    if convite is None or convite.usado_em is not None:
        return None
    if convite.expira_em <= db.agora():
        return None
    return convite


@ROTEADOR.get("/convite/{token}", response_class=HTMLResponse)
def tela_convite(
    request: Request, token: str, conn: Connection = Depends(ses.conexao)
):
    convite = _convite_aberto(conn, token)
    if convite is None:
        # Inexistente, expirado e usado dão a mesma resposta: distinguir
        # entrega informação a quem está adivinhando token.
        return HTMLResponse("This invitation is no longer valid.", status_code=404)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="convite.html",
        context={
            "token": token,
            "redefinicao": convite.tipo == servico.TIPO_REDEFINICAO,
            "erro": None,
        },
    )


@ROTEADOR.post("/convite/{token}", dependencies=[Depends(ses.mesma_origem)])
def usar_convite(
    request: Request,
    token: str,
    nome: str = Form(""),
    senha: str = Form(...),
    conn: Connection = Depends(ses.conexao),
) -> Response:
    convite = _convite_aberto(conn, token)
    if convite is None:
        return HTMLResponse("This invitation is no longer valid.", status_code=404)

    redefinicao = convite.tipo == servico.TIPO_REDEFINICAO
    try:
        if redefinicao:
            usuario = servico.redefinir(conn, token, senha=senha, quando=db.agora())
        else:
            usuario = servico.aceitar_convite(
                conn, token, nome=nome, senha=senha, quando=db.agora()
            )
    except (servico.ErroDeConta, SenhaCurta) as erro:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="convite.html",
            context={
                "token": token, "redefinicao": redefinicao,
                "erro": _account_error_message(erro),
            },
        )

    # Já entra: pedir para digitar de novo a senha recém-escolhida é atrito
    # sem ganho, e o link acabou de provar quem é.
    sessao_token = servico.entrar_direto(conn, usuario, quando=db.agora())
    resposta = RedirectResponse("/", status_code=303)
    ses.gravar_cookie(resposta, request, sessao_token)
    return resposta
