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


def test_abrir_acompanhado_com_efeito_a_venda_preenche_efeito_e_avaliacao(engine):
    """Reproduz o clique num acompanhado: os dois blocos têm que fechar juntos.

    Antes da correção o botão chamava `/analise` e pulava `/efeitos`; a
    avaliação vinha certa, mas o bloco EFEITO continuava dizendo "aguardando
    item" — a tela se contradizendo.
    """
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Deep Dive"})

    assert r.status_code == 200
    assert "aguardando item" not in r.text
    assert "aguardando efeito" not in r.text
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text
    assert "180,44" in r.text  # listagem mais barata do efeito, de _analise.html
    assert 'id="analise"' in r.text and 'hx-swap-oob="true"' in r.text
    # o efeito aberto fica marcado na lista, e só ele
    assert r.text.count('class="escolhido"') == 1


def test_abrir_acompanhado_com_efeito_sumido_mostra_lista_e_avisa_ausencia(engine):
    """O efeito acompanhado pode não estar mais à venda nesta página.

    A lista de efeitos tem que aparecer normal, e a avaliação tem que avisar
    a ausência — nunca mostrar o preço de outro efeito no lugar: o mesmo
    chapéu com outro efeito vale outra ordem de grandeza.
    """
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Burning Flames"})

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Burning Flames"})

    assert r.status_code == 200
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text
    assert "sem listagem deste efeito agora" in r.text
    assert "180,44" not in r.text  # preço de Deep Dive não pode aparecer no lugar
