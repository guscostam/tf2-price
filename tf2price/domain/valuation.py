from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification

STEAM_SELLER_FEE = 0.15
STALE_AFTER_DAYS = 30
MAX_RANGE_RATIO = 1.25


@dataclass(frozen=True)
class BptfPrice:
    """Uma entrada de preço do índice da backpack.tf.

    `value` é o piso da faixa sugerida e é o único que usamos no cálculo.
    `value_high` entra apenas na guarda de faixa larga.
    """

    value: float
    value_high: float | None
    currency: str
    last_update: int


@dataclass(frozen=True)
class Valuation:
    fair_value: Brl
    discount: float
    resale_profit: Brl


def evaluate(steam_total: Brl, fair_keys: float, key_brl: Brl) -> Valuation:
    """Avalia uma listagem contra o valor justo em chaves.

    `steam_total` é o que o COMPRADOR paga (preço + taxa), nunca o líquido
    do vendedor. A taxa de 15% sai do vendedor, então ela aparece só em
    `resale_profit` e jamais no desconto.
    """
    fair = key_brl * fair_keys
    if fair.cents <= 0:
        raise ValueError(f"valor justo inválido: {fair_keys} chaves a {key_brl}")

    discount = 1 - (steam_total.cents / fair.cents)
    resale_profit = fair * (1 - STEAM_SELLER_FEE) - steam_total
    return Valuation(fair_value=fair, discount=discount, resale_profit=resale_profit)


class Guard(str, Enum):
    OK = "ok"
    MARKET_DERIVED = "derivado_da_steam"
    STALE_PRICE = "preco_desatualizado"
    WIDE_RANGE = "faixa_larga"
    UNRESOLVED = "incognitas_nao_resolvidas"


def check_guards(
    price: BptfPrice,
    classification: Classification,
    deep_fetched: bool,
    now: int | None = None,
) -> Guard:
    """Devolve o primeiro motivo de reprovação, ou OK.

    A ordem é deliberada: um preço derivado da Steam torna toda a comparação
    circular, então não adianta checar mais nada depois dele.
    """
    now = int(time.time()) if now is None else now

    # Guarda 4: preço em USD é o sinal candidato de origem Steam Market.
    # Hipótese a confirmar no Task 11.
    # Defesa em profundidade: no pipeline este ramo não dispara, porque
    # to_keys() devolve None para USD e a entrada é descartada antes de
    # chegar aqui. A guarda fica como rede de segurança para chamadas
    # futuras que não passem por aquele filtro.
    if price.currency == "usd":
        return Guard.MARKET_DERIVED

    if now - price.last_update > STALE_AFTER_DAYS * 86400:
        return Guard.STALE_PRICE

    if price.value_high is not None and price.value_high > price.value * MAX_RANGE_RATIO:
        return Guard.WIDE_RANGE

    # Guarda 1: só se aplica a candidatas. Uma garantida já foi provada no
    # pior cenário pela poda e não precisa de fetch profundo.
    # Defesa em profundidade: no pipeline este ramo não dispara, porque uma
    # candidata sem fetch profundo nunca vira Opportunity. A guarda fica
    # como rede de segurança, não como comportamento observável da execução.
    if classification is Classification.CANDIDATE and not deep_fetched:
        return Guard.UNRESOLVED

    return Guard.OK
