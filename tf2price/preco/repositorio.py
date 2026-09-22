"""SQL do retrato compartilhado, da cotação da chave na Steam e da PTAX."""

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


# --- cotação da chave ------------------------------------------------------
#
# Uma linha só, id fixo. Ela existe para o processo novo não nascer sem
# cotação: a Steam limita por IP, o Railway sai todo pelo mesmo IP, e medido
# em 21/09/2026 um deploy real levou 429 na primeira requisição e ficou 5
# minutos sem preço de chave nenhum. Guardada, a última cotação conhecida
# atravessa o deploy — velha por alguns minutos, e a tela diz a idade.
LINHA_DA_COTACAO = 1


def _atualizar_cotacao(
    conn: Connection, key_brl_cents: int, usd_to_brl: float, quando: datetime
):
    return conn.execute(
        update(db.cotacao)
        .where(db.cotacao.c.id == LINHA_DA_COTACAO)
        .values(
            key_brl_cents=key_brl_cents, usd_to_brl=usd_to_brl, buscado_em=quando
        )
    )


def guardar_cotacao(
    conn: Connection, key_brl_cents: int, usd_to_brl: float, quando: datetime
) -> None:
    """Grava ou substitui a cotação. Mesmo update-depois-insert de `guardar`,
    e pelo mesmo motivo: `ON CONFLICT` se escreve diferente em cada dialeto, e
    dois processos subindo juntos (um deploy sobrepõe o antigo e o novo)
    disputam esta linha de verdade — o savepoint deixa capturar só o
    conflito de chave e refazer o update em cima do que o outro gravou."""
    resultado = _atualizar_cotacao(conn, key_brl_cents, usd_to_brl, quando)
    if resultado.rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(db.cotacao).values(
                        id=LINHA_DA_COTACAO,
                        key_brl_cents=key_brl_cents,
                        usd_to_brl=usd_to_brl,
                        buscado_em=quando,
                    )
                )
        except IntegrityError:
            _atualizar_cotacao(conn, key_brl_cents, usd_to_brl, quando)


def ler_cotacao(conn: Connection) -> tuple[int, float, datetime] | None:
    """Centavos da chave, taxa dólar->real e quando foi buscada."""
    linha = conn.execute(
        select(
            db.cotacao.c.key_brl_cents,
            db.cotacao.c.usd_to_brl,
            db.cotacao.c.buscado_em,
        ).where(db.cotacao.c.id == LINHA_DA_COTACAO)
    ).first()
    if linha is None:
        return None
    return (int(linha.key_brl_cents), float(linha.usd_to_brl), linha.buscado_em)


# --- PTAX ------------------------------------------------------------------
#
# Mesma linha única e mesmo update-depois-insert da cotação, pelo mesmo
# motivo: o processo novo de cada deploy herda a última PTAX conhecida em vez
# de nascer sem referência.
LINHA_DA_PTAX = 1


def _atualizar_ptax(
    conn: Connection, valor: float, data_cotacao: datetime, quando: datetime
):
    return conn.execute(
        update(db.ptax)
        .where(db.ptax.c.id == LINHA_DA_PTAX)
        .values(valor=valor, data_cotacao=data_cotacao, buscado_em=quando)
    )


def guardar_ptax(
    conn: Connection, valor: float, data_cotacao: datetime, quando: datetime
) -> None:
    resultado = _atualizar_ptax(conn, valor, data_cotacao, quando)
    if resultado.rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(db.ptax).values(
                        id=LINHA_DA_PTAX,
                        valor=valor,
                        data_cotacao=data_cotacao,
                        buscado_em=quando,
                    )
                )
        except IntegrityError:
            _atualizar_ptax(conn, valor, data_cotacao, quando)


def ler_ptax(conn: Connection) -> tuple[float, datetime, datetime] | None:
    """Valor, data da cotação no BC e quando foi buscada."""
    linha = conn.execute(
        select(db.ptax.c.valor, db.ptax.c.data_cotacao, db.ptax.c.buscado_em)
        .where(db.ptax.c.id == LINHA_DA_PTAX)
    ).first()
    if linha is None:
        return None
    return (float(linha.valor), linha.data_cotacao, linha.buscado_em)
