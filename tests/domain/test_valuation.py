from __future__ import annotations

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import (
    BptfPrice,
    Guard,
    check_guards,
    evaluate,
)

AGORA = 1_760_000_000
CHAVE = Brl.from_float(22.00)


def _preco(
    value: float = 10.0,
    value_high: float | None = 11.0,
    currency: str = "keys",
    last_update: int = AGORA - 3600,
) -> BptfPrice:
    return BptfPrice(
        value=value, value_high=value_high, currency=currency, last_update=last_update
    )


def test_valor_justo_usa_a_taxa_da_chave():
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.fair_value == Brl.from_float(220.00)


def test_desconto_e_fracao_sobre_o_valor_justo():
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.discount == pytest.approx(1 - 180 / 220)


def test_lucro_de_revenda_desconta_a_taxa_da_steam():
    # R$ 220 de valor justo, menos 15% de taxa do vendedor, menos R$ 180 pagos
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.resale_profit == Brl.from_float(7.00)


def test_desconto_negativo_quando_o_item_esta_caro():
    resultado = evaluate(Brl.from_float(300.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.discount < 0


def test_valor_justo_zero_e_erro():
    with pytest.raises(ValueError):
        evaluate(Brl.from_float(10.00), fair_keys=0.0, key_brl=CHAVE)


def test_guarda_derivado_da_steam_tem_precedencia():
    # mesmo desatualizado e com faixa larga, o motivo reportado é o circular
    preco = _preco(currency="usd", value=1.0, value_high=99.0, last_update=0)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.MARKET_DERIVED
    )


def test_guarda_preco_desatualizado():
    preco = _preco(last_update=AGORA - 31 * 86400)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.STALE_PRICE
    )


def test_preco_de_29_dias_passa():
    preco = _preco(last_update=AGORA - 29 * 86400)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_guarda_faixa_larga():
    preco = _preco(value=10.0, value_high=13.0)  # 1.3x, acima do teto de 1.25x
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.WIDE_RANGE
    )


def test_faixa_no_limite_passa():
    preco = _preco(value=10.0, value_high=12.5)  # exatamente 1.25x
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_faixa_ausente_passa():
    preco = _preco(value_high=None)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_candidata_sem_fetch_profundo_e_reprovada():
    assert check_guards(_preco(), Classification.CANDIDATE, False, now=AGORA) is (
        Guard.UNRESOLVED
    )


def test_candidata_com_fetch_profundo_passa():
    assert check_guards(_preco(), Classification.CANDIDATE, True, now=AGORA) is Guard.OK


def test_garantida_sem_fetch_profundo_passa():
    """Regressão da correção central do spec.

    A poda já provou que uma garantida vale mesmo no pior cenário — não
    craftável e com o pior efeito. Aplicar a guarda de incógnitas a ela
    zeraria os itens não-Unusual, que são justamente o que a passada rasa
    resolve sozinha.
    """
    assert check_guards(_preco(), Classification.GUARANTEED, False, now=AGORA) is Guard.OK
