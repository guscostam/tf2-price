# Varredura de cosméticos Unusual — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Varrer periodicamente todas as listagens de cosméticos Unusual da Steam e mostrá-las numa página do painel. Cada listagem diz se comprá-la e trocá-la pelo valor da backpack.tf dá lucro.

**Architecture:** Novo pacote `tf2price/varredura/` com cinco partes. `escopo` decide o que é cosmético Unusual; `repositorio` concentra o SQL; `rodada` faz a passada rasa pela busca e a funda só onde a assinatura mudou, gravando o retrato e as listagens; `agendador` roda num thread de fundo com trava de rodada única; `leitura` é pura e cruza cada listagem com a bp.tf na hora. O painel ganha a rota `/scan` e uma seção em `/admin`.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 + HTMX 1.9.12, SQLAlchemy Core (SQLite nos testes, PostgreSQL em produção), pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-varredura-unusual-design.md`

## Global Constraints

- Leia `AGENTS.md` antes de começar. Valem todos os invariantes dele, e os abaixo são só os que esta feature toca mais.
- Nenhum import e nenhum teste acessa a rede. Os clientes, o relógio e o sono são injetados nos testes.
- Nenhuma conexão ou transação de banco fica aberta durante HTTP, espera de rate limit ou `sleep`.
- Dinheiro em `Brl` (centavos inteiros). Nunca `float` para quantia. Instantes em UTC ingênuo (`db.agora()`).
- O efeito faz parte da identidade: uma listagem sem preço na bp.tf **nunca** usa o preço de outro efeito.
- Todo número mostrado expõe a idade real (idade do preço da bp.tf e idade da leitura da listagem).
- A interface é em inglês. Nenhum texto em português chega à tela (há teste para isso em `tests/painel/test_english_ui.py`).
- Rotas mutáveis exigem `Depends(ses.mesma_origem)`.
- SQL só nos módulos `repositorio.py`. Sem `ON CONFLICT`/`MERGE`: use update-depois-insert, como em `preco/repositorio.py`.
- Intervalo mínimo entre rodadas: **60 min**. Idade máxima da leitura funda: mínimo **1 h**. Padrões: desligada, 180 min, 24 h.
- Comandos (PowerShell, na raiz do repositório):
  - teste focado: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_escopo.py -v`
  - suíte: `.\.venv\Scripts\python.exe -m pytest`
- Mensagem de commit em português, no estilo do `git log`, terminando com:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WstGxhhpa1wsEBwaCqjWJ1
  ```

## Decisões que refinam a spec

Estas decisões saíram da leitura do código durante o planejamento. A Task 10 as registra na spec.

1. **A assinatura usa o preço em centavos de dólar** (`sell_price` cru da busca), não em reais. A busca responde em USD, e o valor em reais depende da taxa derivada da chave, que muda entre processos. Com a assinatura em reais, cada deploy faria todos os nomes parecerem "mudados".
2. **`varredura_nome.n_guardadas`** guarda quantas listagens a funda gravou. "+N more on Steam" vem de `n_listagens − n_guardadas`.
3. **Remoção de nomes sumidos:** só depois de **duas** rodadas completas seguidas sem vê-los. A busca é ordenada por preço e leva ~15 min. Um item cujo preço muda no meio da rodada pode trocar de página e não ser visto uma vez sem ter saído do mercado.
4. **Preço da bp.tf mais velho que o filtro de idade:** a linha continua em "All listings", com o valor e a idade à mostra, mas sem resultado. O motivo aparece no lugar do resultado ("backpack.tf price is older than N days"), e a linha nunca entra em "Profitable".
5. **Espaço extra da varredura:** `ESPACO_EXTRA_S = 4.0`. Com o `RateLimiter` de 1 s, dá uma requisição a cada ~5 s. Nas medições de 2026-09-19, a Steam deu 429 na 128ª requisição a 1 s e cinco 429 em 389 a 3 s. Rodadas interrompidas não perdem trabalho, porque `funda_em` por nome faz a próxima pular o que já foi lido.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `tf2price/varredura/__init__.py` | pacote (vazio) |
| `tf2price/varredura/escopo.py` | o que é cosmético Unusual; extração dos nomes do schema |
| `tf2price/varredura/repositorio.py` | SQL de config, assinaturas, listagens e rodadas |
| `tf2price/varredura/rodada.py` | uma rodada: rasa → seleção → funda |
| `tf2price/varredura/agendador.py` | trava de rodada única, ciclo de fundo, montagem |
| `tf2price/varredura/leitura.py` | filtros, resultado por listagem, ordenação, paginação (puro) |
| `tf2price/data/cosmeticos.json` | nomes base dos cosméticos (gerado) |
| `scripts/fetch_cosmeticos.py` | gera o JSON acima a partir do schema da Valve |
| `tf2price/db.py` | 4 tabelas novas |
| `tf2price/sources/steam.py` | `SearchResult.sell_price_usd_cents` |
| `tf2price/preco/retrato.py` | `Retratos.em_calma()` e `Retratos.acalmar()` públicos |
| `tf2price/painel/varredura.py` | rota `GET /scan` |
| `tf2price/painel/templates/scan.html`, `_scan_estado.html`, `_scan_tabela.html` | página |
| `tf2price/painel/templates/_navigation.html` | link "Market Scan" |
| `tf2price/painel/admin.py`, `templates/admin.html` | seção de configuração e "Run now" |
| `tf2price/painel/app.py` | `criar_app(..., agendador=None)`, `preparar_varredura` |
| `tf2price/painel/static/briefcase.css` | estilos `.scan-*` |
| `tests/varredura/…`, `tests/painel/test_scan.py`, `tests/painel/test_admin_varredura.py` | testes |

---

### Task 1: Verificações ao vivo antes do código

Esta task mede o que a spec deixou em aberto (seção 9). Ela não produz código de produção, só um registro de achados. É a única task que usa a rede, e ela roda por um script no scratchpad, nunca por teste.

**Files:**
- Create: `docs/superpowers/findings/2026-09-22-varredura-verificacoes.md`

- [ ] **Step 1: Escrever o script de verificação no scratchpad (fora do repositório)**

Crie `$env:TEMP\verifica_pagina.py`:

```python
"""Verifica se a página do item aceita start/count e quantas listagens traz."""
import sys
import time
import urllib.parse

import httpx

from tf2price.sources.steam_page import PageStructureError, parse_item_page

NOMES = ["Unusual Team Captain", "Unusual Brigade Helm", "Unusual Killer Exclusive"]
URL = "https://steamcommunity.com/market/listings/440/"
CABECALHO = {"User-Agent": "tf2price/0.1"}

for nome in NOMES:
    for params in (
        {"l": "english", "currency": 7},
        {"l": "english", "currency": 7, "start": 0, "count": 100},
        {"l": "english", "currency": 7, "start": 10, "count": 10},
    ):
        r = httpx.get(URL + urllib.parse.quote(nome, safe=""),
                      params=params, headers=CABECALHO, timeout=20, follow_redirects=True)
        if r.status_code == 429:
            print("429 — pare e espere 5 minutos antes de tentar de novo")
            sys.exit(1)
        try:
            p = parse_item_page(r.text, nome, 5.5)
            ids = [l.listing_id for l in p.listings]
            print(nome, params, r.status_code, "listagens:", len(ids),
                  "sell_orders:", p.orderbook.sell_orders, "primeiros ids:", ids[:3])
        except PageStructureError as erro:
            print(nome, params, r.status_code, "PageStructureError:", erro)
        time.sleep(6)
```

- [ ] **Step 2: Rodar**

Run: `.\.venv\Scripts\python.exe $env:TEMP\verifica_pagina.py`

Se sair `429`, espere 5 minutos e rode de novo. **Não** reduza o `sleep`. O IP local já estava limitado em 2026-09-22 durante o planejamento.

- [ ] **Step 3: Registrar os achados**

Crie `docs/superpowers/findings/2026-09-22-varredura-verificacoes.md` com:

```markdown
# Verificações da varredura — 2026-09-22

| # | Pergunta | Observado |
|---|---|---|
| 1 | A página do item aceita `count=100`? | <sim/não: nº de listagens com e sem o parâmetro, e sell_orders> |
| 2 | Quantas listagens a página traz sem parâmetro? | <número> |
| 3 | `start=10&count=10` devolve outras listagens? | <sim/não: ids diferentes?> |

**Decisão para a Task 5:** <"executar: a página aceita count=100" ou "pular: a página ignora count; a tela mostra +N more on Steam">
```

Preencha com os números reais. A regra: se, para um item com `sell_orders` > 10, `count=100` trouxe mais listagens que a chamada sem parâmetro, a Task 5 **roda**. Caso contrário, a Task 5 é **pulada**.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/findings/2026-09-22-varredura-verificacoes.md
git commit -m "Registra as verificacoes ao vivo da pagina do item para a varredura"
```

---

### Task 2: Escopo — o que é cosmético Unusual

**Files:**
- Create: `tf2price/varredura/__init__.py` (vazio)
- Create: `tf2price/varredura/escopo.py`
- Create: `scripts/fetch_cosmeticos.py`
- Create: `tf2price/data/cosmeticos.json` (gerado pelo script)
- Create: `tests/varredura/__init__.py` (vazio)
- Test: `tests/varredura/test_escopo.py`

**Interfaces:**
- Produces:
  - `COSMETICOS_PATH: Path`
  - `SLOTS_DE_COSMETICO: frozenset[str]` = `{"head", "misc"}`
  - `nomes_de_cosmeticos(itens: list[dict]) -> list[str]` (ordenada, sem repetição)
  - `carregar_cosmeticos(path: Path = COSMETICOS_PATH) -> frozenset[str]` (com `lru_cache`)
  - `e_cosmetico_unusual(hash_name: str, cosmeticos: frozenset[str] | None = None) -> bool`

Por que o slot: no schema da Valve, **taunts também são `tf_wearable`** (slot `taunt`), e alguns itens de arma também são (Gunboats, Razorback: slot `secondary`). Só `head` e `misc` são cosméticos de verdade.

- [ ] **Step 1: Escrever os testes que falham**

`tests/varredura/test_escopo.py`:

```python
from __future__ import annotations

import pytest

from tf2price.varredura.escopo import (
    carregar_cosmeticos,
    e_cosmetico_unusual,
    nomes_de_cosmeticos,
)

COSMETICOS = frozenset({"Team Captain", "Brigade Helm", "Hot Case", "Bonk Boy"})


@pytest.mark.parametrize("nome", [
    "Unusual Team Captain",
    "Unusual Brigade Helm",
    "Unusual Hot Case",  # misc, não chapéu: entra
])
def test_aceita_cosmetico_unusual(nome):
    assert e_cosmetico_unusual(nome, COSMETICOS)


@pytest.mark.parametrize("nome", [
    "Unusual Taunt: Chairholder",                        # taunt
    "Strange Unusual Bonk Boy",                          # qualidade dupla
    "Unusual Strange Bonk Boy",                          # qualidade dupla, outra ordem
    "Unusual Professional Killstreak Rocket Launcher",   # arma
    "Unusual Sleighin' Style War Paint (Factory New)",   # war paint
    "Unusual Taunt: Chairholder Unusualifier",           # ferramenta
    "Team Captain",                                      # não é Unusual
    "Unusual Não Existe",                                # fora do schema
])
def test_recusa_o_que_nao_e_cosmetico_unusual(nome):
    assert not e_cosmetico_unusual(nome, COSMETICOS)


def test_nomes_de_cosmeticos_filtra_classe_e_slot():
    itens = [
        {"item_name": "Team Captain", "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Hot Case", "item_class": "tf_wearable", "item_slot": "misc"},
        {"item_name": "Taunt: Chairholder", "item_class": "tf_wearable", "item_slot": "taunt"},
        {"item_name": "Gunboats", "item_class": "tf_wearable", "item_slot": "secondary"},
        {"item_name": "Rocket Launcher", "item_class": "tf_weapon_rocketlauncher", "item_slot": "primary"},
        {"item_name": "Team Captain", "item_class": "tf_wearable", "item_slot": "head"},  # defindex repetido
    ]
    assert nomes_de_cosmeticos(itens) == ["Hot Case", "Team Captain"]


def test_arquivo_empacotado_tem_chapeus_e_nao_tem_taunts():
    cosmeticos = carregar_cosmeticos()
    assert "Team Captain" in cosmeticos
    assert "Brigade Helm" in cosmeticos
    assert "Taunt: Chairholder" not in cosmeticos
    assert len(cosmeticos) > 500
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_escopo.py -v`
Expected: FAIL (`ModuleNotFoundError: tf2price.varredura`)

- [ ] **Step 3: Implementar `escopo.py`**

`tf2price/varredura/escopo.py`:

```python
"""O que entra na varredura: cosméticos Unusual, e só eles.

Taunts, armas, war paints e Strange Unusual ficam de fora por decisão do
dono do projeto. O critério vem do schema da Valve (classe e slot do item),
e não de uma lista de exclusão por nome, que sempre deixaria algum escapar.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from tf2price.domain.identity import (
    QUALITY_PREFIXES,
    is_unusual_name,
    parse_market_hash_name,
)

COSMETICOS_PATH = Path(__file__).resolve().parent.parent / "data" / "cosmeticos.json"

# `tf_wearable` sozinho não basta: no schema, as provocações também são
# `tf_wearable` (slot `taunt`), e alguns itens de arma também (Gunboats,
# Razorback: slot `secondary`). Cosmético de verdade é cabeça ou misc.
SLOTS_DE_COSMETICO = frozenset({"head", "misc"})

_QUALIDADE_UNUSUAL = QUALITY_PREFIXES["Unusual"]


def nomes_de_cosmeticos(itens: Iterable[dict[str, Any]]) -> list[str]:
    """Nomes base dos cosméticos no schema, ordenados e sem repetição.

    O mesmo nome aparece em vários defindex (versões promocionais, de
    ferramenta), e o que casa com o nome da Steam é `item_name`.
    """
    return sorted({
        str(item["item_name"])
        for item in itens
        if item.get("item_class") == "tf_wearable"
        and item.get("item_slot") in SLOTS_DE_COSMETICO
        and item.get("item_name")
    })


@lru_cache(maxsize=4)
def carregar_cosmeticos(path: Path = COSMETICOS_PATH) -> frozenset[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"cosmeticos.json não encontrado em {path}. "
            "Rode: .venv/Scripts/python scripts/fetch_cosmeticos.py"
        )
    return frozenset(json.loads(path.read_text(encoding="utf-8")))


def e_cosmetico_unusual(hash_name: str, cosmeticos: frozenset[str] | None = None) -> bool:
    if not is_unusual_name(hash_name):
        return False
    ident = parse_market_hash_name(hash_name)
    # Qualidade dupla: o parser consome um prefixo só. `Strange Unusual X`
    # sai com qualidade Strange; `Unusual Strange X` sai com base `Strange X`.
    if ident.quality_id != _QUALIDADE_UNUSUAL:
        return False
    if ident.killstreak or ident.australium or ident.festivized or ident.wear:
        return False
    if ident.base_name.startswith(("Taunt:", "Unusual ", "Strange ")):
        return False
    conjunto = carregar_cosmeticos() if cosmeticos is None else cosmeticos
    return ident.base_name in conjunto
```

- [ ] **Step 4: Escrever o script gerador**

`scripts/fetch_cosmeticos.py`:

```python
"""Gera tf2price/data/cosmeticos.json a partir do schema oficial do TF2.

Roda quando o TF2 ganha cosméticos novos. Precisa de STEAM_API_KEY (grátis em
https://steamcommunity.com/dev/apikey).

    .venv/Scripts/python scripts/fetch_cosmeticos.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from tf2price.varredura.escopo import COSMETICOS_PATH, nomes_de_cosmeticos

SCHEMA_ITEMS_URL = "https://api.steampowered.com/IEconItems_440/GetSchemaItems/v0001/"


def main() -> int:
    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    if not api_key:
        print("STEAM_API_KEY não configurada. Veja .env.example.", file=sys.stderr)
        return 1

    itens: list[dict] = []
    inicio: int | None = 0
    while inicio is not None:
        resposta = httpx.get(
            SCHEMA_ITEMS_URL,
            params={"key": api_key, "language": "en", "start": inicio},
            timeout=60.0,
        )
        resposta.raise_for_status()
        resultado = resposta.json()["result"]
        itens.extend(resultado.get("items") or [])
        inicio = resultado.get("next")
        if inicio is not None:
            time.sleep(1.0)

    nomes = nomes_de_cosmeticos(itens)
    destino = Path(COSMETICOS_PATH)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(nomes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(itens)} itens lidos, {len(nomes)} cosméticos gravados em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Gerar o arquivo**

Run: `.\.venv\Scripts\python.exe scripts\fetch_cosmeticos.py`
Expected: `NNNNN itens lidos, NNNN cosméticos gravados em ...cosmeticos.json`, com mais de 500 cosméticos.

Se `STEAM_API_KEY` não estiver no `.env`, **pare e peça ao usuário**. Não invente a lista.

Depois confira à mão: `Select-String -Path tf2price\data\cosmeticos.json -Pattern '"Team Captain"','"Taunt:'`. Deve achar `Team Captain` e **nenhum** `Taunt:`.

- [ ] **Step 6: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_escopo.py -v`
Expected: PASS (todos)

- [ ] **Step 7: Commit**

```bash
git add tf2price/varredura/__init__.py tf2price/varredura/escopo.py scripts/fetch_cosmeticos.py tf2price/data/cosmeticos.json tests/varredura/__init__.py tests/varredura/test_escopo.py
git commit -m "Define o escopo da varredura: cosmeticos Unusual pelo schema da Valve"
```

---

### Task 3: Tabelas e repositório da varredura

**Files:**
- Modify: `tf2price/db.py` (depois da tabela `pedido_acesso`)
- Create: `tf2price/varredura/repositorio.py`
- Test: `tests/varredura/test_repositorio.py`

**Interfaces:**
- Produces (em `tf2price.varredura.repositorio`, importado como `repo`):
  - `MOTIVO_OK = "ok"`, `MOTIVO_429 = "429"`, `MOTIVO_ERRO = "erro"`, `MOTIVO_INTERROMPIDA = "interrompida"`
  - `INTERVALO_MINIMO_MIN = 60`, `IDADE_MINIMA_FUNDA_H = 1`
  - `Config(ligada: bool, intervalo_min: int, idade_max_funda_h: int)`, `PADRAO = Config(False, 180, 24)`
  - `ler_config(conn) -> Config`; `gravar_config(conn, config: Config, quando) -> None` (levanta `ValueError` abaixo do mínimo)
  - `Assinatura(preco_usd_cents: int, n_listagens: int, funda_em: datetime | None)`
  - `ler_assinatura(conn, hash_name) -> Assinatura | None`
  - `gravar_vista(conn, hash_name, preco_usd_cents, n_listagens, quando) -> None`
  - `substituir_listagens(conn, hash_name, listagens: list[PageListing], quando) -> None`
  - `apagar_nao_vistos_desde(conn, limite: datetime) -> int`
  - `Rodada(id, inicio, fim, nomes_lidos, fundas_feitas, falhas, motivo_parada)`
  - `abrir_rodada(conn, quando) -> int`; `atualizar_progresso(conn, rodada_id, *, nomes_lidos, fundas_feitas, falhas)`; `fechar_rodada(conn, rodada_id, quando, *, nomes_lidos, fundas_feitas, falhas, motivo)`; `fechar_abertas(conn, quando) -> int`; `ultimas_rodadas(conn, n=10) -> list[Rodada]`; `ultima_rodada(conn) -> Rodada | None`; `ultima_completa(conn) -> Rodada | None`
  - `ListagemVarrida(listing_id, hash_name, efeito: str | None, preco: Brl, icone: str | None, lido_em, mais_na_steam: int)`
  - `listar_listagens(conn, *, texto="", efeito="", preco_min: Brl | None = None, preco_max: Brl | None = None) -> list[ListagemVarrida]`
  - `efeitos_varridos(conn) -> list[str]`
  - `Cobertura(nomes: int, listagens: int)`; `cobertura(conn) -> Cobertura`

- [ ] **Step 1: Escrever os testes que falham**

`tests/varredura/test_repositorio.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.sources.steam_page import PageListing
from tf2price.varredura import repositorio as repo

T0 = db.agora()


def _l(ident, centavos, efeito="Burning Flames"):
    return PageListing(ident, Brl(centavos), efeito, None)


def test_config_padrao_quando_nada_foi_gravado(engine):
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.PADRAO
    assert repo.PADRAO == repo.Config(ligada=False, intervalo_min=180, idade_max_funda_h=24)


def test_config_grava_e_regrava(engine):
    with engine.begin() as conn:
        repo.gravar_config(conn, repo.Config(True, 60, 6), T0)
        repo.gravar_config(conn, repo.Config(True, 120, 12), T0)
        assert repo.ler_config(conn) == repo.Config(True, 120, 12)


@pytest.mark.parametrize("config", [repo.Config(True, 59, 24), repo.Config(True, 60, 0)])
def test_config_abaixo_do_minimo_e_recusada(engine, config):
    with engine.begin() as conn, pytest.raises(ValueError):
        repo.gravar_config(conn, config, T0)


def test_assinatura_nova_nasce_sem_funda(engine):
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual Team Captain") is None
        repo.gravar_vista(conn, "Unusual Team Captain", 89000, 7, T0)
        assert repo.ler_assinatura(conn, "Unusual Team Captain") == repo.Assinatura(89000, 7, None)


def test_gravar_vista_nao_apaga_a_funda(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500)], T0)
        repo.gravar_vista(conn, "X", 200, 2, T0 + timedelta(hours=1))
        assert repo.ler_assinatura(conn, "X") == repo.Assinatura(200, 2, T0)


def test_substituir_troca_todas_as_listagens_do_nome(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 2, T0)
        repo.gravar_vista(conn, "Y", 100, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500), _l("2", 700)], T0)
        repo.substituir_listagens(conn, "Y", [_l("9", 900)], T0)
        repo.substituir_listagens(conn, "X", [_l("2", 650)], T0 + timedelta(hours=1))
        linhas = repo.listar_listagens(conn)
    assert [(l.hash_name, l.listing_id, l.preco) for l in linhas] == [
        ("X", "2", Brl(650)),
        ("Y", "9", Brl(900)),
    ]


def test_substituir_ignora_listagem_sem_id_e_repetida(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 3, T0)
        repo.substituir_listagens(conn, "X", [_l("", 1), _l("1", 500), _l("1", 500)], T0)
        assert [l.listing_id for l in repo.listar_listagens(conn)] == ["1"]


def test_mais_na_steam_e_o_que_a_busca_viu_menos_o_que_foi_gravado(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 12, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500), _l("2", 600)], T0)
        assert {l.mais_na_steam for l in repo.listar_listagens(conn)} == {10}


def test_listar_filtra_por_texto_efeito_e_preco(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "Unusual Team Captain", 1, 2, T0)
        repo.gravar_vista(conn, "Unusual Brigade Helm", 1, 1, T0)
        repo.substituir_listagens(conn, "Unusual Team Captain",
                                  [_l("1", 500), _l("2", 900, "Sunbeams")], T0)
        repo.substituir_listagens(conn, "Unusual Brigade Helm", [_l("3", 700)], T0)

        assert {l.listing_id for l in repo.listar_listagens(conn, texto="team CAP")} == {"1", "2"}
        assert {l.listing_id for l in repo.listar_listagens(conn, efeito="Sunbeams")} == {"2"}
        assert {l.listing_id for l in repo.listar_listagens(
            conn, preco_min=Brl(600), preco_max=Brl(800))} == {"3"}
        # `%` e `_` são texto, não curinga
        assert repo.listar_listagens(conn, texto="%") == []
        assert repo.efeitos_varridos(conn) == ["Burning Flames", "Sunbeams"]


def test_apagar_nao_vistos_desde_remove_nome_e_listagens(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "Velho", 1, 1, T0)
        repo.substituir_listagens(conn, "Velho", [_l("1", 500)], T0)
        repo.gravar_vista(conn, "Novo", 1, 1, T0 + timedelta(hours=2))
        repo.substituir_listagens(conn, "Novo", [_l("2", 500)], T0 + timedelta(hours=2))

        assert repo.apagar_nao_vistos_desde(conn, T0 + timedelta(hours=1)) == 1
        assert [l.hash_name for l in repo.listar_listagens(conn)] == ["Novo"]
        assert repo.ler_assinatura(conn, "Velho") is None


def test_rodadas_abrir_progredir_fechar(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, T0)
        repo.atualizar_progresso(conn, rid, nomes_lidos=5, fundas_feitas=2, falhas=0)
        em_curso = repo.ultima_rodada(conn)
        assert (em_curso.fim, em_curso.nomes_lidos, em_curso.motivo_parada) == (None, 5, None)

        repo.fechar_rodada(conn, rid, T0 + timedelta(minutes=9),
                           nomes_lidos=7, fundas_feitas=3, falhas=1, motivo=repo.MOTIVO_OK)
        fechada = repo.ultima_completa(conn)
        assert (fechada.id, fechada.fundas_feitas, fechada.falhas) == (rid, 3, 1)


def test_ultima_completa_ignora_rodada_parada_por_429(engine):
    with engine.begin() as conn:
        ok = repo.abrir_rodada(conn, T0)
        repo.fechar_rodada(conn, ok, T0, nomes_lidos=1, fundas_feitas=1, falhas=0, motivo=repo.MOTIVO_OK)
        parada = repo.abrir_rodada(conn, T0 + timedelta(hours=1))
        repo.fechar_rodada(conn, parada, T0 + timedelta(hours=1),
                           nomes_lidos=1, fundas_feitas=0, falhas=0, motivo=repo.MOTIVO_429)
        assert repo.ultima_rodada(conn).id == parada
        assert repo.ultima_completa(conn).id == ok


def test_fechar_abertas_marca_interrompida(engine):
    with engine.begin() as conn:
        aberta = repo.abrir_rodada(conn, T0)
        assert repo.fechar_abertas(conn, T0 + timedelta(minutes=1)) == 1
        rodada = repo.ultima_rodada(conn)
        assert (rodada.id, rodada.motivo_parada) == (aberta, repo.MOTIVO_INTERROMPIDA)
        assert repo.fechar_abertas(conn, T0) == 0


def test_cobertura_conta_nomes_lidos_a_fundo_e_listagens(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 1, 2, T0)
        repo.gravar_vista(conn, "So vista", 1, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 1), _l("2", 2)], T0)
        assert repo.cobertura(conn) == repo.Cobertura(nomes=1, listagens=2)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_repositorio.py -v`
Expected: FAIL (`ImportError` / `AttributeError: module 'tf2price.db' has no attribute 'varredura_config'`)

- [ ] **Step 3: Adicionar as tabelas em `tf2price/db.py`**

Acrescente depois da tabela `pedido_acesso` (antes de `url_do_ambiente`):

```python
varredura_config = Table(
    "varredura_config",
    METADATA,
    # Uma linha só, id 1, como a cotação: a configuração é global.
    Column("id", Integer, primary_key=True),
    Column("ligada", Boolean, nullable=False),
    Column("intervalo_min", Integer, nullable=False),
    Column("idade_max_funda_h", Integer, nullable=False),
    Column("alterado_em", DateTime, nullable=False),
)

varredura_nome = Table(
    "varredura_nome",
    METADATA,
    Column("hash_name", String(300), primary_key=True),
    # A assinatura é o preço CRU da busca, em centavos de dólar. Em reais ela
    # dependeria da taxa derivada da chave, que muda entre processos, e cada
    # deploy faria o mercado inteiro parecer "mudado".
    Column("preco_usd_cents", Integer, nullable=False),
    Column("n_listagens", Integer, nullable=False),
    # Quantas listagens a última leitura funda gravou. A diferença para
    # `n_listagens` é o "+N more on Steam" da tela.
    Column("n_guardadas", Integer, nullable=False, default=0),
    Column("visto_em", DateTime, nullable=False),
    Column("funda_em", DateTime, nullable=True),
)

listagem_varrida = Table(
    "listagem_varrida",
    METADATA,
    Column("listing_id", String(40), primary_key=True),
    Column("hash_name", String(300), nullable=False, index=True),
    # Nulo quando a Steam não informou o efeito: essa linha não tem preço.
    Column("efeito", String(120), nullable=True),
    Column("preco_cents", Integer, nullable=False),
    Column("icone", String(500), nullable=True),
    Column("lido_em", DateTime, nullable=False),
)

varredura_rodada = Table(
    "varredura_rodada",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("inicio", DateTime, nullable=False),
    Column("fim", DateTime, nullable=True),
    Column("nomes_lidos", Integer, nullable=False, default=0),
    Column("fundas_feitas", Integer, nullable=False, default=0),
    Column("falhas", Integer, nullable=False, default=0),
    # ok, 429, erro, interrompida; nulo enquanto roda.
    Column("motivo_parada", String(20), nullable=True),
)
```

`db.criar_schema` usa `METADATA.create_all`, que cria tabelas novas num banco existente sem mexer nas antigas. Não há migração a escrever.

- [ ] **Step 4: Implementar `tf2price/varredura/repositorio.py`**

```python
"""SQL da varredura: configuração, assinaturas, listagens e rodadas.

Só a varredura escreve em `varredura_nome` e `listagem_varrida`, e nunca há
duas rodadas ao mesmo tempo (trava em `agendador.py`). Por isso os upserts
daqui não precisam do savepoint de `preco/repositorio.py`. A configuração é
a exceção: dois admins podem salvar juntos, e ela usa o savepoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.sources.steam_page import PageListing

MOTIVO_OK = "ok"
MOTIVO_429 = "429"
MOTIVO_ERRO = "erro"
MOTIVO_INTERROMPIDA = "interrompida"

INTERVALO_MINIMO_MIN = 60
IDADE_MINIMA_FUNDA_H = 1
LINHA_DA_CONFIG = 1


# --- configuração -----------------------------------------------------------

@dataclass(frozen=True)
class Config:
    ligada: bool
    intervalo_min: int
    idade_max_funda_h: int


PADRAO = Config(ligada=False, intervalo_min=180, idade_max_funda_h=24)


def ler_config(conn: Connection) -> Config:
    t = db.varredura_config
    linha = conn.execute(select(t).where(t.c.id == LINHA_DA_CONFIG)).first()
    if linha is None:
        return PADRAO
    return Config(bool(linha.ligada), int(linha.intervalo_min), int(linha.idade_max_funda_h))


def _atualizar_config(conn: Connection, config: Config, quando: datetime):
    t = db.varredura_config
    return conn.execute(
        update(t).where(t.c.id == LINHA_DA_CONFIG).values(
            ligada=config.ligada,
            intervalo_min=config.intervalo_min,
            idade_max_funda_h=config.idade_max_funda_h,
            alterado_em=quando,
        )
    )


def gravar_config(conn: Connection, config: Config, quando: datetime) -> None:
    """Recusa abaixo do mínimo aqui também, e não só na rota: o mínimo existe
    para proteger a consulta do 429, e uma segunda porta de escrita não pode
    contorná-lo."""
    if config.intervalo_min < INTERVALO_MINIMO_MIN:
        raise ValueError(f"intervalo abaixo de {INTERVALO_MINIMO_MIN} min")
    if config.idade_max_funda_h < IDADE_MINIMA_FUNDA_H:
        raise ValueError(f"idade da leitura funda abaixo de {IDADE_MINIMA_FUNDA_H} h")
    if _atualizar_config(conn, config, quando).rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(insert(db.varredura_config).values(
                    id=LINHA_DA_CONFIG,
                    ligada=config.ligada,
                    intervalo_min=config.intervalo_min,
                    idade_max_funda_h=config.idade_max_funda_h,
                    alterado_em=quando,
                ))
        except IntegrityError:
            _atualizar_config(conn, config, quando)


# --- assinaturas ------------------------------------------------------------

@dataclass(frozen=True)
class Assinatura:
    preco_usd_cents: int
    n_listagens: int
    funda_em: datetime | None


def ler_assinatura(conn: Connection, hash_name: str) -> Assinatura | None:
    t = db.varredura_nome
    linha = conn.execute(
        select(t.c.preco_usd_cents, t.c.n_listagens, t.c.funda_em).where(t.c.hash_name == hash_name)
    ).first()
    if linha is None:
        return None
    return Assinatura(int(linha.preco_usd_cents), int(linha.n_listagens), linha.funda_em)


def gravar_vista(
    conn: Connection, hash_name: str, preco_usd_cents: int, n_listagens: int, quando: datetime
) -> None:
    """Grava o que a passada rasa viu. Não toca `funda_em`: ter visto o nome na
    busca não é ter lido as listagens dele."""
    t = db.varredura_nome
    resultado = conn.execute(
        update(t).where(t.c.hash_name == hash_name).values(
            preco_usd_cents=preco_usd_cents, n_listagens=n_listagens, visto_em=quando
        )
    )
    if resultado.rowcount == 0:
        conn.execute(insert(t).values(
            hash_name=hash_name,
            preco_usd_cents=preco_usd_cents,
            n_listagens=n_listagens,
            n_guardadas=0,
            visto_em=quando,
            funda_em=None,
        ))


def substituir_listagens(
    conn: Connection, hash_name: str, listagens: list[PageListing], quando: datetime
) -> None:
    """Troca TODAS as listagens do nome pelas da leitura nova.

    Listagem vendida ou retirada some junto: nunca fica na tela uma listagem
    que a última leitura não viu.
    """
    t = db.listagem_varrida
    conn.execute(delete(t).where(t.c.hash_name == hash_name))
    vistas: set[str] = set()
    linhas = []
    for l in listagens:
        if not l.listing_id or l.listing_id in vistas:
            continue
        vistas.add(l.listing_id)
        linhas.append({
            "listing_id": l.listing_id,
            "hash_name": hash_name,
            "efeito": l.effect,
            "preco_cents": l.total_price.cents,
            "icone": l.icon_url,
            "lido_em": quando,
        })
    if linhas:
        conn.execute(insert(t), linhas)
    n = db.varredura_nome
    conn.execute(
        update(n).where(n.c.hash_name == hash_name).values(funda_em=quando, n_guardadas=len(linhas))
    )


def apagar_nao_vistos_desde(conn: Connection, limite: datetime) -> int:
    """Apaga nomes (e suas listagens) que a busca não viu desde `limite`."""
    n = db.varredura_nome
    sumidos = select(n.c.hash_name).where(n.c.visto_em < limite)
    conn.execute(delete(db.listagem_varrida).where(db.listagem_varrida.c.hash_name.in_(sumidos)))
    return conn.execute(delete(n).where(n.c.visto_em < limite)).rowcount


# --- rodadas ----------------------------------------------------------------

@dataclass(frozen=True)
class Rodada:
    id: int
    inicio: datetime
    fim: datetime | None
    nomes_lidos: int
    fundas_feitas: int
    falhas: int
    motivo_parada: str | None


def _rodada(linha) -> Rodada:
    return Rodada(
        id=int(linha.id),
        inicio=linha.inicio,
        fim=linha.fim,
        nomes_lidos=int(linha.nomes_lidos),
        fundas_feitas=int(linha.fundas_feitas),
        falhas=int(linha.falhas),
        motivo_parada=linha.motivo_parada,
    )


def abrir_rodada(conn: Connection, quando: datetime) -> int:
    resultado = conn.execute(insert(db.varredura_rodada).values(
        inicio=quando, nomes_lidos=0, fundas_feitas=0, falhas=0
    ))
    return int(resultado.inserted_primary_key[0])


def atualizar_progresso(
    conn: Connection, rodada_id: int, *, nomes_lidos: int, fundas_feitas: int, falhas: int
) -> None:
    t = db.varredura_rodada
    conn.execute(update(t).where(t.c.id == rodada_id).values(
        nomes_lidos=nomes_lidos, fundas_feitas=fundas_feitas, falhas=falhas
    ))


def fechar_rodada(
    conn: Connection, rodada_id: int, quando: datetime, *,
    nomes_lidos: int, fundas_feitas: int, falhas: int, motivo: str,
) -> None:
    t = db.varredura_rodada
    conn.execute(update(t).where(t.c.id == rodada_id).values(
        fim=quando, nomes_lidos=nomes_lidos, fundas_feitas=fundas_feitas,
        falhas=falhas, motivo_parada=motivo,
    ))


def fechar_abertas(conn: Connection, quando: datetime) -> int:
    """Na subida: rodada sem fim é de um processo que morreu no meio dela."""
    t = db.varredura_rodada
    return conn.execute(
        update(t).where(t.c.fim.is_(None)).values(fim=quando, motivo_parada=MOTIVO_INTERROMPIDA)
    ).rowcount


def ultimas_rodadas(conn: Connection, n: int = 10) -> list[Rodada]:
    t = db.varredura_rodada
    return [_rodada(l) for l in conn.execute(
        select(t).order_by(t.c.inicio.desc(), t.c.id.desc()).limit(n)
    )]


def ultima_rodada(conn: Connection) -> Rodada | None:
    rodadas = ultimas_rodadas(conn, 1)
    return rodadas[0] if rodadas else None


def ultima_completa(conn: Connection) -> Rodada | None:
    t = db.varredura_rodada
    linha = conn.execute(
        select(t).where(t.c.motivo_parada == MOTIVO_OK)
        .order_by(t.c.inicio.desc(), t.c.id.desc()).limit(1)
    ).first()
    return _rodada(linha) if linha else None


# --- leitura para a página --------------------------------------------------

@dataclass(frozen=True)
class ListagemVarrida:
    listing_id: str
    hash_name: str
    efeito: str | None
    preco: Brl
    icone: str | None
    lido_em: datetime
    mais_na_steam: int


def listar_listagens(
    conn: Connection, *, texto: str = "", efeito: str = "",
    preco_min: Brl | None = None, preco_max: Brl | None = None,
) -> list[ListagemVarrida]:
    l = db.listagem_varrida
    n = db.varredura_nome
    consulta = select(
        l, (n.c.n_listagens - n.c.n_guardadas).label("mais_na_steam")
    ).select_from(l.join(n, l.c.hash_name == n.c.hash_name))
    if texto.strip():
        consulta = consulta.where(
            func.lower(l.c.hash_name).contains(texto.strip().lower(), autoescape=True)
        )
    if efeito:
        consulta = consulta.where(l.c.efeito == efeito)
    if preco_min is not None:
        consulta = consulta.where(l.c.preco_cents >= preco_min.cents)
    if preco_max is not None:
        consulta = consulta.where(l.c.preco_cents <= preco_max.cents)
    consulta = consulta.order_by(l.c.hash_name, l.c.preco_cents, l.c.listing_id)
    return [
        ListagemVarrida(
            listing_id=linha.listing_id,
            hash_name=linha.hash_name,
            efeito=linha.efeito,
            preco=Brl(int(linha.preco_cents)),
            icone=linha.icone,
            lido_em=linha.lido_em,
            mais_na_steam=max(0, int(linha.mais_na_steam)),
        )
        for linha in conn.execute(consulta)
    ]


def efeitos_varridos(conn: Connection) -> list[str]:
    l = db.listagem_varrida
    return [e for (e,) in conn.execute(
        select(l.c.efeito).where(l.c.efeito.is_not(None)).distinct().order_by(l.c.efeito)
    )]


@dataclass(frozen=True)
class Cobertura:
    nomes: int
    listagens: int


def cobertura(conn: Connection) -> Cobertura:
    n = db.varredura_nome
    nomes = conn.execute(select(func.count()).select_from(n).where(n.c.funda_em.is_not(None))).scalar_one()
    listagens = conn.execute(select(func.count()).select_from(db.listagem_varrida)).scalar_one()
    return Cobertura(nomes=int(nomes), listagens=int(listagens))
```

- [ ] **Step 5: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_repositorio.py tests\test_db.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tf2price/db.py tf2price/varredura/repositorio.py tests/varredura/test_repositorio.py
git commit -m "Cria as tabelas e o repositorio da varredura de cosmeticos"
```

---

### Task 4: Peças emprestadas — preço cru da busca e calma pública do retrato

**Files:**
- Modify: `tf2price/sources/steam.py` (`SearchResult` e `parse_search_page`)
- Modify: `tf2price/preco/retrato.py` (`Retratos`)
- Test: `tests/sources/test_steam.py`, `tests/preco/test_retrato.py`

**Interfaces:**
- Produces:
  - `SearchResult.sell_price_usd_cents: int = 0` (último campo, com default: `tests/painel/conftest.py` constrói `SearchResult` sem ele)
  - `Retratos.em_calma() -> bool`
  - `Retratos.acalmar() -> None` (liga a mesma calma de 5 min que um 429 na página liga)

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/sources/test_steam.py`:

```python
def test_parse_search_page_guarda_o_preco_cru_em_centavos_de_dolar():
    # A assinatura da varredura precisa do número que a Steam mandou, antes
    # da taxa: em reais, ele mudaria a cada processo novo.
    page = parse_search_page(_fixture("steam_search_page.json"), TAXA_REDONDA)
    assert [r.sell_price_usd_cents for r in page.results] == [2214, 89000, 15990]
```

Acrescente a `tests/preco/test_retrato.py`:

```python
def test_acalmar_por_fora_liga_a_mesma_calma_do_429(engine):
    relogio = _Relogio()
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=relogio)
    assert not retratos.em_calma()

    retratos.acalmar()

    assert retratos.em_calma()
    leitura = retratos.obter(engine, NOME, 1.0, AGORA)
    assert paginas.chamadas == 0
    assert leitura.limitando
    relogio.avancar(mod.CALMA_APOS_429.total_seconds() + 1)
    assert not retratos.em_calma()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_steam.py tests\preco\test_retrato.py -v`
Expected: FAIL (`AttributeError: 'SearchResult' object has no attribute 'sell_price_usd_cents'`, `'Retratos' object has no attribute 'em_calma'`)

- [ ] **Step 3: Implementar**

Em `tf2price/sources/steam.py`, troque `SearchResult` por:

```python
@dataclass(frozen=True)
class SearchResult:
    hash_name: str
    lowest_price: Brl
    sell_listings: int
    # `sell_price` como a busca mandou, em centavos de dólar, antes da taxa.
    # A varredura compara este número entre rodadas; `lowest_price` depende
    # da taxa do processo e mudaria sozinho a cada deploy.
    sell_price_usd_cents: int = 0
```

E, em `parse_search_page`, construa cada resultado assim:

```python
        SearchResult(
            hash_name=row["hash_name"],
            # Arredonda uma única vez, na conversão: centavos de dólar *
            # taxa -> centavos de real.
            lowest_price=Brl.from_cents(round(int(row["sell_price"]) * usd_to_brl)),
            sell_listings=int(row["sell_listings"]),
            sell_price_usd_cents=int(row["sell_price"]),
        )
```

Em `tf2price/preco/retrato.py`, dentro de `Retratos.obter`, troque a linha
`self._calma_ate = self._relogio() + CALMA_APOS_429.total_seconds()` por `self.acalmar()`.
Depois troque o método `_em_calma` por estes dois métodos públicos, e renomeie as chamadas internas de `self._em_calma()` para `self.em_calma()`:

```python
    def em_calma(self) -> bool:
        return self._relogio() < self._calma_ate

    def acalmar(self) -> None:
        """Liga a calma por fora. A varredura chama isto quando a BUSCA da
        Steam (não a página) responde 429: é o mesmo IP, e a consulta que
        viesse logo depois bateria no mesmo limite."""
        self._calma_ate = self._relogio() + CALMA_APOS_429.total_seconds()
```

Confira que nada mais usa o nome antigo: `Select-String -Path tf2price,tests -Pattern "_em_calma" -Recurse` não deve achar nada.

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources tests\preco tests\painel -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/sources/steam.py tf2price/preco/retrato.py tests/sources/test_steam.py tests/preco/test_retrato.py
git commit -m "Expoe o preco cru da busca e a calma do retrato para a varredura"
```

---

### Task 5 (CONDICIONAL): página do item com até 100 listagens

**Execute só se o registro da Task 1 disser "executar".** Se disser "pular", marque os passos como pulados e siga para a Task 6. O "+N more on Steam" (Task 3) cobre o caso sem paginação.

**Files:**
- Modify: `tf2price/sources/steam_page.py` (`SteamPageClient.item_page`)
- Test: `tests/sources/test_steam_page.py`

**Interfaces:**
- Produces: `LISTAGENS_POR_PAGINA = 100` em `steam_page.py`, e `item_page` passa a enviar `count=LISTAGENS_POR_PAGINA`, sem mudar a assinatura.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/sources/test_steam_page.py`:

```python
def test_item_page_pede_ate_100_listagens():
    import httpx

    from tf2price.sources.ratelimit import RateLimiter
    from tf2price.sources.steam_page import LISTAGENS_POR_PAGINA, SteamPageClient

    html = (Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html").read_text(encoding="utf-8")
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, text=html)

    cliente = SteamPageClient(
        RateLimiter(min_interval_s=0),
        client=httpx.Client(transport=httpx.MockTransport(responder)),
    )
    cliente.item_page("Unusual Taunt: Chairholder", 1.0)

    assert LISTAGENS_POR_PAGINA == 100
    assert pedidos[0].url.params["count"] == "100"
    assert pedidos[0].url.params["start"] == "0"
```

(Se `Path` ainda não estiver importado no arquivo, acrescente `from pathlib import Path` no topo.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources\test_steam_page.py -v`
Expected: FAIL (`ImportError: cannot import name 'LISTAGENS_POR_PAGINA'`)

- [ ] **Step 3: Implementar**

Em `tf2price/sources/steam_page.py`, perto das outras constantes do topo:

```python
# Medido em 2026-09-22 (docs/superpowers/findings/2026-09-22-varredura-verificacoes.md):
# sem `count`, a página traz só a primeira dezena de listagens. Com ele, uma
# requisição traz todas de quase todo Unusual — e a varredura não precisa
# paginar.
LISTAGENS_POR_PAGINA = 100
```

E em `item_page`, troque `params = {"currency": CURRENCY_BRL, "l": "english"}` por:

```python
        params = {
            "currency": CURRENCY_BRL,
            "l": "english",
            "start": 0,
            "count": LISTAGENS_POR_PAGINA,
        }
```

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources tests\lookup tests\painel -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/sources/steam_page.py tests/sources/test_steam_page.py
git commit -m "Pede ate 100 listagens na pagina do item"
```

---

### Task 6: A rodada

**Files:**
- Create: `tf2price/varredura/rodada.py`
- Test: `tests/varredura/test_rodada.py`

**Interfaces:**
- Consumes: `repo.*` (Task 3), `e_cosmetico_unusual` (Task 2), `SearchResult.sell_price_usd_cents`, `Retratos.em_calma/acalmar/obter` (Task 4), `cotacao.obter(engine) -> objeto com .usd_to_brl | None`
- Produces:
  - `QUERY = "Unusual"`, `ESPACO_EXTRA_S = 4.0`, `MAX_PAGINAS_RASAS = 400`
  - `Resumo(nomes_lidos=0, fundas_feitas=0, falhas=0, motivo=repo.MOTIVO_OK)` (dataclass mutável)
  - `executar_rodada(engine, *, steam, retratos, cotacao, agora=db.agora, dormir=time.sleep, aceitar=e_cosmetico_unusual, espaco_extra_s=ESPACO_EXTRA_S) -> Resumo`

- [ ] **Step 1: Escrever os testes que falham**

`tests/varredura/test_rodada.py`:

```python
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import event

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.preco.retrato import Leitura
from tf2price.sources.ratelimit import SteamLimitando
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, PageStructureError
from tf2price.varredura import repositorio as repo
from tf2price.varredura.rodada import ESPACO_EXTRA_S, QUERY, executar_rodada

T0 = db.agora()


def _aceitar(nome: str) -> bool:
    return nome.startswith("Unusual ") and "Taunt" not in nome


def _r(nome, usd=1000, n=1):
    return SearchResult(hash_name=nome, lowest_price=Brl(usd * 5), sell_listings=n,
                        sell_price_usd_cents=usd)


def _pagina(nome, *listagens):
    return ItemPage(
        hash_name=nome,
        listings=[PageListing(i, Brl(c), e, None) for i, c, e in listagens],
        orderbook=OrderBook(None, None, 0, 0),
        history=[],
    )


class _Steam:
    """Busca falsa: fatia a lista inteira de 10 em 10, como a Steam real."""

    def __init__(self, resultados, erro_no_start=None, contador=None):
        self.resultados = list(resultados)
        self.erro_no_start = erro_no_start
        self.contador = contador
        self.chamadas = []
        self.emprestadas = []

    def search_page(self, start=0, count=100, query=None):
        self.chamadas.append((start, query))
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if start == self.erro_no_start:
            raise SteamLimitando("429")
        return SearchPage(total_count=len(self.resultados),
                          results=self.resultados[start:start + 10])


class _Retratos:
    def __init__(self, paginas, limitar_em=None, quebrar=(), antigo=(), contador=None):
        self.paginas = paginas
        self.limitar_em = limitar_em
        self.quebrar = set(quebrar)
        self.antigo = set(antigo)
        self.contador = contador
        self.calma = False
        self.pedidos = []
        self.emprestadas = []

    def em_calma(self):
        return self.calma

    def acalmar(self):
        self.calma = True

    def obter(self, engine, hash_name, usd_to_brl, quando, forcar=False):
        assert forcar
        self.pedidos.append(hash_name)
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if hash_name == self.limitar_em:
            self.calma = True
            return Leitura(None, None, True)
        if hash_name in self.quebrar:
            raise PageStructureError("pagina mudou")
        if hash_name in self.antigo:
            return Leitura(self.paginas[hash_name], quando - timedelta(minutes=1), False)
        return Leitura(self.paginas[hash_name], quando, False)


def _cotacao(valor=SimpleNamespace(usd_to_brl=5.0)):
    return SimpleNamespace(obter=lambda engine: valor)


def _rodar(engine, steam, retratos, quando=T0, cotacao=None, dormir=None):
    return executar_rodada(
        engine, steam=steam, retratos=retratos, cotacao=cotacao or _cotacao(),
        agora=lambda: quando, dormir=dormir or (lambda s: None), aceitar=_aceitar,
    )


def _listagens(engine):
    with engine.begin() as conn:
        return {(l.hash_name, l.listing_id) for l in repo.listar_listagens(conn)}


PAGINAS = {
    "Unusual A": _pagina("Unusual A", ("a1", 500, "Burning Flames"), ("a2", 900, "Sunbeams")),
    "Unusual B": _pagina("Unusual B", ("b1", 700, "Burning Flames")),
}


def test_primeira_rodada_le_a_fundo_so_os_cosmeticos_e_pagina_a_busca(engine):
    # 12 resultados: exige duas páginas da busca (start 0 e 10).
    extras = [_r(f"Unusual Taunt: {i}") for i in range(10)]
    steam = _Steam([_r("Unusual A", n=2), *extras, _r("Unusual B")])
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, steam, retratos)

    assert steam.chamadas == [(0, QUERY), (10, QUERY)]
    assert retratos.pedidos == ["Unusual A", "Unusual B"]
    assert (resumo.nomes_lidos, resumo.fundas_feitas, resumo.falhas, resumo.motivo) == (2, 2, 0, "ok")
    assert _listagens(engine) == {("Unusual A", "a1"), ("Unusual A", "a2"), ("Unusual B", "b1")}
    with engine.begin() as conn:
        rodada = repo.ultima_rodada(conn)
    assert (rodada.motivo_parada, rodada.nomes_lidos, rodada.fundas_feitas) == ("ok", 2, 2)


def test_assinatura_igual_dentro_do_prazo_nao_le_a_fundo(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos,
                    quando=T0 + timedelta(hours=3))

    assert retratos.pedidos == []
    assert (resumo.nomes_lidos, resumo.fundas_feitas) == (2, 0)


def test_assinatura_mudada_le_a_fundo_so_aquele_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B")]), retratos,
           quando=T0 + timedelta(hours=1))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_vencida_le_de_novo(engine):
    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    # PADRAO: 24 h de idade máxima da leitura funda.
    _rodar(engine, _Steam([_r("Unusual A")]), retratos, quando=T0 + timedelta(hours=25))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_substitui_as_listagens_do_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A", n=2)]), _Retratos(PAGINAS))
    vendida = {"Unusual A": _pagina("Unusual A", ("a2", 900, "Sunbeams"))}

    _rodar(engine, _Steam([_r("Unusual A", n=1)]), _Retratos(vendida),
           quando=T0 + timedelta(hours=1))

    assert _listagens(engine) == {("Unusual A", "a2")}


def test_429_na_leitura_funda_para_a_rodada_sem_apagar_nada(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    antes = _listagens(engine)
    retratos = _Retratos(PAGINAS, limitar_em="Unusual A")

    resumo = _rodar(engine, _Steam([_r("Unusual A", usd=1), _r("Unusual B", usd=1)]),
                    retratos, quando=T0 + timedelta(hours=1))

    assert resumo.motivo == "429"
    assert retratos.pedidos == ["Unusual A"]  # B nem foi pedido
    assert _listagens(engine) == antes
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "429"


def test_429_na_busca_liga_a_calma_do_retrato_e_para(engine):
    retratos = _Retratos(PAGINAS)
    steam = _Steam([_r("Unusual A")] + [_r(f"Unusual Taunt: {i}") for i in range(15)],
                   erro_no_start=10)

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "429"
    assert retratos.calma
    assert retratos.pedidos == []  # a funda não começa depois de uma rasa interrompida


def test_nome_quebrado_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, quebrar={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_retrato_antigo_nao_substitui_listagens_nem_marca_funda(engine):
    retratos = _Retratos(PAGINAS, antigo={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A")]), retratos)

    assert resumo.fundas_feitas == 0
    assert _listagens(engine) == set()
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual A").funda_em is None


def test_nome_sumido_so_sai_depois_de_duas_rodadas_completas_sem_ele(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=1))
    assert ("Unusual B", "b1") in _listagens(engine)

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=2))
    assert ("Unusual B", "b1") not in _listagens(engine)


def test_sem_cotacao_a_rodada_para_com_erro_sem_ir_a_steam(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), cotacao=_cotacao(None))

    assert resumo.motivo == "erro"
    assert steam.chamadas == []


def test_espaco_extra_antes_de_cada_requisicao(engine):
    esperas = []

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS),
           dormir=esperas.append)

    # 1 página da busca + 2 leituras fundas
    assert esperas == [ESPACO_EXTRA_S] * 3


def test_nenhuma_conexao_emprestada_durante_as_requisicoes(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    steam = _Steam([_r("Unusual A"), _r("Unusual B")], contador=contador)
    retratos = _Retratos(PAGINAS, contador=contador)

    _rodar(engine, steam, retratos)

    assert steam.emprestadas == [0]
    assert retratos.emprestadas == [0, 0]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_rodada.py -v`
Expected: FAIL (`ModuleNotFoundError: tf2price.varredura.rodada`)

- [ ] **Step 3: Implementar `tf2price/varredura/rodada.py`**

```python
"""Uma rodada da varredura: passada rasa, seleção, passada funda.

A passada rasa lê a busca da Steam (10 nomes por requisição) e guarda, por
nome, o menor preço e o número de listagens, que é a assinatura. A funda abre
a página só dos nomes cuja assinatura mudou, que nunca foram lidos ou cuja
leitura passou do prazo. Numa rodada típica, isso é a busca mais algumas
dezenas de páginas, em vez de mil.

Toda requisição sai do mesmo IP da consulta, e a consulta é o produto. Por
isso a rodada dorme um intervalo extra antes de cada requisição, para com o
primeiro 429 e nunca segura conexão de banco durante a rede.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.ratelimit import SteamLimitando
from tf2price.sources.steam import SearchResult
from tf2price.varredura import repositorio as repo
from tf2price.varredura.escopo import e_cosmetico_unusual

QUERY = "Unusual"
# Com o RateLimiter de 1 s, a varredura sai a cada ~5 s. Medido em
# 2026-09-19: 429 na 128ª requisição a 1 s, cinco 429 em 389 a 3 s. Uma
# consulta de usuário espera no máximo uma requisição da varredura.
ESPACO_EXTRA_S = 4.0
# Freio contra um `total_count` absurdo: 4.000 nomes, o dobro do medido.
MAX_PAGINAS_RASAS = 400


@dataclass
class Resumo:
    nomes_lidos: int = 0
    fundas_feitas: int = 0
    falhas: int = 0
    motivo: str = repo.MOTIVO_OK


def _precisa_funda(
    anterior: repo.Assinatura | None, visto: SearchResult, quando: datetime, config: repo.Config
) -> bool:
    if anterior is None or anterior.funda_em is None:
        return True
    if (anterior.preco_usd_cents, anterior.n_listagens) != (
        visto.sell_price_usd_cents, visto.sell_listings
    ):
        return True
    return quando - anterior.funda_em > timedelta(hours=config.idade_max_funda_h)


def executar_rodada(
    engine: Engine,
    *,
    steam: Any,
    retratos: Any,
    cotacao: Any,
    agora: Callable[[], datetime] = db.agora,
    dormir: Callable[[float], None] = time.sleep,
    aceitar: Callable[[str], bool] = e_cosmetico_unusual,
    espaco_extra_s: float = ESPACO_EXTRA_S,
) -> Resumo:
    inicio = agora()
    with engine.begin() as conn:
        config = repo.ler_config(conn)
        anterior_completa = repo.ultima_completa(conn)
        rodada_id = repo.abrir_rodada(conn, inicio)

    resumo = Resumo()
    try:
        resumo.motivo = _rodar(
            engine, rodada_id, resumo, config,
            steam=steam, retratos=retratos, cotacao=cotacao,
            agora=agora, dormir=dormir, aceitar=aceitar, espaco_extra_s=espaco_extra_s,
        )
    except Exception as erro:
        print(f"[varredura] rodada {rodada_id}: {type(erro).__name__}: "
              f"{mensagem_saneada(erro)}", flush=True)
        resumo.motivo = repo.MOTIVO_ERRO

    with engine.begin() as conn:
        repo.fechar_rodada(
            conn, rodada_id, agora(),
            nomes_lidos=resumo.nomes_lidos, fundas_feitas=resumo.fundas_feitas,
            falhas=resumo.falhas, motivo=resumo.motivo,
        )
        # Só uma rodada COMPLETA viu o mercado inteiro. E um nome some só
        # depois de duas completas sem ele: a busca ordena por preço e leva
        # minutos, e um item cujo preço mudou no meio pode trocar de página e
        # não ser visto uma vez sem ter saído do mercado.
        if resumo.motivo == repo.MOTIVO_OK and anterior_completa is not None:
            repo.apagar_nao_vistos_desde(conn, anterior_completa.inicio)
    print(f"[varredura] rodada {rodada_id}: {resumo.motivo}, {resumo.nomes_lidos} nomes, "
          f"{resumo.fundas_feitas} lidos a fundo, {resumo.falhas} falhas", flush=True)
    return resumo


def _rodar(
    engine: Engine, rodada_id: int, resumo: Resumo, config: repo.Config, *,
    steam: Any, retratos: Any, cotacao: Any,
    agora: Callable[[], datetime], dormir: Callable[[float], None],
    aceitar: Callable[[str], bool], espaco_extra_s: float,
) -> str:
    cot = cotacao.obter(engine)
    if cot is None:
        print("[varredura] sem cotação da chave: a página do item vem em dólar "
              "e não há taxa para converter", flush=True)
        return repo.MOTIVO_ERRO

    # --- passada rasa
    vistos: set[str] = set()
    pendentes: list[str] = []
    start = 0
    for _ in range(MAX_PAGINAS_RASAS):
        if retratos.em_calma():
            return repo.MOTIVO_429
        dormir(espaco_extra_s)
        try:
            pagina = steam.search_page(start=start, query=QUERY)
        except SteamLimitando:
            retratos.acalmar()
            return repo.MOTIVO_429
        if not pagina.results:
            break
        quando = agora()
        with engine.begin() as conn:
            for visto in pagina.results:
                if not aceitar(visto.hash_name) or visto.hash_name in vistos:
                    continue
                vistos.add(visto.hash_name)
                anterior = repo.ler_assinatura(conn, visto.hash_name)
                repo.gravar_vista(conn, visto.hash_name, visto.sell_price_usd_cents,
                                  visto.sell_listings, quando)
                if _precisa_funda(anterior, visto, quando, config):
                    pendentes.append(visto.hash_name)
            resumo.nomes_lidos = len(vistos)
            repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                     fundas_feitas=0, falhas=0)
        start += len(pagina.results)
        if start >= pagina.total_count:
            break

    # --- passada funda
    for nome in pendentes:
        if retratos.em_calma():
            return repo.MOTIVO_429
        dormir(espaco_extra_s)
        quando = agora()
        try:
            leitura = retratos.obter(engine, nome, cot.usd_to_brl, quando, forcar=True)
        except RuntimeError as erro:  # PageStructureError e falhas de transporte
            resumo.falhas += 1
            print(f"[varredura] {nome}: {type(erro).__name__}: {mensagem_saneada(erro)}", flush=True)
            continue
        if leitura.limitando:
            return repo.MOTIVO_429
        # Retrato devolvido do banco (piso de `forcar`: alguém acabou de
        # atualizar este item) não é leitura nova. Regravar com ele marcaria
        # como "lido agora" um dado de antes.
        if leitura.pagina is None or leitura.buscado_em != quando:
            continue
        with engine.begin() as conn:
            repo.substituir_listagens(conn, nome, leitura.pagina.listings, quando)
            resumo.fundas_feitas += 1
            repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                     fundas_feitas=resumo.fundas_feitas, falhas=resumo.falhas)
    return repo.MOTIVO_OK
```

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/varredura/rodada.py tests/varredura/test_rodada.py
git commit -m "Implementa a rodada da varredura em dois niveis"
```

---

### Task 7: Agendador e montagem na subida

**Files:**
- Create: `tf2price/varredura/agendador.py`
- Modify: `tf2price/painel/app.py` (`criar_app`, `servir`, `construir_aplicacao`, nova `preparar_varredura`)
- Test: `tests/varredura/test_agendador.py`, `tests/painel/test_aquecimento.py` (acrescentar um teste)

**Interfaces:**
- Consumes: `executar_rodada` (Task 6), `repo.ler_config/ultima_rodada/fechar_abertas` (Task 3)
- Produces:
  - `PERIODO_S = 60.0`
  - `class Agendador(engine, rodar: Callable[[], Any], agora=db.agora)` com `.rodando -> bool`, `.vencida() -> bool`, `.tentar_rodar() -> bool`, `.disparar_em_segundo_plano() -> bool`, `.ciclo(parar: threading.Event, periodo_s: float = PERIODO_S) -> None`
  - `construir_agendador(engine, contexto) -> Agendador`
  - `iniciar_em_segundo_plano(agendador) -> threading.Thread`
  - Em `app.py`: `criar_app(engine, contexto=None, agendador=None)` guarda `app.state.agendador`; `preparar_varredura(engine, contexto, iniciar=iniciar_em_segundo_plano) -> Agendador`

- [ ] **Step 1: Escrever os testes que falham**

`tests/varredura/test_agendador.py`:

```python
from __future__ import annotations

import threading
from datetime import timedelta

from tf2price import db
from tf2price.varredura import repositorio as repo
from tf2price.varredura.agendador import Agendador

T0 = db.agora()


def _ligar(engine, intervalo_min=60):
    with engine.begin() as conn:
        repo.gravar_config(conn, repo.Config(True, intervalo_min, 24), T0)


def _rodada_em(engine, quando):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, quando)
        repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=repo.MOTIVO_OK)


def test_desligada_nunca_vence(engine):
    assert not Agendador(engine, rodar=lambda: None, agora=lambda: T0).vencida()


def test_ligada_sem_rodada_nenhuma_vence(engine):
    _ligar(engine)
    assert Agendador(engine, rodar=lambda: None, agora=lambda: T0).vencida()


def test_vence_so_depois_do_intervalo(engine):
    _ligar(engine, intervalo_min=60)
    _rodada_em(engine, T0)
    antes = Agendador(engine, rodar=lambda: None, agora=lambda: T0 + timedelta(minutes=59))
    depois = Agendador(engine, rodar=lambda: None, agora=lambda: T0 + timedelta(minutes=60))
    assert not antes.vencida()
    assert depois.vencida()


def test_nunca_duas_rodadas_ao_mesmo_tempo(engine):
    entrou = threading.Event()
    soltar = threading.Event()
    rodadas = []

    def rodar():
        rodadas.append(1)
        entrou.set()
        soltar.wait(5)

    agendador = Agendador(engine, rodar=rodar)
    assert agendador.disparar_em_segundo_plano()
    assert entrou.wait(5)

    assert agendador.rodando
    assert not agendador.tentar_rodar()
    assert not agendador.disparar_em_segundo_plano()

    soltar.set()
    for _ in range(100):
        if not agendador.rodando:
            break
        threading.Event().wait(0.01)
    assert not agendador.rodando
    assert rodadas == [1]


def test_ciclo_roda_quando_vence_e_sobrevive_a_erro(engine):
    _ligar(engine)
    parar = threading.Event()
    chamadas = []

    def rodar():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("bug da rodada")
        parar.set()

    Agendador(engine, rodar=rodar).ciclo(parar, periodo_s=0)

    assert chamadas == [1, 1]
```

Acrescente a `tests/painel/test_aquecimento.py`:

```python
def test_preparar_varredura_fecha_rodadas_abertas_e_inicia_o_agendador(engine):
    from tf2price import db
    from tf2price.painel.app import preparar_varredura
    from tf2price.varredura import repositorio as varredura_repo
    from tf2price.varredura.agendador import Agendador

    with engine.begin() as conn:
        varredura_repo.abrir_rodada(conn, db.agora())
    iniciados = []

    agendador = preparar_varredura(engine, contexto=None, iniciar=iniciados.append)

    assert isinstance(agendador, Agendador)
    assert iniciados == [agendador]
    with engine.begin() as conn:
        assert varredura_repo.ultima_rodada(conn).motivo_parada == varredura_repo.MOTIVO_INTERROMPIDA
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_agendador.py tests\painel\test_aquecimento.py -v`
Expected: FAIL (`ModuleNotFoundError: tf2price.varredura.agendador`, `ImportError: preparar_varredura`)

- [ ] **Step 3: Implementar `tf2price/varredura/agendador.py`**

```python
"""Quando rodar a varredura, e nunca duas ao mesmo tempo.

Vive no processo do painel, num thread daemon, como o aquecimento da
cotação. Isso só é seguro com uma réplica (AGENTS.md): trava e calma são da
memória deste processo.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.saneamento import mensagem_saneada
from tf2price.varredura import repositorio as repo
from tf2price.varredura.rodada import executar_rodada

# De quanto em quanto tempo o fundo acorda para olhar a configuração. Não é o
# intervalo das rodadas: esse vem do painel admin.
PERIODO_S = 60.0


class Agendador:
    def __init__(
        self,
        engine: Engine,
        rodar: Callable[[], Any],
        agora: Callable[[], datetime] = db.agora,
    ) -> None:
        self._engine = engine
        self._rodar = rodar
        self._agora = agora
        # Adquirida sem bloquear, por quem vai rodar. `Lock` (e não `RLock`)
        # porque "Run now" a adquire no thread da requisição e a solta no
        # thread da rodada.
        self._trava = threading.Lock()

    @property
    def rodando(self) -> bool:
        return self._trava.locked()

    def vencida(self) -> bool:
        with self._engine.begin() as conn:
            config = repo.ler_config(conn)
            ultima = repo.ultima_rodada(conn)
        if not config.ligada:
            return False
        if ultima is None:
            return True
        return self._agora() - ultima.inicio >= timedelta(minutes=config.intervalo_min)

    def tentar_rodar(self) -> bool:
        """Roda no thread de quem chamou. Falso se já havia rodada em curso."""
        if not self._trava.acquire(blocking=False):
            return False
        self._executar_segurando()
        return True

    def disparar_em_segundo_plano(self) -> bool:
        """Para o "Run now": a requisição volta na hora, a rodada leva minutos."""
        if not self._trava.acquire(blocking=False):
            return False
        threading.Thread(
            target=self._executar_segurando, name="varredura-manual", daemon=True
        ).start()
        return True

    def _executar_segurando(self) -> None:
        try:
            self._rodar()
        finally:
            self._trava.release()

    def ciclo(self, parar: threading.Event, periodo_s: float = PERIODO_S) -> None:
        while not parar.wait(periodo_s):
            try:
                if self.vencida():
                    self.tentar_rodar()
            except Exception as erro:
                # Um bug numa rodada não pode matar o agendador para sempre:
                # ninguém veria, e a página só envelheceria.
                print(f"[varredura] agendador: {type(erro).__name__}: "
                      f"{mensagem_saneada(erro)}", flush=True)


def construir_agendador(engine: Engine, contexto: Any) -> Agendador:
    def rodar():
        return executar_rodada(
            engine,
            steam=contexto.steam,
            retratos=contexto.retratos,
            cotacao=contexto.cotacao,
        )

    return Agendador(engine, rodar)


def iniciar_em_segundo_plano(agendador: Agendador) -> threading.Thread:
    thread = threading.Thread(
        target=agendador.ciclo, args=(threading.Event(),), name="varredura", daemon=True
    )
    thread.start()
    return thread
```

- [ ] **Step 4: Ligar em `tf2price/painel/app.py`**

1. Nos imports, acrescente:

```python
from tf2price.varredura import repositorio as varredura_repo
from tf2price.varredura.agendador import (
    Agendador,
    construir_agendador,
    iniciar_em_segundo_plano,
)
```

2. Troque a assinatura de `criar_app` e guarde o agendador:

```python
def criar_app(
    engine: Engine, contexto: "Contexto | None" = None, agendador: Agendador | None = None
) -> FastAPI:
    app = FastAPI(title="briefcase.tf")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.engine = engine
    app.state.contexto = contexto
    # None nos testes e em qualquer app sem contexto: a página e o admin
    # dizem que a varredura não roda neste processo.
    app.state.agendador = agendador
```

(o resto de `criar_app` fica igual)

3. Acrescente, logo depois de `aquecer_em_segundo_plano`:

```python
def preparar_varredura(
    engine: Engine,
    contexto: "Contexto | None",
    iniciar: Callable[[Agendador], object] = iniciar_em_segundo_plano,
) -> Agendador:
    """Fecha rodadas que um processo anterior deixou abertas e sobe o agendador.

    Uma rodada sem fim no banco é de um processo que morreu no meio dela
    (deploy, reinício). Não há retomada: `funda_em` por nome faz a próxima
    rodada pular o que já foi lido.
    """
    with engine.begin() as conn:
        fechadas = varredura_repo.fechar_abertas(conn, db.agora())
    if fechadas:
        print(f"[varredura] {fechadas} rodada(s) interrompida(s) por reinício", flush=True)
    agendador = construir_agendador(engine, contexto)
    iniciar(agendador)
    return agendador
```

E, no topo de `app.py`, acrescente `from typing import TYPE_CHECKING, Callable` (hoje é só `TYPE_CHECKING`).

4. Em `servir()`, troque as duas últimas linhas por:

```python
    contexto = construir_contexto()
    aquecer_em_segundo_plano(contexto, engine)
    agendador = preparar_varredura(engine, contexto)
    uvicorn.run(criar_app(engine, contexto, agendador), host="127.0.0.1", port=8000)
```

5. Em `construir_aplicacao()`, troque o final por:

```python
    aquecer_em_segundo_plano(contexto, engine)
    agendador = preparar_varredura(engine, contexto)
    return criar_app(engine, contexto, agendador)
```

- [ ] **Step 5: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura tests\painel -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tf2price/varredura/agendador.py tf2price/painel/app.py tests/varredura/test_agendador.py tests/painel/test_aquecimento.py
git commit -m "Agenda a varredura num thread de fundo com trava de rodada unica"
```

---

### Task 8: Leitura — resultado por listagem, filtros e paginação

**Files:**
- Create: `tf2price/varredura/leitura.py`
- Test: `tests/varredura/test_leitura.py`

**Interfaces:**
- Consumes: `repo.ListagemVarrida` (Task 3), `patient_exit` de `tf2price.lookup.analysis`, `arte_dos_efeitos.url_do_efeito`
- Produces:
  - `IDADE_MAX_BPTF_PADRAO = 90`, `POR_PAGINA = 50`, `ABAS = ("todas", "lucro")`, `ORDENS = ("resultado", "percentual", "preco", "idade_bptf")`, `SEM_COTACAO`, `EFEITO_DESCONHECIDO`
  - `Filtros(aba, texto, efeito, preco_min, preco_max, idade_max_bptf_dias, so_com_preco, ordem, pagina)` com `.query(**mudancas) -> str`
  - `filtros_da_query(*, aba, q, efeito, preco_min, preco_max, idade_max, so_com_preco, ordem, pagina) -> Filtros` (todos `str`)
  - `LinhaVarrida(listagem, preco_em_chaves, chaves_bptf, valor_bptf, resultado, percentual, idade_bptf_dias, motivo, arte)`
  - `Pagina(linhas, total, pagina, paginas)`
  - `avaliar(listagem, indice, key_brl, agora_unix, idade_max_bptf_dias, effects_path=DEFAULT_EFFECTS_PATH) -> LinhaVarrida`
  - `montar(listagens, indice, key_brl, filtros, agora_unix, effects_path=DEFAULT_EFFECTS_PATH) -> Pagina`

- [ ] **Step 1: Escrever os testes que falham**

`tests/varredura/test_leitura.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import RAZAO_SEM_INDICE, RAZAO_SEM_PRECO
from tf2price.sources.backpacktf import PriceIndex
from tf2price.varredura import leitura
from tf2price.varredura.repositorio import ListagemVarrida

EFEITOS = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"
AGORA = 1_790_000_000
CHAVE = Brl.from_cents(1000)  # R$ 10,00 a chave: conta de cabeça


def _indice(dias=10, chaves=100.0, efeito_id="13"):
    return PriceIndex.from_payload({"response": {"items": {
        "Team Captain": {"prices": {"5": {"Tradable": {"Craftable": {
            efeito_id: {"currency": "keys", "value": chaves, "last_update": AGORA - dias * 86400},
        }}}}},
    }}}, key_in_refined=64.11)


def _l(ident, centavos, efeito="Burning Flames", nome="Unusual Team Captain", mais=0):
    return ListagemVarrida(ident, nome, efeito, Brl(centavos), None, db.agora(), mais)


def _avaliar(listagem, indice=None, chave=CHAVE, idade_max=90):
    return leitura.avaliar(listagem, indice if indice is not None else _indice(), chave,
                           AGORA, idade_max, effects_path=EFEITOS)


def test_resultado_e_o_da_saida_paciente():
    # 100 chaves x R$ 10 = R$ 1.000; paga R$ 800 -> +R$ 200 (25%).
    linha = _avaliar(_l("1", 80000))
    assert linha.valor_bptf == Brl(100000)
    assert linha.chaves_bptf == 100.0
    assert linha.resultado == Brl(20000)
    assert linha.percentual == pytest.approx(0.25)
    assert linha.idade_bptf_dias == 10
    assert linha.preco_em_chaves == pytest.approx(80.0)
    assert linha.motivo is None


def test_efeito_sem_preco_nunca_herda_o_de_outro_efeito():
    # O índice só precifica Burning Flames (13); Sunbeams (17) fica sem.
    linha = _avaliar(_l("1", 80000, efeito="Sunbeams"))
    assert (linha.resultado, linha.valor_bptf) == (None, None)
    assert linha.motivo == RAZAO_SEM_PRECO


def test_efeito_desconhecido_nao_tem_resultado():
    linha = _avaliar(_l("1", 80000, efeito=None))
    assert linha.resultado is None
    assert linha.motivo == leitura.EFEITO_DESCONHECIDO


def test_sem_cotacao_nao_tem_resultado():
    linha = _avaliar(_l("1", 80000), chave=None)
    assert (linha.resultado, linha.preco_em_chaves) == (None, None)
    assert linha.motivo == leitura.SEM_COTACAO


def test_sem_indice_diz_que_o_indice_nao_carregou():
    linha = leitura.avaliar(_l("1", 80000), None, CHAVE, AGORA, 90, effects_path=EFEITOS)
    assert linha.motivo == RAZAO_SEM_INDICE


def test_preco_velho_mostra_valor_e_idade_mas_nao_resultado():
    linha = _avaliar(_l("1", 80000), indice=_indice(dias=200), idade_max=90)
    assert linha.valor_bptf == Brl(100000)
    assert linha.idade_bptf_dias == 200
    assert linha.resultado is None
    assert linha.motivo == "backpack.tf price is older than 90 days"


def test_sem_limite_de_idade_o_preco_velho_conta():
    linha = _avaliar(_l("1", 80000), indice=_indice(dias=200), idade_max=None)
    assert linha.resultado == Brl(20000)


def _montar(listagens, **filtros):
    return leitura.montar(listagens, _indice(), CHAVE, leitura.Filtros(**filtros),
                          AGORA, effects_path=EFEITOS)


def test_aba_lucro_so_tem_resultado_positivo():
    listagens = [_l("ganha", 80000), _l("perde", 150000), _l("sem", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens, aba="lucro").linhas] == ["ganha"]
    assert _montar(listagens).total == 3


def test_so_com_preco_tira_as_linhas_sem_resultado():
    listagens = [_l("ganha", 80000), _l("sem", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens, so_com_preco=True).linhas] == ["ganha"]


def test_ordenacoes():
    listagens = [_l("a", 90000), _l("b", 50000), _l("c", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens).linhas] == ["b", "a", "c"]
    assert [l.listagem.listing_id for l in _montar(listagens, ordem="preco").linhas] == ["c", "b", "a"]
    assert [l.listagem.listing_id for l in _montar(listagens, ordem="percentual").linhas] == ["b", "a", "c"]


def test_paginacao_limita_e_corrige_pagina_fora_do_intervalo():
    listagens = [_l(f"{i:03}", 80000 + i) for i in range(leitura.POR_PAGINA + 5)]
    segunda = _montar(listagens, pagina=2)
    assert (segunda.total, segunda.pagina, segunda.paginas, len(segunda.linhas)) == (55, 2, 2, 5)
    assert _montar(listagens, pagina=99).pagina == 2


def test_filtros_da_query_valida_tudo():
    f = leitura.filtros_da_query(aba="lucro", q="  team ", efeito="Sunbeams",
                                 preco_min="10.50", preco_max="abc", idade_max="",
                                 so_com_preco="1", ordem="preco", pagina="-3")
    assert f == leitura.Filtros(aba="lucro", texto="team", efeito="Sunbeams",
                                preco_min=Brl(1050), preco_max=None,
                                idade_max_bptf_dias=None, so_com_preco=True,
                                ordem="preco", pagina=1)


def test_filtros_da_query_recusa_valores_desconhecidos():
    f = leitura.filtros_da_query(aba="x", ordem="y", idade_max="0", preco_min="-5")
    assert (f.aba, f.ordem, f.idade_max_bptf_dias, f.preco_min) == ("todas", "resultado", None, None)


def test_filtros_padrao():
    assert leitura.filtros_da_query() == leitura.Filtros()
    assert leitura.Filtros().idade_max_bptf_dias == 90


def test_query_preserva_filtros_e_troca_so_o_pedido():
    f = leitura.Filtros(texto="team", preco_min=Brl(1050), so_com_preco=True)
    q = f.query(pagina=3)
    assert "q=team" in q and "preco_min=10.50" in q and "so_com_preco=1" in q
    assert "pagina=3" in q
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_leitura.py -v`
Expected: FAIL (`ImportError: cannot import name 'leitura'`)

- [ ] **Step 3: Implementar `tf2price/varredura/leitura.py`**

```python
"""A página da varredura: cada listagem cruzada com a backpack.tf, na hora.

O resultado nunca é gravado. Ele sai da mesma `patient_exit` da tela de
consulta, contra o índice e a cotação que estão na memória agora. Quando a
bp.tf atualiza um preço, a página reflete sem nenhuma requisição à Steam.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH
from tf2price.domain.money import Brl
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.lookup.analysis import patient_exit
from tf2price.sources.backpacktf import PriceIndex
from tf2price.varredura.repositorio import ListagemVarrida

IDADE_MAX_BPTF_PADRAO = 90
POR_PAGINA = 50
ABAS = ("todas", "lucro")
ORDENS = ("resultado", "percentual", "preco", "idade_bptf")
SEM_COTACAO = "the key exchange rate has not loaded yet"
EFEITO_DESCONHECIDO = "Steam did not report the effect of this listing"


@dataclass(frozen=True)
class Filtros:
    aba: str = "todas"
    texto: str = ""
    efeito: str = ""
    preco_min: Brl | None = None
    preco_max: Brl | None = None
    idade_max_bptf_dias: int | None = IDADE_MAX_BPTF_PADRAO
    so_com_preco: bool = False
    ordem: str = "resultado"
    pagina: int = 1

    def query(self, **mudancas) -> str:
        """Query string destes filtros, com `mudancas` aplicadas: é o que as
        abas e a paginação usam para não perder o resto do filtro."""
        f = replace(self, **mudancas)
        pares = {
            "aba": f.aba,
            "q": f.texto,
            "efeito": f.efeito,
            "preco_min": _reais(f.preco_min),
            "preco_max": _reais(f.preco_max),
            "idade_max": "" if f.idade_max_bptf_dias is None else str(f.idade_max_bptf_dias),
            "ordem": f.ordem,
            "pagina": str(f.pagina),
        }
        if f.so_com_preco:
            pares["so_com_preco"] = "1"
        return urlencode(pares)


def _reais(valor: Brl | None) -> str:
    return "" if valor is None else f"{valor.cents // 100}.{valor.cents % 100:02d}"


def _brl(texto: str) -> Brl | None:
    """Texto de formulário em reais para `Brl`, sem passar por float."""
    texto = texto.strip().replace(",", ".")
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    if not valor.is_finite() or valor < 0:
        return None
    return Brl(int((valor * 100).to_integral_value()))


def _positivo(texto: str) -> int | None:
    try:
        valor = int(texto.strip())
    except ValueError:
        return None
    return valor if valor > 0 else None


def filtros_da_query(
    *, aba: str = "todas", q: str = "", efeito: str = "", preco_min: str = "",
    preco_max: str = "", idade_max: str = str(IDADE_MAX_BPTF_PADRAO),
    so_com_preco: str = "", ordem: str = "resultado", pagina: str = "1",
) -> Filtros:
    """Tudo aqui é texto de fora: valor inválido vira o padrão, nunca erro."""
    return Filtros(
        aba=aba if aba in ABAS else "todas",
        texto=q.strip()[:100],
        efeito=efeito.strip()[:120],
        preco_min=_brl(preco_min),
        preco_max=_brl(preco_max),
        idade_max_bptf_dias=_positivo(idade_max),
        so_com_preco=so_com_preco == "1",
        ordem=ordem if ordem in ORDENS else "resultado",
        pagina=_positivo(pagina) or 1,
    )


@dataclass(frozen=True)
class LinhaVarrida:
    listagem: ListagemVarrida
    preco_em_chaves: float | None
    chaves_bptf: float | None
    valor_bptf: Brl | None
    resultado: Brl | None
    percentual: float | None
    idade_bptf_dias: int | None
    motivo: str | None
    arte: str | None


@dataclass(frozen=True)
class Pagina:
    linhas: list[LinhaVarrida]
    total: int
    pagina: int
    paginas: int


def avaliar(
    listagem: ListagemVarrida,
    indice: PriceIndex | None,
    key_brl: Brl | None,
    agora_unix: int,
    idade_max_bptf_dias: int | None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> LinhaVarrida:
    arte = (
        arte_dos_efeitos.url_do_efeito(listagem.efeito, effects_path=effects_path)
        if listagem.efeito else None
    )

    def linha(**campos) -> LinhaVarrida:
        base = dict(
            listagem=listagem, preco_em_chaves=None, chaves_bptf=None, valor_bptf=None,
            resultado=None, percentual=None, idade_bptf_dias=None, motivo=None, arte=arte,
        )
        base.update(campos)
        return LinhaVarrida(**base)

    if key_brl is None or key_brl.cents <= 0:
        return linha(motivo=SEM_COTACAO)
    em_chaves = listagem.preco.cents / key_brl.cents
    if listagem.efeito is None:
        return linha(preco_em_chaves=em_chaves, motivo=EFEITO_DESCONHECIDO)

    saida = patient_exit(
        listagem.preco, listagem.hash_name, listagem.efeito, indice, key_brl,
        now=agora_unix, effects_path=effects_path,
    )
    if not saida.available:
        return linha(preco_em_chaves=em_chaves, motivo=saida.reason)
    if (
        idade_max_bptf_dias is not None
        and saida.age_days is not None
        and saida.age_days > idade_max_bptf_dias
    ):
        # O valor e a idade continuam à mostra; o resultado não. Um lucro
        # medido contra um preço de anos atrás é o falso positivo que
        # derrubou o spike de 2026-09-19.
        return linha(
            preco_em_chaves=em_chaves, chaves_bptf=saida.keys, valor_bptf=saida.fair_value,
            idade_bptf_dias=saida.age_days,
            motivo=f"backpack.tf price is older than {idade_max_bptf_dias} days",
        )
    percentual = (
        saida.result.cents / listagem.preco.cents if listagem.preco.cents > 0 else None
    )
    return linha(
        preco_em_chaves=em_chaves, chaves_bptf=saida.keys, valor_bptf=saida.fair_value,
        resultado=saida.result, percentual=percentual, idade_bptf_dias=saida.age_days,
    )


def _chave_de_ordem(ordem: str):
    # Sem resultado vai sempre para o fim; o id desempata para a ordem ser
    # estável entre uma página e a seguinte.
    if ordem == "preco":
        return lambda l: (l.listagem.preco.cents, l.listagem.listing_id)
    if ordem == "idade_bptf":
        return lambda l: (l.idade_bptf_dias is None, l.idade_bptf_dias or 0, l.listagem.listing_id)
    if ordem == "percentual":
        return lambda l: (l.percentual is None, -(l.percentual or 0.0), l.listagem.listing_id)
    return lambda l: (
        l.resultado is None, -(l.resultado.cents if l.resultado else 0), l.listagem.listing_id
    )


def montar(
    listagens: list[ListagemVarrida],
    indice: PriceIndex | None,
    key_brl: Brl | None,
    filtros: Filtros,
    agora_unix: int,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> Pagina:
    linhas = [
        avaliar(l, indice, key_brl, agora_unix, filtros.idade_max_bptf_dias, effects_path)
        for l in listagens
    ]
    if filtros.so_com_preco:
        linhas = [l for l in linhas if l.resultado is not None]
    if filtros.aba == "lucro":
        linhas = [l for l in linhas if l.resultado is not None and l.resultado.cents > 0]
    linhas.sort(key=_chave_de_ordem(filtros.ordem))

    total = len(linhas)
    paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina = min(max(1, filtros.pagina), paginas)
    inicio = (pagina - 1) * POR_PAGINA
    return Pagina(linhas[inicio:inicio + POR_PAGINA], total, pagina, paginas)
```

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_leitura.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/varredura/leitura.py tests/varredura/test_leitura.py
git commit -m "Calcula o resultado de cada listagem varrida contra a backpack.tf"
```

---

### Task 9: A página `/scan`

**Files:**
- Create: `tf2price/painel/varredura.py`
- Create: `tf2price/painel/templates/scan.html`, `_scan_estado.html`, `_scan_tabela.html`
- Modify: `tf2price/painel/templates/_navigation.html`
- Modify: `tf2price/painel/app.py` (incluir o roteador)
- Modify: `tf2price/painel/static/briefcase.css` (acrescentar no fim)
- Modify: `tests/painel/test_accessibility.py`, `tests/painel/test_english_ui.py` (acrescentar `/scan` às listas de caminhos)
- Test: `tests/painel/test_scan.py`

**Interfaces:**
- Consumes: `repo.listar_listagens/efeitos_varridos/ler_config/ultima_rodada/ultima_completa/cobertura`, `leitura.filtros_da_query/montar`, `idade_por_extenso` e `SEM_COTACAO` de `tf2price.painel.consulta`, `request.app.state.agendador`
- Produces: `ROTEADOR` com `GET /scan`; `ROTULO_DA_PARADA: dict[str | None, str]` (usado também pelo admin na Task 10)

- [ ] **Step 1: Escrever os testes que falham**

`tests/painel/test_scan.py`:

```python
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import RAZAO_SEM_PRECO
from tf2price.painel.app import criar_app
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import PageListing
from tf2price.varredura import repositorio as repo

from .conftest import _contexto, cliente_logado

NOME = "Unusual Team Captain"


def _indice(dias=10):
    # CHAVE do conftest é R$ 11,73: 100 chaves = R$ 1.173,00.
    return PriceIndex.from_payload({"response": {"items": {
        "Team Captain": {"prices": {"5": {"Tradable": {"Craftable": {
            "13": {"currency": "keys", "value": 100.0, "last_update": int(time.time()) - dias * 86400},
        }}}}},
    }}}, key_in_refined=64.11)


def _semear(engine, listagens, n_listagens=None, nome=NOME):
    quando = db.agora()
    with engine.begin() as conn:
        repo.gravar_vista(conn, nome, 1000, n_listagens or len(listagens), quando)
        repo.substituir_listagens(
            conn, nome, [PageListing(i, Brl(c), e, None) for i, c, e in listagens], quando
        )


def test_sem_sessao_vai_para_entrar(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    assert cliente.get("/scan").status_code == 303


def test_mostra_cada_listagem_e_o_resultado(engine):
    _semear(engine, [("1", 80000, "Burning Flames"), ("2", 150000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan").text

    assert NOME in texto
    assert "R$ 800,00" in texto and "R$ 1.500,00" in texto
    assert "R$ 373,00" in texto       # 1.173 - 800
    assert "R$ -327,00" in texto      # 1.173 - 1.500
    assert 'href="/scan"' in texto and "Market Scan" in texto


def test_aba_profitable_so_mostra_lucro(engine):
    _semear(engine, [("1", 80000, "Burning Flames"), ("2", 150000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan", params={"aba": "lucro"}).text

    assert "R$ 800,00" in texto
    assert "R$ 1.500,00" not in texto


def test_efeito_sem_preco_nao_herda_de_outro_efeito(engine):
    _semear(engine, [("1", 100, "Sunbeams")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    todas = cliente.get("/scan").text
    lucro = cliente.get("/scan", params={"aba": "lucro"}).text

    assert RAZAO_SEM_PRECO in todas
    assert "Sunbeams" not in lucro.split('id="scan-tabela"')[1]


def test_preco_velho_fica_fora_do_lucro_pelo_filtro_padrao(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice(dias=200)))

    padrao = cliente.get("/scan", params={"aba": "lucro"}).text
    sem_limite = cliente.get("/scan", params={"aba": "lucro", "idade_max": ""}).text

    assert "No listings match these filters." in padrao
    assert "R$ 373,00" in sem_limite


def test_mais_listagens_na_steam(engine):
    _semear(engine, [("1", 80000, "Burning Flames")], n_listagens=13)
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    assert "+12 more on Steam" in cliente.get("/scan").text


def test_htmx_recebe_so_a_tabela(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    parcial = cliente.get("/scan", headers={"HX-Request": "true"}).text

    assert "<!doctype" not in parcial.lower()
    assert "R$ 800,00" in parcial


def test_estado_sem_varredura_ainda(engine):
    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/scan").text
    assert "No full scan yet" in texto
    assert "Scanner is off" in texto
```

Em `tests/painel/test_accessibility.py` e `tests/painel/test_english_ui.py`, acrescente `"/scan"` à lista de `@pytest.mark.parametrize("path", [...])` das páginas autenticadas.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_scan.py -v`
Expected: FAIL (404 em `/scan`)

- [ ] **Step 3: Implementar a rota**

`tf2price/painel/varredura.py`:

```python
"""A página da varredura: todas as listagens de cosméticos Unusual.

A rota só lê o banco e a memória. Ela nunca vai à Steam nem à backpack.tf:
quem busca é a rodada, no fundo, e o índice é o que o aquecimento carregou.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.consulta import SEM_COTACAO, idade_por_extenso
from tf2price.painel.templates import TEMPLATES
from tf2price.varredura import leitura
from tf2price.varredura import repositorio as repo

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])

# Os motivos são gravados em português (são dado); a tela é em inglês.
ROTULO_DA_PARADA: dict[str | None, str] = {
    None: "Running",
    repo.MOTIVO_OK: "Completed",
    repo.MOTIVO_429: "Stopped: Steam rate limit",
    repo.MOTIVO_ERRO: "Stopped: error",
    repo.MOTIVO_INTERROMPIDA: "Interrupted by a restart",
}


def _ha(idade: str) -> str:
    """"5 min" -> "5 min ago"; "now" -> "just now" (e não "now ago")."""
    return "just now" if idade == "now" else f"{idade} ago"


@ROTEADOR.get("/scan", response_class=HTMLResponse)
def scan(
    request: Request,
    aba: str = "todas",
    q: str = "",
    efeito: str = "",
    preco_min: str = "",
    preco_max: str = "",
    idade_max: str = str(leitura.IDADE_MAX_BPTF_PADRAO),
    so_com_preco: str = "",
    ordem: str = "resultado",
    pagina: str = "1",
    usuario: Usuario = Depends(ses.usuario_obrigatorio),
):
    filtros = leitura.filtros_da_query(
        aba=aba, q=q, efeito=efeito, preco_min=preco_min, preco_max=preco_max,
        idade_max=idade_max, so_com_preco=so_com_preco, ordem=ordem, pagina=pagina,
    )
    engine = request.app.state.engine
    contexto = request.app.state.contexto
    agora = db.agora()
    cotacao = contexto.cotacao.obter(engine)
    indice = contexto.indice.em_memoria()
    with engine.begin() as conn:
        listagens = repo.listar_listagens(
            conn, texto=filtros.texto, efeito=filtros.efeito,
            preco_min=filtros.preco_min, preco_max=filtros.preco_max,
        )
        efeitos = repo.efeitos_varridos(conn)
        config = repo.ler_config(conn)
        ultima = repo.ultima_rodada(conn)
        completa = repo.ultima_completa(conn)
        cobertura = repo.cobertura(conn)
    resultado = leitura.montar(
        listagens, indice, cotacao.key_brl if cotacao else None, filtros, int(time.time())
    )
    agendador = request.app.state.agendador
    contexto_da_tela = {
        "usuario": usuario,
        "filtros": filtros,
        "pagina": resultado,
        "efeitos": efeitos,
        "config": config,
        "ultima": ultima,
        "completa": completa,
        "cobertura": cobertura,
        "rodando": bool(agendador and agendador.rodando),
        "cotacao": cotacao,
        "sem_cotacao": SEM_COTACAO,
        "rotulo_da_parada": ROTULO_DA_PARADA,
        "idade": lambda quando: idade_por_extenso(quando, agora),
        "ha": lambda quando: _ha(idade_por_extenso(quando, agora)),
    }
    nome = "_scan_tabela.html" if request.headers.get("HX-Request") else "scan.html"
    return TEMPLATES.TemplateResponse(request=request, name=nome, context=contexto_da_tela)
```

Em `tf2price/painel/app.py`, dentro do `if contexto is not None:` de `criar_app`:

```python
    if contexto is not None:
        from tf2price.painel import consulta, paginas, varredura

        app.include_router(paginas.ROTEADOR)
        app.include_router(consulta.ROTEADOR)
        app.include_router(varredura.ROTEADOR)
```

- [ ] **Step 4: Escrever os templates**

`tf2price/painel/templates/scan.html`:

```html
{% extends "base.html" %}
{% block title %}Market Scan · briefcase.tf{% endblock %}
{% block page_eyebrow %}Steam → trade{% endblock %}
{% block page_title %}Market Scan{% endblock %}
{% block content %}
<section data-page="scan" class="scan-status" aria-labelledby="scan-status-title">
  <h2 id="scan-status-title" class="visually-hidden">Scanner status</h2>
  {% include "_scan_estado.html" %}
</section>

<form id="scan-filtros" class="scan-filters" method="get" action="/scan"
      hx-get="/scan" hx-target="#scan-tabela" hx-push-url="true" hx-trigger="change, submit">
  <input type="hidden" name="aba" value="{{ filtros.aba }}">
  <label>Item
    <input type="search" name="q" value="{{ filtros.texto }}" maxlength="100">
  </label>
  <label>Effect
    <select name="efeito">
      <option value="">All effects</option>
      {% for e in efeitos %}
      <option value="{{ e }}"{% if e == filtros.efeito %} selected{% endif %}>{{ e }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Min price (R$)
    <input type="number" name="preco_min" min="0" step="0.01"
           value="{{ '%.2f'|format(filtros.preco_min.as_float) if filtros.preco_min else '' }}">
  </label>
  <label>Max price (R$)
    <input type="number" name="preco_max" min="0" step="0.01"
           value="{{ '%.2f'|format(filtros.preco_max.as_float) if filtros.preco_max else '' }}">
  </label>
  <label>Max backpack.tf age (days)
    <input type="number" name="idade_max" min="1"
           value="{{ filtros.idade_max_bptf_dias if filtros.idade_max_bptf_dias else '' }}">
  </label>
  <label class="scan-filters__check">
    <input type="checkbox" name="so_com_preco" value="1"{% if filtros.so_com_preco %} checked{% endif %}>
    Only with a usable backpack.tf price
  </label>
  <label>Sort by
    <select name="ordem">
      <option value="resultado"{% if filtros.ordem == 'resultado' %} selected{% endif %}>Result (R$)</option>
      <option value="percentual"{% if filtros.ordem == 'percentual' %} selected{% endif %}>Result (%)</option>
      <option value="preco"{% if filtros.ordem == 'preco' %} selected{% endif %}>Steam price</option>
      <option value="idade_bptf"{% if filtros.ordem == 'idade_bptf' %} selected{% endif %}>backpack.tf price age</option>
    </select>
  </label>
  <button class="button button--quiet" type="submit">Apply</button>
</form>

<div id="scan-tabela" aria-live="polite">{% include "_scan_tabela.html" %}</div>
{% endblock %}
```

`tf2price/painel/templates/_scan_estado.html`:

```html
<dl class="scan-status__grid">
  <div>
    <dt class="scope-label">LAST FULL SCAN</dt>
    <dd>{% if completa %}Finished {{ ha(completa.fim) }} · {{ completa.nomes_lidos }} items{% else %}No full scan yet{% endif %}</dd>
  </div>
  <div>
    <dt class="scope-label">NOW</dt>
    <dd>
      {% if rodando and ultima %}Scanning for {{ idade(ultima.inicio) }} · {{ ultima.nomes_lidos }} items seen, {{ ultima.fundas_feitas }} re-read
      {% elif not config.ligada %}Scanner is off
      {% else %}Idle · every {{ config.intervalo_min }} min{% endif %}
    </dd>
  </div>
  <div>
    <dt class="scope-label">COVERAGE</dt>
    <dd>{{ cobertura.nomes }} items · {{ cobertura.listagens }} listings</dd>
  </div>
</dl>
{% if ultima and ultima.motivo_parada == '429' %}
<p class="evidence-note evidence-note--stale" role="status">The last scan stopped because Steam is rate limiting this server. The listings below are from earlier reads; each row shows its own age.</p>
{% endif %}
{% if not cotacao %}
<p class="evidence-note evidence-note--stale" role="status">{{ sem_cotacao }}</p>
{% endif %}
```

`tf2price/painel/templates/_scan_tabela.html`:

```html
<nav class="scan-tabs" aria-label="Scan views">
  <a class="scan-tab{% if filtros.aba == 'todas' %} scan-tab--active{% endif %}"
     href="/scan?{{ filtros.query(aba='todas', pagina=1) }}">All listings</a>
  <a class="scan-tab{% if filtros.aba == 'lucro' %} scan-tab--active{% endif %}"
     href="/scan?{{ filtros.query(aba='lucro', pagina=1) }}">Profitable</a>
</nav>
<p class="scan-count">{{ pagina.total }} listings{% if pagina.paginas > 1 %} · page {{ pagina.pagina }} of {{ pagina.paginas }}{% endif %}
  · result = backpack.tf value in keys × Steam key price − Steam price</p>

{% if not pagina.linhas %}
<p class="empty-state">No listings match these filters.</p>
{% else %}
<div class="scan-table-wrap">
  <table class="scan-table">
    <thead>
      <tr>
        <th scope="col">Item</th>
        <th scope="col">Effect</th>
        <th scope="col">Steam price</th>
        <th scope="col">backpack.tf value</th>
        <th scope="col">Result</th>
        <th scope="col">bp.tf age</th>
        <th scope="col">Read</th>
        <th scope="col"><span class="visually-hidden">Links</span></th>
      </tr>
    </thead>
    <tbody>
    {% for l in pagina.linhas %}
      <tr>
        <td>{{ l.listagem.hash_name }}
          {% if l.listagem.mais_na_steam > 0 %}<span class="scan-sub">+{{ l.listagem.mais_na_steam }} more on Steam</span>{% endif %}</td>
        <td>{% if l.arte %}<img class="scan-art" src="{{ l.arte }}" alt="" width="32" height="32" loading="lazy">{% endif %}{{ l.listagem.efeito or 'Effect unknown' }}</td>
        <td>{{ l.listagem.preco }}
          {% if l.preco_em_chaves is not none %}<span class="scan-sub">{{ l.preco_em_chaves|keys }} keys</span>{% endif %}</td>
        <td>{% if l.valor_bptf %}{{ l.valor_bptf }}<span class="scan-sub">{{ l.chaves_bptf|keys }} keys</span>{% else %}—{% endif %}</td>
        <td>
          {% if l.resultado is not none %}
          <span class="scan-result {{ 'scan-result--gain' if l.resultado.cents > 0 else 'scan-result--loss' }}">{{ l.resultado }}</span>
          {% if l.percentual is not none %}<span class="scan-sub">{{ '%+.0f'|format(l.percentual * 100) }}%</span>{% endif %}
          {% else %}
          <span class="scan-sub">{{ l.motivo }}</span>
          {% endif %}
        </td>
        <td>{{ '%d d'|format(l.idade_bptf_dias) if l.idade_bptf_dias is not none else '—' }}</td>
        <td>{{ ha(l.listagem.lido_em) }}</td>
        <td class="scan-links">
          {% if l.listagem.efeito %}<a href="/cases/new?nome={{ l.listagem.hash_name|urlencode }}&amp;efeito={{ l.listagem.efeito|urlencode }}">Open case</a>{% endif %}
          <a href="https://steamcommunity.com/market/listings/440/{{ l.listagem.hash_name|urlencode }}" target="_blank" rel="noopener noreferrer">Steam</a>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% if pagina.paginas > 1 %}
<nav class="scan-pages" aria-label="Pages">
  {% if pagina.pagina > 1 %}
  <a href="/scan?{{ filtros.query(pagina=pagina.pagina - 1) }}"
     hx-get="/scan?{{ filtros.query(pagina=pagina.pagina - 1) }}" hx-target="#scan-tabela" hx-push-url="true">Previous</a>
  {% endif %}
  {% if pagina.pagina < pagina.paginas %}
  <a href="/scan?{{ filtros.query(pagina=pagina.pagina + 1) }}"
     hx-get="/scan?{{ filtros.query(pagina=pagina.pagina + 1) }}" hx-target="#scan-tabela" hx-push-url="true">Next</a>
  {% endif %}
</nav>
{% endif %}
{% endif %}
```

Em `tf2price/painel/templates/_navigation.html`, acrescente depois do link "Case Files":

```html
    <a href="/scan"{% if request.url.path == "/scan" %} aria-current="page"{% endif %}>Market Scan</a>
```

No fim de `tf2price/painel/static/briefcase.css`:

```css
/* Market Scan */
.scan-status__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 1rem; margin: 0 0 1rem; }
.scan-status__grid dd { margin: .35rem 0 0; font-family: var(--font-mono); font-size: .85rem; }
.scan-filters { display: flex; flex-wrap: wrap; align-items: flex-end; gap: .75rem 1rem; margin: 1.5rem 0; padding: 1rem; background: var(--ink-panel); border: 1px solid var(--ink-blue); }
.scan-filters label { display: grid; gap: .3rem; font: 600 .75rem var(--font-condensed); text-transform: uppercase; }
.scan-filters__check { display: flex !important; align-items: center; gap: .5rem; }
.scan-filters input, .scan-filters select { min-height: 44px; font: 500 .85rem var(--font-mono); }
.scan-tabs { display: flex; gap: .5rem; margin-bottom: .75rem; }
.scan-tab { padding: .5rem .9rem; border: 1px solid var(--ink-blue); color: var(--paper); text-decoration: none; font: 700 .8rem var(--font-condensed); text-transform: uppercase; }
.scan-tab--active { border-color: var(--warning); color: var(--warning); }
.scan-count { font-family: var(--font-mono); font-size: .75rem; color: color-mix(in srgb, var(--paper) 70%, transparent); }
.scan-table-wrap { overflow-x: auto; border: 1px solid var(--ink-blue); }
.scan-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.scan-table th, .scan-table td { padding: .6rem .75rem; text-align: left; vertical-align: top; border-bottom: 1px dotted var(--ink-blue); }
.scan-table th { font: 700 .72rem var(--font-condensed); text-transform: uppercase; background: var(--ink-panel); }
.scan-sub { display: block; margin-top: .2rem; font-family: var(--font-mono); font-size: .72rem; color: color-mix(in srgb, var(--paper) 65%, transparent); }
.scan-art { vertical-align: middle; margin-right: .4rem; }
.scan-result { font-family: var(--font-mono); font-weight: 700; }
.scan-result--gain { color: #7fd48a; }
.scan-result--loss { color: var(--rust-stamp); }
.scan-links { white-space: nowrap; }
.scan-links a + a { margin-left: .6rem; }
.scan-pages { display: flex; gap: 1rem; margin-top: 1rem; }
```

- [ ] **Step 5: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -q`
Expected: PASS. Se `test_briefcase_js.cjs` ou algum teste de marca varrer o CSS, confira que continua passando.

- [ ] **Step 6: Ver no navegador**

Run: `.\.venv\Scripts\python.exe -m tf2price.painel.app`, entre e abra `http://127.0.0.1:8000/scan`. Com o banco local vazio, deve aparecer "No full scan yet", "Scanner is off" e "No listings match these filters.", sem erro 500. Confira também a largura de celular (~400 px): a tabela rola na horizontal dentro do próprio contêiner, e a página não.

- [ ] **Step 7: Commit**

```bash
git add tf2price/painel/varredura.py tf2price/painel/templates/scan.html tf2price/painel/templates/_scan_estado.html tf2price/painel/templates/_scan_tabela.html tf2price/painel/templates/_navigation.html tf2price/painel/app.py tf2price/painel/static/briefcase.css tests/painel/test_scan.py tests/painel/test_accessibility.py tests/painel/test_english_ui.py
git commit -m "Mostra todas as listagens varridas na pagina Market Scan"
```

---

### Task 10: Painel admin e documentação

**Files:**
- Modify: `tf2price/painel/admin.py`
- Modify: `tf2price/painel/templates/admin.html`
- Modify: `AGENTS.md`, `README.md`, `docs/superpowers/specs/2026-09-22-varredura-unusual-design.md`
- Test: `tests/painel/test_admin_varredura.py`

**Interfaces:**
- Consumes: `repo.ler_config/gravar_config/ultimas_rodadas/INTERVALO_MINIMO_MIN/IDADE_MINIMA_FUNDA_H`, `ROTULO_DA_PARADA` de `tf2price.painel.varredura`, `request.app.state.agendador` (Task 7)
- Produces: `POST /admin/varredura`, `POST /admin/varredura/rodar`

- [ ] **Step 1: Escrever os testes que falham**

`tests/painel/test_admin_varredura.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as contas_repo
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from tf2price.varredura import repositorio as repo

SENHA = "uma senha longa"


class _AgendadorFalso:
    def __init__(self, livre=True):
        self.livre = livre
        self.disparos = 0
        self.rodando = not livre

    def disparar_em_segundo_plano(self):
        self.disparos += 1
        return self.livre


def _entra(engine, nome="gusco", admin=True, agendador=None):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = contas_repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine, agendador=agendador))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente


def test_admin_mostra_a_configuracao_padrao(engine):
    texto = _entra(engine).get("/admin").text
    assert "Market scan" in texto
    assert 'name="intervalo_min"' in texto and 'value="180"' in texto
    assert "No scans yet." in texto


def test_salvar_configuracao(engine):
    admin = _entra(engine)
    r = admin.post("/admin/varredura",
                   data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    assert r.status_code == 200
    assert "Scanner settings saved." in r.text
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.Config(True, 90, 12)


def test_desmarcar_desliga(engine):
    admin = _entra(engine)
    admin.post("/admin/varredura", data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    admin.post("/admin/varredura", data={"intervalo_min": "90", "idade_max_funda_h": "12"})
    with engine.begin() as conn:
        assert not repo.ler_config(conn).ligada


@pytest.mark.parametrize("dados, mensagem", [
    ({"ligada": "1", "intervalo_min": "59", "idade_max_funda_h": "12"}, "at least 60 minutes"),
    ({"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "0"}, "at least 1 hour"),
    ({"ligada": "1", "intervalo_min": "abc", "idade_max_funda_h": "12"}, "whole numbers"),
])
def test_configuracao_invalida_e_recusada(engine, dados, mensagem):
    admin = _entra(engine)
    r = admin.post("/admin/varredura", data=dados)
    assert mensagem in r.text
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.PADRAO


def test_membro_comum_nao_configura(engine):
    _entra(engine)
    comum = _entra(engine, nome="amiga", admin=False)
    r = comum.post("/admin/varredura", data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    assert r.status_code == 403


def test_origem_de_outro_site_e_recusada(engine):
    admin = _entra(engine)
    r = admin.post("/admin/varredura",
                   data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"},
                   headers={"origin": "https://outro.site"})
    assert r.status_code == 403


def test_run_now_dispara(engine):
    agendador = _AgendadorFalso()
    r = _entra(engine, agendador=agendador).post("/admin/varredura/rodar")
    assert agendador.disparos == 1
    assert "Scan started." in r.text


def test_run_now_com_rodada_em_curso(engine):
    r = _entra(engine, agendador=_AgendadorFalso(livre=False)).post("/admin/varredura/rodar")
    assert "A scan is already running." in r.text


def test_run_now_sem_agendador(engine):
    r = _entra(engine).post("/admin/varredura/rodar")
    assert "The scanner is not available in this process." in r.text


def test_lista_as_rodadas_com_rotulo_em_ingles(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, db.agora())
        repo.fechar_rodada(conn, rid, db.agora(), nomes_lidos=12, fundas_feitas=3,
                           falhas=1, motivo=repo.MOTIVO_429)
    texto = _entra(engine).get("/admin").text
    assert "Stopped: Steam rate limit" in texto
    assert "interrompida" not in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_admin_varredura.py -v`
Expected: FAIL ("Market scan" ausente; 404/405 nas rotas novas)

- [ ] **Step 3: Implementar em `tf2price/painel/admin.py`**

Nos imports:

```python
from tf2price.painel.varredura import ROTULO_DA_PARADA
from tf2price.varredura import repositorio as varredura_repo
```

Troque `_tela_admin` por:

```python
def _tela_admin(
    request: Request,
    conn: Connection,
    usuario: Usuario,
    link=None,
    erro: str | None = None,
    varredura_msg: str | None = None,
):
    agendador = request.app.state.agendador
    return TEMPLATES.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "usuario": usuario,
            "usuarios": repo.listar_usuarios(conn),
            "pedidos": repo_pedidos.listar_pendentes(conn),
            "link": link,
            "erro": erro,
            "varredura": varredura_repo.ler_config(conn),
            "rodadas": varredura_repo.ultimas_rodadas(conn),
            "rodando": bool(agendador and agendador.rodando),
            "rotulo_da_parada": ROTULO_DA_PARADA,
            "intervalo_minimo": varredura_repo.INTERVALO_MINIMO_MIN,
            "varredura_msg": varredura_msg,
        },
    )
```

Acrescente no fim do arquivo:

```python
@ROTEADOR.post("/admin/varredura", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def salvar_varredura(
    request: Request,
    ligada: str = Form(""),
    intervalo_min: str = Form(""),
    idade_max_funda_h: str = Form(""),
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    # Texto, e não `int` no Form: um valor inválido tem de voltar como
    # mensagem na tela do admin, não como o 422 cru do FastAPI.
    try:
        config = varredura_repo.Config(
            ligada=ligada == "1",
            intervalo_min=int(intervalo_min),
            idade_max_funda_h=int(idade_max_funda_h),
        )
    except ValueError:
        return _tela_admin(request, conn, usuario, erro="Scanner settings must be whole numbers.")
    if config.intervalo_min < varredura_repo.INTERVALO_MINIMO_MIN:
        return _tela_admin(
            request, conn, usuario,
            erro=f"The interval must be at least {varredura_repo.INTERVALO_MINIMO_MIN} minutes.",
        )
    if config.idade_max_funda_h < varredura_repo.IDADE_MINIMA_FUNDA_H:
        return _tela_admin(request, conn, usuario, erro="The re-read age must be at least 1 hour.")
    varredura_repo.gravar_config(conn, config, db.agora())
    return _tela_admin(request, conn, usuario, varredura_msg="Scanner settings saved.")


@ROTEADOR.post("/admin/varredura/rodar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def rodar_varredura(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    agendador = request.app.state.agendador
    if agendador is None:
        return _tela_admin(request, conn, usuario,
                           erro="The scanner is not available in this process.")
    if not agendador.disparar_em_segundo_plano():
        return _tela_admin(request, conn, usuario, erro="A scan is already running.")
    return _tela_admin(request, conn, usuario, varredura_msg="Scan started.")
```

- [ ] **Step 4: Acrescentar a seção em `admin.html`**

Antes da `<section class="admin-people" ...>`:

```html
<section class="admin-scan" aria-labelledby="scan-title">
  <h2 id="scan-title">Market scan</h2>
  {% if varredura_msg %}<div class="admin-link" role="status"><p>{{ varredura_msg }}</p></div>{% endif %}
  <form method="post" action="/admin/varredura" class="scan-filters">
    <label class="scan-filters__check">
      <input type="checkbox" name="ligada" value="1"{% if varredura.ligada %} checked{% endif %}>
      Scanner enabled
    </label>
    <label>Interval between scans (minutes)
      <input type="number" name="intervalo_min" min="{{ intervalo_minimo }}" value="{{ varredura.intervalo_min }}" required>
    </label>
    <label>Re-read unchanged items after (hours)
      <input type="number" name="idade_max_funda_h" min="1" value="{{ varredura.idade_max_funda_h }}" required>
    </label>
    <button class="button button--primary" type="submit">Save scanner settings</button>
  </form>
  <form method="post" action="/admin/varredura/rodar">
    <button class="button button--quiet" type="submit"{% if rodando %} disabled{% endif %}>{{ 'Scan running…' if rodando else 'Run now' }}</button>
  </form>
  {% if rodadas %}
  <div class="scan-table-wrap">
    <table class="scan-table">
      <thead><tr>
        <th scope="col">Started (UTC)</th><th scope="col">Duration</th><th scope="col">Items seen</th>
        <th scope="col">Re-read</th><th scope="col">Failures</th><th scope="col">Outcome</th>
      </tr></thead>
      <tbody>
      {% for r in rodadas %}
        <tr>
          <td>{{ r.inicio.strftime('%Y-%m-%d %H:%M') }}</td>
          <td>{{ ((r.fim - r.inicio).total_seconds() // 60)|int ~ ' min' if r.fim else '—' }}</td>
          <td>{{ r.nomes_lidos }}</td>
          <td>{{ r.fundas_feitas }}</td>
          <td>{{ r.falhas }}</td>
          <td>{{ rotulo_da_parada.get(r.motivo_parada, r.motivo_parada) }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p>No scans yet.</p>
  {% endif %}
</section>
```

Em `briefcase.css`, acrescente `.admin-scan { display: grid; gap: 1rem; margin-bottom: 2rem; }` junto das regras `.admin-*`.

- [ ] **Step 5: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -q`
Expected: PASS

- [ ] **Step 6: Documentação**

1. `AGENTS.md`, seção "Mapa do repositório", depois de `tf2price/acompanhamento/`:

   ```markdown
   - `tf2price/varredura/`: varredura periódica dos cosméticos Unusual — escopo
     pelo schema da Valve, rodada em dois níveis (busca rasa; página só onde a
     assinatura mudou), agendador de fundo e cálculo do resultado na leitura.
   ```

   E na seção "Dados gerados e deploy", acrescente `tf2price/data/cosmeticos.json` (gerado por `scripts/fetch_cosmeticos.py`) à frase sobre dados gerados.

2. `README.md`: um parágrafo curto sob o uso do produto dizendo que a página **Market Scan** lista as listagens de cosméticos Unusual varridas em segundo plano, que o admin liga, desliga e define o intervalo em `/admin` (mínimo de 60 min), e que o resultado é "valor da bp.tf em chaves × preço da chave − preço na Steam", com a idade do preço da bp.tf como filtro.

3. Spec `docs/superpowers/specs/2026-09-22-varredura-unusual-design.md`: registre as cinco decisões da seção "Decisões que refinam a spec" deste plano. Em §3.3, troque `menor_preco_cents` por `preco_usd_cents` e acrescente `n_guardadas`. Em §4 item 4, deixe "duas rodadas completas". Em §6, registre o tratamento do preço mais velho que o filtro. Se a Task 5 foi pulada, em §9 escreva que a página não pagina e a tela mostra "+N more on Steam".

Run: `git diff --check`
Expected: sem saída.

- [ ] **Step 7: Suíte completa**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: todos passam.

- [ ] **Step 8: Commit**

```bash
git add tf2price/painel/admin.py tf2price/painel/templates/admin.html tf2price/painel/static/briefcase.css tests/painel/test_admin_varredura.py AGENTS.md README.md docs/superpowers/specs/2026-09-22-varredura-unusual-design.md
git commit -m "Configura a varredura no painel admin e documenta a feature"
```

---

### Task 11: Primeira rodada real, local

Esta task confere, contra a Steam de verdade, o que os dublês não provam. Ela não muda código, a menos que ache defeito. Se achar, abra um teste de regressão antes do conserto.

- [ ] **Step 1: Subir o painel local e disparar uma rodada**

Run: `.\.venv\Scripts\python.exe -m tf2price.painel.app`. Em `/admin`, deixe o scanner **desligado** e clique **Run now**.

- [ ] **Step 2: Acompanhar pelo log**

Espere as linhas `[varredura] rodada N: ...`. Anote:
- quantos nomes a passada rasa aceitou (é a verificação 3 da spec);
- quanto tempo a rodada levou;
- se parou por 429, em qual requisição.

- [ ] **Step 3: Conferir a página**

Abra `/scan`. Confira à mão três linhas, cada uma contra a tela de consulta ("Open case"): o preço da listagem e o valor da bp.tf têm de bater com o que a consulta mostra para o mesmo item e efeito.

- [ ] **Step 4: Registrar e commitar**

Acrescente uma seção "Primeira rodada" em `docs/superpowers/findings/2026-09-22-varredura-verificacoes.md` com os números do Step 2 e o resultado da conferência.

```bash
git add docs/superpowers/findings/2026-09-22-varredura-verificacoes.md
git commit -m "Registra a primeira rodada real da varredura"
```
