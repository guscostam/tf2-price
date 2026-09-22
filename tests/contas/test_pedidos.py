from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from tf2price import db
from tf2price.contas import pedidos
from tf2price.contas import repositorio as contas_repo
from tf2price.contas import repositorio_pedidos as repo
from tf2price.contas import servico, tokens

ID64 = "76561197960287930"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("https://steamcommunity.com/id/Gusco/", "https://steamcommunity.com/id/gusco"),
        ("steamcommunity.com/id/gus-co_1", "https://steamcommunity.com/id/gus-co_1"),
        ("http://www.steamcommunity.com/id/ab", "https://steamcommunity.com/id/ab"),
        ("HTTPS://STEAMCOMMUNITY.COM/id/Gusco", "https://steamcommunity.com/id/gusco"),
        (f"www.steamcommunity.com/profiles/{ID64}", f"https://steamcommunity.com/profiles/{ID64}"),
        (f"https://steamcommunity.com/profiles/{ID64}/", f"https://steamcommunity.com/profiles/{ID64}"),
        ("  https://steamcommunity.com/id/gusco  ", "https://steamcommunity.com/id/gusco"),
    ],
)
def test_normaliza_perfis_aceitos(entrada, esperado):
    assert pedidos.normalizar_perfil_steam(entrada) == esperado


@pytest.mark.parametrize(
    "entrada",
    [
        "",
        "gusco",
        "https://evil.example/steamcommunity.com/id/gusco",
        "https://steamcommunity.com.evil.example/id/gusco",
        "https://steamcommunity.com/id/g",
        "https://steamcommunity.com/id/" + "a" * 33,
        "https://steamcommunity.com/id/gus.co",
        "https://steamcommunity.com/profiles/123",
        f"https://steamcommunity.com/profiles/{ID64}0",
        # Dígitos de largura total: `\d` do Python aceitaria.
        "https://steamcommunity.com/profiles/７６５６１１９７９６０２８７９３０",
        "https://steamcommunity.com/id/gusco/inventory",
        "https://steamcommunity.com/id/gusco?x=1",
        "https://steamcommunity.com/id/gusco#topo",
        "ftp://steamcommunity.com/id/gusco",
        "https://steamcommunity.com/id/gusco\n",
    ],
)
def test_recusa_o_que_nao_e_perfil(entrada):
    assert pedidos.normalizar_perfil_steam(entrada) is None


def test_pedido_valido_sai_normalizado():
    pedido, erros = pedidos.validar_pedido(
        "steamcommunity.com/id/Gusco", "  gusco#1234 no Discord ", "   "
    )
    assert erros == {}
    assert pedido == pedidos.Pedido(
        perfil_steam="https://steamcommunity.com/id/gusco",
        contato="gusco#1234 no Discord",
        observacao=None,
    )


def test_observacao_preenchida_e_preservada_sem_espacos_nas_bordas():
    pedido, _ = pedidos.validar_pedido(
        "steamcommunity.com/id/gusco", "discord", "  coleciono Team Captains  "
    )
    assert pedido.observacao == "coleciono Team Captains"


def test_erros_por_campo():
    pedido, erros = pedidos.validar_pedido("gusco", "   ", "x" * 1001)
    assert pedido is None
    assert set(erros) == {"perfil_steam", "contato", "observacao"}


def test_limites_de_tamanho_sao_inclusivos():
    pedido, erros = pedidos.validar_pedido(
        "steamcommunity.com/id/gusco", "c" * 200, "o" * 1000
    )
    assert erros == {} and pedido is not None
    _, erros = pedidos.validar_pedido("steamcommunity.com/id/gusco", "c" * 201, "")
    assert set(erros) == {"contato"}


PERFIL = "https://steamcommunity.com/id/gusco"


def _pedido(perfil=PERFIL):
    return pedidos.Pedido(perfil_steam=perfil, contato="discord gusco", observacao=None)


def _admin(conn):
    token = servico.convite_de_partida(conn, db.agora())
    return servico.aceitar_convite(
        conn, token, nome="gusco", senha="uma senha longa", quando=db.agora()
    )


def _status(conn, pedido_id):
    return conn.execute(
        select(db.pedido_acesso.c.status, db.pedido_acesso.c.resolvido_em)
        .where(db.pedido_acesso.c.id == pedido_id)
    ).one()


def test_registrar_grava_um_pendente(engine):
    quando = db.agora()
    with engine.begin() as conn:
        assert pedidos.registrar_pedido(conn, _pedido(), quando) is pedidos.Resultado.GRAVADO
        [linha] = repo.listar_pendentes(conn)
    assert linha.perfil_steam == PERFIL
    assert linha.contato == "discord gusco"
    assert linha.observacao is None
    assert linha.criado_em == quando
    assert linha.status == repo.PENDENTE
    assert linha.resolvido_em is None


def test_mesmo_perfil_pendente_nao_duplica(engine):
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.DUPLICADO
        assert repo.contar_pendentes(conn) == 1


def test_perfil_ja_resolvido_pode_pedir_de_novo(engine):
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.GRAVADO


def test_teto_de_pendentes_fecha_novos_pedidos(engine):
    with engine.begin() as conn:
        for n in range(pedidos.TETO_DE_PENDENTES):
            repo.criar_pedido(
                conn, perfil_steam=f"https://steamcommunity.com/id/p{n}",
                contato="c", observacao=None, quando=db.agora(),
            )
        assert pedidos.registrar_pedido(conn, _pedido(), db.agora()) is pedidos.Resultado.FECHADO
        assert repo.contar_pendentes(conn) == pedidos.TETO_DE_PENDENTES


def test_listar_pendentes_vem_do_mais_antigo_e_ignora_resolvidos(engine):
    base = db.agora()
    with engine.begin() as conn:
        novo = repo.criar_pedido(conn, perfil_steam=PERFIL + "2", contato="c",
                                 observacao=None, quando=base)
        velho = repo.criar_pedido(conn, perfil_steam=PERFIL + "1", contato="c",
                                  observacao=None, quando=base - timedelta(hours=1))
        resolvido = repo.criar_pedido(conn, perfil_steam=PERFIL + "3", contato="c",
                                      observacao=None, quando=base - timedelta(hours=2))
        repo.resolver(conn, resolvido, repo.DESCARTADO, base)
        assert [p.id for p in repo.listar_pendentes(conn)] == [velho, novo]


def test_convidar_pedido_cria_convite_e_marca_o_pedido(engine):
    quando = db.agora()
    with engine.begin() as conn:
        admin = _admin(conn)
        pedidos.registrar_pedido(conn, _pedido(), quando)
        [linha] = repo.listar_pendentes(conn)
        token = pedidos.convidar_pedido(conn, linha.id, admin_id=admin.id, quando=quando)
        convite = contas_repo.convite_por_hash(conn, tokens.hash_de(token))
        assert convite is not None and convite.criado_por == admin.id
        assert tuple(_status(conn, linha.id)) == (repo.CONVIDADO, quando)


def test_descartar_pedido_marca_descartado(engine):
    quando = db.agora()
    with engine.begin() as conn:
        pedidos.registrar_pedido(conn, _pedido(), quando)
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=quando)
        assert tuple(_status(conn, linha.id)) == (repo.DESCARTADO, quando)


def test_pedido_resolvido_ou_inexistente_nao_muda_de_novo(engine):
    with engine.begin() as conn:
        admin = _admin(conn)
        pedidos.registrar_pedido(conn, _pedido(), db.agora())
        [linha] = repo.listar_pendentes(conn)
        pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.convidar_pedido(conn, linha.id, admin_id=admin.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.descartar_pedido(conn, linha.id, quando=db.agora())
        with pytest.raises(pedidos.PedidoJaResolvido):
            pedidos.descartar_pedido(conn, 9999, quando=db.agora())
        assert _status(conn, linha.id).status == repo.DESCARTADO
