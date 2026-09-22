from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import repositorio_pedidos as repo_pedidos
from tf2price.contas import servico, tokens
from tf2price.painel.app import criar_app
from tf2price.painel.sessao import NOME_COOKIE

SENHA = "uma senha longa"


def _entra(engine, nome, admin, superadmin=None):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id if dono else None, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine, superadmin=superadmin))
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


def _pedido(engine, perfil="https://steamcommunity.com/id/amiga", contato="amiga no Discord",
            observacao=None):
    with engine.begin() as conn:
        return repo_pedidos.criar_pedido(
            conn, perfil_steam=perfil, contato=contato, observacao=observacao, quando=db.agora()
        )


def _status_do_pedido(engine, pedido_id):
    with engine.begin() as conn:
        return conn.execute(
            select(db.pedido_acesso.c.status).where(db.pedido_acesso.c.id == pedido_id)
        ).scalar_one()


def test_admin_lista_pedidos_pendentes(admin, engine):
    _pedido(engine, observacao="coleciono Team Captains")
    texto = admin.get("/admin").text
    assert "Access requests" in texto
    assert ('<a href="https://steamcommunity.com/id/amiga" target="_blank" '
            'rel="noopener noreferrer">') in texto
    assert "amiga no Discord" in texto
    assert "coleciono Team Captains" in texto


def test_admin_sem_pedidos_diz_isso(admin):
    assert "No pending requests." in admin.get("/admin").text


def test_texto_do_pedido_e_escapado(admin, engine):
    _pedido(engine, contato="<script>alert(1)</script>")
    texto = admin.get("/admin").text
    assert "<script>alert(1)</script>" not in texto
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in texto


def test_convidar_pedido_mostra_link_valido_e_tira_da_lista(admin, engine):
    pedido_id = _pedido(engine)
    r = admin.post(f"/admin/pedido/{pedido_id}/convidar")
    assert r.status_code == 200
    token = re.search(r"/convite/([A-Za-z0-9_\-]+)", r.text).group(1)
    with engine.begin() as conn:
        assert repo.convite_por_hash(conn, tokens.hash_de(token)) is not None
    assert _status_do_pedido(engine, pedido_id) == "convidado"
    assert "https://steamcommunity.com/id/amiga" not in admin.get("/admin").text


def test_descartar_pedido(admin, engine):
    pedido_id = _pedido(engine)
    r = admin.post(f"/admin/pedido/{pedido_id}/descartar")
    assert r.status_code == 200
    assert "/convite/" not in r.text
    assert _status_do_pedido(engine, pedido_id) == "descartado"


def test_pedido_ja_resolvido_nao_gera_convite(admin, engine):
    pedido_id = _pedido(engine)
    admin.post(f"/admin/pedido/{pedido_id}/descartar")
    r = admin.post(f"/admin/pedido/{pedido_id}/convidar")
    assert "This request was already resolved." in r.text
    assert "/convite/" not in r.text
    assert _status_do_pedido(engine, pedido_id) == "descartado"


def test_acoes_de_pedido_exigem_mesma_origem(admin, engine):
    pedido_id = _pedido(engine)
    for acao in ("convidar", "descartar"):
        r = admin.post(f"/admin/pedido/{pedido_id}/{acao}",
                       headers={"Origin": "https://site-de-outro.example"})
        assert r.status_code == 403
    assert _status_do_pedido(engine, pedido_id) == "pendente"


def test_nao_admin_nao_resolve_pedido(admin, engine):
    comum = _entra(engine, "amiga", admin=False)
    pedido_id = _pedido(engine)
    assert comum.post(f"/admin/pedido/{pedido_id}/convidar").status_code == 403
    assert _status_do_pedido(engine, pedido_id) == "pendente"


# --- administradores e superadmin -----------------------------------------


@pytest.fixture
def dono(engine):
    """"gusco" é o superadmin: a primeira conta, e o nome na variável."""
    return _entra(engine, "gusco", admin=True, superadmin="gusco")


def _id(engine, nome):
    with engine.begin() as conn:
        return repo.usuario_por_nome(conn, nome).id


def _usuario(engine, nome):
    with engine.begin() as conn:
        return repo.usuario_por_nome(conn, nome)


def _colega(engine, nome="colega", superadmin="gusco"):
    """Admin comum: nasce membro e é promovido direto no banco."""
    cliente = _entra(engine, nome, admin=False, superadmin=superadmin)
    with engine.begin() as conn:
        repo.definir_admin(conn, repo.usuario_por_nome(conn, nome).id, True)
    return cliente


def test_superadmin_promove_e_rebaixa(dono, engine):
    _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")

    r = dono.post(f"/admin/papel/{alvo}", data={"admin": "1"})
    assert r.status_code == 200
    assert _usuario(engine, "amiga").admin is True
    assert "Remove admin" in r.text

    r = dono.post(f"/admin/papel/{alvo}", data={"admin": "0"})
    assert r.status_code == 200
    assert _usuario(engine, "amiga").admin is False
    assert "Make admin" in r.text


def test_promover_e_rebaixar_valem_na_requisicao_seguinte(dono, engine):
    """Sem derrubar a sessão: `admin` é relido do banco a cada requisição."""
    amiga = _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")
    assert amiga.get("/admin").status_code == 403

    dono.post(f"/admin/papel/{alvo}", data={"admin": "1"})
    assert amiga.get("/admin").status_code == 200

    dono.post(f"/admin/papel/{alvo}", data={"admin": "0"})
    assert amiga.get("/admin").status_code == 403


def test_admin_comum_nao_muda_papel_de_ninguem(dono, engine):
    colega = _colega(engine)
    _entra(engine, "amiga", admin=False)

    r = colega.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert r.text == "Not allowed."
    assert _usuario(engine, "amiga").admin is False

    r = colega.post(f"/admin/papel/{_id(engine, 'gusco')}", data={"admin": "0"})
    assert r.status_code == 403
    assert _usuario(engine, "gusco").admin is True


def test_admin_comum_nao_reseta_nem_desativa_admin(dono, engine):
    colega = _colega(engine)
    _colega(engine, nome="outro")

    for nome in ("gusco", "outro"):
        alvo = _id(engine, nome)
        r = colega.post(f"/admin/redefinir/{alvo}")
        assert r.status_code == 403
        assert r.text == "Not allowed."
        r = colega.post(f"/admin/ativo/{alvo}", data={"ativo": "0"})
        assert r.status_code == 403
        assert _usuario(engine, nome).ativo is True

    with engine.begin() as conn:
        resets = conn.execute(
            select(db.convite).where(db.convite.c.tipo == servico.TIPO_REDEFINICAO)
        ).all()
    assert resets == []


def test_admin_comum_continua_gerindo_membros(dono, engine):
    colega = _colega(engine)
    _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")

    assert "/convite/" in colega.post(f"/admin/redefinir/{alvo}").text
    assert colega.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 200
    assert _usuario(engine, "amiga").ativo is False


def test_admin_comum_reativa_membro(dono, engine):
    colega = _colega(engine)
    _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")

    assert colega.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 200
    assert _usuario(engine, "amiga").ativo is False

    r = colega.post(f"/admin/ativo/{alvo}", data={"ativo": "1"})
    assert r.status_code == 200
    assert _usuario(engine, "amiga").ativo is True


def test_superadmin_reseta_e_desativa_admin(dono, engine):
    _colega(engine)
    alvo = _id(engine, "colega")

    assert "/convite/" in dono.post(f"/admin/redefinir/{alvo}").text
    assert dono.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 200
    assert _usuario(engine, "colega").ativo is False


def test_superadmin_nao_se_rebaixa_nem_se_desativa(dono, engine):
    eu = _id(engine, "gusco")

    r = dono.post(f"/admin/papel/{eu}", data={"admin": "0"})
    assert r.status_code == 403
    r = dono.post(f"/admin/ativo/{eu}", data={"ativo": "0"})
    assert "You cannot disable your own account." in r.text

    gusco = _usuario(engine, "gusco")
    assert gusco.admin is True and gusco.ativo is True


def test_sem_superadmin_ninguem_muda_papel_nem_mexe_em_admin(admin, engine):
    """`admin` é o fixture antigo: "gusco" sem a variável, um admin comum."""
    _entra(engine, "amiga", admin=False)
    _colega(engine, superadmin=None)

    r = admin.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False

    assert admin.post(f"/admin/redefinir/{_id(engine, 'colega')}").status_code == 403
    assert "/admin/papel/" not in admin.get("/admin").text


def test_papel_exige_mesma_origem(dono, engine):
    _entra(engine, "amiga", admin=False)
    r = dono.post(
        f"/admin/papel/{_id(engine, 'amiga')}",
        data={"admin": "1"},
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False


def test_papel_para_usuario_inexistente_da_404(dono):
    r = dono.post("/admin/papel/999999", data={"admin": "1"})
    assert r.status_code == 404
    assert r.text == "User not found."


def test_membro_leva_403_no_papel(dono, engine):
    amiga = _entra(engine, "amiga", admin=False, superadmin="gusco")
    r = amiga.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False


def _acao(caminho, ident):
    return f'action="/admin/{caminho}/{ident}"'


def test_botoes_vistos_pelo_superadmin(dono, engine):
    _colega(engine)
    _entra(engine, "amiga", admin=False)
    texto = dono.get("/admin").text
    eu, colega, amiga = (_id(engine, n) for n in ("gusco", "colega", "amiga"))

    for outro in (colega, amiga):
        for caminho in ("redefinir", "ativo", "papel"):
            assert _acao(caminho, outro) in texto
    assert _acao("redefinir", eu) in texto
    assert _acao("ativo", eu) not in texto
    assert _acao("papel", eu) not in texto

    assert "Owner · Active" in texto
    assert texto.count('data-confirm="Grant administrator access to this person?"') == 1
    assert texto.count('data-confirm="Remove administrator access from this person?"') == 1


def test_botoes_vistos_pelo_admin_comum(dono, engine):
    colega = _colega(engine)
    _colega(engine, nome="outro")
    _entra(engine, "amiga", admin=False)
    texto = colega.get("/admin").text
    eu, gusco, outro, amiga = (
        _id(engine, n) for n in ("colega", "gusco", "outro", "amiga")
    )

    assert "/admin/papel/" not in texto
    for admin_alheio in (gusco, outro):
        assert _acao("redefinir", admin_alheio) not in texto
        assert _acao("ativo", admin_alheio) not in texto
    assert _acao("redefinir", amiga) in texto
    assert _acao("ativo", amiga) in texto
    assert _acao("redefinir", eu) in texto
    assert _acao("ativo", eu) not in texto
    assert "Owner · Active" in texto
