from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import RAZAO_SEM_PRECO
from tf2price.painel.app import criar_app
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import PageListing
from tf2price.varredura import repositorio as repo

from .conftest import _contexto, cliente_logado

NOME = "Unusual Team Captain"


def _indice(dias=10):
    # CHAVE do conftest é R$ 11,73: 100 chaves = R$ 1.173,00.
    return PriceIndex.from_payload({"response": {"items": {
        "Team Captain": {"prices": {"5": {"Tradable": {"Craftable": {
            "13": {"currency": "keys", "value": 100.0, "last_update": int(time.time()) - dias * 86400},
        }}}}},
    }}}, key_in_refined=64.11)


def _semear(engine, listagens, n_listagens=None, nome=NOME):
    quando = db.agora()
    with engine.begin() as conn:
        repo.gravar_vista(conn, nome, 1000, n_listagens or len(listagens), quando)
        repo.substituir_listagens(
            conn, nome, [PageListing(i, Brl(c), e, None) for i, c, e in listagens], quando
        )


def test_sem_sessao_vai_para_entrar(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    assert cliente.get("/scan").status_code == 303


def test_mostra_cada_listagem_e_o_resultado(engine):
    _semear(engine, [("1", 80000, "Burning Flames"), ("2", 150000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan").text

    assert NOME in texto
    assert "R$ 800,00" in texto and "R$ 1.500,00" in texto
    assert "R$ 373,00" in texto       # 1.173 - 800
    assert "R$ -327,00" in texto      # 1.173 - 1.500
    assert 'href="/scan"' in texto and "Market Scan" in texto


def test_aba_profitable_so_mostra_lucro(engine):
    _semear(engine, [("1", 80000, "Burning Flames"), ("2", 150000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan", params={"aba": "lucro"}).text

    assert "R$ 800,00" in texto
    assert "R$ 1.500,00" not in texto


def test_efeito_sem_preco_nao_herda_de_outro_efeito(engine):
    _semear(engine, [("1", 100, "Sunbeams")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    todas = cliente.get("/scan").text
    lucro = cliente.get("/scan", params={"aba": "lucro"}).text

    assert RAZAO_SEM_PRECO in todas
    assert "Sunbeams" not in lucro.split('id="scan-tabela"')[1]


def test_preco_velho_fica_fora_do_lucro_pelo_filtro_padrao(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice(dias=200)))

    padrao = cliente.get("/scan", params={"aba": "lucro"}).text
    sem_limite = cliente.get("/scan", params={"aba": "lucro", "idade_max": ""}).text

    assert "No listings match these filters." in padrao
    assert "R$ 373,00" in sem_limite


def test_mais_listagens_na_steam(engine):
    _semear(engine, [("1", 80000, "Burning Flames")], n_listagens=13)
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    assert "+12 more on Steam" in cliente.get("/scan").text


def test_htmx_recebe_so_a_tabela(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    parcial = cliente.get("/scan", headers={"HX-Request": "true"}).text

    assert "<!doctype" not in parcial.lower()
    assert "R$ 800,00" in parcial


def test_estado_sem_varredura_ainda(engine):
    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/scan").text
    assert "No full scan yet" in texto
    assert "Scanner is off" in texto
