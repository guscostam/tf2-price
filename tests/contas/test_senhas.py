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


def test_senha_no_minimo_exato_e_aceita():
    """A regra é `<`; exatamente `SENHA_MINIMA` caracteres tem que passar."""
    senhas.gerar("a" * senhas.SENHA_MINIMA)


def test_hash_corrompido_nao_levanta_excecao():
    """Um hash inválido no banco não pode derrubar a tela de entrar."""
    assert senhas.confere("isto nao e um hash", "uma senha longa") is False


def test_confere_em_falso_nao_levanta_para_nenhuma_entrada():
    """Só existe para gastar tempo de Argon2; não afirma nada sobre a senha."""
    assert senhas.confere_em_falso("qualquer coisa") is None
    assert senhas.confere_em_falso("") is None
