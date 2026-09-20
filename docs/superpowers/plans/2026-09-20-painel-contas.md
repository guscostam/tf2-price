# Painel fechado, parte 1: contas e implantação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pôr a consulta de Unusual que já existe no ar como painel fechado — hospedado no Railway, com Postgres, onde só entra quem abriu um link de convite gerado pelo dono.

**Architecture:** Três camadas novas ao lado do que existe. `db.py` declara o schema uma vez em SQLAlchemy Core e roda em Postgres na produção e em SQLite na memória nos testes. `contas/` separa repositório (SQL), senhas (Argon2id), tokens (aleatório + SHA-256) e serviço (regras, sem SQL solto). `painel/` reúne rotas, sessão por cookie e os templates, absorvendo as rotas que hoje vivem em `lookup/app.py`. `domain/`, `sources/` e `lookup/analysis.py` não são tocados.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, HTMX, SQLAlchemy 2 (Core, não ORM), psycopg 3, argon2-cffi, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-painel-fechado-design.md`

---

## Contexto de domínio

Este projeto avalia chapéus **Unusual** de Team Fortress 2 comparando o preço da
Steam com o valor de troca da backpack.tf. Ele já funciona como aplicação local de
um usuário. O que muda aqui é só a moldura: contas, sessão e hospedagem.

Duas regras do projeto valem para todo código deste plano:

1. **Nenhum teste toca a rede.** A suíte atual tem 193 testes e roda em 0,5 s.
2. **Nenhum dado aparece no lugar de outro.** Vale também para mensagem de erro:
   "convite expirado", "convite já usado" e "convite inexistente" são a mesma
   frase na tela, porque distinguir entrega informação a quem adivinha token.

## Global Constraints

- Python 3.12+; a suíte roda com `.venv/Scripts/python -m pytest` (Windows).
- **Nenhum teste faz requisição de rede.** Banco dos testes é SQLite em memória.
- **Todo SQL vive nos repositórios.** Nenhuma rota e nenhum serviço escreve SQL.
- **Datas são UTC ingênuas** (`db.agora()`), nunca `datetime.now()` local, e todo
  serviço recebe o instante como parâmetro para o teste poder mentir sobre ele.
- **Tokens nunca são guardados em claro** — só o SHA-256 hexadecimal, 64 caracteres.
- Mensagens e nomes de código em português, como o resto do projeto.
- **CSS próprio, sem Tailwind nem framework de estilo.** As variáveis de tema
  (`--papel`, `--tinta`, `--carimbo`…) ficam no `:root` de `base.html`, e cada
  regra não óbvia carrega o comentário que diz por que ela existe.
- Commits em português, no imperativo, com as duas linhas de atribuição que os
  commits existentes usam (veja `git log -1`).
- Uma réplica só: **o freio de requisições à Steam** e o período de calma vivem
  na memória do processo. Não confundir com o **freio de login**, que é de banco
  (tabela `tentativa`) de propósito: ele precisa sobreviver a reinício, senão
  reiniciar o serviço zera as tentativas de quem está tentando adivinhar senha.
- Os totais de teste citados em cada task (`Expected: 221 passed`) são
  referência para você perceber que nada sumiu, não contrato. O que vale é a
  suíte inteira verde.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `tf2price/db.py` | schema único, fábrica de engine, `agora()` |
| `tf2price/contas/senhas.py` | Argon2id: gerar e conferir |
| `tf2price/contas/tokens.py` | token aleatório e seu hash |
| `tf2price/contas/modelo.py` | `Usuario`, `Convite`, `Sessao` (dataclasses) |
| `tf2price/contas/repositorio.py` | todo o SQL de contas |
| `tf2price/contas/servico.py` | convidar, aceitar, entrar, sair, redefinir, freio |
| `tf2price/painel/sessao.py` | cookie, dependências de conexão e usuário, origem |
| `tf2price/painel/app.py` | rotas e montagem da aplicação |
| `tf2price/painel/templates/` | `base.html` e as telas |
| `tests/conftest.py` | engine SQLite em memória compartilhada |

`tf2price/lookup/app.py` e `tf2price/lookup/templates/` são **movidos** para
`painel/` na Task 7; `tf2price/lookup/analysis.py` fica onde está e não muda.

## Sequência

1. Dependências e `db.py`
2. `senhas.py` e `tokens.py`
3. `modelo.py` e `repositorio.py`
4. `servico.py`
5. `painel/`: base, sessão, entrar e sair
6. Convite: criar conta e redefinir senha
7. Mover a consulta para dentro do painel, atrás da sessão
8. `/admin`
9. Índice da bp.tf sob demanda e implantação no Railway

---

### Task 1: `db.py` — schema, engine e relógio

**Files:**
- Modify: `pyproject.toml`
- Create: `tf2price/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nada.
- Produces: `METADATA`, as tabelas `usuario`, `convite`, `sessao`, `tentativa`,
  `url_do_ambiente() -> str`, `criar_engine(url: str | None = None) -> Engine`,
  `criar_schema(engine: Engine) -> None`, `agora() -> datetime`.

- [ ] **Step 1: Acrescentar as dependências**

Em `pyproject.toml`, na lista `dependencies`, acrescente três linhas:

```toml
dependencies = [
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "fastapi>=0.115",
    "jinja2>=3.1",
    "uvicorn>=0.30",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "argon2-cffi>=23.1",
]
```

Instale: `.venv/Scripts/python -m pip install -e ".[dev]"`

- [ ] **Step 2: Escrever o teste que falha**

Crie `tests/conftest.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from tf2price import db


@pytest.fixture
def engine() -> Engine:
    """SQLite em memória, uma conexão só.

    Sem StaticPool cada conexão abriria um banco vazio novo, e o TestClient
    perderia tudo que o teste gravou antes da requisição.
    """
    motor = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.criar_schema(motor)
    return motor
```

Crie `tests/test_db.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect

from tf2price import db


def test_criar_schema_cria_as_quatro_tabelas(engine):
    tabelas = set(inspect(engine).get_table_names())
    assert {"usuario", "convite", "sessao", "tentativa"} <= tabelas


def test_nome_de_usuario_e_unico(engine):
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        conn.execute(db.usuario.insert().values(
            nome="gusco", senha_hash="x", admin=True, ativo=True, criado_em=db.agora()
        ))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(db.usuario.insert().values(
                nome="gusco", senha_hash="y", admin=False, ativo=True, criado_em=db.agora()
            ))


@pytest.mark.parametrize(
    "bruta, esperada",
    [
        ("postgres://u:s@h:5432/d", "postgresql+psycopg://u:s@h:5432/d"),
        ("postgresql://u:s@h:5432/d", "postgresql+psycopg://u:s@h:5432/d"),
        ("postgresql+psycopg://u:s@h:5432/d", "postgresql+psycopg://u:s@h:5432/d"),
        ("sqlite+pysqlite:///:memory:", "sqlite+pysqlite:///:memory:"),
    ],
)
def test_url_do_ambiente_normaliza_o_dialeto(monkeypatch, bruta, esperada):
    """O Railway entrega postgres://, que o SQLAlchemy 2 não reconhece.

    Sem normalizar, o erro só aparece na primeira subida em produção.
    """
    monkeypatch.setenv("DATABASE_URL", bruta)
    assert db.url_do_ambiente() == esperada


def test_url_do_ambiente_sem_variavel_e_erro(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.url_do_ambiente()


def test_agora_e_utc_sem_fuso_embutido():
    """SQLite não guarda fuso e o Postgres guardaria: ingênuo em UTC dos dois lados."""
    quando = db.agora()
    assert quando.tzinfo is None
    de_fora = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((de_fora - quando).total_seconds()) < 5
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.db'`

- [ ] **Step 4: Implementar `tf2price/db.py`**

```python
"""Schema, conexão e relógio do painel.

SQLAlchemy Core, não ORM: o SQL continua explícito e confinado aos
repositórios, e o mesmo código roda em Postgres na produção e em SQLite na
memória nos testes — que precisam continuar rodando em menos de um segundo,
sem banco de pé.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.engine import Engine

METADATA = MetaData()

# Datas: UTC ingênuo dos dois lados.
#
# O Postgres guardaria o fuso e o SQLite não guarda; comparar os dois tipos
# levanta exceção em um dialeto e passa no outro, que é a classe de bug que
# testar em SQLite e rodar em Postgres pode esconder. Gravando sempre UTC sem
# fuso, os dois se comportam igual.
def agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


usuario = Table(
    "usuario",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("nome", String(60), nullable=False, unique=True),
    Column("senha_hash", String(255), nullable=False),
    Column("admin", Boolean, nullable=False, default=False),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("criado_em", DateTime, nullable=False),
)

convite = Table(
    "convite",
    METADATA,
    # Só o hash. Banco vazado não vira convite válido.
    Column("hash_do_token", String(64), primary_key=True),
    Column("tipo", String(20), nullable=False),  # "conta" ou "redefinicao"
    Column("concede_admin", Boolean, nullable=False, default=False),
    # Em "redefinicao", de quem é a senha que este link troca.
    Column("alvo", Integer, ForeignKey("usuario.id"), nullable=True),
    Column("criado_por", Integer, ForeignKey("usuario.id"), nullable=True),
    Column("criado_em", DateTime, nullable=False),
    Column("expira_em", DateTime, nullable=False),
    Column("usado_em", DateTime, nullable=True),
    Column("usado_por", Integer, ForeignKey("usuario.id"), nullable=True),
)

sessao = Table(
    "sessao",
    METADATA,
    Column("hash_do_token", String(64), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuario.id"), nullable=False),
    Column("criado_em", DateTime, nullable=False),
    Column("expira_em", DateTime, nullable=False),
)

tentativa = Table(
    "tentativa",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("nome", String(60), nullable=False),
    Column("quando", DateTime, nullable=False),
)


def url_do_ambiente() -> str:
    """URL do banco, com o dialeto normalizado.

    O Railway entrega `postgres://`, herança do Heroku, e o SQLAlchemy 2 não
    reconhece esse prefixo. Normalizar aqui evita descobrir isso na primeira
    subida em produção.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL não configurada")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def criar_engine(url: str | None = None) -> Engine:
    return create_engine(url or url_do_ambiente(), future=True, pool_pre_ping=True)


def criar_schema(engine: Engine) -> None:
    METADATA.create_all(engine)
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -q`
Expected: PASS, 8 testes

- [ ] **Step 6: Rodar a suíte inteira**

Run: `.venv/Scripts/python -m pytest`
Expected: 201 passed (193 de antes + 8)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tf2price/db.py tests/conftest.py tests/test_db.py
git commit -m "Declara o schema do painel em SQLAlchemy Core"
```

Corpo do commit: registre que o mesmo schema roda em Postgres e em SQLite, por que
as datas são UTC ingênuas, e que `postgres://` do Railway precisa de normalização.

---

### Task 2: `senhas.py` e `tokens.py`

**Files:**
- Create: `tf2price/contas/__init__.py` (vazio)
- Create: `tf2price/contas/senhas.py`
- Create: `tf2price/contas/tokens.py`
- Test: `tests/contas/__init__.py` (vazio), `tests/contas/test_senhas.py`, `tests/contas/test_tokens.py`

**Interfaces:**
- Consumes: nada.
- Produces: `senhas.SENHA_MINIMA: int`, `senhas.SenhaCurta(ValueError)`,
  `senhas.gerar(senha: str) -> str`, `senhas.confere(hash_guardado: str, senha: str) -> bool`;
  `tokens.novo() -> tuple[str, str]` (claro, hash), `tokens.hash_de(token: str) -> str`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/contas/test_senhas.py`:

```python
from __future__ import annotations

import pytest

from tf2price.contas import senhas


def test_hash_confere_com_a_senha_certa():
    guardado = senhas.gerar("uma senha longa")
    assert senhas.confere(guardado, "uma senha longa") is True


def test_hash_recusa_senha_errada():
    guardado = senhas.gerar("uma senha longa")
    assert senhas.confere(guardado, "outra senha longa") is False


def test_duas_senhas_iguais_geram_hashes_diferentes():
    """Argon2 embute sal aleatório; hash igual denunciaria senha igual."""
    assert senhas.gerar("uma senha longa") != senhas.gerar("uma senha longa")


def test_senha_curta_e_recusada():
    with pytest.raises(senhas.SenhaCurta):
        senhas.gerar("curta")


def test_hash_corrompido_nao_levanta_excecao():
    """Um hash inválido no banco não pode derrubar a tela de entrar."""
    assert senhas.confere("isto nao e um hash", "uma senha longa") is False
```

Crie `tests/contas/test_tokens.py`:

```python
from __future__ import annotations

from tf2price.contas import tokens


def test_novo_devolve_claro_e_hash_correspondentes():
    claro, resumo = tokens.novo()
    assert tokens.hash_de(claro) == resumo


def test_dois_tokens_nunca_se_repetem():
    assert tokens.novo()[0] != tokens.novo()[0]


def test_hash_tem_64_caracteres_hexadecimais():
    _, resumo = tokens.novo()
    assert len(resumo) == 64
    assert set(resumo) <= set("0123456789abcdef")


def test_token_claro_e_longo_o_bastante():
    """32 bytes aleatórios: adivinhar por força bruta está fora de questão."""
    claro, _ = tokens.novo()
    assert len(claro) >= 40
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/contas -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.contas'`

- [ ] **Step 3: Implementar os dois módulos**

Crie `tf2price/contas/__init__.py` vazio e `tests/contas/__init__.py` vazio.

`tf2price/contas/senhas.py`:

```python
"""Hash de senha com Argon2id.

O dono do painel nunca vê senha de ninguém, e o banco nunca guarda senha —
só o hash, com sal embutido pela própria biblioteca.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SENHA_MINIMA = 10

_HASHER = PasswordHasher()


class SenhaCurta(ValueError):
    """Senha abaixo do mínimo."""


def gerar(senha: str) -> str:
    if len(senha) < SENHA_MINIMA:
        raise SenhaCurta(f"a senha precisa de pelo menos {SENHA_MINIMA} caracteres")
    return _HASHER.hash(senha)


def confere(hash_guardado: str, senha: str) -> bool:
    # verify() devolve True ou levanta. Um hash corrompido no banco não pode
    # derrubar a tela de entrar, então as três exceções viram False.
    try:
        return _HASHER.verify(hash_guardado, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```

`tf2price/contas/tokens.py`:

```python
"""Token aleatório para convite e sessão, e o resumo que vai para o banco.

O banco guarda só o SHA-256: um vazamento não entrega convite nem sessão
utilizáveis. Não há salt aqui de propósito — o token já tem 32 bytes de
entropia, e precisamos achá-lo pela chave primária numa consulta.
"""

from __future__ import annotations

import hashlib
import secrets


def hash_de(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def novo() -> tuple[str, str]:
    """Devolve (token em claro, hash). O claro só existe no link enviado."""
    token = secrets.token_urlsafe(32)
    return token, hash_de(token)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/contas -q`
Expected: PASS, 9 testes

- [ ] **Step 5: Suíte inteira**

Run: `.venv/Scripts/python -m pytest`
Expected: 210 passed

- [ ] **Step 6: Commit**

```bash
git add tf2price/contas tests/contas
git commit -m "Adiciona hash de senha e tokens de uso único"
```

---

### Task 3: `modelo.py` e `repositorio.py` — todo o SQL de contas

**Files:**
- Create: `tf2price/contas/modelo.py`
- Create: `tf2price/contas/repositorio.py`
- Test: `tests/contas/test_repositorio.py`

**Interfaces:**
- Consumes: `db.usuario`, `db.convite`, `db.sessao`, `db.tentativa`, `db.agora`.
- Produces: dataclasses `Usuario(id, nome, senha_hash, admin, ativo, criado_em)`,
  `Convite(hash_do_token, tipo, concede_admin, alvo, criado_por, criado_em, expira_em, usado_em, usado_por)`,
  `Sessao(hash_do_token, usuario_id, criado_em, expira_em)`; e as funções de
  `repositorio`, todas recebendo `conn: Connection` como primeiro argumento:
  `criar_usuario(conn, *, nome, senha_hash, admin, quando) -> int`,
  `usuario_por_nome(conn, nome) -> Usuario | None`,
  `usuario_por_id(conn, usuario_id) -> Usuario | None`,
  `listar_usuarios(conn) -> list[Usuario]`, `contar_usuarios(conn) -> int`,
  `definir_ativo(conn, usuario_id, ativo) -> None`,
  `trocar_senha(conn, usuario_id, senha_hash) -> None`,
  `criar_convite(conn, *, hash_do_token, tipo, concede_admin, alvo, criado_por, criado_em, expira_em) -> None`,
  `convite_por_hash(conn, hash_do_token) -> Convite | None`,
  `marcar_convite_usado(conn, hash_do_token, *, usado_em, usado_por) -> None`,
  `criar_sessao(conn, *, hash_do_token, usuario_id, criado_em, expira_em) -> None`,
  `sessao_por_hash(conn, hash_do_token) -> Sessao | None`,
  `apagar_sessao(conn, hash_do_token) -> None`,
  `apagar_sessoes_do_usuario(conn, usuario_id) -> None`,
  `registrar_tentativa(conn, nome, quando) -> None`,
  `contar_tentativas(conn, nome, desde) -> int`,
  `limpar_tentativas(conn, nome) -> None`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/contas/test_repositorio.py`:

```python
from __future__ import annotations

from datetime import timedelta

from tf2price import db
from tf2price.contas import repositorio as repo

AGORA = db.agora()


def _usuario(conn, nome="gusco", admin=True) -> int:
    return repo.criar_usuario(
        conn, nome=nome, senha_hash="hash", admin=admin, quando=AGORA
    )


def test_criar_e_buscar_usuario_por_nome(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        achado = repo.usuario_por_nome(conn, "gusco")
    assert achado is not None
    assert achado.id == ident
    assert achado.nome == "gusco"
    assert achado.admin is True
    assert achado.ativo is True


def test_booleanos_voltam_como_bool_e_nao_como_inteiro(engine):
    """O SQLite devolve 0 e 1; `if usuario.admin` mentiria em comparação estrita."""
    with engine.begin() as conn:
        _usuario(conn, admin=False)
        achado = repo.usuario_por_nome(conn, "gusco")
    assert achado.admin is False


def test_usuario_inexistente_e_none(engine):
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "ninguem") is None
        assert repo.usuario_por_id(conn, 999) is None


def test_contar_usuarios(engine):
    with engine.begin() as conn:
        assert repo.contar_usuarios(conn) == 0
        _usuario(conn)
        assert repo.contar_usuarios(conn) == 1


def test_desativar_e_trocar_senha(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        repo.definir_ativo(conn, ident, False)
        repo.trocar_senha(conn, ident, "outro hash")
        achado = repo.usuario_por_id(conn, ident)
    assert achado.ativo is False
    assert achado.senha_hash == "outro hash"


def test_convite_guarda_e_devolve_os_campos(engine):
    with engine.begin() as conn:
        dono = _usuario(conn)
        repo.criar_convite(
            conn, hash_do_token="a" * 64, tipo="conta", concede_admin=False,
            alvo=None, criado_por=dono, criado_em=AGORA,
            expira_em=AGORA + timedelta(days=7),
        )
        achado = repo.convite_por_hash(conn, "a" * 64)
    assert achado.tipo == "conta"
    assert achado.concede_admin is False
    assert achado.usado_em is None


def test_marcar_convite_usado(engine):
    with engine.begin() as conn:
        dono = _usuario(conn)
        repo.criar_convite(
            conn, hash_do_token="b" * 64, tipo="conta", concede_admin=False,
            alvo=None, criado_por=dono, criado_em=AGORA,
            expira_em=AGORA + timedelta(days=7),
        )
        repo.marcar_convite_usado(conn, "b" * 64, usado_em=AGORA, usado_por=dono)
        achado = repo.convite_por_hash(conn, "b" * 64)
    assert achado.usado_em == AGORA
    assert achado.usado_por == dono


def test_sessao_criada_e_apagada(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        repo.criar_sessao(
            conn, hash_do_token="c" * 64, usuario_id=ident,
            criado_em=AGORA, expira_em=AGORA + timedelta(days=30),
        )
        assert repo.sessao_por_hash(conn, "c" * 64).usuario_id == ident
        repo.apagar_sessao(conn, "c" * 64)
        assert repo.sessao_por_hash(conn, "c" * 64) is None


def test_apagar_todas_as_sessoes_do_usuario(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        for letra in "de":
            repo.criar_sessao(
                conn, hash_do_token=letra * 64, usuario_id=ident,
                criado_em=AGORA, expira_em=AGORA + timedelta(days=30),
            )
        repo.apagar_sessoes_do_usuario(conn, ident)
        assert repo.sessao_por_hash(conn, "d" * 64) is None
        assert repo.sessao_por_hash(conn, "e" * 64) is None


def test_tentativas_contam_apenas_dentro_da_janela(engine):
    with engine.begin() as conn:
        repo.registrar_tentativa(conn, "gusco", AGORA - timedelta(hours=1))
        repo.registrar_tentativa(conn, "gusco", AGORA)
        repo.registrar_tentativa(conn, "outro", AGORA)
        recentes = repo.contar_tentativas(conn, "gusco", AGORA - timedelta(minutes=15))
    assert recentes == 1


def test_limpar_tentativas_apaga_so_daquele_nome(engine):
    with engine.begin() as conn:
        repo.registrar_tentativa(conn, "gusco", AGORA)
        repo.registrar_tentativa(conn, "outro", AGORA)
        repo.limpar_tentativas(conn, "gusco")
        antigo = AGORA - timedelta(minutes=15)
        assert repo.contar_tentativas(conn, "gusco", antigo) == 0
        assert repo.contar_tentativas(conn, "outro", antigo) == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/contas/test_repositorio.py -q`
Expected: FAIL com `ImportError: cannot import name 'repositorio'`

- [ ] **Step 3: Implementar `tf2price/contas/modelo.py`**

```python
"""As formas que o repositório devolve. Sem comportamento, sem SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Usuario:
    id: int
    nome: str
    senha_hash: str
    admin: bool
    ativo: bool
    criado_em: datetime


@dataclass(frozen=True)
class Convite:
    hash_do_token: str
    tipo: str
    concede_admin: bool
    alvo: int | None
    criado_por: int | None
    criado_em: datetime
    expira_em: datetime
    usado_em: datetime | None
    usado_por: int | None


@dataclass(frozen=True)
class Sessao:
    hash_do_token: str
    usuario_id: int
    criado_em: datetime
    expira_em: datetime
```

- [ ] **Step 4: Implementar `tf2price/contas/repositorio.py`**

```python
"""Todo o SQL de contas mora aqui.

Nenhuma rota e nenhum serviço escreve SQL: trocar de banco é mexer neste
arquivo e em `db.py`, não no painel.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas.modelo import Convite, Sessao, Usuario


def _para_usuario(linha) -> Usuario:
    # bool() explícito: o SQLite devolve 0 e 1, e `admin is True` mentiria.
    return Usuario(
        id=linha.id,
        nome=linha.nome,
        senha_hash=linha.senha_hash,
        admin=bool(linha.admin),
        ativo=bool(linha.ativo),
        criado_em=linha.criado_em,
    )


def criar_usuario(
    conn: Connection, *, nome: str, senha_hash: str, admin: bool, quando: datetime
) -> int:
    resultado = conn.execute(
        insert(db.usuario).values(
            nome=nome, senha_hash=senha_hash, admin=admin, ativo=True, criado_em=quando
        )
    )
    return int(resultado.inserted_primary_key[0])


def usuario_por_nome(conn: Connection, nome: str) -> Usuario | None:
    linha = conn.execute(
        select(db.usuario).where(db.usuario.c.nome == nome)
    ).first()
    return _para_usuario(linha) if linha else None


def usuario_por_id(conn: Connection, usuario_id: int) -> Usuario | None:
    linha = conn.execute(
        select(db.usuario).where(db.usuario.c.id == usuario_id)
    ).first()
    return _para_usuario(linha) if linha else None


def listar_usuarios(conn: Connection) -> list[Usuario]:
    linhas = conn.execute(select(db.usuario).order_by(db.usuario.c.nome)).all()
    return [_para_usuario(linha) for linha in linhas]


def contar_usuarios(conn: Connection) -> int:
    return int(conn.execute(select(func.count()).select_from(db.usuario)).scalar_one())


def definir_ativo(conn: Connection, usuario_id: int, ativo: bool) -> None:
    conn.execute(
        update(db.usuario).where(db.usuario.c.id == usuario_id).values(ativo=ativo)
    )


def trocar_senha(conn: Connection, usuario_id: int, senha_hash: str) -> None:
    conn.execute(
        update(db.usuario)
        .where(db.usuario.c.id == usuario_id)
        .values(senha_hash=senha_hash)
    )


def criar_convite(
    conn: Connection,
    *,
    hash_do_token: str,
    tipo: str,
    concede_admin: bool,
    alvo: int | None,
    criado_por: int | None,
    criado_em: datetime,
    expira_em: datetime,
) -> None:
    conn.execute(
        insert(db.convite).values(
            hash_do_token=hash_do_token,
            tipo=tipo,
            concede_admin=concede_admin,
            alvo=alvo,
            criado_por=criado_por,
            criado_em=criado_em,
            expira_em=expira_em,
            usado_em=None,
            usado_por=None,
        )
    )


def convite_por_hash(conn: Connection, hash_do_token: str) -> Convite | None:
    linha = conn.execute(
        select(db.convite).where(db.convite.c.hash_do_token == hash_do_token)
    ).first()
    if linha is None:
        return None
    return Convite(
        hash_do_token=linha.hash_do_token,
        tipo=linha.tipo,
        concede_admin=bool(linha.concede_admin),
        alvo=linha.alvo,
        criado_por=linha.criado_por,
        criado_em=linha.criado_em,
        expira_em=linha.expira_em,
        usado_em=linha.usado_em,
        usado_por=linha.usado_por,
    )


def marcar_convite_usado(
    conn: Connection, hash_do_token: str, *, usado_em: datetime, usado_por: int
) -> None:
    conn.execute(
        update(db.convite)
        .where(db.convite.c.hash_do_token == hash_do_token)
        .values(usado_em=usado_em, usado_por=usado_por)
    )


def criar_sessao(
    conn: Connection,
    *,
    hash_do_token: str,
    usuario_id: int,
    criado_em: datetime,
    expira_em: datetime,
) -> None:
    conn.execute(
        insert(db.sessao).values(
            hash_do_token=hash_do_token,
            usuario_id=usuario_id,
            criado_em=criado_em,
            expira_em=expira_em,
        )
    )


def sessao_por_hash(conn: Connection, hash_do_token: str) -> Sessao | None:
    linha = conn.execute(
        select(db.sessao).where(db.sessao.c.hash_do_token == hash_do_token)
    ).first()
    if linha is None:
        return None
    return Sessao(
        hash_do_token=linha.hash_do_token,
        usuario_id=linha.usuario_id,
        criado_em=linha.criado_em,
        expira_em=linha.expira_em,
    )


def apagar_sessao(conn: Connection, hash_do_token: str) -> None:
    conn.execute(delete(db.sessao).where(db.sessao.c.hash_do_token == hash_do_token))


def apagar_sessoes_do_usuario(conn: Connection, usuario_id: int) -> None:
    conn.execute(delete(db.sessao).where(db.sessao.c.usuario_id == usuario_id))


def registrar_tentativa(conn: Connection, nome: str, quando: datetime) -> None:
    conn.execute(insert(db.tentativa).values(nome=nome, quando=quando))


def contar_tentativas(conn: Connection, nome: str, desde: datetime) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(db.tentativa)
            .where(db.tentativa.c.nome == nome, db.tentativa.c.quando >= desde)
        ).scalar_one()
    )


def limpar_tentativas(conn: Connection, nome: str) -> None:
    conn.execute(delete(db.tentativa).where(db.tentativa.c.nome == nome))
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/contas/test_repositorio.py -q`
Expected: PASS, 11 testes

- [ ] **Step 6: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: 221 passed

```bash
git add tf2price/contas tests/contas
git commit -m "Adiciona o repositorio de contas"
```

---

### Task 4: `servico.py` — as regras de conta

**Files:**
- Create: `tf2price/contas/servico.py`
- Test: `tests/contas/test_servico.py`

**Interfaces:**
- Consumes: `repositorio`, `senhas`, `tokens`, `db.agora`.
- Produces: exceções `ConviteInvalido`, `NomeEmUso`, `CredenciaisInvalidas`,
  `ContaInativa`, `ContaBloqueada` (todas de `ErroDeConta(Exception)`); constantes
  `VALIDADE_CONVITE`, `VALIDADE_CONVITE_DE_PARTIDA`, `VALIDADE_SESSAO`,
  `JANELA_DO_FREIO`, `FALHAS_ATE_BLOQUEIO`; funções
  `convidar(conn, *, criado_por, quando, tipo="conta", concede_admin=False, alvo=None, validade=None) -> str`,
  `aceitar_convite(conn, token, *, nome, senha, quando) -> Usuario`,
  `redefinir(conn, token, *, senha, quando) -> Usuario`,
  `entrar(conn, *, nome, senha, quando) -> str`,
  `usuario_da_sessao(conn, token, quando) -> Usuario | None`,
  `sair(conn, token) -> None`,
  `convite_de_partida(conn, quando) -> str | None`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/contas/test_servico.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico

AGORA = db.agora()
SENHA = "uma senha longa"


def _dono(conn) -> int:
    return repo.criar_usuario(
        conn, nome="dono", senha_hash="hash", admin=True, quando=AGORA
    )


# --- convite -------------------------------------------------------------


def test_convite_cria_conta_e_devolve_usuario(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.nome == "amiga"
    assert novo.admin is False
    assert novo.ativo is True


def test_o_token_em_claro_nao_fica_no_banco(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        assert repo.convite_por_hash(conn, token) is None


def test_convite_nao_serve_duas_vezes(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        servico.aceitar_convite(conn, token, nome="amiga", senha=SENHA, quando=AGORA)
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, token, nome="outra", senha=SENHA, quando=AGORA
            )


def test_convite_expirado_e_recusado(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        depois = AGORA + servico.VALIDADE_CONVITE + timedelta(seconds=1)
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, token, nome="amiga", senha=SENHA, quando=depois
            )


def test_token_inventado_e_recusado(engine):
    with engine.begin() as conn:
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, "token-que-nao-existe", nome="amiga", senha=SENHA, quando=AGORA
            )


def test_nome_ja_em_uso(engine):
    with engine.begin() as conn:
        dono = _dono(conn)
        token = servico.convidar(conn, criado_por=dono, quando=AGORA)
        with pytest.raises(servico.NomeEmUso):
            servico.aceitar_convite(
                conn, token, nome="dono", senha=SENHA, quando=AGORA
            )


def test_convite_de_partida_so_existe_com_banco_vazio(engine):
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, AGORA)
        assert token is not None
        primeiro = servico.aceitar_convite(
            conn, token, nome="gusco", senha=SENHA, quando=AGORA
        )
        assert primeiro.admin is True
        assert servico.convite_de_partida(conn, AGORA) is None


def test_convite_comum_nunca_cria_administrador(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.admin is False


# --- entrar e sessão -----------------------------------------------------


def _com_conta(conn, nome="amiga") -> None:
    token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
    servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=AGORA)


def test_entrar_devolve_sessao_que_resolve_o_usuario(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        achado = servico.usuario_da_sessao(conn, sessao, AGORA)
    assert achado.nome == "amiga"


def test_senha_errada_nao_entra(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)


def test_nome_inexistente_da_o_mesmo_erro_da_senha_errada(engine):
    """Distinguir os dois conta a quem adivinha quais nomes existem."""
    with engine.begin() as conn:
        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome="ninguem", senha=SENHA, quando=AGORA)


def test_sessao_expirada_nao_resolve(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        depois = AGORA + servico.VALIDADE_SESSAO + timedelta(seconds=1)
        assert servico.usuario_da_sessao(conn, sessao, depois) is None


def test_sair_invalida_a_sessao(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        servico.sair(conn, sessao)
        assert servico.usuario_da_sessao(conn, sessao, AGORA) is None


def test_usuario_desativado_perde_a_sessao_e_nao_entra(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        repo.definir_ativo(conn, repo.usuario_por_nome(conn, "amiga").id, False)
        assert servico.usuario_da_sessao(conn, sessao, AGORA) is None
        with pytest.raises(servico.ContaInativa):
            servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)


def test_sessao_inexistente_e_none(engine):
    with engine.begin() as conn:
        assert servico.usuario_da_sessao(conn, "nao-existe", AGORA) is None


# --- freio ---------------------------------------------------------------


def test_cinco_erros_bloqueiam_o_nome(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        # Agora nem a senha certa passa.
        with pytest.raises(servico.ContaBloqueada):
            servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)


def test_o_bloqueio_passa_depois_da_janela(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        depois = AGORA + servico.JANELA_DO_FREIO + timedelta(seconds=1)
        assert servico.entrar(conn, nome="amiga", senha=SENHA, quando=depois)


def test_acertar_a_senha_limpa_o_contador(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO - 1):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        assert repo.contar_tentativas(conn, "amiga", AGORA - timedelta(minutes=15)) == 0


# --- redefinir -----------------------------------------------------------


def test_redefinir_troca_a_senha_e_derruba_as_sessoes(engine):
    with engine.begin() as conn:
        dono = _dono(conn)
        _com_conta(conn, nome="amiga")
        alvo = repo.usuario_por_nome(conn, "amiga").id
        antiga = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)

        token = servico.convidar(
            conn, criado_por=dono, quando=AGORA, tipo="redefinicao", alvo=alvo
        )
        servico.redefinir(conn, token, senha="senha novinha", quando=AGORA)

        assert servico.usuario_da_sessao(conn, antiga, AGORA) is None
        assert servico.entrar(conn, nome="amiga", senha="senha novinha", quando=AGORA)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/contas/test_servico.py -q`
Expected: FAIL com `ImportError: cannot import name 'servico'`

- [ ] **Step 3: Implementar `tf2price/contas/servico.py`**

```python
"""As regras de conta. Recebe conexão, não abre nenhuma; não escreve SQL.

Todo instante entra por parâmetro (`quando`) em vez de vir de `datetime.now`,
pelo mesmo motivo que `lookup/analysis` faz isso: teste de expiração precisa
mentir sobre o relógio sem esperar sete dias.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.engine import Connection

from tf2price.contas import repositorio as repo
from tf2price.contas import senhas, tokens
from tf2price.contas.modelo import Usuario

VALIDADE_CONVITE = timedelta(days=7)
VALIDADE_CONVITE_DE_PARTIDA = timedelta(hours=24)
VALIDADE_SESSAO = timedelta(days=30)
JANELA_DO_FREIO = timedelta(minutes=15)
FALHAS_ATE_BLOQUEIO = 5

TIPO_CONTA = "conta"
TIPO_REDEFINICAO = "redefinicao"


class ErroDeConta(Exception):
    """Raiz dos erros esperados de conta."""


class ConviteInvalido(ErroDeConta):
    """Inexistente, expirado ou já usado — a tela não distingue os três."""


class NomeEmUso(ErroDeConta):
    pass


class CredenciaisInvalidas(ErroDeConta):
    """Nome que não existe ou senha errada — a tela não distingue os dois."""


class ContaInativa(ErroDeConta):
    pass


class ContaBloqueada(ErroDeConta):
    pass


def convidar(
    conn: Connection,
    *,
    criado_por: int | None,
    quando: datetime,
    tipo: str = TIPO_CONTA,
    concede_admin: bool = False,
    alvo: int | None = None,
    validade: timedelta | None = None,
) -> str:
    """Cria o convite e devolve o token em claro, que só existe no link."""
    claro, resumo = tokens.novo()
    repo.criar_convite(
        conn,
        hash_do_token=resumo,
        tipo=tipo,
        concede_admin=concede_admin,
        alvo=alvo,
        criado_por=criado_por,
        criado_em=quando,
        expira_em=quando + (validade or VALIDADE_CONVITE),
    )
    return claro


def convite_de_partida(conn: Connection, quando: datetime) -> str | None:
    """Primeiro acesso: com o banco vazio, gera um convite de administrador.

    Devolve `None` quando já existe alguém — assim a subida pode chamar isto
    sempre, sem risco de abrir uma porta num painel já povoado.
    """
    if repo.contar_usuarios(conn) > 0:
        return None
    return convidar(
        conn,
        criado_por=None,
        quando=quando,
        concede_admin=True,
        validade=VALIDADE_CONVITE_DE_PARTIDA,
    )


def _convite_utilizavel(conn: Connection, token: str, tipo: str, quando: datetime):
    convite = repo.convite_por_hash(conn, tokens.hash_de(token))
    if convite is None or convite.tipo != tipo:
        raise ConviteInvalido("convite inválido")
    if convite.usado_em is not None:
        raise ConviteInvalido("convite inválido")
    if convite.expira_em <= quando:
        raise ConviteInvalido("convite inválido")
    return convite


def aceitar_convite(
    conn: Connection, token: str, *, nome: str, senha: str, quando: datetime
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_CONTA, quando)
    nome = nome.strip()
    if not nome:
        raise NomeEmUso("escolha um nome")
    if repo.usuario_por_nome(conn, nome) is not None:
        raise NomeEmUso("esse nome já está em uso")

    ident = repo.criar_usuario(
        conn,
        nome=nome,
        senha_hash=senhas.gerar(senha),
        admin=convite.concede_admin,
        quando=quando,
    )
    repo.marcar_convite_usado(
        conn, convite.hash_do_token, usado_em=quando, usado_por=ident
    )
    return repo.usuario_por_id(conn, ident)


def redefinir(
    conn: Connection, token: str, *, senha: str, quando: datetime
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_REDEFINICAO, quando)
    if convite.alvo is None:
        raise ConviteInvalido("convite inválido")

    repo.trocar_senha(conn, convite.alvo, senhas.gerar(senha))
    # Trocar a senha derruba o que já estava aberto: se a troca foi por
    # suspeita, deixar a sessão antiga viva anularia a troca.
    repo.apagar_sessoes_do_usuario(conn, convite.alvo)
    repo.marcar_convite_usado(
        conn, convite.hash_do_token, usado_em=quando, usado_por=convite.alvo
    )
    return repo.usuario_por_id(conn, convite.alvo)


def entrar(conn: Connection, *, nome: str, senha: str, quando: datetime) -> str:
    """Devolve o token de sessão em claro, que vai para o cookie."""
    nome = nome.strip()
    if repo.contar_tentativas(conn, nome, quando - JANELA_DO_FREIO) >= FALHAS_ATE_BLOQUEIO:
        raise ContaBloqueada("tentativas demais; espere alguns minutos")

    usuario = repo.usuario_por_nome(conn, nome)
    if usuario is None or not senhas.confere(usuario.senha_hash, senha):
        repo.registrar_tentativa(conn, nome, quando)
        raise CredenciaisInvalidas("nome ou senha incorretos")
    if not usuario.ativo:
        raise ContaInativa("esta conta está desativada")

    repo.limpar_tentativas(conn, nome)
    claro, resumo = tokens.novo()
    repo.criar_sessao(
        conn,
        hash_do_token=resumo,
        usuario_id=usuario.id,
        criado_em=quando,
        expira_em=quando + VALIDADE_SESSAO,
    )
    return claro


def usuario_da_sessao(
    conn: Connection, token: str, quando: datetime
) -> Usuario | None:
    if not token:
        return None
    sessao = repo.sessao_por_hash(conn, tokens.hash_de(token))
    if sessao is None or sessao.expira_em <= quando:
        return None
    usuario = repo.usuario_por_id(conn, sessao.usuario_id)
    if usuario is None or not usuario.ativo:
        return None
    return usuario


def sair(conn: Connection, token: str) -> None:
    if token:
        repo.apagar_sessao(conn, tokens.hash_de(token))
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/contas/test_servico.py -q`
Expected: PASS, 18 testes

- [ ] **Step 5: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: 239 passed

```bash
git add tf2price/contas tests/contas
git commit -m "Adiciona as regras de convite, sessao e freio de login"
```

---

### Task 5: `painel/` — base, sessão, entrar e sair

**Files:**
- Create: `tf2price/painel/__init__.py` (vazio)
- Create: `tf2price/painel/sessao.py`
- Create: `tf2price/painel/app.py`
- Create: `tf2price/painel/templates/base.html`, `entrar.html`
- Test: `tests/painel/__init__.py` (vazio), `tests/painel/test_entrar.py`

**Interfaces:**
- Consumes: `db.criar_engine`, `db.agora`, `contas.servico`.
- Produces: `sessao.NOME_COOKIE = "sessao"`, `sessao.PrecisaEntrar`,
  `sessao.PrecisaSerAdmin`, `sessao.conexao`, `sessao.usuario_opcional`,
  `sessao.usuario_obrigatorio`, `sessao.exigir_admin`, `sessao.mesma_origem`,
  `sessao.gravar_cookie(resposta, request, token)`, `sessao.apagar_cookie(resposta)`;
  `app.criar_app(engine) -> FastAPI` (a Task 7 acrescenta um segundo parâmetro),
  `app.TEMPLATES`.
- Nota: a rota `/` criada aqui é provisória e é substituída na Task 7.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_entrar.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

SENHA = "uma senha longa"


@pytest.fixture
def cliente(engine):
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
        servico.aceitar_convite(conn, token, nome="gusco", senha=SENHA, quando=db.agora())
    return TestClient(criar_app(engine), follow_redirects=False)


def test_entrar_mostra_o_formulario(cliente):
    r = cliente.get("/entrar")
    assert r.status_code == 200
    assert "senha" in r.text.lower()


def test_entrar_com_senha_certa_cria_cookie_e_redireciona(cliente):
    r = cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert cliente.cookies.get(NOME_COOKIE)


def test_entrar_com_senha_errada_nao_cria_cookie(cliente):
    r = cliente.post("/entrar", data={"nome": "gusco", "senha": "errada demais"})
    assert r.status_code == 200
    assert "nome ou senha" in r.text.lower()
    assert cliente.cookies.get(NOME_COOKIE) is None


def test_painel_sem_cookie_manda_para_entrar(cliente):
    r = cliente.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/entrar"


def test_fragmento_htmx_sem_cookie_devolve_401_com_redirecionamento(cliente):
    """Um 303 dentro de fragmento seria engolido pelo swap do HTMX.

    O navegador só sai da página quando o HTMX vê HX-Redirect.
    """
    r = cliente.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/entrar"


def test_com_cookie_o_painel_abre(cliente):
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    r = cliente.get("/")
    assert r.status_code == 200
    assert "gusco" in r.text


def test_sair_apaga_a_sessao(cliente):
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    r = cliente.post("/sair")
    assert r.status_code == 303
    assert cliente.get("/").status_code == 303


def test_post_de_outra_origem_e_recusado(cliente):
    """SameSite=Lax já barra o navegador; isto barra o resto."""
    r = cliente.post(
        "/entrar",
        data={"nome": "gusco", "senha": SENHA},
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.painel'`

- [ ] **Step 3: Implementar `tf2price/painel/sessao.py`**

```python
"""Cookie de sessão, dependências de requisição e conferência de origem."""

from __future__ import annotations

from typing import Iterator
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas import servico
from tf2price.contas.modelo import Usuario

NOME_COOKIE = "sessao"


class PrecisaEntrar(Exception):
    """Sem sessão válida. O tratador decide entre redirecionar e HX-Redirect."""


class PrecisaSerAdmin(Exception):
    """Sessão válida, mas sem permissão."""


def conexao(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.begin() as conn:
        yield conn


def usuario_opcional(
    request: Request, conn: Connection = Depends(conexao)
) -> Usuario | None:
    token = request.cookies.get(NOME_COOKIE, "")
    return servico.usuario_da_sessao(conn, token, db.agora())


def usuario_obrigatorio(
    usuario: Usuario | None = Depends(usuario_opcional),
) -> Usuario:
    if usuario is None:
        raise PrecisaEntrar()
    return usuario


def exigir_admin(usuario: Usuario = Depends(usuario_obrigatorio)) -> Usuario:
    if not usuario.admin:
        raise PrecisaSerAdmin()
    return usuario


def mesma_origem(request: Request) -> None:
    """Recusa POST vindo de outro site.

    O cookie já é SameSite=Lax, o que barra o navegador; esta conferência
    cobre o que não é navegador. Quando o cabeçalho Origin não vem — curl,
    teste — não há o que comparar e a requisição segue.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    origem = request.headers.get("origin")
    if origem and urlparse(origem).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="origem não confere")


def gravar_cookie(resposta: Response, request: Request, token: str) -> None:
    # `Secure` pelo esquema da requisição: fixá-lo sempre impediria entrar em
    # http://127.0.0.1 no desenvolvimento. Em produção, atrás do proxy do
    # Railway, o uvicorn precisa de --proxy-headers para que o esquema chegue
    # como https (veja a Task 9).
    resposta.set_cookie(
        NOME_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=int(servico.VALIDADE_SESSAO.total_seconds()),
        path="/",
    )


def apagar_cookie(resposta: Response) -> None:
    resposta.delete_cookie(NOME_COOKIE, path="/")
```

- [ ] **Step 4: Criar `tf2price/painel/templates/base.html`**

O `base.html` carrega **apenas o que as telas de conta usam**. Copie de
`tf2price/lookup/templates/index.html`, verbatim e com os comentários, só estes
trechos:

- o bloco `:root` inteiro (as variáveis de tema)
- `*, *::before, *::after`, `body`, `body::before`
- `.guia`, `.timbre`, `.timbre h1`, `.cotacao`, `.cotacao b`
- `.campo`, `.campo + .campo`, `.rotulo`, `.dica`, `.dica b`
- `.erro`, `.erro b`, `a`, `a:hover`, `:focus-visible`
- as duas media queries, de `prefers-reduced-motion` e de impressão

**Não copie** as regras de `.opcoes`, `.linha`, `.bloco`, `.carimbo`, `.tag`,
`.numero-grande` e companhia: elas pertencem à análise, continuam em
`index.html` enquanto ele existir, e a Task 7 as traz para cá junto com o
template. Assim nenhuma regra vive em dois arquivos ao mesmo tempo.

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{% block titulo %}Avaliação de Unusual{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    /* COLE AQUI os trechos listados acima, verbatim, e acrescente: */

    .topo-conta {
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 1rem; margin-bottom: .6rem;
      font-family: var(--mono); font-size: .72rem; letter-spacing: .09em;
      text-transform: uppercase; color: var(--tinta-2);
    }
    .topo-conta form { margin: 0; }
    .topo-conta button {
      background: none; border: 0; padding: 0; cursor: pointer;
      font: inherit; color: var(--tinta-2); text-decoration: underline;
    }
    .topo-conta button:hover { color: var(--carimbo); }
    .campo-form { margin-bottom: 1rem; }
    .campo-form label {
      display: block; margin-bottom: .3rem;
      font-family: var(--display); font-weight: 700; font-size: .95rem;
      text-transform: uppercase; letter-spacing: .14em; color: var(--tinta-2);
    }
    .campo-form input {
      width: 100%; padding: .45rem .1rem;
      border: 0; border-bottom: 2px solid var(--tinta); border-radius: 0;
      background: transparent; color: var(--tinta);
      font-family: var(--corpo); font-size: 1.1rem;
    }
    .campo-form input:focus { outline: 0; border-bottom-color: var(--carimbo); }
    .acao {
      font-family: var(--display); font-weight: 700; font-size: 1rem;
      text-transform: uppercase; letter-spacing: .12em;
      background: var(--tinta); color: var(--slip);
      border: 0; padding: .6rem 1.4rem; cursor: pointer;
    }
    .acao:hover { background: var(--carimbo); }
  </style>
</head>
<body{% block corpo_attrs %}{% endblock %}>
  <main class="guia">
    <header class="timbre">
      {% if usuario %}
      <div class="topo-conta">
        <span>{{ usuario.nome }}{% if usuario.admin %} · <a href="/admin">admin</a>{% endif %}</span>
        <form method="post" action="/sair"><button type="submit">sair</button></form>
      </div>
      {% endif %}
      <h1>{% block cabecalho %}Avaliação de Unusual{% endblock %}</h1>
      {% block subtitulo %}{% endblock %}
    </header>
    {% block conteudo %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 5: Criar `tf2price/painel/templates/entrar.html`**

```html
{% extends "base.html" %}
{% block titulo %}Entrar{% endblock %}
{% block cabecalho %}Entrar{% endblock %}
{% block conteudo %}
<section class="campo">
  {% if erro %}<div class="erro"><b>Não deu para entrar</b>{{ erro }}</div>{% endif %}
  <form method="post" action="/entrar">
    <div class="campo-form">
      <label for="nome">Nome</label>
      <input id="nome" name="nome" autocomplete="username" autofocus required>
    </div>
    <div class="campo-form">
      <label for="senha">Senha</label>
      <input id="senha" name="senha" type="password" autocomplete="current-password" required>
    </div>
    <button class="acao" type="submit">Entrar</button>
  </form>
  <p class="dica">Este painel é fechado. Quem entra, entra por um convite.</p>
</section>
{% endblock %}
```

- [ ] **Step 6: Implementar `tf2price/painel/app.py`**

```python
"""Montagem da aplicação, rotas de sessão e tratadores de erro."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Connection, Engine

from tf2price import db
from tf2price.contas import servico
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def criar_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="Painel de Unusual")
    app.state.engine = engine

    @app.exception_handler(ses.PrecisaEntrar)
    def _sem_sessao(request: Request, _exc: ses.PrecisaEntrar) -> Response:
        # Fragmento HTMX não pode receber 303: o swap engoliria a página de
        # entrar dentro do alvo. HX-Redirect tira o navegador da página.
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/entrar"})
        return RedirectResponse("/entrar", status_code=303)

    @app.exception_handler(ses.PrecisaSerAdmin)
    def _sem_permissao(request: Request, _exc: ses.PrecisaSerAdmin) -> Response:
        return HTMLResponse("Esta página é só do administrador.", status_code=403)

    @app.get("/entrar", response_class=HTMLResponse)
    def tela_entrar(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request, name="entrar.html", context={"erro": None}
        )

    @app.post("/entrar", dependencies=[Depends(ses.mesma_origem)])
    def fazer_entrar(
        request: Request,
        nome: str = Form(...),
        senha: str = Form(...),
        conn: Connection = Depends(ses.conexao),
    ) -> Response:
        try:
            token = servico.entrar(conn, nome=nome, senha=senha, quando=db.agora())
        except servico.ErroDeConta as erro:
            return TEMPLATES.TemplateResponse(
                request=request, name="entrar.html", context={"erro": str(erro)}
            )
        resposta = RedirectResponse("/", status_code=303)
        ses.gravar_cookie(resposta, request, token)
        return resposta

    @app.post("/sair", dependencies=[Depends(ses.mesma_origem)])
    def fazer_sair(
        request: Request, conn: Connection = Depends(ses.conexao)
    ) -> Response:
        servico.sair(conn, request.cookies.get(ses.NOME_COOKIE, ""))
        resposta = RedirectResponse("/entrar", status_code=303)
        ses.apagar_cookie(resposta)
        return resposta

    # Provisória: a Task 7 troca o corpo desta rota pela consulta.
    @app.get("/", response_class=HTMLResponse)
    def painel(
        request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)
    ):
        return TEMPLATES.TemplateResponse(
            request=request, name="base.html", context={"usuario": usuario}
        )

    return app
```

- [ ] **Step 7: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/painel -q`
Expected: PASS, 8 testes

- [ ] **Step 8: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: 247 passed

```bash
git add tf2price/painel tests/painel
git commit -m "Poe a aplicacao atras de uma sessao"
```

---

### Task 6: convite — criar conta e redefinir senha

**Files:**
- Modify: `tf2price/painel/app.py`
- Create: `tf2price/painel/templates/convite.html`
- Test: `tests/painel/test_convite.py`

**Interfaces:**
- Consumes: `servico.aceitar_convite`, `servico.redefinir`, `servico.TIPO_CONTA`,
  `servico.TIPO_REDEFINICAO`, `repositorio.convite_por_hash`, `tokens.hash_de`.
- Produces: rotas `GET /convite/{token}` e `POST /convite/{token}`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_convite.py`:

```python
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

SENHA = "uma senha longa"


@pytest.fixture
def cliente(engine):
    return TestClient(criar_app(engine), follow_redirects=False)


def _convite(engine, **kwargs) -> str:
    with engine.begin() as conn:
        dono = repo.criar_usuario(
            conn, nome="dono", senha_hash="hash", admin=True, quando=db.agora()
        )
        return servico.convidar(conn, criado_por=dono, quando=db.agora(), **kwargs)


def test_link_valido_mostra_o_formulario(cliente, engine):
    token = _convite(engine)
    r = cliente.get(f"/convite/{token}")
    assert r.status_code == 200
    assert "senha" in r.text.lower()


def test_link_invalido_diz_a_mesma_coisa_que_o_expirado(cliente, engine):
    """Distinguir os dois conta a quem está adivinhando token."""
    inexistente = cliente.get("/convite/token-inventado")
    assert inexistente.status_code == 404

    token = _convite(engine)
    with engine.begin() as conn:
        repo.marcar_convite_usado(
            conn, tokens.hash_de(token), usado_em=db.agora(), usado_por=1
        )
    usado = cliente.get(f"/convite/{token}")
    assert usado.status_code == 404
    assert usado.text == inexistente.text


def test_aceitar_cria_a_conta_e_ja_entra(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "amiga", "senha": SENHA})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert cliente.cookies.get(NOME_COOKIE)
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is not None


def test_senha_curta_volta_com_recado_e_nao_cria_conta(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "amiga", "senha": "curta"})
    assert r.status_code == 200
    assert "10" in r.text
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is None


def test_nome_em_uso_volta_com_recado(cliente, engine):
    token = _convite(engine)
    r = cliente.post(f"/convite/{token}", data={"nome": "dono", "senha": SENHA})
    assert r.status_code == 200
    assert "uso" in r.text.lower()


def test_convite_de_redefinicao_troca_a_senha(cliente, engine):
    with engine.begin() as conn:
        dono = repo.criar_usuario(
            conn, nome="dono", senha_hash="hash", admin=True, quando=db.agora()
        )
        conta = servico.convidar(conn, criado_por=dono, quando=db.agora())
        usuario = servico.aceitar_convite(
            conn, conta, nome="amiga", senha=SENHA, quando=db.agora()
        )
        token = servico.convidar(
            conn, criado_por=dono, quando=db.agora(),
            tipo=servico.TIPO_REDEFINICAO, alvo=usuario.id,
        )

    r = cliente.get(f"/convite/{token}")
    assert "nova senha" in r.text.lower()

    r = cliente.post(f"/convite/{token}", data={"senha": "senha novinha"})
    assert r.status_code == 303

    entrou = cliente.post("/entrar", data={"nome": "amiga", "senha": "senha novinha"})
    assert entrou.status_code == 303
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_convite.py -q`
Expected: FAIL com 404 em `/convite/...` para todos os casos

- [ ] **Step 3: Criar `tf2price/painel/templates/convite.html`**

```html
{% extends "base.html" %}
{% block titulo %}{{ "Nova senha" if redefinicao else "Criar conta" }}{% endblock %}
{% block cabecalho %}{{ "Nova senha" if redefinicao else "Criar conta" }}{% endblock %}
{% block conteudo %}
<section class="campo">
  {% if erro %}<div class="erro"><b>Não deu para continuar</b>{{ erro }}</div>{% endif %}
  <form method="post" action="/convite/{{ token }}">
    {% if not redefinicao %}
    <div class="campo-form">
      <label for="nome">Nome</label>
      <input id="nome" name="nome" autocomplete="username" autofocus required>
    </div>
    {% endif %}
    <div class="campo-form">
      <label for="senha">{{ "Nova senha" if redefinicao else "Senha" }}</label>
      <input id="senha" name="senha" type="password" autocomplete="new-password"
             minlength="10" required {% if redefinicao %}autofocus{% endif %}>
    </div>
    <button class="acao" type="submit">{{ "Trocar senha" if redefinicao else "Criar conta" }}</button>
  </form>
  <p class="dica">A senha precisa de pelo menos 10 caracteres. Este link vale uma vez só.</p>
</section>
{% endblock %}
```

- [ ] **Step 4: Acrescentar as rotas em `tf2price/painel/app.py`**

Acrescente o import no topo do arquivo:

```python
from tf2price.contas import repositorio as repo
from tf2price.contas import tokens
```

E dentro de `criar_app`, antes do `return app`:

```python
    def _convite_aberto(conn: Connection, token: str):
        """Convite utilizável, ou None. Não diz por que não serve."""
        convite = repo.convite_por_hash(conn, tokens.hash_de(token))
        if convite is None or convite.usado_em is not None:
            return None
        if convite.expira_em <= db.agora():
            return None
        return convite

    @app.get("/convite/{token}", response_class=HTMLResponse)
    def tela_convite(
        request: Request, token: str, conn: Connection = Depends(ses.conexao)
    ):
        convite = _convite_aberto(conn, token)
        if convite is None:
            # Inexistente, expirado e usado dão a mesma resposta: distinguir
            # entrega informação a quem está adivinhando token.
            return HTMLResponse("Este convite não serve mais.", status_code=404)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="convite.html",
            context={
                "token": token,
                "redefinicao": convite.tipo == servico.TIPO_REDEFINICAO,
                "erro": None,
            },
        )

    @app.post("/convite/{token}", dependencies=[Depends(ses.mesma_origem)])
    def usar_convite(
        request: Request,
        token: str,
        nome: str = Form(""),
        senha: str = Form(...),
        conn: Connection = Depends(ses.conexao),
    ) -> Response:
        convite = _convite_aberto(conn, token)
        if convite is None:
            return HTMLResponse("Este convite não serve mais.", status_code=404)

        redefinicao = convite.tipo == servico.TIPO_REDEFINICAO
        try:
            if redefinicao:
                usuario = servico.redefinir(conn, token, senha=senha, quando=db.agora())
            else:
                usuario = servico.aceitar_convite(
                    conn, token, nome=nome, senha=senha, quando=db.agora()
                )
        except (servico.ErroDeConta, SenhaCurta) as erro:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="convite.html",
                context={"token": token, "redefinicao": redefinicao, "erro": str(erro)},
            )

        # Já entra: pedir para digitar de novo a senha recém-escolhida é atrito
        # sem ganho, e o link acabou de provar quem é.
        sessao_token = servico.entrar_direto(conn, usuario, quando=db.agora())
        resposta = RedirectResponse("/", status_code=303)
        ses.gravar_cookie(resposta, request, sessao_token)
        return resposta
```

Acrescente também, no topo:

```python
from tf2price.contas.senhas import SenhaCurta
```

- [ ] **Step 5: Acrescentar `entrar_direto` em `tf2price/contas/servico.py`**

Logo depois de `entrar`:

```python
def entrar_direto(conn: Connection, usuario: Usuario, *, quando: datetime) -> str:
    """Abre sessão sem conferir senha, para quem acabou de provar quem é.

    Usado só após aceitar convite ou redefinir senha: exigir a senha recém
    digitada de novo seria atrito sem ganho de segurança.
    """
    claro, resumo = tokens.novo()
    repo.criar_sessao(
        conn,
        hash_do_token=resumo,
        usuario_id=usuario.id,
        criado_em=quando,
        expira_em=quando + VALIDADE_SESSAO,
    )
    return claro
```

E acrescente ao fim de `tests/contas/test_servico.py`:

```python
def test_entrar_direto_abre_sessao_sem_senha(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        usuario = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
        sessao = servico.entrar_direto(conn, usuario, quando=AGORA)
        assert servico.usuario_da_sessao(conn, sessao, AGORA).nome == "amiga"
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/painel/test_convite.py tests/contas -q`
Expected: PASS, 7 + 19 testes

- [ ] **Step 7: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: 255 passed

```bash
git add tf2price/painel tf2price/contas tests
git commit -m "Abre conta e redefine senha por link de convite"
```

---

### Task 7: mover a consulta para dentro do painel

**Files:**
- Create: `tf2price/painel/consulta.py`
- Move: `tf2price/lookup/templates/*.html` → `tf2price/painel/templates/`
- Create: `tf2price/painel/templates/painel.html` (a partir do antigo `index.html`)
- Delete: `tf2price/lookup/app.py`, `tf2price/lookup/templates/`
- Modify: `tf2price/painel/app.py`
- Move: `tests/lookup/test_app.py` → `tests/painel/test_consulta.py`

**Interfaces:**
- Consumes: `lookup.analysis.analyse`, `lookup.analysis.effects_available`,
  `domain.identity.is_unusual_name`, `sources.*`, `sessao.usuario_obrigatorio`.
- Produces: `consulta.Contexto`, `consulta.PageCache`, `consulta.construir_contexto()`,
  `consulta.ROTEADOR` (APIRouter com `/`, `/buscar`, `/efeitos`, `/analise`),
  `consulta._chaves` registrado como filtro Jinja; `app.criar_app(engine, contexto)`.

`tf2price/lookup/analysis.py` **não muda** nesta task.

- [ ] **Step 1: Mover os arquivos preservando o histórico**

```bash
git mv tf2price/lookup/templates/index.html tf2price/painel/templates/painel.html
git mv tf2price/lookup/templates/_analise.html tf2price/painel/templates/_analise.html
git mv tf2price/lookup/templates/_efeitos.html tf2price/painel/templates/_efeitos.html
git mv tf2price/lookup/templates/_erro.html tf2price/painel/templates/_erro.html
git mv tf2price/lookup/templates/_itens.html tf2price/painel/templates/_itens.html
git mv tests/lookup/test_app.py tests/painel/test_consulta.py
```

- [ ] **Step 2: Transformar `painel.html` em filho de `base.html`**

O arquivo movido ainda é uma página inteira. Duas coisas:

1. **Leve o CSS que sobrou para `base.html`.** A Task 5 levou as variáveis e a
   casca; agora vão as regras da análise — `.opcoes`, `.vazio`, `.niveis`,
   `.tag*`, `.cruz`, `.avaliacao`, `.pago`, `.cifrao`, `.numero-grande`,
   `.em-chaves`, `.bloco*`, `.explica`, `.linha*`, `.fio`, `.valor`, `.bom`,
   `.ruim`, `.nota`, `.carimbo*`, `#espera`, `#q` e as keyframes. Ao colar,
   **não repita** o que já está lá (`:root`, `body`, `.guia`, `.timbre`,
   `.campo`, `.rotulo`, `.dica`, `.erro`, `a`, `:focus-visible`): confira uma a
   uma e descarte as repetidas.
2. Troque o que está **fora** do `<main class="guia">` pelas diretivas de
   herança.

O arquivo passa a ser:

```html
{% extends "base.html" %}
{% block titulo %}Avaliação de Unusual{% endblock %}
{% block subtitulo %}
  <p class="cotacao">
    chave <b>{{ key_brl }}</b> · dólar <b>{{ usd_brl }}</b> ·
    preços da Steam já com a taxa de 15%
  </p>
{% endblock %}
{% block corpo_attrs %} hx-indicator="#espera"{% endblock %}
{% block conteudo %}
<section class="campo" data-campo="item">
  <label class="rotulo" for="q">Item</label>
  <input id="q" name="q" autocomplete="off" placeholder="parte do nome, ex: Chairholder"
         hx-get="/buscar" hx-target="#itens" hx-trigger="keyup changed delay:400ms">
  <div id="espera"></div>
  <p class="dica">Parte do nome basta. A busca aceita dupla qualidade —
    <b>Strange Unusual</b> — e ignora as ferramentas <b>Unusualifier</b>.</p>
  <div id="itens" class="opcoes"></div>
</section>

<section class="campo" data-campo="efeito">
  <span class="rotulo">Efeito</span>
  <div id="efeitos" class="opcoes colunas">
    <p class="vazio">aguardando item</p>
  </div>
</section>

<section class="campo" data-campo="avaliacao">
  <span class="rotulo">Avaliação</span>
  <div id="analise" aria-live="polite">
    <p class="vazio">aguardando efeito</p>
  </div>
</section>

<script>
  // Marca a opção escolhida dentro do próprio grupo: sem isso, depois de
  // dois cliques não dá para saber de qual item a avaliação abaixo fala.
  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest(".opcoes button");
    if (!botao) return;
    botao.parentElement.querySelectorAll("button").forEach(function (outro) {
      outro.removeAttribute("data-escolhido");
    });
    botao.setAttribute("data-escolhido", "");
  });
</script>
{% endblock %}
```

- [ ] **Step 3: Criar `tf2price/painel/consulta.py`**

O conteúdo sai de `tf2price/lookup/app.py`, com três mudanças: as rotas passam a
viver num `APIRouter`, o contexto vem de `request.app.state.contexto`, e a rota
raiz renderiza `painel.html` com o usuário.

```python
"""A consulta de Unusual: contexto, cache de página e rotas.

O que decide número continua em `lookup/analysis.py`, que não sabe que existe
usuário. Aqui só há transporte e apresentação.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from tf2price.contas.modelo import Usuario
from tf2price.domain.identity import is_unusual_name
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import analyse, effects_available
from tf2price.painel import sessao as ses
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SteamClient
from tf2price.sources.steam_page import ItemPage, PageStructureError, SteamPageClient

CACHE_TTL_S = 300.0
BUSCA_MAX = 25
INTERVALO_S = 1.0

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _chaves(valor: float) -> str:
    """Quantidade de chaves com vírgula decimal, como o resto da tela."""
    return f"{valor:.1f}".replace(".", ",")


TEMPLATES.env.filters["chaves"] = _chaves

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])
```

Em seguida, **copie de `tf2price/lookup/app.py`, sem alterar**, as classes
`PageCache` e `Contexto` e a função `construir_contexto`, e a função auxiliar
`_erro`. Depois acrescente as rotas:

```python
def _contexto(request: Request) -> Contexto:
    return request.app.state.contexto


def _pagina_do_item(contexto: Contexto, nome: str) -> ItemPage:
    guardada = contexto.cache.get(nome)
    if guardada is not None:
        return guardada
    pagina = contexto.paginas.item_page(nome, contexto.usd_to_brl)
    contexto.cache.put(nome, pagina)
    return pagina


@ROTEADOR.get("/", response_class=HTMLResponse)
def painel(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    contexto = _contexto(request)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="painel.html",
        context={
            "usuario": usuario,
            "key_brl": contexto.key_brl,
            "usd_brl": Brl.from_float(contexto.usd_to_brl),
        },
    )


@ROTEADOR.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = ""):
    contexto = _contexto(request)
    termo = q.strip()
    if not termo:
        return TEMPLATES.TemplateResponse(
            request=request, name="_itens.html", context={"nomes": []}
        )
    try:
        pagina = contexto.steam.search_page(start=0, count=BUSCA_MAX, query=termo)
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))

    nomes = [r.hash_name for r in pagina.results if is_unusual_name(r.hash_name)]
    return TEMPLATES.TemplateResponse(
        request=request, name="_itens.html", context={"nomes": nomes[:BUSCA_MAX]}
    )


@ROTEADOR.get("/efeitos", response_class=HTMLResponse)
def efeitos(request: Request, nome: str):
    contexto = _contexto(request)
    try:
        pagina = _pagina_do_item(contexto, nome)
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_efeitos.html",
        context={"nome": nome, "efeitos": effects_available(pagina)},
    )


@ROTEADOR.get("/analise", response_class=HTMLResponse)
def rota_analise(request: Request, nome: str, efeito: str):
    contexto = _contexto(request)
    try:
        pagina = _pagina_do_item(contexto, nome)
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))
    try:
        resultado = analyse(pagina, efeito, contexto.index, contexto.key_brl)
    except ValueError as erro:
        return _erro(request, str(erro))
    return TEMPLATES.TemplateResponse(
        request=request, name="_analise.html", context={"a": resultado}
    )
```

- [ ] **Step 4: Ligar o roteador em `tf2price/painel/app.py`**

Troque a assinatura e apague a rota `/` provisória:

```python
def criar_app(engine: Engine, contexto: "Contexto | None" = None) -> FastAPI:
    app = FastAPI(title="Painel de Unusual")
    app.state.engine = engine
    app.state.contexto = contexto
    ...
    # no lugar da rota `/` provisória:
    if contexto is not None:
        from tf2price.painel.consulta import ROTEADOR
        app.include_router(ROTEADOR)
    return app
```

E no fim do arquivo, o ponto de entrada:

```python
def servir() -> None:
    """Ponto de entrada: python -m tf2price.painel.app"""
    import uvicorn

    from tf2price.painel.consulta import construir_contexto

    engine = db.criar_engine()
    db.criar_schema(engine)
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    if token:
        print(f"[partida] nenhum usuário ainda. Convite de administrador: /convite/{token}")

    uvicorn.run(criar_app(engine, construir_contexto()), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    servir()
```

- [ ] **Step 5: Mover o contexto falso para `tests/painel/conftest.py`**

`test_entrar.py` também bate em `/`, que a partir daqui só existe quando há
contexto. Para os dois arquivos usarem o mesmo duplo, mova de
`tests/painel/test_consulta.py` para um `tests/painel/conftest.py` novo: as
classes `_SteamFalso` e `_PaginasFalsas`, a função `_pagina`, as constantes
`FIXTURES`, `NOME` e `CHAVE`, e a função `_contexto`. Acrescente ali o auxiliar
de login, que os dois arquivos vão usar:

```python
SENHA = "uma senha longa"


def cliente_logado(engine, ctx):
    """TestClient autenticado, com a primeira conta vinda do convite de partida."""
    from fastapi.testclient import TestClient

    from tf2price import db as _db
    from tf2price.contas import servico
    from tf2price.painel.app import criar_app

    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, _db.agora())
        servico.aceitar_convite(
            conn, token, nome="gusco", senha=SENHA, quando=_db.agora()
        )
    cliente = TestClient(criar_app(engine, ctx))
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    cliente.ctx = ctx
    return cliente
```

Em `tests/painel/test_entrar.py`, troque `criar_app(engine)` por
`criar_app(engine, _contexto())` na fixture. Os três testes que batem em `/` —
`test_painel_sem_cookie_manda_para_entrar`,
`test_fragmento_htmx_sem_cookie_devolve_401_com_redirecionamento` e
`test_com_cookie_o_painel_abre` — continuam valendo palavra por palavra.

- [ ] **Step 6: Adaptar `tests/painel/test_consulta.py`**

O corpo dos testes **não muda** — as asserções sobre dupla qualidade, Unusualifier,
carimbo, limpeza fora de banda e cotação no timbre continuam palavra por palavra.
Muda só o cabeçalho: os imports apontam para `painel`, e o cliente entra antes.

Troque os imports do topo:

```python
from tf2price.painel.app import criar_app
from tf2price.painel.consulta import Contexto, PageCache
```

E troque a fixture `cliente` por esta:

```python
@pytest.fixture
def cliente(engine):
    return cliente_logado(engine, _contexto())
```

importando `cliente_logado`, `_contexto`, `NOME` e `CHAVE` do `conftest.py`.

Nos testes que montam contexto próprio, troque `TestClient(criar_app(ctx))` por
`cliente_logado(engine, ctx)` e acrescente `engine` aos parâmetros do teste:

- `test_busca_mantem_a_dupla_qualidade(engine)`
- `test_busca_descarta_o_unusualifier(engine)`
- o auxiliar vira `_texto_da_analise(engine, idade_dias)` e o teste
  parametrizado passa a ser
  `test_o_carimbo_reflete_a_idade_do_preco(engine, idade, classe, palavra)`,
  chamando `_texto_da_analise(engine, idade)`

Acrescente um teste novo ao fim do arquivo:

```python
def test_a_consulta_exige_sessao(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    for caminho in ("/", "/buscar", "/efeitos", "/analise"):
        assert cliente.get(caminho, params={"q": "x", "nome": "x", "efeito": "x"}).status_code in (303, 401)
```

- [ ] **Step 7: Apagar o que sobrou de `lookup/app.py`**

```bash
git rm tf2price/lookup/app.py
```

Confira que nada mais o referencia:

Run: `grep -rn "lookup.app\|lookup/app" --include="*.py" --include="*.toml" --include="*.md" . | grep -v ".venv"`
Expected: só ocorrências em `docs/` e no `README.md`, que a Task 9 atualiza.

- [ ] **Step 8: Rodar tudo**

Run: `.venv/Scripts/python -m pytest`
Expected: 256 passed (os mesmos de antes, mais o teste de sessão)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Move a consulta para dentro do painel"
```

---

### Task 8: `/admin` — convidar, redefinir e desativar

**Files:**
- Modify: `tf2price/painel/app.py`
- Create: `tf2price/painel/templates/admin.html`
- Test: `tests/painel/test_admin.py`

**Interfaces:**
- Consumes: `sessao.exigir_admin`, `repositorio.listar_usuarios`,
  `repositorio.definir_ativo`, `repositorio.apagar_sessoes_do_usuario`,
  `servico.convidar`.
- Produces: rotas `GET /admin`, `POST /admin/convite`,
  `POST /admin/redefinir/{usuario_id}`, `POST /admin/ativo/{usuario_id}`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_admin.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico
from tf2price.painel.app import criar_app

SENHA = "uma senha longa"


def _entra(engine, nome, admin):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id if dono else None, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente


@pytest.fixture
def admin(engine):
    return _entra(engine, "gusco", admin=True)


def test_admin_lista_os_usuarios(admin, engine):
    _entra(engine, "amiga", admin=False)
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "gusco" in r.text and "amiga" in r.text


def test_nao_admin_leva_403(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    assert comum.get("/admin").status_code == 403


def test_sem_sessao_nao_chega_no_admin(engine):
    cliente = TestClient(criar_app(engine), follow_redirects=False)
    assert cliente.get("/admin").status_code == 303


def test_gerar_convite_mostra_o_link_uma_vez(admin):
    r = admin.post("/admin/convite")
    assert r.status_code == 200
    assert "/convite/" in r.text


def test_link_gerado_realmente_cria_conta(admin, engine):
    import re

    texto = admin.post("/admin/convite").text
    token = re.search(r"/convite/([A-Za-z0-9_\-]+)", texto).group(1)
    outro = TestClient(criar_app(engine), follow_redirects=False)
    r = outro.post(f"/convite/{token}", data={"nome": "amiga", "senha": SENHA})
    assert r.status_code == 303
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is not None


def test_redefinir_gera_link_para_aquele_usuario(admin, engine):
    _entra(engine, "amiga", admin=False)
    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    r = admin.post(f"/admin/redefinir/{alvo}")
    assert "/convite/" in r.text


def test_desativar_derruba_a_sessao_da_pessoa(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    assert comum.get("/admin").status_code == 403  # sessão viva

    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    admin.post(f"/admin/ativo/{alvo}", data={"ativo": "0"})

    comum.follow_redirects = False
    assert comum.get("/admin").status_code == 303  # sessão morta
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_admin.py -q`
Expected: FAIL com 404 em `/admin`

- [ ] **Step 3: Criar `tf2price/painel/templates/admin.html`**

```html
{% extends "base.html" %}
{% block titulo %}Administração{% endblock %}
{% block cabecalho %}Administração{% endblock %}
{% block conteudo %}
<section class="campo">
  {% if link %}
  <div class="aviso">
    <b>Link gerado.</b> Ele aparece uma vez só — copie agora.<br>
    <code>{{ link }}</code>
  </div>
  {% endif %}
  <form method="post" action="/admin/convite">
    <button class="acao" type="submit">Gerar convite</button>
  </form>
</section>

<section class="campo">
  <span class="rotulo">Pessoas</span>
  {% for u in usuarios %}
  <div class="linha">
    <span>{{ u.nome }}{% if u.admin %} · admin{% endif %}{% if not u.ativo %} · desativada{% endif %}</span>
    <span class="fio"></span>
    <form method="post" action="/admin/redefinir/{{ u.id }}" style="display:inline">
      <button type="submit">redefinir senha</button>
    </form>
    <form method="post" action="/admin/ativo/{{ u.id }}" style="display:inline">
      <input type="hidden" name="ativo" value="{{ '0' if u.ativo else '1' }}">
      <button type="submit">{{ 'desativar' if u.ativo else 'reativar' }}</button>
    </form>
  </div>
  {% endfor %}
</section>
{% endblock %}
```

- [ ] **Step 4: Acrescentar as rotas em `tf2price/painel/app.py`**

Dentro de `criar_app`, antes do `return app`:

```python
    def _tela_admin(request: Request, conn: Connection, usuario: Usuario, link=None):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "usuario": usuario,
                "usuarios": repo.listar_usuarios(conn),
                "link": link,
            },
        )

    @app.get("/admin", response_class=HTMLResponse)
    def tela_admin(
        request: Request,
        usuario: Usuario = Depends(ses.exigir_admin),
        conn: Connection = Depends(ses.conexao),
    ):
        return _tela_admin(request, conn, usuario)

    @app.post("/admin/convite", response_class=HTMLResponse,
              dependencies=[Depends(ses.mesma_origem)])
    def gerar_convite(
        request: Request,
        usuario: Usuario = Depends(ses.exigir_admin),
        conn: Connection = Depends(ses.conexao),
    ):
        token = servico.convidar(conn, criado_por=usuario.id, quando=db.agora())
        # O token em claro existe só aqui: o banco tem apenas o hash.
        return _tela_admin(request, conn, usuario, link=f"/convite/{token}")

    @app.post("/admin/redefinir/{usuario_id}", response_class=HTMLResponse,
              dependencies=[Depends(ses.mesma_origem)])
    def gerar_redefinicao(
        request: Request,
        usuario_id: int,
        usuario: Usuario = Depends(ses.exigir_admin),
        conn: Connection = Depends(ses.conexao),
    ):
        token = servico.convidar(
            conn,
            criado_por=usuario.id,
            quando=db.agora(),
            tipo=servico.TIPO_REDEFINICAO,
            alvo=usuario_id,
        )
        return _tela_admin(request, conn, usuario, link=f"/convite/{token}")

    @app.post("/admin/ativo/{usuario_id}", response_class=HTMLResponse,
              dependencies=[Depends(ses.mesma_origem)])
    def mudar_ativo(
        request: Request,
        usuario_id: int,
        ativo: str = Form(...),
        usuario: Usuario = Depends(ses.exigir_admin),
        conn: Connection = Depends(ses.conexao),
    ):
        ligado = ativo == "1"
        repo.definir_ativo(conn, usuario_id, ligado)
        if not ligado:
            # Desativar sem derrubar a sessão deixaria a pessoa dentro por
            # mais 30 dias.
            repo.apagar_sessoes_do_usuario(conn, usuario_id)
        return _tela_admin(request, conn, usuario)
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/painel/test_admin.py -q`
Expected: PASS, 7 testes

- [ ] **Step 6: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: 263 passed

```bash
git add tf2price/painel tests/painel
git commit -m "Adiciona a administracao de contas"
```

---

### Task 9: índice da bp.tf sob demanda e implantação no Railway

**Files:**
- Modify: `tf2price/lookup/analysis.py`
- Modify: `tf2price/painel/consulta.py`
- Modify: `tf2price/painel/templates/_analise.html`
- Create: `Procfile`
- Modify: `README.md`, `.env.example`
- Test: `tests/lookup/test_analysis.py`, `tests/painel/test_consulta.py`

**Interfaces:**
- Consumes: `analysis.patient_exit`.
- Produces: `analysis.RAZAO_SEM_INDICE`; `analyse(page, effect, index, key_brl, ...)`
  passa a aceitar `index: PriceIndex | None`; `consulta.IndiceSobDemanda` com
  `obter() -> PriceIndex | None`; `consulta.Cotacao` (dataclass com `key_brl: Brl`
  e `usd_to_brl: float`) e `consulta.CotacaoSobDemanda` com
  `obter() -> Cotacao | None`; `consulta.SEM_COTACAO` (mensagem).

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/lookup/test_analysis.py`:

```python
def test_sem_indice_a_saida_paciente_diz_que_falta_o_indice(pagina):
    """Diferente de "a bp.tf não precifica este efeito".

    Um é falha nossa de carregar o índice, o outro é ausência de preço.
    Misturar os dois faria a tela mentir sobre o mercado.
    """
    r = analyse(pagina, "Deep Dive", None, CHAVE, now=AGORA, effects_path=EFEITOS)
    assert r.patient.available is False
    assert r.patient.reason == RAZAO_SEM_INDICE
    assert RAZAO_SEM_PRECO != RAZAO_SEM_INDICE
```

Acrescente `RAZAO_SEM_INDICE` e `RAZAO_SEM_PRECO` ao import do topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/lookup/test_analysis.py -q`
Expected: FAIL com `ImportError: cannot import name 'RAZAO_SEM_INDICE'`

- [ ] **Step 3: Aceitar índice ausente em `tf2price/lookup/analysis.py`**

Ao lado das outras razões:

```python
RAZAO_SEM_INDICE = (
    "o índice de preços da backpack.tf ainda não carregou; tente de novo em alguns minutos"
)
```

Em `patient_exit`, logo depois da resolução do efeito:

```python
    if index is None:
        return PatientExit(False, RAZAO_SEM_INDICE, None, None, None, None)
```

E troque as assinaturas para aceitar `index: PriceIndex | None` em `patient_exit`
e em `analyse`.

- [ ] **Step 4: Implementar `IndiceSobDemanda` em `tf2price/painel/consulta.py`**

```python
class IndiceSobDemanda:
    """Carrega o índice da bp.tf na primeira necessidade, não na subida.

    Um serviço hospedado não pode morrer na partida porque um terceiro está
    fora do ar; hoje `construir_contexto` fazia exatamente isso. Se falhar,
    devolve None — e a tela diz que falta o índice, que é diferente de dizer
    que o efeito não tem preço.
    """

    def __init__(
        self,
        cliente: BackpackTfClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cliente = cliente
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._indice: PriceIndex | None = None
        self._proxima_tentativa = 0.0

    def obter(self) -> PriceIndex | None:
        if self._indice is not None:
            return self._indice
        if self._relogio() < self._proxima_tentativa:
            return None
        try:
            moedas = self._cliente.currencies()
            self._indice = PriceIndex.from_payload(
                self._cliente.prices_payload(), moedas.key_in_refined
            )
        except Exception:
            self._proxima_tentativa = self._relogio() + self._espera
            return None
        return self._indice
```

Em `Contexto`, troque o campo `index: PriceIndex` por `indice: IndiceSobDemanda`,
e em `rota_analise` troque `contexto.index` por `contexto.indice.obter()`.
Em `construir_contexto`, monte `IndiceSobDemanda(BackpackTfClient(chave))` em vez
de baixar na hora.

Acrescente a `tests/painel/test_consulta.py`:

```python
class _IndiceFalso:
    def __init__(self, indice=None):
        self.indice = indice

    def obter(self):
        return self.indice
```

e troque `index=...` por `indice=_IndiceFalso(indice or PriceIndex.from_payload(...))`
na função `_contexto`. Acrescente:

```python
def test_analise_sem_indice_nao_mente_sobre_a_bptf(engine):
    ctx = _contexto()
    ctx.indice = _IndiceFalso(None)
    cliente = cliente_logado(engine, ctx)
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert "ainda não carregou" in r.text
```

- [ ] **Step 5: Rodar tudo**

Run: `.venv/Scripts/python -m pytest`
Expected: 266 passed

- [ ] **Step 6: Tornar a cotação preguiçosa também**

O índice da bp.tf deixou de ser pré-condição de subida, mas `construir_contexto`
ainda faz **duas requisições à Steam na partida** — preço da chave e taxa do
dólar. Se a Steam responder 429 na hora do deploy, a aplicação não sobe e o
Railway reinicia em laço. É a mesma razão que a spec deu para o índice, e vale
igual aqui.

Acrescente a `tf2price/painel/consulta.py`:

```python
SEM_COTACAO = (
    "a cotação da chave ainda não carregou; tente de novo em alguns minutos"
)


@dataclass(frozen=True)
class Cotacao:
    """Preço da chave e taxa do dólar, que a tela inteira usa para converter."""

    key_brl: Brl
    usd_to_brl: float


class CotacaoSobDemanda:
    """Busca a cotação na primeira necessidade, não na subida.

    As duas vêm juntas porque as duas saem do mesmo cliente da Steam e são
    inúteis separadas: preço em chaves sem taxa de conversão não vira tela.
    """

    def __init__(
        self,
        steam: SteamClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._steam = steam
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._cotacao: Cotacao | None = None
        self._proxima_tentativa = 0.0

    def obter(self) -> Cotacao | None:
        if self._cotacao is not None:
            return self._cotacao
        if self._relogio() < self._proxima_tentativa:
            return None
        try:
            self._cotacao = Cotacao(
                key_brl=self._steam.key_price(), usd_to_brl=self._steam.usd_to_brl()
            )
        except Exception:
            self._proxima_tentativa = self._relogio() + self._espera
            return None
        return self._cotacao
```

Em `Contexto`, troque os campos `key_brl: Brl` e `usd_to_brl: float` pelo único
campo `cotacao: CotacaoSobDemanda`. Em `construir_contexto`, monte
`CotacaoSobDemanda(steam)` em vez de chamar `steam.key_price()` e
`steam.usd_to_brl()` na hora.

As quatro rotas passam a lidar com a ausência:

```python
@ROTEADOR.get("/", response_class=HTMLResponse)
def painel(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    # A cotação pode não ter carregado ainda; o painel abre assim mesmo e o
    # timbre diz isso, em vez de a aplicação não subir.
    cotacao = _contexto(request).cotacao.obter()
    return TEMPLATES.TemplateResponse(
        request=request,
        name="painel.html",
        context={"usuario": usuario, "cotacao": cotacao},
    )
```

`/buscar` não precisa de cotação e fica como está. `/efeitos` e `/analise`
precisam, e devolvem o erro próprio quando falta:

```python
    cotacao = contexto.cotacao.obter()
    if cotacao is None:
        return _erro(request, SEM_COTACAO)
```

Ponha esse bloco logo no começo das duas, antes de buscar a página, e troque
`contexto.usd_to_brl` por `cotacao.usd_to_brl` e `contexto.key_brl` por
`cotacao.key_brl` nas chamadas seguintes. `_pagina_do_item` passa a receber a
taxa como parâmetro: `_pagina_do_item(contexto, nome, usd_to_brl)`.

No `painel.html`, o bloco do timbre passa a ser:

```html
{% block subtitulo %}
  {% if cotacao %}
  <p class="cotacao">
    chave <b>{{ cotacao.key_brl }}</b> · dólar <b>{{ cotacao.usd_brl_formatado }}</b> ·
    preços da Steam já com a taxa de 15%
  </p>
  {% else %}
  <p class="cotacao">cotação da chave indisponível no momento</p>
  {% endif %}
{% endblock %}
```

Para `usd_brl_formatado` existir, acrescente à dataclass `Cotacao`:

```python
    @property
    def usd_brl_formatado(self) -> Brl:
        return Brl.from_float(self.usd_to_brl)
```

Nos testes, `tests/painel/conftest.py` monta o contexto falso: troque
`key_brl=CHAVE, usd_to_brl=1.0` por `cotacao=_CotacaoFalsa(Cotacao(CHAVE, 1.0))`,
com o duplo:

```python
class _CotacaoFalsa:
    def __init__(self, cotacao):
        self.cotacao = cotacao

    def obter(self):
        return self.cotacao
```

E acrescente a `tests/painel/test_consulta.py`:

```python
def test_sem_cotacao_a_tela_diz_e_nao_quebra(engine):
    """A Steam limitando na subida nao pode derrubar o painel inteiro."""
    ctx = _contexto()
    ctx.cotacao = _CotacaoFalsa(None)
    cliente = cliente_logado(engine, ctx)

    assert "indisponível" in cliente.get("/").text
    assert "ainda não carregou" in cliente.get(
        "/analise", params={"nome": NOME, "efeito": "Deep Dive"}
    ).text
```

- [ ] **Step 7: Rodar tudo de novo**

Run: `.venv/Scripts/python -m pytest`
Expected: tudo verde, com o teste novo da cotação ausente

- [ ] **Step 8: Criar o `Procfile`**

O Procfile final está logo abaixo; primeiro a fábrica que ele chama.

`--proxy-headers` não é enfeite: sem ele o esquema chega como `http` atrás do
proxy do Railway e o cookie de sessão nunca recebe `Secure`.

Acrescente ao fim de `tf2price/painel/app.py`:

```python
def construir_aplicacao() -> FastAPI:
    """Aplicação de produção: schema, convite de partida e contexto.

    É fábrica, e não uma variável de módulo, porque `construir_contexto` faz
    requisições à Steam: criar a aplicação no import faria qualquer `import
    tf2price.painel.app` — inclusive o de um teste — sair para a rede.
    """
    from tf2price.painel.consulta import construir_contexto

    engine = db.criar_engine()
    db.criar_schema(engine)
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    if token:
        # Primeiro acesso: o link sai no log, uma vez, e vale 24 horas.
        print(f"[partida] convite de administrador: /convite/{token}", flush=True)
    return criar_app(engine, construir_contexto())
```

Nenhuma variável de módulo é criada. O `--factory` do uvicorn chama a função:

```
web: uvicorn --factory tf2price.painel.app:construir_aplicacao --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*
```

- [ ] **Step 9: Atualizar `.env.example` e `README.md`**

`.env.example` ganha:

```
# Banco. No Railway é injetada automaticamente pelo serviço Postgres.
DATABASE_URL=postgresql://usuario:senha@localhost:5432/tf2price
```

No `README.md`, troque a seção **Uso** por:

````markdown
## Uso

```bash
.venv/Scripts/python -m tf2price.painel.app
```

Abre em `http://127.0.0.1:8000`. Na primeira subida, com o banco vazio, o
terminal imprime um link de convite de administrador válido por 24 horas — é
por ele que a primeira conta nasce. Depois, novas contas saem de `/admin`.

Requer `BPTF_API_KEY` e `DATABASE_URL` no `.env`.
````

Acrescente uma seção nova:

````markdown
## Implantação (Railway)

1. Crie o serviço a partir do repositório e acrescente um serviço **Postgres** —
   o Railway injeta `DATABASE_URL` sozinho.
2. Configure `BPTF_API_KEY` nas variáveis do serviço web.
3. O `Procfile` já sobe com `--proxy-headers`, necessário para o cookie de
   sessão receber `Secure` atrás do proxy.
4. Na primeira subida, procure no log a linha `[partida] convite de
   administrador:` e abra o link.

Uma réplica só: o freio de requisições à Steam e o período de calma vivem na
memória do processo.
````

- [ ] **Step 10: Conferir que a aplicação sobe de verdade**

```bash
.venv/Scripts/python -m tf2price.painel.app
```

Esperado: o log imprime o convite de administrador, a página `/entrar` abre em
`http://127.0.0.1:8000/entrar`, o link do convite cria a conta, e a consulta de
um Unusual funciona como antes. Encerre com Ctrl+C.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "Prepara o painel para o Railway"
```

---

### Task 10: fechar a transação antes de falar com terceiro

Acrescentada depois da revisão do branch inteiro, por decisão do dono do projeto.

**Files:**
- Modify: `tf2price/painel/sessao.py`
- Test: `tests/painel/test_transacao.py` (novo)

**Interfaces:**
- Consumes: `db.agora`, `contas.servico.usuario_da_sessao`.
- Produces: `sessao.usuario_opcional` e `sessao.usuario_obrigatorio` deixam de
  depender de `sessao.conexao` e passam a abrir e fechar conexão própria.
  `sessao.conexao` continua existindo, sem mudança, para as rotas que escrevem.

**O defeito.** `conexao` é dependência com `yield` sobre `engine.begin()`: a
transação abre antes da rota e só fecha depois da resposta pronta. O roteador da
consulta inteiro depende dela, por tabela, via `usuario_obrigatorio`. Então uma
requisição a `/analise` que dispare a primeira carga do índice segura uma conexão
do Postgres em *idle in transaction* enquanto baixa dezenas de MB da backpack.tf,
com `timeout=180.0`, e enquanto o `RateLimiter` dorme. Com o pool padrão do
SQLAlchemy e algumas pessoas clicando logo depois de um deploy, dá para prender
todas as conexões em transações que não estão fazendo nada.

**Por que a ordem dos parâmetros importa.** Depois da mudança, uma rota que
declare `usuario` e `conn` vai abrir duas conexões. O FastAPI resolve as
dependências na ordem em que os parâmetros aparecem, e hoje `usuario` vem antes
de `conn` em todas as rotas — então a conexão da autenticação fecha antes de a
outra abrir, e nunca há duas ao mesmo tempo. Isso não é acidente feliz que se
possa deixar implícito: o dublê de teste usa `StaticPool`, que serve **a mesma**
conexão a todo mundo, então uma sobreposição vira erro de transação aninhada na
hora. Escreva isso como comentário em `conexao`, para quem for reordenar
parâmetros saber o que vai quebrar.

- [ ] **Step 1: Escrever o teste que falha**

**Primeira tentativa, e por que ela não serviu.** A versão anterior deste step
mandava o dublê da página abrir uma conexão nova e executar `SELECT 1`, supondo
que o `StaticPool` levantaria por transação aninhada. Não levanta: o driver
`sqlite3` só abre transação de verdade antes de uma escrita, e tanto a
autenticação quanto o dublê só fazem leitura. O teste passava antes da correção,
ou seja, não provava nada. Em Postgres o problema existe — qualquer SQL já deixa
a conexão *idle in transaction* — mas o dublê de teste não reproduz isso.

**A prova que serve** não depende de semântica de dialeto nenhum: conte as
conexões emprestadas pelo pool, com os eventos `checkout` e `checkin` do
SQLAlchemy, e meça **durante** a chamada ao terceiro. Medido nesta máquina: com
uma transação aberta o contador marca 1, e volta a 0 ao fechar, em todas as
voltas, desde que as conexões não se aninhem — que é o caso aqui.

Crie `tests/painel/test_transacao.py`:

```python
from __future__ import annotations

from sqlalchemy import event

from tests.painel.conftest import NOME, _contexto, _pagina, cliente_logado


def _contar_conexoes(motor) -> dict:
    """Conta conexões emprestadas pelo pool, a qualquer momento.

    Não depende de dialeto: mede a propriedade que interessa ao Postgres —
    conexão emprestada é conexão indisponível para os outros — sem depender
    de o SQLite levantar erro, que ele não levanta em leitura pura.
    """
    estado = {"emprestadas": 0}
    event.listen(motor, "checkout", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] + 1))
    event.listen(motor, "checkin", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] - 1))
    return estado


class _PaginasQueObservamOPool:
    """Dublê que anota quantas conexões estavam emprestadas quando foi chamado.

    É o instante que importa: aqui, na aplicação de verdade, o processo está
    baixando dezenas de MB da backpack.tf com timeout de 180 s.
    """

    def __init__(self, contador, pagina):
        self.contador = contador
        self.pagina = pagina
        self.emprestadas_durante_o_io = None

    def item_page(self, hash_name, usd_to_brl):
        self.emprestadas_durante_o_io = self.contador["emprestadas"]
        return self.pagina


def test_nenhuma_conexao_fica_emprestada_durante_o_io(engine):
    """Uma consulta lenta não pode prender conexão do banco sem usá-la.

    A primeira carga do índice baixa dezenas de MB. Se a transação da
    requisição ficar aberta durante isso, algumas pessoas clicando depois de
    um deploy esgotam o pool do Postgres com conexões ociosas.
    """
    contador = _contar_conexoes(engine)
    ctx = _contexto()
    paginas = _PaginasQueObservamOPool(contador, _pagina())
    ctx.paginas = paginas
    cliente = cliente_logado(engine, ctx)

    resposta = cliente.get("/efeitos", params={"nome": NOME})

    assert resposta.status_code == 200
    assert paginas.emprestadas_durante_o_io == 0


def test_rota_de_escrita_continua_funcionando(engine):
    """A mudança não pode quebrar quem legitimamente escreve no banco."""
    cliente = cliente_logado(engine, _contexto())
    assert cliente.get("/admin").status_code == 200
    assert cliente.post("/admin/convite").status_code == 200
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_transacao.py`
Expected: `test_nenhuma_conexao_fica_emprestada_durante_o_io` FALHA, com
`assert 1 == 0` — a conexão da autenticação está emprestada enquanto a rota
fala com o terceiro. O segundo teste passa desde já; ele existe para provar que
a correção não quebra o caminho de escrita.

**Se o primeiro teste passar aqui, pare e reporte.** Um teste que já passa não
prova correção nenhuma, e foi exatamente assim que a primeira versão deste step
falhou.

- [ ] **Step 3: Abrir conexão curta na autenticação**

Em `tf2price/painel/sessao.py`, `usuario_opcional` deixa de receber
`conn: Connection = Depends(conexao)` e passa a abrir a sua:

```python
def usuario_opcional(request: Request) -> Usuario | None:
    # Conexão curta, aberta e fechada aqui dentro: se a autenticação usasse a
    # conexão da requisição, ela ficaria aberta durante as chamadas à Steam e
    # à backpack.tf, que levam segundos e não tocam o banco.
    token = request.cookies.get(NOME_COOKIE, "")
    if not token:
        return None
    with request.app.state.engine.begin() as conn:
        return servico.usuario_da_sessao(conn, token, db.agora())
```

O curto-circuito em token ausente não é otimização: sem ele, toda requisição sem
cookie abriria conexão para nada.

`usuario_obrigatorio` e `exigir_admin` não mudam — continuam dependendo de
`usuario_opcional`.

Acrescente a `conexao` o comentário sobre ordem de parâmetros descrito acima.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/painel/test_transacao.py`
Expected: PASS nos dois

- [ ] **Step 5: Registrar a diferença de dialeto perto da fixture**

Em `tests/conftest.py`, acrescente ao docstring da fixture `engine` que o
`sqlite3` só abre transação de verdade antes de uma escrita, então o dublê
**não** reproduz o aperto que o Postgres sente em caminho de leitura pura. Quem
escrever o próximo teste de concorrência precisa saber disso antes de presumir
cobertura que não existe.

- [ ] **Step 6: Suíte inteira**

Run: `.venv/Scripts/python -m pytest`
Expected: tudo verde. Preste atenção especial a `tests/painel/test_admin.py` e
`tests/painel/test_convite.py`, que são as rotas que declaram as duas
dependências.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Fecha a transacao antes de falar com terceiro"
```

---

## Cobertura da spec

| Seção da spec | Onde é implementada |
|---|---|
| §4 arquitetura e fronteiras | Tasks 1, 3, 5, 7 |
| §5 modelo de dados | Task 1 (schema), Task 3 (acesso) |
| §6 primeiro acesso pelo log | Task 4 (`convite_de_partida`), Task 9 (impressão) |
| §6 convite, hash do token, uso único, validade | Tasks 4 e 6 |
| §6 Argon2id e senha mínima | Task 2 |
| §6 sessão revogável, cookie, `Secure` por esquema | Tasks 4, 5 e 9 |
| §6 freio de login | Task 4 |
| §6 CSRF por origem | Task 5 (`mesma_origem`) |
| §6 desativar derruba sessão | Task 8 |
| §8 índice da bp.tf sob demanda | Task 9 |
| §8 subida não depende de terceiro (cotação da Steam também sob demanda) | Task 9 |
| §11 rotas de conta, convite e admin | Tasks 5, 6, 8 |
| §12 erros indistinguíveis de convite e de login | Tasks 4 e 6 |
| §13 testes sem rede, em SQLite na memória | Task 1 (fixture) e todas as demais |
| §14 implantação, uma réplica, `--proxy-headers` | Task 9 |
| §16 risco 3 (uma réplica): conexão não fica presa durante I/O | Task 10 |

**Fica para os planos 2 e 3:** retrato compartilhado, acompanhamento, coleta da
arte, tela nova em duas colunas. Nada disso aparece aqui.



