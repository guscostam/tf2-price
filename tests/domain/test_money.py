from __future__ import annotations

import pytest

from tf2price.domain.money import Brl


def test_from_float_converte_para_centavos():
    assert Brl.from_float(12.34).cents == 1234


def test_from_cents_e_as_float_sao_inversos():
    assert Brl.from_cents(2214).as_float == pytest.approx(22.14)


def test_soma_e_subtracao():
    assert Brl.from_cents(1000) + Brl.from_cents(250) == Brl.from_cents(1250)
    assert Brl.from_cents(1000) - Brl.from_cents(250) == Brl.from_cents(750)


def test_multiplicacao_arredonda_para_centavo():
    # taxa de 15% da Steam sobre R$ 10,00 deixa R$ 8,50 ao vendedor
    assert Brl.from_float(10.00) * 0.85 == Brl.from_float(8.50)


def test_ordenacao():
    assert Brl.from_cents(100) < Brl.from_cents(200)
    assert max(Brl.from_cents(100), Brl.from_cents(200)) == Brl.from_cents(200)


def test_str_em_formato_brasileiro():
    assert str(Brl.from_float(1234.5)) == "R$ 1.234,50"
    assert str(Brl.from_float(0.99)) == "R$ 0,99"
