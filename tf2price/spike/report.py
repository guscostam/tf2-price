from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from statistics import median

from tf2price.domain.money import Brl
from tf2price.domain.valuation import Guard
from tf2price.spike.pipeline import Opportunity

STRONG_DISCOUNT = 0.20
MIN_MEAN_DISCOUNT_BRL = Brl.from_float(50.00)
MIN_STRONG_COUNT_GREEN = 10
MIN_STRONG_COUNT_YELLOW = 3
DISPLAY_BUCKETS = (0.15, 0.25, 0.40)

# Análise da guarda 4
NEAR_15PCT_TOLERANCE = 0.03
MIN_USD_SAMPLE = 30
MIN_FRACTION_NEAR = 0.5


class Verdict(str, Enum):
    GREEN = "VERDE"
    YELLOW = "AMARELO"
    RED = "VERMELHO"


def net_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Oportunidades líquidas: passaram nas guardas e têm desconto real."""
    return [
        o for o in opportunities if o.guard is Guard.OK and o.valuation.discount > 0
    ]


def _best_per_name(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Colapsa para uma linha por hash_name: a de maior desconto."""
    melhores: dict[str, Opportunity] = {}
    for o in opportunities:
        atual = melhores.get(o.hash_name)
        if atual is None or o.valuation.discount > atual.valuation.discount:
            melhores[o.hash_name] = o
    return list(melhores.values())


def decide(opportunities: list[Opportunity]) -> Verdict:
    """Veredito do §8 do spec, sobre as líquidas.

    Conta NOMES distintos, não linhas. As duas fontes de oportunidade têm
    granularidades incompatíveis: `guaranteed_opportunities` emite uma linha
    por hash_name, enquanto `resolve_deep` emite uma por listagem, e um
    fetch profundo traz até 100 listagens do MESMO item. Contando linhas,
    um único chapéu subprecificado com 20 listagens baratas já dispararia
    "construa a aplicação" sozinho — exatamente o falso positivo que o
    spec manda evitar. Os cortes continuam os mesmos; só a unidade muda.
    """
    strong = [
        o
        for o in net_opportunities(opportunities)
        if o.valuation.discount >= STRONG_DISCOUNT
    ]

    if not strong:
        return Verdict.RED

    distintas = _best_per_name(strong)
    mean_cents = sum(o.absolute_discount.cents for o in distintas) / len(distintas)

    if (
        len(distintas) >= MIN_STRONG_COUNT_GREEN
        and mean_cents >= MIN_MEAN_DISCOUNT_BRL.cents
    ):
        return Verdict.GREEN
    if len(distintas) >= MIN_STRONG_COUNT_YELLOW:
        return Verdict.YELLOW
    return Verdict.RED


@dataclass(frozen=True)
class MarketDerivedAnalysis:
    sample_size: int
    median_discount: float | None
    fraction_near_15pct: float
    hypothesis_supported: bool


def analyse_market_derived(
    usd_items: list[tuple[float, Brl]],
    raw_usd_per_refined: float,
    key_in_refined: float,
    key_brl: Brl,
) -> MarketDerivedAnalysis:
    """Testa a hipótese da guarda 4 sem consultar câmbio externo.

    O câmbio USD->BRL sai da própria economia da Steam: a bp.tf diz quantos
    dólares vale um refined, e a Steam diz quantos reais vale uma chave.

    Se os preços em USD da bp.tf forem derivados da Steam Market menos 15%,
    o desconto desses itens vai se agrupar perto de 0,15.
    """
    usd_per_key = raw_usd_per_refined * key_in_refined
    if usd_per_key <= 0:
        return MarketDerivedAnalysis(0, None, 0.0, False)

    brl_per_usd = key_brl.as_float / usd_per_key

    discounts: list[float] = []
    for usd_value, steam_price in usd_items:
        fair_cents = round(usd_value * brl_per_usd * 100)
        if fair_cents <= 0:
            continue
        discounts.append(1 - steam_price.cents / fair_cents)

    if not discounts:
        return MarketDerivedAnalysis(0, None, 0.0, False)

    near = sum(1 for d in discounts if abs(d - 0.15) <= NEAR_15PCT_TOLERANCE)
    fraction = near / len(discounts)

    return MarketDerivedAnalysis(
        sample_size=len(discounts),
        median_discount=median(discounts),
        fraction_near_15pct=fraction,
        hypothesis_supported=(
            len(discounts) >= MIN_USD_SAMPLE and fraction >= MIN_FRACTION_NEAR
        ),
    )


def render_csv(opportunities: list[Opportunity]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "hash_name",
            "listing_id",
            "effect",
            "craftable",
            "steam_total_brl",
            "fair_value_brl",
            "discount_pct",
            "absolute_discount_brl",
            "resale_profit_brl",
            "classification",
            "guard",
            "deep_fetched",
            "steam_url",
        ]
    )
    for o in sorted(opportunities, key=lambda x: x.valuation.discount, reverse=True):
        writer.writerow(
            [
                o.hash_name,
                o.listing_id or "",
                o.effect or "",
                o.craftable if o.craftable is not None else "",
                f"{o.steam_total.as_float:.2f}",
                f"{o.valuation.fair_value.as_float:.2f}",
                f"{o.valuation.discount * 100:.1f}",
                f"{o.absolute_discount.as_float:.2f}",
                f"{o.valuation.resale_profit.as_float:.2f}",
                o.classification.value,
                o.guard.value,
                o.deep_fetched,
                o.steam_url,
            ]
        )
    return buffer.getvalue()


def render_markdown(
    opportunities: list[Opportunity],
    key_brl: Brl,
    key_median_brl: Brl,
    total_names: int,
    unmatched: list[str],
    guaranteed_count: int,
    candidate_count: int,
    deep_fetched_count: int,
    requests_made: int,
    first_429_after: int | None,
    market_derived: MarketDerivedAnalysis | None,
) -> str:
    net = net_opportunities(opportunities)
    verdict = decide(opportunities)

    nomes_liquidos = _best_per_name(net)

    def faixa(minimo: float) -> int:
        return sum(1 for o in net if o.valuation.discount >= minimo)

    def faixa_nomes(minimo: float) -> int:
        return len({o.hash_name for o in net if o.valuation.discount >= minimo})

    linhas: list[str] = []
    add = linhas.append

    add("# Relatório do spike de arbitragem TF2")
    add("")
    add(f"## Veredito: **{verdict.value}**")
    add("")
    add("### Oportunidades")
    add("")
    add("| Faixa de desconto | Líquidas | Nomes distintos |")
    add("|---|---|---|")
    for bucket in DISPLAY_BUCKETS:
        add(f"| >= {bucket * 100:.0f}% | {faixa(bucket)} | {faixa_nomes(bucket)} |")
    add("")
    add(f"- Brutas avaliadas: {len(opportunities)}")
    add(
        f"- Líquidas (pós-guardas, desconto positivo): {len(net)} oportunidades "
        f"líquidas em {len(nomes_liquidos)} nomes distintos"
    )
    add(
        "  (uma listagem é uma linha; um fetch profundo traz até 100 listagens "
        "do mesmo item, então o veredito conta nomes, não linhas)"
    )

    if net:
        melhor = max(net, key=lambda o: o.absolute_discount.cents)
        media = sum(o.absolute_discount.cents for o in net) / len(net)
        add(f"- Desconto absoluto médio: {Brl.from_cents(round(media))}")
        add(f"- Maior desconto absoluto: {melhor.absolute_discount} em `{melhor.hash_name}`")

    add("")
    add("### Motivos de reprovação")
    add("")
    add("| Guarda | Itens |")
    add("|---|---|")
    for guard, total in Counter(
        o.guard for o in opportunities if o.guard is not Guard.OK
    ).most_common():
        add(f"| {guard.value} | {total} |")

    add("")
    add("**Excluídos ANTES das guardas** (não aparecem na tabela acima, e por")
    add("isso a tabela subestima o quanto de sinal aparente foi descartado):")
    add("")
    usd_excluidos = market_derived.sample_size if market_derived is not None else 0
    add(
        f"- Itens precificados em USD: {usd_excluidos}. USD não converte para "
        "chaves, então eles caem em 'nomes não casados' na passada rasa e "
        "nunca chegam à guarda `derivado_da_steam`."
    )
    sem_fetch = max(candidate_count - deep_fetched_count, 0)
    add(
        f"- Candidatas sem fetch profundo: {sem_fetch}. Ficaram com as "
        "incógnitas por resolver e não viraram oportunidade nenhuma, então a "
        "guarda `incognitas_nao_resolvidas` também não as conta."
    )

    add("")
    add("### Varredura")
    add("")
    add(f"- Nomes na busca da Steam: {total_names}")
    add(f"- Garantidas: {guaranteed_count}")
    add(f"- Candidatas: {candidate_count}")
    add(f"- Candidatas com fetch profundo: {deep_fetched_count}")
    add(f"- Nomes não casados: {len(unmatched)}")
    add(f"- Requisições feitas: {requests_made}")
    add(
        f"- Primeiro 429 após: "
        f"{first_429_after if first_429_after is not None else 'nenhum 429'}"
    )
    add(f"- Chave (listagem mais barata): {key_brl}")
    add(f"- Chave (mediana 24h): {key_median_brl}")

    add("")
    add("### Hipótese da guarda 4 — preços derivados da Steam")
    add("")
    if market_derived is None:
        add("Não analisada nesta execução.")
    else:
        status = "CONFIRMADA" if market_derived.hypothesis_supported else "REFUTADA"
        add(f"**{status}**")
        add("")
        add(f"- Itens precificados em USD: {market_derived.sample_size}")
        mediana = market_derived.median_discount
        add(f"- Desconto mediano: {mediana * 100:.1f}%" if mediana is not None else "- Sem dados")
        add(f"- Fração perto de 15%: {market_derived.fraction_near_15pct * 100:.1f}%")
        if not market_derived.hypothesis_supported:
            add("")
            add(
                "> Detecção por moeda USD não se sustenta. Alternativa: cruzar "
                "contra a lista `/market` da própria backpack.tf."
            )

    add("")
    add("### Top 20 oportunidades líquidas")
    add("")
    add("| Item | Efeito | Pago | Justo | Desc. | Lucro revenda |")
    add("|---|---|---|---|---|---|")
    for o in sorted(net, key=lambda x: x.valuation.discount, reverse=True)[:20]:
        add(
            f"| [{o.hash_name}]({o.steam_url}) | {o.effect or '-'} | {o.steam_total} | "
            f"{o.valuation.fair_value} | {o.valuation.discount * 100:.1f}% | "
            f"{o.valuation.resale_profit} |"
        )

    add("")
    add("### Nomes não casados, por frequência")
    add("")
    add("| Nome | Ocorrências |")
    add("|---|---|")
    for nome, total in Counter(unmatched).most_common(50):
        add(f"| {nome} | {total} |")

    return "\n".join(linhas) + "\n"
