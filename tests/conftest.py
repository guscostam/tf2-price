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

    Cuidado ao provar "conexão presa durante I/O" em cima deste fixture: o
    driver `sqlite3` da stdlib só abre transação de verdade antes de uma
    escrita — leitura pura fica em autocommit de fato, mesmo com
    `engine.begin()` aberto no SQLAlchemy. Duas transações que só leem podem
    conviver na mesma conexão do StaticPool sem erro nenhum, ainda que em
    Postgres a mesma sobreposição já deixasse a conexão em
    *idle in transaction*. Foi assim que a primeira versão do teste da Task 10
    (tests/painel/test_transacao.py) passou sem provar nada: o dublê abria
    uma conexão nova e só fazia SELECT. A prova que funciona conta conexões
    emprestadas pelo pool via os eventos `checkout`/`checkin`, que não
    dependem de dialeto nenhum.
    """
    motor = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.criar_schema(motor)
    return motor
