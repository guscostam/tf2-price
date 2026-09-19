# Spike de Validação de Arbitragem TF2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Medir uma vez o mercado de TF2 na Steam contra os preços da backpack.tf e emitir um veredito verde/amarelo/vermelho sobre construir ou não o app completo.

**Architecture:** Um pacote Python `tf2price` com `domain/` puro (zero I/O, testável sem rede), `sources/` para os dois clientes HTTP, e `spike/` que orquestra uma passada única e gera relatório. A separação existe porque `domain/` e `sources/` vão inteiros para o projeto completo; só `spike/` é descartável.

**Tech Stack:** Python 3.12+, httpx, pytest, hypothesis, python-dotenv.

**Spec:** `docs/superpowers/specs/2026-09-19-tf2-arbitragem-spike-design.md`

---

## Glossário

Um engenheiro sem contexto de TF2 precisa disto para ler o resto:

| Termo | O que é |
|---|---|
| **chave** (*key*) | *Mann Co. Supply Crate Key*. A moeda de facto do comércio de TF2. Tudo é cotado em chaves. |
| **refined** (*ref*) | *Refined Metal*. Moeda menor. Uma chave vale dezenas de refined; a taxa flutua. |
| **backpack.tf** (bp.tf) | Site que publica preços sugeridos pela comunidade, em chaves ou refined. |
| **Steam Market** | Mercado oficial da Valve, em dinheiro (aqui, BRL). Saldo não sai da Steam. |
| **`market_hash_name`** | Identificador textual de um item na Steam. Ex: `Strange Professional Killstreak Australium Rocket Launcher`. |
| **Unusual** | Qualidade rara com efeito de partícula. Todos os Unusual do mesmo chapéu **compartilham o mesmo `market_hash_name`**, mas valem valores radicalmente diferentes conforme o efeito. |
| **craftável** | Item *Not Usable in Crafting* tem nome idêntico ao normal e vale uma fração. |
| **`priceindex`** | Campo da bp.tf que desambigua variantes de um mesmo item. Para Unusual, é o id do efeito. |
| **passada rasa** | Varredura paginada da busca da Steam. Devolve só `hash_name` + preço mínimo. Barata. |
| **fetch profundo** | Busca das listagens individuais de um nome. Devolve efeito e craftabilidade. Cara. |

---

## Global Constraints

Requisitos do projeto inteiro. **Todo task os herda implicitamente.**

- **Python >= 3.12.** Usar `from __future__ import annotations` no topo de todo módulo.
- **`tf2price/domain/` não pode importar `httpx`, `requests`, `os`, nem tocar em rede, disco ou relógio do sistema sem injeção.** Onde precisar de "agora", receber `now: int` como parâmetro com default `None`. É isto que torna o domínio testável sem rede — e é a regra mais fácil de quebrar sem perceber.
- **Nenhum teste faz requisição de rede.** Clientes HTTP testam contra fixtures de JSON gravado em `tests/fixtures/`. A única exceção é o Task 11, que é execução real e não é teste.
- **Dinheiro é `Brl`, guardado em centavos inteiros.** Nunca `float` para valor monetário. Nunca comparar reais com `==` em float.
- **Conservadorismo obrigatório:** usar sempre o piso da faixa da bp.tf (`value`, nunca `value_high`) e sempre o preço total pago pelo comprador (`converted_price + converted_fee`). Errar para menos.
- **Steam: `currency=7`** (BRL) e **`l=english`** em toda requisição. Sem `l=english`, as descrições voltam traduzidas e o parsing de efeito e craftabilidade quebra silenciosamente.
- **Constantes fixadas pelo spec**, a serem definidas uma vez e importadas, nunca repetidas como literal:
  - `STEAM_SELLER_FEE = 0.15`
  - `STALE_AFTER_DAYS = 30`
  - `MAX_RANGE_RATIO = 1.25` (guarda 3: `value_high > value * 1.25` reprova)
  - `APPID = 440`, `CURRENCY_BRL = 7`
- **Todo commit termina com estas duas linhas**, separadas do corpo por uma linha em branco:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
  ```
- **Mensagens de commit em português**, no imperativo.

---

## Estrutura de arquivos

```
pyproject.toml
.env.example
.gitignore
scripts/
  fetch_effects.py          # gera data/effects.json a partir do schema da Valve
tf2price/
  __init__.py
  data/
    effects.json            # mapa nome do efeito -> priceindex (gerado)
  domain/                   # PURO. zero I/O.
    __init__.py
    money.py                # Brl, Keys
    identity.py             # parse de market_hash_name -> ItemIdentity
    prefilter.py            # Classification, ValueRange, classify()
    valuation.py            # BptfPrice, Valuation, evaluate(), Guard, check_guards()
    effects.py              # leitura do mapa de efeitos
  sources/                  # I/O. um módulo por origem.
    __init__.py
    ratelimit.py            # RateLimiter, backoff_delays()
    steam.py                # parsers puros + SteamClient
    backpacktf.py           # parsers puros + BackpackTfClient + PriceIndex
  spike/                    # DESCARTÁVEL.
    __init__.py
    pipeline.py             # build_opportunities(): puro, sobre dados já buscados
    report.py               # relatório, veredito, análise da guarda 4
    run.py                  # CLI: amarra tudo e faz o I/O
tests/
  domain/
    test_money.py
    test_identity.py
    test_prefilter.py
    test_valuation.py
  sources/
    test_ratelimit.py
    test_steam.py
    test_backpacktf.py
  spike/
    test_pipeline.py
    test_report.py
  fixtures/
    steam_search_page.json
    steam_listings_unusual.json
    steam_priceoverview.json
    bptf_prices.json
    bptf_currencies.json
docs/superpowers/
  specs/2026-09-19-tf2-arbitragem-spike-design.md
  plans/2026-09-19-tf2-arbitragem-spike.md
  findings/2026-09-19-verificacoes-tecnicas.md   # produzido pelo Task 11
```

**Por que esta divisão:** cada módulo de `domain/` tem uma responsabilidade e nenhuma dependência de rede, então cabe inteiro na cabeça e testa em milissegundos. `sources/` separa parsing puro do cliente HTTP, para que o parsing — onde moram os bugs de verdade — seja testável contra fixtures. `spike/pipeline.py` é puro de propósito: a lógica de decisão do spike precisa de teste, o I/O não.

---

## Sequência de tasks

| # | Entrega | Depende de |
|---|---|---|
| 1 | Scaffolding + `domain/money.py` | — |
| 2 | `domain/identity.py` | 1 |
| 3 | `domain/prefilter.py` | 1 |
| 4 | `domain/valuation.py` | 1, 3 |
| 5 | `sources/ratelimit.py` | 1 |
| 6 | `sources/steam.py` | 1, 5 |
| 7 | `sources/backpacktf.py` | 1, 3, 4 |
| 8 | `domain/effects.py` + `scripts/fetch_effects.py` | 1 |
| 9 | `spike/pipeline.py` | 2, 3, 4, 6, 7, 8 |
| 10 | `spike/report.py` | 9 |
| 11 | `spike/run.py` + execução real + verificações | 10 |

---

### Task 1: Scaffolding e `domain/money.py`

O setup do projeto entra aqui porque é o que o teste de `money.py` precisa para rodar. Não é task própria.

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tf2price/__init__.py`
- Create: `tf2price/domain/__init__.py`
- Create: `tf2price/domain/money.py`
- Create: `tests/__init__.py`
- Create: `tests/domain/__init__.py`
- Test: `tests/domain/test_money.py`

**Interfaces:**
- Consumes: nada.
- Produces: `tf2price.domain.money.Brl` (frozen dataclass, campo `cents: int`, construtores `from_cents(int)` e `from_float(float)`, propriedade `as_float`, operadores `+ - *`, ordenação, `__str__` em formato pt-BR) e `tf2price.domain.money.Keys` (frozen dataclass, campo `amount: float`, método `to_brl(key_brl: Brl) -> Brl`).

- [ ] **Step 1: Criar `pyproject.toml`**

```toml
[project]
name = "tf2price"
version = "0.1.0"
description = "Spike de validação de arbitragem TF2 entre Steam Market e backpack.tf"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "hypothesis>=6.100",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["tf2price*"]

[tool.setuptools.package-data]
tf2price = ["data/*.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Criar `.env.example`**

```
# backpack.tf: obrigatória. https://backpack.tf/developer/apikey/new (login via Steam)
BPTF_API_KEY=

# Steam Web API: só para gerar data/effects.json. https://steamcommunity.com/dev/apikey
STEAM_API_KEY=
```

- [ ] **Step 3: Criar `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
.pytest_cache/
*.egg-info/
build/
dist/
out/
```

- [ ] **Step 4: Criar os `__init__.py` vazios**

```bash
mkdir -p tf2price/domain tf2price/sources tf2price/spike tf2price/data
mkdir -p tests/domain tests/sources tests/spike tests/fixtures
touch tf2price/__init__.py tf2price/domain/__init__.py tf2price/sources/__init__.py tf2price/spike/__init__.py
touch tests/__init__.py tests/domain/__init__.py tests/sources/__init__.py tests/spike/__init__.py
```

- [ ] **Step 5: Instalar o ambiente**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

Esperado: `Successfully installed ... tf2price-0.1.0 ...`

> No Windows o executável é `.venv/Scripts/python`. Em Linux/macOS, `.venv/bin/python`. Todos os comandos seguintes usam `.venv/Scripts/python`; ajuste se estiver em outro sistema.

- [ ] **Step 6: Escrever o teste que falha**

Arquivo `tests/domain/test_money.py`:

```python
from __future__ import annotations

import pytest

from tf2price.domain.money import Brl, Keys


def test_from_float_converte_para_centavos():
    assert Brl.from_float(12.34).cents == 1234


def test_from_cents_e_as_float_sao_inversos():
    assert Brl.from_cents(2214).as_float == pytest.approx(22.14)


def test_soma_e_subtracao():
    assert Brl.from_cents(1000) + Brl.from_cents(250) == Brl.from_cents(1250)
    assert Brl.from_cents(1000) - Brl.from_cents(250) == Brl.from_cents(750)


def test_multiplicacao_arredonda_para_centavo():
    # taxa de 15% da Steam sobre R$ 10,00 deixa R$ 8,50 ao vendedor
    assert Brl.from_float(10.00) * 0.85 == Brl.from_float(8.50)


def test_ordenacao():
    assert Brl.from_cents(100) < Brl.from_cents(200)
    assert max(Brl.from_cents(100), Brl.from_cents(200)) == Brl.from_cents(200)


def test_str_em_formato_brasileiro():
    assert str(Brl.from_float(1234.5)) == "R$ 1.234,50"
    assert str(Brl.from_float(0.99)) == "R$ 0,99"


def test_keys_converte_para_brl_pela_taxa_da_steam():
    # 10 chaves a R$ 22,00 cada
    assert Keys(10).to_brl(Brl.from_float(22.00)) == Brl.from_float(220.00)


def test_keys_fracionaria():
    assert Keys(2.5).to_brl(Brl.from_float(20.00)) == Brl.from_float(50.00)
```

- [ ] **Step 7: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/domain/test_money.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.domain.money'`

- [ ] **Step 8: Implementar `tf2price/domain/money.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Brl:
    """Valor em reais, guardado em centavos inteiros.

    Float para dinheiro acumula erro e faz comparação de igualdade mentir.
    Todo o cálculo do spike decide compra ou não-compra por comparação de
    valores, então o tipo é inteiro por baixo e a conversão é explícita.
    """

    cents: int

    @classmethod
    def from_cents(cls, cents: int) -> "Brl":
        return cls(int(cents))

    @classmethod
    def from_float(cls, reais: float) -> "Brl":
        return cls(round(reais * 100))

    @property
    def as_float(self) -> float:
        return self.cents / 100

    def __add__(self, other: "Brl") -> "Brl":
        return Brl(self.cents + other.cents)

    def __sub__(self, other: "Brl") -> "Brl":
        return Brl(self.cents - other.cents)

    def __mul__(self, factor: float) -> "Brl":
        return Brl(round(self.cents * factor))

    def __str__(self) -> str:
        # Python formata no padrão en-US; trocamos os separadores via
        # marcador temporário para não embaralhar ponto com vírgula.
        formatted = f"{self.as_float:,.2f}"
        formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        return f"R$ {formatted}"


@dataclass(frozen=True, order=True)
class Keys:
    """Valor em chaves de TF2. Pode ser fracionário."""

    amount: float

    def to_brl(self, key_brl: Brl) -> Brl:
        """Converte para reais pela taxa da chave na própria Steam Market.

        Usar a chave da Steam (e não a cotação em dólar da bp.tf) é o que
        cancela o prêmio de saldo travado dos dois lados da comparação.
        """
        return key_brl * self.amount
```

- [ ] **Step 9: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/domain/test_money.py -v
```

Esperado: 8 passed

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml .env.example .gitignore tf2price tests
git commit -m "$(cat <<'MSG'
Adiciona scaffolding do projeto e o tipo monetário Brl

Dinheiro em centavos inteiros: o spike decide compra por comparação
de valores, e float faria a comparação mentir.

Keys.to_brl converte pela taxa da chave na própria Steam, que é o
que cancela o prêmio de saldo travado dos dois lados.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 2: `domain/identity.py` — parse de `market_hash_name`

**Files:**
- Create: `tf2price/domain/identity.py`
- Test: `tests/domain/test_identity.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces:
  - `ItemIdentity` — frozen dataclass com `base_name: str`, `quality_id: int`, `killstreak: int` (0 nenhum, 1 Killstreak, 2 Specialized, 3 Professional), `australium: bool`, `festivized: bool`, `wear: str | None`.
  - `parse_market_hash_name(name: str) -> ItemIdentity`
  - `bptf_name_candidates(identity: ItemIdentity, original: str) -> list[str]`
  - Constante `QUALITY_UNIQUE = 6`.

**Contexto para quem implementa:** os ids de qualidade vêm do schema do TF2 e não são sequenciais: 1 Genuine, 3 Vintage, 5 Unusual, 6 Unique, 11 Strange, 13 Haunted, 14 Collector's. Unique (6) **não tem prefixo** no nome — é o default quando nenhum prefixo casa.

A ordem dos prefixos no nome variou ao longo de 15 anos de TF2. Por isso o parser consome gulosamente pela frente num laço até nenhum prefixo casar mais, em vez de assumir uma ordem fixa.

Há uma armadilha: alguns itens **começam com uma palavra de qualidade sem serem daquela qualidade**. `Strange Part: Kills` é um item Unique cujo nome literalmente começa com "Strange". Por isso existe a lista de exceções.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/domain/test_identity.py`:

```python
from __future__ import annotations

import pytest

from tf2price.domain.identity import (
    QUALITY_UNIQUE,
    ItemIdentity,
    bptf_name_candidates,
    parse_market_hash_name,
)

# (market_hash_name, base_name, quality_id, killstreak, australium, festivized, wear)
CASOS = [
    # --- sem nenhum modificador ---
    ("Mann Co. Supply Crate Key", "Mann Co. Supply Crate Key", 6, 0, False, False, None),
    ("Refined Metal", "Refined Metal", 6, 0, False, False, None),
    ("Taunt: The Killer Solo", "Taunt: The Killer Solo", 6, 0, False, False, None),
    # --- qualidades ---
    ("Strange Scattergun", "Scattergun", 11, 0, False, False, None),
    ("Genuine Dead Cone", "Dead Cone", 1, 0, False, False, None),
    ("Vintage Tyrolean", "Tyrolean", 3, 0, False, False, None),
    ("Unusual Team Captain", "Team Captain", 5, 0, False, False, None),
    ("Haunted Executioner", "Executioner", 13, 0, False, False, None),
    ("Collector's Rocket Launcher", "Rocket Launcher", 14, 0, False, False, None),
    # --- killstreak, do mais longo para o mais curto ---
    ("Killstreak Scattergun", "Scattergun", 6, 1, False, False, None),
    ("Specialized Killstreak Scattergun", "Scattergun", 6, 2, False, False, None),
    ("Professional Killstreak Scattergun", "Scattergun", 6, 3, False, False, None),
    ("Strange Professional Killstreak Scattergun", "Scattergun", 11, 3, False, False, None),
    ("Specialized Killstreak Kit Fabricator", "Kit Fabricator", 6, 2, False, False, None),
    # --- australium e festivized ---
    ("Australium Rocket Launcher", "Rocket Launcher", 6, 0, True, False, None),
    ("Strange Australium Rocket Launcher", "Rocket Launcher", 11, 0, True, False, None),
    ("Professional Killstreak Australium Rocket Launcher", "Rocket Launcher", 6, 3, True, False, None),
    ("Festivized Rocket Launcher", "Rocket Launcher", 6, 0, False, True, None),
    (
        "Strange Festivized Professional Killstreak Australium Rocket Launcher",
        "Rocket Launcher",
        11,
        3,
        True,
        True,
        None,
    ),
    # --- war paints: desgaste no fim, entre parênteses ---
    (
        "Civic Duty Mk.II War Paint (Field-Tested)",
        "Civic Duty Mk.II War Paint",
        6,
        0,
        False,
        False,
        "Field-Tested",
    ),
    (
        "Strange Civic Duty Mk.II War Paint (Battle Scarred)",
        "Civic Duty Mk.II War Paint",
        11,
        0,
        False,
        False,
        "Battle Scarred",
    ),
    (
        "Bomber Soul War Paint (Factory New)",
        "Bomber Soul War Paint",
        6,
        0,
        False,
        False,
        "Factory New",
    ),
    # --- a armadilha: nome começa com palavra de qualidade sem ser daquela qualidade ---
    ("Strange Part: Kills", "Strange Part: Kills", 6, 0, False, False, None),
    ("Strange Filter: Mann Manor", "Strange Filter: Mann Manor", 6, 0, False, False, None),
    ("Haunted Metal Scrap", "Haunted Metal Scrap", 6, 0, False, False, None),
    ("Strange Bacon Grease", "Strange Bacon Grease", 6, 0, False, False, None),
]


@pytest.mark.parametrize(
    "hash_name,base,quality,killstreak,australium,festivized,wear", CASOS
)
def test_parse_market_hash_name(
    hash_name, base, quality, killstreak, australium, festivized, wear
):
    assert parse_market_hash_name(hash_name) == ItemIdentity(
        base_name=base,
        quality_id=quality,
        killstreak=killstreak,
        australium=australium,
        festivized=festivized,
        wear=wear,
    )


def test_quality_unique_e_o_default():
    assert parse_market_hash_name("Scattergun").quality_id == QUALITY_UNIQUE


def test_espacos_nas_bordas_sao_ignorados():
    assert parse_market_hash_name("  Strange Scattergun  ").base_name == "Scattergun"


def test_candidatos_tentam_o_nome_original_primeiro():
    original = "Specialized Killstreak Kit Fabricator"
    identity = parse_market_hash_name(original)
    assert bptf_name_candidates(identity, original)[0] == original


def test_candidatos_incluem_variante_australium_antes_da_base():
    original = "Strange Australium Rocket Launcher"
    identity = parse_market_hash_name(original)
    candidatos = bptf_name_candidates(identity, original)
    assert candidatos.index("Australium Rocket Launcher") < candidatos.index(
        "Rocket Launcher"
    )


def test_candidatos_sem_repeticao():
    original = "Scattergun"
    identity = parse_market_hash_name(original)
    candidatos = bptf_name_candidates(identity, original)
    assert len(candidatos) == len(set(candidatos))
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/domain/test_identity.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.domain.identity'`

- [ ] **Step 3: Implementar `tf2price/domain/identity.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass

QUALITY_UNIQUE = 6

# Ids do schema do TF2. Não são sequenciais e não devem ser "arrumados".
QUALITY_PREFIXES: dict[str, int] = {
    "Genuine": 1,
    "Vintage": 3,
    "Unusual": 5,
    "Strange": 11,
    "Haunted": 13,
    "Collector's": 14,
}

# Itens Unique cujo nome começa com uma palavra de qualidade. Sem esta lista,
# "Strange Part: Kills" viraria um "Part: Kills" de qualidade Strange, que não
# existe, e o item sumiria da análise sem aviso.
QUALITY_PREFIX_EXCEPTIONS: tuple[str, ...] = (
    "Strange Part:",
    "Strange Filter:",
    "Strange Count Transfer Tool",
    "Strange Bacon Grease",
    "Haunted Metal Scrap",
)

# Ordem importa: o mais longo tem que ser testado primeiro, senão
# "Professional Killstreak X" casaria como "Killstreak" deixando lixo atrás.
KILLSTREAK_PREFIXES: dict[str, int] = {
    "Professional Killstreak": 3,
    "Specialized Killstreak": 2,
    "Killstreak": 1,
}

WEARS: tuple[str, ...] = (
    "Factory New",
    "Minimal Wear",
    "Field-Tested",
    "Well-Worn",
    "Battle Scarred",
)

_WEAR_RE = re.compile(r"\s*\((" + "|".join(re.escape(w) for w in WEARS) + r")\)$")


@dataclass(frozen=True)
class ItemIdentity:
    """O que dá para saber de um item olhando só o nome.

    Tudo que NÃO está aqui — efeito de Unusual, craftabilidade, spells,
    sheen — é incógnita da passada rasa, e é o que a poda das três vias
    precisa tratar.
    """

    base_name: str
    quality_id: int
    killstreak: int
    australium: bool
    festivized: bool
    wear: str | None


def parse_market_hash_name(name: str) -> ItemIdentity:
    rest = name.strip()

    wear: str | None = None
    match = _WEAR_RE.search(rest)
    if match:
        wear = match.group(1)
        rest = rest[: match.start()].strip()

    quality_id = QUALITY_UNIQUE
    killstreak = 0
    australium = False
    festivized = False

    # A ordem dos prefixos variou ao longo de 15 anos de TF2. Em vez de
    # assumir uma sequência, consumimos gulosamente pela frente até nada
    # mais casar.
    changed = True
    while changed:
        changed = False

        for prefix, tier in KILLSTREAK_PREFIXES.items():
            if killstreak == 0 and rest.startswith(prefix + " "):
                killstreak = tier
                rest = rest[len(prefix) + 1 :]
                changed = True
                break
        if changed:
            continue

        if quality_id == QUALITY_UNIQUE and not rest.startswith(QUALITY_PREFIX_EXCEPTIONS):
            for prefix, qid in QUALITY_PREFIXES.items():
                if rest.startswith(prefix + " "):
                    quality_id = qid
                    rest = rest[len(prefix) + 1 :]
                    changed = True
                    break
        if changed:
            continue

        if not festivized and rest.startswith("Festivized "):
            festivized = True
            rest = rest[len("Festivized ") :]
            changed = True
            continue

        if not australium and rest.startswith("Australium "):
            australium = True
            rest = rest[len("Australium ") :]
            changed = True
            continue

    return ItemIdentity(
        base_name=rest,
        quality_id=quality_id,
        killstreak=killstreak,
        australium=australium,
        festivized=festivized,
        wear=wear,
    )


def bptf_name_candidates(identity: ItemIdentity, original: str) -> list[str]:
    """Nomes a tentar no índice da bp.tf, do mais específico ao mais genérico.

    A bp.tf mudou de convenção de nomenclatura várias vezes. Em vez de
    adivinhar qual vale hoje, tentamos em ordem e registramos qual funcionou.
    A distribuição das estratégias vencedoras é um resultado do spike.
    """
    candidates: list[str] = []

    def add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    add(original.strip())
    if identity.australium:
        add(f"Australium {identity.base_name}")
    add(identity.base_name)

    return candidates
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/domain/test_identity.py -v
```

Esperado: 31 passed (26 casos parametrizados + 5 testes avulsos)

- [ ] **Step 5: Commit**

```bash
git add tf2price/domain/identity.py tests/domain/test_identity.py
git commit -m "$(cat <<'MSG'
Adiciona parse de market_hash_name para identidade de item

Consome prefixos gulosamente em laço em vez de assumir ordem fixa,
porque a ordem variou ao longo de 15 anos de TF2.

Inclui lista de exceções para itens Unique cujo nome começa com
palavra de qualidade, como "Strange Part: Kills" — sem ela o item
some da análise sem aviso.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 3: `domain/prefilter.py` — a poda das três vias

Este é o coração do spike e o único lugar onde um bug é silencioso. Todo o resto falha fazendo barulho; uma poda agressiva demais faria você perder dinheiro sem nada aparecer na tela. Por isso o teste principal aqui é de propriedade, não de exemplo.

**Files:**
- Create: `tf2price/domain/prefilter.py`
- Test: `tests/domain/test_prefilter.py`

**Interfaces:**
- Consumes: `tf2price.domain.money.Brl` (Task 1).
- Produces:
  - `Classification(str, Enum)` com membros `GUARANTEED = "garantida"`, `CANDIDATE = "candidata"`, `DISCARDED = "descartada"`.
  - `ValueRange` — frozen dataclass com `min_keys: float`, `max_keys: float`; levanta `ValueError` se `min_keys > max_keys`.
  - `classify(steam_lowest: Brl, value_range: ValueRange, key_brl: Brl, threshold: float) -> Classification`.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/domain/test_prefilter.py`:

```python
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification, ValueRange, classify

CHAVE = Brl.from_float(22.00)


def test_faixa_invertida_e_erro():
    with pytest.raises(ValueError):
        ValueRange(min_keys=10.0, max_keys=5.0)


def test_garantida_quando_barato_ate_no_pior_cenario():
    # faixa 10 a 30 chaves. Piso = 10 * 22 = R$ 220. Com limiar 15%: R$ 187.
    resultado = classify(Brl.from_float(150.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.GUARANTEED


def test_candidata_quando_so_vale_no_melhor_cenario():
    # R$ 400 está acima do piso (R$ 187) mas abaixo do teto (30 * 22 * 0.85 = R$ 561)
    resultado = classify(Brl.from_float(400.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.CANDIDATE


def test_descartada_quando_nem_o_melhor_cenario_justifica():
    resultado = classify(Brl.from_float(900.00), ValueRange(10.0, 30.0), CHAVE, 0.15)
    assert resultado is Classification.DISCARDED


def test_faixa_de_um_ponto_so_nunca_e_candidata():
    # Item de nome limpo: piso e teto coincidem, então ou é garantida ou é descartada.
    estreita = ValueRange(10.0, 10.0)
    assert classify(Brl.from_float(150.00), estreita, CHAVE, 0.15) is Classification.GUARANTEED
    assert classify(Brl.from_float(300.00), estreita, CHAVE, 0.15) is Classification.DISCARDED


def test_limiar_zero_ainda_classifica():
    assert classify(Brl.from_float(219.00), ValueRange(10.0, 10.0), CHAVE, 0.0) is (
        Classification.GUARANTEED
    )


@given(
    min_keys=st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False),
    span=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
    frac=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    price_cents=st.integers(min_value=1, max_value=500_000),
    key_cents=st.integers(min_value=100, max_value=10_000),
    threshold=st.floats(min_value=0.0, max_value=0.9, allow_nan=False, allow_infinity=False),
)
def test_a_poda_nunca_descarta_uma_pechincha(
    min_keys, span, frac, price_cents, key_cents, threshold
):
    """Propriedade central do sistema.

    Para qualquer valor real dentro da faixa de incerteza: se a listagem
    é pechincha naquele valor, ela NUNCA pode ser classificada como
    descartada. Um falso negativo aqui é invisível — o item simplesmente
    nunca aparece, e você nunca fica sabendo que existiu.
    """
    faixa = ValueRange(min_keys=min_keys, max_keys=min_keys + span)
    valor_real_keys = min_keys + span * frac

    chave = Brl.from_cents(key_cents)
    preco = Brl.from_cents(price_cents)

    e_pechincha = preco < chave * (valor_real_keys * (1 - threshold))
    resultado = classify(preco, faixa, chave, threshold)

    if e_pechincha:
        assert resultado is not Classification.DISCARDED
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/domain/test_prefilter.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.domain.prefilter'`

- [ ] **Step 3: Implementar `tf2price/domain/prefilter.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tf2price.domain.money import Brl


class Classification(str, Enum):
    """Resultado da poda para um market_hash_name."""

    GUARANTEED = "garantida"
    CANDIDATE = "candidata"
    DISCARDED = "descartada"


@dataclass(frozen=True)
class ValueRange:
    """Faixa de valor justo em chaves, sobre todas as interpretações possíveis
    do nome — cada efeito de Unusual × craftável e não-craftável."""

    min_keys: float
    max_keys: float

    def __post_init__(self) -> None:
        if self.min_keys > self.max_keys:
            raise ValueError(
                f"faixa invertida: min_keys={self.min_keys} > max_keys={self.max_keys}"
            )


def classify(
    steam_lowest: Brl,
    value_range: ValueRange,
    key_brl: Brl,
    threshold: float,
) -> Classification:
    """Classifica um nome avaliando o cenário mais e o menos favorável.

    - Abaixo do piso: vale mesmo no PIOR cenário (não-craftável, pior efeito).
      Entra no líquido sem precisar de fetch profundo.
    - Abaixo do teto: só vale em ALGUM cenário. Precisa de fetch profundo
      para resolver as incógnitas.
    - Acima do teto: nenhuma listagem deste nome pode ser negócio. Descarta o
      nome inteiro, que é o que torna a varredura barata.
    """
    floor = key_brl * (value_range.min_keys * (1 - threshold))
    ceiling = key_brl * (value_range.max_keys * (1 - threshold))

    if steam_lowest < floor:
        return Classification.GUARANTEED
    if steam_lowest < ceiling:
        return Classification.CANDIDATE
    return Classification.DISCARDED
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/domain/test_prefilter.py -v
```

Esperado: 7 passed. O teste de propriedade roda 100 exemplos gerados por padrão.

- [ ] **Step 5: Commit**

```bash
git add tf2price/domain/prefilter.py tests/domain/test_prefilter.py
git commit -m "$(cat <<'MSG'
Adiciona a poda das três vias com teste de propriedade

Classifica cada nome avaliando o cenário mais e o menos favorável
dentro das incógnitas do market_hash_name.

O teste de propriedade cobre o único bug silencioso possível do
sistema: uma poda agressiva demais faria perder dinheiro sem nada
aparecer na tela.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 4: `domain/valuation.py` — valor justo, desconto e as quatro guardas

**Files:**
- Create: `tf2price/domain/valuation.py`
- Test: `tests/domain/test_valuation.py`

**Interfaces:**
- Consumes: `tf2price.domain.money.Brl` (Task 1), `tf2price.domain.prefilter.Classification` (Task 3).
- Produces:
  - Constantes `STEAM_SELLER_FEE = 0.15`, `STALE_AFTER_DAYS = 30`, `MAX_RANGE_RATIO = 1.25`.
  - `BptfPrice` — frozen dataclass com `value: float`, `value_high: float | None`, `currency: str`, `last_update: int` (unix timestamp).
  - `Valuation` — frozen dataclass com `fair_value: Brl`, `discount: float`, `resale_profit: Brl`.
  - `evaluate(steam_total: Brl, fair_keys: float, key_brl: Brl) -> Valuation`.
  - `Guard(str, Enum)` com `OK`, `STALE_PRICE`, `WIDE_RANGE`, `MARKET_DERIVED`, `UNRESOLVED`.
  - `check_guards(price: BptfPrice, classification: Classification, deep_fetched: bool, now: int | None = None) -> Guard`.

**Contexto para quem implementa:** a ordem das guardas importa e é deliberada. `MARKET_DERIVED` vem primeiro porque um preço derivado da Steam torna a comparação circular — não adianta checar mais nada. `UNRESOLVED` vem por último porque só se aplica a candidatas sem fetch profundo; uma **garantida nunca é reprovada por ela**, já que a poda provou que o item vale mesmo no pior cenário. Esse ponto é a correção mais importante do spec — errar aqui zera exatamente a fatia que o spike precisa medir.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/domain/test_valuation.py`:

```python
from __future__ import annotations

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import (
    BptfPrice,
    Guard,
    check_guards,
    evaluate,
)

AGORA = 1_760_000_000
CHAVE = Brl.from_float(22.00)


def _preco(
    value: float = 10.0,
    value_high: float | None = 11.0,
    currency: str = "keys",
    last_update: int = AGORA - 3600,
) -> BptfPrice:
    return BptfPrice(
        value=value, value_high=value_high, currency=currency, last_update=last_update
    )


def test_valor_justo_usa_a_taxa_da_chave():
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.fair_value == Brl.from_float(220.00)


def test_desconto_e_fracao_sobre_o_valor_justo():
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.discount == pytest.approx(1 - 180 / 220)


def test_lucro_de_revenda_desconta_a_taxa_da_steam():
    # R$ 220 de valor justo, menos 15% de taxa do vendedor, menos R$ 180 pagos
    resultado = evaluate(Brl.from_float(180.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.resale_profit == Brl.from_float(7.00)


def test_desconto_negativo_quando_o_item_esta_caro():
    resultado = evaluate(Brl.from_float(300.00), fair_keys=10.0, key_brl=CHAVE)
    assert resultado.discount < 0


def test_valor_justo_zero_e_erro():
    with pytest.raises(ValueError):
        evaluate(Brl.from_float(10.00), fair_keys=0.0, key_brl=CHAVE)


def test_guarda_derivado_da_steam_tem_precedencia():
    # mesmo desatualizado e com faixa larga, o motivo reportado é o circular
    preco = _preco(currency="usd", value=1.0, value_high=99.0, last_update=0)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.MARKET_DERIVED
    )


def test_guarda_preco_desatualizado():
    preco = _preco(last_update=AGORA - 31 * 86400)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.STALE_PRICE
    )


def test_preco_de_29_dias_passa():
    preco = _preco(last_update=AGORA - 29 * 86400)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_guarda_faixa_larga():
    preco = _preco(value=10.0, value_high=13.0)  # 1.3x, acima do teto de 1.25x
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is (
        Guard.WIDE_RANGE
    )


def test_faixa_no_limite_passa():
    preco = _preco(value=10.0, value_high=12.5)  # exatamente 1.25x
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_faixa_ausente_passa():
    preco = _preco(value_high=None)
    assert check_guards(preco, Classification.GUARANTEED, False, now=AGORA) is Guard.OK


def test_candidata_sem_fetch_profundo_e_reprovada():
    assert check_guards(_preco(), Classification.CANDIDATE, False, now=AGORA) is (
        Guard.UNRESOLVED
    )


def test_candidata_com_fetch_profundo_passa():
    assert check_guards(_preco(), Classification.CANDIDATE, True, now=AGORA) is Guard.OK


def test_garantida_sem_fetch_profundo_passa():
    """Regressão da correção central do spec.

    A poda já provou que uma garantida vale mesmo no pior cenário — não
    craftável e com o pior efeito. Aplicar a guarda de incógnitas a ela
    zeraria os itens não-Unusual, que são justamente o que a passada rasa
    resolve sozinha.
    """
    assert check_guards(_preco(), Classification.GUARANTEED, False, now=AGORA) is Guard.OK
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/domain/test_valuation.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.domain.valuation'`

- [ ] **Step 3: Implementar `tf2price/domain/valuation.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification

STEAM_SELLER_FEE = 0.15
STALE_AFTER_DAYS = 30
MAX_RANGE_RATIO = 1.25


@dataclass(frozen=True)
class BptfPrice:
    """Uma entrada de preço do índice da backpack.tf.

    `value` é o piso da faixa sugerida e é o único que usamos no cálculo.
    `value_high` entra apenas na guarda de faixa larga.
    """

    value: float
    value_high: float | None
    currency: str
    last_update: int


@dataclass(frozen=True)
class Valuation:
    fair_value: Brl
    discount: float
    resale_profit: Brl


def evaluate(steam_total: Brl, fair_keys: float, key_brl: Brl) -> Valuation:
    """Avalia uma listagem contra o valor justo em chaves.

    `steam_total` é o que o COMPRADOR paga (preço + taxa), nunca o líquido
    do vendedor. A taxa de 15% sai do vendedor, então ela aparece só em
    `resale_profit` e jamais no desconto.
    """
    fair = key_brl * fair_keys
    if fair.cents <= 0:
        raise ValueError(f"valor justo inválido: {fair_keys} chaves a {key_brl}")

    discount = 1 - (steam_total.cents / fair.cents)
    resale_profit = fair * (1 - STEAM_SELLER_FEE) - steam_total
    return Valuation(fair_value=fair, discount=discount, resale_profit=resale_profit)


class Guard(str, Enum):
    OK = "ok"
    MARKET_DERIVED = "derivado_da_steam"
    STALE_PRICE = "preco_desatualizado"
    WIDE_RANGE = "faixa_larga"
    UNRESOLVED = "incognitas_nao_resolvidas"


def check_guards(
    price: BptfPrice,
    classification: Classification,
    deep_fetched: bool,
    now: int | None = None,
) -> Guard:
    """Devolve o primeiro motivo de reprovação, ou OK.

    A ordem é deliberada: um preço derivado da Steam torna toda a comparação
    circular, então não adianta checar mais nada depois dele.
    """
    now = int(time.time()) if now is None else now

    # Guarda 4: preço em USD é o sinal candidato de origem Steam Market.
    # Hipótese a confirmar no Task 11.
    if price.currency == "usd":
        return Guard.MARKET_DERIVED

    if now - price.last_update > STALE_AFTER_DAYS * 86400:
        return Guard.STALE_PRICE

    if price.value_high is not None and price.value_high > price.value * MAX_RANGE_RATIO:
        return Guard.WIDE_RANGE

    # Guarda 1: só se aplica a candidatas. Uma garantida já foi provada no
    # pior cenário pela poda e não precisa de fetch profundo.
    if classification is Classification.CANDIDATE and not deep_fetched:
        return Guard.UNRESOLVED

    return Guard.OK
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/domain/test_valuation.py -v
```

Esperado: 14 passed

- [ ] **Step 5: Rodar a suíte inteira do domínio**

```bash
.venv/Scripts/python -m pytest tests/domain -v
```

Esperado: todos passando. `domain/` está completo exceto `effects.py` (Task 8).

- [ ] **Step 6: Commit**

```bash
git add tf2price/domain/valuation.py tests/domain/test_valuation.py
git commit -m "$(cat <<'MSG'
Adiciona valor justo, desconto e as quatro guardas

A taxa de 15% sai do vendedor, então aparece só no lucro de revenda
e nunca no cálculo de desconto.

A guarda de incógnitas só se aplica a candidatas: uma garantida já
foi provada no pior cenário pela poda, e reprová-la zeraria os itens
não-Unusual que a passada rasa resolve sozinha.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 5: `sources/ratelimit.py` — espaçamento e backoff

**Files:**
- Create: `tf2price/sources/ratelimit.py`
- Test: `tests/sources/test_ratelimit.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `RateLimiter` — dataclass mutável com `min_interval_s: float`, contadores públicos `requests: int`, `throttled: int`, `first_429_after: int | None`; métodos `wait() -> None` e `record_throttle() -> None`.
  - `backoff_delays(attempts: int, base: float = 2.0, cap: float = 120.0) -> list[float]`.

**Contexto:** os contadores não são telemetria decorativa. A **verificação #3 do spec** — requisições por minuto até o primeiro 429 — sai daqui e entra no relatório final. `backoff_delays` é função pura para ser testável sem dormir de verdade.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/sources/test_ratelimit.py`:

```python
from __future__ import annotations

from tf2price.sources.ratelimit import RateLimiter, backoff_delays


def test_contador_de_requisicoes():
    limiter = RateLimiter(min_interval_s=0.0)
    for _ in range(3):
        limiter.wait()
    assert limiter.requests == 3


def test_primeiro_429_registra_em_que_requisicao_aconteceu():
    limiter = RateLimiter(min_interval_s=0.0)
    limiter.wait()
    limiter.wait()
    limiter.record_throttle()
    limiter.wait()
    limiter.record_throttle()

    assert limiter.first_429_after == 2
    assert limiter.throttled == 2


def test_sem_429_o_marcador_fica_nulo():
    limiter = RateLimiter(min_interval_s=0.0)
    limiter.wait()
    assert limiter.first_429_after is None


def test_espacamento_respeita_o_intervalo_minimo():
    import time

    limiter = RateLimiter(min_interval_s=0.05)
    inicio = time.monotonic()
    limiter.wait()
    limiter.wait()
    assert time.monotonic() - inicio >= 0.05


def test_backoff_cresce_e_respeita_o_teto():
    delays = backoff_delays(attempts=8, base=2.0, cap=30.0)
    assert len(delays) == 8
    assert all(d > 0 for d in delays)
    assert max(delays) <= 30.0


def test_backoff_tem_jitter_mas_fica_na_metade_de_cima():
    # jitter entre 50% e 100% do valor bruto: nunca colapsa para quase zero
    delays = backoff_delays(attempts=1, base=2.0, cap=100.0)
    assert 1.0 <= delays[0] <= 2.0
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/sources/test_ratelimit.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.sources.ratelimit'`

- [ ] **Step 3: Implementar `tf2price/sources/ratelimit.py`**

```python
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Espaça requisições e registra o que aconteceu.

    Os contadores alimentam a verificação #3 do spec: quantas requisições
    o IP aguenta por minuto antes do primeiro 429. Esse número dimensiona
    o ciclo do projeto completo.
    """

    min_interval_s: float
    requests: int = 0
    throttled: int = 0
    first_429_after: int | None = None
    _last_call: float = field(default=0.0, repr=False)

    def wait(self) -> None:
        remaining = self.min_interval_s - (time.monotonic() - self._last_call)
        if remaining > 0:
            time.sleep(remaining)
        self._last_call = time.monotonic()
        self.requests += 1

    def record_throttle(self) -> None:
        self.throttled += 1
        if self.first_429_after is None:
            self.first_429_after = self.requests


def backoff_delays(attempts: int, base: float = 2.0, cap: float = 120.0) -> list[float]:
    """Atrasos exponenciais com jitter, como função pura.

    Pura para ser testável sem dormir de verdade. O jitter fica entre 50% e
    100% do valor bruto: espalha as tentativas sem nunca colapsar o atraso
    para perto de zero, que é o que transformaria o backoff em martelada.
    """
    delays: list[float] = []
    for attempt in range(attempts):
        raw = min(cap, base * (2**attempt))
        delays.append(raw * (0.5 + random.random() * 0.5))
    return delays
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/sources/test_ratelimit.py -v
```

Esperado: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tf2price/sources/ratelimit.py tests/sources/test_ratelimit.py
git commit -m "$(cat <<'MSG'
Adiciona espaçamento de requisições e backoff com jitter

Os contadores alimentam a verificação #3 do spec: quantas requisições
o IP aguenta antes do primeiro 429, que é o que dimensiona o ciclo
do projeto completo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 6: `sources/steam.py` — parsers puros e cliente HTTP

**Files:**
- Create: `tests/fixtures/steam_search_page.json`
- Create: `tests/fixtures/steam_listings_unusual.json`
- Create: `tests/fixtures/steam_priceoverview.json`
- Create: `tf2price/sources/steam.py`
- Test: `tests/sources/test_steam.py`

**Interfaces:**
- Consumes: `tf2price.domain.money.Brl` (Task 1), `tf2price.sources.ratelimit.RateLimiter` e `backoff_delays` (Task 5).
- Produces:
  - Constantes `APPID = 440`, `CURRENCY_BRL = 7`, `KEY_HASH_NAME = "Mann Co. Supply Crate Key"`.
  - `SearchResult` — frozen dataclass com `hash_name: str`, `lowest_price: Brl`, `sell_listings: int`.
  - `SearchPage` — frozen dataclass com `total_count: int`, `results: list[SearchResult]`.
  - `Listing` — frozen dataclass com `listing_id: str`, `total_price: Brl`, `effect: str | None`, `craftable: bool`, `spelled: bool`.
  - `parse_price_text(text: str) -> Brl`
  - `parse_search_page(payload: dict) -> SearchPage`
  - `parse_listings(payload: dict) -> list[Listing]`
  - `SteamClient(limiter, client=None, sleep=time.sleep)` com métodos `search_page(start, count=100) -> SearchPage`, `listings(hash_name, count=100) -> list[Listing]`, `key_price() -> Brl`, `key_median_price() -> Brl`.

**Contexto para quem implementa:**

O parsing fica em funções puras separadas do cliente porque é onde moram os bugs e é o que precisa de teste. O cliente só faz I/O.

Três armadilhas reais da API da Steam:

1. **`l=english` é obrigatório.** Sem ele as descrições voltam traduzidas e `"( Not Usable in Crafting )"` nunca casa — o item passa como craftável e vira falso positivo silencioso.
2. **A estrutura de `assets` é aninhada por appid e contextid**, e o `asset.id` do `listinginfo` é a chave dentro dela. Não é um join direto.
3. **`converted_price + converted_fee`** é o que o comprador paga. `price` sozinho é o líquido do vendedor. Usar o campo errado infla todo desconto em ~15%.

- [ ] **Step 1: Criar `tests/fixtures/steam_search_page.json`**

```json
{
  "success": true,
  "start": 0,
  "pagesize": "100",
  "total_count": 21543,
  "results": [
    {
      "name": "Mann Co. Supply Crate Key",
      "hash_name": "Mann Co. Supply Crate Key",
      "sell_listings": 4821,
      "sell_price": 2214,
      "sell_price_text": "R$ 22,14"
    },
    {
      "name": "Unusual Team Captain",
      "hash_name": "Unusual Team Captain",
      "sell_listings": 7,
      "sell_price": 89000,
      "sell_price_text": "R$ 890,00"
    },
    {
      "name": "Strange Australium Rocket Launcher",
      "hash_name": "Strange Australium Rocket Launcher",
      "sell_listings": 31,
      "sell_price": 15990,
      "sell_price_text": "R$ 159,90"
    }
  ]
}
```

- [ ] **Step 2: Criar `tests/fixtures/steam_listings_unusual.json`**

```json
{
  "success": true,
  "start": 0,
  "pagesize": 100,
  "total_count": 3,
  "listinginfo": {
    "1111111111111111111": {
      "listingid": "1111111111111111111",
      "price": 80000,
      "fee": 9000,
      "converted_price": 80000,
      "converted_fee": 9000,
      "asset": { "currency": 0, "appid": 440, "contextid": "2", "id": "aaa1", "amount": "1" }
    },
    "2222222222222222222": {
      "listingid": "2222222222222222222",
      "price": 120000,
      "fee": 13500,
      "converted_price": 120000,
      "converted_fee": 13500,
      "asset": { "currency": 0, "appid": 440, "contextid": "2", "id": "aaa2", "amount": "1" }
    },
    "3333333333333333333": {
      "listingid": "3333333333333333333",
      "converted_price": 0,
      "converted_fee": 0,
      "asset": { "currency": 0, "appid": 440, "contextid": "2", "id": "aaa3", "amount": "1" }
    }
  },
  "assets": {
    "440": {
      "2": {
        "aaa1": {
          "appid": 440,
          "contextid": "2",
          "id": "aaa1",
          "market_hash_name": "Unusual Team Captain",
          "descriptions": [
            { "value": "Level 10 Hat" },
            { "value": "★ Unusual Effect: Burning Flames", "color": "ffd700" },
            { "value": " " }
          ]
        },
        "aaa2": {
          "appid": 440,
          "contextid": "2",
          "id": "aaa2",
          "market_hash_name": "Unusual Team Captain",
          "descriptions": [
            { "value": "Level 10 Hat" },
            { "value": "★ Unusual Effect: Green Confetti", "color": "ffd700" },
            { "value": "( Not Usable in Crafting )" },
            { "value": "Halloween: Exorcism (spell only active during event)" }
          ]
        },
        "aaa3": {
          "appid": 440,
          "contextid": "2",
          "id": "aaa3",
          "market_hash_name": "Unusual Team Captain",
          "descriptions": [{ "value": "Level 10 Hat" }]
        }
      }
    }
  }
}
```

- [ ] **Step 3: Criar `tests/fixtures/steam_priceoverview.json`**

```json
{
  "success": true,
  "lowest_price": "R$ 22,14",
  "volume": "6,482",
  "median_price": "R$ 22,49"
}
```

- [ ] **Step 4: Escrever o teste que falha**

Arquivo `tests/sources/test_steam.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import (
    SteamClient,
    parse_listings,
    parse_price_text,
    parse_search_page,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- parsers puros -------------------------------------------------------


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("R$ 22,14", 2214),
        ("R$ 1.234,50", 123450),
        ("R$ 0,99", 99),
        ("R$ 12.345.678,90", 1234567890),
    ],
)
def test_parse_price_text(texto, centavos):
    assert parse_price_text(texto) == Brl.from_cents(centavos)


def test_parse_search_page_le_total_e_resultados():
    page = parse_search_page(_fixture("steam_search_page.json"))
    assert page.total_count == 21543
    assert len(page.results) == 3


def test_parse_search_page_converte_sell_price_de_centavos():
    page = parse_search_page(_fixture("steam_search_page.json"))
    chave = page.results[0]
    assert chave.hash_name == "Mann Co. Supply Crate Key"
    assert chave.lowest_price == Brl.from_float(22.14)
    assert chave.sell_listings == 4821


def test_parse_search_page_sem_resultados():
    page = parse_search_page({"total_count": 0, "results": None})
    assert page.results == []


def test_parse_listings_ignora_listagem_sem_preco_convertido():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    assert len(listings) == 2


def test_parse_listings_soma_preco_e_taxa():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    primeira = next(l for l in listings if l.listing_id == "1111111111111111111")
    assert primeira.total_price == Brl.from_cents(89000)


def test_parse_listings_extrai_efeito_de_unusual():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    primeira = next(l for l in listings if l.listing_id == "1111111111111111111")
    assert primeira.effect == "Burning Flames"
    assert primeira.craftable is True
    assert primeira.spelled is False


def test_parse_listings_detecta_nao_craftavel_e_spell():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    segunda = next(l for l in listings if l.listing_id == "2222222222222222222")
    assert segunda.effect == "Green Confetti"
    assert segunda.craftable is False
    assert segunda.spelled is True
    assert segunda.total_price == Brl.from_cents(133500)


# --- cliente HTTP --------------------------------------------------------


def _cliente(payload: dict, capturadas: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capturadas is not None:
            capturadas.append(request)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_page_envia_currency_brl_e_idioma_ingles():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)

    params = capturadas[0].url.params
    assert params["currency"] == "7"
    assert params["l"] == "english"
    assert params["appid"] == "440"
    assert params["norender"] == "1"


def test_listings_escapa_o_nome_na_url():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_listings_unusual.json"), capturadas),
    )

    client.listings("Unusual Team Captain")

    assert "Unusual%20Team%20Captain" in str(capturadas[0].url)


def test_key_price_usa_a_listagem_mais_barata():
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_priceoverview.json")),
    )
    assert client.key_price() == Brl.from_float(22.14)


def test_key_median_price_le_a_mediana():
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_priceoverview.json")),
    )
    assert client.key_median_price() == Brl.from_float(22.49)


def test_429_e_repetido_com_backoff_e_registrado():
    respostas = [429, 429, 200]
    payload = _fixture("steam_search_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        status = respostas.pop(0)
        if status == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, json=payload)

    limiter = RateLimiter(min_interval_s=0.0)
    client = SteamClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,  # não dorme de verdade no teste
    )

    page = client.search_page(start=0)

    assert page.total_count == 21543
    assert limiter.throttled == 2
    assert limiter.first_429_after == 1


def test_erro_persistente_levanta():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="não respondeu"):
        client.search_page(start=0)
```

- [ ] **Step 5: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/sources/test_steam.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.sources.steam'`

- [ ] **Step 6: Implementar `tf2price/sources/steam.py`**

```python
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
    vírgula para decimal.
    """
    cleaned = _NON_NUMERIC.sub("", text)
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return Brl.from_float(float(cleaned))


def parse_search_page(payload: dict[str, Any]) -> SearchPage:
    results = [
        SearchResult(
            hash_name=row["hash_name"],
            lowest_price=Brl.from_cents(int(row["sell_price"])),
            sell_listings=int(row["sell_listings"]),
        )
        for row in (payload.get("results") or [])
    ]
    return SearchPage(total_count=int(payload.get("total_count", 0)), results=results)


def _descriptions_for(payload: dict[str, Any], asset_id: str) -> list[str]:
    """Busca as descrições de um asset dentro de assets[appid][contextid][id].

    O contextid varia, então varremos os contextos em vez de assumir "2".
    """
    contexts = (payload.get("assets") or {}).get(str(APPID)) or {}
    for context in contexts.values():
        asset = context.get(asset_id)
        if asset:
            return [str(d.get("value", "")) for d in (asset.get("descriptions") or [])]
    return []


def parse_listings(payload: dict[str, Any]) -> list[Listing]:
    listings: list[Listing] = []

    for listing_id, info in (payload.get("listinginfo") or {}).items():
        asset_id = str((info.get("asset") or {}).get("id", ""))

        effect: str | None = None
        craftable = True
        spelled = False

        for value in _descriptions_for(payload, asset_id):
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
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price-spike/0.1"},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_status: int | None = None

        for delay in [0.0, *backoff_delays(5)]:
            if delay:
                self._sleep(delay)
            self._limiter.wait()

            response = self._http.get(url, params=params)
            if response.status_code == 429:
                self._limiter.record_throttle()
                last_status = 429
                continue

            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Steam não respondeu após backoff (último status {last_status})")

    def search_page(self, start: int, count: int = 100) -> SearchPage:
        payload = self._get(
            f"{BASE}/market/search/render/",
            {
                "appid": APPID,
                "norender": 1,
                "count": count,
                "start": start,
                "currency": CURRENCY_BRL,
                "l": "english",
            },
        )
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
        return self._get(
            f"{BASE}/market/priceoverview/",
            {
                "appid": APPID,
                "currency": CURRENCY_BRL,
                "market_hash_name": KEY_HASH_NAME,
            },
        )

    def key_price(self) -> Brl:
        """Taxa de câmbio do spike: a listagem mais barata de chave.

        É o preço pelo qual você converteria reais em chaves de fato, então
        é a taxa honesta — ainda que mais volátil que a mediana.
        """
        return parse_price_text(self._priceoverview()["lowest_price"])

    def key_median_price(self) -> Brl:
        """Mediana de 24h, registrada no relatório como referência de sanidade."""
        return parse_price_text(self._priceoverview()["median_price"])
```

- [ ] **Step 7: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/sources/test_steam.py -v
```

Esperado: 17 passed

- [ ] **Step 8: Commit**

```bash
git add tf2price/sources/steam.py tests/sources/test_steam.py tests/fixtures
git commit -m "$(cat <<'MSG'
Adiciona cliente e parsers da Steam Market

Parsing separado do I/O porque é onde moram os bugs e é o que precisa
de teste contra fixtures.

Três armadilhas tratadas: l=english obrigatório para o texto de
craftabilidade casar, assets aninhado por appid e contextid, e
converted_price + converted_fee como preço do comprador.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 7: `sources/backpacktf.py` — índice de preços e moedas

**Files:**
- Create: `tests/fixtures/bptf_currencies.json`
- Create: `tests/fixtures/bptf_prices.json`
- Create: `tf2price/sources/backpacktf.py`
- Test: `tests/sources/test_backpacktf.py`

**Interfaces:**
- Consumes: `tf2price.domain.prefilter.ValueRange` (Task 3), `tf2price.domain.valuation.BptfPrice` (Task 4).
- Produces:
  - `Currencies` — frozen dataclass com `key_in_refined: float`, `key_in_usd: float`; construtor `Currencies.from_payload(payload: dict) -> Currencies`.
  - `PriceEntry` — frozen dataclass com `craftable: bool`, `priceindex: str | None`, `price: BptfPrice`.
  - `PriceIndex` — classe com construtor `PriceIndex.from_payload(payload: dict, key_in_refined: float) -> PriceIndex` e métodos:
    - `entries(item_name: str, quality_id: int) -> list[PriceEntry]`
    - `to_keys(price: BptfPrice) -> float | None`
    - `lookup(item_name: str, quality_id: int, craftable: bool = True, priceindex: str | None = None) -> BptfPrice | None`
    - `value_range_keys(item_name: str, quality_id: int) -> ValueRange | None`
    - `item_names() -> set[str]`
  - `BackpackTfClient(api_key, client=None)` com `currencies() -> Currencies` e `prices_payload() -> dict`.

**Contexto para quem implementa — a esquisitice central:**

O `IGetPrices/v4` aninha assim: `items[nome].prices[quality][tradable][craftable]`. E o último nível **muda de tipo**:

- Item sem variantes → **lista** com uma entrada. `"Craftable": [{...}]`
- Item com variantes (efeitos de Unusual, séries de caixa) → **dicionário** com o `priceindex` como chave. `"Craftable": {"13": {...}, "17": {...}}`

Mesmo campo, dois tipos. Tratar só um dos casos faz metade do catálogo sumir sem erro.

Moeda: `value` pode vir em `"keys"`, `"metal"` ou `"usd"`. Converter metal para chaves usa `key_in_refined` do `IGetCurrencies`. **`usd` não é convertido de propósito** — é o sinal candidato da guarda 4, e converter esconderia o que o spike precisa medir.

- [ ] **Step 1: Criar `tests/fixtures/bptf_currencies.json`**

```json
{
  "response": {
    "success": 1,
    "name": "Team Fortress 2",
    "url": "https://backpack.tf",
    "currencies": {
      "metal": {
        "name": "Refined Metal",
        "quality": 6,
        "priceindex": "0",
        "single": "ref",
        "plural": "ref",
        "defindex": 5002,
        "price": {
          "value": 0.05,
          "currency": "keys",
          "difference": 0,
          "last_update": 1759000000
        }
      },
      "keys": {
        "name": "Mann Co. Supply Crate Key",
        "quality": 6,
        "priceindex": "0",
        "single": "key",
        "plural": "keys",
        "defindex": 5021,
        "price": {
          "value": 69.44,
          "value_high": 69.55,
          "currency": "metal",
          "difference": 0.11,
          "last_update": 1759000000,
          "usd": 2.52
        }
      }
    }
  }
}
```

- [ ] **Step 2: Criar `tests/fixtures/bptf_prices.json`**

```json
{
  "response": {
    "success": 1,
    "current_time": 1760000000,
    "raw_usd_value": 0.0363,
    "usd_currency": "metal",
    "usd_currency_index": 5002,
    "items": {
      "Rocket Launcher": {
        "defindex": [205, 18],
        "prices": {
          "6": {
            "Tradable": {
              "Craftable": [
                { "currency": "metal", "value": 0.11, "last_update": 1759900000, "difference": 0 }
              ],
              "Non-Craftable": [
                { "currency": "metal", "value": 0.05, "last_update": 1759900000, "difference": 0 }
              ]
            }
          },
          "11": {
            "Tradable": {
              "Craftable": [
                {
                  "currency": "keys",
                  "value": 1.55,
                  "value_high": 1.66,
                  "last_update": 1759900000,
                  "difference": 0
                }
              ]
            }
          }
        }
      },
      "Team Captain": {
        "defindex": [378],
        "prices": {
          "5": {
            "Tradable": {
              "Craftable": {
                "13": {
                  "currency": "keys",
                  "value": 28.0,
                  "value_high": 30.0,
                  "last_update": 1759900000
                },
                "17": {
                  "currency": "keys",
                  "value": 9.0,
                  "value_high": 10.0,
                  "last_update": 1759900000
                },
                "701": {
                  "currency": "keys",
                  "value": 45.0,
                  "value_high": 50.0,
                  "last_update": 1759900000
                }
              }
            }
          },
          "6": {
            "Tradable": {
              "Craftable": [
                { "currency": "metal", "value": 1.0, "last_update": 1759900000 }
              ]
            }
          }
        }
      },
      "Mildly Disturbing Halloween Mask": {
        "defindex": [115],
        "prices": {
          "6": {
            "Tradable": {
              "Craftable": [
                { "currency": "usd", "value": 4.25, "last_update": 1759900000 }
              ]
            }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 3: Escrever o teste que falha**

Arquivo `tests/sources/test_backpacktf.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.sources.backpacktf import (
    BackpackTfClient,
    Currencies,
    PriceIndex,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
KEY_IN_REFINED = 69.44


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def index() -> PriceIndex:
    return PriceIndex.from_payload(_fixture("bptf_prices.json"), KEY_IN_REFINED)


# --- moedas --------------------------------------------------------------


def test_currencies_le_chave_em_refined_e_em_usd():
    currencies = Currencies.from_payload(_fixture("bptf_currencies.json"))
    assert currencies.key_in_refined == pytest.approx(69.44)
    assert currencies.key_in_usd == pytest.approx(2.52)


# --- a esquisitice lista vs dicionário -----------------------------------


def test_entries_le_o_formato_lista(index: PriceIndex):
    entries = index.entries("Rocket Launcher", 6)
    assert len(entries) == 2
    assert {e.craftable for e in entries} == {True, False}
    assert all(e.priceindex is None for e in entries)


def test_entries_le_o_formato_dicionario_com_priceindex(index: PriceIndex):
    entries = index.entries("Team Captain", 5)
    assert {e.priceindex for e in entries} == {"13", "17", "701"}
    assert all(e.craftable for e in entries)


def test_entries_de_item_inexistente_e_vazio(index: PriceIndex):
    assert index.entries("Item Que Não Existe", 6) == []


def test_entries_de_qualidade_inexistente_e_vazio(index: PriceIndex):
    assert index.entries("Team Captain", 11) == []


# --- conversão para chaves -----------------------------------------------


def test_to_keys_mantem_valor_ja_em_chaves(index: PriceIndex):
    price = index.lookup("Team Captain", 5, priceindex="13")
    assert index.to_keys(price) == pytest.approx(28.0)


def test_to_keys_converte_metal_pela_taxa(index: PriceIndex):
    price = index.lookup("Rocket Launcher", 6)
    assert index.to_keys(price) == pytest.approx(0.11 / KEY_IN_REFINED)


def test_to_keys_recusa_usd(index: PriceIndex):
    """USD não é convertido de propósito: é o sinal candidato da guarda 4."""
    price = index.lookup("Mildly Disturbing Halloween Mask", 6)
    assert price.currency == "usd"
    assert index.to_keys(price) is None


# --- lookup --------------------------------------------------------------


def test_lookup_por_priceindex(index: PriceIndex):
    assert index.lookup("Team Captain", 5, priceindex="701").value == pytest.approx(45.0)


def test_lookup_respeita_craftabilidade(index: PriceIndex):
    craftable = index.lookup("Rocket Launcher", 6, craftable=True)
    non_craftable = index.lookup("Rocket Launcher", 6, craftable=False)
    assert craftable.value == pytest.approx(0.11)
    assert non_craftable.value == pytest.approx(0.05)


def test_lookup_ausente_devolve_none(index: PriceIndex):
    assert index.lookup("Team Captain", 5, priceindex="9999") is None


# --- faixa de valor ------------------------------------------------------


def test_value_range_cobre_todos_os_efeitos(index: PriceIndex):
    faixa = index.value_range_keys("Team Captain", 5)
    assert faixa.min_keys == pytest.approx(9.0)
    assert faixa.max_keys == pytest.approx(45.0)


def test_value_range_cobre_craftavel_e_nao_craftavel(index: PriceIndex):
    faixa = index.value_range_keys("Rocket Launcher", 6)
    assert faixa.min_keys == pytest.approx(0.05 / KEY_IN_REFINED)
    assert faixa.max_keys == pytest.approx(0.11 / KEY_IN_REFINED)


def test_value_range_de_item_so_em_usd_e_none(index: PriceIndex):
    assert index.value_range_keys("Mildly Disturbing Halloween Mask", 6) is None


def test_value_range_de_item_inexistente_e_none(index: PriceIndex):
    assert index.value_range_keys("Item Que Não Existe", 6) is None


def test_item_names(index: PriceIndex):
    assert "Team Captain" in index.item_names()
    assert len(index.item_names()) == 3


# --- cliente HTTP --------------------------------------------------------


def test_cliente_envia_a_api_key_e_o_appid():
    capturadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(200, json=_fixture("bptf_prices.json"))

    client = BackpackTfClient(
        api_key="CHAVE_DE_TESTE",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.prices_payload()

    params = capturadas[0].url.params
    assert params["key"] == "CHAVE_DE_TESTE"
    assert params["appid"] == "440"


def test_cliente_devolve_currencies_tipado():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fixture("bptf_currencies.json"))

    client = BackpackTfClient(
        api_key="CHAVE_DE_TESTE",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.currencies().key_in_refined == pytest.approx(69.44)
```

- [ ] **Step 4: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/sources/test_backpacktf.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.sources.backpacktf'`

- [ ] **Step 5: Implementar `tf2price/sources/backpacktf.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from tf2price.domain.prefilter import ValueRange
from tf2price.domain.valuation import BptfPrice

BASE = "https://backpack.tf/api"
APPID = 440


@dataclass(frozen=True)
class Currencies:
    key_in_refined: float
    key_in_usd: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Currencies":
        price = payload["response"]["currencies"]["keys"]["price"]
        return cls(
            key_in_refined=float(price["value"]),
            key_in_usd=float(price.get("usd", 0.0)),
        )


@dataclass(frozen=True)
class PriceEntry:
    craftable: bool
    priceindex: str | None
    price: BptfPrice


def _to_price(entry: dict[str, Any]) -> BptfPrice:
    raw_high = entry.get("value_high")
    return BptfPrice(
        value=float(entry.get("value", 0.0)),
        value_high=float(raw_high) if raw_high is not None else None,
        currency=str(entry.get("currency", "")),
        last_update=int(entry.get("last_update", 0)),
    )


class PriceIndex:
    """O índice de preços da backpack.tf, indexado para consulta."""

    def __init__(self, items: dict[str, Any], key_in_refined: float) -> None:
        if key_in_refined <= 0:
            raise ValueError("key_in_refined tem que ser positivo")
        self._items = items
        self._key_in_refined = key_in_refined

    @classmethod
    def from_payload(cls, payload: dict[str, Any], key_in_refined: float) -> "PriceIndex":
        return cls(payload["response"]["items"], key_in_refined)

    def item_names(self) -> set[str]:
        return set(self._items)

    def entries(self, item_name: str, quality_id: int) -> list[PriceEntry]:
        return list(self._iter_entries(item_name, quality_id))

    def _iter_entries(self, item_name: str, quality_id: int) -> Iterator[PriceEntry]:
        item = self._items.get(item_name)
        if not item:
            return

        quality = (item.get("prices") or {}).get(str(quality_id))
        if not quality:
            return

        # Só itens tradáveis interessam: um item não-tradável não pode virar
        # chaves, que é a moeda em que o lucro é denominado.
        tradable = quality.get("Tradable")
        if not tradable:
            return

        for craft_key, node in tradable.items():
            craftable = craft_key == "Craftable"

            # A bp.tf usa LISTA para itens sem variante e DICIONÁRIO com
            # priceindex para itens com variante (efeitos de Unusual, séries
            # de caixa). Mesmo campo, dois tipos. Tratar só um faz metade do
            # catálogo sumir sem erro nenhum.
            if isinstance(node, list):
                for entry in node:
                    yield PriceEntry(craftable, None, _to_price(entry))
            elif isinstance(node, dict):
                for priceindex, entry in node.items():
                    yield PriceEntry(craftable, str(priceindex), _to_price(entry))

    def to_keys(self, price: BptfPrice | None) -> float | None:
        """Converte para chaves, ou None se não der.

        USD não é convertido de propósito: é o sinal candidato de preço
        derivado da Steam Market (guarda 4). Converter esconderia justamente
        o que o spike precisa medir.
        """
        if price is None:
            return None
        if price.currency == "keys":
            return price.value
        if price.currency == "metal":
            return price.value / self._key_in_refined
        return None

    def lookup(
        self,
        item_name: str,
        quality_id: int,
        craftable: bool = True,
        priceindex: str | None = None,
    ) -> BptfPrice | None:
        for entry in self._iter_entries(item_name, quality_id):
            if entry.craftable != craftable:
                continue
            if priceindex is not None and entry.priceindex != priceindex:
                continue
            if priceindex is None and entry.priceindex is not None:
                continue
            return entry.price
        return None

    def value_range_keys(self, item_name: str, quality_id: int) -> ValueRange | None:
        """Faixa de valor sobre TODAS as interpretações do nome.

        É esta faixa que a poda das três vias consome: o mínimo é o pior
        cenário possível, o máximo é o melhor.
        """
        values = [
            keys
            for entry in self._iter_entries(item_name, quality_id)
            if (keys := self.to_keys(entry.price)) is not None and keys > 0
        ]
        if not values:
            return None
        return ValueRange(min_keys=min(values), max_keys=max(values))


class BackpackTfClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("BPTF_API_KEY não configurada")
        self._api_key = api_key
        self._http = client or httpx.Client(
            timeout=180.0,  # IGetPrices devolve dezenas de MB
            headers={"User-Agent": "tf2price-spike/0.1"},
            follow_redirects=True,
        )

    def _get(self, path: str) -> dict[str, Any]:
        response = self._http.get(
            f"{BASE}/{path}", params={"key": self._api_key, "appid": APPID}
        )
        response.raise_for_status()
        return response.json()

    def currencies(self) -> Currencies:
        return Currencies.from_payload(self._get("IGetCurrencies/v1"))

    def prices_payload(self) -> dict[str, Any]:
        return self._get("IGetPrices/v4")
```

- [ ] **Step 6: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/sources/test_backpacktf.py -v
```

Esperado: 18 passed

- [ ] **Step 7: Commit**

```bash
git add tf2price/sources/backpacktf.py tests/sources/test_backpacktf.py tests/fixtures
git commit -m "$(cat <<'MSG'
Adiciona cliente e índice de preços da backpack.tf

Trata a esquisitice central do IGetPrices: o nível de craftabilidade
vem como lista para itens sem variante e como dicionário indexado por
priceindex para itens com variante. Tratar só um dos casos faria
metade do catálogo sumir sem erro.

Preço em USD não é convertido de propósito: é o sinal candidato da
guarda 4, e converter esconderia o que o spike precisa medir.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 8: `domain/effects.py` e `scripts/fetch_effects.py` — mapa de efeitos

O fetch profundo devolve o efeito como **nome** (`"Burning Flames"`). O índice da bp.tf indexa por **id numérico** (`priceindex = "13"`). Sem a ponte entre os dois, nenhum Unusual casa.

**Files:**
- Create: `scripts/fetch_effects.py`
- Create: `tf2price/data/effects.json` (gerado pelo script)
- Create: `tf2price/domain/effects.py`
- Create: `tests/fixtures/effects_sample.json`
- Test: `tests/domain/test_effects.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `DEFAULT_EFFECTS_PATH: Path`
  - `load_effect_map(path: Path = DEFAULT_EFFECTS_PATH) -> dict[str, int]` — nome do efeito para id, com cache.
  - `effect_id_for(name: str, path: Path = DEFAULT_EFFECTS_PATH) -> int | None` — tolerante a espaços e caixa.

**Nota sobre pureza:** `domain/` não faz I/O **sem injeção**. Aqui o caminho é parâmetro com default, então o teste injeta uma fixture e o módulo continua testável sem tocar no arquivo real.

- [ ] **Step 1: Escrever `scripts/fetch_effects.py`**

```python
"""Gera tf2price/data/effects.json a partir do schema oficial do TF2.

Roda uma vez. Precisa de STEAM_API_KEY (grátis em
https://steamcommunity.com/dev/apikey).

    .venv/Scripts/python scripts/fetch_effects.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

SCHEMA_URL = "https://api.steampowered.com/IEconItems_440/GetSchemaOverview/v0001/"
DESTINO = Path(__file__).resolve().parent.parent / "tf2price" / "data" / "effects.json"


def main() -> int:
    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    if not api_key:
        print("STEAM_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    response = httpx.get(
        SCHEMA_URL, params={"key": api_key, "language": "en"}, timeout=60.0
    )
    response.raise_for_status()

    particles = response.json()["result"]["attribute_controlled_attached_particles"]
    mapa = {str(p["name"]): int(p["id"]) for p in particles}

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(
        json.dumps(mapa, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{len(mapa)} efeitos gravados em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Rodar o script para gerar o arquivo real**

```bash
.venv/Scripts/python scripts/fetch_effects.py
```

Esperado: `NNN efeitos gravados em .../tf2price/data/effects.json`, com NNN na casa das centenas.

> Se a `STEAM_API_KEY` não estiver disponível, pare aqui e peça a chave ao usuário. Não invente um `effects.json` parcial — um mapa incompleto faz Unusuals sumirem silenciosamente da análise, que é exatamente o tipo de falha que este spike existe para evitar.

- [ ] **Step 3: Criar `tests/fixtures/effects_sample.json`**

```json
{
  "Burning Flames": 13,
  "Circling TF Logo": 11,
  "Green Confetti": 6,
  "Scorching Flames": 14,
  "Sunbeams": 17
}
```

> Nota: a fixture é um recorte mínimo do schema real, só com os efeitos que os testes usam. `"Green Confetti"` está aqui de propósito **sem** preço correspondente no `bptf_prices.json`, para cobrir o caso de efeito conhecido mas não precificado.

- [ ] **Step 4: Escrever o teste que falha**

Arquivo `tests/domain/test_effects.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.effects import effect_id_for, load_effect_map

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"


def test_carrega_o_mapa():
    mapa = load_effect_map(FIXTURE)
    assert mapa["Burning Flames"] == 13


def test_ids_sao_inteiros():
    mapa = load_effect_map(FIXTURE)
    assert all(isinstance(v, int) for v in mapa.values())


def test_busca_por_nome_exato():
    assert effect_id_for("Burning Flames", FIXTURE) == 13


def test_busca_ignora_caixa_e_espacos():
    assert effect_id_for("  burning FLAMES  ", FIXTURE) == 13


def test_efeito_desconhecido_devolve_none():
    assert effect_id_for("Efeito Inexistente", FIXTURE) is None


def test_arquivo_ausente_levanta_erro_claro(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="effects.json"):
        load_effect_map(tmp_path / "nao_existe.json")


def test_mapa_real_do_projeto_existe_e_tem_centenas_de_efeitos():
    """O effects.json de produção precisa estar gerado (Task 8, Step 2)."""
    mapa = load_effect_map()
    assert len(mapa) > 100
    assert "Burning Flames" in mapa
```

- [ ] **Step 5: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/domain/test_effects.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.domain.effects'`

- [ ] **Step 6: Implementar `tf2price/domain/effects.py`**

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_EFFECTS_PATH = Path(__file__).resolve().parent.parent / "data" / "effects.json"


@lru_cache(maxsize=4)
def load_effect_map(path: Path = DEFAULT_EFFECTS_PATH) -> dict[str, int]:
    """Nome do efeito de Unusual para o id usado como priceindex na bp.tf.

    O caminho é parâmetro com default para o módulo continuar testável sem
    tocar no arquivo de produção.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"effects.json não encontrado em {path}. "
            "Rode: .venv/Scripts/python scripts/fetch_effects.py"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): int(effect_id) for name, effect_id in raw.items()}


@lru_cache(maxsize=4)
def _normalized_map(path: Path) -> dict[str, int]:
    return {name.strip().casefold(): eid for name, eid in load_effect_map(path).items()}


def effect_id_for(name: str, path: Path = DEFAULT_EFFECTS_PATH) -> int | None:
    """Busca tolerante a caixa e espaços.

    A Steam devolve o efeito dentro de uma string de descrição; espaço
    extra ou diferença de caixa não deveria fazer o item sumir da análise.
    """
    return _normalized_map(path).get(name.strip().casefold())
```

- [ ] **Step 7: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/domain/test_effects.py -v
```

Esperado: 7 passed

- [ ] **Step 8: Commit**

```bash
git add scripts/fetch_effects.py tf2price/domain/effects.py tf2price/data/effects.json tests/domain/test_effects.py tests/fixtures/effects_sample.json
git commit -m "$(cat <<'MSG'
Adiciona o mapa de efeitos de Unusual

A Steam devolve o efeito como nome, a bp.tf indexa por id numérico.
Sem essa ponte nenhum Unusual casa.

Busca tolerante a caixa e espaços: o nome vem dentro de uma string de
descrição, e diferença de formatação não deveria fazer o item sumir
da análise.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 9: `spike/pipeline.py` — a lógica de decisão, pura

Toda a lógica do spike opera sobre dados **já buscados**. O I/O fica no Task 11. Essa separação existe porque a decisão precisa de teste e o I/O não.

**Files:**
- Create: `tf2price/spike/pipeline.py`
- Test: `tests/spike/test_pipeline.py`

**Interfaces:**
- Consumes: `ItemIdentity`, `parse_market_hash_name`, `bptf_name_candidates` (Task 2); `Classification`, `ValueRange`, `classify` (Task 3); `Valuation`, `Guard`, `evaluate`, `check_guards` (Task 4); `SearchResult`, `Listing` (Task 6); `PriceIndex`, `PriceEntry` (Task 7); `effect_id_for` (Task 8).
- Produces:
  - `QUALITY_UNUSUAL = 5`
  - `Candidate` — frozen dataclass: `hash_name: str`, `identity: ItemIdentity`, `bptf_name: str`, `value_range: ValueRange`, `classification: Classification`, `steam_lowest: Brl`, `sell_listings: int`.
  - `Opportunity` — frozen dataclass: `hash_name: str`, `listing_id: str | None`, `effect: str | None`, `craftable: bool | None`, `steam_total: Brl`, `valuation: Valuation`, `classification: Classification`, `guard: Guard`, `deep_fetched: bool`; propriedades `absolute_discount -> Brl` e `steam_url -> str`.
  - `ShallowOutcome` — frozen dataclass: `candidates: list[Candidate]`, `unmatched: list[str]`.
  - `shallow_pass(results, index, key_brl, threshold) -> ShallowOutcome`
  - `guaranteed_opportunities(candidates, index, key_brl, now=None) -> list[Opportunity]`
  - `deep_targets(candidates, key_brl, limit) -> list[Candidate]`
  - `resolve_deep(candidate, listings, index, key_brl, now=None) -> list[Opportunity]`

**Decisão de projeto:** uma oportunidade **garantida** é avaliada pelo **pior** valor da faixa, não pelo melhor. A poda já provou que ela vale mesmo no pior cenário; reportá-la pelo melhor cenário inflaria o desconto com uma suposição que ninguém verificou. O relatório tem que poder ser lido sem desconto de credibilidade.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/spike/test_pipeline.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import Guard
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam import Listing, SearchResult
from tf2price.spike.pipeline import (
    deep_targets,
    guaranteed_opportunities,
    resolve_deep,
    shallow_pass,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
EFEITOS = FIXTURES / "effects_sample.json"
KEY_IN_REFINED = 69.44
CHAVE = Brl.from_float(22.00)
AGORA = 1_760_000_000


@pytest.fixture
def index() -> PriceIndex:
    payload = json.loads((FIXTURES / "bptf_prices.json").read_text(encoding="utf-8"))
    return PriceIndex.from_payload(payload, KEY_IN_REFINED)


def _resultado(hash_name: str, reais: float, listings: int = 5) -> SearchResult:
    return SearchResult(
        hash_name=hash_name,
        lowest_price=Brl.from_float(reais),
        sell_listings=listings,
    )


# --- passada rasa --------------------------------------------------------


def test_nome_sem_correspondencia_vai_para_unmatched(index: PriceIndex):
    saida = shallow_pass([_resultado("Item Inexistente", 10.0)], index, CHAVE, 0.15)
    assert saida.candidates == []
    assert saida.unmatched == ["Item Inexistente"]


def test_unusual_barato_e_candidata(index: PriceIndex):
    # Team Captain Unusual: faixa de 9 a 45 chaves = R$ 198 a R$ 990.
    # Piso com limiar 15% = R$ 168,30. Teto = R$ 841,50.
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.CANDIDATE


def test_unusual_muito_barato_e_garantida(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.GUARANTEED


def test_unusual_caro_e_descartada(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 950.0)], index, CHAVE, 0.15)
    assert saida.candidates[0].classification is Classification.DISCARDED


def test_resolve_nome_com_australium_pela_lista_de_candidatos(index: PriceIndex):
    """'Strange Australium Rocket Launcher' cai em 'Rocket Launcher' quality 11
    depois que a variante Australium não existe no índice."""
    saida = shallow_pass(
        [_resultado("Strange Australium Rocket Launcher", 1.0)], index, CHAVE, 0.15
    )
    assert saida.candidates[0].bptf_name == "Rocket Launcher"
    assert saida.candidates[0].identity.quality_id == 11


def test_item_so_em_usd_nao_gera_candidata(index: PriceIndex):
    """Sem valor convertível para chaves não há faixa, e sem faixa não há poda."""
    saida = shallow_pass(
        [_resultado("Mildly Disturbing Halloween Mask", 1.0)], index, CHAVE, 0.15
    )
    assert saida.candidates == []
    assert saida.unmatched == ["Mildly Disturbing Halloween Mask"]


# --- garantidas ----------------------------------------------------------


def test_garantida_e_avaliada_pelo_pior_valor_da_faixa(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    oportunidades = guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA)

    assert len(oportunidades) == 1
    # pior efeito = 9 chaves = R$ 198, não os 45 chaves do melhor
    assert oportunidades[0].valuation.fair_value == Brl.from_float(198.00)
    assert oportunidades[0].deep_fetched is False
    assert oportunidades[0].guard is Guard.OK


def test_garantida_expoe_desconto_absoluto_e_url(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    oportunidade = guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA)[0]

    assert oportunidade.absolute_discount == Brl.from_float(98.00)
    assert "Unusual%20Team%20Captain" in oportunidade.steam_url


def test_candidatas_nao_viram_garantidas(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    assert guaranteed_opportunities(saida.candidates, index, CHAVE, now=AGORA) == []


def test_preco_desatualizado_reprova_a_garantida(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 100.0)], index, CHAVE, 0.15)
    futuro = 1_759_900_000 + 40 * 86400
    oportunidade = guaranteed_opportunities(saida.candidates, index, CHAVE, now=futuro)[0]
    assert oportunidade.guard is Guard.STALE_PRICE


# --- alvos do fetch profundo ---------------------------------------------


def test_deep_targets_ordena_pelo_melhor_cenario(index: PriceIndex):
    saida = shallow_pass(
        [
            _resultado("Unusual Team Captain", 800.0),
            _resultado("Unusual Team Captain", 300.0),
        ],
        index,
        CHAVE,
        0.15,
    )
    alvos = deep_targets(saida.candidates, CHAVE, limit=2)
    assert alvos[0].steam_lowest == Brl.from_float(300.00)


def test_deep_targets_respeita_o_limite(index: PriceIndex):
    saida = shallow_pass(
        [_resultado("Unusual Team Captain", 500.0)] * 5, index, CHAVE, 0.15
    )
    assert len(deep_targets(saida.candidates, CHAVE, limit=3)) == 3


def test_deep_targets_ignora_garantidas_e_descartadas(index: PriceIndex):
    saida = shallow_pass(
        [
            _resultado("Unusual Team Captain", 100.0),  # garantida
            _resultado("Unusual Team Captain", 950.0),  # descartada
        ],
        index,
        CHAVE,
        0.15,
    )
    assert deep_targets(saida.candidates, CHAVE, limit=10) == []


# --- fetch profundo ------------------------------------------------------


def _listagem(
    listing_id: str, reais: float, effect: str | None, craftable: bool = True
) -> Listing:
    return Listing(
        listing_id=listing_id,
        total_price=Brl.from_float(reais),
        effect=effect,
        craftable=craftable,
        spelled=False,
    )


def test_resolve_deep_casa_o_efeito_com_o_priceindex(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    candidata = saida.candidates[0]

    oportunidades = resolve_deep(
        candidata,
        [_listagem("L1", 500.0, "Burning Flames")],  # id 13 = 28 chaves = R$ 616
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )

    assert len(oportunidades) == 1
    assert oportunidades[0].effect == "Burning Flames"
    assert oportunidades[0].valuation.fair_value == Brl.from_float(616.00)
    assert oportunidades[0].deep_fetched is True
    assert oportunidades[0].guard is Guard.OK


def test_resolve_deep_ignora_listagem_sem_efeito_em_item_unusual(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, None)],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []


def test_resolve_deep_ignora_efeito_fora_do_mapa(index: PriceIndex):
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, "Efeito Que Não Existe")],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []


def test_resolve_deep_ignora_efeito_sem_preco_no_indice(index: PriceIndex):
    """Green Confetti (id 6) está no mapa mas não tem preço no fixture."""
    saida = shallow_pass([_resultado("Unusual Team Captain", 500.0)], index, CHAVE, 0.15)
    oportunidades = resolve_deep(
        saida.candidates[0],
        [_listagem("L1", 500.0, "Green Confetti")],
        index,
        CHAVE,
        now=AGORA,
        effects_path=EFEITOS,
    )
    assert oportunidades == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/spike/test_pipeline.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.spike.pipeline'`

- [ ] **Step 3: Implementar `tf2price/spike/pipeline.py`**

```python
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import (
    ItemIdentity,
    bptf_name_candidates,
    parse_market_hash_name,
)
from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification, ValueRange, classify
from tf2price.domain.valuation import Guard, Valuation, check_guards, evaluate
from tf2price.sources.backpacktf import PriceEntry, PriceIndex
from tf2price.sources.steam import APPID, Listing, SearchResult

QUALITY_UNUSUAL = 5


@dataclass(frozen=True)
class Candidate:
    hash_name: str
    identity: ItemIdentity
    bptf_name: str
    value_range: ValueRange
    classification: Classification
    steam_lowest: Brl
    sell_listings: int


@dataclass(frozen=True)
class Opportunity:
    hash_name: str
    listing_id: str | None
    effect: str | None
    craftable: bool | None
    steam_total: Brl
    valuation: Valuation
    classification: Classification
    guard: Guard
    deep_fetched: bool

    @property
    def absolute_discount(self) -> Brl:
        return self.valuation.fair_value - self.steam_total

    @property
    def steam_url(self) -> str:
        quoted = urllib.parse.quote(self.hash_name, safe="")
        return f"https://steamcommunity.com/market/listings/{APPID}/{quoted}"


@dataclass(frozen=True)
class ShallowOutcome:
    candidates: list[Candidate]
    unmatched: list[str]


def _resolve_bptf_name(identity: ItemIdentity, original: str, index: PriceIndex) -> str | None:
    """Primeiro nome candidato que existe no índice COM faixa utilizável.

    Existir no índice não basta: um item precificado só em USD não tem valor
    convertível para chaves, e sem faixa a poda não tem o que fazer.
    """
    for name in bptf_name_candidates(identity, original):
        if index.value_range_keys(name, identity.quality_id) is not None:
            return name
    return None


def shallow_pass(
    results: list[SearchResult],
    index: PriceIndex,
    key_brl: Brl,
    threshold: float,
) -> ShallowOutcome:
    candidates: list[Candidate] = []
    unmatched: list[str] = []

    for result in results:
        identity = parse_market_hash_name(result.hash_name)
        bptf_name = _resolve_bptf_name(identity, result.hash_name, index)

        if bptf_name is None:
            unmatched.append(result.hash_name)
            continue

        value_range = index.value_range_keys(bptf_name, identity.quality_id)
        candidates.append(
            Candidate(
                hash_name=result.hash_name,
                identity=identity,
                bptf_name=bptf_name,
                value_range=value_range,
                classification=classify(result.lowest_price, value_range, key_brl, threshold),
                steam_lowest=result.lowest_price,
                sell_listings=result.sell_listings,
            )
        )

    return ShallowOutcome(candidates=candidates, unmatched=unmatched)


def _entry_with_min_keys(
    index: PriceIndex, item_name: str, quality_id: int
) -> tuple[PriceEntry, float] | None:
    best: tuple[PriceEntry, float] | None = None
    for entry in index.entries(item_name, quality_id):
        keys = index.to_keys(entry.price)
        if keys is None or keys <= 0:
            continue
        if best is None or keys < best[1]:
            best = (entry, keys)
    return best


def guaranteed_opportunities(
    candidates: list[Candidate],
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
) -> list[Opportunity]:
    """Avalia as garantidas SEM fetch profundo, pelo pior valor da faixa.

    Usar o pior valor é o que torna o número reportável: a poda provou que
    o item vale ao menos isso, então o desconto mostrado não depende de
    nenhuma suposição não verificada.
    """
    opportunities: list[Opportunity] = []

    for candidate in candidates:
        if candidate.classification is not Classification.GUARANTEED:
            continue

        worst = _entry_with_min_keys(index, candidate.bptf_name, candidate.identity.quality_id)
        if worst is None:
            continue
        entry, keys = worst

        opportunities.append(
            Opportunity(
                hash_name=candidate.hash_name,
                listing_id=None,
                effect=None,
                craftable=entry.craftable,
                steam_total=candidate.steam_lowest,
                valuation=evaluate(candidate.steam_lowest, keys, key_brl),
                classification=candidate.classification,
                guard=check_guards(entry.price, candidate.classification, False, now=now),
                deep_fetched=False,
            )
        )

    return opportunities


def deep_targets(candidates: list[Candidate], key_brl: Brl, limit: int) -> list[Candidate]:
    """Candidatas ordenadas pelo desconto no cenário mais favorável.

    O fetch profundo é o recurso caro do spike; gastá-lo primeiro onde o
    potencial é maior é o que faz 20 requisições valerem alguma coisa.
    """
    pending = [c for c in candidates if c.classification is Classification.CANDIDATE]

    def best_case_discount(candidate: Candidate) -> float:
        ceiling = key_brl * candidate.value_range.max_keys
        if ceiling.cents <= 0:
            return -1.0
        return 1 - candidate.steam_lowest.cents / ceiling.cents

    pending.sort(key=best_case_discount, reverse=True)
    return pending[:limit]


def resolve_deep(
    candidate: Candidate,
    listings: list[Listing],
    index: PriceIndex,
    key_brl: Brl,
    now: int | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> list[Opportunity]:
    """Resolve as incógnitas de uma candidata com as listagens reais."""
    opportunities: list[Opportunity] = []
    quality_id = candidate.identity.quality_id

    for listing in listings:
        priceindex: str | None = None

        if quality_id == QUALITY_UNUSUAL:
            if listing.effect is None:
                continue  # Unusual sem efeito legível: não dá para avaliar
            effect_id = effect_id_for(listing.effect, effects_path)
            if effect_id is None:
                continue  # efeito fora do mapa: registrar seria ruído, pular é honesto
            priceindex = str(effect_id)

        price = index.lookup(
            candidate.bptf_name,
            quality_id,
            craftable=listing.craftable,
            priceindex=priceindex,
        )
        keys = index.to_keys(price)
        if keys is None or keys <= 0:
            continue

        opportunities.append(
            Opportunity(
                hash_name=candidate.hash_name,
                listing_id=listing.listing_id,
                effect=listing.effect,
                craftable=listing.craftable,
                steam_total=listing.total_price,
                valuation=evaluate(listing.total_price, keys, key_brl),
                classification=candidate.classification,
                guard=check_guards(price, candidate.classification, True, now=now),
                deep_fetched=True,
            )
        )

    return opportunities
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/spike/test_pipeline.py -v
```

Esperado: 17 passed

- [ ] **Step 5: Commit**

```bash
git add tf2price/spike/pipeline.py tests/spike/test_pipeline.py
git commit -m "$(cat <<'MSG'
Adiciona a lógica de decisão do spike, sem I/O

Garantidas são avaliadas pelo PIOR valor da faixa, não pelo melhor:
a poda provou que valem ao menos isso, então o desconto reportado
não depende de suposição não verificada.

Alvos do fetch profundo são ordenados pelo cenário mais favorável,
que é o que faz 20 requisições valerem alguma coisa.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 10: `spike/report.py` — veredito, análise da guarda 4 e relatório

**Files:**
- Create: `tf2price/spike/report.py`
- Test: `tests/spike/test_report.py`

**Interfaces:**
- Consumes: `Opportunity` (Task 9), `Guard` (Task 4), `PriceIndex` (Task 7), `Brl` (Task 1).
- Produces:
  - `Verdict(str, Enum)` com `GREEN = "VERDE"`, `YELLOW = "AMARELO"`, `RED = "VERMELHO"`.
  - `STRONG_DISCOUNT = 0.20`, `MIN_MEAN_DISCOUNT_BRL = Brl.from_float(50.00)`.
  - `net_opportunities(opportunities) -> list[Opportunity]` — só `Guard.OK` e desconto positivo.
  - `decide(opportunities) -> Verdict`
  - `MarketDerivedAnalysis` — frozen dataclass: `sample_size: int`, `median_discount: float | None`, `fraction_near_15pct: float`, `hypothesis_supported: bool`.
  - `analyse_market_derived(index, results, raw_usd_per_refined, key_in_refined, key_brl) -> MarketDerivedAnalysis`
  - `render_markdown(...) -> str` e `render_csv(opportunities) -> str`.

**Contexto — como testar a hipótese da guarda 4 sem cotação externa:**

A hipótese é que a bp.tf precifica alguns itens a partir da Steam Market, descontando 15%. Para conferir, é preciso converter os preços em USD da bp.tf para BRL. E dá para fazer isso **sem consultar câmbio nenhum**, usando só dados já em mãos:

```
usd_por_chave = raw_usd_value × key_in_refined     # raw_usd_value = USD por refined
brl_por_usd   = key_brl / usd_por_chave            # câmbio implícito na economia Steam
valor_brl     = valor_usd × brl_por_usd
```

Se a hipótese estiver certa, o desconto desses itens vai se **agrupar perto de 15%**. Se estiver errada, vai se espalhar. O spike reporta qual dos dois aconteceu.

- [ ] **Step 1: Escrever o teste que falha**

Arquivo `tests/spike/test_report.py`:

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import Guard, evaluate
from tf2price.spike.pipeline import Opportunity
from tf2price.spike.report import (
    Verdict,
    decide,
    net_opportunities,
    render_csv,
    render_markdown,
)

CHAVE = Brl.from_float(22.00)


def _oportunidade(
    desconto_reais: float, fair_reais: float = 200.0, guard: Guard = Guard.OK
) -> Opportunity:
    fair_keys = fair_reais / 22.0
    pago = Brl.from_float(fair_reais - desconto_reais)
    return Opportunity(
        hash_name="Unusual Team Captain",
        listing_id="L1",
        effect="Burning Flames",
        craftable=True,
        steam_total=pago,
        valuation=evaluate(pago, fair_keys, CHAVE),
        classification=Classification.CANDIDATE,
        guard=guard,
        deep_fetched=True,
    )


def test_liquidas_excluem_reprovadas_pela_guarda():
    todas = [_oportunidade(60.0), _oportunidade(60.0, guard=Guard.STALE_PRICE)]
    assert len(net_opportunities(todas)) == 1


def test_liquidas_excluem_desconto_negativo():
    assert net_opportunities([_oportunidade(-10.0)]) == []


def test_veredito_verde():
    # 10 oportunidades com 30% de desconto e R$ 60 de valor absoluto
    todas = [_oportunidade(60.0) for _ in range(10)]
    assert decide(todas) is Verdict.GREEN


def test_veredito_amarelo_por_quantidade():
    todas = [_oportunidade(60.0) for _ in range(5)]
    assert decide(todas) is Verdict.YELLOW


def test_veredito_amarelo_por_valor_baixo():
    # quantidade suficiente, mas desconto médio de R$ 45 fica abaixo do corte
    todas = [_oportunidade(45.0) for _ in range(12)]
    assert decide(todas) is Verdict.YELLOW


def test_veredito_vermelho():
    assert decide([_oportunidade(60.0) for _ in range(2)]) is Verdict.RED


def test_veredito_vermelho_com_lista_vazia():
    assert decide([]) is Verdict.RED


def test_desconto_fraco_nao_conta_para_o_veredito():
    # 15% de desconto está abaixo do corte de 20%
    fracas = [_oportunidade(30.0) for _ in range(20)]
    assert decide(fracas) is Verdict.RED


def test_csv_tem_cabecalho_e_uma_linha_por_oportunidade():
    linhas = render_csv([_oportunidade(60.0), _oportunidade(70.0)]).strip().splitlines()
    assert linhas[0].startswith("hash_name,")
    assert len(linhas) == 3


def test_csv_escapa_virgula_no_nome():
    oportunidade = replace(_oportunidade(60.0), hash_name='Item, com vírgula')
    assert '"Item, com vírgula"' in render_csv([oportunidade])


def test_markdown_traz_o_veredito_e_as_contagens():
    texto = render_markdown(
        opportunities=[_oportunidade(60.0) for _ in range(10)],
        key_brl=CHAVE,
        key_median_brl=Brl.from_float(22.49),
        total_names=21543,
        unmatched=["Item Estranho"],
        guaranteed_count=8,
        candidate_count=120,
        deep_fetched_count=20,
        requests_made=231,
        first_429_after=None,
        market_derived=None,
    )
    assert "VERDE" in texto
    assert "21543" in texto
    assert "Item Estranho" in texto


def test_markdown_lista_nomes_nao_casados_por_frequencia():
    texto = render_markdown(
        opportunities=[],
        key_brl=CHAVE,
        key_median_brl=CHAVE,
        total_names=3,
        unmatched=["A", "B", "A", "A", "B"],
        guaranteed_count=0,
        candidate_count=0,
        deep_fetched_count=0,
        requests_made=1,
        first_429_after=None,
        market_derived=None,
    )
    posicao_a = texto.index("| A |")
    posicao_b = texto.index("| B |")
    assert posicao_a < posicao_b


def test_analise_da_guarda_4_confirma_agrupamento_em_15pct():
    from tf2price.spike.report import analyse_market_derived

    # câmbio implícito: usd_por_chave = 0.0363 * 69.44 = 2.5207
    #                   brl_por_usd  = 22.00 / 2.5207 = 8.7277
    # item de US$ 10 -> R$ 87,28. Listado a 85% disso -> R$ 74,19
    usd_items = [(10.0, Brl.from_float(74.19)) for _ in range(40)]

    analise = analyse_market_derived(
        usd_items=usd_items,
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )

    assert analise.sample_size == 40
    assert analise.median_discount == pytest.approx(0.15, abs=0.01)
    assert analise.fraction_near_15pct == pytest.approx(1.0)
    assert analise.hypothesis_supported is True


def test_analise_da_guarda_4_refuta_quando_espalhado():
    from tf2price.spike.report import analyse_market_derived

    usd_items = [(10.0, Brl.from_float(20.0 + i * 3)) for i in range(40)]
    analise = analyse_market_derived(
        usd_items=usd_items,
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )
    assert analise.hypothesis_supported is False


def test_analise_da_guarda_4_com_amostra_pequena_nao_conclui():
    from tf2price.spike.report import analyse_market_derived

    analise = analyse_market_derived(
        usd_items=[(10.0, Brl.from_float(74.19))],
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )
    assert analise.hypothesis_supported is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/spike/test_report.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'tf2price.spike.report'`

- [ ] **Step 3: Implementar `tf2price/spike/report.py`**

```python
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


def decide(opportunities: list[Opportunity]) -> Verdict:
    """Veredito do §8 do spec, sobre as líquidas."""
    strong = [
        o
        for o in net_opportunities(opportunities)
        if o.valuation.discount >= STRONG_DISCOUNT
    ]

    if not strong:
        return Verdict.RED

    mean_cents = sum(o.absolute_discount.cents for o in strong) / len(strong)

    if len(strong) >= MIN_STRONG_COUNT_GREEN and mean_cents >= MIN_MEAN_DISCOUNT_BRL.cents:
        return Verdict.GREEN
    if len(strong) >= MIN_STRONG_COUNT_YELLOW:
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

    def faixa(minimo: float) -> int:
        return sum(1 for o in net if o.valuation.discount >= minimo)

    linhas: list[str] = []
    add = linhas.append

    add("# Relatório do spike de arbitragem TF2")
    add("")
    add(f"## Veredito: **{verdict.value}**")
    add("")
    add("### Oportunidades")
    add("")
    add("| Faixa de desconto | Líquidas |")
    add("|---|---|")
    add(f"| >= 15% | {faixa(0.15)} |")
    add(f"| >= 25% | {faixa(0.25)} |")
    add(f"| >= 40% | {faixa(0.40)} |")
    add("")
    add(f"- Brutas avaliadas: {len(opportunities)}")
    add(f"- Líquidas (pós-guardas, desconto positivo): {len(net)}")

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
    for guard, total in Counter(o.guard for o in opportunities).most_common():
        add(f"| {guard.value} | {total} |")

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
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/spike/test_report.py -v
```

Esperado: 15 passed

- [ ] **Step 5: Commit**

```bash
git add tf2price/spike/report.py tests/spike/test_report.py
git commit -m "$(cat <<'MSG'
Adiciona veredito, análise da guarda 4 e relatório

O veredito sai dos números do §8 do spec, sobre as oportunidades
líquidas, para a decisão não depender de vontade de que dê certo.

A hipótese da guarda 4 é testada sem consultar câmbio externo: o
USD-BRL sai da própria economia da Steam, cruzando o valor do refined
em dólar com o valor da chave em reais.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

### Task 11: `spike/run.py`, execução real e registro das verificações

Último task. Amarra tudo, roda de verdade contra a Steam e a backpack.tf, e produz os dois entregáveis do spike: o relatório com o veredito e o documento de verificações técnicas.

**Files:**
- Modify: `tf2price/spike/pipeline.py` (acrescenta `collect_usd_items`)
- Modify: `tests/spike/test_pipeline.py` (acrescenta os testes de `collect_usd_items`)
- Create: `tf2price/spike/run.py`
- Create: `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`
- Create: `README.md`

**Interfaces:**
- Consumes: tudo dos tasks 1 a 10.
- Produces: `collect_usd_items(results, index) -> list[tuple[float, Brl]]` e `main(argv=None) -> int`.

- [ ] **Step 1: Escrever o teste que falha para `collect_usd_items`**

Acrescentar ao fim de `tests/spike/test_pipeline.py`:

```python
def test_collect_usd_items_pega_valor_em_dolar_e_preco_da_steam(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    itens = collect_usd_items(
        [_resultado("Mildly Disturbing Halloween Mask", 30.0)], index
    )
    assert itens == [(4.25, Brl.from_float(30.00))]


def test_collect_usd_items_ignora_itens_precificados_em_chaves(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    assert collect_usd_items([_resultado("Unusual Team Captain", 500.0)], index) == []


def test_collect_usd_items_ignora_nome_fora_do_indice(index: PriceIndex):
    from tf2price.spike.pipeline import collect_usd_items

    assert collect_usd_items([_resultado("Item Inexistente", 10.0)], index) == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
.venv/Scripts/python -m pytest tests/spike/test_pipeline.py -k collect_usd -v
```

Esperado: FAIL com `ImportError: cannot import name 'collect_usd_items'`

- [ ] **Step 3: Acrescentar `collect_usd_items` ao fim de `tf2price/spike/pipeline.py`**

```python
def collect_usd_items(
    results: list[SearchResult], index: PriceIndex
) -> list[tuple[float, Brl]]:
    """Pares (valor em USD na bp.tf, preço na Steam) para testar a guarda 4.

    Estes itens são justamente os que `shallow_pass` descarta como não
    casados, porque USD não converte para chaves. Coletá-los à parte é o
    que permite verificar se o preço deles é derivado da Steam Market.
    """
    pairs: list[tuple[float, Brl]] = []

    for result in results:
        identity = parse_market_hash_name(result.hash_name)

        for name in bptf_name_candidates(identity, result.hash_name):
            entries = index.entries(name, identity.quality_id)
            if not entries:
                continue

            usd = [
                e
                for e in entries
                if e.price.currency == "usd" and e.craftable and e.price.value > 0
            ]
            if usd:
                pairs.append((usd[0].price.value, result.lowest_price))
            break  # primeiro nome que existe no índice decide

    return pairs
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
.venv/Scripts/python -m pytest tests/spike/test_pipeline.py -v
```

Esperado: 20 passed

- [ ] **Step 5: Implementar `tf2price/spike/run.py`**

```python
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
```

- [ ] **Step 6: Rodar a suíte inteira**

```bash
.venv/Scripts/python -m pytest -v
```

Esperado: tudo verde. Se algo falhar, conserte antes de seguir — o próximo passo gasta requisições reais.

- [ ] **Step 7: Commit do código**

```bash
git add tf2price/spike tests/spike
git commit -m "$(cat <<'MSG'
Adiciona a execução do spike

Coleta itens precificados em USD à parte, que são justamente os que
a passada rasa descarta como não casados — é o que permite testar a
hipótese da guarda 4.

Falha de fetch profundo numa candidata não derruba a varredura.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

- [ ] **Step 8: Ensaiar com poucas páginas antes de rodar tudo**

```bash
.venv/Scripts/python -m tf2price.spike.run --max-pages 2 --deep-limit 3 --out out/ensaio
```

Esperado: roda até o fim, imprime um veredito e grava `out/ensaio/relatorio.md`.

> Este passo existe para descobrir erro de integração gastando 5 requisições em vez de 230. Se ele falhar, conserte e repita antes de seguir. Se aparecer 429 já aqui, suba `--min-interval` para 5 ou 6.

- [ ] **Step 9: Execução real completa**

```bash
.venv/Scripts/python -m tf2price.spike.run --out out
```

Esperado: cerca de 230 requisições, 15 a 30 minutos com o intervalo padrão de 3 s, terminando com o veredito impresso.

- [ ] **Step 10: Ler o relatório e registrar as verificações técnicas**

Criar `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md` preenchendo **com o que foi observado na execução**, não com o que este plano supôs:

```markdown
# Verificações técnicas do spike — 2026-09-19

Observado na execução real. Onde o plano supôs errado, o registro é o
valor real, não o suposto.

## Veredito

**<VERDE | AMARELO | VERMELHO>**

Se não for verde: onde o sinal morreu — mercado genuinamente seco, ou
guarda específica comendo tudo? A tabela "Motivos de reprovação" do
relatório responde.

## As sete verificações

| # | Item | Observado |
|---|---|---|
| 1 | Paginação de `/market/search/render`: parâmetros aceitos, `count` máximo real, `total_count` | |
| 2 | `currency=7` devolve BRL? Formato do `sell_price` e do `sell_price_text` | |
| 3 | Requisições até o primeiro 429; intervalo que se mostrou seguro | |
| 4 | Tamanho real do `IGetPrices/v4`; coube em memória? tempo de download | |
| 5 | `★ Unusual Effect:` e `( Not Usable in Crafting )` aparecem nas `descriptions` com `l=english`? | |
| 6 | Mapa `priceindex` → nome do efeito: quantos efeitos, e quantos casaram de fato | |
| 7 | Trade hold em item comprado na Market: existe? quantos dias? | |

> A verificação 7 não sai da execução — confirme na documentação da Steam
> ou comprando um item barato. Não deixe em branco: ela decide quanto tempo
> passa entre a compra e a realização do lucro em chaves.

## Hipótese da guarda 4

- Status: **<CONFIRMADA | REFUTADA>**
- Itens em USD na amostra:
- Desconto mediano:
- Fração perto de 15%:

Se refutada, a detecção de preço derivado fica em aberto. Alternativa
registrada no spec: cruzar contra a lista `/market` da própria backpack.tf.

## Qualidade do casamento de nomes

- Nomes na busca:
- Casados:
- Não casados:
- Taxa de casamento:

Os 10 padrões mais frequentes entre os não casados, e o que cada um
sugere de conserto no parser:

| Padrão | Ocorrências | Conserto sugerido |
|---|---|---|

## Recomendação

Uma ou duas frases: construir o projeto completo, construir a versão
reduzida, ou não construir — e por quê.
```

- [ ] **Step 11: Escrever o `README.md`**

````markdown
# tf2price

Spike de validação: mede uma vez o mercado de TF2 na Steam contra os preços
da backpack.tf e emite um veredito sobre construir ou não o app completo.

## Pré-requisitos

- Python 3.12+
- API key da backpack.tf: https://backpack.tf/developer/apikey/new
- Steam Web API key (só para gerar o mapa de efeitos): https://steamcommunity.com/dev/apikey

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env    # preencha as chaves
.venv/Scripts/python scripts/fetch_effects.py
```

## Uso

```bash
# ensaio rápido
.venv/Scripts/python -m tf2price.spike.run --max-pages 2 --deep-limit 3 --out out/ensaio

# execução completa (15 a 30 min)
.venv/Scripts/python -m tf2price.spike.run --out out
```

Saídas em `out/relatorio.md` e `out/oportunidades.csv`.

## Testes

```bash
.venv/Scripts/python -m pytest
```

Nenhum teste toca a rede.

## Documentos

- Spec: `docs/superpowers/specs/2026-09-19-tf2-arbitragem-spike-design.md`
- Plano: `docs/superpowers/plans/2026-09-19-tf2-arbitragem-spike.md`
- Verificações: `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`
````

- [ ] **Step 12: Commit final**

```bash
git add README.md docs/superpowers/findings
git commit -m "$(cat <<'MSG'
Registra o resultado da execução do spike

Veredito, as sete verificações técnicas contra dados reais, o status
da hipótese da guarda 4 e a taxa de casamento de nomes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B3rJkyFW2EpVJcWFKH4hUw
MSG
)"
```

---

## Cobertura do spec

| Seção do spec | Onde é implementada |
|---|---|
| §2.1-3 perguntas de mercado | Task 10 (`render_markdown`, faixas de 15/25/40%, bruto vs líquido) |
| §2.4 hipótese da guarda 4 | Task 10 (`analyse_market_derived`), Task 11 (`collect_usd_items`, registro) |
| §2.5 trade hold | Task 11 Step 10, verificação 7 |
| §2.6 rate limit real | Task 5 (contadores), Task 11 (relatório) |
| §3 câmbio pela chave da Steam | Task 1 (`Keys.to_brl`), Task 6 (`key_price`) |
| §3 conservadorismo | Task 4 (`evaluate` usa `value`), Task 6 (`converted_price + converted_fee`), Task 9 (garantida pelo pior valor) |
| §4 passada rasa completa | Task 6 (`search_page`), Task 11 (`_shallow_scan`) |
| §4 índice bp.tf | Task 7 |
| §4 avaliação dos não-Unusual pela rasa | Task 9 (`guaranteed_opportunities`) |
| §4 contagem de candidatas Unusual | Task 9 (`shallow_pass`), Task 10 (relatório) |
| §4 fetch profundo nos 20 melhores | Task 9 (`deep_targets`), Task 11 |
| §4 relatório Markdown + CSV | Task 10 |
| §5 arquitetura de módulos | Estrutura de arquivos deste plano |
| §5 regra das três vias | Task 3 |
| §5 fórmulas de cálculo | Task 4 |
| §6 guarda 1 (só candidatas) | Task 4 (`check_guards`), com teste de regressão |
| §6 guarda 2 (30 dias) | Task 4 |
| §6 guarda 3 (faixa 1,25x) | Task 4 |
| §6 guarda 4 (derivado da Steam) | Task 4 (detecção), Task 10 (teste da hipótese) |
| §7 sete verificações | Task 11 Step 10 |
| §8 critério de decisão | Task 10 (`decide`) |
| §9 testes de identidade | Task 2 (26 casos) |
| §9 testes de valuation | Task 4 |
| §9 teste de propriedade da poda | Task 3 |
| §9 fixtures sem rede | Tasks 6, 7, 8 |
| §10 riscos | Task 5 (backoff), Task 11 (ensaio antes da execução real, falha isolada no fetch profundo) |
| §12 pré-requisito da API key | Task 1 (`.env.example`), Task 11 (verificação no `main`) |

**Adiado conforme §11 do spec:** canal de alerta, modelo de dados, fetch profundo em escala, fila adaptativa. Nenhum aparece neste plano, e é assim que tem que ser.
