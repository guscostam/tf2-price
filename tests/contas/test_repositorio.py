from __future__ import annotations

from datetime import timedelta

from tf2price import db
from tf2price.contas import repositorio as repo

AGORA = db.agora()


def _usuario(conn, nome="gusco", admin=True) -> int:
    return repo.criar_usuario(
        conn, nome=nome, senha_hash="hash", admin=admin, quando=AGORA
    )


def test_criar_e_buscar_usuario_por_nome(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        achado = repo.usuario_por_nome(conn, "gusco")
    assert achado is not None
    assert achado.id == ident
    assert achado.nome == "gusco"
    assert achado.admin is True
    assert achado.ativo is True


def test_booleanos_voltam_como_bool_e_nao_como_inteiro(engine):
    """O SQLite devolve 0 e 1; `if usuario.admin` mentiria em comparação estrita."""
    with engine.begin() as conn:
        _usuario(conn, admin=False)
        achado = repo.usuario_por_nome(conn, "gusco")
    assert achado.admin is False


def test_usuario_inexistente_e_none(engine):
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "ninguem") is None
        assert repo.usuario_por_id(conn, 999) is None


def test_contar_usuarios(engine):
    with engine.begin() as conn:
        assert repo.contar_usuarios(conn) == 0
        _usuario(conn)
        assert repo.contar_usuarios(conn) == 1


def test_desativar_e_trocar_senha(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        repo.definir_ativo(conn, ident, False)
        repo.trocar_senha(conn, ident, "outro hash")
        achado = repo.usuario_por_id(conn, ident)
    assert achado.ativo is False
    assert achado.senha_hash == "outro hash"


def test_convite_guarda_e_devolve_os_campos(engine):
    with engine.begin() as conn:
        dono = _usuario(conn)
        repo.criar_convite(
            conn, hash_do_token="a" * 64, tipo="conta", concede_admin=False,
            alvo=None, criado_por=dono, criado_em=AGORA,
            expira_em=AGORA + timedelta(days=7),
        )
        achado = repo.convite_por_hash(conn, "a" * 64)
    assert achado.tipo == "conta"
    assert achado.concede_admin is False
    assert achado.usado_em is None


def test_consumir_convite_marca_e_registra_quem_usou(engine):
    with engine.begin() as conn:
        dono = _usuario(conn)
        repo.criar_convite(
            conn, hash_do_token="b" * 64, tipo="conta", concede_admin=False,
            alvo=None, criado_por=dono, criado_em=AGORA,
            expira_em=AGORA + timedelta(days=7),
        )
        assert repo.consumir_convite(conn, "b" * 64, usado_em=AGORA) is True
        repo.registrar_quem_usou(conn, "b" * 64, usado_por=dono)
        achado = repo.convite_por_hash(conn, "b" * 64)
    assert achado.usado_em == AGORA
    assert achado.usado_por == dono


def test_consumir_convite_só_dá_certo_uma_vez(engine):
    """A trava do uso único: o segundo UPDATE não encontra linha com
    `usado_em IS NULL` e devolve False. É esta resposta que o serviço usa
    para saber se foi ele quem ficou com o convite."""
    with engine.begin() as conn:
        dono = _usuario(conn)
        repo.criar_convite(
            conn, hash_do_token="d" * 64, tipo="conta", concede_admin=False,
            alvo=None, criado_por=dono, criado_em=AGORA,
            expira_em=AGORA + timedelta(days=7),
        )
        primeiro = repo.consumir_convite(conn, "d" * 64, usado_em=AGORA)
        segundo = repo.consumir_convite(
            conn, "d" * 64, usado_em=AGORA + timedelta(minutes=1)
        )
        achado = repo.convite_por_hash(conn, "d" * 64)
    assert primeiro is True
    assert segundo is False
    # E não sobrescreveu a marca de quem chegou primeiro.
    assert achado.usado_em == AGORA


def test_consumir_convite_inexistente_devolve_falso(engine):
    with engine.begin() as conn:
        assert repo.consumir_convite(conn, "e" * 64, usado_em=AGORA) is False


def test_sessao_criada_e_apagada(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        repo.criar_sessao(
            conn, hash_do_token="c" * 64, usuario_id=ident,
            criado_em=AGORA, expira_em=AGORA + timedelta(days=30),
        )
        assert repo.sessao_por_hash(conn, "c" * 64).usuario_id == ident
        repo.apagar_sessao(conn, "c" * 64)
        assert repo.sessao_por_hash(conn, "c" * 64) is None


def test_apagar_todas_as_sessoes_do_usuario(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        for letra in "de":
            repo.criar_sessao(
                conn, hash_do_token=letra * 64, usuario_id=ident,
                criado_em=AGORA, expira_em=AGORA + timedelta(days=30),
            )
        repo.apagar_sessoes_do_usuario(conn, ident)
        assert repo.sessao_por_hash(conn, "d" * 64) is None
        assert repo.sessao_por_hash(conn, "e" * 64) is None


def test_tentativas_contam_apenas_dentro_da_janela(engine):
    with engine.begin() as conn:
        repo.registrar_tentativa(conn, "gusco", AGORA - timedelta(hours=1))
        repo.registrar_tentativa(conn, "gusco", AGORA)
        repo.registrar_tentativa(conn, "outro", AGORA)
        recentes = repo.contar_tentativas(conn, "gusco", AGORA - timedelta(minutes=15))
    assert recentes == 1


def test_limpar_tentativas_apaga_so_daquele_nome(engine):
    with engine.begin() as conn:
        repo.registrar_tentativa(conn, "gusco", AGORA)
        repo.registrar_tentativa(conn, "outro", AGORA)
        repo.limpar_tentativas(conn, "gusco")
        antigo = AGORA - timedelta(minutes=15)
        assert repo.contar_tentativas(conn, "gusco", antigo) == 0
        assert repo.contar_tentativas(conn, "outro", antigo) == 1


def test_limpar_tentativas_antigas_apaga_so_as_de_fora_da_janela(engine):
    with engine.begin() as conn:
        repo.registrar_tentativa(conn, "gusco", AGORA - timedelta(hours=1))
        repo.registrar_tentativa(conn, "outro", AGORA)
        repo.limpar_tentativas_antigas(conn, AGORA - timedelta(minutes=15))
        antigo = AGORA - timedelta(minutes=15)
        assert repo.contar_tentativas(conn, "gusco", antigo) == 0
        assert repo.contar_tentativas(conn, "outro", antigo) == 1
