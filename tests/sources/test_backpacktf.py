from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.sources.backpacktf import (
    BackpackTfClient,
    Currencies,
    PriceIndex,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
KEY_IN_REFINED = 69.44


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def index() -> PriceIndex:
    return PriceIndex.from_payload(_fixture("bptf_prices.json"), KEY_IN_REFINED)


# --- moedas --------------------------------------------------------------


def test_currencies_le_chave_em_refined_e_em_usd():
    currencies = Currencies.from_payload(_fixture("bptf_currencies.json"))
    assert currencies.key_in_refined == pytest.approx(69.44)
    assert currencies.key_in_usd == pytest.approx(2.52)


# --- a esquisitice lista vs dicionário -----------------------------------


def test_entries_le_o_formato_lista(index: PriceIndex):
    entries = index.entries("Rocket Launcher", 6)
    assert len(entries) == 2
    assert {e.craftable for e in entries} == {True, False}
    assert all(e.priceindex is None for e in entries)


def test_entries_le_o_formato_dicionario_com_priceindex(index: PriceIndex):
    entries = index.entries("Team Captain", 5)
    assert {e.priceindex for e in entries} == {"13", "17", "701"}
    assert all(e.craftable for e in entries)


def test_entries_de_item_inexistente_e_vazio(index: PriceIndex):
    assert index.entries("Item Que Não Existe", 6) == []


def test_entries_de_qualidade_inexistente_e_vazio(index: PriceIndex):
    assert index.entries("Team Captain", 11) == []


# --- conversão para chaves -----------------------------------------------


def test_to_keys_mantem_valor_ja_em_chaves(index: PriceIndex):
    price = index.lookup("Team Captain", 5, priceindex="13")
    assert index.to_keys(price) == pytest.approx(28.0)


def test_to_keys_converte_metal_pela_taxa(index: PriceIndex):
    price = index.lookup("Rocket Launcher", 6)
    assert index.to_keys(price) == pytest.approx(0.11 / KEY_IN_REFINED)


def test_to_keys_recusa_usd(index: PriceIndex):
    """USD não é convertido de propósito: é o sinal candidato da guarda 4."""
    price = index.lookup("Mildly Disturbing Halloween Mask", 6)
    assert price.currency == "usd"
    assert index.to_keys(price) is None


# --- lookup --------------------------------------------------------------


def test_lookup_por_priceindex(index: PriceIndex):
    assert index.lookup("Team Captain", 5, priceindex="701").value == pytest.approx(45.0)


def test_lookup_respeita_craftabilidade(index: PriceIndex):
    craftable = index.lookup("Rocket Launcher", 6, craftable=True)
    non_craftable = index.lookup("Rocket Launcher", 6, craftable=False)
    assert craftable.value == pytest.approx(0.11)
    assert non_craftable.value == pytest.approx(0.05)


def test_lookup_ausente_devolve_none(index: PriceIndex):
    assert index.lookup("Team Captain", 5, priceindex="9999") is None


# --- faixa de valor ------------------------------------------------------


def test_value_range_cobre_todos_os_efeitos(index: PriceIndex):
    faixa = index.value_range_keys("Team Captain", 5)
    assert faixa.min_keys == pytest.approx(9.0)
    assert faixa.max_keys == pytest.approx(45.0)


def test_value_range_cobre_craftavel_e_nao_craftavel(index: PriceIndex):
    faixa = index.value_range_keys("Rocket Launcher", 6)
    assert faixa.min_keys == pytest.approx(0.05 / KEY_IN_REFINED)
    assert faixa.max_keys == pytest.approx(0.11 / KEY_IN_REFINED)


def test_value_range_de_item_so_em_usd_e_none(index: PriceIndex):
    assert index.value_range_keys("Mildly Disturbing Halloween Mask", 6) is None


def test_value_range_de_item_inexistente_e_none(index: PriceIndex):
    assert index.value_range_keys("Item Que Não Existe", 6) is None


def test_item_names(index: PriceIndex):
    assert "Team Captain" in index.item_names()
    assert len(index.item_names()) == 3


# --- cliente HTTP --------------------------------------------------------


def test_cliente_envia_a_api_key_e_o_appid():
    capturadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(200, json=_fixture("bptf_prices.json"))

    client = BackpackTfClient(
        api_key="CHAVE_DE_TESTE",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.prices_payload()

    params = capturadas[0].url.params
    assert params["key"] == "CHAVE_DE_TESTE"
    assert params["appid"] == "440"


def test_cliente_devolve_currencies_tipado():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fixture("bptf_currencies.json"))

    client = BackpackTfClient(
        api_key="CHAVE_DE_TESTE",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.currencies().key_in_refined == pytest.approx(69.44)
