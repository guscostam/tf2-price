from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam_page import (
    ItemPage,
    PageStructureError,
    SteamPageClient,
    parse_item_page,
    parse_page_price,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"
NOME = "Unusual Taunt: Chairholder"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def pagina() -> ItemPage:
    # Taxa 1.0 onde o teste não é sobre moeda: a conversão vira no-op e as
    # asserções mantêm os valores originais.
    return parse_item_page(_html(), NOME, 1.0)


# --- preço em formato en-US, diferente do priceoverview ------------------


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("R$124.52", 12452),
        ("R$1,880.07", 188007),
        ("R$0.99", 99),
        ("R$12,345,678.90", 1234567890),
        ("R$1234.56", 123456),
    ],
)
def test_parse_page_price(texto, centavos):
    assert parse_page_price(texto) == Brl.from_cents(centavos)


@pytest.mark.parametrize(
    "texto",
    [
        "R$ 1.234,50",
        "R$32,25",
        "R$999,99",
        "R$1,88",
        "sob consulta",
    ],
)
def test_parse_page_price_recusa_formato_ptbr(texto):
    """Ler 'R$32,25' (pt-BR) como en-US dá R$3.225,00 — 100x o valor, sem exceção.

    A validação precisa rodar antes de remover as vírgulas, senão a página
    de listagens (en-US) e o priceoverview (pt-BR) ficam indistinguíveis e
    esse erro de cem vezes passa batido.
    """
    with pytest.raises(PageStructureError):
        parse_page_price(texto)


# --- listagens -----------------------------------------------------------


def test_extrai_as_sete_listagens(pagina: ItemPage):
    assert len(pagina.listings) == 7
    assert pagina.hash_name == NOME


def test_listagem_mais_barata_tem_preco_e_efeito(pagina: ItemPage):
    barata = min(pagina.listings, key=lambda x: x.total_price)
    assert barata.total_price == Brl.from_cents(12452)
    assert barata.effect == "Midnight Whirlwind"
    assert barata.listing_id == "518632172291794014"


def test_efeitos_distintos_da_pagina(pagina: ItemPage):
    efeitos = {x.effect for x in pagina.listings}
    assert efeitos == {
        "Midnight Whirlwind",
        "Silver Cyclone",
        "Deep Dive",
        "Screaming Tiger",
    }


def test_o_mesmo_efeito_aparece_em_precos_diferentes(pagina: ItemPage):
    """Duas Deep Dive com preços distintos — é o sinal que o app procura."""
    deep = sorted(
        (x.total_price.cents for x in pagina.listings if x.effect == "Deep Dive")
    )
    assert len(deep) == 2
    assert deep[0] < deep[1]


# --- livro de ofertas ----------------------------------------------------


def test_livro_de_ofertas(pagina: ItemPage):
    ob = pagina.orderbook
    assert ob.max_buy_order == Brl.from_cents(10631)
    assert ob.min_sell_order == Brl.from_cents(12452)
    assert ob.buy_orders == 39
    assert ob.sell_orders == 7


# --- histórico -----------------------------------------------------------


def test_historico_de_vendas(pagina: ItemPage):
    assert len(pagina.history) == 102
    primeiro = pagina.history[0]
    assert primeiro.when > 0
    assert primeiro.purchases >= 1
    assert primeiro.median.cents > 0


# --- falhas de estrutura -------------------------------------------------


def test_pagina_sem_render_context_falha_com_mensagem_clara():
    with pytest.raises(PageStructureError, match="renderContext"):
        parse_item_page("<html><body>nada aqui</body></html>", NOME, 1.0)


def test_render_context_sem_query_esperada_falha_nomeando_qual():
    html = 'x<script>window.SSR.renderContext="{\\"queryData\\":\\"{}\\"}";</script>'
    with pytest.raises(PageStructureError, match="market_item_search"):
        parse_item_page(html, NOME, 1.0)


# --- cliente HTTP --------------------------------------------------------


def _cliente(corpo: str, capturadas: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capturadas is not None:
            capturadas.append(request)
        return httpx.Response(200, text=corpo, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_cliente_escapa_o_nome_e_pede_moeda_brl():
    capturadas: list[httpx.Request] = []
    cliente = SteamPageClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_html(), capturadas),
    )

    pagina = cliente.item_page(NOME, 1.0)

    assert len(pagina.listings) == 7
    url = str(capturadas[0].url)
    assert "Unusual%20Taunt%3A%20Chairholder" in url
    assert capturadas[0].url.params["currency"] == "7"
    assert capturadas[0].url.params["l"] == "english"


def test_cliente_repete_em_429_e_registra():
    respostas = [429, 200]
    corpo = _html()

    def handler(request: httpx.Request) -> httpx.Response:
        if respostas.pop(0) == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, text=corpo, headers={"content-type": "text/html"})

    limiter = RateLimiter(min_interval_s=0.0)
    cliente = SteamPageClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    assert len(cliente.item_page(NOME, 1.0).listings) == 7
    assert limiter.throttled == 1


# --- moeda declarada pelo payload ----------------------------------------
#
# Medido em 2026-09-20: a página de listagens IGNORA o parâmetro `currency`
# e alterna entre dólar e real de uma requisição para outra. `parse_page_price`
# só conhece o formato en-US, então '$1,746.01' entrava como R$ 1.746,01 —
# 5,15x menos que os R$ 8.999,99 reais do item. Cada parte do renderContext
# declara a sua moeda ao lado do valor; estes testes prendem essa leitura.


def _pagina_sintetica(
    *,
    moeda_listagem: int,
    moeda_livro: int,
    moeda_historico: int,
    subtotal: str = "$100.00",
    campo_listagem: str = "eCurrency",
) -> str:
    """HTML mínimo com o renderContext duplamente escapado da página real.

    Os escapes aninhados são construídos com `json.dumps` em vez de escritos
    à mão: assim o teste continua legível e não pode divergir da forma que a
    Valve serve — uma string JSON (o renderContext) que carrega outra string
    JSON (o queryData) dentro.
    """
    query_data = {
        "queries": [
            {
                "queryKey": ["market_item_search", NOME],
                "state": {
                    "data": {
                        "pages": [
                            {
                                "listings": [
                                    {
                                        "listingid": "1",
                                        "strSubtotal": subtotal,
                                        campo_listagem: moeda_listagem,
                                        "description": {
                                            "descriptions": [
                                                {"value": "Unusual Effect: Deep Dive"}
                                            ]
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                },
            },
            {
                "queryKey": ["orderbook", NOME],
                "state": {
                    "data": {
                        "eCurrency": moeda_livro,
                        "amtMaxBuyOrder": 5000,
                        "amtMinSellOrder": 10000,
                        "cBuyOrders": 3,
                        "cSellOrders": 2,
                    }
                },
            },
            {
                "queryKey": ["pricehistory", NOME],
                "state": {
                    "data": {
                        # Minúsculo no histórico, diferente das outras partes.
                        "ecurrency": moeda_historico,
                        "prices": [
                            {"time": 1_790_000_000, "price_median": 20.0, "purchases": 4}
                        ],
                    }
                },
            },
        ]
    }
    contexto = json.dumps({"queryData": json.dumps(query_data)})
    return f"<script>window.SSR.renderContext={json.dumps(contexto)};</script>"


def test_fixture_real_declara_brl_e_a_taxa_nao_a_toca():
    """A fixture veio em real: com taxa 5,15 o preço tem de continuar igual."""
    pagina = parse_item_page(_html(), NOME, 5.15)

    barata = min(pagina.listings, key=lambda x: x.total_price)
    assert barata.total_price == Brl.from_cents(12452)
    assert pagina.orderbook.max_buy_order == Brl.from_cents(10631)
    assert pagina.orderbook.min_sell_order == Brl.from_cents(12452)


def test_pagina_em_dolar_converte_as_tres_partes():
    html = _pagina_sintetica(moeda_listagem=1, moeda_livro=1, moeda_historico=1)

    pagina = parse_item_page(html, NOME, 5.0)

    # '$100.00' lido como real daria R$ 100,00; declarado em dólar, R$ 500,00.
    assert pagina.listings[0].total_price == Brl.from_cents(50_000)
    assert pagina.orderbook.max_buy_order == Brl.from_cents(25_000)
    assert pagina.orderbook.min_sell_order == Brl.from_cents(50_000)
    assert pagina.history[0].median == Brl.from_cents(10_000)


def test_listagem_em_moeda_desconhecida_levanta_com_o_codigo():
    html = _pagina_sintetica(moeda_listagem=23, moeda_livro=7, moeda_historico=7)

    with pytest.raises(PageStructureError, match="listagem veio na moeda 23"):
        parse_item_page(html, NOME, 5.0)


def test_livro_em_moeda_desconhecida_levanta_com_o_codigo():
    html = _pagina_sintetica(moeda_listagem=7, moeda_livro=23, moeda_historico=7)

    with pytest.raises(PageStructureError, match="livro de ofertas veio na moeda 23"):
        parse_item_page(html, NOME, 5.0)


def test_historico_em_moeda_desconhecida_levanta_com_o_codigo():
    html = _pagina_sintetica(moeda_listagem=7, moeda_livro=7, moeda_historico=23)

    with pytest.raises(PageStructureError, match="veio na moeda 23"):
        parse_item_page(html, NOME, 5.0)


def test_campo_de_moeda_ausente_levanta():
    """Sem o campo não há como saber a moeda — adivinhar é o bug de novo."""
    html = _pagina_sintetica(
        moeda_listagem=7,
        moeda_livro=7,
        moeda_historico=7,
        campo_listagem="naoEhMoeda",
    )

    with pytest.raises(PageStructureError, match="listagem veio na moeda None"):
        parse_item_page(html, NOME, 5.0)


def test_as_partes_sao_lidas_de_forma_independente():
    """Livro em dólar, listagens em real: só o livro converte.

    É o teste que pega quem depois "simplificar" lendo um campo de moeda só
    e aplicando o mesmo fator na página inteira.
    """
    html = _pagina_sintetica(
        moeda_listagem=7,
        moeda_livro=1,
        moeda_historico=7,
        subtotal="R$100.00",
    )

    pagina = parse_item_page(html, NOME, 5.0)

    assert pagina.listings[0].total_price == Brl.from_cents(10_000)
    assert pagina.orderbook.max_buy_order == Brl.from_cents(25_000)
    assert pagina.orderbook.min_sell_order == Brl.from_cents(50_000)
    assert pagina.history[0].median == Brl.from_cents(2_000)
