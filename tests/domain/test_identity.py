from __future__ import annotations

import pytest

from tf2price.domain.identity import (
    QUALITY_UNIQUE,
    ItemIdentity,
    bptf_name_candidates,
    is_unusual_name,
    parse_market_hash_name,
)

# (market_hash_name, base_name, quality_id, killstreak, australium, festivized, wear)
CASOS = [
    # --- sem nenhum modificador ---
    ("Mann Co. Supply Crate Key", "Mann Co. Supply Crate Key", 6, 0, False, False, None),
    ("Refined Metal", "Refined Metal", 6, 0, False, False, None),
    ("Taunt: The Killer Solo", "Taunt: The Killer Solo", 6, 0, False, False, None),
    # --- qualidades ---
    ("Strange Scattergun", "Scattergun", 11, 0, False, False, None),
    ("Genuine Dead Cone", "Dead Cone", 1, 0, False, False, None),
    ("Vintage Tyrolean", "Tyrolean", 3, 0, False, False, None),
    ("Unusual Team Captain", "Team Captain", 5, 0, False, False, None),
    ("Haunted Executioner", "Executioner", 13, 0, False, False, None),
    ("Collector's Rocket Launcher", "Rocket Launcher", 14, 0, False, False, None),
    # --- killstreak, do mais longo para o mais curto ---
    ("Killstreak Scattergun", "Scattergun", 6, 1, False, False, None),
    ("Specialized Killstreak Scattergun", "Scattergun", 6, 2, False, False, None),
    ("Professional Killstreak Scattergun", "Scattergun", 6, 3, False, False, None),
    ("Strange Professional Killstreak Scattergun", "Scattergun", 11, 3, False, False, None),
    ("Specialized Killstreak Kit Fabricator", "Kit Fabricator", 6, 2, False, False, None),
    # --- australium e festivized ---
    ("Australium Rocket Launcher", "Rocket Launcher", 6, 0, True, False, None),
    ("Strange Australium Rocket Launcher", "Rocket Launcher", 11, 0, True, False, None),
    ("Professional Killstreak Australium Rocket Launcher", "Rocket Launcher", 6, 3, True, False, None),
    ("Festivized Rocket Launcher", "Rocket Launcher", 6, 0, False, True, None),
    (
        "Strange Festivized Professional Killstreak Australium Rocket Launcher",
        "Rocket Launcher",
        11,
        3,
        True,
        True,
        None,
    ),
    # --- war paints: desgaste no fim, entre parênteses ---
    (
        "Civic Duty Mk.II War Paint (Field-Tested)",
        "Civic Duty Mk.II War Paint",
        6,
        0,
        False,
        False,
        "Field-Tested",
    ),
    (
        "Strange Civic Duty Mk.II War Paint (Battle Scarred)",
        "Civic Duty Mk.II War Paint",
        11,
        0,
        False,
        False,
        "Battle Scarred",
    ),
    (
        "Bomber Soul War Paint (Factory New)",
        "Bomber Soul War Paint",
        6,
        0,
        False,
        False,
        "Factory New",
    ),
    # --- a armadilha: nome começa com palavra de qualidade sem ser daquela qualidade ---
    ("Strange Part: Kills", "Strange Part: Kills", 6, 0, False, False, None),
    ("Strange Filter: Mann Manor", "Strange Filter: Mann Manor", 6, 0, False, False, None),
    ("Haunted Metal Scrap", "Haunted Metal Scrap", 6, 0, False, False, None),
    ("Strange Bacon Grease", "Strange Bacon Grease", 6, 0, False, False, None),
]


@pytest.mark.parametrize(
    "hash_name,base,quality,killstreak,australium,festivized,wear", CASOS
)
def test_parse_market_hash_name(
    hash_name, base, quality, killstreak, australium, festivized, wear
):
    assert parse_market_hash_name(hash_name) == ItemIdentity(
        base_name=base,
        quality_id=quality,
        killstreak=killstreak,
        australium=australium,
        festivized=festivized,
        wear=wear,
    )


def test_quality_unique_e_o_default():
    assert parse_market_hash_name("Scattergun").quality_id == QUALITY_UNIQUE


def test_espacos_nas_bordas_sao_ignorados():
    assert parse_market_hash_name("  Strange Scattergun  ").base_name == "Scattergun"


def test_candidatos_tentam_o_nome_original_primeiro():
    original = "Specialized Killstreak Kit Fabricator"
    identity = parse_market_hash_name(original)
    assert bptf_name_candidates(identity, original)[0] == original


def test_candidatos_incluem_variante_australium_antes_da_base():
    original = "Strange Australium Rocket Launcher"
    identity = parse_market_hash_name(original)
    candidatos = bptf_name_candidates(identity, original)
    assert candidatos.index("Australium Rocket Launcher") < candidatos.index(
        "Rocket Launcher"
    )


def test_candidatos_sem_repeticao():
    original = "Scattergun"
    identity = parse_market_hash_name(original)
    candidatos = bptf_name_candidates(identity, original)
    assert len(candidatos) == len(set(candidatos))


# --- reconhecimento da qualidade Unusual pelo nome -----------------------

UNUSUAIS = [
    "Unusual Team Captain",
    "Unusual Taunt: Chairholder",
    # Dupla qualidade: 28 de 100 nomes da busca real por "Unusual".
    "Strange Unusual Bonk Boy",
    "Strange Unusual Villain's Veil",
    "Strange Unusual Sleighin' Style War Paint (Battle Scarred)",
    "Strange Unusual Professional Killstreak Blitzkrieg Medi Gun (Minimal Wear)",
    "Strange Unusual Festivized Candy Coated Rescue Ranger (Factory New)",
]

NAO_UNUSUAIS = [
    "Team Captain",
    "Strange Scattergun",
    "Mann Co. Supply Crate Key",
    # Ferramentas que APLICAM um efeito. Começam com "Unusual " sem serem
    # itens Unusual, e a busca as devolve junto das de verdade.
    "Unusual Taunt: Chairholder Unusualifier",
    "Unusual Taunt: Conga Unusualifier",
]


@pytest.mark.parametrize("nome", UNUSUAIS)
def test_reconhece_os_unusuais(nome):
    assert is_unusual_name(nome) is True


@pytest.mark.parametrize("nome", NAO_UNUSUAIS)
def test_recusa_o_que_nao_e_unusual(nome):
    assert is_unusual_name(nome) is False


def test_unusual_nao_casa_como_pedaco_de_palavra():
    assert is_unusual_name("Strange Unusualifier") is False


def test_espacos_nas_bordas_nao_atrapalham():
    assert is_unusual_name("  Strange Unusual Bonk Boy  ") is True


def test_candidatos_descascam_o_unusual_da_dupla_qualidade():
    """`Strange Unusual Bonk Boy` tem preço na bp.tf sob `Bonk Boy`.

    O parser consome uma qualidade só, então `Unusual ` sobra no base_name e
    nenhum candidato batia no índice: o preço de troca saía indisponível para
    todo item de dupla qualidade.
    """
    original = "Strange Unusual Bonk Boy"
    identity = parse_market_hash_name(original)
    candidatos = bptf_name_candidates(identity, original)

    assert "Bonk Boy" in candidatos
    assert candidatos.index("Unusual Bonk Boy") < candidatos.index("Bonk Boy")


def test_candidatos_nao_descascam_unusual_de_item_simples():
    """Em `Unusual Team Captain` a qualidade já foi consumida pelo parser."""
    original = "Unusual Team Captain"
    identity = parse_market_hash_name(original)
    assert bptf_name_candidates(identity, original) == [original, "Team Captain"]
