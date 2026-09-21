from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.acompanhamento import repositorio as repo
from tf2price.contas import repositorio as contas
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from .conftest import NOME, _contexto, cliente_logado

SENHA = "uma senha longa"


def test_acompanhar_guarda_e_aparece_na_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code == 200
    assert "Deep Dive" in r.text
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_acompanhar_duas_vezes_nao_duplica(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_remover_tira_da_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
    r = cliente.delete(f"/acompanhar/{ident}")
    assert r.status_code == 200
    with engine.begin() as conn:
        assert repo.listar(conn, eu.id) == []


def test_ninguem_remove_o_item_de_outra_pessoa_pela_rota(engine):
    """O isolamento tem de valer na rota, não só no repositório."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
        # uma segunda pessoa, com sessão própria
        token = servico.convidar(conn, criado_por=eu.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome="outra", senha=SENHA, quando=db.agora())

    outro = TestClient(criar_app(engine, _contexto()))
    outro.post("/entrar", data={"nome": "outra", "senha": SENHA})
    r = outro.delete(f"/acompanhar/{ident}")

    assert r.status_code in (404, 200)
    with engine.begin() as conn:
        assert len(repo.listar(conn, eu.id)) == 1


def test_acompanhar_exige_sessao(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code in (303, 401)


def test_item_sem_retrato_diz_que_nao_ha_dado_ainda(engine):
    """Acompanhar um item nunca aberto não pode deixar a linha em branco."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": "Unusual Chapeu Nunca Aberto", "efeito": "Smoking"})
    assert "sem dado ainda" in cliente.get("/").text
