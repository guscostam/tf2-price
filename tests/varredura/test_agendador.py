from __future__ import annotations

import threading
from datetime import timedelta

from tf2price import db
from tf2price.varredura import repositorio as repo
from tf2price.varredura.agendador import Agendador

T0 = db.agora()


def _ligar(engine, intervalo_min=60):
    with engine.begin() as conn:
        repo.gravar_config(conn, repo.Config(True, intervalo_min, 24), T0)


def _rodada_em(engine, quando, fim=None):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, quando)
        repo.fechar_rodada(conn, rid, fim or quando, nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=repo.MOTIVO_OK)


def test_desligada_nunca_vence(engine):
    assert not Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0).vencida()


def test_ligada_sem_rodada_nenhuma_vence(engine):
    _ligar(engine)
    assert Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0).vencida()


def test_vence_so_depois_do_intervalo(engine):
    _ligar(engine, intervalo_min=60)
    _rodada_em(engine, T0)
    antes = Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0 + timedelta(minutes=59))
    depois = Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0 + timedelta(minutes=60))
    assert not antes.vencida()
    assert depois.vencida()


def test_intervalo_conta_do_fim_da_ultima_rodada(engine):
    # A primeira rodada lê ~1000 páginas a ~5 s: dura mais que o intervalo.
    # Contado do início, a próxima sairia logo em seguida e o piso de 60 min
    # que protege a consulta do 429 não valeria nada.
    _ligar(engine, intervalo_min=60)
    _rodada_em(engine, T0 - timedelta(hours=3), fim=T0 - timedelta(minutes=30))
    assert not Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0).vencida()


def test_rodada_longa_vence_depois_do_intervalo_contado_do_fim(engine):
    _ligar(engine, intervalo_min=60)
    _rodada_em(engine, T0 - timedelta(hours=3), fim=T0 - timedelta(minutes=61))
    assert Agendador(engine, rodar=lambda cancelar: None, agora=lambda: T0).vencida()


def test_nunca_duas_rodadas_ao_mesmo_tempo(engine):
    entrou = threading.Event()
    soltar = threading.Event()
    rodadas = []

    def rodar(cancelar):
        rodadas.append(1)
        entrou.set()
        soltar.wait(5)

    agendador = Agendador(engine, rodar=rodar)
    assert agendador.disparar_em_segundo_plano()
    assert entrou.wait(5)

    assert agendador.rodando
    assert not agendador.tentar_rodar()
    assert not agendador.disparar_em_segundo_plano()

    soltar.set()
    for _ in range(100):
        if not agendador.rodando:
            break
        threading.Event().wait(0.01)
    assert not agendador.rodando
    assert rodadas == [1]


def test_ciclo_roda_quando_vence_e_sobrevive_a_erro(engine):
    _ligar(engine)
    parar = threading.Event()
    chamadas = []

    def rodar(cancelar):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("bug da rodada")
        parar.set()

    Agendador(engine, rodar=rodar).ciclo(parar, periodo_s=0)

    assert chamadas == [1, 1]


def test_parar_rodada_liga_o_evento_da_rodada_em_curso(engine):
    entrou = threading.Event()
    viu_cancelamento = []

    def rodar(cancelar):
        entrou.set()
        viu_cancelamento.append(cancelar.wait(5))

    agendador = Agendador(engine, rodar=rodar)
    assert agendador.disparar_em_segundo_plano()
    assert entrou.wait(5)

    assert agendador.parar_rodada()

    for _ in range(100):
        if not agendador.rodando:
            break
        threading.Event().wait(0.01)
    assert viu_cancelamento == [True]


def test_parar_sem_rodada_devolve_falso(engine):
    assert not Agendador(engine, rodar=lambda cancelar: None).parar_rodada()


def test_cada_rodada_recebe_um_evento_novo(engine):
    eventos = []
    agendador = Agendador(engine, rodar=eventos.append)

    agendador.tentar_rodar()
    eventos[0].set()
    agendador.tentar_rodar()

    assert eventos[0] is not eventos[1]
    assert not eventos[1].is_set()


def test_construir_agendador_passa_o_cancelamento_como_espera(engine, monkeypatch):
    from types import SimpleNamespace

    from tf2price.varredura import agendador as agendador_mod

    capturado = {}
    monkeypatch.setattr(agendador_mod, "executar_rodada",
                        lambda engine, **kwargs: capturado.update(kwargs))
    contexto = SimpleNamespace(steam="s", retratos="r", cotacao="c")
    evento = threading.Event()

    agendador_mod.construir_agendador(engine, contexto)._rodar(evento)

    assert capturado == {"steam": "s", "retratos": "r", "cotacao": "c", "esperar": evento.wait}
