from __future__ import annotations

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
    return parse_item_page(_html(), NOME)


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
        parse_item_page("<html><body>nada aqui</body></html>", NOME)


def test_render_context_sem_query_esperada_falha_nomeando_qual():
    html = 'x<script>window.SSR.renderContext="{\\"queryData\\":\\"{}\\"}";</script>'
    with pytest.raises(PageStructureError, match="market_item_search"):
        parse_item_page(html, NOME)


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

    pagina = cliente.item_page(NOME)

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

    assert len(cliente.item_page(NOME).listings) == 7
    assert limiter.throttled == 1
