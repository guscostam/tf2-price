from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import (
    ItemIdentity,
    bptf_name_candidates,
    parse_market_hash_name,
)
from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification, ValueRange, classify
from tf2price.domain.valuation import Guard, Valuation, check_guards, evaluate
from tf2price.sources.backpacktf import PriceEntry, PriceIndex
from tf2price.sources.steam import APPID, Listing, SearchResult

QUALITY_UNUSUAL = 5


@dataclass(frozen=True)
class Candidate:
    hash_name: str
    identity: ItemIdentity
    bptf_name: str
    value_range: ValueRange
    classification: Classification
    steam_lowest: Brl
    sell_listings: int


@dataclass(frozen=True)
class Opportunity:
    hash_name: str
    listing_id: str | None
    effect: str | None
    craftable: bool | None
    steam_total: Brl
    valuation: Valuation
    classification: Classification
    guard: Guard
    deep_fetched: bool

    @property
    def absolute_discount(self) -> Brl:
        return self.valuation.fair_value - self.steam_total

    @property
    def steam_url(self) -> str:
        quoted = urllib.parse.quote(self.hash_name, safe="")
        return f"https://steamcommunity.com/market/listings/{APPID}/{quoted}"


@dataclass(frozen=True)
class ShallowOutcome:
    candidates: list[Candidate]
    unmatched: list[str]


def _resolve_bptf_name(identity: ItemIdentity, original: str, index: PriceIndex) -> str | None:
    """Primeiro nome candidato que existe no índice COM faixa utilizável.

    Existir no índice não basta: um item precificado só em USD não tem valor
    convertível para chaves, e sem faixa a poda não tem o que fazer.
    """
    for name in bptf_name_candidates(identity, original):
        if index.value_range_keys(name, identity.quality_id) is not None:
            return name
    return None


def shallow_pass(
    results: list[SearchResult],
    index: PriceIndex,
    key_brl: Brl,
    threshold: float,
) -> ShallowOutcome:
    candidates: list[Candidate] = []
    unmatched: list[str] = []

    for result in results:
        identity = parse_market_hash_name(result.hash_name)
        bptf_name = _resolve_bptf_name(identity, result.hash_name, index)

        if bptf_name is None:
            unmatched.append(result.hash_name)
            continue

        value_range = index.value_range_keys(bptf_name, identity.quality_id)
        candidates.append(
            Candidate(
                hash_name=result.hash_name,
                identity=identity,
                bptf_name=bptf_name,
                value_range=value_range,
                classification=classify(result.lowest_price, value_range, key_brl, threshold),
                steam_lowest=result.lowest_price,
                sell_listings=result.sell_listings,
            )
        )

    return ShallowOutcome(candidates=candidates, unmatched=unmatched)


def _entry_with_min_keys(
    index: PriceIndex, item_name: str, quality_id: int
) -> tuple[PriceEntry, float] | None:
    best: tuple[PriceEntry, float] | None = None
    for entry in index.entries(item_name, quality_id):
        keys = index.to_keys(entry.price)
        if keys is None or keys <= 0:
            continue
        if best is None or keys < best[1]:
            best = (entry, keys)
    return best


def guaranteed_opportunities(
    candidates: list[Candidate],
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
) -> list[Opportunity]:
    """Avalia as garantidas SEM fetch profundo, pelo pior valor da faixa.

    Usar o pior valor é o que torna o número reportável: a poda provou que
    o item vale ao menos isso, então o desconto mostrado não depende de
    nenhuma suposição não verificada.
    """
    opportunities: list[Opportunity] = []

    for candidate in candidates:
        if candidate.classification is not Classification.GUARANTEED:
            continue

        worst = _entry_with_min_keys(index, candidate.bptf_name, candidate.identity.quality_id)
        if worst is None:
            continue
        entry, keys = worst

        opportunities.append(
            Opportunity(
                hash_name=candidate.hash_name,
                listing_id=None,
                effect=None,
                craftable=None,  # Craftability is unresolved at the shallow-pass stage, like effect
                steam_total=candidate.steam_lowest,
                valuation=evaluate(candidate.steam_lowest, keys, key_brl),
                classification=candidate.classification,
                guard=check_guards(entry.price, candidate.classification, False, now=now),
                deep_fetched=False,
            )
        )

    return opportunities


def deep_targets(candidates: list[Candidate], key_brl: Brl, limit: int) -> list[Candidate]:
    """Candidatas ordenadas pelo desconto no cenário mais favorável.

    O fetch profundo é o recurso caro do spike; gastá-lo primeiro onde o
    potencial é maior é o que faz 20 requisições valerem alguma coisa.
    """
    pending = [c for c in candidates if c.classification is Classification.CANDIDATE]

    def best_case_discount(candidate: Candidate) -> float:
        ceiling = key_brl * candidate.value_range.max_keys
        if ceiling.cents <= 0:
            return -1.0
        return 1 - candidate.steam_lowest.cents / ceiling.cents

    pending.sort(key=best_case_discount, reverse=True)
    return pending[:limit]


def resolve_deep(
    candidate: Candidate,
    listings: list[Listing],
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> list[Opportunity]:
    """Resolve as incógnitas de uma candidata com as listagens reais."""
    opportunities: list[Opportunity] = []
    quality_id = candidate.identity.quality_id

    for listing in listings:
        priceindex: str | None = None

        if quality_id == QUALITY_UNUSUAL:
            if listing.effect is None:
                continue  # Unusual sem efeito legível: não dá para avaliar
            effect_id = effect_id_for(listing.effect, effects_path)
            if effect_id is None:
                continue  # efeito fora do mapa: registrar seria ruído, pular é honesto
            priceindex = str(effect_id)

        price = index.lookup(
            candidate.bptf_name,
            quality_id,
            craftable=listing.craftable,
            priceindex=priceindex,
        )
        keys = index.to_keys(price)
        if keys is None or keys <= 0:
            continue

        opportunities.append(
            Opportunity(
                hash_name=candidate.hash_name,
                listing_id=listing.listing_id,
                effect=listing.effect,
                craftable=listing.craftable,
                steam_total=listing.total_price,
                valuation=evaluate(listing.total_price, keys, key_brl),
                classification=candidate.classification,
                guard=check_guards(price, candidate.classification, True, now=now),
                deep_fetched=True,
            )
        )

    return opportunities
