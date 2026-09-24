from __future__ import annotations

import time
from decimal import Decimal

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import RAZAO_SEM_PRECO
from tf2price.painel.app import criar_app
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import PageListing
from tf2price.varredura import repositorio as repo
from tf2price.varredura import vendas_repo

from .conftest import USD_DO_TESTE, _contexto, cliente_logado

NOME = "Unusual Team Captain"


def _indice(dias=10):
    # CHAVE do conftest é R$ 11,73: 100 chaves = R$ 1.173,00.
    return PriceIndex.from_payload({"response": {"items": {
        "Team Captain": {"prices": {"5": {"Tradable": {"Craftable": {
            "13": {"currency": "keys", "value": 100.0, "last_update": int(time.time()) - dias * 86400},
        }}}}},
    }, **USD_DO_TESTE}}, key_in_refined=64.11)


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


def test_restauracao_do_historico_recebe_a_pagina_inteira(engine):
    # Com hx-push-url, o htmx 1.9 sem cache do histórico pede a URL de novo
    # com HX-Request E HX-History-Restore-Request, e troca o <body> inteiro:
    # a tabela sozinha apagaria cabeçalho, navegação e filtros.
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan", headers={
        "HX-Request": "true", "HX-History-Restore-Request": "true",
    }).text

    assert "<!doctype" in texto.lower()
    assert 'href="/scan"' in texto and "Market Scan" in texto
    assert "R$ 800,00" in texto


def test_pagina_e_parcial_variam_pelo_cabecalho_do_htmx(engine):
    # Sem Vary, o Voltar do navegador pode servir o fragmento em cache no
    # lugar da página inteira.
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    inteira = cliente.get("/scan")
    parcial = cliente.get("/scan", headers={"HX-Request": "true"})

    assert "HX-Request" in inteira.headers.get("vary", "")
    assert "HX-Request" in parcial.headers.get("vary", "")


def test_estado_sem_varredura_ainda(engine):
    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/scan").text
    assert "No full scan yet" in texto
    assert "Scanner is off" in texto


def _rodada_fechada(engine, motivo):
    quando = db.agora()
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, quando)
        repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=motivo)


def test_aviso_de_429_so_quando_a_ultima_rodada_parou_por_429(engine):
    aviso = "stopped because Steam is rate limiting"
    _rodada_fechada(engine, repo.MOTIVO_429)
    cliente = cliente_logado(engine, _contexto(indice=_indice()))
    assert aviso in cliente.get("/scan").text

    _rodada_fechada(engine, repo.MOTIVO_OK)
    assert aviso not in cliente.get("/scan").text


def test_sem_referencia_o_scan_diz_e_esconde_o_resultado(engine):
    from .conftest import _PtaxFalsa

    _semear(engine, [("1", 80000, "Burning Flames")])
    ctx = _contexto(indice=_indice())
    ctx.ptax = _PtaxFalsa(None)
    cliente = cliente_logado(engine, ctx)

    texto = cliente.get("/scan").text

    assert "PTAX dollar rate" in texto
    assert "R$ 373,00" not in texto


def test_o_cabecalho_do_scan_diz_qual_chave_usa(engine):
    cliente = cliente_logado(engine, _contexto(indice=_indice()))
    assert "× reference key price" in cliente.get("/scan").text


def test_scan_distingue_preco_sugerido_de_vendas_ativas(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan").text

    assert "Below suggested price" in texto
    assert "Suggested backpack.tf price" in texto
    assert "Guide gap" in texto
    assert "A suggested price is not a buyer offer" in texto
    assert "View sellers" in texto
    assert "item=Team+Captain" in texto and "particle=13" in texto
    assert "Profitable" not in texto


def test_scan_mostra_potencial_de_revenda_com_estado_indisponivel_sem_cache(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan").text

    assert "Potential resale" in texto
    assert "Lowest observed seller ask" in texto
    assert "Unavailable" in texto
    assert "A seller ask does not guarantee a buyer" in texto


def test_venda_ativa_define_potencial_sem_substituir_preco_sugerido(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    with engine.begin() as conn:
        vendas_repo.gravar_sucesso(
            conn, NOME, "Burning Flames", Decimal("120"), Decimal("0"), db.agora(),
            metal_por_chave=Decimal("64.11"),
        )
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan", params={"aba": "revenda"}).text

    assert "R$ 1.407,60" in texto  # menor pedido observado, 120 × R$ 11,73
    assert "R$ 607,60" in texto  # potencial, 1.407,60 − 800,00
    assert "R$ 1.173,00" in texto  # sugestão independente, 100 × R$ 11,73
    assert "R$ 373,00" in texto  # guide gap independente


def test_aba_revenda_nao_usa_guia_quando_venda_indisponivel(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    assert "No listings match these filters." in cliente.get("/scan", params={"aba": "revenda"}).text
    assert "R$ 373,00" in cliente.get("/scan", params={"aba": "lucro"}).text
