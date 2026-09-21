from __future__ import annotations

from datetime import timedelta

from tf2price import db
from tf2price.preco import repositorio as repo

AGORA = db.agora()


def test_guardar_e_ler(engine):
    with engine.begin() as conn:
        repo.guardar(conn, "Unusual Team Captain", '{"a": 1}', AGORA)
        lido = repo.ler(conn, "Unusual Team Captain")
    assert lido is not None
    dados, quando = lido
    assert dados == '{"a": 1}'
    assert quando == AGORA


def test_ler_item_nunca_visto_e_none(engine):
    with engine.begin() as conn:
        assert repo.ler(conn, "Item Que Ninguem Abriu") is None


def test_guardar_de_novo_substitui_e_atualiza_a_hora(engine):
    """O retrato é um só por item: o segundo sobrescreve, não duplica."""
    depois = AGORA + timedelta(minutes=20)
    with engine.begin() as conn:
        repo.guardar(conn, "X", '{"v": 1}', AGORA)
        repo.guardar(conn, "X", '{"v": 2}', depois)
        dados, quando = repo.ler(conn, "X")
    assert dados == '{"v": 2}'
    assert quando == depois


def test_nomes_com_apostrofo_e_acento(engine):
    """`Strange Unusual Villain's Veil` existe e já mordeu este projeto."""
    nome = "Strange Unusual Villain's Veil"
    with engine.begin() as conn:
        repo.guardar(conn, nome, "{}", AGORA)
        assert repo.ler(conn, nome) is not None
