"""Hash de senha com Argon2id.

O dono do painel nunca vê senha de ninguém, e o banco nunca guarda senha —
só o hash, com sal embutido pela própria biblioteca.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

SENHA_MINIMA = 10

_HASHER = PasswordHasher()


class SenhaCurta(ValueError):
    """Senha abaixo do mínimo."""


def gerar(senha: str) -> str:
    if len(senha) < SENHA_MINIMA:
        raise SenhaCurta(f"a senha precisa de pelo menos {SENHA_MINIMA} caracteres")
    return _HASHER.hash(senha)


def confere(hash_guardado: str, senha: str) -> bool:
    # verify() devolve True ou levanta. Um hash corrompido no banco não pode
    # derrubar a tela de entrar, então as três exceções viram False.
    try:
        return _HASHER.verify(hash_guardado, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Hash de referência calculado uma vez, no import, sobre uma senha fixa
# qualquer — nenhuma conta real usa esta senha, e não precisa: ele existe só
# para ter algo a comparar quando o nome não existe.
_HASH_DE_REFERENCIA = _HASHER.hash("senha de referencia do freio de tempo")


def confere_em_falso(senha: str) -> None:
    """Paga o custo do Argon2 sem validar nada.

    Usado quando o nome não existe: sem isto, `entrar` voltaria em ~1ms
    contra os ~50-100ms de uma senha errada contra um nome real, e esse
    relógio denunciaria quais nomes existem — o mesmo vazamento que a
    mensagem de erro única já foi escrita para evitar.
    """
    try:
        _HASHER.verify(_HASH_DE_REFERENCIA, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
