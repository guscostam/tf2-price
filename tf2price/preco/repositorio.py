"""SQL do retrato compartilhado."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from tf2price import db


def _atualizar(conn: Connection, hash_name: str, dados: str, quando: datetime):
    return conn.execute(
        update(db.retrato)
        .where(db.retrato.c.hash_name == hash_name)
        .values(json=dados, buscado_em=quando)
    )


def guardar(conn: Connection, hash_name: str, dados: str, quando: datetime) -> None:
    """Grava ou substitui o retrato daquele item.

    Tenta atualizar primeiro e só insere se não havia linha: `ON CONFLICT` e
    `MERGE` se escrevem diferente em cada dialeto, e este projeto roda em
    Postgres e em SQLite.

    O update-depois-insert não é atômico, e as rotas são síncronas: o uvicorn
    as roda em threads de verdade. Duas pessoas pedindo o MESMO chapéu nunca
    visto buscam a Steam em paralelo (segundos!), as duas veem zero linhas no
    update, e a segunda bate na chave primária. `begin_nested` (um savepoint)
    em volta do insert, no mesmo padrão de `acompanhamento/repositorio.py`,
    deixa capturar só esse conflito específico: se ele acontecer, a outra
    transação já gravou o retrato, então refazemos o update em cima dele.
    """
    resultado = _atualizar(conn, hash_name, dados, quando)
    if resultado.rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(db.retrato).values(hash_name=hash_name, json=dados, buscado_em=quando)
                )
        except IntegrityError:
            _atualizar(conn, hash_name, dados, quando)


def ler(conn: Connection, hash_name: str) -> tuple[str, datetime] | None:
    linha = conn.execute(
        select(db.retrato.c.json, db.retrato.c.buscado_em).where(
            db.retrato.c.hash_name == hash_name
        )
    ).first()
    return (linha.json, linha.buscado_em) if linha else None
