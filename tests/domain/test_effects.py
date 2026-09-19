from __future__ import annotations

from pathlib import Path

import pytest

from tf2price.domain.effects import effect_id_for, load_effect_map

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"


def test_carrega_o_mapa():
    mapa = load_effect_map(FIXTURE)
    assert mapa["Burning Flames"] == 13


def test_ids_sao_inteiros():
    mapa = load_effect_map(FIXTURE)
    assert all(isinstance(v, int) for v in mapa.values())


def test_busca_por_nome_exato():
    assert effect_id_for("Burning Flames", FIXTURE) == 13


def test_busca_ignora_caixa_e_espacos():
    assert effect_id_for("  burning FLAMES  ", FIXTURE) == 13


def test_efeito_desconhecido_devolve_none():
    assert effect_id_for("Efeito Inexistente", FIXTURE) is None


def test_arquivo_ausente_levanta_erro_claro(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="effects.json"):
        load_effect_map(tmp_path / "nao_existe.json")
