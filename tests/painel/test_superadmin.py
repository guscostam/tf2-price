from __future__ import annotations

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.painel.app import aviso_do_superadmin, preparar_superadmin


def _usuario(engine, nome, admin=True, ativo=True):
    with engine.begin() as conn:
        ident = repo.criar_usuario(
            conn, nome=nome, senha_hash="hash", admin=admin, quando=db.agora()
        )
        if not ativo:
            repo.definir_ativo(conn, ident, False)


def test_sem_variavel_avisa(engine):
    aviso = aviso_do_superadmin(engine, None)
    assert aviso.startswith("[superadmin] SUPERADMIN ausente")


def test_nome_que_nao_existe_avisa(engine):
    aviso = aviso_do_superadmin(engine, "gusco")
    assert aviso.startswith('[superadmin] "gusco" não é um admin ativo')


def test_nome_de_membro_avisa(engine):
    _usuario(engine, "gusco", admin=False)
    assert aviso_do_superadmin(engine, "gusco") is not None


def test_nome_de_admin_desativado_avisa(engine):
    _usuario(engine, "gusco", ativo=False)
    assert aviso_do_superadmin(engine, "gusco") is not None


def test_admin_ativo_nao_avisa(engine):
    _usuario(engine, "gusco")
    assert aviso_do_superadmin(engine, "gusco") is None


def test_preparar_le_a_variavel_sem_espacos(engine, monkeypatch, capsys):
    _usuario(engine, "gusco")
    monkeypatch.setenv("SUPERADMIN", "  gusco  ")
    assert preparar_superadmin(engine) == "gusco"
    assert "[superadmin]" not in capsys.readouterr().out


def test_preparar_sem_variavel_devolve_none_e_avisa(engine, monkeypatch, capsys):
    monkeypatch.delenv("SUPERADMIN", raising=False)
    assert preparar_superadmin(engine) is None
    assert "[superadmin] SUPERADMIN ausente" in capsys.readouterr().out


def test_preparar_com_variavel_vazia_devolve_none(engine, monkeypatch):
    monkeypatch.setenv("SUPERADMIN", "   ")
    assert preparar_superadmin(engine) is None
