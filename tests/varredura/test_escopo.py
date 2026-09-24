from __future__ import annotations

import pytest

from tf2price.varredura.escopo import (
    COSMETICOS_DEFINDEX_PATH,
    carregar_cosmeticos,
    defindices_de_cosmeticos,
    e_cosmetico_unusual,
    nomes_de_cosmeticos,
)

COSMETICOS = frozenset({"Team Captain", "Brigade Helm", "Hot Case", "Bonk Boy"})


@pytest.mark.parametrize("nome", [
    "Unusual Team Captain",
    "Unusual Brigade Helm",
    "Unusual Hot Case",  # misc, não chapéu: entra
])
def test_aceita_cosmetico_unusual(nome):
    assert e_cosmetico_unusual(nome, COSMETICOS)


@pytest.mark.parametrize("nome", [
    "Unusual Taunt: Chairholder",                        # taunt
    "Strange Unusual Bonk Boy",                          # qualidade dupla
    "Unusual Strange Bonk Boy",                          # qualidade dupla, outra ordem
    "Unusual Professional Killstreak Rocket Launcher",   # arma
    "Unusual Sleighin' Style War Paint (Factory New)",   # war paint
    "Unusual Taunt: Chairholder Unusualifier",           # ferramenta
    "Team Captain",                                      # não é Unusual
    "Unusual Não Existe",                                # fora do schema
])
def test_recusa_o_que_nao_e_cosmetico_unusual(nome):
    assert not e_cosmetico_unusual(nome, COSMETICOS)


def test_nomes_de_cosmeticos_filtra_classe_e_slot():
    itens = [
        {"item_name": "Team Captain", "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Hot Case", "item_class": "tf_wearable", "item_slot": "misc"},
        {"item_name": "Taunt: Chairholder", "item_class": "tf_wearable", "item_slot": "taunt"},
        {"item_name": "Gunboats", "item_class": "tf_wearable", "item_slot": "secondary"},
        {"item_name": "Rocket Launcher", "item_class": "tf_weapon_rocketlauncher", "item_slot": "primary"},
        {"item_name": "Team Captain", "item_class": "tf_wearable", "item_slot": "head"},  # defindex repetido
    ]
    assert nomes_de_cosmeticos(itens) == ["Hot Case", "Team Captain"]


def test_defindices_de_cosmeticos_preserva_multiplos_ids_por_nome():
    itens = [
        {"item_name": "Team Captain", "defindex": 378, "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Team Captain", "defindex": 999, "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Team Captain", "defindex": 378, "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Taunt: Chairholder", "defindex": 31578, "item_class": "tf_wearable", "item_slot": "taunt"},
        {"item_name": "Gunboats", "defindex": 444, "item_class": "tf_wearable", "item_slot": "secondary"},
    ]
    assert defindices_de_cosmeticos(itens) == {"Team Captain": [378, 999]}


def test_arquivo_empacotado_tem_chapeus_e_nao_tem_taunts():
    cosmeticos = carregar_cosmeticos()
    assert "Team Captain" in cosmeticos
    assert "Brigade Helm" in cosmeticos
    assert "Taunt: Chairholder" not in cosmeticos
    assert len(cosmeticos) > 500


def test_mapa_empacotado_cobre_todos_os_nomes():
    from tf2price.sources.classificados import carregar_defindices

    mapa = carregar_defindices(COSMETICOS_DEFINDEX_PATH)
    assert set(mapa) == carregar_cosmeticos()
    assert 378 in mapa["Team Captain"]
