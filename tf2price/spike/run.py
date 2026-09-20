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

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH
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

# Trava de segurança da passada rasa: a Steam só interrompe a paginação por
# "sem resultados" ou por total_count, e ambos podem falhar juntos (ex.: a
# API degrada e devolve total_count=0 com results não vazio). Esse teto
# independe dos outros dois e garante que o loop sempre termina, mesmo
# contra um endpoint rate-limited.
#
# Dimensionado contra a API real, não contra estimativa: medido em
# 2026-09-19, a busca devolve 10 itens por página (o parâmetro `count` é
# ignorado) e o mercado de TF2 anuncia 41.080 nomes, ou seja ~4.108
# páginas. 6.000 dá ~46% de folga para o mercado crescer sem que o teto
# passe a truncar uma execução saudável.
MAX_SHALLOW_PAGES = 6000


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
    args = parser.parse_args(argv)

    # Validação antes de qualquer rede. Um --threshold negativo faz
    # (1 - threshold) > 1, o que SOBE o piso da poda em vez de baixá-lo e
    # fabrica classificações GARANTIDAS — falsos positivos, exatamente o
    # erro que este spike existe para não cometer. Um --deep-limit negativo
    # fatiaria a lista de alvos pelo lado errado, em silêncio.
    if not 0 <= args.threshold < 1:
        parser.error(f"--threshold precisa estar em [0, 1); recebi {args.threshold}")
    if args.deep_limit < 0:
        parser.error(f"--deep-limit não pode ser negativo; recebi {args.deep_limit}")
    if args.max_pages < 0:
        parser.error(f"--max-pages não pode ser negativo; recebi {args.max_pages}")
    if args.min_interval < 0:
        parser.error(f"--min-interval não pode ser negativo; recebi {args.min_interval}")

    return args


def _shallow_scan(
    steam: SteamClient, max_pages: int
) -> tuple[list[SearchResult], int]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    start = 0
    total = 0
    pages = 0

    while True:
        try:
            page = steam.search_page(start=start)
        except (RuntimeError, httpx.HTTPError) as error:
            # Escopo deliberadamente estreito, igual ao do fetch profundo:
            # um AttributeError é bug e precisa continuar estourando alto.
            # Uma falha de rede não pode jogar fora as páginas já coletadas.
            print(
                f"  AVISO: página {pages + 1} falhou ({error}).\n"
                f"  AVISO: PASSADA RASA INTERROMPIDA — catálogo PARCIAL com "
                f"{len(results)} de {total or '?'} nomes. "
                f"As contagens do relatório NÃO cobrem o mercado inteiro.",
                file=sys.stderr,
                flush=True,
            )
            break

        total = page.total_count or total
        if not page.results:
            break

        # Deduplica por hash_name mantendo a primeira ocorrência. Com a
        # ordenação estável por nome a deriva entre páginas é improvável,
        # mas duplicata inflaria as contagens do veredito. Cinto e
        # suspensório. `start` continua avançando pelo tamanho da página,
        # que é o que a Steam pagina — não pelo que sobrou aqui.
        for result in page.results:
            if result.hash_name in seen:
                continue
            seen.add(result.hash_name)
            results.append(result)

        start += len(page.results)
        pages += 1
        print(f"  página {pages}: {len(results)}/{total} nomes", flush=True)

        if max_pages and pages >= max_pages:
            break
        if total and start >= total:
            break
        if pages >= MAX_SHALLOW_PAGES:
            print(
                "  aviso: passada rasa interrompida no teto de segurança "
                f"({MAX_SHALLOW_PAGES} páginas); resultado incompleto.",
                file=sys.stderr,
            )
            break

    return results, total


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()

    api_key = os.getenv("BPTF_API_KEY", "").strip()
    if not api_key:
        print("BPTF_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    # Cria o diretório de saída antes de qualquer chamada de rede: uma
    # execução completa leva 15-30 min, e descobrir só no final que --out
    # aponta para um caminho inválido jogaria tudo fora.
    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Não foi possível criar o diretório de saída {out_dir}: {error}", file=sys.stderr)
        return 1

    # Mesmo princípio do diretório de saída: o mapa de efeitos só seria lido
    # no fetch profundo, ~15 min depois do início, no primeiro Unusual — e
    # FileNotFoundError não é capturado pelo except do laço. Descobrir a
    # ausência ali jogaria fora toda a passada rasa, a parte cara.
    if not DEFAULT_EFFECTS_PATH.exists():
        print(
            f"Mapa de efeitos ausente: {DEFAULT_EFFECTS_PATH}\n"
            "Gere-o antes de rodar o spike:\n"
            "  .venv/Scripts/python scripts/fetch_effects.py",
            file=sys.stderr,
        )
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
    deep_done = 0
    deep_error: str | None = None
    interrupcao: KeyboardInterrupt | None = None
    # O estágio profundo inteiro fica embrulhado: a passada rasa é a parte
    # cara (~11 min) e qualquer exceção aqui a descartaria junto com o
    # relatório. Escrever o que já temos vale mais do que morrer limpo.
    # O except estreito de dentro do laço continua sendo o caminho normal
    # para falhas de rede de uma listagem isolada.
    try:
        for position, target in enumerate(targets, start=1):
            print(f"  [{position}/{len(targets)}] {target.hash_name}", flush=True)
            try:
                listings = steam.listings(target.hash_name)
            except (RuntimeError, httpx.HTTPError) as error:
                # Uma listagem que falha não pode derrubar a varredura inteira.
                print(f"    falhou: {error}", file=sys.stderr)
                continue
            opportunities.extend(resolve_deep(target, listings, index, key_brl))
            deep_done += 1
    except KeyboardInterrupt as error:
        # Ctrl-C não é Exception e escaparia do handler abaixo, descartando
        # os ~11 min já gastos na passada rasa. Quem babá uma execução de
        # meia hora e decide parar antes quer o resultado parcial, não um
        # traceback. A interrupção é guardada e relançada depois de o
        # relatório estar no disco — parar cedo não é sucesso.
        interrupcao = error
        deep_error = "KeyboardInterrupt: interrompido pelo usuário (Ctrl-C)"
        print(
            f"ERRO: fetch profundo interrompido em {deep_done}/{len(targets)}: "
            f"{deep_error}\nO relatório será escrito assim mesmo, marcado "
            "como incompleto.",
            file=sys.stderr,
            flush=True,
        )
    except Exception as error:  # noqa: BLE001 - relatório antes de morrer
        deep_error = f"{type(error).__name__}: {error}"
        print(
            f"ERRO: fetch profundo interrompido em {deep_done}/{len(targets)}: "
            f"{deep_error}\nO relatório será escrito assim mesmo, marcado "
            "como incompleto.",
            file=sys.stderr,
            flush=True,
        )

    market_derived = analyse_market_derived(
        usd_items=collect_usd_items(results, index),
        raw_usd_per_refined=raw_usd_per_refined,
        key_in_refined=currencies.key_in_refined,
        key_brl=key_brl,
    )

    markdown = render_markdown(
        opportunities=opportunities,
        key_brl=key_brl,
        key_median_brl=key_median_brl,
        total_names=total_names,
        unmatched=outcome.unmatched,
        guaranteed_count=len(guaranteed),
        candidate_count=len(candidates),
        # Quantas candidatas realmente foram buscadas, não quantas estavam
        # na fila: um estágio interrompido não pode parecer completo.
        deep_fetched_count=deep_done,
        requests_made=limiter.requests,
        first_429_after=limiter.first_429_after,
        market_derived=market_derived,
    )

    avisos: list[str] = []
    if total_names and len(results) < total_names:
        avisos.append(
            f"A passada rasa coletou {len(results)} nomes distintos de "
            f"{total_names} anunciados pela Steam. O catálogo está PARCIAL "
            "(página com falha ou deriva de paginação): as contagens abaixo "
            "são um piso, não o mercado inteiro."
        )
    if deep_error is not None:
        avisos.append(
            f"O fetch profundo foi INTERROMPIDO em {deep_done} de "
            f"{len(targets)} candidatas por `{deep_error}`. As candidatas "
            "restantes não foram avaliadas e o veredito abaixo se apoia "
            "numa amostra menor do que a planejada."
        )
    if avisos:
        cabecalho = ["> **AVISO: EXECUÇÃO INCOMPLETA.**", ">"]
        for aviso in avisos:
            cabecalho.append(f"> - {aviso}")
        cabecalho.append("")
        markdown = "\n".join(cabecalho) + "\n" + markdown

    (out_dir / "relatorio.md").write_text(markdown, encoding="utf-8")
    (out_dir / "oportunidades.csv").write_text(
        render_csv(opportunities), encoding="utf-8"
    )

    print()
    print(f"Veredito: {decide(opportunities).value}")
    print(f"Requisições: {limiter.requests} | 429s: {limiter.throttled}")
    print(f"Relatório: {out_dir / 'relatorio.md'}")
    # Relatório no disco: agora sim a interrupção pode seguir seu curso. Não
    # engolir o Ctrl-C é o que mantém a execução parada cedo como
    # interrupção, e não como sucesso.
    if interrupcao is not None:
        print(
            "Execução INTERROMPIDA pelo usuário: relatório parcial escrito.",
            file=sys.stderr,
            flush=True,
        )
        raise interrupcao
    if avisos:
        print("Execução INCOMPLETA: veja os avisos no topo do relatório.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
