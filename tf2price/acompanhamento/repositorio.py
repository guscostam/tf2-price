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
