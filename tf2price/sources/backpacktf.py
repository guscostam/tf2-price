from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from tf2price.domain.prefilter import ValueRange
from tf2price.domain.valuation import BptfPrice

BASE = "https://backpack.tf/api"
APPID = 440


@dataclass(frozen=True)
class Currencies:
    key_in_refined: float
    key_in_usd: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Currencies":
        price = payload["response"]["currencies"]["keys"]["price"]
        return cls(
            key_in_refined=float(price["value"]),
            key_in_usd=float(price.get("usd", 0.0)),
        )


@dataclass(frozen=True)
class PriceEntry:
    craftable: bool
    priceindex: str | None
    price: BptfPrice


def _to_price(entry: dict[str, Any]) -> BptfPrice:
    raw_high = entry.get("value_high")
    return BptfPrice(
        value=float(entry.get("value", 0.0)),
        value_high=float(raw_high) if raw_high is not None else None,
        currency=str(entry.get("currency", "")),
        last_update=int(entry.get("last_update", 0)),
    )


class PriceIndex:
    """O índice de preços da backpack.tf, indexado para consulta."""

    def __init__(self, items: dict[str, Any], key_in_refined: float) -> None:
        if key_in_refined <= 0:
            raise ValueError("key_in_refined tem que ser positivo")
        self._items = items
        self._key_in_refined = key_in_refined

    @classmethod
    def from_payload(cls, payload: dict[str, Any], key_in_refined: float) -> "PriceIndex":
        return cls(payload["response"]["items"], key_in_refined)

    def item_names(self) -> set[str]:
        return set(self._items)

    def entries(self, item_name: str, quality_id: int) -> list[PriceEntry]:
        return list(self._iter_entries(item_name, quality_id))

    def _iter_entries(self, item_name: str, quality_id: int) -> Iterator[PriceEntry]:
        item = self._items.get(item_name)
        if not item:
            return

        quality = (item.get("prices") or {}).get(str(quality_id))
        if not quality:
            return

        # Só itens tradáveis interessam: um item não-tradável não pode virar
        # chaves, que é a moeda em que o lucro é denominado.
        tradable = quality.get("Tradable")
        if not tradable:
            return

        for craft_key, node in tradable.items():
            craftable = craft_key == "Craftable"

            # A bp.tf usa LISTA para itens sem variante e DICIONÁRIO com
            # priceindex para itens com variante (efeitos de Unusual, séries
            # de caixa). Mesmo campo, dois tipos. Tratar só um faz metade do
            # catálogo sumir sem erro nenhum.
            if isinstance(node, list):
                for entry in node:
                    yield PriceEntry(craftable, None, _to_price(entry))
            elif isinstance(node, dict):
                for priceindex, entry in node.items():
                    yield PriceEntry(craftable, str(priceindex), _to_price(entry))

    def to_keys(self, price: BptfPrice | None) -> float | None:
        """Converte para chaves, ou None se não der.

        USD não é convertido de propósito: é o sinal candidato de preço
        derivado da Steam Market (guarda 4). Converter esconderia justamente
        o que o spike precisa medir.
        """
        if price is None:
            return None
        if price.currency == "keys":
            return price.value
        if price.currency == "metal":
            return price.value / self._key_in_refined
        return None

    def lookup(
        self,
        item_name: str,
        quality_id: int,
        craftable: bool = True,
        priceindex: str | None = None,
    ) -> BptfPrice | None:
        for entry in self._iter_entries(item_name, quality_id):
            if entry.craftable != craftable:
                continue
            if priceindex is not None and entry.priceindex != priceindex:
                continue
            if priceindex is None and entry.priceindex is not None:
                continue
            return entry.price
        return None

    def value_range_keys(self, item_name: str, quality_id: int) -> ValueRange | None:
        """Faixa de valor sobre TODAS as interpretações do nome.

        É esta faixa que a poda das três vias consome: o mínimo é o pior
        cenário possível, o máximo é o melhor.
        """
        values = [
            keys
            for entry in self._iter_entries(item_name, quality_id)
            if (keys := self.to_keys(entry.price)) is not None and keys > 0
        ]
        if not values:
            return None
        return ValueRange(min_keys=min(values), max_keys=max(values))


class BackpackTfClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("BPTF_API_KEY não configurada")
        self._api_key = api_key
        self._http = client or httpx.Client(
            timeout=180.0,  # IGetPrices devolve dezenas de MB
            headers={"User-Agent": "tf2price-spike/0.1"},
            follow_redirects=True,
        )

    def _get(self, path: str) -> dict[str, Any]:
        response = self._http.get(
            f"{BASE}/{path}", params={"key": self._api_key, "appid": APPID}
        )
        response.raise_for_status()
        return response.json()

    def currencies(self) -> Currencies:
        return Currencies.from_payload(self._get("IGetCurrencies/v1"))

    def prices_payload(self) -> dict[str, Any]:
        return self._get("IGetPrices/v4")
