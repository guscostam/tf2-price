from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import bptf_name_candidates, parse_market_hash_name
from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, SalePoint

# A taxa é 15% sobre o valor do vendedor, e o comprador paga a soma. Observado
# na página: 124,52 ao comprador, 16,23 de taxa, 108,29 ao vendedor, e
# 108,29 x 0,15 = 16,24. Logo o líquido é o preço dividido por 1,15.
STEAM_FEE_MULTIPLIER = 1.15

QUALITY_UNUSUAL = 5

RAZAO_EFEITO_DESCONHECIDO = (
    "the effect is not in the Valve schema map, so it cannot be matched on backpack.tf"
)
RAZAO_SEM_PRECO = "backpack.tf does not price this effect for this item"
RAZAO_SEM_INDICE = (
    "the backpack.tf price index has not loaded yet; try again in a few minutes"
)


@dataclass(frozen=True)
class ImmediateExit:
    """Vender agora para a melhor oferta de compra existente.

    Dado duro: são ordens reais, verificáveis neste minuto, e não dependem de
    referência externa nenhuma.
    """

    top_bid: Brl | None
    net_received: Brl | None
    result: Brl | None
    buy_orders: int


@dataclass(frozen=True)
class PatientExit:
    """Trocar por chaves usando a backpack.tf como referência.

    Dado mole: preço *sugerido*, não oferta de compra. Ninguém se comprometeu
    a pagar aquilo, e a idade pode ser de anos. Por isso carrega `age_days`,
    e por isso `available` pode ser falso com um motivo legível.
    """

    available: bool
    reason: str | None
    keys: float | None
    fair_value: Brl | None
    result: Brl | None
    age_days: int | None


@dataclass(frozen=True)
class Analysis:
    hash_name: str
    effect: str
    listings: list[PageListing]
    cheapest: PageListing
    price_in_keys: float
    immediate: ImmediateExit
    patient: PatientExit
    # Abaixo: dados DO ITEM INTEIRO, somando todos os efeitos. A Steam não os
    # separa por efeito. Repassados sem transformação para que a apresentação
    # os rotule como são.
    orderbook: OrderBook
    history: list[SalePoint]
    history_median: Brl | None
    history_purchases: int
    key_brl: Brl


def net_after_fee(buyer_price: Brl) -> Brl:
    """O que o vendedor recebe quando o comprador paga `buyer_price`."""
    return Brl.from_cents(round(buyer_price.cents / STEAM_FEE_MULTIPLIER))


def effects_available(page: ItemPage) -> list[str]:
    """Efeitos que de fato têm listagem agora, em ordem alfabética."""
    return sorted({x.effect for x in page.listings if x.effect})


def listings_of(page: ItemPage, effect: str) -> list[PageListing]:
    """Listagens daquele efeito, da mais barata para a mais cara."""
    return sorted(
        (x for x in page.listings if x.effect == effect),
        key=lambda x: x.total_price,
    )


def immediate_exit(paid: Brl, orderbook: OrderBook) -> ImmediateExit:
    """Resultado de comprar por `paid` e vender já para a melhor oferta.

    Uma ordem de compra na Steam vale para QUALQUER exemplar daquele nome,
    seja qual for o efeito. É por isso que comparar o preço de um efeito
    específico contra a melhor oferta do item é legítimo — é o único
    cruzamento entre o nível por-efeito e o nível por-item que se sustenta.
    """
    if orderbook.max_buy_order is None:
        return ImmediateExit(None, None, None, orderbook.buy_orders)

    recebido = net_after_fee(orderbook.max_buy_order)
    return ImmediateExit(
        top_bid=orderbook.max_buy_order,
        net_received=recebido,
        result=recebido - paid,
        buy_orders=orderbook.buy_orders,
    )


def patient_exit(
    paid: Brl,
    hash_name: str,
    effect: str,
    index: PriceIndex | None,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> PatientExit:
    now = int(time.time()) if now is None else now

    effect_id = effect_id_for(effect, effects_path)
    if effect_id is None:
        return PatientExit(False, RAZAO_EFEITO_DESCONHECIDO, None, None, None, None)

    if index is None:
        return PatientExit(False, RAZAO_SEM_INDICE, None, None, None, None)

    identity = parse_market_hash_name(hash_name)
    for nome in bptf_name_candidates(identity, hash_name):
        preco = index.lookup(
            nome, QUALITY_UNUSUAL, craftable=True, priceindex=str(effect_id)
        )
        chaves = index.to_keys(preco)
        if chaves is None or chaves <= 0:
            continue

        justo = key_brl * chaves
        return PatientExit(
            available=True,
            reason=None,
            keys=chaves,
            fair_value=justo,
            result=justo - paid,
            age_days=(now - preco.last_update) // 86400,
        )

    return PatientExit(False, RAZAO_SEM_PRECO, None, None, None, None)


def analyse(
    page: ItemPage,
    effect: str,
    index: PriceIndex | None,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> Analysis:
    listagens = listings_of(page, effect)
    if not listagens:
        raise ValueError(f"No listings for effect {effect!r} in this snapshot")

    barata = listagens[0]
    medianas = [p.median.cents for p in page.history]

    return Analysis(
        hash_name=page.hash_name,
        effect=effect,
        listings=listagens,
        cheapest=barata,
        price_in_keys=barata.total_price.cents / key_brl.cents,
        immediate=immediate_exit(barata.total_price, page.orderbook),
        patient=patient_exit(
            barata.total_price, page.hash_name, effect, index, key_brl,
            now=now, effects_path=effects_path,
        ),
        orderbook=page.orderbook,
        history=page.history,
        history_median=Brl.from_cents(round(median(medianas))) if medianas else None,
        history_purchases=sum(p.purchases for p in page.history),
        key_brl=key_brl,
    )
