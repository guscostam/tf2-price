from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from tf2price.domain.money import Brl
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.ratelimit import (
    RateLimiter,
    SteamLimitando,
    backoff_delays,
)

# Reexportado: a definição mora em `ratelimit` porque o cliente da API
# também a levanta, e quem importava daqui continua importando daqui.
__all__ = ["SteamLimitando"]
from tf2price.sources.steam import APPID, CURRENCY_BRL, CURRENCY_USD

BASE = "https://steamcommunity.com"
RENDER_CONTEXT_MARKER = "window.SSR.renderContext="
UNUSUAL_EFFECT_PREFIX = "Unusual Effect: "

# A CDN de economia da Steam serve o ícone a partir do caminho que vem na
# listagem. O tamanho é parte do caminho, não parâmetro de consulta.
CDN_IMAGEM = "https://community.cloudflare.steamstatic.com/economy/image"


def url_da_imagem(icon_url: str, tamanho: str = "330x192") -> str:
    return f"{CDN_IMAGEM}/{icon_url}/{tamanho}"

# Campo de moeda de cada parte do renderContext. O histórico escreve em
# minúsculas — `ecurrency` — ao contrário da listagem e do livro de ofertas.
# Não é engano de digitação; é assim que a Valve manda.
CURRENCY_FIELD = "eCurrency"
CURRENCY_FIELD_HISTORY = "ecurrency"

# A página usa formato en-US: vírgula para milhar, ponto para decimal.
# priceoverview usa pt-BR. Ver "Duas convenções de preço" no plano.
#
# A validação roda ANTES de remover as vírgulas, de propósito: uma vírgula só
# é aceita onde um separador de milhar legítimo entraria (logo antes de
# exatamente três dígitos). Se a vírgula for removida primeiro, o padrão não
# tem mais como distinguir "1,880.07" (en-US, milhar) de "32,25" (pt-BR,
# decimal curto) — e "32,25" vira silenciosamente R$ 3.225,00, cem vezes o
# valor real, sem nenhuma exceção. Não inverta a ordem destas duas linhas.
_SO_NUMERO = re.compile(r"[^\d.,]")
_EN_US = re.compile(r"(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?")


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
    icon_url: str | None


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
    limpo = _SO_NUMERO.sub("", text)
    if not _EN_US.fullmatch(limpo):
        raise PageStructureError(f"preço em formato inesperado: {text!r}")
    return Brl.from_float(float(limpo.replace(",", "")))


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


def _fator(
    dados: dict[str, Any],
    parte: str,
    usd_to_brl: float,
    campo: str = CURRENCY_FIELD,
) -> float:
    """Fator que leva o valor DESTA parte para reais.

    Medido em 2026-09-20: a página de listagens IGNORA o parâmetro
    `currency` e alterna de moeda entre requisições — o mesmo
    `Unusual HazMat Headcase` veio 'R$124.52' quando a fixture foi capturada,
    em real vinte minutos atrás e '$1,746.01' (eCurrency=1) agora, com
    currency=7, com country=BR e sem parâmetro nenhum, todos idênticos em
    dólar. Lido como real, o dólar vira um preço cinco vezes menor que o
    verdadeiro (R$ 8.999,99 confirmado no priceoverview) sem nada avisar.

    O próprio payload declara a moeda ao lado do valor, então é ela que
    mandamos — nunca o símbolo '$' ou 'R$' do `strSubtotal`, que é
    apresentação e não dado estruturado.

    Cada parte é lida com o seu campo. Não assuma que concordam entre si.
    """
    moeda = dados.get(campo)
    if moeda == CURRENCY_BRL:
        return 1.0
    if moeda == CURRENCY_USD:
        return usd_to_brl
    raise PageStructureError(
        f"{parte} veio na moeda {moeda!r}, esperava "
        f"{CURRENCY_USD} (USD) ou {CURRENCY_BRL} (BRL)"
    )


def _efeito(listagem: dict[str, Any]) -> str | None:
    descricoes = ((listagem.get("description") or {}).get("descriptions")) or []
    for d in descricoes:
        valor = str(d.get("value", ""))
        if UNUSUAL_EFFECT_PREFIX in valor:
            return valor.split(UNUSUAL_EFFECT_PREFIX, 1)[1].strip()
    return None


def _icone(listagem: dict[str, Any]) -> str | None:
    """Caminho do ícone na CDN, ou None.

    Mesmo lugar de onde `_efeito` lê: a descrição da listagem.
    """
    valor = (listagem.get("description") or {}).get("icon_url")
    return str(valor) if valor else None


def _listagens(qd: dict[str, Any], usd_to_brl: float) -> list[PageListing]:
    dados = _por_chave(qd, "market_item_search") or {}
    paginas = dados.get("pages") or []
    saida: list[PageListing] = []
    for pagina in paginas:
        for item in pagina.get("listings") or []:
            bruto = item.get("strSubtotal")
            if not bruto:
                continue  # sem preço não dá para avaliar; pular é honesto
            # A moeda vem por listagem, ao lado do valor.
            fator = _fator(item, "listagem", usd_to_brl)
            saida.append(
                PageListing(
                    listing_id=str(item.get("listingid", "")),
                    # Arredonda uma única vez, na conversão.
                    total_price=parse_page_price(str(bruto)) * fator,
                    effect=_efeito(item),
                    icon_url=_icone(item),
                )
            )
    return saida


def _centavos(valor: Any, fator: float) -> Brl | None:
    return Brl.from_cents(round(int(valor) * fator)) if valor else None


def _livro(qd: dict[str, Any], usd_to_brl: float) -> OrderBook:
    d = _por_chave(qd, "orderbook") or {}
    fator = _fator(d, "livro de ofertas", usd_to_brl)
    return OrderBook(
        max_buy_order=_centavos(d.get("amtMaxBuyOrder"), fator),
        min_sell_order=_centavos(d.get("amtMinSellOrder"), fator),
        buy_orders=int(d.get("cBuyOrders") or 0),
        sell_orders=int(d.get("cSellOrders") or 0),
    )


def _historico(qd: dict[str, Any], usd_to_brl: float) -> list[SalePoint]:
    d = _por_chave(qd, "pricehistory") or {}
    fator = _fator(d, "histórico", usd_to_brl, campo=CURRENCY_FIELD_HISTORY)
    saida: list[SalePoint] = []
    for ponto in d.get("prices") or []:
        mediana = ponto.get("price_median")
        if mediana is None:
            continue
        saida.append(
            SalePoint(
                when=int(ponto.get("time", 0)),
                # Unidades -> centavos e dólar -> real na mesma conta, para
                # arredondar uma única vez.
                median=Brl.from_cents(round(float(mediana) * 100 * fator)),
                purchases=int(ponto.get("purchases") or 0),
            )
        )
    return saida


def parse_item_page(html: str, hash_name: str, usd_to_brl: float) -> ItemPage:
    """Extrai a página de listagens, convertendo o que vier em dólar.

    `usd_to_brl` é posicional e obrigatório de propósito. Um valor padrão é
    justamente como esta classe de bug volta: torna a conversão esquecível
    no ponto de chamada e deixa todo teste existente verde enquanto um
    chamador novo pula a conversão em silêncio.
    """
    qd = _query_data(_render_context(html))
    return ItemPage(
        hash_name=hash_name,
        listings=_listagens(qd, usd_to_brl),
        orderbook=_livro(qd, usd_to_brl),
        history=_historico(qd, usd_to_brl),
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

    def item_page(self, hash_name: str, usd_to_brl: float) -> ItemPage:
        quoted = urllib.parse.quote(hash_name, safe="")
        url = f"{BASE}/market/listings/{APPID}/{quoted}"
        # `currency` continua sendo enviado por honestidade de pedido, mas a
        # página o ignora e alterna de moeda entre requisições; quem decide
        # é o campo de moeda que cada parte do payload declara.
        params = {"currency": CURRENCY_BRL, "l": "english"}

        ultimo: int | str | None = None
        houve_429 = False
        for atraso in [0.0, *backoff_delays(5)]:
            if atraso:
                self._sleep(atraso)
            self._limiter.wait()

            try:
                resposta = self._http.get(url, params=params)
                if resposta.status_code == 429:
                    self._limiter.record_throttle()
                    ultimo = 429
                    houve_429 = True
                    continue
                if resposta.status_code >= 500:
                    ultimo = resposta.status_code
                    continue
                resposta.raise_for_status()
            except httpx.HTTPStatusError as erro:
                # `raise_for_status()` só levanta isto para um 4xx que não é
                # 429 (429 e 5xx já deram `continue` acima) — e um 4xx não é
                # retentável: tentar de novo não muda um 403 (bloqueio) nem
                # um 404 (item deslistado). Falha na hora, saneada porque a
                # mensagem de um HTTPStatusError carrega a URL do pedido; as
                # três rotas que chamam esta função capturam RuntimeError.
                #
                # Mas se já houve 429 antes deste 4xx, quem manda é o 429:
                # estrangular e depois bloquear o reincidente é o padrão de
                # um limitador, e sair daqui como RuntimeError puro deixaria
                # a calma desligada justamente contra um IP já marcado.
                classe = SteamLimitando if houve_429 else RuntimeError
                raise classe(f"Steam recusou: {mensagem_saneada(erro)}") from erro
            except httpx.RequestError as erro:
                # Erro de transporte (timeout, conexão) — este sim é
                # retentável: sem este `except`, um `httpx.ReadTimeout` subia
                # cru e virava 500 na tela. Conta como mais uma tentativa
                # gasta do mesmo backoff que já existe para 429/5xx.
                ultimo = mensagem_saneada(erro)
                continue
            return parse_item_page(resposta.text, hash_name, usd_to_brl)

        mensagem = f"Steam não respondeu após backoff (último: {ultimo})"
        # Qualquer 429 no laço liga a calma, mesmo que a última tentativa
        # tenha sido outra coisa (timeout, 500...): a mensagem acima só
        # guarda a ÚLTIMA falha, mas `houve_429` viu o laço inteiro.
        if houve_429:
            raise SteamLimitando(mensagem)
        raise RuntimeError(mensagem)
