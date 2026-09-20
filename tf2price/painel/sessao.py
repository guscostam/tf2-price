"""Cookie de sessão, dependências de requisição e conferência de origem."""

from __future__ import annotations

from typing import Iterator
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas import servico
from tf2price.contas.modelo import Usuario

NOME_COOKIE = "sessao"


class PrecisaEntrar(Exception):
    """Sem sessão válida. O tratador decide entre redirecionar e HX-Redirect."""


class PrecisaSerAdmin(Exception):
    """Sessão válida, mas sem permissão."""


def conexao(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.begin() as conn:
        yield conn


def usuario_opcional(
    request: Request, conn: Connection = Depends(conexao)
) -> Usuario | None:
    token = request.cookies.get(NOME_COOKIE, "")
    return servico.usuario_da_sessao(conn, token, db.agora())


def usuario_obrigatorio(
    usuario: Usuario | None = Depends(usuario_opcional),
) -> Usuario:
    if usuario is None:
        raise PrecisaEntrar()
    return usuario


def exigir_admin(usuario: Usuario = Depends(usuario_obrigatorio)) -> Usuario:
    if not usuario.admin:
        raise PrecisaSerAdmin()
    return usuario


def mesma_origem(request: Request) -> None:
    """Recusa POST vindo de outro site.

    O cookie já é SameSite=Lax, o que barra o navegador; esta conferência
    cobre o que não é navegador. Quando o cabeçalho Origin não vem — curl,
    teste — não há o que comparar e a requisição segue.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    origem = request.headers.get("origin")
    if origem and urlparse(origem).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="origem não confere")


def gravar_cookie(resposta: Response, request: Request, token: str) -> None:
    # `Secure` pelo esquema da requisição: fixá-lo sempre impediria entrar em
    # http://127.0.0.1 no desenvolvimento. Em produção, atrás do proxy do
    # Railway, o uvicorn precisa de --proxy-headers para que o esquema chegue
    # como https (veja a Task 9).
    resposta.set_cookie(
        NOME_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=int(servico.VALIDADE_SESSAO.total_seconds()),
        path="/",
    )


def apagar_cookie(resposta: Response) -> None:
    resposta.delete_cookie(NOME_COOKIE, path="/")
