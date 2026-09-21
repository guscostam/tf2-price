from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.preco import serial
from tf2price.sources.steam_page import (
    ItemPage,
    OrderBook,
    PageListing,
    SalePoint,
    parse_item_page,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"


def _pagina_real() -> ItemPage:
    return parse_item_page(FIXTURE.read_text(encoding="utf-8"), "Unusual Taunt: Chairholder", 1.0)


def test_ida_e_volta_devolve_a_mesma_pagina():
    """Se a volta não for idêntica, o retrato guardado mente sobre a Steam."""
    original = _pagina_real()
    assert serial.de_dict(serial.para_dict(original)) == original


def test_ida_e_volta_preserva_centavos_exatos():
    """Dinheiro é inteiro em centavos; um float no meio do caminho arredonda."""
    original = _pagina_real()
    volta = serial.de_dict(serial.para_dict(original))
    assert volta.listings[0].total_price.cents == original.listings[0].total_price.cents


def test_ida_e_volta_com_campos_ausentes():
    """Livro vazio e listagem sem efeito nem ícone são casos reais."""
    pagina = ItemPage(
        hash_name="Unusual Team Captain",
        listings=[PageListing(listing_id="1", total_price=Brl(100), effect=None, icon_url=None)],
        orderbook=OrderBook(max_buy_order=None, min_sell_order=None, buy_orders=0, sell_orders=0),
        history=[],
    )
    assert serial.de_dict(serial.para_dict(pagina)) == pagina


def test_o_dicionario_e_serializavel_em_json():
    import json

    texto = json.dumps(serial.para_dict(_pagina_real()))
    assert serial.de_dict(json.loads(texto)) == _pagina_real()


def test_versao_desconhecida_e_recusada():
    """Mudar a forma do retrato sem migrar os guardados seria ler lixo."""
    with pytest.raises(ValueError, match="versão"):
        serial.de_dict({"versao": 999, "hash_name": "x", "listings": [], "orderbook": {}, "history": []})
