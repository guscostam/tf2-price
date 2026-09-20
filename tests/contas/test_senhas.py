from __future__ import annotations

import pytest

from tf2price.contas import senhas


def test_hash_confere_com_a_senha_certa():
    guardado = senhas.gerar("uma senha longa")
    assert senhas.confere(guardado, "uma senha longa") is True


def test_hash_recusa_senha_errada():
    guardado = senhas.gerar("uma senha longa")
    assert senhas.confere(guardado, "outra senha longa") is False


def test_duas_senhas_iguais_geram_hashes_diferentes():
    """Argon2 embute sal aleatório; hash igual denunciaria senha igual."""
    assert senhas.gerar("uma senha longa") != senhas.gerar("uma senha longa")


def test_senha_curta_e_recusada():
    with pytest.raises(senhas.SenhaCurta):
        senhas.gerar("curta")


def test_hash_corrompido_nao_levanta_excecao():
    """Um hash inválido no banco não pode derrubar a tela de entrar."""
    assert senhas.confere("isto nao e um hash", "uma senha longa") is False
