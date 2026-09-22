"""Gera tf2price/data/cosmeticos.json a partir do schema oficial do TF2.

Roda quando o TF2 ganha cosméticos novos. Precisa de STEAM_API_KEY (grátis em
https://steamcommunity.com/dev/apikey).

    .venv/Scripts/python scripts/fetch_cosmeticos.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from tf2price.varredura.escopo import COSMETICOS_PATH, nomes_de_cosmeticos

SCHEMA_ITEMS_URL = "https://api.steampowered.com/IEconItems_440/GetSchemaItems/v0001/"


def main() -> int:
    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    if not api_key:
        print("STEAM_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    itens: list[dict] = []
    inicio: int | None = 0
    while inicio is not None:
        resposta = httpx.get(
            SCHEMA_ITEMS_URL,
            params={"key": api_key, "language": "en", "start": inicio},
            timeout=60.0,
        )
        resposta.raise_for_status()
        resultado = resposta.json()["result"]
        itens.extend(resultado.get("items") or [])
        inicio = resultado.get("next")
        if inicio is not None:
            time.sleep(1.0)

    nomes = nomes_de_cosmeticos(itens)
    destino = Path(COSMETICOS_PATH)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(nomes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(itens)} itens lidos, {len(nomes)} cosméticos gravados em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
