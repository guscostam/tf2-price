from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx

BASE = "https://backpack.tf/api"
APPID = 440


@dataclass(frozen=True)
class BptfPrice:
    """Uma entrada de preço do índice da backpack.tf.

    `value` é o piso da faixa sugerida e é o único que entra no cálculo.
    `value_high` fica registrado porque é o que revela uma faixa larga
    demais para sustentar decisão.
    """

    value: float
    value_high: float | None
    currency: str
    last_update: int


@dataclass(frozen=True)
class Currencies:
    key_in_refined: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Currencies":
        # Aqui existia `key_in_usd`, lido de `price.usd`. A bp.tf deixou de
        # mandar esse campo (conferido em 22/09/2026) e ele valia 0 sem
        # ninguém perceber. O dólar da chave agora vem do `IGetPrices`: ver
        # `PriceIndex.key_in_usd`.
        price = payload["response"]["currencies"]["keys"]["price"]
        return cls(key_in_refined=float(price["value"]))


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


def _agora_utc() -> datetime:
    # Mesmo formato de `db.agora()` (UTC ingênuo), sem uma fonte de dados
    # importar o módulo do banco.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _positivo_ou_none(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


class PriceIndex:
    """O índice de preços da backpack.tf, indexado para consulta."""

    def __init__(
        self,
        items: dict[str, Any],
        key_in_refined: float,
        raw_usd_value: float | None = None,
        usd_currency: str | None = None,
        carregado_em: datetime | None = None,
    ) -> None:
        if key_in_refined <= 0:
            raise ValueError("key_in_refined tem que ser positivo")
        self._items = items
        self._key_in_refined = key_in_refined
        self._raw_usd_value = raw_usd_value
        self._usd_currency = usd_currency
        # Quando o payload foi baixado. O índice é carregado uma vez por
        # processo e nunca renovado, então esta é a idade do dólar da chave.
        self.carregado_em = carregado_em or _agora_utc()

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        key_in_refined: float,
        carregado_em: datetime | None = None,
    ) -> "PriceIndex":
        response = payload["response"]
        return cls(
            response["items"],
            key_in_refined,
            # Lido com tolerância: um campo de dólar estragado custa só a
            # referência, nunca o índice inteiro.
            raw_usd_value=_positivo_ou_none(response.get("raw_usd_value")),
            usd_currency=response.get("usd_currency"),
            carregado_em=carregado_em,
        )

    def item_names(self) -> set[str]:
        return set(self._items)

    @property
    def key_in_refined(self) -> float:
        return self._key_in_refined

    def key_in_usd(self) -> float | None:
        """Dólar de uma chave segundo a bp.tf, ou None se não der para saber.

        `raw_usd_value` é o dólar de uma unidade de `usd_currency`, que em
        22/09/2026 era `metal` (o refined): 0.026 × 64.11 ref ≈ US$ 1,67.
        Outra unidade é recusa, não conversão: sem saber o que ela vale em
        chaves, qualquer conta aqui sairia errada em silêncio.
        """
        if self._usd_currency != "metal" or self._raw_usd_value is None:
            return None
        return self._raw_usd_value * self._key_in_refined

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

class BackpackTfClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("BPTF_API_KEY não configurada")
        self._api_key = api_key
        self._http = client or httpx.Client(
            # IGetPrices é grande: medido em 21/09/2026, 5,0 MB de JSON em
            # ~2s. O timeout largo é folga para um dia ruim da bp.tf, não a
            # medida do payload de hoje.
            timeout=180.0,
            headers={"User-Agent": "tf2price/0.1"},
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
