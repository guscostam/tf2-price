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
