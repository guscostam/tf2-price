from __future__ import annotations

import pytest

from tf2price.domain.identity import (
    QUALITY_UNIQUE,
    ItemIdentity,
    bptf_name_candidates,
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
