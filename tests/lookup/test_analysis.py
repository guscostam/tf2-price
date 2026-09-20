from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import ItemPage, OrderBook, parse_item_page
from tf2price.lookup.analysis import (
    Analysis,
    analyse,
    effects_available,
    immediate_exit,
    listings_of,
    net_after_fee,
    patient_exit,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EFEITOS = FIXTURES / "effects_sample.json"
NOME = "Unusual Taunt: Chairholder"
CHAVE = Brl.from_float(11.73)
AGORA = 1_790_000_000


@pytest.fixture
def pagina() -> ItemPage:
    html = (FIXTURES / "steam_listing_page.html").read_text(encoding="utf-8")
    return parse_item_page(html, NOME)


def _indice(entradas: dict) -> PriceIndex:
    """PriceIndex minúsculo construído em linha, sem tocar as fixtures da bp.tf."""
    return PriceIndex.from_payload({"response": {"items": entradas}}, key_in_refined=64.11)


# --- taxa ----------------------------------------------------------------


def test_net_after_fee_desfaz_os_15_por_cento():
    # observado na página: 124,52 ao comprador, 16,23 de taxa, 108,29 ao vendedor
    assert net_after_fee(Brl.from_cents(12452)) == Brl.from_cents(10828)


def test_net_after_fee_nao_aplica_a_taxa_duas_vezes():
    uma = net_after_fee(Brl.from_cents(10000))
    assert uma.cents > 8000  # 1/1,15 e não 0,85 x 0,85


# --- efeitos e listagens por efeito --------------------------------------


def test_efeitos_disponiveis_sao_os_que_tem_listagem(pagina: ItemPage):
    assert effects_available(pagina) == [
        "Deep Dive",
        "Midnight Whirlwind",
        "Screaming Tiger",
        "Silver Cyclone",
    ]


def test_listagens_do_efeito_vem_ordenadas(pagina: ItemPage):
    deep = listings_of(pagina, "Deep Dive")
    assert len(deep) == 2
    assert deep[0].total_price < deep[1].total_price
    assert all(x.effect == "Deep Dive" for x in deep)


def test_efeito_inexistente_devolve_lista_vazia(pagina: ItemPage):
    assert listings_of(pagina, "Burning Flames") == []


# --- saída imediata ------------------------------------------------------


def test_saida_imediata_no_caso_real(pagina: ItemPage):
    """Comprar a 124,52 e vender já para a oferta de 106,31 dá prejuízo."""
    r = immediate_exit(Brl.from_cents(12452), pagina.orderbook)
    assert r.top_bid == Brl.from_cents(10631)
    assert r.net_received == Brl.from_cents(9244)
    assert r.result == Brl.from_cents(-3208)
    assert r.buy_orders == 39


def test_saida_imediata_positiva_e_arbitragem_dura():
    """Listagem abaixo do que a melhor oferta paga líquido: lucro sem troca."""
    livro = OrderBook(
        max_buy_order=Brl.from_cents(20000),
        min_sell_order=Brl.from_cents(10000),
        buy_orders=5,
        sell_orders=2,
    )
    r = immediate_exit(Brl.from_cents(10000), livro)
    assert r.net_received == Brl.from_cents(17391)
    assert r.result.cents > 0


def test_saida_imediata_sem_ofertas_de_compra():
    livro = OrderBook(max_buy_order=None, min_sell_order=None, buy_orders=0, sell_orders=0)
    r = immediate_exit(Brl.from_cents(10000), livro)
    assert r.top_bid is None
    assert r.net_received is None
    assert r.result is None


# --- saída paciente ------------------------------------------------------


def test_saida_paciente_indisponivel_quando_a_bptf_nao_precifica_o_efeito():
    """O caso real do Chairholder: nenhum efeito à venda tem preço na bp.tf."""
    idx = _indice({"Taunt: Chairholder": {"prices": {"5": {"Tradable": {"Craftable": {
        "9999": {"currency": "keys", "value": 24.0, "last_update": AGORA - 86400}
    }}}}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Burning Flames", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is False
    assert r.reason
    assert r.fair_value is None
    assert r.result is None


def test_saida_paciente_indisponivel_quando_o_efeito_nao_esta_no_mapa():
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Efeito Que Nao Existe", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is False
    assert r.reason


def test_saida_paciente_disponivel_traz_valor_e_idade():
    # Burning Flames = 13 na fixture de efeitos
    idx = _indice({"Taunt: Chairholder": {"prices": {"5": {"Tradable": {"Craftable": {
        "13": {"currency": "keys", "value": 20.0, "last_update": AGORA - 60 * 86400}
    }}}}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Burning Flames", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is True
    assert r.keys == pytest.approx(20.0)
    assert r.fair_value == Brl.from_cents(23460)   # 20 x 11,73
    assert r.result == Brl.from_cents(11008)
    assert r.age_days == 60


# --- análise completa ----------------------------------------------------


def test_analise_usa_a_listagem_mais_barata_do_efeito(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.effect == "Deep Dive"
    assert a.cheapest.total_price == Brl.from_cents(18044)
    assert len(a.listings) == 2


def test_analise_repassa_livro_e_historico_sem_transformar(pagina: ItemPage):
    """Regra do spec §4: são dados POR ITEM e não podem ser filtrados por efeito.

    Se alguém um dia filtrar o livro ou o histórico pelo efeito escolhido,
    estará inventando um dado que a Steam não fornece — que é exatamente o
    erro que invalidou o projeto anterior.
    """
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.orderbook == pagina.orderbook
    assert a.history == pagina.history
    assert a.history_purchases == sum(p.purchases for p in pagina.history)


def test_analise_converte_para_chaves(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.price_in_keys == pytest.approx(180.44 / 11.73, rel=1e-3)


def test_analise_de_efeito_sem_listagem_levanta(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    with pytest.raises(ValueError, match="Burning Flames"):
        analyse(pagina, "Burning Flames", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
