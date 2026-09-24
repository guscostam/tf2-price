"""Cache persistido do menor anúncio observado para cada item e efeito."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from tf2price import db

ENCONTRADO = "encontrado"
SEM_VENDAS = "sem_vendas_confirmado"
INDISPONIVEL = "indisponivel"


@dataclass(frozen=True)
class RegistroVenda:
    hash_name: str
    efeito: str
    estado: str
    chaves: Decimal | None
    metal: Decimal | None
    buscado_em: datetime | None
    falhou_em: datetime | None
    metal_por_chave: Decimal | None = None


def _identidade_data(hash_name: str, efeito: str, quando: datetime) -> None:
    if not hash_name or not hash_name.strip() or len(hash_name) > 300:
        raise ValueError("hash_name inválido")
    if not efeito or not efeito.strip() or len(efeito) > 120:
        raise ValueError("efeito inválido")
    if not isinstance(quando, datetime) or quando.tzinfo is not None:
        raise ValueError("instante deve ser UTC ingênuo")


def _quantia(valor: Decimal | None) -> str:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor < 0:
        raise ValueError("quantia inválida")
    return str(valor)


def ler_todas(conn: Connection) -> dict[tuple[str, str], RegistroVenda]:
    linhas = conn.execute(select(db.venda_efeito)).all()
    return {
        (l.hash_name, l.efeito): RegistroVenda(
            l.hash_name, l.efeito, l.estado,
            Decimal(l.chaves) if l.chaves is not None else None,
            Decimal(l.metal) if l.metal is not None else None,
            l.buscado_em, l.falhou_em,
            Decimal(l.metal_por_chave) if l.metal_por_chave is not None else None,
        ) for l in linhas
    }


def pares_recentes(conn: Connection, desde: datetime) -> list[tuple[str, str]]:
    """Pares Steam com efeito conhecido, deduplicados antes de qualquer HTTP."""
    if not isinstance(desde, datetime) or desde.tzinfo is not None:
        raise ValueError("instante deve ser UTC ingênuo")
    t = db.listagem_varrida
    linhas = conn.execute(
        select(t.c.hash_name, t.c.efeito)
        .where(t.c.lido_em >= desde, t.c.efeito.is_not(None))
        .distinct().order_by(t.c.hash_name, t.c.efeito)
    )
    return [(l.hash_name, l.efeito) for l in linhas]


def _upsert(conn: Connection, hash_name: str, efeito: str, valores: dict) -> None:
    t = db.venda_efeito
    criterio = (t.c.hash_name == hash_name) & (t.c.efeito == efeito)
    if conn.execute(update(t).where(criterio).values(**valores)).rowcount:
        return
    try:
        with conn.begin_nested():
            conn.execute(insert(t).values(hash_name=hash_name, efeito=efeito, **valores))
    except IntegrityError:
        conn.execute(update(t).where(criterio).values(**valores))


def gravar_sucesso(
    conn: Connection, hash_name: str, efeito: str,
    chaves: Decimal | None, metal: Decimal | None, quando: datetime,
    *, metal_por_chave: Decimal | None = None,
) -> None:
    _identidade_data(hash_name, efeito, quando)
    if (chaves is None) != (metal is None):
        raise ValueError("chaves e metal devem vir juntos")
    if chaves is not None:
        _quantia(chaves)
        _quantia(metal)
        if (
            not isinstance(metal_por_chave, Decimal)
            or not metal_por_chave.is_finite()
            or metal_por_chave <= 0
        ):
            raise ValueError("relação metal/chave inválida")
    estado = SEM_VENDAS if chaves is None else ENCONTRADO
    valores = {
        "estado": estado,
        "chaves": None if chaves is None else _quantia(chaves),
        "metal": None if metal is None else _quantia(metal),
        "metal_por_chave": None if chaves is None else str(metal_por_chave),
        "buscado_em": quando,
        "falhou_em": None,
    }
    _upsert(conn, hash_name, efeito, valores)


def gravar_falha(conn: Connection, hash_name: str, efeito: str, quando: datetime) -> None:
    _identidade_data(hash_name, efeito, quando)
    t = db.venda_efeito
    criterio = (t.c.hash_name == hash_name) & (t.c.efeito == efeito)
    if conn.execute(update(t).where(criterio).values(falhou_em=quando)).rowcount:
        return
    try:
        with conn.begin_nested():
            conn.execute(insert(t).values(
                hash_name=hash_name, efeito=efeito, estado=INDISPONIVEL,
                chaves=None, metal=None, buscado_em=None, falhou_em=quando,
            ))
    except IntegrityError:
        conn.execute(update(t).where(criterio).values(falhou_em=quando))
