from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

SENHA = "uma senha longa"


def _entra(engine, nome, admin):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id if dono else None, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente


@pytest.fixture
def admin(engine):
    return _entra(engine, "gusco", admin=True)


def test_admin_lista_os_usuarios(admin, engine):
    _entra(engine, "amiga", admin=False)
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "gusco" in r.text and "amiga" in r.text


def test_nao_admin_leva_403(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    resposta = comum.get("/admin")
    assert resposta.status_code == 403
    assert resposta.text == "This page is restricted to administrators."


def test_sem_sessao_nao_chega_no_admin(engine):
    cliente = TestClient(criar_app(engine), follow_redirects=False)
    assert cliente.get("/admin").status_code == 303


def test_gerar_convite_mostra_o_link_uma_vez(admin):
    r = admin.post("/admin/convite")
    assert r.status_code == 200
    assert "/convite/" in r.text
    assert "The link is shown once. Copy it now." in r.text
    assert "/convite/" not in admin.get("/admin").text


def test_link_gerado_realmente_cria_conta(admin, engine):
    import re

    texto = admin.post("/admin/convite").text
    token = re.search(r"/convite/([A-Za-z0-9_\-]+)", texto).group(1)
    outro = TestClient(criar_app(engine), follow_redirects=False)
    r = outro.post(f"/convite/{token}", data={"nome": "amiga", "senha": SENHA})
    assert r.status_code == 303
    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "amiga") is not None


def test_redefinir_gera_link_para_aquele_usuario(admin, engine):
    _entra(engine, "amiga", admin=False)
    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    r = admin.post(f"/admin/redefinir/{alvo}")
    assert "/convite/" in r.text


def test_desativar_derruba_a_sessao_da_pessoa(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    assert comum.get("/admin").status_code == 403  # sessão viva
    token = comum.cookies.get(NOME_COOKIE)

    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    admin.post(f"/admin/ativo/{alvo}", data={"ativo": "0"})

    comum.follow_redirects = False
    assert comum.get("/admin").status_code == 303  # sessão morta

    # A checagem de conta ativa já bastaria para barrar /admin, mesmo com a
    # linha da sessão viva no banco. O que prova que a sessão foi de fato
    # apagada — e não apenas mascarada pela checagem — é consultar o banco
    # diretamente.
    with engine.begin() as conn:
        assert repo.sessao_por_hash(conn, tokens.hash_de(token)) is None


def test_admin_nao_consegue_se_desativar(admin, engine):
    with engine.begin() as conn:
        eu = repo.usuario_por_nome(conn, "gusco")
    resposta = admin.post(f"/admin/ativo/{eu.id}", data={"ativo": "0"})
    assert "You cannot disable your own account." in resposta.text

    with engine.begin() as conn:
        assert repo.usuario_por_nome(conn, "gusco").ativo is True
    assert admin.get("/admin").status_code == 200


def test_comum_leva_403_nos_tres_posts_de_admin(admin, engine):
    """As três rotas de escrita dependem de `exigir_admin`; a garantia é
    estrutural (Depends), mas é a superfície de escrita e merece teste
    próprio, não só o GET."""
    comum = _entra(engine, "amiga", admin=False)
    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id

    assert comum.post("/admin/convite").status_code == 403
    assert comum.post(f"/admin/redefinir/{alvo}").status_code == 403
    assert comum.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 403


def test_redefinir_para_usuario_inexistente_da_404(admin):
    resposta = admin.post("/admin/redefinir/999999")
    assert resposta.status_code == 404
    assert resposta.text == "User not found."


def test_ativo_para_usuario_inexistente_da_404(admin):
    resposta = admin.post("/admin/ativo/999999", data={"ativo": "0"})
    assert resposta.status_code == 404
    assert resposta.text == "User not found."


def test_admin_copy_and_disable_confirmation(admin, engine):
    _entra(engine, "amiga", admin=False)
    texto = admin.get("/admin").text
    for label in ("Administration", "Generate invitation", "People", "Reset password", "Disable"):
        assert label in texto
    confirmation = 'data-confirm="Disable this account and invalidate its sessions?"'
    assert texto.count(confirmation) == 1
    with engine.begin() as conn:
        alvo = repo.usuario_por_nome(conn, "amiga").id
    texto = admin.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).text
    assert "Reactivate" in texto
    assert confirmation not in texto
    assert 'name="ativo" value="1"' in texto


def test_admin_nao_ve_botao_de_desativar_a_propria_linha(admin, engine):
    _entra(engine, "amiga", admin=False)
    texto = admin.get("/admin").text
    with engine.begin() as conn:
        eu = repo.usuario_por_nome(conn, "gusco")
        outra = repo.usuario_por_nome(conn, "amiga")
    assert f'/admin/ativo/{eu.id}' not in texto
    assert f'/admin/ativo/{outra.id}' in texto
