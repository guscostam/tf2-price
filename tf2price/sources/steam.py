from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter, backoff_delays

APPID = 440
CURRENCY_BRL = 7
BASE = "https://steamcommunity.com"
KEY_HASH_NAME = "Mann Co. Supply Crate Key"

UNUSUAL_EFFECT_PREFIX = "★ Unusual Effect: "
NOT_CRAFTABLE = "( Not Usable in Crafting )"
SPELL_PREFIX = "Halloween:"

_NON_NUMERIC = re.compile(r"[^\d,.]")

# Formatos pt-BR inequívocos aceitos por parse_price_text. Qualquer outra
# forma (ex.: "22.14", formato en-US) levanta ValueError em vez de ser
# interpretada errado silenciosamente.
_PTBR_THOUSANDS_AND_CENTS = re.compile(r"^\d{1,3}(\.\d{3})*,\d{2}$")
_PTBR_THOUSANDS_ONLY = re.compile(r"^\d{1,3}(\.\d{3})+$")
_PTBR_INTEGER = re.compile(r"^\d+$")


@dataclass(frozen=True)
class SearchResult:
    hash_name: str
    lowest_price: Brl
    sell_listings: int


@dataclass(frozen=True)
class SearchPage:
    total_count: int
    results: list[SearchResult]


@dataclass(frozen=True)
class Listing:
    listing_id: str
    total_price: Brl
    effect: str | None
    craftable: bool
    spelled: bool


def parse_price_text(text: str) -> Brl:
    """'R$ 1.234,50' -> Brl(123450).

    Com currency=7 a Steam responde no formato pt-BR: ponto para milhar,
    vírgula para decimal. Só aceitamos formas pt-BR inequívocas; qualquer
    outra coisa (ex.: en-US "22.14") levanta ValueError em vez de ser
    interpretada 100x errado silenciosamente — essa função precifica a
    chave, e um erro silencioso ali corrompe todo o relatório.
    """
    cleaned = _NON_NUMERIC.sub("", text)

    if _PTBR_THOUSANDS_AND_CENTS.match(cleaned):
        reais, cents = cleaned.replace(".", "").split(",")
        return Brl.from_cents(int(reais) * 100 + int(cents))

    if _PTBR_THOUSANDS_ONLY.match(cleaned):
        return Brl.from_cents(int(cleaned.replace(".", "")) * 100)

    if _PTBR_INTEGER.match(cleaned):
        return Brl.from_cents(int(cleaned) * 100)

    raise ValueError(f"texto de preço não está em formato pt-BR reconhecido: {text!r}")


def parse_search_page(payload: dict[str, Any]) -> SearchPage:
    # `sell_price` é lido como o preço em CENTAVOS já com a taxa do
    # comprador embutida — o equivalente, na busca, a
    # converted_price + converted_fee das listagens. Ele alimenta a poda, o
    # caminho garantido e a amostragem em USD, ou seja, a maior parte das
    # oportunidades líquidas. ATENÇÃO: isso é item de verificação da
    # execução real, não fato provado; se for o líquido do vendedor, todo
    # desconto da passada rasa está inflado em ~15%.
    results = [
        SearchResult(
            hash_name=row["hash_name"],
            lowest_price=Brl.from_cents(int(row["sell_price"])),
            sell_listings=int(row["sell_listings"]),
        )
        for row in (payload.get("results") or [])
    ]
    return SearchPage(total_count=int(payload.get("total_count", 0)), results=results)


def _descriptions_for(payload: dict[str, Any], asset_id: str) -> list[str] | None:
    """Busca as descrições de um asset dentro de assets[appid][contextid][id].

    O contextid varia, então varremos os contextos em vez de assumir "2".

    Retorna None quando o asset não foi encontrado em nenhum contexto —
    craftability é desconhecida nesse caso, o que é diferente de um asset
    encontrado sem nenhuma descrição (lista vazia).
    """
    contexts = (payload.get("assets") or {}).get(str(APPID)) or {}
    for context in contexts.values():
        asset = context.get(asset_id)
        if asset:
            return [str(d.get("value", "")) for d in (asset.get("descriptions") or [])]
    return None


def parse_listings(payload: dict[str, Any]) -> list[Listing]:
    listings: list[Listing] = []

    for listing_id, info in (payload.get("listinginfo") or {}).items():
        asset_id = str((info.get("asset") or {}).get("id", ""))

        descriptions = _descriptions_for(payload, asset_id)
        if descriptions is None:
            # Asset não encontrado em nenhum contexto: craftability é
            # desconhecida. Precificar como craftável seria um chute, então
            # pulamos — o mesmo tratamento dado a um preço não convertido.
            continue

        effect: str | None = None
        craftable = True
        spelled = False

        for value in descriptions:
            text = value.strip()
            if text.startswith(UNUSUAL_EFFECT_PREFIX):
                effect = text[len(UNUSUAL_EFFECT_PREFIX) :].strip()
            elif text == NOT_CRAFTABLE:
                craftable = False
            elif text.startswith(SPELL_PREFIX):
                spelled = True

        # converted_price + converted_fee é o que o COMPRADOR paga.
        # 'price' sozinho é o líquido do vendedor e infla todo desconto em ~15%.
        total = int(info.get("converted_price") or 0) + int(info.get("converted_fee") or 0)
        if total <= 0:
            # Sem preço convertido não dá para avaliar. Pular é mais honesto
            # do que avaliar errado.
            continue

        listings.append(
            Listing(
                listing_id=str(listing_id),
                total_price=Brl.from_cents(total),
                effect=effect,
                craftable=craftable,
                spelled=spelled,
            )
        )

    return listings


class SteamClient:
    def __init__(
        self,
        limiter: RateLimiter,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limiter = limiter
        self._sleep = sleep
        # Cache de instância: nunca compartilhado entre dois SteamClient.
        self._priceoverview_cache: dict[str, Any] | None = None
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price-spike/0.1"},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_reason = "sem tentativas"

        for delay in [0.0, *backoff_delays(5)]:
            if delay:
                self._sleep(delay)
            self._limiter.wait()

            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as error:
                # Falha de transporte (timeout, conexão, DNS, TLS, proxy):
                # httpx.TimeoutException é subclasse de TransportError, então
                # o catch cobre os dois. São falhas do canal, não do pedido —
                # repetir é a resposta certa. Não são throttle.
                last_reason = f"{type(error).__name__}: {error}"
                continue

            if response.status_code == 429:
                self._limiter.record_throttle()
                last_reason = "status 429"
                continue

            if response.status_code >= 500:
                # 5xx é a Steam falhando, não o pedido. Repetimos, mas NÃO
                # contamos como throttle: misturar 5xx com 429 corromperia a
                # medição de quantas requisições o IP aguenta antes do
                # primeiro 429, que é entregável do spike.
                last_reason = f"status {response.status_code}"
                continue

            # 4xx que não é 429 significa pedido errado: repetir só queima
            # orçamento de requisições. Falha na primeira tentativa.
            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Steam não respondeu após backoff (último: {last_reason})")

    def search_page(self, start: int, count: int = 100, query: str | None = None) -> SearchPage:
        """Uma página da busca de mercado, opcionalmente filtrada por texto.

        `query` é o parâmetro `query` da Steam: um filtro de TEXTO sobre o
        nome do item, não um filtro de qualidade. "Unusual" casa com
        qualquer `market_hash_name` que contenha a palavra — inclusive itens
        que não são da qualidade Unusual, se algum dia existir um nome assim
        — então ele só reduz o que entra na passada rasa; quem decide a
        qualidade de fato é o parser de identidade no fetch profundo
        (`parse_listings`, via `UNUSUAL_EFFECT_PREFIX`).

        Quando `query` é `None` ou string vazia, nenhum parâmetro `query` é
        enviado — vazio não é o mesmo que ausente: a forma ausente é o que
        varre o catálogo inteiro, e mandar `query=""` poderia se comportar
        diferente na API real.
        """
        params = {
            "appid": APPID,
            "norender": 1,
            "count": count,
            "start": start,
            "currency": CURRENCY_BRL,
            "l": "english",
            # Ordenação por preço decrescente, não por nome.
            #
            # O padrão da Steam é popularidade, que muda durante a
            # varredura: itens migram entre páginas, uns são lidos duas
            # vezes e outros nunca. Qualquer ordem explícita corrige isso,
            # e a deduplicação por hash_name na passada rasa cobre a
            # deriva residual (preço muda mais que nome ao longo de horas).
            #
            # Preço decrescente em vez de alfabética porque a varredura
            # pode não terminar: a de 2026-09-19 morreu em 429 com 3% do
            # catálogo lido. Em ordem alfabética, `Unusual ...` cai na
            # letra U e uma execução truncada não vê Unusual nenhum — que
            # é o dado de maior valor do spike. Por preço, os caros vêm
            # primeiro, então o que mais importa é lido antes.
            "sort_column": "price",
            "sort_dir": "desc",
        }
        if query:
            params["query"] = query
        payload = self._get(f"{BASE}/market/search/render/", params)
        return parse_search_page(payload)

    def listings(self, hash_name: str, count: int = 100) -> list[Listing]:
        quoted = urllib.parse.quote(hash_name, safe="")
        payload = self._get(
            f"{BASE}/market/listings/{APPID}/{quoted}/render/",
            {
                "start": 0,
                "count": count,
                "currency": CURRENCY_BRL,
                "format": "json",
                "l": "english",
            },
        )
        return parse_listings(payload)

    def _priceoverview(self) -> dict[str, Any]:
        """Um único payload para os dois preços da chave.

        Duas requisições seriam duas fotos de um mercado em movimento: o
        menor preço poderia vir de um instante e a mediana de outro, e a
        comparação de sanidade entre eles perderia o sentido.
        """
        if self._priceoverview_cache is None:
            self._priceoverview_cache = self._get(
                f"{BASE}/market/priceoverview/",
                {
                    "appid": APPID,
                    "currency": CURRENCY_BRL,
                    "market_hash_name": KEY_HASH_NAME,
                },
            )
        return self._priceoverview_cache

    def key_price(self) -> Brl:
        """Taxa de câmbio do spike: a listagem mais barata de chave.

        É o preço pelo qual você converteria reais em chaves de fato, então
        é a taxa honesta — ainda que mais volátil que a mediana.
        """
        return parse_price_text(self._priceoverview()["lowest_price"])

    def key_median_price(self) -> Brl:
        """Mediana de 24h, registrada no relatório como referência de sanidade."""
        return parse_price_text(self._priceoverview()["median_price"])
