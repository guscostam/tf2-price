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
