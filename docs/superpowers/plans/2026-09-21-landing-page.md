# Landing page do briefcase.tf — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Servir em `GET /` uma landing pública que explica o briefcase.tf e coleta pedidos de convite, listados e resolvidos em `/admin`, sem abrir o app.

**Architecture:** Um roteador novo, `tf2price/painel/publico.py`, sempre montado, assume `/`: sem sessão renderiza `landing.html`; com sessão (e `Contexto` presente) delega à função do Overview que sai de `paginas.py`. Os pedidos ficam na tabela `pedido_acesso` (SQLAlchemy Core), com validação e regras em `tf2price/contas/pedidos.py`, SQL em `tf2price/contas/repositorio_pedidos.py` e um limitador por IP em memória em `tf2price/painel/limite.py`. O admin ganha a seção "Access requests" com duas ações POST.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, SQLAlchemy Core, pytest com `TestClient` e SQLite em memória.

**Spec:** `docs/superpowers/specs/2026-09-21-landing-page-design.md`

## Global Constraints

- Interface em inglês; código, comentários e mensagens de commit em português, como o resto do repositório.
- Nenhum teste ou import acessa a rede. A landing não chama Steam, backpack.tf, cotação nem índice.
- Datas persistidas em UTC ingênuo via `db.agora()`.
- SQL só nos módulos de repositório; compatível com SQLite (testes) e PostgreSQL (produção). Limites de tamanho validados em código antes do insert.
- Toda rota mutável tem `Depends(ses.mesma_origem)`.
- Limites: contato 1–200 caracteres; observação até 1000; 3 envios por IP por hora; teto de 200 pedidos `pendente`.
- Perfil Steam aceito: `steamcommunity.com/id/<2–32 de [A-Za-z0-9_-]>` ou `steamcommunity.com/profiles/<17 dígitos ASCII>`, com ou sem `http(s)://`, `www.` e barra final; gravado como `https://steamcommunity.com/id/<minúsculas>` ou `https://steamcommunity.com/profiles/<id>`.
- Status do pedido: `pendente`, `convidado`, `descartado`.
- Ordem no POST: limite por IP → honeypot → validação → teto global → deduplicação → insert.
- Respostas: sucesso, honeypot e duplicado → `303` para `/?requested=1#access`; validação → `422`; limite por IP → `429`; teto → `503`; outra origem → `403`.
- Landing sem JavaScript; o Case File de exemplo usa só a arte real `/arte/13.webp` (Burning Flames), nenhuma render de chapéu, e o selo "Sample case · Fictional values".
- Comando de testes (PowerShell): `.\.venv\Scripts\python.exe -m pytest`. Antes de cada commit, `git diff --check`.
- Toda mensagem de commit termina com:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo
  ```

## Mapa de arquivos

| Arquivo | Papel |
| --- | --- |
| `tf2price/contas/pedidos.py` (novo) | Normalização do perfil, validação do formulário, registro e resolução de pedidos |
| `tf2price/contas/repositorio_pedidos.py` (novo) | Todo o SQL de `pedido_acesso` |
| `tf2price/contas/modelo.py` | + dataclass `PedidoAcesso` |
| `tf2price/db.py` | + tabela `pedido_acesso` |
| `tf2price/painel/limite.py` (novo) | `LimitePorChave`: janela deslizante em memória, com trava e relógio injetável |
| `tf2price/painel/publico.py` (novo) | `GET /` e `POST /access-request` |
| `tf2price/painel/paginas.py` | Overview deixa de ser rota e vira `renderizar_overview` |
| `tf2price/painel/app.py` | Monta `publico.ROTEADOR` e cria `app.state.limite_pedidos` |
| `tf2price/painel/admin.py` | + lista de pedidos e rotas convidar/descartar |
| `tf2price/painel/templates/landing.html` (novo) | Landing completa |
| `tf2price/painel/templates/admin.html` | + seção "Access requests" |
| `tf2price/painel/static/landing.css` (novo) | Estilos só da landing |
| `tf2price/painel/static/briefcase.css` | + `.admin-requests` |
| `tests/contas/test_pedidos.py` (novo) | Regras puras e com banco dos pedidos |
| `tests/painel/test_limite.py` (novo) | Limitador |
| `tests/painel/test_publico.py` (novo) | Landing e POST |
| `tests/painel/test_entrar.py` | Ajuste: `/` sem sessão não redireciona mais |
| `tests/painel/test_admin.py` | + testes da seção de pedidos |
| `README.md`, spec | Documentação |

---

### Task 1: Normalização do perfil e validação do pedido

**Files:**
- Create: `tf2price/contas/pedidos.py`
- Test: `tests/contas/test_pedidos.py`

**Interfaces:**
- Produces:
  - `normalizar_perfil_steam(texto: str) -> str | None`
  - `@dataclass(frozen=True) class Pedido: perfil_steam: str; contato: str; observacao: str | None`
  - `validar_pedido(perfil_steam: str, contato: str, observacao: str) -> tuple[Pedido | None, dict[str, str]]` — erros indexados pelos nomes de campo `perfil_steam`, `contato`, `observacao`
  - constantes `CONTATO_MAXIMO = 200`, `OBSERVACAO_MAXIMA = 1000`

- [ ] **Step 1: Escrever os testes que falham**

`tests/contas/test_pedidos.py`:

```python
from __future__ import annotations

import pytest

from tf2price.contas import pedidos

ID64 = "76561197960287930"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("https://steamcommunity.com/id/Gusco/", "https://steamcommunity.com/id/gusco"),
        ("steamcommunity.com/id/gus-co_1", "https://steamcommunity.com/id/gus-co_1"),
        ("http://www.steamcommunity.com/id/ab", "https://steamcommunity.com/id/ab"),
        ("HTTPS://STEAMCOMMUNITY.COM/id/Gusco", "https://steamcommunity.com/id/gusco"),
        (f"www.steamcommunity.com/profiles/{ID64}", f"https://steamcommunity.com/profiles/{ID64}"),
        (f"https://steamcommunity.com/profiles/{ID64}/", f"https://steamcommunity.com/profiles/{ID64}"),
        ("  https://steamcommunity.com/id/gusco  ", "https://steamcommunity.com/id/gusco"),
    ],
)
def test_normaliza_perfis_aceitos(entrada, esperado):
    assert pedidos.normalizar_perfil_steam(entrada) == esperado


@pytest.mark.parametrize(
    "entrada",
    [
        "",
        "gusco",
        "https://evil.example/steamcommunity.com/id/gusco",
        "https://steamcommunity.com.evil.example/id/gusco",
        "https://steamcommunity.com/id/g",
        "https://steamcommunity.com/id/" + "a" * 33,
        "https://steamcommunity.com/id/gus.co",
        "https://steamcommunity.com/profiles/123",
        f"https://steamcommunity.com/profiles/{ID64}0",
        # Dígitos de largura total: `\d` do Python aceitaria.
        "https://steamcommunity.com/profiles/７６５６１１９７９６０２８７９３０",
        "https://steamcommunity.com/id/gusco/inventory",
        "https://steamcommunity.com/id/gusco?x=1",
        "https://steamcommunity.com/id/gusco#topo",
        "ftp://steamcommunity.com/id/gusco",
        "https://steamcommunity.com/id/gusco\n",
    ],
)
def test_recusa_o_que_nao_e_perfil(entrada):
    assert pedidos.normalizar_perfil_steam(entrada) is None


def test_pedido_valido_sai_normalizado():
    pedido, erros = pedidos.validar_pedido(
        "steamcommunity.com/id/Gusco", "  gusco#1234 no Discord ", "   "
    )
    assert erros == {}
    assert pedido == pedidos.Pedido(
        perfil_steam="https://steamcommunity.com/id/gusco",
        contato="gusco#1234 no Discord",
        observacao=None,
    )


def test_observacao_preenchida_e_preservada_sem_espacos_nas_bordas():
    pedido, _ = pedidos.validar_pedido(
        "steamcommunity.com/id/gusco", "discord", "  coleciono Team Captains  "
    )
    assert pedido.observacao == "coleciono Team Captains"


def test_erros_por_campo():
    pedido, erros = pedidos.validar_pedido("gusco", "   ", "x" * 1001)
    assert pedido is None
    assert set(erros) == {"perfil_steam", "contato", "observacao"}


def test_limites_de_tamanho_sao_inclusivos():
    pedido, erros = pedidos.validar_pedido(
        "steamcommunity.com/id/gusco", "c" * 200, "o" * 1000
    )
    assert erros == {} and pedido is not None
    _, erros = pedidos.validar_pedido("steamcommunity.com/id/gusco", "c" * 201, "")
    assert set(erros) == {"contato"}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_pedidos.py -q`
Expected: FAIL — `ImportError: cannot import name 'pedidos'`.

- [ ] **Step 3: Implementar**

`tf2price/contas/pedidos.py`:

```python
"""Pedidos de acesso: o que a landing aceita e como o admin os resolve.

A entrada é pública. Por isso o perfil da Steam só passa se tiver exatamente
uma das duas formas que a Steam usa, e é gravado numa forma canônica: é essa
forma que o admin abre como link, e é por ela que dois pedidos da mesma
pessoa se reconhecem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTATO_MAXIMO = 200
OBSERVACAO_MAXIMA = 1000

# `[0-9]` e não `\d`: em `str`, `\d` aceita dígitos de qualquer escrita.
# `fullmatch` ancora nas duas pontas sem o furo do `$` antes de "\n".
_PERFIL = re.compile(
    r"(?:https?://)?(?:www\.)?steamcommunity\.com/"
    r"(?:id/(?P<nome>[A-Za-z0-9_-]{2,32})|profiles/(?P<id>[0-9]{17}))/?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Pedido:
    perfil_steam: str
    contato: str
    observacao: str | None


def normalizar_perfil_steam(texto: str) -> str | None:
    casou = _PERFIL.fullmatch(texto.strip(" \t"))
    if casou is None:
        return None
    if casou["id"]:
        return f"https://steamcommunity.com/profiles/{casou['id']}"
    # A Steam não diferencia maiúsculas no nome personalizado.
    return f"https://steamcommunity.com/id/{casou['nome'].lower()}"


def validar_pedido(
    perfil_steam: str, contato: str, observacao: str
) -> tuple[Pedido | None, dict[str, str]]:
    erros: dict[str, str] = {}
    perfil = normalizar_perfil_steam(perfil_steam)
    if perfil is None:
        erros["perfil_steam"] = (
            "Enter a steamcommunity.com/id/… or steamcommunity.com/profiles/… link."
        )
    contato = contato.strip()
    if not contato:
        erros["contato"] = "Tell us where to send the invite."
    elif len(contato) > CONTATO_MAXIMO:
        erros["contato"] = f"Use at most {CONTATO_MAXIMO} characters."
    observacao = observacao.strip()
    if len(observacao) > OBSERVACAO_MAXIMA:
        erros["observacao"] = f"Use at most {OBSERVACAO_MAXIMA} characters."
    if erros:
        return None, erros
    return Pedido(perfil_steam=perfil, contato=contato, observacao=observacao or None), {}
```

Obs.: `strip(" \t")` e não `strip()`, para que `"...gusco\n"` continue recusado pelo teste (quebra de linha não é espaço acidental de colagem de URL; recusar é o lado seguro).

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_pedidos.py -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```powershell
git add tf2price/contas/pedidos.py tests/contas/test_pedidos.py
git diff --cached --check
git commit -m "Valida e normaliza o pedido de acesso da landing" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 2: Tabela, repositório e resolução dos pedidos

**Files:**
- Modify: `tf2price/db.py` (nova tabela depois de `acompanhado`)
- Modify: `tf2price/contas/modelo.py` (nova dataclass no fim)
- Create: `tf2price/contas/repositorio_pedidos.py`
- Modify: `tf2price/contas/pedidos.py`
- Test: `tests/contas/test_pedidos.py`

**Interfaces:**
- Consumes: `Pedido` (Task 1); `servico.convidar(conn, *, criado_por, quando) -> str` (existente).
- Produces:
  - `db.pedido_acesso` (Table)
  - `modelo.PedidoAcesso(id, perfil_steam, contato, observacao, criado_em, status, resolvido_em)`
  - `repositorio_pedidos`: `PENDENTE`, `CONVIDADO`, `DESCARTADO`; `criar_pedido(conn, *, perfil_steam, contato, observacao, quando) -> int`; `contar_pendentes(conn) -> int`; `existe_pendente(conn, perfil_steam) -> bool`; `listar_pendentes(conn) -> list[PedidoAcesso]`; `resolver(conn, pedido_id, status, quando) -> bool`
  - `pedidos`: `TETO_DE_PENDENTES = 200`; `class Resultado(Enum): GRAVADO, DUPLICADO, FECHADO`; `registrar_pedido(conn, pedido: Pedido, quando) -> Resultado`; `class PedidoJaResolvido(Exception)`; `convidar_pedido(conn, pedido_id: int, *, admin_id: int, quando) -> str`; `descartar_pedido(conn, pedido_id: int, *, quando) -> None`

- [ ] **Step 1: Escrever os testes que falham** (acrescentar a `tests/contas/test_pedidos.py`)

```python
from datetime import timedelta

from sqlalchemy import select

from tf2price import db
from tf2price.contas import repositorio as contas_repo
from tf2price.contas import repositorio_pedidos as repo
from tf2price.contas import servico, tokens

PERFIL = "https://steamcommunity.com/id/gusco"


def _pedido(perfil=PERFIL):
    return pedidos.Pedido(perfil_steam=perfil, contato="discord gusco", observacao=None)


def _admin(conn):
    token = servico.convite_de_partida(conn, db.agora())
    return servico.aceitar_convite(
        conn, token, nome="gusco", senha="uma senha longa", quando=db.agora()
    )


def _status(conn, pedido_id):
    return conn.execute(
        select(db.pedido_acesso.c.status, db.pedido_acesso.c.resolvido_em)
        .where(db.pedido_acesso.c.id == pedido_id)
    ).one()


def test_registrar_grava_um_pendente(engine):
    quando = db.agora()
    with engine.begin() as conn:
        assert pedidos.registrar_pedido(conn, _pedido(), quando) is pedidos.Resultado.GRAVADO
        [linha] = repo.listar_pendentes(conn)
    assert linha.perfil_steam == PERFIL
    assert linha.contato == "discord gusco"
    assert linha.observacao is None
    assert linha.criado_em == quando
    assert linha.status == repo.PENDENTE
    assert linha.resolvido_em is None


def test_mesmo_perfil_pendente_nao_duplica(engine):
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.DUPLICADO
        assert repo.contar_pendentes(conn) == 1


def test_perfil_ja_resolvido_pode_pedir_de_novo(engine):
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.GRAVADO


def test_teto_de_pendentes_fecha_novos_pedidos(engine):
    with engine.begin() as conn:
        for n in range(pedidos.TETO_DE_PENDENTES):
            repo.criar_pedido(
                conn, perfil_steam=f"https://steamcommunity.com/id/p{n}",
                contato="c", observacao=None, quando=db.agora(),
            )
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.FECHADO
        assert repo.contar_pendentes(conn) == pedidos.TETO_DE_PENDENTES


def test_listar_pendentes_vem_do_mais_antigo_e_ignora_resolvidos(engine):
    base = db.agora()
    with engine.begin() as conn:
        novo = repo.criar_pedido(conn, perfil_steam=PERFIL + "2", contato="c",
                                 observacao=None, quando=base)
        velho = repo.criar_pedido(conn, perfil_steam=PERFIL + "1", contato="c",
                                  observacao=None, quando=base - timedelta(hours=1))
        resolvido = repo.criar_pedido(conn, perfil_steam=PERFIL + "3", contato="c",
                                      observacao=None, quando=base - timedelta(hours=2))
        repo.resolver(conn, resolvido, repo.DESCARTADO, base)
        assert [p.id for p in repo.listar_pendentes(conn)] == [velho, novo]


def test_convidar_pedido_cria_convite_e_marca_o_pedido(engine):
    quando = db.agora()
    with engine.begin() as conn:
        admin = _admin(conn)
        pedidos.registrar_pedido(conn, _pedido(), quando)
        [linha] = repo.listar_pendentes(conn)
        token = pedidos.convidar_pedido(conn, linha.id, admin_id=admin.id, quando=quando)
        convite = contas_repo.convite_por_hash(conn, tokens.hash_de(token))
        assert convite is not None and convite.criado_por == admin.id
        assert tuple(_status(conn, linha.id)) == (repo.CONVIDADO, quando)


def test_descartar_pedido_marca_descartado(engine):
    quando = db.agora()
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), quando)
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=quando)
        assert tuple(_status(conn, linha.id)) == (repo.DESCARTADO, quando)


def test_pedido_resolvido_ou_inexistente_nao_muda_de_novo(engine):
    with engine.begin() as conn:
        admin = _admin(conn)
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.convidar_pedido(conn, linha.id, admin_id=admin.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.descartar_pedido(conn, 9999, quando=db.agora())
        assert _status(conn, linha.id).status == repo.DESCARTADO
```

Os imports novos (`timedelta`, `select`, `db`, `contas_repo`, `repo`, `servico`, `tokens`) vão para o topo do arquivo, junto dos da Task 1. `servico.aceitar_convite` devolve o `Usuario` criado, por isso `_admin` usa `admin.id` direto.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_pedidos.py -q`
Expected: FAIL — `ImportError` de `repositorio_pedidos` / `AttributeError: pedido_acesso`.

- [ ] **Step 3: Implementar a tabela** — em `tf2price/db.py`, depois de `acompanhado`:

```python
pedido_acesso = Table(
    "pedido_acesso",
    METADATA,
    Column("id", Integer, primary_key=True),
    # Forma canônica (contas/pedidos.py): é ela que o admin abre como link.
    Column("perfil_steam", String(120), nullable=False),
    Column("contato", String(200), nullable=False),
    Column("observacao", String(1000), nullable=True),
    Column("criado_em", DateTime, nullable=False),
    Column("status", String(20), nullable=False),  # pendente, convidado, descartado
    Column("resolvido_em", DateTime, nullable=True),
)
```

- [ ] **Step 4: Implementar o modelo** — no fim de `tf2price/contas/modelo.py`:

```python
@dataclass(frozen=True)
class PedidoAcesso:
    id: int
    perfil_steam: str
    contato: str
    observacao: str | None
    criado_em: datetime
    status: str
    resolvido_em: datetime | None
```

- [ ] **Step 5: Implementar o repositório** — `tf2price/contas/repositorio_pedidos.py`:

```python
"""Todo o SQL dos pedidos de acesso mora aqui."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas.modelo import PedidoAcesso

PENDENTE = "pendente"
CONVIDADO = "convidado"
DESCARTADO = "descartado"

_T = db.pedido_acesso


def _para_pedido(linha) -> PedidoAcesso:
    return PedidoAcesso(
        id=linha.id,
        perfil_steam=linha.perfil_steam,
        contato=linha.contato,
        observacao=linha.observacao,
        criado_em=linha.criado_em,
        status=linha.status,
        resolvido_em=linha.resolvido_em,
    )


def criar_pedido(
    conn: Connection,
    *,
    perfil_steam: str,
    contato: str,
    observacao: str | None,
    quando: datetime,
) -> int:
    resultado = conn.execute(
        insert(_T).values(
            perfil_steam=perfil_steam,
            contato=contato,
            observacao=observacao,
            criado_em=quando,
            status=PENDENTE,
        )
    )
    return int(resultado.inserted_primary_key[0])


def contar_pendentes(conn: Connection) -> int:
    return int(
        conn.execute(
            select(func.count()).select_from(_T).where(_T.c.status == PENDENTE)
        ).scalar_one()
    )


def existe_pendente(conn: Connection, perfil_steam: str) -> bool:
    return conn.execute(
        select(_T.c.id)
        .where(_T.c.perfil_steam == perfil_steam, _T.c.status == PENDENTE)
        .limit(1)
    ).first() is not None


def listar_pendentes(conn: Connection) -> list[PedidoAcesso]:
    linhas = conn.execute(
        select(_T).where(_T.c.status == PENDENTE).order_by(_T.c.criado_em, _T.c.id)
    ).all()
    return [_para_pedido(linha) for linha in linhas]


def resolver(conn: Connection, pedido_id: int, status: str, quando: datetime) -> bool:
    """Tira o pedido de pendente. Falso se ele não existe ou já foi resolvido.

    A condição `status == pendente` no próprio UPDATE é o que impede dois
    cliques (ou duas abas) de resolverem o mesmo pedido duas vezes.
    """
    resultado = conn.execute(
        update(_T)
        .where(_T.c.id == pedido_id, _T.c.status == PENDENTE)
        .values(status=status, resolvido_em=quando)
    )
    return resultado.rowcount == 1
```

- [ ] **Step 6: Implementar registro e resolução** — acrescentar a `tf2price/contas/pedidos.py` (imports no topo, resto no fim):

```python
from datetime import datetime
from enum import Enum

from sqlalchemy.engine import Connection

from tf2price.contas import repositorio_pedidos as repo
from tf2price.contas import servico

TETO_DE_PENDENTES = 200


class Resultado(Enum):
    GRAVADO = "gravado"
    DUPLICADO = "duplicado"
    FECHADO = "fechado"


class PedidoJaResolvido(Exception):
    """O pedido não existe ou já saiu de pendente."""


def registrar_pedido(conn: Connection, pedido: Pedido, quando: datetime) -> Resultado:
    # O teto vem antes da deduplicação: uma inundação não pode crescer a
    # tabela, e a resposta de "fechado" não depende de quem pede.
    if repo.contar_pendentes(conn) >= TETO_DE_PENDENTES:
        return Resultado.FECHADO
    # Consulta e insert na mesma transação curta. Dois envios simultâneos do
    # mesmo perfil ainda podem gerar duas linhas; o admin descarta uma. Um
    # índice parcial evitaria isso, mas a sintaxe dele depende do dialeto.
    if repo.existe_pendente(conn, pedido.perfil_steam):
        return Resultado.DUPLICADO
    repo.criar_pedido(
        conn,
        perfil_steam=pedido.perfil_steam,
        contato=pedido.contato,
        observacao=pedido.observacao,
        quando=quando,
    )
    return Resultado.GRAVADO


def convidar_pedido(
    conn: Connection, pedido_id: int, *, admin_id: int, quando: datetime
) -> str:
    """Resolve o pedido e cria o convite na mesma transação; devolve o token."""
    if not repo.resolver(conn, pedido_id, repo.CONVIDADO, quando):
        raise PedidoJaResolvido()
    return servico.convidar(conn, criado_por=admin_id, quando=quando)


def descartar_pedido(conn: Connection, pedido_id: int, *, quando: datetime) -> None:
    if not repo.resolver(conn, pedido_id, repo.DESCARTADO, quando):
        raise PedidoJaResolvido()
```

- [ ] **Step 7: Rodar e ver passar, e a suíte de contas e db**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas tests\test_db.py -q`
Expected: todos PASS.

- [ ] **Step 8: Commit**

```powershell
git add tf2price/db.py tf2price/contas/modelo.py tf2price/contas/repositorio_pedidos.py tf2price/contas/pedidos.py tests/contas/test_pedidos.py
git diff --cached --check
git commit -m "Guarda os pedidos de acesso e os resolve em convite" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 3: Limitador por chave em memória

**Files:**
- Create: `tf2price/painel/limite.py`
- Test: `tests/painel/test_limite.py`

**Interfaces:**
- Produces: `LimitePorChave(maximo: int, janela_s: float, relogio: Callable[[], float] = time.monotonic)` com `permitir(chave: str) -> bool` (registra o evento quando permite).

- [ ] **Step 1: Escrever os testes que falham** — `tests/painel/test_limite.py`:

```python
from __future__ import annotations

import threading

from tf2price.painel.limite import LimitePorChave


class _Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


def test_permite_ate_o_maximo_e_recusa_o_seguinte():
    limite = LimitePorChave(maximo=3, janela_s=3600, relogio=_Relogio())
    assert [limite.permitir("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_chaves_sao_independentes():
    limite = LimitePorChave(maximo=1, janela_s=3600, relogio=_Relogio())
    assert limite.permitir("a")
    assert limite.permitir("b")
    assert not limite.permitir("a")


def test_janela_deslizante_libera_quando_o_mais_antigo_vence():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=2, janela_s=3600, relogio=relogio)
    assert limite.permitir("a")
    relogio.agora += 1800
    assert limite.permitir("a")
    assert not limite.permitir("a")
    relogio.agora += 1800  # o primeiro completou uma hora
    assert limite.permitir("a")
    assert not limite.permitir("a")


def test_recusa_nao_consome_cota():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=1, janela_s=60, relogio=relogio)
    assert limite.permitir("a")
    for _ in range(10):
        assert not limite.permitir("a")
    relogio.agora += 60
    assert limite.permitir("a")


def test_chaves_vencidas_saem_da_memoria():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=3, janela_s=60, relogio=relogio)
    for n in range(50):
        limite.permitir(f"ip-{n}")
    relogio.agora += 60
    limite.permitir("outro")
    # Sem limpeza, cada IP que passou uma vez ficaria para sempre na memória.
    assert limite.chaves_ativas() == 1


def test_concorrencia_nao_deixa_passar_alem_do_maximo():
    limite = LimitePorChave(maximo=5, janela_s=3600, relogio=_Relogio())
    barreira = threading.Barrier(20)
    resultados = []

    def tenta():
        barreira.wait()
        resultados.append(limite.permitir("a"))

    fios = [threading.Thread(target=tenta) for _ in range(20)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert resultados.count(True) == 5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_limite.py -q`
Expected: FAIL — `ModuleNotFoundError: tf2price.painel.limite`.

- [ ] **Step 3: Implementar** — `tf2price/painel/limite.py`:

```python
"""Freio de envios por chave (hoje, IP), em memória do processo.

Vive só neste processo, como o freio da Steam: coerente com a réplica única
de produção. Um deploy o zera; o teto global de pedidos pendentes cobre essa
janela.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class LimitePorChave:
    def __init__(
        self,
        maximo: int,
        janela_s: float,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maximo = maximo
        self._janela_s = janela_s
        self._relogio = relogio
        self._trava = threading.Lock()
        self._eventos: dict[str, deque[float]] = {}

    def permitir(self, chave: str) -> bool:
        """Registra e devolve True se a chave ainda tem cota; senão, False."""
        agora = self._relogio()
        vencido = agora - self._janela_s
        with self._trava:
            for outra in list(self._eventos):
                fila = self._eventos[outra]
                while fila and fila[0] <= vencido:
                    fila.popleft()
                if not fila:
                    del self._eventos[outra]
            fila = self._eventos.setdefault(chave, deque())
            if len(fila) >= self._maximo:
                return False
            fila.append(agora)
            return True

    def chaves_ativas(self) -> int:
        with self._trava:
            return len(self._eventos)
```

Obs.: no teste de "recusa não consome cota", a chave "a" some da memória quando vence e é recriada — correto.

- [ ] **Step 4: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_limite.py -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```powershell
git add tf2price/painel/limite.py tests/painel/test_limite.py
git diff --cached --check
git commit -m "Acrescenta freio de envios por IP em memoria" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 4: `/` pública com a landing completa

**Files:**
- Create: `tf2price/painel/publico.py`
- Create: `tf2price/painel/templates/landing.html`
- Create: `tf2price/painel/static/landing.css`
- Modify: `tf2price/painel/paginas.py:33-39` (Overview deixa de ser rota)
- Modify: `tf2price/painel/app.py` (montar o roteador)
- Modify: `tests/painel/test_entrar.py` (três testes que assumiam `/` protegido)
- Test: `tests/painel/test_publico.py`

**Interfaces:**
- Consumes: `ses.usuario_opcional`; `paginas.renderizar_overview(request, usuario)`.
- Produces:
  - `publico.ROTEADOR`
  - `publico.renderizar_landing(request, *, estado="formulario", valores=None, erros=None, status_code=200)` — `estado` ∈ `formulario`, `enviado`, `fechado`, `limite`; usado pela Task 5
  - Template `landing.html` com contexto `estado: str`, `valores: dict[str, str]`, `erros: dict[str, str]`; marca `data-page="landing"` no `<body>`

- [ ] **Step 1: Escrever os testes que falham** — `tests/painel/test_publico.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app

from .conftest import _contexto, cliente_logado


def _anonimo(engine, contexto="padrao"):
    ctx = _contexto() if contexto == "padrao" else contexto
    return TestClient(criar_app(engine, ctx), follow_redirects=False)


def test_raiz_sem_sessao_mostra_a_landing(engine):
    r = _anonimo(engine).get("/")
    assert r.status_code == 200
    assert 'data-page="landing"' in r.text
    assert "Every Unusual Is a Case." in r.text


def test_landing_nao_depende_de_contexto(engine):
    r = _anonimo(engine, contexto=None).get("/")
    assert r.status_code == 200
    assert 'data-page="landing"' in r.text


def test_raiz_com_sessao_continua_sendo_o_overview(engine):
    r = cliente_logado(engine, _contexto()).get("/")
    assert r.status_code == 200
    assert 'data-page="overview"' in r.text
    assert 'data-page="landing"' not in r.text


def test_landing_tem_o_conteudo_da_spec(engine):
    texto = _anonimo(engine).get("/").text
    for trecho in (
        "Unusual Market Intelligence",
        "Evidence for this effect. Context for the item. A verdict before you buy.",
        'href="#access"',
        'href="#sample-case"',
        "How it works",
        "This effect is not all effects.",
        "Insufficient Data",
        "1.72×",
        'action="/access-request#access"',
        "Not affiliated with Valve, Steam, or backpack.tf.",
        'href="/entrar"',
    ):
        assert trecho in texto, trecho


def test_exemplo_e_rotulado_e_nao_inventa_item(engine):
    texto = _anonimo(engine).get("/").text
    assert "Sample case · Fictional values" in texto
    assert 'src="/arte/13.webp"' in texto
    # Só a marca e a arte real do efeito: nenhuma render de chapéu.
    assert texto.count("<img") == 2


def test_landing_e_acessivel_e_sem_javascript(engine):
    texto = _anonimo(engine).get("/").text
    assert '<html lang="en">' in texto
    assert texto.count("<h1") == 1
    assert 'href="#main-content"' in texto and 'id="main-content"' in texto
    assert "<script" not in texto
    assert '<label for="perfil_steam">' in texto
    assert '<label for="contato">' in texto
    assert '<label for="observacao">' in texto
    assert 'aria-hidden="true"' in texto and 'name="website"' in texto
    assert 'name="description"' in texto and 'property="og:title"' in texto
    assert "/static/briefcase.css" in texto and "/static/landing.css" in texto


def test_confirmacao_substitui_o_formulario(engine):
    texto = _anonimo(engine).get("/?requested=1").text
    assert 'role="status"' in texto and "Request filed." in texto
    assert 'action="/access-request#access"' not in texto


def test_css_da_landing_e_responsivo_e_respeita_movimento_reduzido(engine):
    cliente = _anonimo(engine)
    assert cliente.get("/static/landing.css").status_code == 200
    css = Path("tf2price/painel/static/landing.css").read_text(encoding="utf-8")
    assert "@media (max-width: 56rem)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_publico.py -q`
Expected: FAIL — sem sessão, `/` responde 303.

- [ ] **Step 3: Transformar o Overview em função** — em `tf2price/painel/paginas.py`, trocar a rota `/` por:

```python
def renderizar_overview(request: Request, usuario: Usuario):
    """O Overview de quem está logado. `/` é de `publico.py`, que decide
    entre isto e a landing; aqui fica só a montagem da página."""
    estado = _estado(request, usuario)
    estado["recentes"] = list(reversed(estado["linhas"]))[:5]
    return TEMPLATES.TemplateResponse(
        request=request, name="overview.html", context=estado
    )
```

Confirme com `git grep -n "paginas.overview\|import overview"` que nada mais chamava a função antiga.

- [ ] **Step 4: Criar o roteador público** — `tf2price/painel/publico.py`:

```python
"""Rotas públicas: a landing em `/` e o pedido de acesso.

`/` é a porta de entrada dos dois públicos. Sem sessão, a landing; com sessão,
o Overview de sempre, na mesma URL, para que os redirecionamentos existentes
para `/` continuem levando quem está logado ao painel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter()


def renderizar_landing(
    request: Request,
    *,
    estado: str = "formulario",
    valores: dict[str, str] | None = None,
    erros: dict[str, str] | None = None,
    status_code: int = 200,
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="landing.html",
        context={"estado": estado, "valores": valores or {}, "erros": erros or {}},
        status_code=status_code,
    )


@ROTEADOR.get("/", response_class=HTMLResponse)
def raiz(
    request: Request,
    requested: str = "",
    usuario: Usuario | None = Depends(ses.usuario_opcional),
):
    # Sem `Contexto` (montagem dos testes de autenticação) não há Overview.
    if usuario is not None and request.app.state.contexto is not None:
        # Import tardio pelo mesmo motivo de `criar_app`: `paginas` puxa a
        # consulta inteira, que só existe quando há `Contexto`.
        from tf2price.painel import paginas

        return paginas.renderizar_overview(request, usuario)
    return renderizar_landing(
        request, estado="enviado" if requested == "1" else "formulario"
    )
```

- [ ] **Step 5: Montar em `criar_app`** — em `tf2price/painel/app.py`, trocar `from tf2price.painel import acesso, admin` por `from tf2price.painel import acesso, admin, publico` e, logo depois de `app.include_router(admin.ROTEADOR)`, acrescentar:

```python
    app.include_router(publico.ROTEADOR)
```

- [ ] **Step 6: Criar o template** — `tf2price/painel/templates/landing.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>briefcase.tf — Unusual Market Intelligence</title>
  <meta name="description" content="Evidence for this effect. Context for the item. A verdict before you buy a TF2 Unusual. Independent, fan-made, invitation only.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="briefcase.tf">
  <meta property="og:title" content="briefcase.tf — Every Unusual Is a Case.">
  <meta property="og:description" content="Evidence for this effect. Context for the item. A verdict before you buy.">
  <link rel="icon" href="/static/brand/briefcase.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/briefcase.css">
  <link rel="stylesheet" href="/static/landing.css">
</head>
<body class="landing" data-page="landing">
  <a class="skip-link" href="#main-content">Skip to content</a>
  <header class="landing-top">
    <a class="brand" href="/" aria-label="briefcase.tf home">
      <img class="brand__mark" src="/static/brand/briefcase.svg" alt="" width="36" height="36">
      <span class="brand__copy">
        <strong>briefcase.tf</strong>
        <small>Unusual Market Intelligence</small>
      </span>
    </a>
    <a class="landing-top__signin" href="/entrar">Sign in</a>
  </header>

  <main id="main-content" tabindex="-1">
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero__copy">
        <p class="landing-eyebrow">Unusual Market Intelligence</p>
        <h1 id="hero-title">Every Unusual Is a Case.</h1>
        <p class="hero__lede">Evidence for this effect. Context for the item. A verdict before you buy.</p>
        <div class="hero__actions">
          <a class="button button--primary" href="#access">Request access</a>
          <a class="button button--quiet" href="#sample-case">See a sample case</a>
        </div>
        <p class="hero__note">Invitation only · Independent and fan-made</p>
      </div>

      <article class="sample-case" id="sample-case" aria-labelledby="sample-title">
        <p class="sample-case__tag">Sample case · Fictional values</p>
        <div class="sample-case__head">
          <img src="/arte/13.webp" alt="Burning Flames effect art" width="72" height="72">
          <div>
            <p class="scope-label">Case file BRF-000001</p>
            <h2 id="sample-title">Team Captain</h2>
            <p class="sample-case__effect">Unusual effect: Burning Flames</p>
          </div>
          <p class="sample-case__verdict">Fair Price</p>
        </div>
        <div class="sample-case__columns">
          <section aria-labelledby="sample-this">
            <h3 id="sample-this">This effect</h3>
            <dl>
              <div><dt>Lowest Steam listing</dt><dd>R$ 4.850,00</dd></div>
              <div><dt>backpack.tf price</dt><dd>R$ 4.410,00</dd></div>
              <div><dt>Listings for this effect</dt><dd>3</dd></div>
            </dl>
            <p class="sample-case__age">backpack.tf priced 3 days ago</p>
          </section>
          <section class="sample-case__all" aria-labelledby="sample-all">
            <h3 id="sample-all">All effects</h3>
            <dl>
              <div><dt>Highest buy order</dt><dd>R$ 1.120,00</dd></div>
              <div><dt>Median sale, 30 days</dt><dd>R$ 2.300,00</dd></div>
            </dl>
            <p class="sample-case__age">Steam publishes these for every effect together</p>
          </section>
        </div>
      </article>
    </section>

    <section class="landing-section" aria-labelledby="how-title">
      <p class="landing-eyebrow">Procedure</p>
      <h2 id="how-title">How it works</h2>
      <ol class="steps">
        <li>
          <span class="steps__n">01</span>
          <h3>Pick the hat and effect</h3>
          <p>Search the Unusual you are considering and choose its exact effect.</p>
        </li>
        <li>
          <span class="steps__n">02</span>
          <h3>We collect the evidence</h3>
          <p>Steam listings for that effect, its backpack.tf price, and the Steam offer book and sales history for the item.</p>
        </li>
        <li>
          <span class="steps__n">03</span>
          <h3>Read the verdict</h3>
          <p>Good Buy, Fair Price, Caution, or Insufficient Data — with every source and its age on the page.</p>
        </li>
      </ol>
    </section>

    <section class="landing-section" aria-labelledby="rule-title">
      <p class="landing-eyebrow">Ground rule</p>
      <h2 id="rule-title">This effect is not all effects.</h2>
      <p>Two hats with the same name and different effects can be worth very different amounts. briefcase.tf keeps them apart.</p>
      <div class="rule-columns">
        <div class="rule-columns__this">
          <h3>This effect</h3>
          <p>Listings and the backpack.tf price for the exact effect you chose. The evidence behind the verdict.</p>
        </div>
        <div class="rule-columns__all">
          <h3>All effects</h3>
          <p>The Steam offer book and sales history, which Steam only publishes for every effect together. Context, never a substitute.</p>
        </div>
      </div>
      <p>When the effect has no reliable price, the case says <strong>Insufficient Data</strong>. It never borrows another effect's price.</p>
    </section>

    <section class="landing-section" aria-labelledby="found-title">
      <p class="landing-eyebrow">Findings</p>
      <h2 id="found-title">What we've found</h2>
      <p class="finding">
        <span class="finding__number">1.72×</span>
        <span class="finding__text">On the median, the Steam price sits 1.72 times above trade value.</span>
      </p>
      <p>Buying low on Steam to gain value in keys runs the wrong way, and not by accident: systematically. briefcase.tf exists to keep you out of a bad one-off deal, not to promise profit.</p>
    </section>

    <section class="access" id="access" aria-labelledby="access-title" tabindex="-1">
      <div class="auth-card access__card">
        <p class="access__tab">Access file</p>
        <h2 id="access-title">Request access</h2>
        <p class="access__intro">briefcase.tf is invitation only. Tell us who you are on Steam and where to send the invite.</p>
        {% if estado == "enviado" %}
        <div class="access__status" role="status"><b>Request filed.</b> If approved, you'll receive an invite link through the contact you gave.</div>
        {% elif estado == "fechado" %}
        <div class="erro" role="alert"><b>Access requests are temporarily closed.</b> Try again later.</div>
        {% elif estado == "limite" %}
        <div class="erro" role="alert"><b>Too many requests from this connection.</b> Try again later.</div>
        {% else %}
        {% if erros %}
        <div class="erro" id="access-errors" role="alert"><b>Check the highlighted fields.</b></div>
        {% endif %}
        <form method="post" action="/access-request#access">
          <div class="campo-form">
            <label for="perfil_steam">Steam profile URL</label>
            <input id="perfil_steam" name="perfil_steam" inputmode="url" autocomplete="url" required maxlength="200"
                   placeholder="steamcommunity.com/id/your-name" value="{{ valores.get('perfil_steam', '') }}"
                   aria-describedby="perfil_steam-hint{% if erros.perfil_steam %} perfil_steam-erro{% endif %}"{% if erros.perfil_steam %} aria-invalid="true"{% endif %}>
            <p class="dica" id="perfil_steam-hint">We use it to see who is asking. Nothing else.</p>
            {% if erros.perfil_steam %}<p class="access__erro" id="perfil_steam-erro">{{ erros.perfil_steam }}</p>{% endif %}
          </div>
          <div class="campo-form">
            <label for="contato">Where can we reach you?</label>
            <input id="contato" name="contato" required maxlength="200"
                   placeholder="Discord, email, or Steam chat" value="{{ valores.get('contato', '') }}"
                   aria-describedby="contato-hint{% if erros.contato %} contato-erro{% endif %}"{% if erros.contato %} aria-invalid="true"{% endif %}>
            <p class="dica" id="contato-hint">The invite link goes here.</p>
            {% if erros.contato %}<p class="access__erro" id="contato-erro">{{ erros.contato }}</p>{% endif %}
          </div>
          <div class="campo-form">
            <label for="observacao">Anything we should know? <span class="access__optional">(optional)</span></label>
            <textarea id="observacao" name="observacao" rows="4" maxlength="1000"{% if erros.observacao %} aria-invalid="true" aria-describedby="observacao-erro"{% endif %}>{{ valores.get('observacao', '') }}</textarea>
            {% if erros.observacao %}<p class="access__erro" id="observacao-erro">{{ erros.observacao }}</p>{% endif %}
          </div>
          <div class="access__trap" aria-hidden="true">
            <label for="website">Website</label>
            <input id="website" name="website" tabindex="-1" autocomplete="off">
          </div>
          <button class="acao" type="submit">Submit request</button>
        </form>
        {% endif %}
      </div>
    </section>
  </main>

  <footer class="landing-footer">
    <p>Independent fan-made project. Not affiliated with Valve, Steam, or backpack.tf.</p>
    <p class="landing-footer__tagline">Every Unusual Is a Case.</p>
    <a href="/entrar">Sign in</a>
  </footer>
</body>
</html>
```

Obs.: o `<label>` do campo opcional contém um `<span>`, por isso o teste procura `<label for="observacao">` (abertura), não o rótulo inteiro.

- [ ] **Step 7: Criar o CSS** — `tf2price/painel/static/landing.css`:

```css
/* Só a landing pública. Tokens, fontes, .button, .brand, .auth-card e o
   formulário (.campo-form, .acao, .erro, .dica) vêm de briefcase.css. */
.landing { background: var(--charcoal); }
.landing-top, .landing main, .landing-footer { width: 100%; max-width: 76rem; margin: 0 auto; padding-inline: clamp(1rem, 4vw, 2.5rem); }
.landing-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding-block: 1.25rem; }
.landing-top__signin, .landing-footer a { min-height: 44px; display: inline-flex; align-items: center; padding-inline: .5rem; font: 500 .8rem var(--font-mono); letter-spacing: .12em; text-transform: uppercase; color: var(--paper); }
.landing main:focus { outline: none; }
.landing-eyebrow { margin: 0 0 .75rem; font: 500 .75rem/1.3 var(--font-mono); letter-spacing: .16em; text-transform: uppercase; color: #8FB0BD; }

.hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: clamp(2rem, 5vw, 4.5rem); align-items: center; padding-block: clamp(2.5rem, 8vw, 6rem); }
.hero h1 { margin: 0; font-family: var(--font-display); font-weight: 800; font-size: clamp(2.6rem, 6vw, 4.75rem); line-height: 1.02; letter-spacing: -.045em; text-wrap: balance; }
.hero__lede { max-width: 32rem; margin: 1.25rem 0 2rem; font-size: 1.15rem; color: rgba(232, 225, 209, .85); }
.hero__actions { display: flex; flex-wrap: wrap; gap: .75rem; }
.hero__note { margin: 1.5rem 0 0; font: .75rem var(--font-mono); letter-spacing: .1em; text-transform: uppercase; color: rgba(232, 225, 209, .75); }

.sample-case { padding: clamp(1rem, 3vw, 1.5rem); background: var(--paper); color: var(--charcoal); border-top: .4rem solid var(--active-blue); box-shadow: 0 1.25rem 2.5rem rgba(0, 0, 0, .45); transform: rotate(2deg); transition: transform .3s ease; }
.sample-case:hover { transform: rotate(.5deg); }
.sample-case__tag { display: inline-block; margin: 0 0 1rem; padding: .2rem .55rem; border: 2px solid var(--rust-stamp); color: var(--rust-stamp); font: 600 .7rem var(--font-mono); letter-spacing: .12em; text-transform: uppercase; }
.sample-case__head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 1rem; align-items: center; padding-bottom: 1rem; border-bottom: 1px solid rgba(14, 15, 16, .2); }
.sample-case__head img { width: 4.5rem; height: 4.5rem; background: var(--ink-panel); }
.sample-case__head .scope-label { color: var(--ink-blue); }
.sample-case h2 { margin: 0; font: 800 1.6rem/1.1 var(--font-display); letter-spacing: -.03em; }
.sample-case__effect { margin: .25rem 0 0; font: 600 .95rem var(--font-condensed); color: var(--ink-blue); }
.sample-case__verdict { margin: 0; padding: .3rem .6rem; border: 3px solid var(--rust-stamp); color: var(--rust-stamp); font: 800 1rem var(--font-condensed); letter-spacing: .06em; text-transform: uppercase; transform: rotate(-6deg); }
.sample-case__columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: .75rem; margin-top: 1rem; }
.sample-case__columns section { padding: .85rem; background: var(--ink-panel); color: var(--paper); border: 1px solid var(--active-blue); }
.sample-case__columns .sample-case__all { border-color: var(--warning); }
.sample-case h3 { margin: 0 0 .6rem; font: 600 .72rem var(--font-mono); letter-spacing: .14em; text-transform: uppercase; }
.sample-case__all h3 { color: var(--warning); }
.sample-case dl { display: grid; gap: .4rem; margin: 0; }
.sample-case dl div { display: flex; justify-content: space-between; gap: .75rem; }
.sample-case dt { font-size: .82rem; }
.sample-case dd { margin: 0; font: 700 .9rem var(--font-condensed); white-space: nowrap; }
.sample-case__age { margin: .7rem 0 0; font: .7rem var(--font-mono); color: rgba(232, 225, 209, .78); }

.landing-section { padding-block: clamp(3rem, 7vw, 5rem); border-top: 1px solid var(--ink-blue); }
.landing-section h2 { margin: 0 0 1rem; font: 800 clamp(1.9rem, 4vw, 2.8rem)/1.1 var(--font-display); letter-spacing: -.04em; text-wrap: balance; }
.landing-section > p { max-width: 44rem; font-size: 1.05rem; }
.steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 2rem 0 0; padding: 0; list-style: none; }
.steps li { padding: 1.25rem; background: var(--ink-panel); border: 1px solid var(--ink-blue); border-top: .3rem solid var(--active-blue); }
.steps__n { display: block; margin-bottom: .75rem; font: 600 .8rem var(--font-mono); letter-spacing: .14em; color: var(--warning); }
.steps h3, .rule-columns h3 { margin: 0 0 .5rem; font: 700 1.25rem var(--font-condensed); }
.steps p, .rule-columns p { margin: 0; color: rgba(232, 225, 209, .85); }
.rule-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; margin: 2rem 0; }
.rule-columns > div { padding: 1.25rem; background: var(--ink-panel); border: 1px solid var(--active-blue); }
.rule-columns > .rule-columns__all { border-color: var(--warning); }
.rule-columns__all h3 { color: var(--warning); }
.finding { display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem 1.5rem; margin: 1.5rem 0; }
.finding__number { font: 800 clamp(4rem, 12vw, 7.5rem)/1 var(--font-display); letter-spacing: -.05em; color: var(--warning); }
.finding__text { max-width: 26rem; font: 600 1.2rem/1.4 var(--font-condensed); }

.access { display: grid; justify-items: center; padding-block: clamp(3rem, 7vw, 5rem); border-top: 1px solid var(--ink-blue); }
.access:focus { outline: none; }
.access__card { position: relative; width: min(100%, 40rem); }
.access__tab { display: inline-block; margin: 0 0 1rem; font: 700 .8rem var(--font-condensed); letter-spacing: .12em; text-transform: uppercase; color: var(--ink-blue); }
.access__card h2 { margin: 0 0 .75rem; font: 800 2rem/1.1 var(--font-display); letter-spacing: -.04em; }
.access__intro { margin: 0 0 1.5rem; }
.access__card .erro { margin-bottom: 1.5rem; }
.access__status { padding: 1rem; border: 2px solid var(--active-blue); border-left-width: .4rem; }
.access__status b { display: block; font-family: var(--font-display); }
.access__erro { margin: .4rem 0 0; font-weight: 600; color: var(--rust-stamp); }
.access__optional { font-family: var(--font-interface); font-weight: 400; text-transform: none; letter-spacing: 0; }
.access__card textarea { width: 100%; min-height: 7rem; padding: .45rem .1rem; border: 0; border-bottom: 2px solid var(--tinta); border-radius: 0; background: transparent; color: var(--tinta); font: 1rem var(--font-interface); resize: vertical; }
.access__card textarea:focus { border-bottom-color: var(--warning); }
.access__card [aria-invalid="true"] { border-bottom-color: var(--rust-stamp); }
.access__trap { position: absolute; left: -10000px; width: 1px; height: 1px; overflow: hidden; }

.landing-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; padding-block: 2rem 3rem; border-top: 1px solid var(--ink-blue); font: .75rem/1.6 var(--font-mono); letter-spacing: .06em; color: rgba(232, 225, 209, .78); }
.landing-footer p { margin: 0; }

@media (max-width: 56rem) {
  .hero { grid-template-columns: minmax(0, 1fr); }
  .sample-case, .sample-case:hover { transform: none; }
  .steps, .rule-columns { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 30rem) {
  .sample-case__head { grid-template-columns: auto minmax(0, 1fr); }
  .sample-case__verdict { grid-column: 1 / -1; justify-self: start; }
  .sample-case__columns { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .sample-case, .sample-case:hover, .sample-case__verdict { transform: none; transition: none; }
}
```

- [ ] **Step 8: Ajustar os testes que assumiam `/` protegido** — em `tests/painel/test_entrar.py`:

```python
def test_painel_sem_cookie_manda_para_entrar(cliente):
    r = cliente.get("/cases")
    assert r.status_code == 303
    assert r.headers["location"] == "/entrar"


def test_raiz_sem_cookie_mostra_a_landing(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert 'data-page="landing"' in r.text


def test_fragmento_htmx_sem_cookie_devolve_401_com_redirecionamento(cliente):
    """Um 303 dentro de fragmento seria engolido pelo swap do HTMX.

    O navegador só sai da página quando o HTMX vê HX-Redirect.
    """
    r = cliente.get("/cases", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/entrar"
```

E, em `test_sair_apaga_a_sessao`, trocar a última linha por `assert cliente.get("/cases").status_code == 303`.

- [ ] **Step 9: Rodar a suíte do painel**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -q`
Expected: todos PASS. Se outro teste falhar por acessar `/` sem sessão esperando redirecionamento, ajuste-o para uma rota protegida (`/cases`) como acima — não relaxe o que ele verifica.

- [ ] **Step 10: Conferir no navegador**

Run: `.\.venv\Scripts\python.exe -m tf2price.painel.app` e abra `http://127.0.0.1:8000/` numa janela anônima. Verifique: hero em duas colunas acima de ~900px e em uma abaixo; cartão sem rotação no estreito; nenhuma rolagem horizontal a 360px; arte do efeito carregando; `Tab` mostra o skip link primeiro; âncoras levam ao exemplo e ao formulário.

- [ ] **Step 11: Commit**

```powershell
git add tf2price/painel/publico.py tf2price/painel/paginas.py tf2price/painel/app.py tf2price/painel/templates/landing.html tf2price/painel/static/landing.css tests/painel/test_publico.py tests/painel/test_entrar.py
git diff --cached --check
git commit -m "Abre a raiz como landing publica para quem nao esta logado" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 5: `POST /access-request`

**Files:**
- Modify: `tf2price/painel/publico.py`
- Modify: `tf2price/painel/app.py` (criar `app.state.limite_pedidos`)
- Test: `tests/painel/test_publico.py`

**Interfaces:**
- Consumes: `pedidos.validar_pedido`, `pedidos.registrar_pedido`, `pedidos.Resultado` (Tasks 1–2); `LimitePorChave` (Task 3); `renderizar_landing` (Task 4).
- Produces: `publico.PEDIDOS_POR_IP = 3`, `publico.JANELA_DOS_PEDIDOS_S = 3600`; `app.state.limite_pedidos: LimitePorChave`.

- [ ] **Step 1: Escrever os testes que falham** (acrescentar a `tests/painel/test_publico.py`)

```python
from tf2price import db
from tf2price.contas import repositorio_pedidos as repo
from tf2price.painel.limite import LimitePorChave

VALIDO = {
    "perfil_steam": "steamcommunity.com/id/Gusco",
    "contato": "gusco no Discord",
    "observacao": "",
    "website": "",
}


def _pendentes(engine):
    with engine.begin() as conn:
        return repo.listar_pendentes(conn)


def test_pedido_valido_grava_e_confirma(engine):
    r = _anonimo(engine).post("/access-request", data=VALIDO)
    assert r.status_code == 303
    assert r.headers["location"] == "/?requested=1#access"
    [pedido] = _pendentes(engine)
    assert pedido.perfil_steam == "https://steamcommunity.com/id/gusco"
    assert pedido.contato == "gusco no Discord"


def test_pedido_invalido_volta_com_erros_e_valores(engine):
    r = _anonimo(engine).post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "https://evil.example/<b>x</b>", "contato": " "},
    )
    assert r.status_code == 422
    assert "Check the highlighted fields." in r.text
    assert "Enter a steamcommunity.com/id/" in r.text
    assert "Tell us where to send the invite." in r.text
    assert 'aria-invalid="true"' in r.text
    assert 'value="https://evil.example/&lt;b&gt;x&lt;/b&gt;"' in r.text
    assert _pendentes(engine) == []


def test_perfil_ja_pendente_recebe_a_mesma_resposta(engine):
    cliente = _anonimo(engine)
    primeira = cliente.post("/access-request", data=VALIDO)
    segunda = cliente.post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "https://steamcommunity.com/id/gusco/"},
    )
    assert (segunda.status_code, segunda.headers["location"]) == (
        primeira.status_code, primeira.headers["location"]
    )
    assert len(_pendentes(engine)) == 1


def test_honeypot_parece_sucesso_e_nao_grava(engine):
    r = _anonimo(engine).post("/access-request", data={**VALIDO, "website": "http://spam"})
    assert r.status_code == 303
    assert r.headers["location"] == "/?requested=1#access"
    assert _pendentes(engine) == []


def test_quarto_envio_do_mesmo_ip_na_hora_e_recusado(engine):
    relogio = [1000.0]
    cliente = _anonimo(engine)
    cliente.app.state.limite_pedidos = LimitePorChave(
        maximo=3, janela_s=3600, relogio=lambda: relogio[0]
    )
    for n in range(3):
        dados = {**VALIDO, "perfil_steam": f"steamcommunity.com/id/p{n}x"}
        assert cliente.post("/access-request", data=dados).status_code == 303
    r = cliente.post("/access-request", data={**VALIDO, "perfil_steam": "steamcommunity.com/id/p9x"})
    assert r.status_code == 429
    assert "Too many requests from this connection." in r.text
    assert len(_pendentes(engine)) == 3
    relogio[0] += 3600
    r = cliente.post("/access-request", data={**VALIDO, "perfil_steam": "steamcommunity.com/id/p9x"})
    assert r.status_code == 303


def test_teto_de_pendentes_fecha_os_pedidos(engine):
    with engine.begin() as conn:
        for n in range(200):
            repo.criar_pedido(conn, perfil_steam=f"https://steamcommunity.com/id/p{n}x",
                              contato="c", observacao=None, quando=db.agora())
    r = _anonimo(engine).post("/access-request", data=VALIDO)
    assert r.status_code == 503
    assert "Access requests are temporarily closed." in r.text
    assert len(_pendentes(engine)) == 200


def test_pedido_de_outra_origem_e_recusado(engine):
    r = _anonimo(engine).post(
        "/access-request", data=VALIDO,
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
    assert _pendentes(engine) == []


def test_limite_padrao_do_app_e_tres_por_hora(engine):
    cliente = _anonimo(engine, contexto=None)
    codigos = [
        cliente.post("/access-request",
                     data={**VALIDO, "perfil_steam": f"steamcommunity.com/id/q{n}x"}).status_code
        for n in range(4)
    ]
    assert codigos == [303, 303, 303, 429]
```

Os imports novos (`db`, `repo`, `LimitePorChave`) vão para o topo do arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_publico.py -q`
Expected: os testes novos FALHAM com 404/405 em `/access-request`.

- [ ] **Step 3: Criar o limitador na aplicação** — em `tf2price/painel/app.py`, acrescentar o import `from tf2price.painel.limite import LimitePorChave` e, em `criar_app`, logo depois de `app.state.contexto = contexto`:

```python
    app.state.limite_pedidos = LimitePorChave(
        maximo=publico.PEDIDOS_POR_IP, janela_s=publico.JANELA_DOS_PEDIDOS_S
    )
```

- [ ] **Step 4: Implementar a rota** — em `tf2price/painel/publico.py`, ajustar os imports:

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from tf2price import db
from tf2price.contas import pedidos
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES
```

e acrescentar, depois de `ROTEADOR = APIRouter()`:

```python
PEDIDOS_POR_IP = 3
JANELA_DOS_PEDIDOS_S = 3600
_CONFIRMADO = "/?requested=1#access"
```

e, no fim do arquivo:

```python
@ROTEADOR.post("/access-request", dependencies=[Depends(ses.mesma_origem)])
def pedir_acesso(
    request: Request,
    perfil_steam: str = Form(""),
    contato: str = Form(""),
    observacao: str = Form(""),
    website: str = Form(""),
) -> Response:
    # `--proxy-headers` já põe aqui o IP de quem pediu, não o do proxy.
    ip = request.client.host if request.client else "desconhecido"
    if not request.app.state.limite_pedidos.permitir(ip):
        return renderizar_landing(request, estado="limite", status_code=429)
    if website:
        # Honeypot: só robô preenche. Responde como sucesso para não ensinar.
        return RedirectResponse(_CONFIRMADO, status_code=303)
    pedido, erros = pedidos.validar_pedido(perfil_steam, contato, observacao)
    if pedido is None:
        return renderizar_landing(
            request,
            valores={
                "perfil_steam": perfil_steam,
                "contato": contato,
                "observacao": observacao,
            },
            erros=erros,
            status_code=422,
        )
    with request.app.state.engine.begin() as conn:
        resultado = pedidos.registrar_pedido(conn, pedido, db.agora())
    if resultado is pedidos.Resultado.FECHADO:
        return renderizar_landing(request, estado="fechado", status_code=503)
    # GRAVADO e DUPLICADO respondem igual: a página não revela quem já pediu.
    return RedirectResponse(_CONFIRMADO, status_code=303)
```

Cuidado com import circular: `app.py` passa a usar `publico.PEDIDOS_POR_IP` e `publico` não importa `app`; está livre.

- [ ] **Step 5: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_publico.py tests\painel\test_entrar.py -q`
Expected: todos PASS.

- [ ] **Step 6: Conferir no navegador** — com o app local rodando, numa janela anônima: enviar um pedido válido (URL vira `/?requested=1#access` e mostra "Request filed."), um inválido (erros por campo, valores mantidos, foco rolado até o formulário) e F5 na confirmação (não reenvia).

- [ ] **Step 7: Commit**

```powershell
git add tf2price/painel/publico.py tf2price/painel/app.py tests/painel/test_publico.py
git diff --cached --check
git commit -m "Recebe pedidos de acesso pela landing com freio e honeypot" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 6: Pedidos em `/admin`

**Files:**
- Modify: `tf2price/painel/admin.py`
- Modify: `tf2price/painel/templates/admin.html`
- Modify: `tf2price/painel/static/briefcase.css:202` (`.admin-requests h2` junto de `.admin-people h2`)
- Test: `tests/painel/test_admin.py`

**Interfaces:**
- Consumes: `repositorio_pedidos.listar_pendentes`, `pedidos.convidar_pedido`, `pedidos.descartar_pedido`, `pedidos.PedidoJaResolvido` (Task 2).
- Produces: rotas `POST /admin/pedido/{pedido_id}/convidar` e `POST /admin/pedido/{pedido_id}/descartar`.

- [ ] **Step 1: Escrever os testes que falham** (acrescentar a `tests/painel/test_admin.py`)

```python
import re

from sqlalchemy import select

from tf2price.contas import repositorio_pedidos as repo_pedidos


def _pedido(engine, perfil="https://steamcommunity.com/id/amiga", contato="amiga no Discord",
            observacao=None):
    with engine.begin() as conn:
        return repo_pedidos.criar_pedido(
            conn, perfil_steam=perfil, contato=contato, observacao=observacao, quando=db.agora()
        )


def _status_do_pedido(engine, pedido_id):
    with engine.begin() as conn:
        return conn.execute(
            select(db.pedido_acesso.c.status).where(db.pedido_acesso.c.id == pedido_id)
        ).scalar_one()


def test_admin_lista_pedidos_pendentes(admin, engine):
    _pedido(engine, observacao="coleciono Team Captains")
    texto = admin.get("/admin").text
    assert "Access requests" in texto
    assert ('<a href="https://steamcommunity.com/id/amiga" target="_blank" '
            'rel="noopener noreferrer">') in texto
    assert "amiga no Discord" in texto
    assert "coleciono Team Captains" in texto


def test_admin_sem_pedidos_diz_isso(admin):
    assert "No pending requests." in admin.get("/admin").text


def test_texto_do_pedido_e_escapado(admin, engine):
    _pedido(engine, contato="<script>alert(1)</script>")
    texto = admin.get("/admin").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in texto


def test_convidar_pedido_mostra_link_valido_e_tira_da_lista(admin, engine):
    pedido_id = _pedido(engine)
    r = admin.post(f"/admin/pedido/{pedido_id}/convidar")
    assert r.status_code == 200
    token = re.search(r"/convite/([A-Za-z0-9_\-]+)", r.text).group(1)
    with engine.begin() as conn:
        assert repo.convite_por_hash(conn, tokens.hash_de(token)) is not None
    assert _status_do_pedido(engine, pedido_id) == "convidado"
    assert "https://steamcommunity.com/id/amiga" not in admin.get("/admin").text


def test_descartar_pedido(admin, engine):
    pedido_id = _pedido(engine)
    r = admin.post(f"/admin/pedido/{pedido_id}/descartar")
    assert r.status_code == 200
    assert "/convite/" not in r.text
    assert _status_do_pedido(engine, pedido_id) == "descartado"


def test_pedido_ja_resolvido_nao_gera_convite(admin, engine):
    pedido_id = _pedido(engine)
    admin.post(f"/admin/pedido/{pedido_id}/descartar")
    r = admin.post(f"/admin/pedido/{pedido_id}/convidar")
    assert "This request was already resolved." in r.text
    assert "/convite/" not in r.text
    assert _status_do_pedido(engine, pedido_id) == "descartado"


def test_acoes_de_pedido_exigem_mesma_origem(admin, engine):
    pedido_id = _pedido(engine)
    for acao in ("convidar", "descartar"):
        r = admin.post(f"/admin/pedido/{pedido_id}/{acao}",
                       headers={"Origin": "https://site-de-outro.example"})
        assert r.status_code == 403
    assert _status_do_pedido(engine, pedido_id) == "pendente"


def test_nao_admin_nao_resolve_pedido(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    pedido_id = _pedido(engine)
    assert comum.post(f"/admin/pedido/{pedido_id}/convidar").status_code == 403
    assert _status_do_pedido(engine, pedido_id) == "pendente"
```

(`db`, `repo`, `tokens`, `_entra` e a fixture `admin` já existem no arquivo; os imports novos — `re`, `select`, `repo_pedidos` — vão para o topo.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_admin.py -q`
Expected: os testes novos FALHAM ("Access requests" ausente, rotas 404/405).

- [ ] **Step 3: Implementar as rotas** — em `tf2price/painel/admin.py`, acrescentar os imports:

```python
from tf2price.contas import pedidos
from tf2price.contas import repositorio_pedidos as repo_pedidos
```

em `_tela_admin`, acrescentar ao contexto `"pedidos": repo_pedidos.listar_pendentes(conn),`, e no fim do arquivo:

```python
_JA_RESOLVIDO = "This request was already resolved."


@ROTEADOR.post("/admin/pedido/{pedido_id}/convidar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def convidar_pedido(
    request: Request,
    pedido_id: int,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    try:
        token = pedidos.convidar_pedido(
            conn, pedido_id, admin_id=usuario.id, quando=db.agora()
        )
    except pedidos.PedidoJaResolvido:
        return _tela_admin(request, conn, usuario, erro=_JA_RESOLVIDO)
    # O token em claro existe só aqui, como em `gerar_convite`.
    return _tela_admin(request, conn, usuario, link=f"/convite/{token}")


@ROTEADOR.post("/admin/pedido/{pedido_id}/descartar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def descartar_pedido(
    request: Request,
    pedido_id: int,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    try:
        pedidos.descartar_pedido(conn, pedido_id, quando=db.agora())
    except pedidos.PedidoJaResolvido:
        return _tela_admin(request, conn, usuario, erro=_JA_RESOLVIDO)
    return _tela_admin(request, conn, usuario)
```

- [ ] **Step 4: Implementar a seção** — em `tf2price/painel/templates/admin.html`, entre a `</section>` de convites e `<section class="admin-people" ...>`:

```html
<section class="admin-requests" aria-labelledby="requests-title">
  <h2 id="requests-title">Access requests</h2>
  {% if pedidos %}
  <ul class="admin-people__list">
  {% for p in pedidos %}
    <li class="admin-person">
      <div class="admin-person__identity">
        <a href="{{ p.perfil_steam }}" target="_blank" rel="noopener noreferrer">{{ p.perfil_steam }}</a>
        <span>{{ p.contato }} · Filed {{ p.criado_em.strftime('%Y-%m-%d %H:%M') }} UTC</span>
        {% if p.observacao %}<p>{{ p.observacao }}</p>{% endif %}
      </div>
      <div class="admin-person__actions">
        <form method="post" action="/admin/pedido/{{ p.id }}/convidar">
          <button class="button button--primary" type="submit">Create invite</button>
        </form>
        <form method="post" action="/admin/pedido/{{ p.id }}/descartar">
          <button class="button button--quiet" type="submit">Dismiss</button>
        </form>
      </div>
    </li>
  {% endfor %}
  </ul>
  {% else %}
  <p>No pending requests.</p>
  {% endif %}
</section>
```

- [ ] **Step 5: Estilo** — em `tf2price/painel/static/briefcase.css`, trocar a linha 202 por:

```css
.admin-people h2, .admin-requests h2 { margin: 0 0 1rem; font-family: var(--font-display); }
.admin-requests { margin-bottom: 2rem; }
```

- [ ] **Step 6: Rodar e ver passar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_admin.py -q`
Expected: todos PASS.

- [ ] **Step 7: Commit**

```powershell
git add tf2price/painel/admin.py tf2price/painel/templates/admin.html tf2price/painel/static/briefcase.css tests/painel/test_admin.py
git diff --cached --check
git commit -m "Lista pedidos de acesso no admin e os converte em convite" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```

---

### Task 7: Documentação e verificação final

**Files:**
- Modify: `README.md` (seção "Uso")
- Modify: `docs/superpowers/specs/2026-09-21-landing-page-design.md` (dois ajustes decididos no plano)

- [ ] **Step 1: README** — em `README.md`, na seção "Uso", substituir o parágrafo que começa com "Abre em `http://127.0.0.1:8000`." por:

```markdown
Abre em `http://127.0.0.1:8000`. Sem sessão, a raiz mostra a landing pública,
onde qualquer pessoa pode pedir acesso informando o perfil da Steam e um
contato; com sessão, a raiz é o Overview. Na primeira subida, com o banco
vazio, o terminal imprime um link de convite de administrador válido por 24
horas — é por ele que a primeira conta nasce. Depois, novas contas saem de
`/admin`, que também lista os pedidos de acesso pendentes: `Create invite`
gera o link para enviar à pessoa, `Dismiss` descarta o pedido.
```

- [ ] **Step 2: Spec** — em `docs/superpowers/specs/2026-09-21-landing-page-design.md`:
  - na seção 7, trocar "`<title>`, `meta description` e Open Graph (título, descrição, imagem com o logo)" por "`<title>`, `meta description` e Open Graph (título e descrição; sem `og:image`, porque o único logo disponível é SVG, que Discord e Steam não exibem como prévia)";
  - na seção 8, trocar "contato, observação e idade" por "contato, observação e data de envio em UTC".

- [ ] **Step 3: Suíte completa**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: todos PASS, nenhum teste tocando a rede.

- [ ] **Step 4: Revisar o diff do ramo**

Run: `git diff master --stat` e `git diff master --check`
Expected: só os arquivos do mapa acima; nenhum `.env`, banco local (`painel-local.db`), `.superpowers/` ou cache.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/superpowers/specs/2026-09-21-landing-page-design.md
git diff --cached --check
git commit -m "Documenta a landing e os pedidos de acesso" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_01ED7RuHP66ZramCj1FYWFLo"
```
