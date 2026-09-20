from __future__ import annotations

from tf2price.contas import tokens


def test_novo_devolve_claro_e_hash_correspondentes():
    claro, resumo = tokens.novo()
    assert tokens.hash_de(claro) == resumo


def test_dois_tokens_nunca_se_repetem():
    assert tokens.novo()[0] != tokens.novo()[0]


def test_hash_tem_64_caracteres_hexadecimais():
    _, resumo = tokens.novo()
    assert len(resumo) == 64
    assert set(resumo) <= set("0123456789abcdef")


def test_token_claro_e_longo_o_bastante():
    """32 bytes aleatórios: adivinhar por força bruta está fora de questão."""
    claro, _ = tokens.novo()
    assert len(claro) >= 40
