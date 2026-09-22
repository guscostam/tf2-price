from __future__ import annotations

from datetime import timedelta

import pytest

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.sources.steam_page import PageListing
from tf2price.varredura import repositorio as repo

T0 = db.agora()


def _l(ident, centavos, efeito="Burning Flames"):
    return PageListing(ident, Brl(centavos), efeito, None)


def test_config_padrao_quando_nada_foi_gravado(engine):
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.PADRAO
    assert repo.PADRAO == repo.Config(ligada=False, intervalo_min=180, idade_max_funda_h=24)


def test_config_grava_e_regrava(engine):
    with engine.begin() as conn:
        repo.gravar_config(conn, repo.Config(True, 60, 6), T0)
        repo.gravar_config(conn, repo.Config(True, 120, 12), T0)
        assert repo.ler_config(conn) == repo.Config(True, 120, 12)


@pytest.mark.parametrize("config", [repo.Config(True, 59, 24), repo.Config(True, 60, 0)])
def test_config_abaixo_do_minimo_e_recusada(engine, config):
    with engine.begin() as conn, pytest.raises(ValueError):
        repo.gravar_config(conn, config, T0)


def test_assinatura_nova_nasce_sem_funda(engine):
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual Team Captain") is None
        repo.gravar_vista(conn, "Unusual Team Captain", 89000, 7, T0)
        assert repo.ler_assinatura(conn, "Unusual Team Captain") == repo.Assinatura(89000, 7, None)


def test_gravar_vista_nao_apaga_a_funda(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500)], T0)
        repo.gravar_vista(conn, "X", 200, 2, T0 + timedelta(hours=1))
        assert repo.ler_assinatura(conn, "X") == repo.Assinatura(200, 2, T0)


def test_substituir_troca_todas_as_listagens_do_nome(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 2, T0)
        repo.gravar_vista(conn, "Y", 100, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500), _l("2", 700)], T0)
        repo.substituir_listagens(conn, "Y", [_l("9", 900)], T0)
        repo.substituir_listagens(conn, "X", [_l("2", 650)], T0 + timedelta(hours=1))
        linhas = repo.listar_listagens(conn)
    assert [(l.hash_name, l.listing_id, l.preco) for l in linhas] == [
        ("X", "2", Brl(650)),
        ("Y", "9", Brl(900)),
    ]


def test_substituir_ignora_listagem_sem_id_e_repetida(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 3, T0)
        repo.substituir_listagens(conn, "X", [_l("", 1), _l("1", 500), _l("1", 500)], T0)
        assert [l.listing_id for l in repo.listar_listagens(conn)] == ["1"]


def test_mais_na_steam_e_o_que_a_busca_viu_menos_o_que_foi_gravado(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 12, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500), _l("2", 600)], T0)
        assert {l.mais_na_steam for l in repo.listar_listagens(conn)} == {10}


def test_listar_filtra_por_texto_efeito_e_preco(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "Unusual Team Captain", 1, 2, T0)
        repo.gravar_vista(conn, "Unusual Brigade Helm", 1, 1, T0)
        repo.substituir_listagens(conn, "Unusual Team Captain",
                                  [_l("1", 500), _l("2", 900, "Sunbeams")], T0)
        repo.substituir_listagens(conn, "Unusual Brigade Helm", [_l("3", 700)], T0)

        assert {l.listing_id for l in repo.listar_listagens(conn, texto="team CAP")} == {"1", "2"}
        assert {l.listing_id for l in repo.listar_listagens(conn, efeito="Sunbeams")} == {"2"}
        assert {l.listing_id for l in repo.listar_listagens(
            conn, preco_min=Brl(600), preco_max=Brl(800))} == {"3"}
        # `%` e `_` são texto, não curinga
        assert repo.listar_listagens(conn, texto="%") == []
        assert repo.efeitos_varridos(conn) == ["Burning Flames", "Sunbeams"]


def test_apagar_nao_vistos_desde_remove_nome_e_listagens(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "Velho", 1, 1, T0)
        repo.substituir_listagens(conn, "Velho", [_l("1", 500)], T0)
        repo.gravar_vista(conn, "Novo", 1, 1, T0 + timedelta(hours=2))
        repo.substituir_listagens(conn, "Novo", [_l("2", 500)], T0 + timedelta(hours=2))

        assert repo.apagar_nao_vistos_desde(conn, T0 + timedelta(hours=1)) == 1
        assert [l.hash_name for l in repo.listar_listagens(conn)] == ["Novo"]
        assert repo.ler_assinatura(conn, "Velho") is None


def test_rodadas_abrir_progredir_fechar(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, T0)
        repo.atualizar_progresso(conn, rid, nomes_lidos=5, fundas_feitas=2, falhas=0)
        em_curso = repo.ultima_rodada(conn)
        assert (em_curso.fim, em_curso.nomes_lidos, em_curso.motivo_parada) == (None, 5, None)

        repo.fechar_rodada(conn, rid, T0 + timedelta(minutes=9),
                           nomes_lidos=7, fundas_feitas=3, falhas=1, motivo=repo.MOTIVO_OK)
        fechada = repo.ultima_completa(conn)
        assert (fechada.id, fechada.fundas_feitas, fechada.falhas) == (rid, 3, 1)


def test_ultima_completa_ignora_rodada_parada_por_429(engine):
    with engine.begin() as conn:
        ok = repo.abrir_rodada(conn, T0)
        repo.fechar_rodada(conn, ok, T0, nomes_lidos=1, fundas_feitas=1, falhas=0, motivo=repo.MOTIVO_OK)
        parada = repo.abrir_rodada(conn, T0 + timedelta(hours=1))
        repo.fechar_rodada(conn, parada, T0 + timedelta(hours=1),
                           nomes_lidos=1, fundas_feitas=0, falhas=0, motivo=repo.MOTIVO_429)
        assert repo.ultima_rodada(conn).id == parada
        assert repo.ultima_completa(conn).id == ok


def test_fechar_abertas_marca_interrompida(engine):
    with engine.begin() as conn:
        aberta = repo.abrir_rodada(conn, T0)
        assert repo.fechar_abertas(conn, T0 + timedelta(minutes=1)) == 1
        rodada = repo.ultima_rodada(conn)
        assert (rodada.id, rodada.motivo_parada) == (aberta, repo.MOTIVO_INTERROMPIDA)
        assert repo.fechar_abertas(conn, T0) == 0


def test_cobertura_conta_nomes_lidos_a_fundo_e_listagens(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 1, 2, T0)
        repo.gravar_vista(conn, "So vista", 1, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 1), _l("2", 2)], T0)
        assert repo.cobertura(conn) == repo.Cobertura(nomes=1, listagens=2)
