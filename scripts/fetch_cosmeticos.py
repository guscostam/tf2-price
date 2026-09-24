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

from tf2price.varredura.escopo import (
    COSMETICOS_DEFINDEX_PATH,
    COSMETICOS_PATH,
    defindices_de_cosmeticos,
    nomes_de_cosmeticos,
)

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
        try:
            resposta = httpx.get(
                SCHEMA_ITEMS_URL,
                params={"key": api_key, "language": "en", "start": inicio},
                timeout=60.0,
            )
            resposta.raise_for_status()
        except httpx.HTTPError:
            # A URL da exceção contém a chave em query; não imprimi-la.
            print("Falha ao consultar o schema da Steam.", file=sys.stderr)
            return 1
        resultado = resposta.json()["result"]
        itens.extend(resultado.get("items") or [])
        inicio = resultado.get("next")
        if inicio is not None:
            time.sleep(1.0)

    nomes = nomes_de_cosmeticos(itens)
    defindices = defindices_de_cosmeticos(itens)
    if set(nomes) != set(defindices):
        print("Schema incompleto: cosmético sem defindex.", file=sys.stderr)
        return 1
    destino = Path(COSMETICOS_PATH)
    destino_ids = Path(COSMETICOS_DEFINDEX_PATH)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(nomes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    destino_ids.write_text(json.dumps(defindices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(itens)} itens lidos, {len(nomes)} cosméticos gravados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
