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
