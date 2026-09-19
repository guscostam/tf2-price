from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification, ValueRange, classify

CHAVE = Brl.from_float(22.00)


def test_faixa_invertida_e_erro():
    with pytest.raises(ValueError):
        ValueRange(min_keys=10.0, max_keys=5.0)


def test_garantida_quando_barato_ate_no_pior_cenario():
    # faixa 10 a 30 chaves. Piso = 10 * 22 = R$ 220. Com limiar 15%: R$ 187.
    resultado = classify(Brl.from_float(150.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.GUARANTEED


def test_candidata_quando_so_vale_no_melhor_cenario():
    # R$ 400 está acima do piso (R$ 187) mas abaixo do teto (30 * 22 * 0.85 = R$ 561)
    resultado = classify(Brl.from_float(400.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.CANDIDATE


def test_descartada_quando_nem_o_melhor_cenario_justifica():
    resultado = classify(Brl.from_float(900.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.DISCARDED


def test_faixa_de_um_ponto_so_nunca_e_candidata():
    # Item de nome limpo: piso e teto coincidem, então ou é garantida ou é descartada.
    estreita = ValueRange(10.0, 10.0)
    assert classify(Brl.from_float(150.00), estreita, CHAVE, 0.15) is Classification.GUARANTEED
    assert classify(Brl.from_float(300.00), estreita, CHAVE, 0.15) is Classification.DISCARDED


def test_limiar_zero_ainda_classifica():
    assert classify(Brl.from_float(219.00), ValueRange(10.0, 10.0), CHAVE, 0.0) is (
        Classification.GUARANTEED
    )


@given(
    min_keys=st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False),
    span=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
    frac=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    price_cents=st.integers(min_value=1, max_value=500_000),
    key_cents=st.integers(min_value=100, max_value=10_000),
    threshold=st.floats(min_value=0.0, max_value=0.9, allow_nan=False, allow_infinity=False),
)
def test_a_poda_nunca_descarta_uma_pechincha(
    min_keys, span, frac, price_cents, key_cents, threshold
):
    """Propriedade central do sistema.

    Para qualquer valor real dentro da faixa de incerteza: se a listagem
    é pechincha naquele valor, ela NUNCA pode ser classificada como
    descartada. Um falso negativo aqui é invisível — o item simplesmente
    nunca aparece, e você nunca fica sabendo que existiu.
    """
    faixa = ValueRange(min_keys=min_keys, max_keys=min_keys + span)
    valor_real_keys = min_keys + span * frac

    chave = Brl.from_cents(key_cents)
    preco = Brl.from_cents(price_cents)

    e_pechincha = preco < chave * (valor_real_keys * (1 - threshold))
    resultado = classify(preco, faixa, chave, threshold)

    if e_pechincha:
        assert resultado is not Classification.DISCARDED
