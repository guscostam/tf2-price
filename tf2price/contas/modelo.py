"""As formas que o repositório devolve. Sem comportamento, sem SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Usuario:
    id: int
    nome: str
    senha_hash: str
    admin: bool
    ativo: bool
    criado_em: datetime


@dataclass(frozen=True)
class Convite:
    hash_do_token: str
    tipo: str
    concede_admin: bool
    alvo: int | None
    criado_por: int | None
    criado_em: datetime
    expira_em: datetime
    usado_em: datetime | None
    usado_por: int | None


@dataclass(frozen=True)
class Sessao:
    hash_do_token: str
    usuario_id: int
    criado_em: datetime
    expira_em: datetime


@dataclass(frozen=True)
class PedidoAcesso:
    id: int
    perfil_steam: str
    contato: str
    observacao: str | None
    criado_em: datetime
    status: str
    resolvido_em: datetime | None
