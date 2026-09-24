"""O que entra na varredura: cosméticos Unusual, e só eles.

Taunts, armas, war paints e Strange Unusual ficam de fora por decisão do
dono do projeto. O critério vem do schema da Valve (classe e slot do item),
e não de uma lista de exclusão por nome, que sempre deixaria algum escapar.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from tf2price.domain.identity import (
    QUALITY_PREFIXES,
    is_unusual_name,
    parse_market_hash_name,
)

COSMETICOS_PATH = Path(__file__).resolve().parent.parent / "data" / "cosmeticos.json"
COSMETICOS_DEFINDEX_PATH = COSMETICOS_PATH.with_name("cosmeticos_defindices.json")

# `tf_wearable` sozinho não basta: no schema, as provocações também são
# `tf_wearable` (slot `taunt`), e alguns itens de arma também (Gunboats,
# Razorback: slot `secondary`). Cosmético de verdade é cabeça ou misc.
SLOTS_DE_COSMETICO = frozenset({"head", "misc"})

_QUALIDADE_UNUSUAL = QUALITY_PREFIXES["Unusual"]


def nomes_de_cosmeticos(itens: Iterable[dict[str, Any]]) -> list[str]:
    """Nomes base dos cosméticos no schema, ordenados e sem repetição.

    O mesmo nome aparece em vários defindex (versões promocionais, de
    ferramenta), e o que casa com o nome da Steam é `item_name`.
    """
    return sorted({
        str(item["item_name"])
        for item in itens
        if item.get("item_class") == "tf_wearable"
        and item.get("item_slot") in SLOTS_DE_COSMETICO
        and item.get("item_name")
    })


def defindices_de_cosmeticos(itens: Iterable[dict[str, Any]]) -> dict[str, list[int]]:
    """Todos os IDs de schema por nome cosmético, inclusive nomes repetidos."""
    ids: dict[str, set[int]] = {}
    for item in itens:
        if item.get("item_class") != "tf_wearable" or item.get("item_slot") not in SLOTS_DE_COSMETICO:
            continue
        nome, defindex = item.get("item_name"), item.get("defindex")
        if (not isinstance(nome, str) or not nome or not isinstance(defindex, int)
                or isinstance(defindex, bool) or defindex <= 0):
            continue
        ids.setdefault(nome, set()).add(defindex)
    return {nome: sorted(ids[nome]) for nome in sorted(ids)}


@lru_cache(maxsize=4)
def carregar_cosmeticos(path: Path = COSMETICOS_PATH) -> frozenset[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"cosmeticos.json não encontrado em {path}. "
            "Rode: .venv/Scripts/python scripts/fetch_cosmeticos.py"
        )
    return frozenset(json.loads(path.read_text(encoding="utf-8")))


def e_cosmetico_unusual(hash_name: str, cosmeticos: frozenset[str] | None = None) -> bool:
    if not is_unusual_name(hash_name):
        return False
    ident = parse_market_hash_name(hash_name)
    # Qualidade dupla: o parser consome um prefixo só. `Strange Unusual X`
    # sai com qualidade Strange; `Unusual Strange X` sai com base `Strange X`.
    if ident.quality_id != _QUALIDADE_UNUSUAL:
        return False
    if ident.killstreak or ident.australium or ident.festivized or ident.wear:
        return False
    if ident.base_name.startswith(("Taunt:", "Unusual ", "Strange ")):
        return False
    conjunto = carregar_cosmeticos() if cosmeticos is None else cosmeticos
    return ident.base_name in conjunto
