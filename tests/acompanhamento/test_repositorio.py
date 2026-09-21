from __future__ import annotations

from tf2price import db
from tf2price.acompanhamento import repositorio as repo
from tf2price.contas import repositorio as contas

AGORA = db.agora()
NOME = "Unusual Team Captain"


def _pessoa(conn, nome):
    return contas.criar_usuario(conn, nome=nome, senha_hash="h", admin=False, quando=AGORA)


def test_adicionar_e_listar(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        lista = repo.listar(conn, eu)
    assert [(a.hash_name, a.efeito) for a in lista] == [(NOME, "Smoking")]


def test_o_mesmo_trio_nao_entra_duas_vezes(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        primeiro = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        repetido = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 1
    assert primeiro is not None
    assert repetido is None


def test_o_mesmo_chapeu_com_outro_efeito_e_outro_item(engine):
    """Mesmo chapéu, efeito diferente, valores em ordens de grandeza distintas."""
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Terror-Watt", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 2


def test_cada_pessoa_ve_so_a_propria_lista(engine):
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        outra = _pessoa(conn, "outra")
        repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert len(repo.listar(conn, eu)) == 1
        assert repo.listar(conn, outra) == []


def test_ninguem_remove_o_item_de_outra_pessoa(engine):
    """O isolamento vale na escrita, não só na leitura."""
    with engine.begin() as conn:
        eu = _pessoa(conn, "eu")
        outra = _pessoa(conn, "outra")
        meu = repo.adicionar(conn, usuario_id=eu, hash_name=NOME, efeito="Smoking", quando=AGORA)
        assert repo.remover(conn, outra, meu) is False
        assert len(repo.listar(conn, eu)) == 1
        assert repo.remover(conn, eu, meu) is True
        assert repo.listar(conn, eu) == []
