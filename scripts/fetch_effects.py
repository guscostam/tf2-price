"""Gera tf2price/data/effects.json a partir do schema oficial do TF2.

Roda uma vez. Precisa de STEAM_API_KEY (grátis em
https://steamcommunity.com/dev/apikey).

    .venv/Scripts/python scripts/fetch_effects.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

SCHEMA_URL = "https://api.steampowered.com/IEconItems_440/GetSchemaOverview/v0001/"
DESTINO = Path(__file__).resolve().parent.parent / "tf2price" / "data" / "effects.json"


def main() -> int:
    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    if not api_key:
        print("STEAM_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    response = httpx.get(
        SCHEMA_URL, params={"key": api_key, "language": "en"}, timeout=60.0
    )
    response.raise_for_status()

    particles = response.json()["result"]["attribute_controlled_attached_particles"]
    mapa = {str(p["name"]): int(p["id"]) for p in particles}

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(mapa, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{len(mapa)} efeitos gravados em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
