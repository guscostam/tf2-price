from __future__ import annotations

import pytest

from tf2price.contas import pedidos

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
