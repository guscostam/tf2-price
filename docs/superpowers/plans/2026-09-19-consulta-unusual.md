# Consulta de Unusual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma página local onde o usuário escolhe um chapéu Unusual e um efeito, e vê se comprar vale a pena — medido contra ordens de compra reais da Steam e, quando existir, contra o preço de troca da backpack.tf.

**Architecture:** Extrator do `renderContext` da página de listagens da Steam (`sources/steam_page.py`), análise pura sem I/O (`lookup/analysis.py`), e FastAPI + HTMX servindo fragmentos (`lookup/app.py`). Reaproveita `domain/money.py`, `domain/effects.py`, `sources/backpacktf.py`, `sources/ratelimit.py` e `sources/steam.py` sem alterá-los.

**Tech Stack:** Python 3.12+, httpx, FastAPI, Jinja2, HTMX (via CDN), pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-consulta-unusual-design.md`

---

## Contexto de domínio

Em Team Fortress 2, **Unusual** é uma qualidade rara com efeito de partícula. O
mesmo chapéu com efeitos diferentes vale valores que diferem em ordens de
magnitude, e o efeito **não** está no nome do item — só dentro de cada listagem.

Itens são negociados em **chaves** (*Mann Co. Supply Crate Key*), a moeda de facto
do jogo. A backpack.tf publica preços sugeridos pela comunidade nessa unidade. Os
mesmos itens também são vendidos na Steam Community Market por reais.

**Por que este app substitui o anterior:** uma varredura foi construída, executada
e reprovada. A idade mediana de um preço de Unusual na backpack.tf é de 749 dias,
e os efeitos que ela precifica quase não se sobrepõem aos que estão à venda na
Steam — o relatório comparava um efeito contra o preço de outro. O histórico está
em `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`; vale ler o §0-bis
antes de começar.

---

## Global Constraints

Valem para todos os tasks.

- **Python >= 3.12.** `from __future__ import annotations` no topo de todo módulo.
- **`tf2price/domain/` e `tf2price/lookup/analysis.py` não fazem I/O.** Sem rede,
  sem disco, sem relógio direto. Onde precisar de "agora", receber `now: int | None = None`.
- **Nenhum teste faz requisição de rede**, nem importa `unittest.mock`. Use
  `httpx.MockTransport` e fixtures gravadas.
- **Dinheiro em reais é `Brl` em centavos inteiros.** Valores em chaves são `float`.
- **Não altere** `domain/money.py`, `domain/effects.py`, `sources/backpacktf.py`,
  `sources/ratelimit.py`, `sources/steam.py`, nem qualquer fixture existente.
  Outros testes dependem delas.
- **A regra de honestidade do spec §4:** livro de ofertas e histórico são **por
  item**; listagens e preço da bp.tf são **por efeito**. Nenhum número de um nível
  entra em cálculo do outro sem rótulo explícito. Confundir os dois invalidou o
  projeto anterior.
- Mensagens de commit em português, no imperativo.
- **Todo commit termina com estas duas linhas exatas**, separadas do corpo por uma
  linha em branco. Copie caractere por caractere; não substitua pelo nome do
  modelo que estiver executando:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
  ```
- Commitar com `git -c user.name="gusco" -c user.email="guscostam@gmail.com" commit ...`
- `.superpowers/` é área de coordenação no `.gitignore`. Não tocar, não commitar.
- Ambiente Windows; o executável é `.venv/Scripts/python`.

### Duas convenções de preço na mesma API

Verificado em 2026-09-19 e **não é suposição**:

| Rota | Formato | Exemplo |
|---|---|---|
| `/market/priceoverview/` | pt-BR: ponto milhar, vírgula decimal | `R$ 32,25` |
| `renderContext` da página | en-US: vírgula milhar, ponto decimal | `R$124.52` |

`parse_price_text` em `sources/steam.py` aceita **só** a primeira e levanta
`ValueError` na segunda, de propósito. **Não a reutilize** nesta página, e não a
afrouxe — ela existe assim porque ler dólar como real já produziu um veredito
falso neste projeto.

---

## Estrutura de arquivos

```
tf2price/
  sources/
    steam_page.py        # extrai renderContext -> ItemPage
  lookup/
    __init__.py
    analysis.py          # puro: ItemPage + bp.tf -> Analise
    app.py               # FastAPI: rotas e cache de página
    templates/
      index.html
      _itens.html        # fragmento: nomes que casam a busca
      _efeitos.html      # fragmento: efeitos à venda
      _analise.html      # fragmento: a análise
tests/
  sources/test_steam_page.py
  lookup/
    __init__.py
    test_analysis.py
  fixtures/
    steam_listing_page.html    # JÁ EXISTE, gravada de página real
```

`tests/fixtures/steam_listing_page.html` **já está no repositório**: 61 KB,
capturada de `Unusual Taunt: Chairholder`, reduzida ao bloco que o extrator
consome. Contém 7 listagens, 4 efeitos distintos, `amtMaxBuyOrder = 10631` e 102
pontos de histórico. **Não a regenere nem a edite.**

---

## Sequência

| # | Entrega | Depende de |
|---|---|---|
| 1 | `sources/steam_page.py` — extrator | — |
| 2 | `lookup/analysis.py` — análise pura | 1 |
| 3 | `lookup/app.py` — rotas e cache | 1, 2 |
| 4 | Templates e execução manual | 3 |

---

### Task 1: `sources/steam_page.py` — extrator do `renderContext`

**Files:**
- Create: `tf2price/sources/steam_page.py`
- Test: `tests/sources/test_steam_page.py`

**Interfaces produzidas:**
- `PageStructureError(RuntimeError)`
- `PageListing` — frozen: `listing_id: str`, `total_price: Brl`, `effect: str | None`
- `OrderBook` — frozen: `max_buy_order: Brl | None`, `min_sell_order: Brl | None`, `buy_orders: int`, `sell_orders: int`
- `SalePoint` — frozen: `when: int`, `median: Brl`, `purchases: int`
- `ItemPage` — frozen: `hash_name: str`, `listings: list[PageListing]`, `orderbook: OrderBook`, `history: list[SalePoint]`
- `parse_page_price(text: str) -> Brl`
- `parse_item_page(html: str, hash_name: str) -> ItemPage`
- `SteamPageClient(limiter, client=None, sleep=time.sleep)` com `item_page(hash_name: str) -> ItemPage`

**O que a página contém**, verificado na fixture:

```
window.SSR.renderContext = JSON.parse("<string JSON>")   <- um nível de escape
  .queryData                                              <- string, OUTRO json.loads
    .queries[]  -> localizadas por fragmento de queryKey:
       "market_item_search"  -> .state.data.pages[0].listings
       "orderbook"           -> .state.data
       "pricehistory"        -> .state.data
```

Cada listagem traz `listingid`, `strSubtotal` (**preço total ao comprador**, em
BRL, `eCurrency: 7`), `unFee`, e `description.descriptions[]` com uma entrada cujo
`value` contém `★ Unusual Effect: <nome>`.

`unFee` é a parcela de taxa **dentro** do total: `124,52 − 16,23 = 108,29`, e
`108,29 × 0,15 = 16,24`. Não subtraia a taxa do preço exibido; ele já é o que o
comprador paga.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/sources/test_steam_page.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam_page import (
    ItemPage,
    PageStructureError,
    SteamPageClient,
    parse_item_page,
    parse_page_price,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"
NOME = "Unusual Taunt: Chairholder"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def pagina() -> ItemPage:
    return parse_item_page(_html(), NOME)


# --- preço em formato en-US, diferente do priceoverview ------------------


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("R$124.52", 12452),
        ("R$1,880.07", 188007),
        ("R$0.99", 99),
        ("R$12,345,678.90", 1234567890),
    ],
)
def test_parse_page_price(texto, centavos):
    assert parse_page_price(texto) == Brl.from_cents(centavos)


def test_parse_page_price_recusa_formato_ptbr():
    """A página usa ponto decimal; priceoverview usa vírgula.

    Aceitar os dois no mesmo parser é como um preço vira 100x o que é.
    """
    with pytest.raises(PageStructureError):
        parse_page_price("R$ 1.234,50")


def test_parse_page_price_recusa_lixo():
    with pytest.raises(PageStructureError):
        parse_page_price("sob consulta")


# --- listagens -----------------------------------------------------------


def test_extrai_as_sete_listagens(pagina: ItemPage):
    assert len(pagina.listings) == 7
    assert pagina.hash_name == NOME


def test_listagem_mais_barata_tem_preco_e_efeito(pagina: ItemPage):
    barata = min(pagina.listings, key=lambda x: x.total_price)
    assert barata.total_price == Brl.from_cents(12452)
    assert barata.effect == "Midnight Whirlwind"
    assert barata.listing_id == "518632172291794014"


def test_efeitos_distintos_da_pagina(pagina: ItemPage):
    efeitos = {x.effect for x in pagina.listings}
    assert efeitos == {
        "Midnight Whirlwind",
        "Silver Cyclone",
        "Deep Dive",
        "Screaming Tiger",
    }


def test_o_mesmo_efeito_aparece_em_precos_diferentes(pagina: ItemPage):
    """Duas Deep Dive com preços distintos — é o sinal que o app procura."""
    deep = sorted(
        (x.total_price.cents for x in pagina.listings if x.effect == "Deep Dive")
    )
    assert len(deep) == 2
    assert deep[0] < deep[1]


# --- livro de ofertas ----------------------------------------------------


def test_livro_de_ofertas(pagina: ItemPage):
    ob = pagina.orderbook
    assert ob.max_buy_order == Brl.from_cents(10631)
    assert ob.min_sell_order == Brl.from_cents(12452)
    assert ob.buy_orders == 39
    assert ob.sell_orders == 7


# --- histórico -----------------------------------------------------------


def test_historico_de_vendas(pagina: ItemPage):
    assert len(pagina.history) == 102
    primeiro = pagina.history[0]
    assert primeiro.when > 0
    assert primeiro.purchases >= 1
    assert primeiro.median.cents > 0


# --- falhas de estrutura -------------------------------------------------


def test_pagina_sem_render_context_falha_com_mensagem_clara():
    with pytest.raises(PageStructureError, match="renderContext"):
        parse_item_page("<html><body>nada aqui</body></html>", NOME)


def test_render_context_sem_query_esperada_falha_nomeando_qual():
    html = 'x<script>window.SSR.renderContext="{\\"queryData\\":\\"{}\\"}";</script>'
    with pytest.raises(PageStructureError, match="market_item_search"):
        parse_item_page(html, NOME)


# --- cliente HTTP --------------------------------------------------------


def _cliente(corpo: str, capturadas: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capturadas is not None:
            capturadas.append(request)
        return httpx.Response(200, text=corpo, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_cliente_escapa_o_nome_e_pede_moeda_brl():
    capturadas: list[httpx.Request] = []
    cliente = SteamPageClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_html(), capturadas),
    )

    pagina = cliente.item_page(NOME)

    assert len(pagina.listings) == 7
    url = str(capturadas[0].url)
    assert "Unusual%20Taunt%3A%20Chairholder" in url
    assert capturadas[0].url.params["currency"] == "7"
    assert capturadas[0].url.params["l"] == "english"


def test_cliente_repete_em_429_e_registra():
    respostas = [429, 200]
    corpo = _html()

    def handler(request: httpx.Request) -> httpx.Response:
        if respostas.pop(0) == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, text=corpo, headers={"content-type": "text/html"})

    limiter = RateLimiter(min_interval_s=0.0)
    cliente = SteamPageClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    assert len(cliente.item_page(NOME).listings) == 7
    assert limiter.throttled == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/sources/test_steam_page.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.sources.steam_page'`

- [ ] **Step 3: Implementar `tf2price/sources/steam_page.py`**

```python
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
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/sources/test_steam_page.py -v
```

Esperado: 16 passed (4 parametrizados + 12 avulsos)

- [ ] **Step 5: Rodar a suíte inteira**

```bash
.venv/Scripts/python -m pytest
```

Esperado: 208 anteriores + 15 novos, saída limpa.

- [ ] **Step 6: Commit**

```bash
git add tf2price/sources/steam_page.py tests/sources/test_steam_page.py
git -c user.name="gusco" -c user.email="guscostam@gmail.com" commit -F - <<'MSG'
Extrai listagens, livro de ofertas e histórico da página da Steam

A Valve desligou o endpoint JSON de listagens, que passou a responder
HTML. Os dados continuam na página, dentro de window.SSR.renderContext,
com dois níveis de escape.

Traz o efeito de cada listagem, que é o dado sem o qual comparar Unusual
não faz sentido, e o livro de ofertas, que diz se existe comprador — a
pergunta que o preço sugerido da backpack.tf não responde.

O parser de preço é estrito e recusa o formato pt-BR: esta rota usa ponto
decimal e o priceoverview usa vírgula.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
```

---

### Task 2: `lookup/analysis.py` — a análise, pura

Este é o módulo onde a regra de honestidade do spec §4 vira código. Ele não faz
I/O: recebe a página já extraída e o índice da backpack.tf, e devolve a análise.

**Files:**
- Create: `tf2price/lookup/__init__.py` (vazio)
- Create: `tf2price/lookup/analysis.py`
- Create: `tests/lookup/__init__.py` (vazio)
- Test: `tests/lookup/test_analysis.py`

**Interfaces produzidas:**
- `STEAM_FEE_MULTIPLIER = 1.15`, `QUALITY_UNUSUAL = 5`
- `RAZAO_EFEITO_DESCONHECIDO`, `RAZAO_SEM_PRECO` — constantes de texto
- `ImmediateExit` — frozen: `top_bid: Brl | None`, `net_received: Brl | None`, `result: Brl | None`, `buy_orders: int`
- `PatientExit` — frozen: `available: bool`, `reason: str | None`, `keys: float | None`, `fair_value: Brl | None`, `result: Brl | None`, `age_days: int | None`
- `Analysis` — frozen: `hash_name`, `effect`, `listings`, `cheapest`, `price_in_keys`, `immediate`, `patient`, `orderbook`, `history`, `history_median`, `history_purchases`, `key_brl`
- `net_after_fee(buyer_price: Brl) -> Brl`
- `effects_available(page: ItemPage) -> list[str]`
- `listings_of(page: ItemPage, effect: str) -> list[PageListing]`
- `immediate_exit(paid: Brl, orderbook: OrderBook) -> ImmediateExit`
- `patient_exit(paid, hash_name, effect, index, key_brl, now=None, effects_path=DEFAULT_EFFECTS_PATH) -> PatientExit`
- `analyse(page, effect, index, key_brl, now=None, effects_path=DEFAULT_EFFECTS_PATH) -> Analysis`

**A regra que este módulo tem que respeitar:**

`orderbook` e `history` são **do item inteiro**, somando todos os efeitos. A Steam
não os separa por efeito. `listings` e `patient` são **do efeito escolhido**.

Na `Analysis`, `orderbook` e `history` são repassados **sem transformação**, para
que a camada de apresentação os rotule como são. Nenhuma média, nenhum filtro,
nenhuma combinação com os dados por efeito.

**Uma ordem de compra vale para qualquer exemplar do nome**, independentemente do
efeito. É por isso que `immediate_exit` pode comparar o preço pago de um efeito
específico contra a melhor oferta do item — e é o único cruzamento entre os dois
níveis que é legítimo. Documente isso no docstring, senão o próximo leitor vai
achar que é o mesmo erro de antes.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/lookup/test_analysis.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import ItemPage, OrderBook, parse_item_page
from tf2price.lookup.analysis import (
    Analysis,
    analyse,
    effects_available,
    immediate_exit,
    listings_of,
    net_after_fee,
    patient_exit,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EFEITOS = FIXTURES / "effects_sample.json"
NOME = "Unusual Taunt: Chairholder"
CHAVE = Brl.from_float(11.73)
AGORA = 1_790_000_000


@pytest.fixture
def pagina() -> ItemPage:
    html = (FIXTURES / "steam_listing_page.html").read_text(encoding="utf-8")
    return parse_item_page(html, NOME)


def _indice(entradas: dict) -> PriceIndex:
    """PriceIndex minúsculo construído em linha, sem tocar as fixtures da bp.tf."""
    return PriceIndex.from_payload({"response": {"items": entradas}}, key_in_refined=64.11)


# --- taxa ----------------------------------------------------------------


def test_net_after_fee_desfaz_os_15_por_cento():
    # observado na página: 124,52 ao comprador, 16,23 de taxa, 108,29 ao vendedor
    assert net_after_fee(Brl.from_cents(12452)) == Brl.from_cents(10828)


def test_net_after_fee_nao_aplica_a_taxa_duas_vezes():
    uma = net_after_fee(Brl.from_cents(10000))
    assert uma.cents > 8000  # 1/1,15 e não 0,85 x 0,85


# --- efeitos e listagens por efeito --------------------------------------


def test_efeitos_disponiveis_sao_os_que_tem_listagem(pagina: ItemPage):
    assert effects_available(pagina) == [
        "Deep Dive",
        "Midnight Whirlwind",
        "Screaming Tiger",
        "Silver Cyclone",
    ]


def test_listagens_do_efeito_vem_ordenadas(pagina: ItemPage):
    deep = listings_of(pagina, "Deep Dive")
    assert len(deep) == 2
    assert deep[0].total_price < deep[1].total_price
    assert all(x.effect == "Deep Dive" for x in deep)


def test_efeito_inexistente_devolve_lista_vazia(pagina: ItemPage):
    assert listings_of(pagina, "Burning Flames") == []


# --- saída imediata ------------------------------------------------------


def test_saida_imediata_no_caso_real(pagina: ItemPage):
    """Comprar a 124,52 e vender já para a oferta de 106,31 dá prejuízo."""
    r = immediate_exit(Brl.from_cents(12452), pagina.orderbook)
    assert r.top_bid == Brl.from_cents(10631)
    assert r.net_received == Brl.from_cents(9244)
    assert r.result == Brl.from_cents(-3208)
    assert r.buy_orders == 39


def test_saida_imediata_positiva_e_arbitragem_dura():
    """Listagem abaixo do que a melhor oferta paga líquido: lucro sem troca."""
    livro = OrderBook(
        max_buy_order=Brl.from_cents(20000),
        min_sell_order=Brl.from_cents(10000),
        buy_orders=5,
        sell_orders=2,
    )
    r = immediate_exit(Brl.from_cents(10000), livro)
    assert r.net_received == Brl.from_cents(17391)
    assert r.result.cents > 0


def test_saida_imediata_sem_ofertas_de_compra():
    livro = OrderBook(max_buy_order=None, min_sell_order=None, buy_orders=0, sell_orders=0)
    r = immediate_exit(Brl.from_cents(10000), livro)
    assert r.top_bid is None
    assert r.net_received is None
    assert r.result is None


# --- saída paciente ------------------------------------------------------


def test_saida_paciente_indisponivel_quando_a_bptf_nao_precifica_o_efeito():
    """O caso real do Chairholder: nenhum efeito à venda tem preço na bp.tf."""
    idx = _indice({"Taunt: Chairholder": {"prices": {"5": {"Tradable": {"Craftable": {
        "9999": {"currency": "keys", "value": 24.0, "last_update": AGORA - 86400}
    }}}}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Burning Flames", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is False
    assert r.reason
    assert r.fair_value is None
    assert r.result is None


def test_saida_paciente_indisponivel_quando_o_efeito_nao_esta_no_mapa():
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Efeito Que Nao Existe", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is False
    assert r.reason


def test_saida_paciente_disponivel_traz_valor_e_idade():
    # Burning Flames = 13 na fixture de efeitos
    idx = _indice({"Taunt: Chairholder": {"prices": {"5": {"Tradable": {"Craftable": {
        "13": {"currency": "keys", "value": 20.0, "last_update": AGORA - 60 * 86400}
    }}}}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Burning Flames", idx, CHAVE,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is True
    assert r.keys == pytest.approx(20.0)
    assert r.fair_value == Brl.from_cents(23460)   # 20 x 11,73
    assert r.result == Brl.from_cents(11008)
    assert r.age_days == 60


# --- análise completa ----------------------------------------------------


def test_analise_usa_a_listagem_mais_barata_do_efeito(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.effect == "Deep Dive"
    assert a.cheapest.total_price == Brl.from_cents(18044)
    assert len(a.listings) == 2


def test_analise_repassa_livro_e_historico_sem_transformar(pagina: ItemPage):
    """Regra do spec §4: são dados POR ITEM e não podem ser filtrados por efeito.

    Se alguém um dia filtrar o livro ou o histórico pelo efeito escolhido,
    estará inventando um dado que a Steam não fornece — que é exatamente o
    erro que invalidou o projeto anterior.
    """
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.orderbook == pagina.orderbook
    assert a.history == pagina.history
    assert a.history_purchases == sum(p.purchases for p in pagina.history)


def test_analise_converte_para_chaves(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert a.price_in_keys == pytest.approx(180.44 / 11.73, rel=1e-3)


def test_analise_de_efeito_sem_listagem_levanta(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    with pytest.raises(ValueError, match="Burning Flames"):
        analyse(pagina, "Burning Flames", idx, CHAVE, now=AGORA, effects_path=EFEITOS)
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/lookup/test_analysis.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.lookup'`

- [ ] **Step 3: Implementar `tf2price/lookup/analysis.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import bptf_name_candidates, parse_market_hash_name
from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, SalePoint

# A taxa é 15% sobre o valor do vendedor, e o comprador paga a soma. Observado
# na página: 124,52 ao comprador, 16,23 de taxa, 108,29 ao vendedor, e
# 108,29 x 0,15 = 16,24. Logo o líquido é o preço dividido por 1,15.
STEAM_FEE_MULTIPLIER = 1.15

QUALITY_UNUSUAL = 5

RAZAO_EFEITO_DESCONHECIDO = (
    "o efeito não está no mapa extraído do schema da Valve, "
    "então não dá para procurá-lo na backpack.tf"
)
RAZAO_SEM_PRECO = "a backpack.tf não precifica este efeito para este item"


@dataclass(frozen=True)
class ImmediateExit:
    """Vender agora para a melhor oferta de compra existente.

    Dado duro: são ordens reais, verificáveis neste minuto, e não dependem de
    referência externa nenhuma.
    """

    top_bid: Brl | None
    net_received: Brl | None
    result: Brl | None
    buy_orders: int


@dataclass(frozen=True)
class PatientExit:
    """Trocar por chaves usando a backpack.tf como referência.

    Dado mole: preço *sugerido*, não oferta de compra. Ninguém se comprometeu
    a pagar aquilo, e a idade pode ser de anos. Por isso carrega `age_days`,
    e por isso `available` pode ser falso com um motivo legível.
    """

    available: bool
    reason: str | None
    keys: float | None
    fair_value: Brl | None
    result: Brl | None
    age_days: int | None


@dataclass(frozen=True)
class Analysis:
    hash_name: str
    effect: str
    listings: list[PageListing]
    cheapest: PageListing
    price_in_keys: float
    immediate: ImmediateExit
    patient: PatientExit
    # Abaixo: dados DO ITEM INTEIRO, somando todos os efeitos. A Steam não os
    # separa por efeito. Repassados sem transformação para que a apresentação
    # os rotule como são.
    orderbook: OrderBook
    history: list[SalePoint]
    history_median: Brl | None
    history_purchases: int
    key_brl: Brl


def net_after_fee(buyer_price: Brl) -> Brl:
    """O que o vendedor recebe quando o comprador paga `buyer_price`."""
    return Brl.from_cents(round(buyer_price.cents / STEAM_FEE_MULTIPLIER))


def effects_available(page: ItemPage) -> list[str]:
    """Efeitos que de fato têm listagem agora, em ordem alfabética."""
    return sorted({x.effect for x in page.listings if x.effect})


def listings_of(page: ItemPage, effect: str) -> list[PageListing]:
    """Listagens daquele efeito, da mais barata para a mais cara."""
    return sorted(
        (x for x in page.listings if x.effect == effect),
        key=lambda x: x.total_price,
    )


def immediate_exit(paid: Brl, orderbook: OrderBook) -> ImmediateExit:
    """Resultado de comprar por `paid` e vender já para a melhor oferta.

    Uma ordem de compra na Steam vale para QUALQUER exemplar daquele nome,
    seja qual for o efeito. É por isso que comparar o preço de um efeito
    específico contra a melhor oferta do item é legítimo — é o único
    cruzamento entre o nível por-efeito e o nível por-item que se sustenta.
    """
    if orderbook.max_buy_order is None:
        return ImmediateExit(None, None, None, orderbook.buy_orders)

    recebido = net_after_fee(orderbook.max_buy_order)
    return ImmediateExit(
        top_bid=orderbook.max_buy_order,
        net_received=recebido,
        result=recebido - paid,
        buy_orders=orderbook.buy_orders,
    )


def patient_exit(
    paid: Brl,
    hash_name: str,
    effect: str,
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> PatientExit:
    now = int(time.time()) if now is None else now

    effect_id = effect_id_for(effect, effects_path)
    if effect_id is None:
        return PatientExit(False, RAZAO_EFEITO_DESCONHECIDO, None, None, None, None)

    identity = parse_market_hash_name(hash_name)
    for nome in bptf_name_candidates(identity, hash_name):
        preco = index.lookup(
            nome, QUALITY_UNUSUAL, craftable=True, priceindex=str(effect_id)
        )
        chaves = index.to_keys(preco)
        if chaves is None or chaves <= 0:
            continue

        justo = key_brl * chaves
        return PatientExit(
            available=True,
            reason=None,
            keys=chaves,
            fair_value=justo,
            result=justo - paid,
            age_days=(now - preco.last_update) // 86400,
        )

    return PatientExit(False, RAZAO_SEM_PRECO, None, None, None, None)


def analyse(
    page: ItemPage,
    effect: str,
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> Analysis:
    listagens = listings_of(page, effect)
    if not listagens:
        raise ValueError(f"nenhuma listagem do efeito {effect!r} nesta página")

    barata = listagens[0]
    medianas = [p.median.cents for p in page.history]

    return Analysis(
        hash_name=page.hash_name,
        effect=effect,
        listings=listagens,
        cheapest=barata,
        price_in_keys=barata.total_price.cents / key_brl.cents,
        immediate=immediate_exit(barata.total_price, page.orderbook),
        patient=patient_exit(
            barata.total_price, page.hash_name, effect, index, key_brl,
            now=now, effects_path=effects_path,
        ),
        orderbook=page.orderbook,
        history=page.history,
        history_median=Brl.from_cents(round(median(medianas))) if medianas else None,
        history_purchases=sum(p.purchases for p in page.history),
        key_brl=key_brl,
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/lookup/test_analysis.py -v
```

Esperado: 15 passed

- [ ] **Step 5: Suíte inteira**

```bash
.venv/Scripts/python -m pytest
```

- [ ] **Step 6: Commit**

```bash
git add tf2price/lookup tests/lookup
git -c user.name="gusco" -c user.email="guscostam@gmail.com" commit -F - <<'MSG'
Adiciona a análise da consulta, sem I/O

Dois vereditos lado a lado. A saída imediata mede contra ordens de
compra reais e não depende de referência externa. A saída paciente mede
contra a backpack.tf e carrega a idade do preço, porque a idade mediana
de um preço de Unusual lá é de 749 dias.

Quando a backpack.tf não precifica o efeito escolhido, a saída paciente
fica indisponível com motivo legível, em vez de cair no preço de outro
efeito — que foi o erro que invalidou o projeto anterior.

Livro de ofertas e histórico são repassados sem transformação: são dados
do item inteiro e não podem ser filtrados por efeito.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
```

---

### Task 3: `lookup/app.py` — rotas, cache de página e templates funcionais

**Files:**
- Modify: `pyproject.toml` (acrescenta `fastapi`, `jinja2`; `httpx` já está)
- Create: `tf2price/lookup/app.py`
- Create: `tf2price/lookup/templates/index.html`
- Create: `tf2price/lookup/templates/_itens.html`
- Create: `tf2price/lookup/templates/_efeitos.html`
- Create: `tf2price/lookup/templates/_analise.html`
- Create: `tf2price/lookup/templates/_erro.html`
- Test: `tests/lookup/test_app.py`

**Interfaces produzidas:**
- `CACHE_TTL_S = 300`, `BUSCA_MAX = 25`
- `PageCache(ttl_s=CACHE_TTL_S, clock=time.monotonic)` com `get(key) -> ItemPage | None` e `put(key, page) -> None`
- `Contexto` — dataclass mutável: `steam`, `paginas`, `index`, `key_brl`, `cache`
- `criar_app(contexto: Contexto) -> FastAPI`
- `construir_contexto() -> Contexto` — lê `.env`, monta clientes, baixa o índice da bp.tf e o preço da chave

**Por que o cache existe:** o spec promete **duas requisições por consulta**. Sem
cache, escolher o efeito e depois ver a análise buscaria a mesma página duas
vezes. O cache guarda a `ItemPage` por `hash_name` com TTL curto.

O relógio é injetável para que o teste de expiração não durma.

**Rotas:**

| Método | Rota | Devolve |
|---|---|---|
| GET | `/` | `index.html` — formulário |
| GET | `/buscar?q=` | `_itens.html` — nomes Unusual que casam |
| GET | `/efeitos?nome=` | `_efeitos.html` — efeitos à venda |
| GET | `/analise?nome=&efeito=` | `_analise.html` — a análise |

Toda rota que fale com a Steam captura `PageStructureError` e `RuntimeError` e
devolve `_erro.html` com a mensagem — nunca um traceback de 500. Se a Valve mudar
a estrutura da página, o usuário tem que ler o que quebrou, não um erro genérico.

- [ ] **Step 1: Acrescentar as dependências ao `pyproject.toml`**

Na lista `dependencies`, junto das existentes:

```toml
    "fastapi>=0.115",
    "jinja2>=3.1",
```

Depois:

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

- [ ] **Step 2: Escrever o teste que falha**

Arquivo `tests/lookup/test_app.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tf2price.domain.money import Brl
from tf2price.lookup.app import Contexto, PageCache, criar_app
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import PageStructureError, parse_item_page

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOME = "Unusual Taunt: Chairholder"
CHAVE = Brl.from_float(11.73)


def _pagina():
    html = (FIXTURES / "steam_listing_page.html").read_text(encoding="utf-8")
    return parse_item_page(html, NOME)


class _SteamFalso:
    def __init__(self, nomes=(NOME, "Unusual Team Captain")):
        self.nomes = nomes
        self.chamadas = 0

    def search_page(self, start=0, count=100, query=None):
        self.chamadas += 1
        return SearchPage(
            total_count=len(self.nomes),
            results=[
                SearchResult(hash_name=n, lowest_price=Brl.from_cents(1000), sell_listings=1)
                for n in self.nomes
            ],
        )


class _PaginasFalsas:
    def __init__(self, pagina=None, erro=None):
        self._pagina = pagina
        self._erro = erro
        self.chamadas = 0

    def item_page(self, hash_name):
        self.chamadas += 1
        if self._erro:
            raise self._erro
        return self._pagina


def _contexto(steam=None, paginas=None, indice=None):
    return Contexto(
        steam=steam or _SteamFalso(),
        paginas=paginas or _PaginasFalsas(_pagina()),
        index=indice or PriceIndex.from_payload(
            {"response": {"items": {}}}, key_in_refined=64.11
        ),
        key_brl=CHAVE,
        cache=PageCache(),
    )


@pytest.fixture
def cliente():
    ctx = _contexto()
    app = criar_app(ctx)
    cliente = TestClient(app)
    cliente.ctx = ctx
    return cliente


# --- rotas ---------------------------------------------------------------


def test_raiz_serve_o_formulario(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "form" in r.text.lower()


def test_busca_lista_os_nomes(cliente):
    r = cliente.get("/buscar", params={"q": "Chairholder"})
    assert r.status_code == 200
    assert NOME in r.text


def test_busca_vazia_nao_chama_a_steam(cliente):
    cliente.get("/buscar", params={"q": "  "})
    assert cliente.ctx.steam.chamadas == 0


def test_efeitos_lista_os_quatro_a_venda(cliente):
    r = cliente.get("/efeitos", params={"nome": NOME})
    assert r.status_code == 200
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text


def test_analise_mostra_preco_e_oferta(cliente):
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code == 200
    assert "180,44" in r.text        # listagem mais barata do efeito
    assert "106,31" in r.text        # melhor oferta de compra


def test_analise_de_efeito_sem_listagem_avisa(cliente):
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Burning Flames"})
    assert r.status_code == 200
    assert "Burning Flames" in r.text


# --- cache ---------------------------------------------------------------


def test_efeitos_e_analise_do_mesmo_item_buscam_a_pagina_uma_vez(cliente):
    cliente.get("/efeitos", params={"nome": NOME})
    cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert cliente.ctx.paginas.chamadas == 1


def test_cache_expira_pelo_relogio_injetado():
    agora = {"t": 0.0}
    cache = PageCache(ttl_s=10.0, clock=lambda: agora["t"])
    cache.put(NOME, _pagina())

    agora["t"] = 9.0
    assert cache.get(NOME) is not None

    agora["t"] = 11.0
    assert cache.get(NOME) is None


# --- falha de estrutura --------------------------------------------------


def test_mudanca_na_valve_vira_mensagem_e_nao_traceback():
    ctx = _contexto(paginas=_PaginasFalsas(erro=PageStructureError("renderContext sumiu")))
    cliente = TestClient(criar_app(ctx), raise_server_exceptions=False)

    r = cliente.get("/efeitos", params={"nome": NOME})

    assert r.status_code == 200
    assert "renderContext sumiu" in r.text
```

- [ ] **Step 3: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/lookup/test_app.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.lookup.app'`

- [ ] **Step 4: Implementar `tf2price/lookup/app.py`**

```python
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from tf2price.domain.money import Brl
from tf2price.lookup.analysis import analyse, effects_available
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SteamClient
from tf2price.sources.steam_page import ItemPage, PageStructureError, SteamPageClient

CACHE_TTL_S = 300.0
BUSCA_MAX = 25
INTERVALO_S = 1.0

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class PageCache:
    """Guarda a ItemPage por hash_name com TTL curto.

    O spec promete duas requisições por consulta. Sem isto, escolher o efeito
    e depois ver a análise buscariam a mesma página duas vezes.
    """

    def __init__(
        self,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._itens: dict[str, tuple[float, ItemPage]] = {}

    def get(self, chave: str) -> ItemPage | None:
        registro = self._itens.get(chave)
        if registro is None:
            return None
        quando, pagina = registro
        if self._clock() - quando > self._ttl:
            del self._itens[chave]
            return None
        return pagina

    def put(self, chave: str, pagina: ItemPage) -> None:
        self._itens[chave] = (self._clock(), pagina)


@dataclass
class Contexto:
    steam: Any
    paginas: Any
    index: PriceIndex
    key_brl: Brl
    cache: PageCache = field(default_factory=PageCache)


def _erro(request: Request, mensagem: str) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request, name="_erro.html", context={"mensagem": mensagem}
    )


def criar_app(contexto: Contexto) -> FastAPI:
    app = FastAPI(title="Consulta de Unusual")

    def pagina_do_item(nome: str) -> ItemPage:
        em_cache = contexto.cache.get(nome)
        if em_cache is not None:
            return em_cache
        pagina = contexto.paginas.item_page(nome)
        contexto.cache.put(nome, pagina)
        return pagina

    @app.get("/", response_class=HTMLResponse)
    def raiz(request: Request):
        return TEMPLATES.TemplateResponse(request=request, name="index.html", context={})

    @app.get("/buscar", response_class=HTMLResponse)
    def buscar(request: Request, q: str = ""):
        termo = q.strip()
        if not termo:
            return TEMPLATES.TemplateResponse(
                request=request, name="_itens.html", context={"nomes": []}
            )
        try:
            pagina = contexto.steam.search_page(start=0, count=BUSCA_MAX, query=termo)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        nomes = [r.hash_name for r in pagina.results if r.hash_name.startswith("Unusual ")]
        return TEMPLATES.TemplateResponse(
            request=request, name="_itens.html", context={"nomes": nomes[:BUSCA_MAX]}
        )

    @app.get("/efeitos", response_class=HTMLResponse)
    def efeitos(request: Request, nome: str):
        try:
            pagina = pagina_do_item(nome)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        return TEMPLATES.TemplateResponse(
            request=request,
            name="_efeitos.html",
            context={"nome": nome, "efeitos": effects_available(pagina)},
        )

    @app.get("/analise", response_class=HTMLResponse)
    def rota_analise(request: Request, nome: str, efeito: str):
        try:
            pagina = pagina_do_item(nome)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        try:
            resultado = analyse(pagina, efeito, contexto.index, contexto.key_brl)
        except ValueError as erro:
            return _erro(request, str(erro))

        return TEMPLATES.TemplateResponse(
            request=request, name="_analise.html", context={"a": resultado}
        )

    return app


def construir_contexto() -> Contexto:
    """Monta os clientes reais e carrega o índice da backpack.tf uma vez."""
    load_dotenv(".env")
    chave_api = os.getenv("BPTF_API_KEY", "").strip()
    if not chave_api:
        raise RuntimeError("BPTF_API_KEY não configurada. Veja .env.example.")

    bptf = BackpackTfClient(chave_api)
    moedas = bptf.currencies()
    index = PriceIndex.from_payload(bptf.prices_payload(), moedas.key_in_refined)

    limitador = RateLimiter(min_interval_s=INTERVALO_S)
    steam = SteamClient(limitador)
    return Contexto(
        steam=steam,
        paginas=SteamPageClient(limitador),
        index=index,
        key_brl=steam.key_price(),
    )


def servir() -> None:
    """Ponto de entrada: python -m tf2price.lookup.app"""
    import uvicorn

    uvicorn.run(criar_app(construir_contexto()), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    servir()
```

- [ ] **Step 5: Criar os templates**

`tf2price/lookup/templates/index.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Consulta de Unusual</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 62rem; margin: 2rem auto; padding: 0 1rem; }
    input { font-size: 1rem; padding: .5rem; width: 24rem; }
    table { border-collapse: collapse; margin: .5rem 0; }
    td, th { padding: .35rem .7rem; border-bottom: 1px solid #ddd; text-align: left; }
    .bom { color: #0a7c2f; font-weight: 600; }
    .ruim { color: #b3261e; font-weight: 600; }
    .nivel { font-size: .8rem; color: #666; text-transform: uppercase; letter-spacing: .04em; }
    .aviso { background: #fff4e5; border-left: 4px solid #d08b00; padding: .6rem .9rem; margin: .6rem 0; }
    .erro { background: #fdeceb; border-left: 4px solid #b3261e; padding: .6rem .9rem; }
    button { font-size: .95rem; padding: .35rem .8rem; margin: .15rem; cursor: pointer; }
  </style>
</head>
<body>
  <h1>Consulta de Unusual</h1>
  <form onsubmit="return false">
    <input name="q" placeholder="parte do nome, ex: Chairholder"
           hx-get="/buscar" hx-target="#itens" hx-trigger="keyup changed delay:400ms">
  </form>
  <div id="itens"></div>
  <div id="efeitos"></div>
  <div id="analise"></div>
</body>
</html>
```

`_itens.html`:

```html
{% if nomes %}
<p class="nivel">itens encontrados</p>
{% for nome in nomes %}
  <button hx-get="/efeitos" hx-vals='{"nome": {{ nome | tojson }}}'
          hx-target="#efeitos">{{ nome }}</button>
{% endfor %}
{% endif %}
```

`_efeitos.html`:

```html
<h2>{{ nome }}</h2>
{% if efeitos %}
<p class="nivel">efeitos à venda agora</p>
{% for e in efeitos %}
  <button hx-get="/analise"
          hx-vals='{"nome": {{ nome | tojson }}, "efeito": {{ e | tojson }}}'
          hx-target="#analise">{{ e }}</button>
{% endfor %}
{% else %}
<p>Nenhuma listagem com efeito legível nesta página.</p>
{% endif %}
```

`_erro.html`:

```html
<div class="erro"><strong>Não consegui ler os dados da Steam.</strong><br>{{ mensagem }}</div>
```

`_analise.html` — a versão funcional; o Task 4 cuida da apresentação:

```html
<h3>{{ a.effect }}</h3>

<p class="nivel">para este efeito</p>
<table>
  <tr><th>Listagem</th><th>Preço</th></tr>
  {% for l in a.listings %}
  <tr>
    <td><a href="https://steamcommunity.com/market/listings/440/{{ a.hash_name | urlencode }}">{{ l.listing_id }}</a></td>
    <td>{{ l.total_price }}</td>
  </tr>
  {% endfor %}
</table>
<p>Mais barata: <strong>{{ a.cheapest.total_price }}</strong> ({{ "%.1f"|format(a.price_in_keys) }} chaves)</p>

<p class="nivel">saída imediata — ordens reais agora</p>
{% if a.immediate.top_bid %}
<p>
  Melhor oferta de compra: {{ a.immediate.top_bid }} ({{ a.immediate.buy_orders }} ordens).<br>
  Você receberia {{ a.immediate.net_received }} após a taxa de 15%.<br>
  Resultado:
  <span class="{{ 'bom' if a.immediate.result.cents > 0 else 'ruim' }}">{{ a.immediate.result }}</span>
</p>
{% else %}
<p>Não há ordem de compra para este item.</p>
{% endif %}

<p class="nivel">saída paciente — troca via backpack.tf</p>
{% if a.patient.available %}
<p>
  Valor sugerido: {{ "%.1f"|format(a.patient.keys) }} chaves = {{ a.patient.fair_value }}.<br>
  Resultado:
  <span class="{{ 'bom' if a.patient.result.cents > 0 else 'ruim' }}">{{ a.patient.result }}</span>
</p>
<div class="aviso">
  Preço atualizado há <strong>{{ a.patient.age_days }} dias</strong>.
  É preço <em>sugerido</em>, não oferta de compra: ninguém se comprometeu a pagar isso.
</div>
{% else %}
<div class="aviso">Sem saída paciente: {{ a.patient.reason }}.</div>
{% endif %}

<p class="nivel">todos os efeitos deste item — a Steam não separa</p>
<p>
  Menor venda {{ a.orderbook.min_sell_order }} · maior compra {{ a.orderbook.max_buy_order }} ·
  {{ a.orderbook.buy_orders }} ordens de compra · {{ a.orderbook.sell_orders }} de venda.<br>
  Histórico: mediana {{ a.history_median }} em {{ a.history_purchases }} vendas.
</p>
```

- [ ] **Step 6: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/lookup/test_app.py -v
```

Esperado: 9 passed

- [ ] **Step 7: Suíte inteira**

```bash
.venv/Scripts/python -m pytest
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml tf2price/lookup tests/lookup
git -c user.name="gusco" -c user.email="guscostam@gmail.com" commit -F - <<'MSG'
Adiciona as rotas da consulta e o cache de página

Quatro rotas servindo fragmentos HTMX. O cache por hash_name existe
porque o spec promete duas requisições por consulta: sem ele, escolher o
efeito e depois ver a análise buscariam a mesma página duas vezes.

Falha de estrutura da página vira mensagem legível nomeando o que
quebrou, não traceback. Se a Valve mudar o renderContext de novo, quem
abrir a tela precisa entender o motivo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
```

---

### Task 4: execução real e README

O primeiro contato com as APIs reais é o que derrubou o projeto anterior. Este
task existe para que isso aconteça agora, com você olhando, e não depois.

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`

- [ ] **Step 1: Subir a aplicação**

```bash
.venv/Scripts/python -m tf2price.lookup.app
```

Esperado: baixa o índice da backpack.tf (dezenas de MB, demora), busca o preço da
chave, e serve em `http://127.0.0.1:8000`.

Se faltar `BPTF_API_KEY`, tem que falhar com mensagem clara antes de qualquer
outra coisa.

- [ ] **Step 2: Consultar o caso conhecido**

Buscar `Chairholder`, escolher `Unusual Taunt: Chairholder`, escolher `Deep Dive`.

Conferir contra os números já verificados:

| Campo | Esperado |
|---|---|
| Listagem mais barata do efeito | R$ 180,44 |
| Melhor oferta de compra | R$ 106,31 |
| Ordens de compra | 39 |
| Saída imediata | negativa |
| Saída paciente | indisponível — a bp.tf não precifica os efeitos à venda |

Os preços podem ter mudado desde a captura; o que tem que bater é a **forma**: o
efeito escolhido filtra as listagens, o livro de ofertas vem rotulado como do
item inteiro, e a saída paciente diz por que está indisponível.

- [ ] **Step 3: Consultar um item com saída paciente disponível**

Procurar um Unusual cujo efeito à venda **tenha** preço na backpack.tf, para
exercitar o caminho oposto. Se não achar em algumas tentativas, **isso é um
resultado**: registre quantas tentativas e quais itens.

- [ ] **Step 4: Procurar arbitragem dura**

Um item cuja listagem mais barata esteja **abaixo** do líquido da melhor oferta de
compra. Se achar, é lucro imediato verificável. Registre; se não achar, registre
também.

- [ ] **Step 5: Escrever `docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`**

Com o que foi observado, não com o que este plano esperava:

- os números do Chairholder no dia
- quantos itens foram consultados até achar um com saída paciente disponível
- se apareceu arbitragem dura
- qualquer divergência entre a fixture e a página real
- quanto tempo a subida leva por causa do índice da backpack.tf

- [ ] **Step 6: Atualizar o `README.md`**

Acrescentar uma seção sobre a consulta: pré-requisito de chave, como subir, e o
que a tela mostra. Deixar claro que a varredura anterior está aposentada e por
quê, apontando para o findings.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/superpowers/findings
git -c user.name="gusco" -c user.email="guscostam@gmail.com" commit -F - <<'MSG'
Registra o primeiro uso real da consulta

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
```

---

## Cobertura do spec

| Seção do spec | Onde é implementada |
|---|---|
| §2 fluxo em 4 passos, 2 requisições | Task 3 (rotas + `PageCache`) |
| §3 origem dos dados no `renderContext` | Task 1 (`parse_item_page`) |
| §4 regra de honestidade por-efeito × por-item | Task 2 (`Analysis` repassa livro e histórico sem transformar, com teste de regressão) e Task 3 (rótulos `.nivel` nos templates) |
| §5 aritmética da taxa | Task 2 (`net_after_fee`, com teste contra os números observados) |
| §6 saída imediata | Task 2 (`immediate_exit`) |
| §6 saída paciente com idade e indisponibilidade | Task 2 (`patient_exit`, `RAZAO_*`) |
| §7 métricas adicionais | Task 2 (`history_median`, `price_in_keys`) e Task 3 (`_analise.html`) |
| §8 arquitetura e reúso | Estrutura de arquivos deste plano |
| §10 riscos: estrutura muda | Task 1 (`PageStructureError`) e Task 3 (`_erro.html`) |
| §10 riscos: efeito sem preço | Task 2 (`RAZAO_SEM_PRECO`) |
| §10 riscos: efeito fora do mapa | Task 2 (`RAZAO_EFEITO_DESCONHECIDO`) |
| §11 verificação herdada de moeda | Task 1 (`parse_page_price` estrito, recusa pt-BR) |

**Fora de escopo conforme §9:** varredura, worker, alertas, banco, deploy, compra
automática, itens não-Unusual, spells e killstreaker. Nenhum aparece aqui.
