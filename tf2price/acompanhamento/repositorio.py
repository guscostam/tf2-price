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


def _trio_ja_existe(
    conn: Connection, *, usuario_id: int, hash_name: str, efeito: str
) -> bool:
    """Verifica se o trio já está na tabela.

    Usada após IntegrityError para distinguir entre violação de chave única
    (duplicata) e violação de chave estrangeira (usuario_id inválido). A
    mensagem do driver não permite essa distinção de forma portável entre
    SQLite e Postgres, então consultamos o banco. Se o trio está lá, o erro
    foi duplicata; se não está, foi outro erro (p.ex. FK) e deve ser relançado.
    """
    resultado = conn.execute(
        select(db.acompanhado).where(
            db.acompanhado.c.usuario_id == usuario_id,
            db.acompanhado.c.hash_name == hash_name,
            db.acompanhado.c.efeito == efeito,
        )
    ).fetchone()
    return resultado is not None


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
        # IntegrityError é amplo: captura tanto duplicata (chave única) quanto
        # violação de chave estrangeira. Verificamos se o trio realmente existe.
        if _trio_ja_existe(conn, usuario_id=usuario_id, hash_name=hash_name, efeito=efeito):
            return None
        # Não era duplicata: relança o erro original (p.ex. FK inválida).
        raise
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
