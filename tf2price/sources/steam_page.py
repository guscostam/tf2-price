from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter, backoff_delays
from tf2price.sources.steam import APPID, CURRENCY_BRL

BASE = "https://steamcommunity.com"
RENDER_CONTEXT_MARKER = "window.SSR.renderContext="
UNUSUAL_EFFECT_PREFIX = "Unusual Effect: "

# A página usa formato en-US: vírgula para milhar, ponto para decimal.
# priceoverview usa pt-BR. Ver "Duas convenções de preço" no plano.
_SO_NUMERO = re.compile(r"[^\d.,]")
_EN_US = re.compile(r"\d+(?:\.\d{1,2})?")


class PageStructureError(RuntimeError):
    """A página da Steam não tem a estrutura que o extrator espera.

    Levantada com o caminho esperado na mensagem para que uma mudança na
    Valve apareça como diagnóstico, e não como KeyError cru no meio de uma
    requisição do usuário.
    """


@dataclass(frozen=True)
class PageListing:
    listing_id: str
    total_price: Brl
    effect: str | None


@dataclass(frozen=True)
class OrderBook:
    max_buy_order: Brl | None
    min_sell_order: Brl | None
    buy_orders: int
    sell_orders: int


@dataclass(frozen=True)
class SalePoint:
    when: int
    median: Brl
    purchases: int


@dataclass(frozen=True)
class ItemPage:
    hash_name: str
    listings: list[PageListing]
    orderbook: OrderBook
    history: list[SalePoint]


def parse_page_price(text: str) -> Brl:
    """'R$124.52' e 'R$1,880.07' -> Brl.

    Formato en-US. `parse_price_text` de sources/steam.py aceita só pt-BR e
    recusa este de propósito; os dois são estritos porque confundir moeda e
    separador já produziu um resultado falso neste projeto.
    """
    limpo = _SO_NUMERO.sub("", text).replace(",", "")
    if not _EN_US.fullmatch(limpo):
        raise PageStructureError(f"preço em formato inesperado: {text!r}")
    return Brl.from_float(float(limpo))


def _render_context(html: str) -> dict[str, Any]:
    inicio = html.find(RENDER_CONTEXT_MARKER)
    if inicio < 0:
        raise PageStructureError(
            f"não encontrei {RENDER_CONTEXT_MARKER!r} na página da Steam"
        )
    aspas = html.find('"', inicio + len(RENDER_CONTEXT_MARKER))
    if aspas < 0:
        raise PageStructureError("renderContext não vem como string JSON")
    try:
        texto, _ = json.JSONDecoder().raw_decode(html[aspas:])
        return json.loads(texto)
    except ValueError as erro:
        raise PageStructureError(f"renderContext não decodificou: {erro}") from erro


def _query_data(ctx: dict[str, Any]) -> dict[str, Any]:
    bruto = ctx.get("queryData")
    if not isinstance(bruto, str):
        raise PageStructureError("renderContext.queryData ausente ou não é string")
    try:
        return json.loads(bruto)
    except ValueError as erro:
        raise PageStructureError(f"queryData não decodificou: {erro}") from erro


def _por_chave(qd: dict[str, Any], fragmento: str) -> Any:
    for consulta in qd.get("queries") or []:
        if fragmento in str(consulta.get("queryKey")):
            return (consulta.get("state") or {}).get("data")
    raise PageStructureError(
        f"consulta {fragmento!r} não está no renderContext da página"
    )


def _efeito(listagem: dict[str, Any]) -> str | None:
    descricoes = ((listagem.get("description") or {}).get("descriptions")) or []
    for d in descricoes:
        valor = str(d.get("value", ""))
        if UNUSUAL_EFFECT_PREFIX in valor:
            return valor.split(UNUSUAL_EFFECT_PREFIX, 1)[1].strip()
    return None


def _listagens(qd: dict[str, Any]) -> list[PageListing]:
    dados = _por_chave(qd, "market_item_search") or {}
    paginas = dados.get("pages") or []
    saida: list[PageListing] = []
    for pagina in paginas:
        for item in pagina.get("listings") or []:
            bruto = item.get("strSubtotal")
            if not bruto:
                continue  # sem preço não dá para avaliar; pular é honesto
            saida.append(
                PageListing(
                    listing_id=str(item.get("listingid", "")),
                    total_price=parse_page_price(str(bruto)),
                    effect=_efeito(item),
                )
            )
    return saida


def _centavos(valor: Any) -> Brl | None:
    return Brl.from_cents(int(valor)) if valor else None


def _livro(qd: dict[str, Any]) -> OrderBook:
    d = _por_chave(qd, "orderbook") or {}
    return OrderBook(
        max_buy_order=_centavos(d.get("amtMaxBuyOrder")),
        min_sell_order=_centavos(d.get("amtMinSellOrder")),
        buy_orders=int(d.get("cBuyOrders") or 0),
        sell_orders=int(d.get("cSellOrders") or 0),
    )


def _historico(qd: dict[str, Any]) -> list[SalePoint]:
    d = _por_chave(qd, "pricehistory") or {}
    saida: list[SalePoint] = []
    for ponto in d.get("prices") or []:
        mediana = ponto.get("price_median")
        if mediana is None:
            continue
        saida.append(
            SalePoint(
                when=int(ponto.get("time", 0)),
                median=Brl.from_float(float(mediana)),
                purchases=int(ponto.get("purchases") or 0),
            )
        )
    return saida


def parse_item_page(html: str, hash_name: str) -> ItemPage:
    qd = _query_data(_render_context(html))
    return ItemPage(
        hash_name=hash_name,
        listings=_listagens(qd),
        orderbook=_livro(qd),
        history=_historico(qd),
    )


class SteamPageClient:
    """Busca a página de listagens de um item e extrai o que ela embute.

    A Valve desligou o endpoint JSON `/render/` — ele responde HTML. Os dados
    continuam na página, dentro do renderContext, e é de lá que vêm.
    """

    def __init__(
        self,
        limiter: RateLimiter,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limiter = limiter
        self._sleep = sleep
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price/0.1"},
            follow_redirects=True,
        )

    def item_page(self, hash_name: str) -> ItemPage:
        quoted = urllib.parse.quote(hash_name, safe="")
        url = f"{BASE}/market/listings/{APPID}/{quoted}"
        params = {"currency": CURRENCY_BRL, "l": "english"}

        ultimo: int | None = None
        for atraso in [0.0, *backoff_delays(5)]:
            if atraso:
                self._sleep(atraso)
            self._limiter.wait()

            resposta = self._http.get(url, params=params)
            if resposta.status_code == 429:
                self._limiter.record_throttle()
                ultimo = 429
                continue
            if resposta.status_code >= 500:
                ultimo = resposta.status_code
                continue
            resposta.raise_for_status()
            return parse_item_page(resposta.text, hash_name)

        raise RuntimeError(f"Steam não respondeu após backoff (último: {ultimo})")
