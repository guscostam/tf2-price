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
    Float,
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

cotacao = Table(
    "cotacao",
    METADATA,
    # Uma linha só, sempre com id 1: a cotação é global — nem por item nem
    # por pessoa. A chave fixa é o que garante isso no banco, em vez de na
    # confiança de quem escreve.
    Column("id", Integer, primary_key=True),
    # Em centavos, inteiro, como `Brl` guarda por dentro: dinheiro não entra
    # em float. A taxa dólar->real é razão, não dinheiro, e por isso é float.
    Column("key_brl_cents", Integer, nullable=False),
    Column("usd_to_brl", Float, nullable=False),
    Column("buscado_em", DateTime, nullable=False),
)

ptax = Table(
    "ptax",
    METADATA,
    # Uma linha só (id 1), como a cotação. Tabela própria, e não colunas em
    # `cotacao`, porque `create_all` não acrescenta colunas a uma tabela que
    # já existe e o projeto não tem migração.
    Column("id", Integer, primary_key=True),
    # Reais por dólar: razão, não dinheiro, por isso float.
    Column("valor", Float, nullable=False),
    # Quando o BC fechou a cotação: é esta a data que a tela mostra.
    Column("data_cotacao", DateTime, nullable=False),
    # Quando nós a buscamos: é esta que decide a validade de 1 hora.
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

pedido_acesso = Table(
    "pedido_acesso",
    METADATA,
    Column("id", Integer, primary_key=True),
    # Forma canônica (contas/pedidos.py): é ela que o admin abre como link.
    Column("perfil_steam", String(120), nullable=False),
    Column("contato", String(200), nullable=False),
    Column("observacao", String(1000), nullable=True),
    Column("criado_em", DateTime, nullable=False),
    Column("status", String(20), nullable=False),  # pendente, convidado, descartado
    Column("resolvido_em", DateTime, nullable=True),
)

varredura_config = Table(
    "varredura_config",
    METADATA,
    # Uma linha só, id 1, como a cotação: a configuração é global.
    Column("id", Integer, primary_key=True),
    Column("ligada", Boolean, nullable=False),
    Column("intervalo_min", Integer, nullable=False),
    Column("idade_max_funda_h", Integer, nullable=False),
    Column("alterado_em", DateTime, nullable=False),
)

varredura_nome = Table(
    "varredura_nome",
    METADATA,
    Column("hash_name", String(300), primary_key=True),
    # A assinatura é o preço CRU da busca, em centavos de dólar. Em reais ela
    # dependeria da taxa derivada da chave, que muda entre processos, e cada
    # deploy faria o mercado inteiro parecer "mudado".
    Column("preco_usd_cents", Integer, nullable=False),
    Column("n_listagens", Integer, nullable=False),
    # Quantas listagens a última leitura funda gravou. A diferença para
    # `n_listagens` é o "+N more on Steam" da tela.
    Column("n_guardadas", Integer, nullable=False, default=0),
    Column("visto_em", DateTime, nullable=False),
    Column("funda_em", DateTime, nullable=True),
)

listagem_varrida = Table(
    "listagem_varrida",
    METADATA,
    Column("listing_id", String(40), primary_key=True),
    Column("hash_name", String(300), nullable=False, index=True),
    # Nulo quando a Steam não informou o efeito: essa linha não tem preço.
    Column("efeito", String(120), nullable=True),
    Column("preco_cents", Integer, nullable=False),
    Column("icone", String(500), nullable=True),
    Column("lido_em", DateTime, nullable=False),
)

varredura_rodada = Table(
    "varredura_rodada",
    METADATA,
    Column("id", Integer, primary_key=True),
    Column("inicio", DateTime, nullable=False),
    Column("fim", DateTime, nullable=True),
    Column("nomes_lidos", Integer, nullable=False, default=0),
    Column("fundas_feitas", Integer, nullable=False, default=0),
    Column("falhas", Integer, nullable=False, default=0),
    # ok, 429, erro, interrompida; nulo enquanto roda.
    Column("motivo_parada", String(20), nullable=True),
)

varredura_andamento = Table(
    "varredura_andamento",
    METADATA,
    # Uma linha só (id 1): o andamento da rodada em curso, que o admin lê a
    # cada 5 s. Tabela própria, e não colunas em `varredura_rodada`, porque
    # `create_all` não acrescenta colunas a uma tabela que já existe.
    Column("id", Integer, primary_key=True),
    Column("rodada_id", Integer, nullable=False),
    Column("fase", String(20), nullable=False),
    Column("paginas_busca_lidas", Integer, nullable=False),
    Column("paginas_busca_total", Integer, nullable=True),
    Column("itens_lidos", Integer, nullable=False),
    Column("itens_total", Integer, nullable=True),
    # Não nulo = pausada depois de um 429, até este instante (UTC).
    Column("pausado_ate", DateTime, nullable=True),
    Column("pausas_seguidas", Integer, nullable=False),
    Column("atualizado_em", DateTime, nullable=False),
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
