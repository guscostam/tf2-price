from __future__ import annotations

import json
from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import Guard
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam import Listing, SearchResult
from tf2price.spike.pipeline import (
    deep_targets,
    guaranteed_opportunities,
    resolve_deep,
    shallow_pass,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EFEITOS = FIXTURES / "effects_sample.json"
KEY_IN_REFINED = 69.44
CHAVE = Brl.from_float(22.00)
AGORA = 1_760_000_000


@pytest.fixture
def index() -> PriceIndex:
    payload = json.loads((FIXTURES / "bptf_prices.json").read_text(encoding="utf-8"))
    return PriceIndex.from_payload(payload, KEY_IN_REFINED)


def _resultado(hash_name: str, reais: float, listings: int = 5) -> SearchResult:
    return SearchResult(
        hash_name=hash_name,
        lowest_price=Brl.from_float(reais),
        sell_listings=listings,
    )


# --- passada rasa --------------------------------------------------------


def test_nome_sem_correspondencia_vai_para_unmatched(index: PriceIndex):
    saida = shallow_pass([_resultado("Item Inexistente", 10.0)], index, CHAVE, 0.15)
    assert saida.candidates == []
    assert saida.unmatched == ["Item Inexistente"]


def test_unusual_barato_e_candidata(index: PriceIndex):
    # Team Captain Unusual: faixa de 9 a 45 chaves = R$ 198 a R$ 990.
    # Piso com limiar 15% = R$ 168,30. Teto = R$ 841,50.
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.CANDIDATE


def test_unusual_muito_barato_e_garantida(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.GUARANTEED


def test_unusual_caro_e_descartada(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 950.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.DISCARDED


def test_resolve_nome_com_australium_pela_lista_de_candidatos(index: PriceIndex):
    """'Strange Australium Rocket Launcher' cai em 'Rocket Launcher' quality 11
    depois que a variante Australium não existe no índice."""
    saida = shallow_pass(
        [_resultado("Strange Australium Rocket Launcher", 1.0)], index, CHAVE, 0.15
    )
    assert saida.candidates[0].bptf_name == "Rocket Launcher"
    assert saida.candidates[0].identity.quality_id == 11


def test_item_so_em_usd_nao_gera_candidata(index: PriceIndex):
    """Sem valor convertível para chaves não há faixa, e sem faixa não há poda."""
    saida = shallow_pass(
        [_resultado("Mildly Disturbing Halloween Mask", 1.0)], index, CHAVE, 0.15
    )
    assert saida.candidates == []
    assert saida.unmatched == ["Mildly Disturbing Halloween Mask"]


# --- garantidas ----------------------------------------------------------


def test_garantida_e_avaliada_pelo_pior_valor_da_faixa(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    oportunidades = guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA)

    assert len(oportunidades) == 1
    # pior efeito = 9 chaves = R$ 198, não os 45 chaves do melhor
    assert oportunidades[0].valuation.fair_value == Brl.from_float(198.00)
    assert oportunidades[0].deep_fetched is False
    assert oportunidades[0].guard is Guard.OK


def test_garantida_expoe_desconto_absoluto_e_url(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    oportunidade = guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA)[0]

    assert oportunidade.absolute_discount == Brl.from_float(98.00)
    assert "Unusual%20Team%20Captain" in oportunidade.steam_url


def test_candidatas_nao_viram_garantidas(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    assert guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA) == []


def test_preco_desatualizado_reprova_a_garantida(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    futuro = 1_759_900_000 + 40 * 86400
    oportunidade = guaranteed_opportunities(saida.candidates, index, CHAVE, now=futuro)[0]
    assert oportunidade.guard is Guard.STALE_PRICE


def test_garantida_nao_resolve_craftabilidade_ou_efeito_na_passada_rasa(index: PriceIndex):
    """Craftabilidade e efeito são incógnitas na passada rasa.

    A passada rasa só vê nomes e preços: não consegue determinar se um item
    é craftável ou qual seu efeito (em Unusuais). Reportar o valor da
    variante mais barata como um fato verificado seria apresentar um
    artefato (qual entrada foi mais barata) como uma verdade do mercado.
    Por isso ambos são None, como expressão de desconhecimento.
    """
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    oportunidade = guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA)[0]

    assert oportunidade.craftable is None
    assert oportunidade.effect is None


# --- alvos do fetch profundo ---------------------------------------------


def test_deep_targets_ordena_pelo_melhor_cenario(index: PriceIndex):
    saida = shallow_pass(
        [
            _resultado("Unusual Team Captain", 800.0),
            _resultado("Unusual Team Captain", 300.0),
        ],
        index,
        CHAVE,
        0.15,
    )
    alvos = deep_targets(saida.candidates, CHAVE, limit=2)
    assert alvos[0].steam_lowest == Brl.from_float(300.00)


def test_deep_targets_respeita_o_limite(index: PriceIndex):
    saida = shallow_pass(
        [_resultado("Unusual Team Captain", 500.0)] * 5, index, CHAVE, 0.15
    )
    assert len(deep_targets(saida.candidates, CHAVE, limit=3)) == 3


def _indice_inline(items: dict) -> PriceIndex:
    """Índice mínimo montado no próprio teste.

    O fixture compartilhado tem um único item Unusual, e outros testes
    afirmam sobre a contagem de itens dele; cenários que precisam de dois
    Unusuais com tetos diferentes montam o payload aqui.
    """
    return PriceIndex.from_payload({"response": {"items": items}}, KEY_IN_REFINED)


def _unusual_em_chaves(barato: float, caro: float) -> dict:
    return {
        "prices": {
            "5": {
                "Tradable": {
                    "Craftable": {
                        "17": {
                            "currency": "keys",
                            "value": barato,
                            "last_update": 1759900000,
                        },
                        "701": {
                            "currency": "keys",
                            "value": caro,
                            "last_update": 1759900000,
                        },
                    }
                }
            }
        }
    }


def test_deep_targets_so_leva_unusuais(index: PriceIndex):
    """Só Unusual entra no fetch profundo, mesmo com proporção pior.

    'Rocket Launcher' Unique a R$ 0,01 tem teto de R$ 0,03: proporção de
    67%, muito acima dos 19% do Unusual. Por proporção ele passaria na
    frente; o spec escopa o fetch nos Unusuais.
    """
    saida = shallow_pass(
        [
            _resultado("Unusual Team Captain", 800.0),
            _resultado("Rocket Launcher", 0.01),
        ],
        index,
        CHAVE,
        0.15,
    )
    assert len(saida.candidates) == 2
    assert {c.identity.quality_id for c in saida.candidates} == {5, 6}

    alvos = deep_targets(saida.candidates, CHAVE, limit=10)
    assert [a.hash_name for a in alvos] == ["Unusual Team Captain"]


def test_deep_targets_ordena_por_ganho_absoluto_e_nao_por_proporcao():
    """O ganho absoluto manda, porque o orçamento de requisições é fixo.

    Chapéu caro: pago R$ 1.000 contra teto de 100 chaves (R$ 2.200) =
    proporção de 55%, ganho de R$ 1.200.
    Chapéu barato: pago R$ 100 contra teto de 20 chaves (R$ 440) =
    proporção de 77%, ganho de R$ 340.

    Por proporção o barato viria primeiro e as requisições caras
    comprariam o menor ganho possível.
    """
    indice = _indice_inline(
        {
            "Chapeu Caro": _unusual_em_chaves(barato=10.0, caro=100.0),
            "Chapeu Barato": _unusual_em_chaves(barato=5.0, caro=20.0),
        }
    )
    saida = shallow_pass(
        [
            _resultado("Unusual Chapeu Barato", 100.0),
            _resultado("Unusual Chapeu Caro", 1000.0),
        ],
        indice,
        CHAVE,
        0.15,
    )
    assert all(c.classification is Classification.CANDIDATE for c in saida.candidates)

    alvos = deep_targets(saida.candidates, CHAVE, limit=10)
    assert [a.hash_name for a in alvos] == [
        "Unusual Chapeu Caro",
        "Unusual Chapeu Barato",
    ]


def test_deep_targets_ignora_garantidas_e_descartadas(index: PriceIndex):
    saida = shallow_pass(
        [
            _resultado("Unusual Team Captain", 100.0),  # garantida
            _resultado("Unusual Team Captain", 950.0),  # descartada
        ],
        index,
        CHAVE,
        0.15,
    )
    assert deep_targets(saida.candidates, CHAVE, limit=10) == []


# --- fetch profundo ------------------------------------------------------


def _listagem(
    listing_id: str, reais: float, effect: str | None, craftable: bool = True
) -> Listing:
    return Listing(
        listing_id=listing_id,
        total_price=Brl.from_float(reais),
        effect=effect,
        craftable=craftable,
        spelled=False,
    )


def test_resolve_deep_casa_o_efeito_com_o_priceindex(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    candidata = saida.candidates[0]

    oportunidades = resolve_deep(
        candidata,
        [_listagem("L1", 500.0, "Burning Flames")],  # id 13 = 28 chaves = R$ 616
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )

    assert len(oportunidades) == 1
    assert oportunidades[0].effect == "Burning Flames"
    assert oportunidades[0].valuation.fair_value == Brl.from_float(616.00)
    assert oportunidades[0].deep_fetched is True
    assert oportunidades[0].guard is Guard.OK


def test_resolve_deep_ignora_listagem_sem_efeito_em_item_unusual(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, None)],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []


def test_resolve_deep_ignora_efeito_fora_do_mapa(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, "Efeito Que Não Existe")],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []


def test_resolve_deep_ignora_efeito_sem_preco_no_indice(index: PriceIndex):
    """Green Confetti (id 6) está no mapa mas não tem preço no fixture."""
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, "Green Confetti")],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []


# --- itens em USD (guarda 4) ----------------------------------------------


def test_collect_usd_items_pega_valor_em_dolar_e_preco_da_steam(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    itens = collect_usd_items(
        [_resultado("Mildly Disturbing Halloween Mask", 30.0)], index
    )
    assert itens == [(4.25, Brl.from_float(30.00))]


def test_collect_usd_items_ignora_itens_precificados_em_chaves(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    assert collect_usd_items([_resultado("Unusual Team Captain", 500.0)], index) == []


def test_collect_usd_items_ignora_nome_fora_do_indice(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    assert collect_usd_items([_resultado("Item Inexistente", 10.0)], index) == []


def _qualidade_unica(*entradas: dict) -> dict:
    return {"prices": {"6": {"Tradable": {"Craftable": list(entradas)}}}}


def test_collect_usd_items_ignora_item_com_preco_em_chaves_E_em_usd():
    """Ter preço em chaves já basta para sair da amostra.

    Este item casa em `shallow_pass` e é avaliado normalmente; medir o
    dólar dele contra a Steam responderia sobre outro item que não o da
    hipótese, que é o dos preços que SÓ existem em dólar.
    """
    from tf2price.spike.pipeline import collect_usd_items

    indice = _indice_inline(
        {
            "Chapeu Misto": _qualidade_unica(
                {"currency": "keys", "value": 2.0, "last_update": 1759900000},
                {"currency": "usd", "value": 4.25, "last_update": 1759900000},
            )
        }
    )
    assert collect_usd_items([_resultado("Chapeu Misto", 30.0)], indice) == []


def test_collect_usd_items_pega_item_so_com_preco_em_usd():
    from tf2price.spike.pipeline import collect_usd_items

    indice = _indice_inline(
        {
            "Chapeu Dolar": _qualidade_unica(
                {"currency": "usd", "value": 4.25, "last_update": 1759900000}
            )
        }
    )
    itens = collect_usd_items([_resultado("Chapeu Dolar", 30.0)], indice)
    assert itens == [(4.25, Brl.from_float(30.00))]


def test_collect_usd_items_ignora_entrada_com_priceindex():
    """Entrada com priceindex é uma variante, não o item do nome.

    Pegar o dólar de um efeito arbitrário e casá-lo com o preço Steam do
    nome inteiro compararia dois itens diferentes no mesmo par.
    """
    from tf2price.spike.pipeline import collect_usd_items

    indice = _indice_inline(
        {
            "Chapeu Variante": {
                "prices": {
                    "6": {
                        "Tradable": {
                            "Craftable": {
                                "13": {
                                    "currency": "usd",
                                    "value": 4.25,
                                    "last_update": 1759900000,
                                },
                                "701": {
                                    "currency": "usd",
                                    "value": 9.99,
                                    "last_update": 1759900000,
                                },
                            }
                        }
                    }
                }
            }
        }
    )
    assert collect_usd_items([_resultado("Chapeu Variante", 30.0)], indice) == []
