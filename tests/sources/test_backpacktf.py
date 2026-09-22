from __future__ import annotations

import json
from datetime import datetime, timezone
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


def test_currencies_le_chave_em_refined():
    currencies = Currencies.from_payload(_fixture("bptf_currencies.json"))
    assert currencies.key_in_refined == pytest.approx(69.44)


# --- dólar da chave --------------------------------------------------------


def test_key_in_usd_e_o_dolar_do_refined_vezes_a_chave(index: PriceIndex):
    # A fixture traz raw_usd_value 0.0363 por refined, e a chave vale 69.44 ref.
    assert index.key_in_usd() == pytest.approx(0.0363 * 69.44)


def _indice_com(extra: dict) -> PriceIndex:
    return PriceIndex.from_payload({"response": {"items": {}, **extra}}, 64.11)


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"raw_usd_value": 0.026},
        {"raw_usd_value": 0, "usd_currency": "metal"},
        {"raw_usd_value": -1, "usd_currency": "metal"},
        {"raw_usd_value": "abc", "usd_currency": "metal"},
        {"raw_usd_value": 0.026, "usd_currency": "keys"},
    ],
)
def test_key_in_usd_recusa_o_que_nao_sabe_ler(extra):
    """Moeda inesperada ou valor ruim é recusa, não conta errada."""
    assert _indice_com(extra).key_in_usd() is None


def test_valor_ruim_de_dolar_nao_derruba_o_indice():
    """O índice inteiro não pode sumir por causa do campo de dólar."""
    idx = _indice_com({"raw_usd_value": "abc", "usd_currency": "metal"})
    assert idx.item_names() == set()


def test_carregado_em_e_quem_carregou_que_diz():
    quando = datetime(2026, 9, 22, 12, 0)
    idx = PriceIndex.from_payload({"response": {"items": {}}}, 64.11, carregado_em=quando)
    assert idx.carregado_em == quando


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_carregado_em_padrao_e_agora():
    antes = _agora()
    idx = PriceIndex.from_payload({"response": {"items": {}}}, 64.11)
    assert antes <= idx.carregado_em <= _agora()


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


def test_lookup_sem_priceindex_nao_devolve_variante(index: PriceIndex):
    """Pedir o preço sem variante de um item que só tem variantes devolve None.

    Se o guard que ignora entradas com priceindex sumir, esta chamada passaria
    a devolver o preço de um efeito de Unusual arbitrário — erro de ordens de
    magnitude, e silencioso.
    """
    assert index.lookup("Team Captain", 5) is None


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
