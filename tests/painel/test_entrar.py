from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

from .conftest import _contexto

SENHA = "uma senha longa"


@pytest.fixture
def cliente(engine):
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
        servico.aceitar_convite(conn, token, nome="gusco", senha=SENHA, quando=db.agora())
    return TestClient(criar_app(engine, _contexto()), follow_redirects=False)


def test_entrar_mostra_o_formulario(cliente):
    r = cliente.get("/entrar")
    assert r.status_code == 200
    assert "senha" in r.text.lower()


def test_entrar_com_senha_certa_cria_cookie_e_redireciona(cliente):
    r = cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert cliente.cookies.get(NOME_COOKIE)


def test_entrar_com_senha_errada_nao_cria_cookie(cliente):
    r = cliente.post("/entrar", data={"nome": "gusco", "senha": "errada demais"})
    assert r.status_code == 200
    assert "nome ou senha" in r.text.lower()
    assert cliente.cookies.get(NOME_COOKIE) is None


def test_painel_sem_cookie_manda_para_entrar(cliente):
    r = cliente.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/entrar"


def test_fragmento_htmx_sem_cookie_devolve_401_com_redirecionamento(cliente):
    """Um 303 dentro de fragmento seria engolido pelo swap do HTMX.

    O navegador só sai da página quando o HTMX vê HX-Redirect.
    """
    r = cliente.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/entrar"


def test_com_cookie_o_painel_abre(cliente):
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    r = cliente.get("/")
    assert r.status_code == 200
    assert "gusco" in r.text


def test_sair_apaga_a_sessao(cliente):
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    r = cliente.post("/sair")
    assert r.status_code == 303
    assert cliente.get("/").status_code == 303


def test_post_de_outra_origem_e_recusado(cliente):
    """SameSite=Lax já barra o navegador; isto barra o resto."""
    r = cliente.post(
        "/entrar",
        data={"nome": "gusco", "senha": SENHA},
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
