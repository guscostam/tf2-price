"""A chave de referência: dólar da chave na bp.tf × PTAX.

Números escolhidos para a conta fechar de cabeça: 0.0183 US$/ref × 64.11 ref
= US$ 1,173213 por chave; × R$ 10,00 = R$ 11,73.
"""

from __future__ import annotations

from datetime import datetime

from tf2price.domain.money import Brl
from tf2price.preco.referencia import (
    FALTA_DOLAR_BPTF,
    FALTA_INDICE,
    FALTA_PTAX,
    ChaveReferencia,
    montar_referencia,
    motivo_sem_referencia,
)
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.bcb import Ptax

CARREGADO = datetime(2026, 9, 22, 9, 0)
PTAX = Ptax(10.0, datetime(2026, 9, 21, 13, 6))


def _indice(raw_usd_value=0.0183, usd_currency="metal") -> PriceIndex:
    return PriceIndex.from_payload(
        {"response": {"items": {}, "raw_usd_value": raw_usd_value,
                      "usd_currency": usd_currency}},
        64.11,
        carregado_em=CARREGADO,
    )


def test_referencia_e_dolar_da_chave_vezes_ptax():
    ref = montar_referencia(_indice(), PTAX)
    assert ref == ChaveReferencia(
        brl=Brl.from_cents(1173),
        usd=0.0183 * 64.11,
        ptax=10.0,
        ptax_data=PTAX.data,
        bptf_carregado_em=CARREGADO,
    )
    assert motivo_sem_referencia(_indice(), PTAX) is None


def test_arredonda_uma_vez_so():
    # US$ 1,666860 × 5,1161 = R$ 8,5277... -> 853 centavos.
    ref = montar_referencia(_indice(raw_usd_value=0.026), Ptax(5.1161, PTAX.data))
    assert ref.brl == Brl.from_cents(853)


def test_ptax_formatada_para_a_tela():
    ref = montar_referencia(_indice(), Ptax(5.1161, PTAX.data))
    assert ref.ptax_formatada == "R$ 5,1161"


def test_usd_formatado_para_a_tela():
    ref = montar_referencia(_indice(), PTAX)
    assert ref.usd_formatado == "US$ 1,17"


def test_sem_indice():
    assert montar_referencia(None, PTAX) is None
    assert motivo_sem_referencia(None, PTAX) == FALTA_INDICE


def test_sem_ptax():
    assert montar_referencia(_indice(), None) is None
    assert motivo_sem_referencia(_indice(), None) == FALTA_PTAX


def test_sem_dolar_na_bptf():
    indice = _indice(usd_currency="keys")
    assert montar_referencia(indice, PTAX) is None
    assert motivo_sem_referencia(indice, PTAX) == FALTA_DOLAR_BPTF


def test_referencia_de_zero_centavos_e_ausencia():
    """Zero centavos viraria divisão por zero em "N chaves"."""
    indice = _indice(raw_usd_value=0.000001)
    assert montar_referencia(indice, PTAX) is None
    assert motivo_sem_referencia(indice, PTAX) == FALTA_DOLAR_BPTF


def test_o_indice_falta_antes_da_ptax():
    """A ordem do motivo é a ordem de carregamento: índice, PTAX, dólar."""
    assert motivo_sem_referencia(None, None) == FALTA_INDICE
