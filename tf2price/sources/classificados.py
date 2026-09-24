"""Leitura conservadora de vendas ativas no snapshot de classificados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import time
from typing import Any

import httpx

BASE = "https://backpack.tf/api/classifieds/listings/snapshot"
APPID = 440
REQUEST_TIMEOUT_S = 10.0
_ITEM_FIELDS = {"quality", "defindex", "quantity", "attributes"}
_ITEM_METADATA = {"id", "inventory", "level", "origin", "original_id"}
# Defaults vistos no schema de cosméticos e confirmados na resposta real.
# Outros atributos podem representar pintura, spell ou outra variante.
_ATTRS_PADRAO = {746: Decimal(1), 292: Decimal(64), 388: Decimal(64)}
_MAX_CURRENCY = Decimal(1_000_000)


@dataclass(frozen=True)
class Venda:
    chaves: Decimal
    metal: Decimal


@dataclass(frozen=True)
class SnapshotVendas:
    vendas: tuple[Venda, ...]
    criado_em: datetime


class ClassificadosLimitando(RuntimeError):
    """A API limitou a leitura; o coletor decide quando tentar novamente."""

    def __init__(self, retry_after_s: float | None) -> None:
        super().__init__("backpack.tf classifieds rate limit")
        self.retry_after_s = retry_after_s


def _decimal_nao_negativo(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def _venda_comparavel(row: dict[str, Any], effect_id: int) -> Venda | None:
    if row.get("intent") != "sell":
        return None
    item = row.get("item")
    currencies = row.get("currencies")
    if not isinstance(item, dict) or not isinstance(currencies, dict):
        raise ValueError("incomplete classifieds sell listing")
    # Não sabemos comparar spells, tintas, craftabilidade ou outras variantes
    # com a listagem Steam. Aceitar apenas o exemplar ordinário conhecido.
    if not _ITEM_FIELDS <= item.keys() or set(item) - _ITEM_FIELDS - _ITEM_METADATA:
        return None
    if item["quality"] != 5 or item["quantity"] != 1:
        return None
    if not isinstance(item["defindex"], int) or item["defindex"] <= 0:
        return None
    attrs = item["attributes"]
    if not isinstance(attrs, list):
        return None
    seen: set[int] = set()
    for attr in attrs:
        if not isinstance(attr, dict):
            return None
        attr_id = attr.get("defindex")
        if not isinstance(attr_id, int) or attr_id in seen:
            return None
        expected = Decimal(effect_id) if attr_id == 134 else _ATTRS_PADRAO.get(attr_id)
        if expected is None or _decimal_nao_negativo(attr.get("float_value")) != expected:
            return None
        seen.add(attr_id)
    if 134 not in seen:
        return None
    if not currencies or set(currencies) - {"keys", "metal"}:
        return None
    keys = _decimal_nao_negativo(currencies.get("keys", 0))
    metal = _decimal_nao_negativo(currencies.get("metal", 0))
    if (
        keys is None
        or metal is None
        or keys > _MAX_CURRENCY
        or metal > _MAX_CURRENCY
        or keys + metal <= 0
    ):
        return None
    return Venda(keys, metal)


def snapshot_para_vendas(payload: Any, sku: str, effect_id: int) -> SnapshotVendas:
    """Extrai vendas estritamente comparáveis; payload inválido não é ausência."""
    if (
        not isinstance(payload, dict)
        or payload.get("appid") != APPID
        or payload.get("sku") != sku
        or isinstance(payload.get("createdAt"), bool)
        or not isinstance(payload.get("createdAt"), int)
        or payload["createdAt"] <= 0
        or not isinstance(payload.get("listings"), list)
    ):
        raise ValueError("invalid classifieds snapshot")
    age_s = time.time() - payload["createdAt"]
    if age_s > 6 * 60 * 60 or age_s < -5 * 60:
        raise ValueError("stale or future classifieds snapshot")
    vendas: list[Venda] = []
    for row in payload["listings"]:
        if not isinstance(row, dict):
            raise ValueError("invalid classifieds listing")
        venda = _venda_comparavel(row, effect_id)
        if venda is not None:
            vendas.append(venda)
    criado_em = datetime.fromtimestamp(payload["createdAt"], timezone.utc).replace(tzinfo=None)
    return SnapshotVendas(tuple(vendas), criado_em)


def _retry_after(header: str | None) -> float | None:
    if header is None:
        return None
    try:
        seconds = float(header)
        return seconds if 0 <= seconds < float("inf") else None
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


class ClassificadosClient:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        if not token:
            raise ValueError("BPTF_USER_TOKEN não configurado")
        self._token = token
        self._http = client or httpx.Client(headers={"User-Agent": "tf2price/0.1"})

    def vendas(self, sku: str, effect_id: int) -> SnapshotVendas:
        try:
            response = self._http.get(
                BASE,
                params={"appid": APPID, "sku": sku},
                headers={"X-Auth-Token": self._token},
                timeout=REQUEST_TIMEOUT_S,
            )
        except httpx.HTTPError:
            raise RuntimeError("classificados indisponíveis") from None
        if response.status_code == 429:
            raise ClassificadosLimitando(_retry_after(response.headers.get("Retry-After")))
        if response.status_code != 200:
            raise RuntimeError("classificados indisponíveis")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("resposta inválida de classificados") from None
        return snapshot_para_vendas(payload, sku, effect_id)
