"""Schema, conexão e relógio do painel.

SQLAlchemy Core, não ORM: o SQL continua explícito e confinado aos
repositórios, e o mesmo código roda em Postgres na produção e em SQLite na
memória nos testes — que precisam continuar rodando em menos de um segundo,
sem banco de pé.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine

METADATA = MetaData()

# Datas: UTC ingênuo dos dois lados.
#
# O Postgres guardaria o fuso e o SQLite não guarda; comparar os dois tipos
# levanta exceção em um dialeto e passa no outro, que é a classe de bug que
# testar em SQLite e rodar em Postgres pode esconder. Gravando sempre UTC sem
# fuso, os dois se comportam igual.
def agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


usuario = Table(
    "usuario",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("nome", String(60), nullable=False, unique=True),
    Column("senha_hash", String(255), nullable=False),
    Column("admin", Boolean, nullable=False, default=False),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("criado_em", DateTime, nullable=False),
)

convite = Table(
    "convite",
    METADATA,
    # Só o hash. Banco vazado não vira convite válido.
    Column("hash_do_token", String(64), primary_key=True),
    Column("tipo", String(20), nullable=False),  # "conta" ou "redefinicao"
    Column("concede_admin", Boolean, nullable=False, default=False),
    # Em "redefinicao", de quem é a senha que este link troca.
    Column("alvo", Integer, ForeignKey("usuario.id"), nullable=True),
    Column("criado_por", Integer, ForeignKey("usuario.id"), nullable=True),
    Column("criado_em", DateTime, nullable=False),
    Column("expira_em", DateTime, nullable=False),
    Column("usado_em", DateTime, nullable=True),
    Column("usado_por", Integer, ForeignKey("usuario.id"), nullable=True),
)

sessao = Table(
    "sessao",
    METADATA,
    Column("hash_do_token", String(64), primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuario.id"), nullable=False),
    Column("criado_em", DateTime, nullable=False),
    Column("expira_em", DateTime, nullable=False),
)

tentativa = Table(
    "tentativa",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("nome", String(60), nullable=False),
    Column("quando", DateTime, nullable=False),
)

retrato = Table(
    "retrato",
    METADATA,
    # Um retrato por item, compartilhado por todos: duas pessoas olhando o
    # mesmo chapéu custam uma requisição à Steam, não duas.
    Column("hash_name", String(300), primary_key=True),
    Column("json", Text, nullable=False),
    Column("buscado_em", DateTime, nullable=False),
)

acompanhado = Table(
    "acompanhado",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("usuario_id", Integer, ForeignKey("usuario.id"), nullable=False),
    Column("hash_name", String(300), nullable=False),
    # O efeito faz parte da chave: o mesmo chapéu com outro efeito é outro
    # item econômico, e vale outra coisa.
    Column("efeito", String(120), nullable=False),
    Column("criado_em", DateTime, nullable=False),
    UniqueConstraint("usuario_id", "hash_name", "efeito", name="acompanhado_unico"),
)


def url_do_ambiente() -> str:
    """URL do banco, com o dialeto normalizado.

    O Railway entrega `postgres://`, herança do Heroku, e o SQLAlchemy 2 não
    reconhece esse prefixo. Normalizar aqui evita descobrir isso na primeira
    subida em produção.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL não configurada")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def criar_engine(url: str | None = None) -> Engine:
    return create_engine(url or url_do_ambiente(), future=True, pool_pre_ping=True)


def criar_schema(engine: Engine) -> None:
    METADATA.create_all(engine)
