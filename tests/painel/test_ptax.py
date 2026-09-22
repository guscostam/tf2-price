"""A PTAX sob demanda: mesma divisão de `CotacaoSobDemanda`.

`obter` só lê (memória, banco) e é o que as rotas chamam; `renovar` vai à
rede e só o fio de fundo chama. A validade é de 1 hora porque a PTAX sai uma
vez por dia.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tf2price import db
from tf2price.painel.ptax import VALIDADE_PTAX, PtaxSobDemanda
from tf2price.preco import repositorio as preco_repo
from tf2price.sources.bcb import Ptax

AGORA = db.agora()
DATA_DO_BC = datetime(2026, 9, 21, 13, 6, 51)


class _Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


class _BcbFalso:
    def __init__(self, valor: float = 5.1117) -> None:
        self.valor = valor
        self.chamadas = 0
        self.dias: list[date] = []
        self.falhar = False

    def ptax(self, hoje: date) -> Ptax:
        self.chamadas += 1
        self.dias.append(hoje)
        if self.falhar:
            raise RuntimeError("BC fora do ar")
        return Ptax(self.valor, DATA_DO_BC)


def _guardar(engine, valor: float, buscado_em: datetime) -> None:
    with engine.begin() as conn:
        preco_repo.guardar_ptax(conn, valor, DATA_DO_BC, buscado_em)


def test_obter_com_banco_vazio_nao_vai_ao_bc(engine):
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).obter(engine) is None
    assert bcb.chamadas == 0


def test_obter_le_do_banco_no_processo_novo(engine):
    _guardar(engine, 5.0, AGORA - timedelta(days=2))
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).obter(engine) == Ptax(5.0, DATA_DO_BC)
    assert bcb.chamadas == 0


def test_renovar_busca_grava_e_diz_no_log(engine, capsys):
    bcb = _BcbFalso()
    sob = PtaxSobDemanda(bcb)

    assert sob.renovar(engine, AGORA) == Ptax(5.1117, DATA_DO_BC)

    assert bcb.dias == [AGORA.date()]
    with engine.begin() as conn:
        assert preco_repo.ler_ptax(conn) == (5.1117, DATA_DO_BC, AGORA)
    assert "[ptax]" in capsys.readouterr().out


def test_renovar_dentro_da_validade_nao_busca(engine):
    _guardar(engine, 5.0, AGORA - VALIDADE_PTAX)
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).renovar(engine, AGORA).valor == 5.0
    assert bcb.chamadas == 0


def test_renovar_vencida_busca_de_novo(engine):
    _guardar(engine, 5.0, AGORA - VALIDADE_PTAX - timedelta(minutes=1))
    bcb = _BcbFalso()
    assert PtaxSobDemanda(bcb).renovar(engine, AGORA).valor == 5.1117
    assert bcb.chamadas == 1


def test_falha_mantem_a_guardada_e_diz_no_log(engine, capsys):
    _guardar(engine, 5.0, AGORA - timedelta(days=1))
    bcb = _BcbFalso()
    bcb.falhar = True

    ptax = PtaxSobDemanda(bcb).renovar(engine, AGORA)

    assert ptax == Ptax(5.0, DATA_DO_BC)
    assert "[sob-demanda] PtaxSobDemanda: RuntimeError" in capsys.readouterr().out


def test_dentro_da_calma_nao_tenta_de_novo(engine):
    relogio = _Relogio()
    bcb = _BcbFalso()
    bcb.falhar = True
    sob = PtaxSobDemanda(bcb, espera_apos_falha_s=300.0, relogio=relogio)

    sob.renovar(engine, AGORA)
    relogio.agora = 299.0
    sob.renovar(engine, AGORA)
    assert bcb.chamadas == 1

    relogio.agora = 301.0
    bcb.falhar = False
    assert sob.renovar(engine, AGORA).valor == 5.1117
    assert bcb.chamadas == 2


def test_obter_depois_de_renovar_usa_a_memoria(engine):
    sob = PtaxSobDemanda(_BcbFalso())
    sob.renovar(engine, AGORA)
    with engine.begin() as conn:
        preco_repo.guardar_ptax(conn, 9.9, DATA_DO_BC, AGORA)
    assert sob.obter(engine).valor == 5.1117


def test_contexto_real_traz_a_ptax_sob_demanda(monkeypatch):
    from tf2price.painel.consulta import construir_contexto

    monkeypatch.setenv("BPTF_API_KEY", "chave-de-teste")
    assert isinstance(construir_contexto().ptax, PtaxSobDemanda)
