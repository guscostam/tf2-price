# Chave de referência em dinheiro — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** trocar o preço da chave na Steam pela chave de referência em dinheiro (dólar da chave na backpack.tf × PTAX do Banco Central) em toda conta de troca, e descongelar a cotação da Steam.

**Architecture:** a backpack.tf já manda `raw_usd_value` no `IGetPrices`; o `PriceIndex` passa a guardá-lo. Um cliente novo lê a PTAX do serviço Olinda do BC, e uma `PtaxSobDemanda` (molde de `CotacaoSobDemanda`: memória, banco, rede só no fundo) a mantém. Um tipo puro, `ChaveReferencia`, junta os dois a cada requisição, e as rotas passam `referencia.brl` à análise no lugar de `cotacao.key_brl`. A cotação da Steam fica só com a taxa implícita que converte listagens em dólar, agora renovada de verdade.

**Tech Stack:** Python 3.12, FastAPI, Jinja + HTMX, SQLAlchemy Core, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-chave-de-referencia-design.md`

## Global Constraints

- A tela é em inglês (`tests/painel/test_english_ui.py`); comentários, docstrings e mensagens de log seguem em português, como o resto do código.
- Dinheiro é `Brl` (centavos inteiros); a taxa é `float`. A referência arredonda uma vez só: `Brl.from_cents(round(usd * 100 * ptax))`.
- Nenhuma rota vai à rede por causa da referência: `obter` só lê memória e banco; `renovar` é do fio de fundo.
- Tabela nova para a PTAX, nunca coluna nova em tabela existente (`create_all` não acrescenta coluna e o projeto não tem migração).
- A saída imediata e a taxa implícita da Steam não mudam de fonte.
- `tf2price/spike/` não é tocado.
- Comandos (PowerShell, na raiz do repositório):
  - suíte: `.\.venv\Scripts\python.exe -m pytest`
  - focado: `.\.venv\Scripts\python.exe -m pytest tests\caminho\arquivo.py -v`
- Linha de base: `768 passed`. Ao fim de cada tarefa a suíte inteira passa.
- Todo commit termina com as linhas:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_016eQWjrFAbWQ3YCoMkJXScN
  ```

## Mapa de arquivos

| Arquivo | Papel |
| --- | --- |
| `tf2price/sources/backpacktf.py` | `PriceIndex` guarda o dólar do refined e sabe o dólar da chave; `Currencies.key_in_usd` morto sai |
| `tf2price/sources/bcb.py` (novo) | cliente e leitura da PTAX |
| `tf2price/db.py` | tabela `ptax` |
| `tf2price/preco/repositorio.py` | `guardar_ptax` / `ler_ptax` |
| `tf2price/painel/ptax.py` (novo) | `PtaxSobDemanda` |
| `tf2price/sources/steam.py` | `SteamClient.renovar_cotacao` |
| `tf2price/painel/consulta.py` | `CotacaoSobDemanda.renovar` usa `renovar_cotacao`; `Contexto.ptax`; rotas usam a referência |
| `tf2price/preco/referencia.py` (novo) | `ChaveReferencia`, `montar_referencia`, `motivo_sem_referencia` |
| `tf2price/lookup/analysis.py` | aceita referência ausente |
| `tf2price/varredura/leitura.py` | idem, com o mesmo motivo |
| `tf2price/painel/app.py` | aquecimento e renovação da PTAX |
| `tf2price/painel/paginas.py`, `tf2price/painel/varredura.py` | montam a referência |
| templates `overview`, `sources`, `_analise`, `_scan_estado`, `_scan_tabela`, `_chave_referencia` (novo) | mostram a referência e a origem |

---

### Task 1: o dólar da chave no índice da backpack.tf

**Files:**
- Modify: `tf2price/sources/backpacktf.py`
- Modify: `tests/sources/test_backpacktf.py`
- Modify: `tests/fixtures/bptf_currencies.json:33-34`
- Modify: `tests/painel/test_sob_demanda.py:46`

**Interfaces:**
- Produces: `PriceIndex.from_payload(payload, key_in_refined, carregado_em: datetime | None = None)`; `PriceIndex.key_in_usd() -> float | None`; atributo `PriceIndex.carregado_em: datetime` (UTC ingênuo). `Currencies` passa a ter só `key_in_refined`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/sources/test_backpacktf.py`, acrescente `from datetime import datetime, timezone` aos imports e troque o teste de moedas:

```python
def test_currencies_le_chave_em_refined():
    currencies = Currencies.from_payload(_fixture("bptf_currencies.json"))
    assert currencies.key_in_refined == pytest.approx(69.44)
```

E acrescente, logo depois dele:

```python
# --- dólar da chave --------------------------------------------------------


def test_key_in_usd_e_o_dolar_do_refined_vezes_a_chave(index: PriceIndex):
    # A fixture traz raw_usd_value 0.0363 por refined, e a chave vale 69.44 ref.
    assert index.key_in_usd() == pytest.approx(0.0363 * 69.44)


def _indice_com(extra: dict) -> PriceIndex:
    return PriceIndex.from_payload({"response": {"items": {}, **extra}}, 64.11)


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"raw_usd_value": 0.026},
        {"raw_usd_value": 0, "usd_currency": "metal"},
        {"raw_usd_value": -1, "usd_currency": "metal"},
        {"raw_usd_value": "abc", "usd_currency": "metal"},
        {"raw_usd_value": 0.026, "usd_currency": "keys"},
    ],
)
def test_key_in_usd_recusa_o_que_nao_sabe_ler(extra):
    """Moeda inesperada ou valor ruim é recusa, não conta errada."""
    assert _indice_com(extra).key_in_usd() is None


def test_valor_ruim_de_dolar_nao_derruba_o_indice():
    """O índice inteiro não pode sumir por causa do campo de dólar."""
    idx = _indice_com({"raw_usd_value": "abc", "usd_currency": "metal"})
    assert idx.item_names() == set()


def test_carregado_em_e_quem_carregou_que_diz():
    quando = datetime(2026, 9, 22, 12, 0)
    idx = PriceIndex.from_payload({"response": {"items": {}}}, 64.11, carregado_em=quando)
    assert idx.carregado_em == quando


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_carregado_em_padrao_e_agora():
    antes = _agora()
    idx = PriceIndex.from_payload({"response": {"items": {}}}, 64.11)
    assert antes <= idx.carregado_em <= _agora()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_backpacktf.py -v`
Expected: FAIL com `AttributeError: 'PriceIndex' object has no attribute 'key_in_usd'` (e `unexpected keyword argument 'carregado_em'`).

- [ ] **Step 3: Implementar**

Em `tf2price/sources/backpacktf.py`, acrescente aos imports:

```python
from datetime import datetime, timezone
```

Troque `Currencies` inteira por:

```python
@dataclass(frozen=True)
class Currencies:
    key_in_refined: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Currencies":
        # Aqui existia `key_in_usd`, lido de `price.usd`. A bp.tf deixou de
        # mandar esse campo (conferido em 22/09/2026) e ele valia 0 sem
        # ninguém perceber. O dólar da chave agora vem do `IGetPrices`: ver
        # `PriceIndex.key_in_usd`.
        price = payload["response"]["currencies"]["keys"]["price"]
        return cls(key_in_refined=float(price["value"]))
```

Acima de `class PriceIndex`, acrescente:

```python
def _agora_utc() -> datetime:
    # Mesmo formato de `db.agora()` (UTC ingênuo), sem uma fonte de dados
    # importar o módulo do banco.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _positivo_ou_none(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None
```

Troque o `__init__` e o `from_payload` de `PriceIndex` por:

```python
    def __init__(
        self,
        items: dict[str, Any],
        key_in_refined: float,
        raw_usd_value: float | None = None,
        usd_currency: str | None = None,
        carregado_em: datetime | None = None,
    ) -> None:
        if key_in_refined <= 0:
            raise ValueError("key_in_refined tem que ser positivo")
        self._items = items
        self._key_in_refined = key_in_refined
        self._raw_usd_value = raw_usd_value
        self._usd_currency = usd_currency
        # Quando o payload foi baixado. O índice é carregado uma vez por
        # processo e nunca renovado, então esta é a idade do dólar da chave.
        self.carregado_em = carregado_em or _agora_utc()

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        key_in_refined: float,
        carregado_em: datetime | None = None,
    ) -> "PriceIndex":
        response = payload["response"]
        return cls(
            response["items"],
            key_in_refined,
            # Lido com tolerância: um campo de dólar estragado custa só a
            # referência, nunca o índice inteiro.
            raw_usd_value=_positivo_ou_none(response.get("raw_usd_value")),
            usd_currency=response.get("usd_currency"),
            carregado_em=carregado_em,
        )

    def key_in_usd(self) -> float | None:
        """Dólar de uma chave segundo a bp.tf, ou None se não der para saber.

        `raw_usd_value` é o dólar de uma unidade de `usd_currency`, que em
        22/09/2026 era `metal` (o refined): 0.026 × 64.11 ref ≈ US$ 1,67.
        Outra unidade é recusa, não conversão: sem saber o que ela vale em
        chaves, qualquer conta aqui sairia errada em silêncio.
        """
        if self._usd_currency != "metal" or self._raw_usd_value is None:
            return None
        return self._raw_usd_value * self._key_in_refined
```

Em `tests/fixtures/bptf_currencies.json`, remova o campo morto. Troque:

```json
          "last_update": 1759000000,
          "usd": 2.52
```

por:

```json
          "last_update": 1759000000
```

Em `tests/painel/test_sob_demanda.py`, troque `return Currencies(key_in_refined=self._key_in_refined, key_in_usd=0.0)` por:

```python
        return Currencies(key_in_refined=self._key_in_refined)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_backpacktf.py tests\painel\test_sob_demanda.py -v`
Expected: PASS

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add tf2price/sources/backpacktf.py tests/sources/test_backpacktf.py tests/fixtures/bptf_currencies.json tests/painel/test_sob_demanda.py
git commit -m "Índice da bp.tf sabe o dólar da chave e quando foi carregado"
```

---

### Task 2: cliente da PTAX

**Files:**
- Create: `tf2price/sources/bcb.py`
- Test: `tests/sources/test_bcb.py`

**Interfaces:**
- Produces: `Ptax(valor: float, data: datetime)` (frozen); `parse_ptax(payload: dict) -> Ptax`; `BcbClient(client: httpx.Client | None = None)` com `.ptax(hoje: date) -> Ptax`. Falhas levantam `RuntimeError` (formato) ou erro do httpx (rede/status).

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/sources/test_bcb.py`:

```python
"""A PTAX do Banco Central.

Formato medido em 22/09/2026 no serviço Olinda: `value` é uma lista, um item
por dia útil, com `cotacaoVenda` e `dataHoraCotacao` em hora de Brasília.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from tf2price.sources.bcb import BcbClient, Ptax, parse_ptax

RESPOSTA = {
    "@odata.context": "https://was-p.bcnet.bcb.gov.br/olinda/...",
    "value": [
        {"cotacaoCompra": 5.15690, "cotacaoVenda": 5.15750,
         "dataHoraCotacao": "2026-09-18 13:03:34.742036"},
        {"cotacaoCompra": 5.11550, "cotacaoVenda": 5.11610,
         "dataHoraCotacao": "2026-09-22 13:03:30.646171"},
        # Fora de ordem de propósito: a leitura não pode confiar na ordem.
        {"cotacaoCompra": 5.11110, "cotacaoVenda": 5.11170,
         "dataHoraCotacao": "2026-09-21 13:06:51.445645"},
    ],
}


def test_fica_com_a_cotacao_de_venda_mais_recente():
    ptax = parse_ptax(RESPOSTA)
    assert ptax == Ptax(5.1161, datetime(2026, 9, 22, 13, 3, 30, 646171))


def test_microsegundos_com_cinco_digitos():
    # O BC manda "13:05:30.35873": cinco dígitos, sem zero à direita.
    ptax = parse_ptax({"value": [
        {"cotacaoVenda": 5.1527, "dataHoraCotacao": "2026-09-16 13:05:30.35873"},
    ]})
    assert ptax.data == datetime(2026, 9, 16, 13, 5, 30, 358730)


@pytest.mark.parametrize(
    "payload",
    [
        {"value": []},
        {},
        {"value": [{"dataHoraCotacao": "2026-09-22 13:03:30.1"}]},
        {"value": [{"cotacaoVenda": 5.1, "dataHoraCotacao": "ontem"}]},
        {"value": [{"cotacaoVenda": 0, "dataHoraCotacao": "2026-09-22 13:03:30.1"}]},
    ],
)
def test_resposta_fora_do_formato_levanta(payload):
    with pytest.raises(RuntimeError, match="PTAX"):
        parse_ptax(payload)


def test_cliente_pede_a_janela_de_dez_dias_ate_hoje():
    capturadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(200, json=RESPOSTA)

    cliente = BcbClient(httpx.Client(transport=httpx.MockTransport(handler)))

    ptax = cliente.ptax(date(2026, 9, 22))

    assert ptax.valor == 5.1161
    pedido = capturadas[0]
    assert "CotacaoDolarPeriodo(" in pedido.url.path
    assert pedido.url.params["@dataInicial"] == "'09-12-2026'"
    assert pedido.url.params["@dataFinalCotacao"] == "'09-22-2026'"
    assert pedido.url.params["$format"] == "json"


def test_cliente_com_erro_http_levanta():
    cliente = BcbClient(httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ))
    with pytest.raises(httpx.HTTPStatusError):
        cliente.ptax(date(2026, 9, 22))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_bcb.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.sources.bcb'`

- [ ] **Step 3: Implementar**

Crie `tf2price/sources/bcb.py`:

```python
"""PTAX do dólar, do serviço Olinda do Banco Central.

A PTAX de venda é o dólar comercial oficial do dia. Aqui ela converte em
reais o preço em dólar da chave segundo a backpack.tf: ver
`preco/referencia.py`. Não confundir com a taxa implícita da Steam
(`SteamClient.usd_to_brl`), que converte o que a própria Steam cobra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
# Dez dias cobrem fim de semana, feriado emendado e atraso de publicação: a
# PTAX só sai em dia útil, e pedir só "hoje" num sábado viria vazio.
JANELA_DIAS = 10


@dataclass(frozen=True)
class Ptax:
    valor: float  # reais por dólar, cotação de venda
    data: datetime  # quando o BC fechou esta cotação, em hora de Brasília


def _data_odata(dia: date) -> str:
    return f"'{dia:%m-%d-%Y}'"


def parse_ptax(payload: dict[str, Any]) -> Ptax:
    """A cotação de venda mais recente da resposta.

    Pega a maior `dataHoraCotacao`, e não a última da lista: nada na
    documentação do BC promete a ordem.
    """
    try:
        linhas = payload["value"]
        if not linhas:
            raise RuntimeError(
                f"PTAX: nenhuma cotação nos últimos {JANELA_DIAS} dias"
            )
        lidas = [
            (datetime.fromisoformat(linha["dataHoraCotacao"]), float(linha["cotacaoVenda"]))
            for linha in linhas
        ]
    except (KeyError, TypeError, ValueError) as erro:
        raise RuntimeError(
            f"PTAX: resposta do Banco Central fora do formato esperado "
            f"({type(erro).__name__})"
        ) from erro
    data, valor = max(lidas)
    if valor <= 0:
        raise RuntimeError("PTAX: cotação de venda não positiva")
    return Ptax(valor=valor, data=data)


class BcbClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price/0.1"},
            follow_redirects=True,
        )

    def ptax(self, hoje: date) -> Ptax:
        resposta = self._http.get(
            URL,
            params={
                "@dataInicial": _data_odata(hoje - timedelta(days=JANELA_DIAS)),
                "@dataFinalCotacao": _data_odata(hoje),
                "$format": "json",
            },
        )
        resposta.raise_for_status()
        return parse_ptax(resposta.json())
```

Atenção: o `RuntimeError` da lista vazia é levantado **dentro** do `try`, mas `RuntimeError` não está entre as exceções capturadas ali, então ele sai com a mensagem própria.

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_bcb.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/sources/bcb.py tests/sources/test_bcb.py
git commit -m "Cliente da PTAX do Banco Central"
```

---

### Task 3: PTAX guardada e renovada sob demanda

**Files:**
- Modify: `tf2price/db.py` (tabela nova, depois de `cotacao`)
- Modify: `tf2price/preco/repositorio.py` (fim do arquivo)
- Create: `tf2price/painel/ptax.py`
- Test: `tests/preco/test_repositorio.py`, `tests/painel/test_ptax.py`

**Interfaces:**
- Consumes: `Ptax`, `BcbClient.ptax(hoje: date)` da Task 2.
- Produces: `preco_repo.guardar_ptax(conn, valor: float, data_cotacao: datetime, quando: datetime) -> None`; `preco_repo.ler_ptax(conn) -> tuple[float, datetime, datetime] | None` (valor, data da cotação, buscado em); `PtaxSobDemanda(bcb, espera_apos_falha_s=300.0, relogio=time.monotonic)` com `.obter(engine) -> Ptax | None` e `.renovar(engine, quando: datetime) -> Ptax | None`; `VALIDADE_PTAX = timedelta(hours=1)`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/preco/test_repositorio.py`, troque `from datetime import timedelta` por `from datetime import datetime, timedelta` (o módulo importa o repositório como `repo`) e acrescente ao fim:

```python
# --- PTAX ------------------------------------------------------------------


def test_ptax_guardada_e_lida(engine):
    data = datetime(2026, 9, 21, 13, 6, 51)
    quando = datetime(2026, 9, 22, 10, 0)
    with engine.begin() as conn:
        repo.guardar_ptax(conn, 5.1117, data, quando)
    with engine.begin() as conn:
        assert repo.ler_ptax(conn) == (5.1117, data, quando)


def test_ptax_nova_substitui_a_velha(engine):
    with engine.begin() as conn:
        repo.guardar_ptax(conn, 5.0, datetime(2026, 9, 18), datetime(2026, 9, 19))
        repo.guardar_ptax(conn, 5.1, datetime(2026, 9, 21), datetime(2026, 9, 22))
    with engine.begin() as conn:
        assert repo.ler_ptax(conn)[0] == 5.1


def test_sem_ptax_guardada_le_none(engine):
    with engine.begin() as conn:
        assert repo.ler_ptax(conn) is None
```

Crie `tests/painel/test_ptax.py`:

```python
"""A PTAX sob demanda: mesma divisão de `CotacaoSobDemanda`.

`obter` só lê (memória, banco) e é o que as rotas chamam; `renovar` vai à
rede e só o fio de fundo chama. A validade é de 1 hora porque a PTAX sai uma
vez por dia.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tf2price import db
from tf2price.painel.ptax import VALIDADE_PTAX, PtaxSobDemanda
from tf2price.preco import repositorio as preco_repo
from tf2price.sources.bcb import Ptax

AGORA = db.agora()
DATA_DO_BC = datetime(2026, 9, 21, 13, 6, 51)


class _Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


class _BcbFalso:
    def __init__(self, valor: float = 5.1117) -> None:
        self.valor = valor
        self.chamadas = 0
        self.dias: list[date] = []
        self.falhar = False

    def ptax(self, hoje: date) -> Ptax:
        self.chamadas += 1
        self.dias.append(hoje)
        if self.falhar:
            raise RuntimeError("BC fora do ar")
        return Ptax(self.valor, DATA_DO_BC)


def _guardar(engine, valor: float, buscado_em: datetime) -> None:
    with engine.begin() as conn:
        preco_repo.guardar_ptax(conn, valor, DATA_DO_BC, buscado_em)


def test_obter_com_banco_vazio_nao_vai_ao_bc(engine):
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).obter(engine) is None
    assert bcb.chamadas == 0


def test_obter_le_do_banco_no_processo_novo(engine):
    _guardar(engine, 5.0, AGORA - timedelta(days=2))
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).obter(engine) == Ptax(5.0, DATA_DO_BC)
    assert bcb.chamadas == 0


def test_renovar_busca_grava_e_diz_no_log(engine, capsys):
    bcb = _BcbFalso()
    sob = PtaxSobDemanda(bcb)

    assert sob.renovar(engine, AGORA) == Ptax(5.1117, DATA_DO_BC)

    assert bcb.dias == [AGORA.date()]
    with engine.begin() as conn:
        assert preco_repo.ler_ptax(conn) == (5.1117, DATA_DO_BC, AGORA)
    assert "[ptax]" in capsys.readouterr().out


def test_renovar_dentro_da_validade_nao_busca(engine):
    _guardar(engine, 5.0, AGORA - VALIDADE_PTAX)
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).renovar(engine, AGORA).valor == 5.0
    assert bcb.chamadas == 0


def test_renovar_vencida_busca_de_novo(engine):
    _guardar(engine, 5.0, AGORA - VALIDADE_PTAX - timedelta(minutes=1))
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).renovar(engine, AGORA).valor == 5.1117
    assert bcb.chamadas == 1


def test_falha_mantem_a_guardada_e_diz_no_log(engine, capsys):
    _guardar(engine, 5.0, AGORA - timedelta(days=1))
    bcb = _BcbFalso()
    bcb.falhar = True

    ptax = PtaxSobDemanda(bcb).renovar(engine, AGORA)

    assert ptax == Ptax(5.0, DATA_DO_BC)
    assert "[sob-demanda] PtaxSobDemanda: RuntimeError" in capsys.readouterr().out


def test_dentro_da_calma_nao_tenta_de_novo(engine):
    relogio = _Relogio()
    bcb = _BcbFalso()
    bcb.falhar = True
    sob = PtaxSobDemanda(bcb, espera_apos_falha_s=300.0, relogio=relogio)

    sob.renovar(engine, AGORA)
    relogio.agora = 299.0
    sob.renovar(engine, AGORA)
    assert bcb.chamadas == 1

    relogio.agora = 301.0
    bcb.falhar = False
    assert sob.renovar(engine, AGORA).valor == 5.1117
    assert bcb.chamadas == 2


def test_obter_depois_de_renovar_usa_a_memoria(engine):
    sob = PtaxSobDemanda(_BcbFalso())
    sob.renovar(engine, AGORA)
    with engine.begin() as conn:
        preco_repo.guardar_ptax(conn, 9.9, DATA_DO_BC, AGORA)
    assert sob.obter(engine).valor == 5.1117
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\preco\test_repositorio.py tests\painel\test_ptax.py -v`
Expected: FAIL com `AttributeError: module 'tf2price.preco.repositorio' has no attribute 'guardar_ptax'` e `ModuleNotFoundError: No module named 'tf2price.painel.ptax'`

- [ ] **Step 3: Implementar**

Em `tf2price/db.py`, logo depois da tabela `cotacao`:

```python
ptax = Table(
    "ptax",
    METADATA,
    # Uma linha só (id 1), como a cotação. Tabela própria, e não colunas em
    # `cotacao`, porque `create_all` não acrescenta colunas a uma tabela que
    # já existe e o projeto não tem migração.
    Column("id", Integer, primary_key=True),
    # Reais por dólar: razão, não dinheiro, por isso float.
    Column("valor", Float, nullable=False),
    # Quando o BC fechou a cotação: é esta a data que a tela mostra.
    Column("data_cotacao", DateTime, nullable=False),
    # Quando nós a buscamos: é esta que decide a validade de 1 hora.
    Column("buscado_em", DateTime, nullable=False),
)
```

Ao fim de `tf2price/preco/repositorio.py`:

```python
# --- PTAX ------------------------------------------------------------------
#
# Mesma linha única e mesmo update-depois-insert da cotação, pelo mesmo
# motivo: o processo novo de cada deploy herda a última PTAX conhecida em vez
# de nascer sem referência.
LINHA_DA_PTAX = 1


def _atualizar_ptax(
    conn: Connection, valor: float, data_cotacao: datetime, quando: datetime
):
    return conn.execute(
        update(db.ptax)
        .where(db.ptax.c.id == LINHA_DA_PTAX)
        .values(valor=valor, data_cotacao=data_cotacao, buscado_em=quando)
    )


def guardar_ptax(
    conn: Connection, valor: float, data_cotacao: datetime, quando: datetime
) -> None:
    resultado = _atualizar_ptax(conn, valor, data_cotacao, quando)
    if resultado.rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(db.ptax).values(
                        id=LINHA_DA_PTAX,
                        valor=valor,
                        data_cotacao=data_cotacao,
                        buscado_em=quando,
                    )
                )
        except IntegrityError:
            _atualizar_ptax(conn, valor, data_cotacao, quando)


def ler_ptax(conn: Connection) -> tuple[float, datetime, datetime] | None:
    """Valor, data da cotação no BC e quando foi buscada."""
    linha = conn.execute(
        select(db.ptax.c.valor, db.ptax.c.data_cotacao, db.ptax.c.buscado_em)
        .where(db.ptax.c.id == LINHA_DA_PTAX)
    ).first()
    if linha is None:
        return None
    return (float(linha.valor), linha.data_cotacao, linha.buscado_em)
```

Crie `tf2price/painel/ptax.py`:

```python
"""A PTAX sob demanda, no molde de `CotacaoSobDemanda` (`painel/consulta.py`).

Mesma divisão, e pelo mesmo motivo medido no Railway em 21/09/2026: `obter`
só lê (memória, banco) e é o que as rotas chamam; `renovar` vai à rede e só
o fio de fundo chama. Nenhuma requisição espera o Banco Central.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.engine import Engine

from tf2price.preco import repositorio as preco_repo
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.bcb import BcbClient, Ptax

# A PTAX sai uma vez por dia útil, por volta das 13h. Buscar de hora em hora
# pega a do dia pouco depois de publicada, sem martelar o BC.
VALIDADE_PTAX = timedelta(hours=1)


class PtaxSobDemanda:
    def __init__(
        self,
        bcb: BcbClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bcb = bcb
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._ptax: Ptax | None = None
        self._buscado_em: datetime | None = None
        self._proxima_tentativa = 0.0
        self._trava = threading.Lock()

    def obter(self, engine: Engine) -> Ptax | None:
        """Só lê: memória, depois banco. **Nunca** vai à rede."""
        em_memoria = self._ptax
        if em_memoria is not None:
            return em_memoria
        # `renovar` segura a trava durante a rede; quem chega nesse
        # intervalo não espera o BC, responde com o que há.
        if not self._trava.acquire(blocking=False):
            return self._ptax
        try:
            if self._ptax is None:
                self._do_banco(engine)
            return self._ptax
        finally:
            self._trava.release()

    def renovar(self, engine: Engine, quando: datetime) -> Ptax | None:
        """Busca no BC se o que há está velho. **Só o fundo chama isto.**"""
        with self._trava:
            if self._ptax is None:
                self._do_banco(engine)
            guardada = self._ptax
            if (
                guardada is not None
                and self._buscado_em is not None
                and quando - self._buscado_em <= VALIDADE_PTAX
            ):
                return guardada
            if self._relogio() < self._proxima_tentativa:
                return guardada
            try:
                nova = self._bcb.ptax(quando.date())
            except Exception as erro:
                # Mesmo formato de `_registra_falha_sob_demanda` em
                # `consulta.py`, que não é importada aqui porque `consulta`
                # importa este módulo.
                print(
                    f"[sob-demanda] PtaxSobDemanda: {type(erro).__name__}: "
                    f"{mensagem_saneada(erro)}; nova tentativa em {self._espera:.0f}s",
                    flush=True,
                )
                self._proxima_tentativa = self._relogio() + self._espera
                # A velha, com a data dela à vista, vale mais que nada.
                return guardada

            self._ptax, self._buscado_em = nova, quando
            with engine.begin() as conn:
                preco_repo.guardar_ptax(conn, nova.valor, nova.data, quando)
            print(
                f"[ptax] R$ {nova.valor:.4f} de {nova.data:%d/%m} — guardada",
                flush=True,
            )
            return nova

    def _do_banco(self, engine: Engine) -> None:
        with engine.begin() as conn:
            guardada = preco_repo.ler_ptax(conn)
        if guardada is not None:
            valor, data_cotacao, buscado_em = guardada
            self._ptax = Ptax(valor, data_cotacao)
            self._buscado_em = buscado_em
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\preco\test_repositorio.py tests\painel\test_ptax.py -v`
Expected: PASS

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add tf2price/db.py tf2price/preco/repositorio.py tf2price/painel/ptax.py tests/preco/test_repositorio.py tests/painel/test_ptax.py
git commit -m "PTAX guardada no banco e renovada sob demanda"
```

---

### Task 4: a cotação da Steam deixa de congelar

**Files:**
- Modify: `tf2price/sources/steam.py` (`_priceoverview`, `_usd_to_brl_rate`, método novo)
- Modify: `tf2price/painel/consulta.py` (`CotacaoSobDemanda.renovar`)
- Test: `tests/sources/test_steam.py`, `tests/painel/test_cotacao.py`, `tests/painel/test_transacao.py`, `tests/painel/test_paginas.py`

**Interfaces:**
- Produces: `SteamClient.renovar_cotacao() -> tuple[Brl, float]` (chave em BRL pelo `lowest_price`, taxa BRL/USD). Só substitui os caches se tudo deu certo.
- `CotacaoSobDemanda.renovar` passa a chamar só `renovar_cotacao()`. Dublês de Steam nos testes passam a implementar `renovar_cotacao` no lugar de `key_price` + `usd_to_brl`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/sources/test_steam.py`, depois de `test_cache_do_priceoverview_nao_vaza_entre_instancias`:

```python
# --- renovação da cotação -------------------------------------------------


def test_renovar_cotacao_busca_de_novo_a_cada_chamada():
    """O conserto do congelamento: o cache do priceoverview não tinha
    validade, e a renovação de 15 em 15 min regravava o mesmo número com
    `buscado_em` novo."""
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente({}, capturadas),
    )

    assert client.renovar_cotacao() == (Brl.from_float(22.14), 6.0)
    client.renovar_cotacao()

    assert sum(1 for r in capturadas if _e_priceoverview(r)) == 4


def test_renovar_cotacao_atualiza_a_taxa_da_busca():
    usd = {"lowest_price": "$3.69"}

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_priceoverview(request):
            if request.url.params.get("currency") == str(CURRENCY_USD):
                return httpx.Response(200, json={"success": True, **usd, "median_price": "$3.70"})
            return httpx.Response(200, json=_fixture("steam_priceoverview.json"))
        return httpx.Response(200, json=_fixture("steam_search_page.json"))

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.renovar_cotacao()
    usd["lowest_price"] = "$3.00"

    _, taxa = client.renovar_cotacao()

    assert taxa == pytest.approx(2214 / 300)
    assert client.usd_to_brl() == pytest.approx(2214 / 300)


def test_renovar_cotacao_que_falha_mantem_a_taxa_antiga():
    """Zerar o cache antes de buscar deixaria a busca da tela sem taxa até a
    próxima renovação boa. Por isso a troca só acontece no sucesso."""
    estado = {"falhar": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if estado["falhar"]:
            return httpx.Response(500)
        if _e_priceoverview(request):
            return _priceoverview_response(request)
        return httpx.Response(200, json=_fixture("steam_search_page.json"))

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
        max_retries=0,
    )
    client.renovar_cotacao()
    estado["falhar"] = True

    with pytest.raises(RuntimeError):
        client.renovar_cotacao()

    # Lida do cache, sem ir à rede (que agora só devolve 500).
    assert client.usd_to_brl() == 6.0
    assert client.key_price() == Brl.from_float(22.14)
```

Confira que `CURRENCY_USD` e `pytest` já estão importados no topo de `tests/sources/test_steam.py` (o arquivo usa `CURRENCY_USD` em `_priceoverview_response`); se `pytest` faltar, acrescente `import pytest`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_steam.py -v -k renovar_cotacao`
Expected: FAIL com `AttributeError: 'SteamClient' object has no attribute 'renovar_cotacao'`

- [ ] **Step 3: Implementar no cliente**

Em `tf2price/sources/steam.py`, logo acima de `class SteamClient` (fora da classe), acrescente:

```python
def _taxa_da_chave(brl_payload: dict[str, Any], usd_payload: dict[str, Any]) -> float:
    """preço_da_chave_em_BRL_centavos / preço_da_chave_em_USD_centavos."""
    brl_cents = parse_price_text(brl_payload["lowest_price"]).cents
    usd_cents = parse_usd_price_text(usd_payload["lowest_price"])
    if usd_cents <= 0:
        raise RuntimeError(
            "priceoverview devolveu preço de chave em USD não positivo; "
            "sem denominador não há como converter a busca para reais"
        )
    return brl_cents / usd_cents
```

Troque o corpo de `_priceoverview` (mantendo a docstring) por:

```python
        cached = self._priceoverview_cache.get(currency)
        if cached is None:
            cached = self._buscar_priceoverview(currency)
            self._priceoverview_cache[currency] = cached
        return cached

    def _buscar_priceoverview(self, currency: int) -> dict[str, Any]:
        return self._get(
            f"{BASE}/market/priceoverview/",
            {
                "appid": APPID,
                "currency": currency,
                "market_hash_name": KEY_HASH_NAME,
            },
        )
```

Troque o corpo de `_usd_to_brl_rate` (mantendo a docstring, mas trocando a última frase "Calculada uma vez por instância e guardada." por "Calculada uma vez por instância e guardada; `renovar_cotacao` é quem a troca.") por:

```python
        if self._usd_to_brl is None:
            self._usd_to_brl = _taxa_da_chave(
                self._priceoverview(CURRENCY_BRL), self._priceoverview(CURRENCY_USD)
            )
        return self._usd_to_brl
```

Logo depois de `usd_to_brl`, acrescente:

```python
    def renovar_cotacao(self) -> tuple[Brl, float]:
        """Busca a chave de novo, sem olhar o cache, e devolve (chave, taxa).

        Existe porque o cache do priceoverview não tem validade: sem isto, a
        cotação renovada de 15 em 15 min era o mesmo número da subida com
        `buscado_em` novo, e a tela dizia "agora" para um preço de dias.

        Os caches só são trocados depois que as duas buscas e a conta deram
        certo. Zerá-los antes deixaria `search_page`, que usa a mesma taxa,
        sem taxa nenhuma durante um 429.
        """
        brl = self._buscar_priceoverview(CURRENCY_BRL)
        usd = self._buscar_priceoverview(CURRENCY_USD)
        taxa = _taxa_da_chave(brl, usd)
        chave = parse_price_text(brl["lowest_price"])
        self._priceoverview_cache = {CURRENCY_BRL: brl, CURRENCY_USD: usd}
        self._usd_to_brl = taxa
        return chave, taxa
```

- [ ] **Step 4: Rodar os testes do cliente**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_steam.py -v`
Expected: PASS

- [ ] **Step 5: `CotacaoSobDemanda.renovar` usa a renovação e os dublês acompanham**

Em `tf2price/painel/consulta.py`, dentro de `CotacaoSobDemanda.renovar`, troque:

```python
            try:
                nova = Cotacao(
                    key_brl=self._steam.key_price(),
                    usd_to_brl=self._steam.usd_to_brl(),
                    buscado_em=quando,
                )
```

por:

```python
            try:
                # `renovar_cotacao`, e não `key_price()`/`usd_to_brl()`: esses
                # leem o cache do cliente, que não tem validade, e a cotação
                # congelava na vida do processo.
                chave, taxa = self._steam.renovar_cotacao()
                nova = Cotacao(key_brl=chave, usd_to_brl=taxa, buscado_em=quando)
```

Em `tests/painel/test_cotacao.py`, troque os dois métodos de `_SteamClienteFalso` (`key_price` e `usd_to_brl`) por um só:

```python
    def renovar_cotacao(self) -> tuple[Brl, float]:
        # A única porta de rede da cotação: contar aqui basta para saber se
        # o cliente foi ao ar.
        self.chamadas += 1
        if self._demora:
            time.sleep(self._demora)
        if self.falhar:
            raise RuntimeError("Steam fora do ar")
        return Brl.from_float(self._chave), 5.0
```

Em `tests/painel/test_transacao.py`, troque os dois métodos de `_SteamQueObservaOPool` por:

```python
    def renovar_cotacao(self) -> tuple[Brl, float]:
        self.emprestadas_durante_o_io = self.contador["emprestadas"]
        return Brl.from_float(11.73), 5.0
```

Em `tests/painel/test_paginas.py`, dentro de `test_paginas_nao_esperam_renovacao_da_cotacao`, troque os dois métodos de `SteamBloqueada` por:

```python
        def renovar_cotacao(self):
            self.entrou_na_rede.set()
            assert self.liberar_rede.wait(2)
            return CHAVE, 1.0
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_cotacao.py tests\painel\test_transacao.py tests\painel\test_paginas.py -v`
Expected: PASS

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

- [ ] **Step 7: Commit**

```bash
git add tf2price/sources/steam.py tf2price/painel/consulta.py tests/sources/test_steam.py tests/painel/test_cotacao.py tests/painel/test_transacao.py tests/painel/test_paginas.py
git commit -m "Renovação da cotação busca a chave de novo em vez de ler o cache eterno"
```

---

### Task 5: a chave de referência

**Files:**
- Create: `tf2price/preco/referencia.py`
- Test: `tests/preco/test_referencia.py`

**Interfaces:**
- Consumes: `PriceIndex.key_in_usd()`, `PriceIndex.carregado_em` (Task 1); `Ptax` (Task 2).
- Produces:
  - `ChaveReferencia(brl: Brl, usd: float, ptax: float, ptax_data: datetime, bptf_carregado_em: datetime)` com a propriedade `ptax_formatada -> Brl`;
  - `montar_referencia(indice: PriceIndex | None, ptax: Ptax | None) -> ChaveReferencia | None`;
  - `motivo_sem_referencia(indice: PriceIndex | None, ptax: Ptax | None) -> str | None`;
  - constantes `FALTA_INDICE`, `FALTA_PTAX`, `FALTA_DOLAR_BPTF`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/preco/test_referencia.py`:

```python
"""A chave de referência: dólar da chave na bp.tf × PTAX.

Números escolhidos para a conta fechar de cabeça: 0.0183 US$/ref × 64.11 ref
= US$ 1,173213 por chave; × R$ 10,00 = R$ 11,73.
"""

from __future__ import annotations

from datetime import datetime

from tf2price.domain.money import Brl
from tf2price.preco.referencia import (
    FALTA_DOLAR_BPTF,
    FALTA_INDICE,
    FALTA_PTAX,
    ChaveReferencia,
    montar_referencia,
    motivo_sem_referencia,
)
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.bcb import Ptax

CARREGADO = datetime(2026, 9, 22, 9, 0)
PTAX = Ptax(10.0, datetime(2026, 9, 21, 13, 6))


def _indice(raw_usd_value=0.0183, usd_currency="metal") -> PriceIndex:
    return PriceIndex.from_payload(
        {"response": {"items": {}, "raw_usd_value": raw_usd_value,
                      "usd_currency": usd_currency}},
        64.11,
        carregado_em=CARREGADO,
    )


def test_referencia_e_dolar_da_chave_vezes_ptax():
    ref = montar_referencia(_indice(), PTAX)
    assert ref == ChaveReferencia(
        brl=Brl.from_cents(1173),
        usd=0.0183 * 64.11,
        ptax=10.0,
        ptax_data=PTAX.data,
        bptf_carregado_em=CARREGADO,
    )
    assert motivo_sem_referencia(_indice(), PTAX) is None


def test_arredonda_uma_vez_so():
    # US$ 1,666860 × 5,1161 = R$ 8,5277... -> 853 centavos.
    ref = montar_referencia(_indice(raw_usd_value=0.026), Ptax(5.1161, PTAX.data))
    assert ref.brl == Brl.from_cents(853)


def test_ptax_formatada_para_a_tela():
    ref = montar_referencia(_indice(), Ptax(5.1161, PTAX.data))
    assert str(ref.ptax_formatada) == "R$ 5,12"


def test_sem_indice():
    assert montar_referencia(None, PTAX) is None
    assert motivo_sem_referencia(None, PTAX) == FALTA_INDICE


def test_sem_ptax():
    assert montar_referencia(_indice(), None) is None
    assert motivo_sem_referencia(_indice(), None) == FALTA_PTAX


def test_sem_dolar_na_bptf():
    indice = _indice(usd_currency="keys")
    assert montar_referencia(indice, PTAX) is None
    assert motivo_sem_referencia(indice, PTAX) == FALTA_DOLAR_BPTF


def test_referencia_de_zero_centavos_e_ausencia():
    """Zero centavos viraria divisão por zero em "N chaves"."""
    indice = _indice(raw_usd_value=0.00001)
    assert montar_referencia(indice, PTAX) is None
    assert motivo_sem_referencia(indice, PTAX) == FALTA_DOLAR_BPTF


def test_o_indice_falta_antes_da_ptax():
    """A ordem do motivo é a ordem de carregamento: índice, PTAX, dólar."""
    assert motivo_sem_referencia(None, None) == FALTA_INDICE
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\preco\test_referencia.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.preco.referencia'`

- [ ] **Step 3: Implementar**

Crie `tf2price/preco/referencia.py`:

```python
"""A chave de referência: quanto uma chave vale em dinheiro.

A backpack.tf dá o dólar da chave (`PriceIndex.key_in_usd`) e o Banco Central
dá o dólar em reais (PTAX). O produto é a régua que converte "N chaves" em
reais em toda conta de troca. O preço da chave na Steam não serve para isso:
é saldo preso, e o preço de compra com a taxa embutida. Medido em
22/09/2026: R$ 11,68 na Steam contra ≈ R$ 8,50 aqui. Ver
`specs/2026-09-22-chave-de-referencia-design.md`.

Montada a cada requisição, do que já está em memória (índice) e no banco
(PTAX). Nunca vai à rede.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.bcb import Ptax

FALTA_INDICE = "the backpack.tf price index has not loaded yet"
FALTA_PTAX = "the PTAX dollar rate from the Central Bank of Brazil has not loaded yet"
FALTA_DOLAR_BPTF = "backpack.tf did not report a usable dollar value for the key"


@dataclass(frozen=True)
class ChaveReferencia:
    brl: Brl  # o que as contas usam
    usd: float  # dólar da chave na bp.tf
    ptax: float  # reais por dólar
    ptax_data: datetime  # quando o BC fechou a cotação
    bptf_carregado_em: datetime  # idade do dólar da chave

    @property
    def ptax_formatada(self) -> Brl:
        return Brl.from_float(self.ptax)


def montar_referencia(
    indice: PriceIndex | None, ptax: Ptax | None
) -> ChaveReferencia | None:
    if indice is None or ptax is None:
        return None
    usd = indice.key_in_usd()
    if usd is None:
        return None
    # Arredonda uma vez só, na conversão final para centavos.
    brl = Brl.from_cents(round(usd * 100 * ptax.valor))
    if brl.cents <= 0:
        return None
    return ChaveReferencia(
        brl=brl,
        usd=usd,
        ptax=ptax.valor,
        ptax_data=ptax.data,
        bptf_carregado_em=indice.carregado_em,
    )


def motivo_sem_referencia(indice: PriceIndex | None, ptax: Ptax | None) -> str | None:
    """Qual parte falta, para o timbre não ser genérico. None se nada falta."""
    if indice is None:
        return FALTA_INDICE
    if ptax is None:
        return FALTA_PTAX
    if montar_referencia(indice, ptax) is None:
        return FALTA_DOLAR_BPTF
    return None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\preco\test_referencia.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/preco/referencia.py tests/preco/test_referencia.py
git commit -m "Chave de referência: dólar da chave na bp.tf vezes PTAX"
```

---

### Task 6: a análise e a varredura aceitam referência ausente

**Files:**
- Modify: `tf2price/lookup/analysis.py`
- Modify: `tf2price/varredura/leitura.py`
- Test: `tests/lookup/test_analysis.py`, `tests/varredura/test_leitura.py`

**Interfaces:**
- Produces: `RAZAO_SEM_REFERENCIA` em `tf2price.lookup.analysis`; `patient_exit(..., key_brl: Brl | None, ...)`; `analyse(..., key_brl: Brl | None, ...)`; `Analysis.price_in_keys: float | None`; `Analysis.key_brl: Brl | None`. `leitura.SEM_COTACAO` deixa de existir; `leitura.avaliar` usa `RAZAO_SEM_REFERENCIA`.
- O parâmetro continua se chamando `key_brl`: agora é o preço de referência da chave, e quem chama passa `referencia.brl`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/lookup/test_analysis.py`, acrescente `RAZAO_SEM_REFERENCIA` ao import de `tf2price.lookup.analysis` e, depois de `test_saida_paciente_disponivel_traz_valor_e_idade`:

```python
def test_sem_referencia_a_saida_paciente_diz_que_falta_a_referencia():
    idx = _indice({"Taunt: Chairholder": {"prices": {"5": {"Tradable": {"Craftable": {
        "13": {"currency": "keys", "value": 20.0, "last_update": AGORA - 60 * 86400}
    }}}}}})
    r = patient_exit(Brl.from_cents(12452), NOME, "Burning Flames", idx, None,
                     now=AGORA, effects_path=EFEITOS)
    assert r.available is False
    assert r.reason == RAZAO_SEM_REFERENCIA
    assert r.fair_value is None


def test_sem_indice_vem_antes_de_sem_referencia(pagina: ItemPage):
    """Os motivos que já existiam continuam na frente."""
    r = analyse(pagina, "Deep Dive", None, None, now=AGORA)
    assert r.patient.reason == RAZAO_SEM_INDICE
```

E, depois de `test_analise_converte_para_chaves`:

```python
def test_sem_referencia_a_analise_nao_converte_para_chaves(pagina: ItemPage):
    idx = _indice({"Taunt: Chairholder": {"prices": {}}})
    a = analyse(pagina, "Deep Dive", idx, None, now=AGORA, effects_path=EFEITOS)
    assert a.price_in_keys is None
    assert a.key_brl is None
    # A saída imediata não depende da chave.
    assert a.immediate.top_bid is not None
```

Em `tests/varredura/test_leitura.py`, acrescente `RAZAO_SEM_REFERENCIA` ao import `from tf2price.lookup.analysis import RAZAO_SEM_INDICE, RAZAO_SEM_PRECO` e troque `test_sem_cotacao_nao_tem_resultado` por:

```python
def test_sem_referencia_nao_tem_resultado():
    linha = _avaliar(_l("1", 80000), chave=None)
    assert (linha.resultado, linha.preco_em_chaves) == (None, None)
    assert linha.motivo == RAZAO_SEM_REFERENCIA
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\lookup\test_analysis.py tests\varredura\test_leitura.py -v`
Expected: FAIL com `ImportError: cannot import name 'RAZAO_SEM_REFERENCIA'`

- [ ] **Step 3: Implementar**

Em `tf2price/lookup/analysis.py`, depois de `RAZAO_SEM_INDICE`:

```python
RAZAO_SEM_REFERENCIA = (
    "the reference key price is unavailable "
    "(backpack.tf dollar value or PTAX missing)"
)
```

Em `Analysis`, troque os dois campos:

```python
    price_in_keys: float | None
```

```python
    # Preço de referência da chave em dinheiro (bp.tf × PTAX), ou None se
    # ele não carregou. Não é o preço da chave na Steam.
    key_brl: Brl | None
```

Em `patient_exit`, troque a anotação `key_brl: Brl,` por `key_brl: Brl | None,` e, logo depois do bloco `if index is None: ...`, acrescente:

```python
    if key_brl is None or key_brl.cents <= 0:
        return PatientExit(False, RAZAO_SEM_REFERENCIA, None, None, None, None)
```

Em `analyse`, troque a anotação `key_brl: Brl,` por `key_brl: Brl | None,` e a linha

```python
        price_in_keys=barata.total_price.cents / key_brl.cents,
```

por:

```python
        price_in_keys=(
            barata.total_price.cents / key_brl.cents
            if key_brl is not None and key_brl.cents > 0
            else None
        ),
```

Em `tf2price/varredura/leitura.py`, apague a linha `SEM_COTACAO = "the key exchange rate has not loaded yet"`, troque o import `from tf2price.lookup.analysis import patient_exit` por `from tf2price.lookup.analysis import RAZAO_SEM_REFERENCIA, patient_exit` e troque:

```python
    if key_brl is None or key_brl.cents <= 0:
        return linha(motivo=SEM_COTACAO)
```

por:

```python
    if key_brl is None or key_brl.cents <= 0:
        return linha(motivo=RAZAO_SEM_REFERENCIA)
```

Confira que nada mais usa `leitura.SEM_COTACAO`:

Run: `git grep -n "leitura.SEM_COTACAO"`
Expected: nenhuma linha.

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\lookup\test_analysis.py tests\varredura\test_leitura.py -v`
Expected: PASS

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add tf2price/lookup/analysis.py tf2price/varredura/leitura.py tests/lookup/test_analysis.py tests/varredura/test_leitura.py
git commit -m "Análise e varredura dizem quando falta a chave de referência"
```

---

### Task 7: a PTAX entra no contexto, no aquecimento e na renovação

**Files:**
- Modify: `tf2price/painel/consulta.py` (`Contexto`, `construir_contexto`)
- Modify: `tf2price/painel/app.py` (`aquecer`, `manter_quente`)
- Modify: `tests/painel/conftest.py`
- Test: `tests/painel/test_aquecimento.py`, `tests/painel/test_ptax.py`

**Interfaces:**
- Consumes: `PtaxSobDemanda` (Task 3), `BcbClient` (Task 2).
- Produces: `Contexto.ptax: PtaxSobDemanda` (campo obrigatório, depois de `cotacao`). No `conftest.py` dos testes do painel: `PTAX_DO_TESTE = Ptax(10.0, datetime(2026, 9, 21, 13, 6))`, `USD_DO_TESTE = {"raw_usd_value": 0.0183, "usd_currency": "metal"}` e `_PtaxFalsa(ptax)` com `obter(engine=None)` e `renovar(engine=None, quando=None)`. Com esses valores a referência dos testes do painel é R$ 11,73, igual a `CHAVE`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/painel/test_aquecimento.py`, troque `_ContextoFalso` por:

```python
class _ContextoFalso:
    def __init__(self, cotacao, indice, ptax=None) -> None:
        self.cotacao = cotacao
        self.indice = indice
        self.ptax = ptax if ptax is not None else _Fonte()
```

Troque `test_aquecer_busca_as_duas_e_diz_no_log` por:

```python
def test_aquecer_busca_as_tres_e_diz_no_log(engine, capsys):
    ctx = _ContextoFalso(_Fonte(), _Fonte())

    aquecer(ctx, engine)

    assert ctx.cotacao.chamadas == 1
    assert ctx.ptax.chamadas == 1
    assert ctx.indice.chamadas == 1
    saida = capsys.readouterr().out
    assert "[aquecimento] cotação: ok" in saida
    assert "[aquecimento] PTAX: ok" in saida
    assert "[aquecimento] índice: ok" in saida


def test_ptax_que_falha_nao_impede_a_cotacao_nem_o_indice(engine, capsys):
    ctx = _ContextoFalso(_Fonte(), _Fonte(), ptax=_Fonte(valor=None))

    aquecer(ctx, engine)

    saida = capsys.readouterr().out
    assert "[aquecimento] PTAX: falhou" in saida
    assert ctx.cotacao.chamadas == 1 and ctx.indice.chamadas == 1
```

Em `test_manter_quente_renova_a_cotacao_em_ciclo`, troque a condição do laço de espera e as asserções finais por:

```python
    while (
        min(ctx.cotacao.chamadas, ctx.ptax.chamadas) < 4
        and time.monotonic() < limite
    ):
        time.sleep(0.02)
    parar.set()
    thread.join(timeout=5)

    assert not thread.is_alive(), "`parar` não interrompeu o laço"
    assert ctx.cotacao.chamadas >= 4, "a cotação não está sendo renovada"
    assert ctx.ptax.chamadas >= 4, "a PTAX não está sendo renovada"
    assert ctx.indice.chamadas == 1, "o índice entrou no ciclo sem ser convidado"
```

Ao fim de `tests/painel/test_ptax.py`:

```python
def test_contexto_real_traz_a_ptax_sob_demanda(monkeypatch):
    from tf2price.painel.consulta import construir_contexto

    monkeypatch.setenv("BPTF_API_KEY", "chave-de-teste")
    assert isinstance(construir_contexto().ptax, PtaxSobDemanda)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_aquecimento.py tests\painel\test_ptax.py -v`
Expected: FAIL (`ctx.ptax.chamadas == 0`; `AttributeError: 'Contexto' object has no attribute 'ptax'`).

- [ ] **Step 3: Implementar**

Em `tf2price/painel/consulta.py`, acrescente aos imports:

```python
from tf2price.painel.ptax import PtaxSobDemanda
from tf2price.sources.bcb import BcbClient
```

No dataclass `Contexto`, logo depois de `cotacao: CotacaoSobDemanda`:

```python
    # PTAX do Banco Central, sob demanda. Com o dólar da chave na bp.tf, dá
    # a chave de referência em dinheiro (`preco/referencia.py`), que é a
    # régua das contas de troca. A cotação da Steam acima ficou só com a
    # taxa que converte as listagens em dólar.
    ptax: PtaxSobDemanda
```

Em `construir_contexto`, no `return Contexto(...)`, depois de `cotacao=CotacaoSobDemanda(steam),`:

```python
        ptax=PtaxSobDemanda(BcbClient()),
```

Em `tf2price/painel/app.py`, em `aquecer`, troque as duas linhas finais por:

```python
    _aquece("cotação", lambda: contexto.cotacao.renovar(engine, db.agora()))
    _aquece("PTAX", lambda: contexto.ptax.renovar(engine, db.agora()))
    _aquece("índice", contexto.indice.obter)
```

Em `manter_quente`, troque o laço por:

```python
    while not parar.wait(periodo_s):
        contexto.cotacao.renovar(engine, db.agora())
        # Independente da cotação: `renovar` engole a falha do terceiro, então
        # uma Steam limitando não impede a PTAX, nem o contrário.
        contexto.ptax.renovar(engine, db.agora())
```

E na docstring de `manter_quente`, troque "Aquece uma vez e depois renova a cotação enquanto o processo viver." por "Aquece uma vez e depois renova a cotação e a PTAX enquanto o processo viver."

Em `tests/painel/conftest.py`, acrescente aos imports:

```python
from datetime import datetime

from tf2price.sources.bcb import Ptax
```

Depois de `SENHA = ...`:

```python
# A chave de referência dos testes do painel sai igual a `CHAVE`:
# 0.0183 US$/ref × 64.11 ref × R$ 10,00 = R$ 11,73. Todo índice falso daqui
# precisa de `**USD_DO_TESTE` na `response`, senão não há referência e a
# saída pela troca fica indisponível.
USD_DO_TESTE = {"raw_usd_value": 0.0183, "usd_currency": "metal"}
PTAX_DO_TESTE = Ptax(10.0, datetime(2026, 9, 21, 13, 6))
```

Depois de `_CotacaoFalsa`:

```python
class _PtaxFalsa:
    """Dublê de `PtaxSobDemanda`; a passagem pelo banco tem teste próprio em
    `test_ptax.py`."""

    def __init__(self, ptax):
        self.ptax = ptax

    def obter(self, engine=None):
        return self.ptax

    def renovar(self, engine=None, quando=None):
        return self.ptax
```

Em `_contexto`, troque a construção do índice padrão e acrescente a PTAX:

```python
        indice=_IndiceFalso(indice or PriceIndex.from_payload(
            {"response": {"items": {}, **USD_DO_TESTE}}, key_in_refined=64.11
        )),
        cotacao=_CotacaoFalsa(Cotacao(CHAVE, usd_to_brl, db.agora())),
        ptax=_PtaxFalsa(PTAX_DO_TESTE),
```

Os índices falsos montados dentro dos testes também precisam do dólar, para a Task 8. Acrescente `**USD_DO_TESTE` à `response` de cada um e importe `USD_DO_TESTE` de `.conftest`:
- `tests/painel/test_consulta.py`, `_indice_com_preco` (linha ~476): `{"response": {**USD_DO_TESTE, "items": {...}}}`;
- `tests/painel/test_acompanhar.py`, `_indice_com_preco` (linha ~32): idem;
- `tests/painel/test_scan.py`, `_indice` (linha ~22): idem.

Confira que não sobrou nenhum:

Run: `git grep -n "PriceIndex.from_payload" tests/painel`
Expected: todas as linhas estão em arquivos que usam `USD_DO_TESTE`, exceto `test_consulta.py:~442` (o teste de que `Contexto` sem conversão levanta `TypeError`), que não monta referência e fica como está.

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -v`
Expected: PASS. As rotas ainda usam `cotacao.key_brl`, então nada na tela mudou.

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add tf2price/painel/consulta.py tf2price/painel/app.py tests/painel/conftest.py tests/painel/test_aquecimento.py tests/painel/test_ptax.py tests/painel/test_consulta.py tests/painel/test_acompanhar.py tests/painel/test_scan.py
git commit -m "PTAX no contexto, no aquecimento e no ciclo de renovação"
```

---

### Task 8: as telas passam a usar a chave de referência

**Files:**
- Modify: `tf2price/painel/consulta.py` (rotas `efeitos`, `rota_analise`, `_coluna`, `linhas_acompanhadas`)
- Modify: `tf2price/painel/paginas.py`
- Modify: `tf2price/painel/varredura.py`
- Create: `tf2price/painel/templates/_chave_referencia.html`
- Modify: `tf2price/painel/templates/overview.html`, `sources.html`, `_analise.html`, `_scan_estado.html`, `_scan_tabela.html`
- Test: `tests/painel/test_consulta.py`, `tests/painel/test_paginas.py`, `tests/painel/test_transacao.py`, `tests/painel/test_scan.py`

**Interfaces:**
- Consumes: `montar_referencia`, `motivo_sem_referencia`, `ChaveReferencia` (Task 5); `Contexto.ptax` e os dublês do conftest (Task 7); `analyse(..., key_brl: Brl | None)` (Task 6).
- Produces: `consulta.chave_de_referencia(contexto, engine, indice) -> ChaveReferencia | None`; `linhas_acompanhadas(conn, chave: Brl | None, indice, usuario_id, agora, selecionado=None)` (o 2º parâmetro deixa de ser a cotação); o contexto de `overview.html` e `sources.html` ganha `referencia`, `sem_referencia` e `bptf_idade`; o de `/scan` troca `cotacao`/`sem_cotacao` por `referencia`/`sem_referencia`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/painel/test_consulta.py`, acrescente `_PtaxFalsa` ao import de `.conftest` (e `USD_DO_TESTE`, se a Task 7 ainda não o importou), `from datetime import datetime` se faltar, e troque `test_o_overview_diz_a_idade_da_cotacao` e `test_sem_cotacao_a_tela_diz_e_nao_quebra` por:

```python
def test_o_overview_mostra_a_referencia_e_a_origem(engine):
    """A régua das contas de troca é a chave em dinheiro, com as duas
    idades à vista: a do dólar da bp.tf e a data da PTAX."""
    indice = PriceIndex.from_payload(
        {"response": {"items": {}, **USD_DO_TESTE}}, key_in_refined=64.11,
        carregado_em=db.agora() - timedelta(hours=3),
    )
    cliente = cliente_logado(engine, _contexto(indice=indice))

    texto = cliente.get("/").text

    assert "≈ R$ 11,73" in texto
    assert "US$ 1.17 on backpack.tf" in texto
    assert "loaded 3 h ago" in texto
    assert "R$ 10,00 PTAX (Sep 21)" in texto


def test_sem_ptax_a_tela_diz_o_que_falta(engine):
    ctx = _contexto()
    ctx.ptax = _PtaxFalsa(None)
    cliente = cliente_logado(engine, ctx)

    texto = cliente.get("/").text

    assert "Awaiting evidence" in texto
    assert "PTAX dollar rate" in texto


def test_sem_referencia_a_analise_esconde_as_chaves_e_mantem_a_saida_imediata(engine):
    ctx = _contexto(indice=_indice_com_preco(5))
    ctx.ptax = _PtaxFalsa(None)
    cliente = cliente_logado(engine, ctx)

    texto = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text

    assert "reference key price is unavailable" in texto
    assert " keys ·" not in texto
    assert "106,31" in texto  # melhor oferta de compra: saída imediata segue


def test_sem_cotacao_da_steam_a_analise_diz_e_nao_quebra(engine):
    """A Steam limitando na subida não pode derrubar o painel: sem a taxa
    implícita as listagens em dólar não viram real, e a tela diz isso."""
    ctx = _contexto()
    ctx.cotacao = _CotacaoFalsa(None)
    cliente = cliente_logado(engine, ctx)

    assert cliente.get("/").status_code == 200
    assert "has not loaded yet" in cliente.get(
        "/analise", params={"nome": NOME, "efeito": "Deep Dive"}
    ).text


def test_a_saida_paciente_diz_qual_chave_usou(engine):
    texto = _texto_da_analise(engine, 5)
    assert "Keys valued at ≈ R$ 11,73 each" in texto
```

Em `tests/painel/test_paginas.py`, acrescente:

```python
def test_sources_mostra_a_taxa_da_steam_com_a_idade(engine):
    from datetime import timedelta

    from tf2price import db
    from tf2price.painel.consulta import Cotacao

    from .conftest import _CotacaoFalsa

    ctx = _contexto()
    ctx.cotacao = _CotacaoFalsa(Cotacao(CHAVE, 5.15, db.agora() - timedelta(hours=3)))
    cliente = cliente_logado(engine, ctx)

    texto = cliente.get("/sources").text

    assert "≈ R$ 11,73" in texto
    assert "R$ 5,15 per US$ · captured 3 h" in texto
```

Em `tests/painel/test_transacao.py`, em `test_rota_nunca_dispara_busca_de_cotacao`, troque as duas últimas asserções por:

```python
    # E a Sources mostra a taxa velha com a idade dela, em vez de nada.
    assert "captured 1 d" in respostas["/sources"].text
    assert "captured 1 d" not in respostas["/cases/new"].text
```

Em `tests/painel/test_scan.py`, acrescente:

```python
def test_sem_referencia_o_scan_diz_e_esconde_o_resultado(engine):
    from .conftest import _PtaxFalsa

    _semear(engine, [("1", 80000, "Burning Flames")])
    ctx = _contexto(indice=_indice())
    ctx.ptax = _PtaxFalsa(None)
    cliente = cliente_logado(engine, ctx)

    texto = cliente.get("/scan").text

    assert "PTAX dollar rate" in texto
    assert "R$ 373,00" not in texto


def test_o_cabecalho_do_scan_diz_qual_chave_usa(engine):
    cliente = cliente_logado(engine, _contexto(indice=_indice()))
    assert "× reference key price" in cliente.get("/scan").text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -v`
Expected: FAIL nos testes novos (o overview ainda mostra "Key price · captured", a análise ainda usa `cotacao.key_brl`, etc.).

- [ ] **Step 3: Rotas da consulta**

Em `tf2price/painel/consulta.py`, acrescente aos imports:

```python
from tf2price.preco.referencia import ChaveReferencia, montar_referencia
```

Troque a mensagem `SEM_COTACAO`, que agora fala só da taxa de conversão da Steam (o texto continua contendo "has not loaded yet", que os testes procuram):

```python
SEM_COTACAO = "Steam's dollar conversion rate has not loaded yet. Try again in a few minutes."
```

Depois de `def _contexto(request)`, acrescente:

```python
def chave_de_referencia(
    contexto: Contexto, engine: Engine, indice: PriceIndex | None
) -> ChaveReferencia | None:
    """A régua das contas de troca: dólar da chave na bp.tf × PTAX.

    Montada na hora com o índice em memória e a PTAX de `obter`, que só lê
    memória e banco. Chamar **antes** de abrir a transação da rota: na
    primeira leitura a PTAX passa pelo banco.
    """
    return montar_referencia(indice, contexto.ptax.obter(engine))


def _brl(referencia: ChaveReferencia | None) -> Brl | None:
    return referencia.brl if referencia is not None else None
```

Em `efeitos`, logo depois de `indice = contexto.indice.obter()`:

```python
    referencia = chave_de_referencia(contexto, request.app.state.engine, indice)
```

e troque, na mesma função, `analyse(pagina, efeito, indice, cotacao.key_brl)` por `analyse(pagina, efeito, indice, _brl(referencia))` e `conn, cotacao, indice, usuario.id, agora,` por `conn, _brl(referencia), indice, usuario.id, agora,`.

Em `rota_analise`, faça as mesmas três trocas: `referencia = chave_de_referencia(contexto, request.app.state.engine, indice)` logo depois de `indice = contexto.indice.obter()`, `analyse(pagina, efeito, indice, _brl(referencia))` e `conn, _brl(referencia), indice, usuario.id, agora, selecionado=(nome, efeito),`.

Em `linhas_acompanhadas`, troque a assinatura e o começo:

```python
def linhas_acompanhadas(
    conn, chave, indice, usuario_id, agora, selecionado: tuple[str, str] | None = None
) -> list[LinhaAcompanhada]:
```

Na docstring, troque "Recebe a cotação e o índice já resolvidos" por "Recebe a chave de referência (`Brl | None`) e o índice já resolvidos", e acrescente ao fim da docstring:

```
    Sem chave de referência a linha ainda mostra o preço, que já está em
    reais no retrato; perde só o prêmio, que depende do valor sugerido.
```

Troque `if guardado is None or cotacao is None:` por `if guardado is None:` e `resultado = analyse(pagina, a.efeito, indice, cotacao.key_brl)` por `resultado = analyse(pagina, a.efeito, indice, chave)`.

Troque `_coluna` por:

```python
def _coluna(request: Request, usuario_id: int) -> HTMLResponse:
    """Monta os Case Files sem iniciar a aquisição do índice da backpack.tf."""
    contexto = _contexto(request)
    agora = db.agora()
    indice = contexto.indice.em_memoria()
    referencia = chave_de_referencia(contexto, request.app.state.engine, indice)
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, _brl(referencia), indice, usuario_id, agora)
    return TEMPLATES.TemplateResponse(
        request=request, name="_case_files.html", context={"linhas": linhas}
    )
```

- [ ] **Step 4: Páginas e varredura**

Troque `_estado` em `tf2price/painel/paginas.py` por:

```python
def _estado(request: Request, usuario: Usuario) -> dict:
    contexto = request.app.state.contexto
    engine = request.app.state.engine
    agora = db.agora()
    cotacao = contexto.cotacao.obter(engine)
    indice = contexto.indice.em_memoria()
    ptax = contexto.ptax.obter(engine)
    referencia = montar_referencia(indice, ptax)
    with engine.begin() as conn:
        linhas = linhas_acompanhadas(
            conn, referencia.brl if referencia else None, indice, usuario.id, agora
        )
    return {
        "usuario": usuario,
        # A cotação da Steam só converte listagens em dólar; a Sources mostra
        # a taxa dela com a idade.
        "cotacao": cotacao,
        "cotacao_idade": (
            idade_por_extenso(cotacao.buscado_em, agora) if cotacao else None
        ),
        "referencia": referencia,
        "sem_referencia": motivo_sem_referencia(indice, ptax),
        "bptf_idade": (
            ha_quanto_tempo(referencia.bptf_carregado_em, agora) if referencia else None
        ),
        "indice_pronto": indice is not None,
        "linhas": linhas,
    }
```

e acrescente aos imports de `paginas.py`:

```python
from tf2price.painel.varredura import ha_quanto_tempo
from tf2price.preco.referencia import montar_referencia, motivo_sem_referencia
```

Em `tf2price/painel/varredura.py`, troque o import `from tf2price.painel.consulta import SEM_COTACAO, idade_por_extenso` por:

```python
from tf2price.painel.consulta import idade_por_extenso
from tf2price.preco.referencia import montar_referencia, motivo_sem_referencia
```

Na rota `scan`, troque `cotacao = contexto.cotacao.obter(engine)` e `indice = contexto.indice.em_memoria()` por:

```python
    indice = contexto.indice.em_memoria()
    ptax = contexto.ptax.obter(engine)
    referencia = montar_referencia(indice, ptax)
```

troque `listagens, indice, cotacao.key_brl if cotacao else None, filtros, int(time.time())` por `listagens, indice, referencia.brl if referencia else None, filtros, int(time.time())`, e no dicionário do contexto troque as linhas `"cotacao": cotacao,` e `"sem_cotacao": SEM_COTACAO,` por:

```python
        "referencia": referencia,
        "sem_referencia": motivo_sem_referencia(indice, ptax),
```

- [ ] **Step 5: Templates**

Crie `tf2price/painel/templates/_chave_referencia.html`:

```html
{# A régua das contas de troca: dólar da chave na backpack.tf × PTAX do
   Banco Central. O "≈" é obrigatório: o dólar da bp.tf vem com três casas. #}
{% if referencia %}
<strong>≈ {{ referencia.brl }}</strong>
<p>Per key · US$ {{ "%.2f"|format(referencia.usd) }} on backpack.tf (loaded {{ bptf_idade }}) × {{ referencia.ptax_formatada }} PTAX ({{ referencia.ptax_data.strftime("%b %d") }})</p>
{% else %}
<strong>Awaiting evidence</strong>
<p>Reference unavailable: {{ sem_referencia }}.</p>
{% endif %}
```

Em `overview.html`, troque a `<section class="metric-card" aria-labelledby="exchange-title">` inteira por:

```html
  <section class="metric-card" aria-labelledby="exchange-title">
    <p class="scope-label">CASH REFERENCE</p>
    <h2 id="exchange-title">Exchange rate</h2>
    {% include "_chave_referencia.html" %}
  </section>
```

Em `sources.html`, troque a última `source-card` (a de `CONVERSION`) por:

```html
  <section class="source-card">
    <p class="scope-label">CONVERSION</p>
    <h2>Exchange Rate</h2>
    {% include "_chave_referencia.html" %}
    {% if cotacao %}<p>Steam listings quoted in dollars convert at {{ cotacao.usd_brl_formatado }} per US$ · captured {{ cotacao_idade }}</p>{% endif %}
  </section>
```

Em `_analise.html`, troque a linha do preço de compra

```html
      <p>{{ a.price_in_keys|keys }} keys · cheapest listing for this effect</p>
```

por:

```html
      {% if a.price_in_keys is not none %}
      <p>{{ a.price_in_keys|keys }} keys · cheapest listing for this effect</p>
      {% else %}
      <p>Cheapest listing for this effect</p>
      {% endif %}
```

troque, na lista de listagens,

```html
<span class="evidence-amount"><strong>{{ listing.total_price }}</strong><small>{{ (listing.total_price.cents / a.key_brl.cents)|keys }} keys</small></span>
```

por:

```html
<span class="evidence-amount"><strong>{{ listing.total_price }}</strong>{% if a.key_brl %}<small>{{ (listing.total_price.cents / a.key_brl.cents)|keys }} keys</small>{% endif %}</span>
```

e, na saída paciente, troque

```html
      <p class="evidence-note">Suggested price, not a buy order. No buyer has committed to pay this value.</p>
```

por:

```html
      <p class="evidence-note">Suggested price, not a buy order. No buyer has committed to pay this value.</p>
      <p class="evidence-note">Keys valued at ≈ {{ a.key_brl }} each: backpack.tf dollar price × PTAX.</p>
```

Em `_scan_estado.html`, troque

```html
{% if not cotacao %}
<p class="evidence-note evidence-note--stale" role="status">{{ sem_cotacao }}</p>
{% endif %}
```

por:

```html
{% if not referencia %}
<p class="evidence-note evidence-note--stale" role="status">Results are hidden: {{ sem_referencia }}.</p>
{% endif %}
```

Em `_scan_tabela.html`, troque `· result = backpack.tf value in keys × Steam key price − Steam price` por:

```html
  · result = backpack.tf value in keys × reference key price (backpack.tf dollar × PTAX) − Steam price
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -v`
Expected: PASS

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

Confira que nenhuma conta de chaves ficou no preço da Steam:

Run: `git grep -n "cotacao.key_brl\|cotacao\.key_brl" tf2price`
Expected: nenhuma linha.

- [ ] **Step 7: Ver a tela de verdade**

Suba o painel (`.\.venv\Scripts\python.exe -m tf2price.painel.app`) e confira no log `[aquecimento] PTAX: ok` e `[ptax] R$ ...`. Abra o Overview, uma análise de Unusual com preço na bp.tf e o `/scan`:
- o Overview mostra `≈ R$ 8,xx` (não `R$ 11,xx`), com a idade da bp.tf e a data da PTAX;
- em "Patient Exit", o valor sugerido ≈ chaves × referência;
- a Sources mostra a taxa da Steam com "captured".

- [ ] **Step 8: Commit**

```bash
git add tf2price/painel/consulta.py tf2price/painel/paginas.py tf2price/painel/varredura.py tf2price/painel/templates tests/painel
git commit -m "Telas usam a chave de referência em dinheiro nas contas de troca"
```

---

### Task 9: fechamento

**Files:**
- Modify: `docs/superpowers/specs/2026-09-22-chave-de-referencia-design.md` (status)
- Modify: `README.md` (se descrever a conversão pela chave da Steam)

- [ ] **Step 1: README**

Run: `git grep -n -i "chave\|key price\|exchange" README.md`

Se alguma passagem disser que a saída pela troca converte pelo preço da chave na Steam, troque por: "A saída pela troca converte o preço da backpack.tf em reais pela chave de referência: o dólar da chave segundo a backpack.tf vezes a PTAX do Banco Central. O preço da chave na Steam só é usado para converter listagens que a Steam devolve em dólar." Se nada disser, siga.

- [ ] **Step 2: Status da spec**

Em `docs/superpowers/specs/2026-09-22-chave-de-referencia-design.md`, troque `**Status:** aprovado, não implementado` por `**Status:** implementado`.

- [ ] **Step 3: Suíte e commit**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: tudo passa.

```bash
git add README.md docs/superpowers/specs/2026-09-22-chave-de-referencia-design.md
git commit -m "Spec da chave de referência implementada"
```
