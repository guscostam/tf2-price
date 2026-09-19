"""Execução única do spike de validação.

    .venv/Scripts/python -m tf2price.spike.run

Passada rasa em todo o mercado de TF2, fetch profundo nas melhores
candidatas Unusual, relatório com veredito.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SearchResult, SteamClient
from tf2price.spike.pipeline import (
    collect_usd_items,
    deep_targets,
    guaranteed_opportunities,
    resolve_deep,
    shallow_pass,
)
from tf2price.spike.report import (
    analyse_market_derived,
    decide,
    render_csv,
    render_markdown,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spike de arbitragem TF2")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.15,
        help="desconto mínimo para a poda considerar oportunidade (padrão 0.15)",
    )
    parser.add_argument(
        "--deep-limit",
        type=int,
        default=20,
        help="quantas candidatas recebem fetch profundo (padrão 20)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="limite de páginas da passada rasa; 0 = tudo. Use 2 ou 3 para ensaiar.",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=3.0,
        help="segundos entre requisições à Steam (padrão 3.0)",
    )
    parser.add_argument("--out", default="out", help="diretório de saída (padrão out)")
    return parser.parse_args(argv)


def _shallow_scan(
    steam: SteamClient, max_pages: int
) -> tuple[list[SearchResult], int]:
    results: list[SearchResult] = []
    start = 0
    total = 0
    pages = 0

    while True:
        page = steam.search_page(start=start)
        total = page.total_count or total
        if not page.results:
            break

        results.extend(page.results)
        start += len(page.results)
        pages += 1
        print(f"  página {pages}: {len(results)}/{total} nomes", flush=True)

        if max_pages and pages >= max_pages:
            break
        if total and start >= total:
            break

    return results, total


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()

    api_key = os.getenv("BPTF_API_KEY", "").strip()
    if not api_key:
        print("BPTF_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    bptf = BackpackTfClient(api_key)

    print("Moedas da backpack.tf...")
    currencies = bptf.currencies()
    print(f"  chave = {currencies.key_in_refined} ref / US$ {currencies.key_in_usd}")

    print("Índice de preços (dezenas de MB, pode demorar)...")
    payload = bptf.prices_payload()
    index = PriceIndex.from_payload(payload, currencies.key_in_refined)
    raw_usd_per_refined = float(payload["response"].get("raw_usd_value", 0.0))
    print(f"  {len(index.item_names())} itens")

    limiter = RateLimiter(min_interval_s=args.min_interval)
    steam = SteamClient(limiter)

    print("Preço da chave na Steam...")
    key_brl = steam.key_price()
    key_median_brl = steam.key_median_price()
    print(f"  chave = {key_brl} (mediana 24h {key_median_brl})")

    print("Passada rasa...")
    results, total_names = _shallow_scan(steam, args.max_pages)

    outcome = shallow_pass(results, index, key_brl, args.threshold)
    guaranteed = [
        c for c in outcome.candidates if c.classification is Classification.GUARANTEED
    ]
    candidates = [
        c for c in outcome.candidates if c.classification is Classification.CANDIDATE
    ]
    print(
        f"  garantidas={len(guaranteed)} candidatas={len(candidates)} "
        f"não casados={len(outcome.unmatched)}"
    )

    opportunities = guaranteed_opportunities(outcome.candidates, index, key_brl)

    targets = deep_targets(outcome.candidates, key_brl, args.deep_limit)
    print(f"Fetch profundo em {len(targets)} candidatas...")
    for position, target in enumerate(targets, start=1):
        print(f"  [{position}/{len(targets)}] {target.hash_name}", flush=True)
        try:
            listings = steam.listings(target.hash_name)
        except (RuntimeError, httpx.HTTPError) as error:
            # Uma listagem que falha não pode derrubar a varredura inteira.
            print(f"    falhou: {error}", file=sys.stderr)
            continue
        opportunities.extend(resolve_deep(target, listings, index, key_brl))

    market_derived = analyse_market_derived(
        usd_items=collect_usd_items(results, index),
        raw_usd_per_refined=raw_usd_per_refined,
        key_in_refined=currencies.key_in_refined,
        key_brl=key_brl,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "relatorio.md").write_text(
        render_markdown(
            opportunities=opportunities,
            key_brl=key_brl,
            key_median_brl=key_median_brl,
            total_names=total_names,
            unmatched=outcome.unmatched,
            guaranteed_count=len(guaranteed),
            candidate_count=len(candidates),
            deep_fetched_count=len(targets),
            requests_made=limiter.requests,
            first_429_after=limiter.first_429_after,
            market_derived=market_derived,
        ),
        encoding="utf-8",
    )
    (out_dir / "oportunidades.csv").write_text(
        render_csv(opportunities), encoding="utf-8"
    )

    print()
    print(f"Veredito: {decide(opportunities).value}")
    print(f"Requisições: {limiter.requests} | 429s: {limiter.throttled}")
    print(f"Relatório: {out_dir / 'relatorio.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
