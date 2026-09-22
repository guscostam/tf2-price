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


def test_marcar_para_funda_zera_a_funda_mantendo_a_assinatura(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 100, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 500)], T0)
        repo.marcar_para_funda(conn, "X")
        assert repo.ler_assinatura(conn, "X") == repo.Assinatura(100, 1, None)


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


def test_cobertura_conta_nomes_com_listagem_guardada_e_listagens(engine):
    with engine.begin() as conn:
        repo.gravar_vista(conn, "X", 1, 2, T0)
        repo.gravar_vista(conn, "So vista", 1, 1, T0)
        # Lido a fundo, mas a página veio sem listagem: não cobre nada.
        repo.gravar_vista(conn, "Lido vazio", 1, 1, T0)
        repo.substituir_listagens(conn, "X", [_l("1", 1), _l("2", 2)], T0)
        repo.substituir_listagens(conn, "Lido vazio", [], T0)
        assert repo.cobertura(conn) == repo.Cobertura(nomes=1, listagens=2)


def test_andamento_nasce_zerado_atualiza_e_some(engine):
    with engine.begin() as conn:
        assert repo.ler_andamento(conn) is None
        rid = repo.abrir_rodada(conn, T0)
        repo.iniciar_andamento(conn, rid, T0)
        assert repo.ler_andamento(conn) == repo.Andamento(
            rodada_id=rid, fase=repo.FASE_COTACAO, paginas_busca_lidas=0,
            paginas_busca_total=None, itens_lidos=0, itens_total=None,
            pausado_ate=None, pausas_seguidas=0, atualizado_em=T0,
        )
        depois = T0 + timedelta(minutes=1)
        repo.atualizar_andamento(conn, depois, fase=repo.FASE_PAGINAS, itens_lidos=3,
                                 itens_total=10, pausado_ate=depois, pausas_seguidas=1)
        andamento = repo.ler_andamento(conn)
        assert (andamento.fase, andamento.itens_lidos, andamento.itens_total) == ("paginas", 3, 10)
        assert (andamento.pausado_ate, andamento.pausas_seguidas, andamento.atualizado_em) == (depois, 1, depois)
        repo.limpar_andamento(conn)
        assert repo.ler_andamento(conn) is None


def test_iniciar_andamento_substitui_o_de_outra_rodada(engine):
    with engine.begin() as conn:
        repo.iniciar_andamento(conn, 1, T0)
        repo.atualizar_andamento(conn, T0, itens_lidos=7)
        repo.iniciar_andamento(conn, 2, T0)
        andamento = repo.ler_andamento(conn)
        assert (andamento.rodada_id, andamento.itens_lidos) == (2, 0)


def test_atualizar_andamento_recusa_campo_desconhecido(engine):
    with engine.begin() as conn:
        repo.iniciar_andamento(conn, 1, T0)
        with pytest.raises(TypeError):
            repo.atualizar_andamento(conn, T0, fase_errada="x")


def test_fechar_abertas_limpa_o_andamento(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, T0)
        repo.iniciar_andamento(conn, rid, T0)
        repo.fechar_abertas(conn, T0)
        assert repo.ler_andamento(conn) is None


def _rodadas_terminadas(conn, n, motivo=repo.MOTIVO_429, a_partir=T0):
    ids = []
    for i in range(n):
        quando = a_partir + timedelta(hours=i)
        rid = repo.abrir_rodada(conn, quando)
        repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=motivo)
        ids.append(rid)
    return ids


def test_podar_guarda_as_20_mais_recentes(engine):
    with engine.begin() as conn:
        ids = _rodadas_terminadas(conn, 25)
        assert repo.podar_rodadas(conn) == 5
        assert [r.id for r in repo.ultimas_rodadas(conn, 100)] == list(reversed(ids[5:]))


def test_podar_guarda_a_ultima_completa_mesmo_antiga(engine):
    with engine.begin() as conn:
        (completa,) = _rodadas_terminadas(conn, 1, motivo=repo.MOTIVO_OK,
                                          a_partir=T0 - timedelta(days=5))
        _rodadas_terminadas(conn, 25)
        repo.podar_rodadas(conn)
        restantes = {r.id for r in repo.ultimas_rodadas(conn, 100)}
    assert completa in restantes
    assert len(restantes) == repo.MANTER_RODADAS + 1


def test_podar_nunca_apaga_a_rodada_aberta(engine):
    with engine.begin() as conn:
        aberta = repo.abrir_rodada(conn, T0 - timedelta(days=9))
        _rodadas_terminadas(conn, 25)
        repo.podar_rodadas(conn)
        assert aberta in {r.id for r in repo.ultimas_rodadas(conn, 100)}
