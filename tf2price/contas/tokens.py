"""Token aleatório para convite e sessão, e o resumo que vai para o banco.

O banco guarda só o SHA-256: um vazamento não entrega convite nem sessão
utilizáveis. Não há salt aqui de propósito — o token já tem 32 bytes de
entropia, e precisamos achá-lo pela chave primária numa consulta.
"""

from __future__ import annotations

import hashlib
import secrets


def hash_de(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def novo() -> tuple[str, str]:
    """Devolve (token em claro, hash). O claro só existe no link enviado."""
    token = secrets.token_urlsafe(32)
    return token, hash_de(token)
