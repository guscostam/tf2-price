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
