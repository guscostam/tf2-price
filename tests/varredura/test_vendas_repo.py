from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from tf2price import db
from tf2price.varredura import vendas_repo as repo


T0 = datetime(2026, 9, 24, 12)


def test_dois_efeitos_ficam_isolados_e_upsert_substitui_sucesso(engine):
    with engine.begin() as conn:
        repo.gravar_sucesso(conn, "Unusual Team Captain", "Burning Flames", Decimal("1.25"), Decimal("3.33"), T0, metal_por_chave=Decimal("50"))
        repo.gravar_sucesso(conn, "Unusual Team Captain", "Sunbeams", None, None, T0)
        repo.gravar_sucesso(conn, "Unusual Team Captain", "Burning Flames", Decimal("2"), Decimal("0"), T0 + timedelta(hours=1), metal_por_chave=Decimal("50"))
        registros = repo.ler_todas(conn)
    burning = registros[("Unusual Team Captain", "Burning Flames")]
    sunbeams = registros[("Unusual Team Captain", "Sunbeams")]
    assert (burning.estado, burning.chaves, burning.metal, burning.buscado_em) == (
        "encontrado", Decimal("2"), Decimal("0"), T0 + timedelta(hours=1))
    assert (sunbeams.estado, sunbeams.chaves, sunbeams.metal, sunbeams.buscado_em) == (
        "sem_vendas_confirmado", None, None, T0)


def test_falha_preserva_preco_e_instante_de_sucesso(engine):
    with engine.begin() as conn:
        repo.gravar_sucesso(conn, "X", "Burning Flames", Decimal("10"), Decimal("5"), T0, metal_por_chave=Decimal("50"))
        repo.gravar_falha(conn, "X", "Burning Flames", T0 + timedelta(hours=1))
        registro = repo.ler_todas(conn)[("X", "Burning Flames")]
        repo.gravar_falha(conn, "Y", "Sunbeams", T0)
        indisponivel = repo.ler_todas(conn)[("Y", "Sunbeams")]
    assert (registro.estado, registro.chaves, registro.metal, registro.buscado_em, registro.falhou_em) == (
        "encontrado", Decimal("10"), Decimal("5"), T0, T0 + timedelta(hours=1))
    assert (indisponivel.estado, indisponivel.buscado_em, indisponivel.falhou_em) == (
        "indisponivel", None, T0)


def test_sucesso_guarda_taxa_da_selecao_e_falha_a_preserva(engine):
    with engine.begin() as conn:
        repo.gravar_sucesso(
            conn, "X", "Burning Flames", Decimal("1"), Decimal("20"), T0,
            metal_por_chave=Decimal("50"),
        )
        repo.gravar_falha(conn, "X", "Burning Flames", T0 + timedelta(hours=1))
        registro = repo.ler_todas(conn)[("X", "Burning Flames")]
    assert registro.metal_por_chave == Decimal("50")
    assert registro.buscado_em == T0


def test_sucesso_com_vendedor_exige_taxa_valida(engine):
    with engine.begin() as conn:
        with pytest.raises(ValueError):
            repo.gravar_sucesso(conn, "X", "E", Decimal("1"), Decimal("0"), T0)
        with pytest.raises(ValueError):
            repo.gravar_sucesso(conn, "X", "E", Decimal("1"), Decimal("0"), T0,
                                metal_por_chave=Decimal("0"))


@pytest.mark.parametrize("chaves,metal", [(-1, 0), (Decimal("NaN"), 0), (None, 0), (0, None)])
def test_gravacao_recusa_quantias_invalidas(engine, chaves, metal):
    with engine.begin() as conn, pytest.raises(ValueError):
        repo.gravar_sucesso(conn, "X", "E", chaves, metal, T0)


def test_gravacao_recusa_identidade_e_data_invalidas(engine):
    with engine.begin() as conn:
        with pytest.raises(ValueError):
            repo.gravar_sucesso(conn, "", "E", None, None, T0)
        with pytest.raises(ValueError):
            repo.gravar_falha(conn, "X", "E", T0.astimezone())


def test_pares_recentes_filtra_data_e_deduplica(engine):
    from sqlalchemy import insert

    with engine.begin() as conn:
        for ident, nome, efeito, instante in [
            ("1", "Unusual Team Captain", "Burning Flames", T0),
            ("2", "Unusual Team Captain", "Burning Flames", T0),
            ("3", "Unusual Team Captain", "Sunbeams", T0),
            ("4", "Unusual Old Hat", "Burning Flames", T0 - timedelta(hours=7)),
        ]:
            conn.execute(insert(db.listagem_varrida).values(
                listing_id=ident, hash_name=nome, efeito=efeito,
                preco_cents=100, icone=None, lido_em=instante,
            ))
        pares = repo.pares_recentes(conn, T0 - timedelta(hours=6))
    assert pares == [
        ("Unusual Team Captain", "Burning Flames"),
        ("Unusual Team Captain", "Sunbeams"),
    ]
