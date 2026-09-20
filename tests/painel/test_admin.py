from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico
from tf2price.painel.app import criar_app

SENHA = "uma senha longa"


def _entra(engine, nome, admin):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id if dono else None, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente


@pytest.fixture
def admin(engine):
    return _entra(engine, "gusco", admin=True)


def test_admin_lista_os_usuarios(admin, engine):
    _entra(engine, "amiga", admin=False)
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "gusco" in r.text and "amiga" in r.text


def test_nao_admin_leva_403(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    assert comum.get("/admin").status_code == 403


def test_sem_sessao_nao_chega_no_admin(engine):
    cliente = TestClient(criar_app(engine), follow_redirects=False)
    assert cliente.get("/admin").status_code == 303


def test_gerar_convite_mostra_o_link_uma_vez(admin):
    r = admin.post("/admin/convite")
    assert r.status_code == 200
    assert "/convite/" in r.text


def test_link_gerado_realmente_cria_conta(admin, engine):
    import re

    texto = admin.post("/admin/convite").text
    token = re.search(r"/convite/([A-Za-z0-9_\-]+)", texto).group(1)
    outro = TestClient(criar_app(engine), follow_redirects=False)
    r = outro.post(f"/convite/{token}", data={"nome": "amiga", "senha": SENHA})
    assert r.status_code == 303
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is not None


def test_redefinir_gera_link_para_aquele_usuario(admin, engine):
    _entra(engine, "amiga", admin=False)
    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    r = admin.post(f"/admin/redefinir/{alvo}")
    assert "/convite/" in r.text


def test_desativar_derruba_a_sessao_da_pessoa(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    assert comum.get("/admin").status_code == 403  # sessão viva

    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    admin.post(f"/admin/ativo/{alvo}", data={"ativo": "0"})

    comum.follow_redirects = False
    assert comum.get("/admin").status_code == 303  # sessão morta
