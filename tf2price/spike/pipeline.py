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
                craftable=None,  # craftabilidade é incógnita na passada rasa, como o efeito
                steam_total=candidate.steam_lowest,
                valuation=evaluate(candidate.steam_lowest, keys, key_brl),
                classification=candidate.classification,
                guard=check_guards(entry.price, candidate.classification, False, now=now),
                deep_fetched=False,
            )
        )

    return opportunities


def deep_targets(candidates: list[Candidate], key_brl: Brl, limit: int) -> list[Candidate]:
    """Candidatas Unusual ordenadas pelo ganho ABSOLUTO no melhor cenário.

    Só Unusuais: o spec escopa o fetch profundo nos 20 melhores candidatos
    Unusual, que é o dado de maior valor do spike. As demais candidatas
    continuam contadas no relatório, mas as incógnitas delas não são
    resolvidas e por isso não entram no líquido.

    Ordenar por valor absoluto, e não por proporção, porque o fetch profundo
    é um orçamento FIXO de requisições caras: cada uma deve comprar o maior
    ganho possível em reais. Por proporção, um cosmético de R$ 1 contra um
    teto de uma chave (95%) passaria na frente de um chapéu Unusual de
    R$ 500 contra um teto de 45 chaves (49%), e as ~20 requisições iriam
    para itens cujo ganho máximo é de centavos.
    """
    pending = [
        c
        for c in candidates
        if c.classification is Classification.CANDIDATE
        and c.identity.quality_id == QUALITY_UNUSUAL
    ]

    def best_case_gap_cents(candidate: Candidate) -> int:
        ceiling = key_brl * candidate.value_range.max_keys
        return ceiling.cents - candidate.steam_lowest.cents

    pending.sort(key=best_case_gap_cents, reverse=True)
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


def collect_usd_items(
    results: list[SearchResult], index: PriceIndex
) -> list[tuple[float, Brl]]:
    """Pares (valor em USD na bp.tf, preço na Steam) para testar a guarda 4.

    A amostra são exatamente os itens que `shallow_pass` descarta como não
    casados: nenhum nome candidato tem faixa em chaves ou metal. Por isso a
    resolução do nome passa pela MESMA `_resolve_bptf_name` — se ela casa,
    o item foi avaliado normalmente e não pertence a esta amostra. Um item
    com preço em chaves E em USD na mesma qualidade fica de fora: ele já
    tem valor convertível, e o que se quer medir é o preço que só existe
    em dólares.

    Dentro do nome, só entradas sem `priceindex`. Uma entrada com
    priceindex é uma variante (um efeito de Unusual específico), e pegar
    uma delas compararia o dólar de um efeito arbitrário contra o preço
    Steam do nome inteiro — dois itens diferentes no mesmo par.
    """
    pairs: list[tuple[float, Brl]] = []

    for result in results:
        identity = parse_market_hash_name(result.hash_name)

        if _resolve_bptf_name(identity, result.hash_name, index) is not None:
            continue

        for name in bptf_name_candidates(identity, result.hash_name):
            usd = [
                e
                for e in index.entries(name, identity.quality_id)
                if e.priceindex is None
                and e.price.currency == "usd"
                and e.craftable
                and e.price.value > 0
            ]
            if usd:
                pairs.append((usd[0].price.value, result.lowest_price))
                break  # primeiro nome com preço em dólar decide

    return pairs
