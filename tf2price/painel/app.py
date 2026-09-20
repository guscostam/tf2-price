"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Connection, Engine

from tf2price import db
from tf2price.contas import servico
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def criar_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="Painel de Unusual")
    app.state.engine = engine

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

    @app.get("/entrar", response_class=HTMLResponse)
    def tela_entrar(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request, name="entrar.html", context={"erro": None}
        )

    @app.post("/entrar", dependencies=[Depends(ses.mesma_origem)])
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
                request=request, name="entrar.html", context={"erro": str(erro)}
            )
        resposta = RedirectResponse("/", status_code=303)
        ses.gravar_cookie(resposta, request, token)
        return resposta

    @app.post("/sair", dependencies=[Depends(ses.mesma_origem)])
    def fazer_sair(
        request: Request, conn: Connection = Depends(ses.conexao)
    ) -> Response:
        servico.sair(conn, request.cookies.get(ses.NOME_COOKIE, ""))
        resposta = RedirectResponse("/entrar", status_code=303)
        ses.apagar_cookie(resposta)
        return resposta

    # Provisória: a Task 7 troca o corpo desta rota pela consulta.
    @app.get("/", response_class=HTMLResponse)
    def painel(
        request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)
    ):
        return TEMPLATES.TemplateResponse(
            request=request, name="base.html", context={"usuario": usuario}
        )

    return app
