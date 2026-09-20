"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Connection, Engine

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.contas.senhas import SenhaCurta
from tf2price.painel import sessao as ses

if TYPE_CHECKING:
    from tf2price.painel.consulta import Contexto

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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

    def _convite_aberto(conn: Connection, token: str):
        """Convite utilizável, ou None. Não diz por que não serve."""
        convite = repo.convite_por_hash(conn, tokens.hash_de(token))
        if convite is None or convite.usado_em is not None:
            return None
        if convite.expira_em <= db.agora():
            return None
        return convite

    @app.get("/convite/{token}", response_class=HTMLResponse)
    def tela_convite(
        request: Request, token: str, conn: Connection = Depends(ses.conexao)
    ):
        convite = _convite_aberto(conn, token)
        if convite is None:
            # Inexistente, expirado e usado dão a mesma resposta: distinguir
            # entrega informação a quem está adivinhando token.
            return HTMLResponse("Este convite não serve mais.", status_code=404)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="convite.html",
            context={
                "token": token,
                "redefinicao": convite.tipo == servico.TIPO_REDEFINICAO,
                "erro": None,
            },
        )

    @app.post("/convite/{token}", dependencies=[Depends(ses.mesma_origem)])
    def usar_convite(
        request: Request,
        token: str,
        nome: str = Form(""),
        senha: str = Form(...),
        conn: Connection = Depends(ses.conexao),
    ) -> Response:
        convite = _convite_aberto(conn, token)
        if convite is None:
            return HTMLResponse("Este convite não serve mais.", status_code=404)

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
                context={"token": token, "redefinicao": redefinicao, "erro": str(erro)},
            )

        # Já entra: pedir para digitar de novo a senha recém-escolhida é atrito
        # sem ganho, e o link acabou de provar quem é.
        sessao_token = servico.entrar_direto(conn, usuario, quando=db.agora())
        resposta = RedirectResponse("/", status_code=303)
        ses.gravar_cookie(resposta, request, sessao_token)
        return resposta

    if contexto is not None:
        from tf2price.painel.consulta import ROTEADOR

        app.include_router(ROTEADOR)

    return app


def servir() -> None:
    """Ponto de entrada: python -m tf2price.painel.app"""
    import uvicorn

    from tf2price.painel.consulta import construir_contexto

    engine = db.criar_engine()
    db.criar_schema(engine)
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    if token:
        print(f"[partida] nenhum usuário ainda. Convite de administrador: /convite/{token}")

    uvicorn.run(criar_app(engine, construir_contexto()), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    servir()
