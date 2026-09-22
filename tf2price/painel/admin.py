"""Rotas de administração: convidar, redefinir senha e ativar/desativar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas import pedidos
from tf2price.contas import repositorio as repo
from tf2price.contas import repositorio_pedidos as repo_pedidos
from tf2price.contas import servico
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES
from tf2price.painel.varredura import ROTULO_DA_PARADA
from tf2price.varredura import repositorio as varredura_repo

ROTEADOR = APIRouter()


def _tela_admin(
    request: Request,
    conn: Connection,
    usuario: Usuario,
    link=None,
    erro: str | None = None,
    varredura_msg: str | None = None,
):
    agendador = request.app.state.agendador
    return TEMPLATES.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "usuario": usuario,
            "usuarios": repo.listar_usuarios(conn),
            "pedidos": repo_pedidos.listar_pendentes(conn),
            "link": link,
            "erro": erro,
            "varredura": varredura_repo.ler_config(conn),
            "rodadas": varredura_repo.ultimas_rodadas(conn),
            "rodando": bool(agendador and agendador.rodando),
            "rotulo_da_parada": ROTULO_DA_PARADA,
            "intervalo_minimo": varredura_repo.INTERVALO_MINIMO_MIN,
            "varredura_msg": varredura_msg,
        },
    )


@ROTEADOR.get("/admin", response_class=HTMLResponse)
def tela_admin(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    return _tela_admin(request, conn, usuario)


@ROTEADOR.post("/admin/convite", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def gerar_convite(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    token = servico.convidar(conn, criado_por=usuario.id, quando=db.agora())
    # O token em claro existe só aqui: o banco tem apenas o hash.
    return _tela_admin(request, conn, usuario, link=f"/convite/{token}")


@ROTEADOR.post("/admin/redefinir/{usuario_id}", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def gerar_redefinicao(
    request: Request,
    usuario_id: int,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    if repo.usuario_por_id(conn, usuario_id) is None:
        # Sem isto o convite nasce com `alvo` apontando para ninguém: o
        # SQLite deixa passar, e a chave estrangeira do Postgres levanta.
        return HTMLResponse("User not found.", status_code=404)
    token = servico.convidar(
        conn,
        criado_por=usuario.id,
        quando=db.agora(),
        tipo=servico.TIPO_REDEFINICAO,
        alvo=usuario_id,
    )
    return _tela_admin(request, conn, usuario, link=f"/convite/{token}")


@ROTEADOR.post("/admin/ativo/{usuario_id}", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def mudar_ativo(
    request: Request,
    usuario_id: int,
    ativo: str = Form(...),
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    if usuario_id == usuario.id:
        return _tela_admin(
            request,
            conn,
            usuario,
            erro="You cannot disable your own account.",
        )
    if repo.usuario_por_id(conn, usuario_id) is None:
        # Sem isto, "sucesso" é um UPDATE que não bateu em linha nenhuma.
        return HTMLResponse("User not found.", status_code=404)
    ligado = ativo == "1"
    repo.definir_ativo(conn, usuario_id, ligado)
    if not ligado:
        # Desativar sem derrubar a sessão deixaria a pessoa dentro por
        # mais 30 dias.
        repo.apagar_sessoes_do_usuario(conn, usuario_id)
    return _tela_admin(request, conn, usuario)


_JA_RESOLVIDO = "This request was already resolved."


@ROTEADOR.post("/admin/pedido/{pedido_id}/convidar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def convidar_pedido(
    request: Request,
    pedido_id: int,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    try:
        token = pedidos.convidar_pedido(
            conn, pedido_id, admin_id=usuario.id, quando=db.agora()
        )
    except pedidos.PedidoJaResolvido:
        return _tela_admin(request, conn, usuario, erro=_JA_RESOLVIDO)
    # O token em claro existe só aqui, como em `gerar_convite`.
    return _tela_admin(request, conn, usuario, link=f"/convite/{token}")


@ROTEADOR.post("/admin/pedido/{pedido_id}/descartar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def descartar_pedido(
    request: Request,
    pedido_id: int,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    try:
        pedidos.descartar_pedido(conn, pedido_id, quando=db.agora())
    except pedidos.PedidoJaResolvido:
        return _tela_admin(request, conn, usuario, erro=_JA_RESOLVIDO)
    return _tela_admin(request, conn, usuario)


@ROTEADOR.post("/admin/varredura", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def salvar_varredura(
    request: Request,
    ligada: str = Form(""),
    intervalo_min: str = Form(""),
    idade_max_funda_h: str = Form(""),
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    # Texto, e não `int` no Form: um valor inválido tem de voltar como
    # mensagem na tela do admin, não como o 422 cru do FastAPI.
    try:
        config = varredura_repo.Config(
            ligada=ligada == "1",
            intervalo_min=int(intervalo_min),
            idade_max_funda_h=int(idade_max_funda_h),
        )
    except ValueError:
        return _tela_admin(request, conn, usuario, erro="Scanner settings must be whole numbers.")
    if config.intervalo_min < varredura_repo.INTERVALO_MINIMO_MIN:
        return _tela_admin(
            request, conn, usuario,
            erro=f"The interval must be at least {varredura_repo.INTERVALO_MINIMO_MIN} minutes.",
        )
    if config.idade_max_funda_h < varredura_repo.IDADE_MINIMA_FUNDA_H:
        return _tela_admin(request, conn, usuario, erro="The re-read age must be at least 1 hour.")
    varredura_repo.gravar_config(conn, config, db.agora())
    return _tela_admin(request, conn, usuario, varredura_msg="Scanner settings saved.")


@ROTEADOR.post("/admin/varredura/rodar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def rodar_varredura(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    agendador = request.app.state.agendador
    if agendador is None:
        return _tela_admin(request, conn, usuario,
                           erro="The scanner is not available in this process.")
    if not agendador.disparar_em_segundo_plano():
        return _tela_admin(request, conn, usuario, erro="A scan is already running.")
    return _tela_admin(request, conn, usuario, varredura_msg="Scan started.")
