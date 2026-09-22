from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio as contas_repo
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from tf2price.varredura import repositorio as repo

SENHA = "uma senha longa"


class _AgendadorFalso:
    def __init__(self, livre=True):
        self.livre = livre
        self.disparos = 0
        self.rodando = not livre

    def disparar_em_segundo_plano(self):
        self.disparos += 1
        return self.livre


def _entra(engine, nome="gusco", admin=True, agendador=None):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = contas_repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine, agendador=agendador))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente


def test_admin_mostra_a_configuracao_padrao(engine):
    texto = _entra(engine).get("/admin").text
    assert "Market scan" in texto
    assert 'name="intervalo_min"' in texto and 'value="180"' in texto
    assert "No scans yet." in texto


def test_salvar_configuracao(engine):
    admin = _entra(engine)
    r = admin.post("/admin/varredura",
                   data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    assert r.status_code == 200
    assert "Scanner settings saved." in r.text
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.Config(True, 90, 12)


def test_desmarcar_desliga(engine):
    admin = _entra(engine)
    admin.post("/admin/varredura", data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    admin.post("/admin/varredura", data={"intervalo_min": "90", "idade_max_funda_h": "12"})
    with engine.begin() as conn:
        assert not repo.ler_config(conn).ligada


@pytest.mark.parametrize("dados, mensagem", [
    ({"ligada": "1", "intervalo_min": "59", "idade_max_funda_h": "12"}, "at least 60 minutes"),
    ({"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "0"}, "at least 1 hour"),
    ({"ligada": "1", "intervalo_min": "abc", "idade_max_funda_h": "12"}, "whole numbers"),
])
def test_configuracao_invalida_e_recusada(engine, dados, mensagem):
    admin = _entra(engine)
    r = admin.post("/admin/varredura", data=dados)
    assert mensagem in r.text
    with engine.begin() as conn:
        assert repo.ler_config(conn) == repo.PADRAO


def test_membro_comum_nao_configura(engine):
    _entra(engine)
    comum = _entra(engine, nome="amiga", admin=False)
    r = comum.post("/admin/varredura", data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"})
    assert r.status_code == 403


def test_origem_de_outro_site_e_recusada(engine):
    admin = _entra(engine)
    r = admin.post("/admin/varredura",
                   data={"ligada": "1", "intervalo_min": "90", "idade_max_funda_h": "12"},
                   headers={"origin": "https://outro.site"})
    assert r.status_code == 403


def test_run_now_dispara(engine):
    agendador = _AgendadorFalso()
    r = _entra(engine, agendador=agendador).post("/admin/varredura/rodar")
    assert agendador.disparos == 1
    assert "Scan started." in r.text


def test_run_now_com_rodada_em_curso(engine):
    r = _entra(engine, agendador=_AgendadorFalso(livre=False)).post("/admin/varredura/rodar")
    assert "A scan is already running." in r.text


def test_run_now_sem_agendador(engine):
    r = _entra(engine).post("/admin/varredura/rodar")
    assert "The scanner is not available in this process." in r.text


def test_lista_as_rodadas_com_rotulo_em_ingles(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, db.agora())
        repo.fechar_rodada(conn, rid, db.agora(), nomes_lidos=12, fundas_feitas=3,
                           falhas=1, motivo=repo.MOTIVO_429)
    texto = _entra(engine).get("/admin").text
    assert "Stopped: Steam rate limit" in texto
    assert "interrompida" not in texto
