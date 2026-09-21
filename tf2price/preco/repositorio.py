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
