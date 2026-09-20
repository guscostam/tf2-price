"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.contas import servico
from tf2price.painel import acesso, admin
from tf2price.painel import sessao as ses

if TYPE_CHECKING:
    from tf2price.painel.consulta import Contexto


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

    return app


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

    uvicorn.run(criar_app(engine, construir_contexto()), host="127.0.0.1", port=8000)


def construir_aplicacao() -> FastAPI:
    """Aplicação de produção: schema, convite de partida e contexto.

    É fábrica, e não uma variável de módulo, porque `construir_contexto` faz
    requisições à Steam: criar a aplicação no import faria qualquer `import
    tf2price.painel.app` — inclusive o de um teste — sair para a rede.
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
    return criar_app(engine, construir_contexto())


if __name__ == "__main__":
    servir()
