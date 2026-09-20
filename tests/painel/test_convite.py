from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

SENHA = "uma senha longa"


@pytest.fixture
def cliente(engine):
    return TestClient(criar_app(engine), follow_redirects=False)


def _convite(engine, **kwargs) -> str:
    with engine.begin() as conn:
        dono = repo.criar_usuario(
            conn, nome="dono", senha_hash="hash", admin=True, quando=db.agora()
        )
        return servico.convidar(conn, criado_por=dono, quando=db.agora(), **kwargs)


def test_link_valido_mostra_o_formulario(cliente, engine):
    token = _convite(engine)
    r = cliente.get(f"/convite/{token}")
    assert r.status_code == 200
    assert "senha" in r.text.lower()


def test_link_invalido_diz_a_mesma_coisa_que_o_expirado(cliente, engine):
    """Distinguir os dois conta a quem está adivinhando token."""
    inexistente = cliente.get("/convite/token-inventado")
    assert inexistente.status_code == 404

    token = _convite(engine)
    with engine.begin() as conn:
        repo.marcar_convite_usado(
            conn, tokens.hash_de(token), usado_em=db.agora(), usado_por=1
        )
    usado = cliente.get(f"/convite/{token}")
    assert usado.status_code == 404
    assert usado.text == inexistente.text


def test_aceitar_cria_a_conta_e_ja_entra(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "amiga", "senha": SENHA})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert cliente.cookies.get(NOME_COOKIE)
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is not None


def test_senha_curta_volta_com_recado_e_nao_cria_conta(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "amiga", "senha": "curta"})
    assert r.status_code == 200
    assert "10" in r.text
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is None


def test_nome_em_uso_volta_com_recado(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "dono", "senha": SENHA})
    assert r.status_code == 200
    assert "uso" in r.text.lower()


def test_convite_de_redefinicao_troca_a_senha(cliente, engine):
    with engine.begin() as conn:
        dono = repo.criar_usuario(
            conn, nome="dono", senha_hash="hash", admin=True, quando=db.agora()
        )
        conta = servico.convidar(conn, criado_por=dono, quando=db.agora())
        usuario = servico.aceitar_convite(
            conn, conta, nome="amiga", senha=SENHA, quando=db.agora()
        )
        token = servico.convidar(
            conn, criado_por=dono, quando=db.agora(),
            tipo=servico.TIPO_REDEFINICAO, alvo=usuario.id,
        )

    r = cliente.get(f"/convite/{token}")
    assert "nova senha" in r.text.lower()

    r = cliente.post(f"/convite/{token}", data={"senha": "senha novinha"})
    assert r.status_code == 303

    entrou = cliente.post("/entrar", data={"nome": "amiga", "senha": "senha novinha"})
    assert entrou.status_code == 303
