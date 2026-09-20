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
CURRENCY_USD = 1
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

# Forma en-US inequívoca: vírgula para milhar, ponto para decimal. Usada só
# para ler a chave em dólar no priceoverview (currency=1), que é o
# denominador da taxa USD->BRL.
_EN_US_PRICE = re.compile(r"^\d{1,3}(,\d{3})*(\.\d{1,2})?$")

# Mensagem única do modo de falha do endpoint de listagens (ver
# SteamClient.listings). Fica fora da função para que o teste e o código
# falem do mesmo texto.
_LISTINGS_NOT_JSON = (
    "o endpoint de listagens do mercado da Steam devolveu HTML em vez de "
    "JSON; sem ele os dados por listagem — efeito do Unusual e "
    "craftabilidade — não podem ser resolvidos"
)


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


def parse_usd_price_text(text: str) -> int:
    """'$1,880.07 USD' -> 188007 centavos de dólar.

    Só existe para ler a chave em dólar no priceoverview. É o espelho en-US
    de parse_price_text e, pelo mesmo motivo, só aceita a forma inequívoca:
    ponto para decimal, vírgula para milhar.
    """
    cleaned = _NON_NUMERIC.sub("", text)

    if not _EN_US_PRICE.match(cleaned):
        raise ValueError(f"texto de preço não está em formato en-US reconhecido: {text!r}")

    whole, _, frac = cleaned.replace(",", "").partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0"))


def parse_search_page(payload: dict[str, Any], usd_to_brl: float) -> SearchPage:
    """Converte uma página da busca de DÓLAR para REAL.

    `sell_price` chega em CENTAVOS DE DÓLAR. Medido contra a API real em
    2026-09-19: /market/search/render/ ignora o parâmetro `currency` e
    responde sempre em USD — testado com currency=7, com country=BR, com os
    dois e com nenhum, sempre `sell_price=188007` e
    `sell_price_text="$1,880.07 USD"`. Ler esse número como centavos de real
    (o que o código fazia até aqui) deixa todo preço da Steam ~5,4x baixo
    demais e fabrica descontos de 40-80% que não existem.

    `usd_to_brl` vem de SteamClient._usd_to_brl_rate(): a chave precificada
    em BRL dividida pela mesma chave precificada em USD, ambas pelo
    /market/priceoverview/, que — ao contrário da busca — honra `currency`.
    Não é uma cotação comercial de câmbio, e não deve ser trocada por uma:
    a comparação que o spike faz é VALOR DO ITEM EM CHAVES. Converter o
    preço do item para BRL com uma taxa derivada da chave e depois dividir
    pelo preço da chave em BRL é algebricamente idêntico a dividir o preço
    do item em USD pelo preço da chave em USD — a moeda se cancela. Derivar
    a taxa do próprio mercado evita depender de uma fonte externa de câmbio
    e mantém os números exibidos em reais, que é o que o relatório precisa.

    `sell_price` é lido como o preço já com a taxa do comprador embutida —
    o equivalente, na busca, a converted_price + converted_fee das
    listagens. ATENÇÃO: isso é item de verificação da execução real, não
    fato provado; se for o líquido do vendedor, todo desconto da passada
    rasa está inflado em ~15%.
    """
    results = [
        SearchResult(
            hash_name=row["hash_name"],
            # Arredonda uma única vez, na conversão: centavos de dólar *
            # taxa -> centavos de real.
            lowest_price=Brl.from_cents(round(int(row["sell_price"]) * usd_to_brl)),
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
        # Caches de instância: nunca compartilhados entre dois SteamClient.
        #
        # O cache do priceoverview é POR MOEDA. Um cache de payload único
        # devolveria o payload em BRL para um pedido em USD (ou o
        # contrário), e a taxa sairia 1,0 — exatamente a mesma classe de
        # bug que esta correção existe para matar, só que silenciosa.
        self._priceoverview_cache: dict[int, dict[str, Any]] = {}
        self._usd_to_brl: float | None = None
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price-spike/0.1"},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._get_response(url, params).json()

    def _get_response(self, url: str, params: dict[str, Any]) -> httpx.Response:
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
            return response

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
        # `currency` continua sendo enviado por honestidade de pedido, mas a
        # busca o ignora e responde em dólar: quem traz o número para reais
        # é a taxa derivada da chave, não a Steam.
        return parse_search_page(payload, self._usd_to_brl_rate())

    def listings(self, hash_name: str, count: int = 100) -> list[Listing]:
        quoted = urllib.parse.quote(hash_name, safe="")
        response = self._get_response(
            f"{BASE}/market/listings/{APPID}/{quoted}/render/",
            {
                "start": 0,
                "count": count,
                "currency": CURRENCY_BRL,
                "format": "json",
                "l": "english",
            },
        )

        # Medido em 2026-09-19: este endpoint passou a devolver a PÁGINA
        # HTML inteira (~380 KB, content-type text/html) com status 200 para
        # toda combinação de parâmetros testada — com l=english, com
        # language=english, com country=BR, com cabeçalho de AJAX, com
        # User-Agent de navegador. O fragmento JSON sumiu, e com ele as
        # variáveis g_rgAssets / g_rgListingInfo que a página carregava.
        #
        # Falhar aqui como RuntimeError é deliberado: quem chama já captura
        # (RuntimeError, httpx.HTTPError) por alvo, então cada candidato
        # degrada com um motivo no log. Deixar o JSONDecodeError escapar
        # derrubou o estágio profundo inteiro no alvo 1 de 27, porque ele
        # não é nem RuntimeError nem httpx.HTTPError.
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            # Só o content-type entra na mensagem; 380 KB de HTML, não.
            raise RuntimeError(f"{_LISTINGS_NOT_JSON} (content-type: {content_type[:80]!r})")

        try:
            payload = response.json()
        except ValueError as error:
            # json.JSONDecodeError é subclasse de ValueError. Content-type
            # mentindo é mais raro que o caso acima, mas o decode não pode
            # vazar de jeito nenhum.
            raise RuntimeError(f"{_LISTINGS_NOT_JSON} (corpo não decodifica como JSON)") from error

        return parse_listings(payload)

    def _priceoverview(self, currency: int = CURRENCY_BRL) -> dict[str, Any]:
        """Um único payload por moeda para os preços da chave.

        Em BRL: duas requisições seriam duas fotos de um mercado em
        movimento — o menor preço poderia vir de um instante e a mediana de
        outro, e a comparação de sanidade entre eles perderia o sentido.
        Por isso key_price e key_median_price custam uma requisição juntas.

        O cache é por moeda: devolver o payload em BRL para um pedido em USD
        zeraria a taxa de conversão sem ninguém perceber.
        """
        cached = self._priceoverview_cache.get(currency)
        if cached is None:
            cached = self._get(
                f"{BASE}/market/priceoverview/",
                {
                    "appid": APPID,
                    "currency": currency,
                    "market_hash_name": KEY_HASH_NAME,
                },
            )
            self._priceoverview_cache[currency] = cached
        return cached

    def _usd_to_brl_rate(self) -> float:
        """Taxa dólar->real tirada da própria economia da Steam.

        usd_to_brl = preço_da_chave_em_BRL_centavos / preço_da_chave_em_USD_centavos

        Os dois lados vêm do /market/priceoverview/, que honra `currency` —
        é essa assimetria com a busca (que não honra) que torna a correção
        possível. Ver parse_search_page para por que uma taxa derivada da
        chave é a taxa CERTA aqui, e não um remendo: a conta do spike é
        valor em chaves, e a moeda se cancela.

        Calculada uma vez por instância e guardada.
        """
        if self._usd_to_brl is None:
            brl_cents = parse_price_text(self._priceoverview(CURRENCY_BRL)["lowest_price"]).cents
            usd_cents = parse_usd_price_text(self._priceoverview(CURRENCY_USD)["lowest_price"])
            if usd_cents <= 0:
                raise RuntimeError(
                    "priceoverview devolveu preço de chave em USD não positivo; "
                    "sem denominador não há como converter a busca para reais"
                )
            self._usd_to_brl = brl_cents / usd_cents
        return self._usd_to_brl

    def key_price(self) -> Brl:
        """Taxa de câmbio do spike: a listagem mais barata de chave.

        É o preço pelo qual você converteria reais em chaves de fato, então
        é a taxa honesta — ainda que mais volátil que a mediana.
        """
        return parse_price_text(self._priceoverview()["lowest_price"])

    def key_median_price(self) -> Brl:
        """Mediana de 24h, registrada no relatório como referência de sanidade."""
        return parse_price_text(self._priceoverview()["median_price"])
