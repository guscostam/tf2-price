# Retrato compartilhado e acompanhamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada pessoa passa a ter a sua lista de Unusuais acompanhados, e o retrato da Steam de cada item vira um dado compartilhado com validade e idade à vista — o que transforma isto de "a consulta atrás de um login" em painel.

**Architecture:** Três peças novas. `preco/serial.py` converte `ItemPage` em dicionário e de volta, para o retrato caber numa coluna de texto. `preco/retrato.py` guarda esse retrato no banco com validade de 15 minutos, força atualização com piso de 60 segundos, e entra em calma de 5 minutos quando a Steam responde 429 — substituindo o `PageCache` de memória. `acompanhamento/` guarda o trio (usuário, item, efeito). A tela finalmente vira duas colunas.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, HTMX, SQLAlchemy 2 Core, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-painel-fechado-design.md`, §5, §7 e §8.

---

## O que este plano fecha

A planta de duas colunas foi aprovada no desenho e adiada duas vezes, porque a
coluna esquerda depende de existir lista de acompanhados. Este plano cria a
lista e então monta a planta.

## Estado de partida

- `master` em produção no Railway, deploy automático a cada push
- 311 testes; nenhum toca a rede
- `painel/consulta.py` tem `Contexto(steam, paginas, indice, cotacao, cache)`,
  onde `cache` é um `PageCache` **de memória** que este plano aposenta
- `sources/steam_page.py` define `ItemPage(hash_name, listings, orderbook,
  history)`, com `PageListing(listing_id, total_price, effect, icon_url)`,
  `OrderBook(max_buy_order, min_sell_order, buy_orders, sell_orders)` e
  `SalePoint(when, median, purchases)`. Dinheiro é `Brl`, que guarda centavos
  inteiros.
- `contas/repositorio.py` é o modelo de como um repositório se parece aqui

## Global Constraints

- Python 3.12+; suíte com `.venv/Scripts/python -m pytest` (Windows).
  **Não use `-q`**: o `pyproject.toml` já traz um, e o segundo vira `-qq` e
  some com a linha-resumo.
- **Nenhum teste faz requisição de rede.** Banco dos testes é SQLite em memória.
- **Todo SQL vive num repositório.** Nenhuma rota e nenhum serviço escreve SQL.
- **Datas em UTC ingênuo** (`db.agora()`), e todo serviço recebe o instante
  como parâmetro.
- **Isolamento entre usuários é obrigatório e testado**: toda leitura e toda
  escrita de acompanhado filtram por `usuario_id`, inclusive a remoção.
- **A idade do dado fica sempre à vista.** É a regra que governa este projeto,
  e agora vale também para o retrato da Steam, não só para o preço da bp.tf.
- **Nenhum dado aparece no lugar de outro.** Sem listagem do efeito salvo, a
  linha diz isso — não mostra o preço de outro efeito.
- CSS próprio, sem framework; comentário explicando o porquê em regra não óbvia.
- Mensagens e nomes em português. Commits em português, no imperativo,
  **sem rodapé de atribuição** (repositório público).
- Trabalhe em branch; o merge na `master` publica.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `tf2price/preco/serial.py` | `ItemPage` ↔ dicionário |
| `tf2price/preco/repositorio.py` | SQL do retrato |
| `tf2price/preco/retrato.py` | validade, força, calma após 429 |
| `tf2price/acompanhamento/repositorio.py` | SQL da lista por usuário |
| `tf2price/db.py` | tabelas `retrato` e `acompanhado` |
| `tf2price/painel/consulta.py` | rotas novas e a coluna esquerda |
| `tf2price/painel/templates/` | `_acompanhados.html` e as duas colunas |

## Sequência

1. `preco/serial.py`
2. tabelas e `preco/repositorio.py`
3. `preco/retrato.py`, aposentando o `PageCache`
4. `acompanhamento/`
5. rotas de acompanhar, remover e atualizar
6. a tela em duas colunas

---

### Task 1: `preco/serial.py` — o retrato cabe em texto

**Files:**
- Create: `tf2price/preco/__init__.py` (vazio), `tf2price/preco/serial.py`
- Test: `tests/preco/__init__.py` (vazio), `tests/preco/test_serial.py`

**Interfaces:**
- Produces: `serial.para_dict(pagina: ItemPage) -> dict`,
  `serial.de_dict(dados: dict) -> ItemPage`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/preco/test_serial.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.preco import serial
from tf2price.sources.steam_page import (
    ItemPage,
    OrderBook,
    PageListing,
    SalePoint,
    parse_item_page,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"


def _pagina_real() -> ItemPage:
    return parse_item_page(FIXTURE.read_text(encoding="utf-8"), "Unusual Taunt: Chairholder", 1.0)


def test_ida_e_volta_devolve_a_mesma_pagina():
    """Se a volta não for idêntica, o retrato guardado mente sobre a Steam."""
    original = _pagina_real()
    assert serial.de_dict(serial.para_dict(original)) == original


def test_ida_e_volta_preserva_centavos_exatos():
    """Dinheiro é inteiro em centavos; um float no meio do caminho arredonda."""
    original = _pagina_real()
    volta = serial.de_dict(serial.para_dict(original))
    assert volta.listings[0].total_price.cents == original.listings[0].total_price.cents


def test_ida_e_volta_com_campos_ausentes():
    """Livro vazio e listagem sem efeito nem ícone são casos reais."""
    pagina = ItemPage(
        hash_name="Unusual Team Captain",
        listings=[PageListing(listing_id="1", total_price=Brl(100), effect=None, icon_url=None)],
        orderbook=OrderBook(max_buy_order=None, min_sell_order=None, buy_orders=0, sell_orders=0),
        history=[],
    )
    assert serial.de_dict(serial.para_dict(pagina)) == pagina


def test_o_dicionario_e_serializavel_em_json():
    import json

    texto = json.dumps(serial.para_dict(_pagina_real()))
    assert serial.de_dict(json.loads(texto)) == _pagina_real()


def test_versao_desconhecida_e_recusada():
    """Mudar a forma do retrato sem migrar os guardados seria ler lixo."""
    with pytest.raises(ValueError, match="versão"):
        serial.de_dict({"versao": 999, "hash_name": "x", "listings": [], "orderbook": {}, "history": []})
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/preco -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.preco'`

- [ ] **Step 3: Implementar `tf2price/preco/serial.py`**

```python
"""`ItemPage` para dicionário e de volta, para o retrato caber numa coluna.

Guardar o HTML seria 266 KB por item; o retrato serializado é alguns KB. A
conversão é explícita, e não um `pickle`, porque este dado vai para o banco e
precisa continuar legível quando a forma do `ItemPage` mudar.
"""

from __future__ import annotations

from typing import Any

from tf2price.domain.money import Brl
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, SalePoint

# Sobe quando a forma mudar. Um retrato gravado com versão diferente é
# descartado em vez de lido torto — ler campo que mudou de significado é
# exatamente como um preço vira outro.
VERSAO = 1


def _centavos(valor: Brl | None) -> int | None:
    return None if valor is None else valor.cents


def _brl(valor: int | None) -> Brl | None:
    return None if valor is None else Brl(int(valor))


def para_dict(pagina: ItemPage) -> dict[str, Any]:
    return {
        "versao": VERSAO,
        "hash_name": pagina.hash_name,
        "listings": [
            {
                "listing_id": l.listing_id,
                "total_price": l.total_price.cents,
                "effect": l.effect,
                "icon_url": l.icon_url,
            }
            for l in pagina.listings
        ],
        "orderbook": {
            "max_buy_order": _centavos(pagina.orderbook.max_buy_order),
            "min_sell_order": _centavos(pagina.orderbook.min_sell_order),
            "buy_orders": pagina.orderbook.buy_orders,
            "sell_orders": pagina.orderbook.sell_orders,
        },
        "history": [
            {"when": p.when, "median": p.median.cents, "purchases": p.purchases}
            for p in pagina.history
        ],
    }


def de_dict(dados: dict[str, Any]) -> ItemPage:
    if dados.get("versao") != VERSAO:
        raise ValueError(f"versão de retrato desconhecida: {dados.get('versao')!r}")
    livro = dados["orderbook"]
    return ItemPage(
        hash_name=dados["hash_name"],
        listings=[
            PageListing(
                listing_id=l["listing_id"],
                total_price=Brl(int(l["total_price"])),
                effect=l["effect"],
                icon_url=l["icon_url"],
            )
            for l in dados["listings"]
        ],
        orderbook=OrderBook(
            max_buy_order=_brl(livro["max_buy_order"]),
            min_sell_order=_brl(livro["min_sell_order"]),
            buy_orders=int(livro["buy_orders"]),
            sell_orders=int(livro["sell_orders"]),
        ),
        history=[
            SalePoint(when=int(p["when"]), median=Brl(int(p["median"])), purchases=int(p["purchases"]))
            for p in dados["history"]
        ],
    )
```

- [ ] **Step 4: Rodar, suíte inteira, commit**

Run: `.venv/Scripts/python -m pytest`

```bash
git add -A && git commit -m "Converte o retrato da pagina em dicionario e de volta"
```

---

### Task 2: as tabelas e `preco/repositorio.py`

**Files:**
- Modify: `tf2price/db.py`
- Create: `tf2price/preco/repositorio.py`
- Test: `tests/preco/test_repositorio.py`

**Interfaces:**
- Produces: tabelas `db.retrato` e `db.acompanhado`;
  `repositorio.guardar(conn, hash_name, dados: str, quando) -> None`,
  `repositorio.ler(conn, hash_name) -> tuple[str, datetime] | None`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/preco/test_repositorio.py`:

```python
from __future__ import annotations

from datetime import timedelta

from tf2price import db
from tf2price.preco import repositorio as repo

AGORA = db.agora()


def test_guardar_e_ler(engine):
    with engine.begin() as conn:
        repo.guardar(conn, "Unusual Team Captain", '{"a": 1}', AGORA)
        lido = repo.ler(conn, "Unusual Team Captain")
    assert lido is not None
    dados, quando = lido
    assert dados == '{"a": 1}'
    assert quando == AGORA


def test_ler_item_nunca_visto_e_none(engine):
    with engine.begin() as conn:
        assert repo.ler(conn, "Item Que Ninguem Abriu") is None


def test_guardar_de_novo_substitui_e_atualiza_a_hora(engine):
    """O retrato é um só por item: o segundo sobrescreve, não duplica."""
    depois = AGORA + timedelta(minutes=20)
    with engine.begin() as conn:
        repo.guardar(conn, "X", '{"v": 1}', AGORA)
        repo.guardar(conn, "X", '{"v": 2}', depois)
        dados, quando = repo.ler(conn, "X")
    assert dados == '{"v": 2}'
    assert quando == depois


def test_nomes_com_apostrofo_e_acento(engine):
    """`Strange Unusual Villain's Veil` existe e já mordeu este projeto."""
    nome = "Strange Unusual Villain's Veil"
    with engine.begin() as conn:
        repo.guardar(conn, nome, "{}", AGORA)
        assert repo.ler(conn, nome) is not None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/preco/test_repositorio.py`
Expected: FAIL com `ImportError` e, depois de criar o módulo, erro de tabela
inexistente

- [ ] **Step 3: As duas tabelas em `tf2price/db.py`**

Ao lado das outras, antes de `url_do_ambiente`:

```python
retrato = Table(
    "retrato",
    METADATA,
    # Um retrato por item, compartilhado por todos: duas pessoas olhando o
    # mesmo chapéu custam uma requisição à Steam, não duas.
    Column("hash_name", String(300), primary_key=True),
    Column("json", Text, nullable=False),
    Column("buscado_em", DateTime, nullable=False),
)

acompanhado = Table(
    "acompanhado",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuario.id"), nullable=False),
    Column("hash_name", String(300), nullable=False),
    # O efeito faz parte da chave: o mesmo chapéu com outro efeito é outro
    # item econômico, e vale outra coisa.
    Column("efeito", String(120), nullable=False),
    Column("criado_em", DateTime, nullable=False),
    UniqueConstraint("usuario_id", "hash_name", "efeito", name="acompanhado_unico"),
)
```

Acrescente `Text` e `UniqueConstraint` ao import de `sqlalchemy` no topo.

- [ ] **Step 4: Implementar `tf2price/preco/repositorio.py`**

```python
"""SQL do retrato compartilhado."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from tf2price import db


def guardar(conn: Connection, hash_name: str, dados: str, quando: datetime) -> None:
    """Grava ou substitui o retrato daquele item.

    Tenta atualizar primeiro e só insere se não havia linha: `ON CONFLICT` e
    `MERGE` se escrevem diferente em cada dialeto, e este projeto roda em
    Postgres e em SQLite.
    """
    resultado = conn.execute(
        update(db.retrato)
        .where(db.retrato.c.hash_name == hash_name)
        .values(json=dados, buscado_em=quando)
    )
    if resultado.rowcount == 0:
        conn.execute(
            insert(db.retrato).values(hash_name=hash_name, json=dados, buscado_em=quando)
        )


def ler(conn: Connection, hash_name: str) -> tuple[str, datetime] | None:
    linha = conn.execute(
        select(db.retrato.c.json, db.retrato.c.buscado_em).where(
            db.retrato.c.hash_name == hash_name
        )
    ).first()
    return (linha.json, linha.buscado_em) if linha else None
```

- [ ] **Step 5: Rodar, suíte inteira, commit**

```bash
git add -A && git commit -m "Acrescenta as tabelas do retrato e do acompanhado"
```

---

### Task 3: `preco/retrato.py` — validade, força e calma

**Files:**
- Create: `tf2price/preco/retrato.py`
- Modify: `tf2price/painel/consulta.py` (aposenta o `PageCache`)
- Test: `tests/preco/test_retrato.py`

**Interfaces:**
- Consumes: `preco.repositorio`, `preco.serial`, o cliente de páginas.
- Produces: `retrato.VALIDADE`, `retrato.PISO_PARA_FORCAR`, `retrato.CALMA_APOS_429`,
  `retrato.Leitura(pagina, buscado_em, limitando)`,
  `retrato.Retratos(paginas, relogio=time.monotonic)` com
  `obter(conn, hash_name, usd_to_brl, quando, forcar=False) -> Leitura`.

**O que esta peça decide.** Ela é a única que fala com a Steam pela página, e
carrega as três regras da §8 da spec: validade de 15 minutos, piso de 60
segundos para forçar, e 5 minutos de calma depois de um 429 — durante os quais
**nenhuma** requisição sai, e o retrato guardado é servido com a idade à vista.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/preco/test_retrato.py`:

```python
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from tf2price import db
from tf2price.preco import repositorio as repo
from tf2price.preco import retrato as mod
from tf2price.preco import serial
from tf2price.sources.steam_page import parse_item_page

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"
NOME = "Unusual Taunt: Chairholder"
AGORA = db.agora()


def _pagina():
    return parse_item_page(FIXTURE.read_text(encoding="utf-8"), NOME, 1.0)


class _PaginasFalsas:
    """Conta chamadas e pode fingir o 429 da Steam."""

    def __init__(self, erro: Exception | None = None):
        self.chamadas = 0
        self.erro = erro

    def item_page(self, hash_name, usd_to_brl):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return _pagina()


class _Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora

    def avancar(self, s):
        self.agora += s


def test_primeira_leitura_busca_e_guarda(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    with engine.begin() as conn:
        leitura = retratos.obter(conn, NOME, 1.0, AGORA)
        assert leitura.pagina.hash_name == NOME
        assert leitura.buscado_em == AGORA
        assert repo.ler(conn, NOME) is not None
    assert paginas.chamadas == 1


def test_dentro_da_validade_nao_busca_de_novo(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)
        leitura = retratos.obter(conn, NOME, 1.0, AGORA + timedelta(minutes=14))
    assert paginas.chamadas == 1
    assert leitura.buscado_em == AGORA


def test_depois_da_validade_busca_de_novo(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    depois = AGORA + mod.VALIDADE + timedelta(seconds=1)
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)
        leitura = retratos.obter(conn, NOME, 1.0, depois)
    assert paginas.chamadas == 2
    assert leitura.buscado_em == depois


def test_o_retrato_e_compartilhado_entre_pessoas(engine):
    """Duas pessoas no mesmo chapéu custam uma requisição, não duas."""
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA + timedelta(minutes=1))
    assert paginas.chamadas == 1


def test_forcar_busca_mesmo_dentro_da_validade(engine):
    paginas = _PaginasFalsas()
    relogio = _Relogio()
    retratos = mod.Retratos(paginas, relogio=relogio)
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)
        relogio.avancar(mod.PISO_PARA_FORCAR.total_seconds() + 1)
        retratos.obter(conn, NOME, 1.0, AGORA + timedelta(minutes=1), forcar=True)
    assert paginas.chamadas == 2


def test_forcar_duas_vezes_seguidas_respeita_o_piso(engine):
    """Sem piso, segurar o botão vira uma enxurrada na Steam."""
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA, forcar=True)
        retratos.obter(conn, NOME, 1.0, AGORA, forcar=True)
    assert paginas.chamadas == 1


def test_429_liga_a_calma_e_serve_o_guardado(engine):
    """A tela mostra o retrato velho dizendo a idade, em vez de quebrar."""
    bons = _PaginasFalsas()
    relogio = _Relogio()
    retratos = mod.Retratos(bons, relogio=relogio)
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)

    bons.erro = RuntimeError("status 429")  # a Steam começa a recusar
    depois = AGORA + mod.VALIDADE + timedelta(minutes=1)
    with engine.begin() as conn:
        leitura = retratos.obter(conn, NOME, 1.0, depois)
    assert leitura.pagina is not None
    assert leitura.buscado_em == AGORA
    assert leitura.limitando is True


def test_durante_a_calma_nenhuma_requisicao_sai(engine):
    ruins = _PaginasFalsas(erro=RuntimeError("status 429"))
    retratos = mod.Retratos(ruins, relogio=_Relogio())
    with engine.begin() as conn:
        retratos.obter(conn, NOME, 1.0, AGORA)
        retratos.obter(conn, NOME, 1.0, AGORA)
        retratos.obter(conn, NOME, 1.0, AGORA)
    assert ruins.chamadas == 1


def test_sem_retrato_e_com_falha_a_leitura_vem_vazia(engine):
    ruins = _PaginasFalsas(erro=RuntimeError("status 429"))
    retratos = mod.Retratos(ruins, relogio=_Relogio())
    with engine.begin() as conn:
        leitura = retratos.obter(conn, NOME, 1.0, AGORA)
    assert leitura.pagina is None
    assert leitura.limitando is True
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/preco/test_retrato.py`
Expected: FAIL com `ImportError: cannot import name 'retrato'`

- [ ] **Step 3: Implementar `tf2price/preco/retrato.py`**

```python
"""O retrato compartilhado de um item: validade, força e calma após 429.

Esta é a única peça que pede a página da Steam. Ela existe porque a Steam
limita por IP, e no Railway todo mundo sai pelo mesmo IP: sem um retrato
compartilhado, dez pessoas olhando o mesmo chapéu custariam dez requisições.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Connection

from tf2price.preco import repositorio as repo
from tf2price.preco import serial
from tf2price.sources.steam_page import ItemPage

VALIDADE = timedelta(minutes=15)
# Sem piso, segurar o botão de atualizar vira enxurrada na Steam.
PISO_PARA_FORCAR = timedelta(seconds=60)
CALMA_APOS_429 = timedelta(minutes=5)


@dataclass(frozen=True)
class Leitura:
    """O retrato e o que a tela precisa dizer sobre ele.

    `buscado_em` nunca é escondido: a idade do dado é a regra que governa
    este projeto, e agora vale também para o que veio da Steam.
    """

    pagina: ItemPage | None
    buscado_em: datetime | None
    limitando: bool


class Retratos:
    def __init__(
        self,
        paginas: Any,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paginas = paginas
        self._relogio = relogio
        # De processo, não de banco: a spec assume uma réplica só, e está
        # escrito lá. Duas réplicas partiriam este freio ao meio.
        self._calma_ate = 0.0
        self._ultima_busca: dict[str, float] = {}

    def obter(
        self,
        conn: Connection,
        hash_name: str,
        usd_to_brl: float,
        quando: datetime,
        forcar: bool = False,
    ) -> Leitura:
        guardado = repo.ler(conn, hash_name)
        pagina, buscado_em = None, None
        if guardado is not None:
            dados, buscado_em = guardado
            try:
                pagina = serial.de_dict(json.loads(dados))
            except (ValueError, KeyError, TypeError):
                # Retrato de uma forma antiga: descartar é mais honesto que
                # ler torto, e a próxima busca regrava.
                pagina, buscado_em = None, None

        if not self._vale_buscar(hash_name, buscado_em, quando, forcar):
            return Leitura(pagina, buscado_em, self._em_calma())

        try:
            nova = self._paginas.item_page(hash_name, usd_to_brl)
        except Exception as erro:
            if "429" in str(erro):
                self._calma_ate = self._relogio() + CALMA_APOS_429.total_seconds()
                print(f"[retrato] Steam limitando: {erro}; calma de "
                      f"{int(CALMA_APOS_429.total_seconds())}s", flush=True)
                return Leitura(pagina, buscado_em, True)
            raise

        self._ultima_busca[hash_name] = self._relogio()
        repo.guardar(conn, hash_name, json.dumps(serial.para_dict(nova)), quando)
        return Leitura(nova, quando, False)

    def _em_calma(self) -> bool:
        return self._relogio() < self._calma_ate

    def _vale_buscar(
        self,
        hash_name: str,
        buscado_em: datetime | None,
        quando: datetime,
        forcar: bool,
    ) -> bool:
        if self._em_calma():
            return False
        if forcar:
            ultima = self._ultima_busca.get(hash_name)
            return ultima is None or self._relogio() - ultima >= PISO_PARA_FORCAR.total_seconds()
        if buscado_em is None:
            return True
        return quando - buscado_em > VALIDADE
```

- [ ] **Step 4: Aposentar o `PageCache` em `tf2price/painel/consulta.py`**

Apague a classe `PageCache` e o campo `cache` do `Contexto`; ponha no lugar
`retratos: Retratos`. Em `construir_contexto`, monte
`Retratos(SteamPageClient(limitador))` e passe o mesmo limitador ao
`SteamClient`, como hoje.

`_pagina_do_item` deixa de existir. As rotas `/efeitos` e `/analise` passam a
receber `conn` e a chamar:

```python
    leitura = contexto.retratos.obter(conn, nome, cotacao.usd_to_brl, db.agora())
    if leitura.pagina is None:
        return _erro(request, SEM_RETRATO)
```

com `SEM_RETRATO = "não consegui ler os dados da Steam, e não há retrato guardado deste item"`.

**Atenção à ordem dos parâmetros:** `usuario` (ou `exigir_admin`) vem antes de
`conn`, pelo motivo comentado em `sessao.py`.

Ajuste `tests/painel/conftest.py`: o contexto falso passa a ter `retratos` em
vez de `cache`, com um duplo que devolve `Leitura(pagina, db.agora(), False)`.

- [ ] **Step 5: Rodar tudo e commitar**

Run: `.venv/Scripts/python -m pytest`
Expected: verde. Se algum teste de `test_consulta.py` quebrar por causa do
contexto, ajuste **só a construção**, nunca a asserção.

```bash
git add -A && git commit -m "Troca o cache de memoria pelo retrato compartilhado"
```

---

### Task 4: `acompanhamento/` — a lista de cada pessoa

**Files:**
- Create: `tf2price/acompanhamento/__init__.py` (vazio), `tf2price/acompanhamento/repositorio.py`
- Test: `tests/acompanhamento/__init__.py` (vazio), `tests/acompanhamento/test_repositorio.py`

**Interfaces:**
- Produces: dataclass `Acompanhado(id, usuario_id, hash_name, efeito, criado_em)`;
  `repositorio.adicionar(conn, *, usuario_id, hash_name, efeito, quando) -> int | None`
  (devolve `None` quando já existe),
  `repositorio.listar(conn, usuario_id) -> list[Acompanhado]`,
  `repositorio.remover(conn, usuario_id, ident) -> bool`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/acompanhamento/test_repositorio.py`:

```python
from __future__ import annotations

from tf2price import db
from tf2price.acompanhamento import repositorio as repo
from tf2price.contas import repositorio as contas

AGORA = db.agora()
NOME = "Unusual Team Captain"


def _pessoa(conn, nome):
    return contas.criar_usuario(conn, nome=nome, senha_hash="h", admin=False, quando=AGORA)


def test_adicionar_e_listar(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        lista = repo.listar(conn, eu)
    assert [(a.hash_name, a.efeito) for a in lista] == [(NOME, "Smoking")]


def test_o_mesmo_trio_nao_entra_duas_vezes(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        primeiro = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        repetido = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 1
    assert primeiro is not None
    assert repetido is None


def test_o_mesmo_chapeu_com_outro_efeito_e_outro_item(engine):
    """Mesmo chapéu, efeito diferente, valores em ordens de grandeza distintas."""
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Terror-Watt", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 2


def test_cada_pessoa_ve_so_a_propria_lista(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        outra = _pessoa(conn, "outra")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 1
        assert repo.listar(conn, outra) == []


def test_ninguem_remove_o_item_de_outra_pessoa(engine):
    """O isolamento vale na escrita, não só na leitura."""
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        outra = _pessoa(conn, "outra")
        meu = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert repo.remover(conn, outra, meu) is False
        assert len(repo.listar(conn, eu)) == 1
        assert repo.remover(conn, eu, meu) is True
        assert repo.listar(conn, eu) == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/acompanhamento`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `tf2price/acompanhamento/repositorio.py`**

```python
"""SQL da lista de itens acompanhados.

Toda função recebe `usuario_id` e filtra por ele — inclusive a remoção. Sem
isso, um id adivinhado apagaria o item de outra pessoa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Connection

from tf2price import db


@dataclass(frozen=True)
class Acompanhado:
    id: int
    usuario_id: int
    hash_name: str
    efeito: str
    criado_em: datetime


def adicionar(
    conn: Connection, *, usuario_id: int, hash_name: str, efeito: str, quando: datetime
) -> int | None:
    """Devolve o id novo, ou None se a pessoa já acompanhava aquele trio.

    Já acompanhar não é erro: é o botão clicado duas vezes.
    """
    try:
        with conn.begin_nested():
            resultado = conn.execute(
                insert(db.acompanhado).values(
                    usuario_id=usuario_id,
                    hash_name=hash_name,
                    efeito=efeito,
                    criado_em=quando,
                )
            )
    except IntegrityError:
        return None
    return int(resultado.inserted_primary_key[0])


def listar(conn: Connection, usuario_id: int) -> list[Acompanhado]:
    linhas = conn.execute(
        select(db.acompanhado)
        .where(db.acompanhado.c.usuario_id == usuario_id)
        .order_by(db.acompanhado.c.criado_em, db.acompanhado.c.id)
    ).all()
    return [
        Acompanhado(
            id=l.id,
            usuario_id=l.usuario_id,
            hash_name=l.hash_name,
            efeito=l.efeito,
            criado_em=l.criado_em,
        )
        for l in linhas
    ]


def remover(conn: Connection, usuario_id: int, ident: int) -> bool:
    """Devolve se removeu. O filtro por usuário é a garantia de isolamento."""
    resultado = conn.execute(
        delete(db.acompanhado).where(
            db.acompanhado.c.id == ident,
            db.acompanhado.c.usuario_id == usuario_id,
        )
    )
    return resultado.rowcount > 0
```

- [ ] **Step 4: Rodar, suíte inteira, commit**

```bash
git add -A && git commit -m "Adiciona a lista de itens acompanhados por pessoa"
```

---

### Task 5: as rotas de acompanhar, remover e atualizar

**Files:**
- Modify: `tf2price/painel/consulta.py`
- Create: `tf2price/painel/templates/_acompanhados.html`
- Modify: `tf2price/painel/templates/_analise.html`
- Test: `tests/painel/test_acompanhar.py`

**Interfaces:**
- Produces: `POST /acompanhar`, `DELETE /acompanhar/{ident}`,
  `POST /atualizar/{hash_name}`, e a função `linhas_acompanhadas(...)` que
  monta o que a coluna esquerda mostra.

**O que cada linha da coluna esquerda mostra**, e os três estados que ela tem
de saber dizer:

| Situação | O que aparece |
|---|---|
| tudo certo | preço na Steam, valor de troca, prêmio, idade do retrato |
| retrato existe, mas sem listagem daquele efeito | *sem listagem deste efeito agora* |
| nunca houve retrato deste item | *sem dado ainda*, com o botão de atualizar |

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_acompanhar.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.acompanhamento import repositorio as repo
from tf2price.contas import repositorio as contas
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from .conftest import NOME, _contexto, cliente_logado

SENHA = "uma senha longa"


def test_acompanhar_guarda_e_aparece_na_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code == 200
    assert "Deep Dive" in r.text
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_acompanhar_duas_vezes_nao_duplica(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_remover_tira_da_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
    r = cliente.delete(f"/acompanhar/{ident}")
    assert r.status_code == 200
    with engine.begin() as conn:
        assert repo.listar(conn, eu.id) == []


def test_ninguem_remove_o_item_de_outra_pessoa_pela_rota(engine):
    """O isolamento tem de valer na rota, não só no repositório."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
        # uma segunda pessoa, com sessão própria
        token = servico.convidar(conn, criado_por=eu.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome="outra", senha=SENHA, quando=db.agora())

    outro = TestClient(criar_app(engine, _contexto()))
    outro.post("/entrar", data={"nome": "outra", "senha": SENHA})
    r = outro.delete(f"/acompanhar/{ident}")

    assert r.status_code in (404, 200)
    with engine.begin() as conn:
        assert len(repo.listar(conn, eu.id)) == 1


def test_acompanhar_exige_sessao(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code in (303, 401)


def test_item_sem_retrato_diz_que_nao_ha_dado_ainda(engine):
    """Acompanhar um item nunca aberto não pode deixar a linha em branco."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": "Unusual Chapeu Nunca Aberto", "efeito": "Smoking"})
    assert "sem dado ainda" in cliente.get("/").text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_acompanhar.py`
Expected: FAIL com 404 nas rotas

- [ ] **Step 3: O fragmento `_acompanhados.html`**

```html
{% if linhas %}
<p class="nivel">acompanhados · {{ linhas|length }}</p>
{% for l in linhas %}
<div class="acompanhado{% if l.selecionado %} escolhido{% endif %}">
  <button class="acompanhado-abrir" hx-get="/analise"
          hx-vals='{"nome": {{ l.hash_name | tojson }}, "efeito": {{ l.efeito | tojson }}}'
          hx-target="#analise">
    <span class="acompanhado-nome">{{ l.hash_name }}</span>
    <span class="acompanhado-efeito">{{ l.efeito }}</span>
    {% if l.preco %}
    <span class="acompanhado-preco">{{ l.preco }}{% if l.premio %} · {{ l.premio }}× {% endif %}</span>
    <span class="acompanhado-idade">retrato de {{ l.idade }}</span>
    {% else %}
    <span class="acompanhado-vazio">{{ l.motivo }}</span>
    {% endif %}
  </button>
  <form hx-post="/atualizar/{{ l.hash_name | urlencode }}" hx-target="#acompanhados" class="acompanhado-acao">
    <button type="submit" title="Atualizar o retrato deste item">↻</button>
  </form>
  <form hx-delete="/acompanhar/{{ l.id }}" hx-target="#acompanhados" class="acompanhado-acao">
    <button type="submit" title="Parar de acompanhar">×</button>
  </form>
</div>
{% endfor %}
{% else %}
<p class="vazio">nada acompanhado ainda</p>
{% endif %}
```

- [ ] **Step 4: As rotas em `tf2price/painel/consulta.py`**

Acrescente a função que monta as linhas e as três rotas:

```python
@dataclass(frozen=True)
class LinhaAcompanhada:
    id: int
    hash_name: str
    efeito: str
    preco: Brl | None
    premio: str | None
    idade: str | None
    motivo: str | None
    selecionado: bool = False


def _idade_por_extenso(quando: datetime, agora: datetime) -> str:
    minutos = int((agora - quando).total_seconds() // 60)
    if minutos < 1:
        return "agora"
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    return f"{horas} h" if horas < 24 else f"{horas // 24} d"


def linhas_acompanhadas(conn, contexto, usuario_id, agora) -> list[LinhaAcompanhada]:
    """O que a coluna esquerda mostra, calculado na hora.

    Nada de preço guardado aqui: a linha sai do mesmo `analyse` do detalhe,
    então a esquerda nunca discorda da direita.
    """
    cotacao = contexto.cotacao.obter()
    saida = []
    for a in acompanhamento.listar(conn, usuario_id):
        guardado = preco_repo.ler(conn, a.hash_name)
        if guardado is None or cotacao is None:
            saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito, None, None, None,
                                          "sem dado ainda"))
            continue
        dados, buscado_em = guardado
        try:
            pagina = serial.de_dict(json.loads(dados))
            resultado = analyse(pagina, a.efeito, contexto.indice.obter(), cotacao.key_brl)
        except ValueError:
            saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito, None, None,
                                          _idade_por_extenso(buscado_em, agora),
                                          "sem listagem deste efeito agora"))
            continue
        premio = None
        if resultado.patient.available and resultado.patient.fair_value.cents > 0:
            premio = f"{resultado.cheapest.total_price.cents / resultado.patient.fair_value.cents:.1f}"
        saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito,
                                      resultado.cheapest.total_price, premio,
                                      _idade_por_extenso(buscado_em, agora), None))
    return saida


@ROTEADOR.post("/acompanhar", response_class=HTMLResponse,
               dependencies=[Depends(ses.mesma_origem)])
def acompanhar(request: Request, nome: str = Form(...), efeito: str = Form(...),
               usuario: Usuario = Depends(ses.usuario_obrigatorio),
               conn: Connection = Depends(ses.conexao)):
    acompanhamento.adicionar(conn, usuario_id=usuario.id, hash_name=nome,
                             efeito=efeito, quando=db.agora())
    return _coluna(request, conn, usuario)


@ROTEADOR.delete("/acompanhar/{ident}", response_class=HTMLResponse,
                 dependencies=[Depends(ses.mesma_origem)])
def parar_de_acompanhar(request: Request, ident: int,
                        usuario: Usuario = Depends(ses.usuario_obrigatorio),
                        conn: Connection = Depends(ses.conexao)):
    acompanhamento.remover(conn, usuario.id, ident)
    return _coluna(request, conn, usuario)


@ROTEADOR.post("/atualizar/{hash_name:path}", response_class=HTMLResponse,
               dependencies=[Depends(ses.mesma_origem)])
def atualizar(request: Request, hash_name: str,
              usuario: Usuario = Depends(ses.usuario_obrigatorio),
              conn: Connection = Depends(ses.conexao)):
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is not None:
        contexto.retratos.obter(conn, hash_name, cotacao.usd_to_brl, db.agora(), forcar=True)
    return _coluna(request, conn, usuario)


def _coluna(request: Request, conn: Connection, usuario: Usuario) -> HTMLResponse:
    linhas = linhas_acompanhadas(conn, _contexto(request), usuario.id, db.agora())
    return TEMPLATES.TemplateResponse(
        request=request, name="_acompanhados.html", context={"linhas": linhas}
    )
```

Acrescente os imports necessários (`dataclass`, `datetime`, `json`, `Form`,
`Connection`, `acompanhamento.repositorio as acompanhamento`,
`preco.repositorio as preco_repo`, `preco.serial as serial`).

No `_analise.html`, acrescente o botão de acompanhar logo abaixo do bloco
`.pago`:

```html
  <form hx-post="/acompanhar" hx-target="#acompanhados" class="acompanhar">
    <input type="hidden" name="nome" value="{{ a.hash_name }}">
    <input type="hidden" name="efeito" value="{{ a.effect }}">
    <button type="submit">acompanhar este efeito</button>
  </form>
```

- [ ] **Step 5: Rodar, suíte inteira, commit**

```bash
git add -A && git commit -m "Acrescenta acompanhar, remover e atualizar"
```

---

### Task 6: a tela em duas colunas

**Files:**
- Modify: `tf2price/painel/templates/painel.html`, `base.html`
- Modify: `tf2price/painel/consulta.py` (a rota `/` passa as linhas)
- Test: `tests/painel/test_consulta.py`

**Interfaces:**
- Consumes: `linhas_acompanhadas`.
- Produces: o painel com `#acompanhados` à esquerda e `#analise` à direita.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/painel/test_consulta.py`:

```python
def test_o_painel_traz_a_coluna_de_acompanhados(engine):
    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/").text
    assert 'id="acompanhados"' in texto
    assert "nada acompanhado ainda" in texto
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_consulta.py -k coluna`
Expected: FAIL — não existe `#acompanhados`

- [ ] **Step 3: A rota `/` passa as linhas**

Em `painel`, acrescente ao contexto do template:

```python
    "linhas": linhas_acompanhadas(conn, contexto, usuario.id, db.agora()),
```

e o parâmetro `conn: Connection = Depends(ses.conexao)` **depois** de `usuario`.

- [ ] **Step 4: As duas colunas no `painel.html`**

Envolva as seções existentes:

```html
<div class="duas-colunas">
  <aside class="coluna-esquerda">
    <section class="campo" data-campo="item">
      ... o campo de busca e #itens, como já está ...
    </section>
    <section class="campo" data-campo="acompanhados">
      <span class="rotulo">Acompanhados</span>
      <div id="acompanhados">
        {% include "_acompanhados.html" %}
      </div>
    </section>
  </aside>
  <main class="coluna-direita">
    <section class="campo" data-campo="efeito"> ... </section>
    <section class="campo" data-campo="avaliacao"> ... </section>
  </main>
</div>
```

- [ ] **Step 5: O CSS das duas colunas em `base.html`**

```css
    /* Duas colunas: a lista acompanha, a avaliação ocupa o espaço. Clicar num
       acompanhado troca só a direita, então a esquerda não pisca nem perde o
       lugar de rolagem. */
    .duas-colunas { display: grid; grid-template-columns: 19rem 1fr; }
    .coluna-esquerda { border-right: 1px solid var(--linha); }
    .coluna-direita { min-width: 0; }

    .acompanhado {
      display: grid; grid-template-columns: 1fr auto auto; gap: .2rem;
      align-items: center; border: 1px solid var(--linha); margin-bottom: .3rem;
    }
    .acompanhado.escolhido { border-color: var(--carimbo); }
    .acompanhado-abrir {
      display: flex; flex-direction: column; gap: .12rem; align-items: flex-start;
      background: none; border: 0; padding: .5rem .6rem; cursor: pointer;
      color: var(--tinta); text-align: left; width: 100%;
    }
    .acompanhado-abrir:hover { background: rgba(228, 231, 236, .07); }
    .acompanhado-nome { font-size: .85rem; }
    .acompanhado-efeito {
      font-family: var(--mono); font-size: .64rem; letter-spacing: .1em;
      text-transform: uppercase; color: var(--tinta-2);
    }
    .acompanhado-preco { font-family: var(--mono); font-size: .8rem; font-weight: 600; }
    .acompanhado-idade, .acompanhado-vazio {
      font-family: var(--mono); font-size: .62rem; color: var(--tinta-2);
    }
    .acompanhado-acao button {
      background: none; border: 0; color: var(--tinta-2); cursor: pointer;
      padding: .3rem .4rem; font-size: .9rem;
    }
    .acompanhado-acao button:hover { color: var(--carimbo); }
    .acompanhar button {
      background: none; border: 1px solid var(--linha); color: var(--tinta);
      font-family: var(--mono); font-size: .7rem; letter-spacing: .1em;
      text-transform: uppercase; padding: .45rem .8rem; cursor: pointer;
      margin-bottom: 1.2rem;
    }
    .acompanhar button:hover { border-color: var(--carimbo); color: var(--carimbo); }

    /* Abaixo de 60rem não cabem duas colunas: a lista vira uma faixa no topo,
       que é o que o celular consegue mostrar sem espremer os números. */
    @media (max-width: 60rem) {
      .duas-colunas { grid-template-columns: 1fr; }
      .coluna-esquerda { border-right: 0; border-bottom: 1px solid var(--linha); }
    }
```

- [ ] **Step 6: Rodar tudo e ver com os olhos**

Run: `.venv/Scripts/python -m pytest`

Suba a aplicação (`DATABASE_URL=sqlite+pysqlite:///painel-local.db` no `.env`),
crie uma conta pelo convite do log, acompanhe dois itens e confira: a esquerda
lista, clicar troca só a direita, atualizar muda a idade, remover tira da lista.
**Não commite o banco local.**

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "Poe o painel em duas colunas"
```

---

## Cobertura da spec

| Seção | Onde |
|---|---|
| §5 tabelas `retrato` e `acompanhado` | Task 2 |
| §7 trio usuário-item-efeito, isolamento | Task 4 |
| §7 "sem listagem deste efeito agora" e "sem dado ainda" | Task 5 |
| §8 validade de 15 min, retrato compartilhado | Task 3 |
| §8 forçar com piso de 60 s | Task 3 |
| §8 calma de 5 min após 429, idade à vista | Tasks 3 e 5 |
| §10 planta de duas colunas | Task 6 |

**Fora deste plano, e recomendado em seguida:** persistir a cotação da chave no
banco. Hoje ela vive só na memória do processo, então todo deploy recomeça
dependendo de a Steam responder naquele instante — foi o que produziu a janela
de cinco minutos sem cotação na primeira subida. Com a infraestrutura do
retrato pronta, isso vira uma tarefa pequena.
