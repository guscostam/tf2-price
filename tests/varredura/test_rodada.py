from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import event

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.preco.retrato import Leitura
from tf2price.sources.ratelimit import SteamLimitando
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, PageStructureError
from tf2price.varredura import repositorio as repo
from tf2price.varredura import rodada as rodada_mod
from tf2price.varredura.rodada import (
    ESPACO_EXTRA_S, MAX_PAUSAS_SEGUIDAS, QUERY, executar_rodada,
)

T0 = db.agora()
CALMA_S = 300.0


class _Tempo:
    """Relógio simulado: `esperar` avança o tempo na hora, sem dormir.

    `cancelar_se(segundos)` decide se a espera volta cancelada, que é o que
    `threading.Event.wait` devolve quando o admin aperta Stop. `ao_esperar`
    deixa o teste olhar o banco no meio de uma espera, antes de o tempo andar.
    """

    def __init__(self, inicio=T0, cancelar_se=None, ao_esperar=None):
        self.inicio = inicio
        self.s = 0.0
        self.esperas: list[float] = []
        self.cancelar_se = cancelar_se
        self.ao_esperar = ao_esperar

    def agora(self):
        return self.inicio + timedelta(seconds=self.s)

    def esperar(self, segundos):
        self.esperas.append(segundos)
        if self.ao_esperar is not None:
            self.ao_esperar(segundos)
        self.s += segundos
        return bool(self.cancelar_se and self.cancelar_se(segundos))

    def pausas(self):
        return [e for e in self.esperas if e >= 60]


def _aceitar(nome: str) -> bool:
    return nome.startswith("Unusual ") and "Taunt" not in nome


def _r(nome, usd=1000, n=1):
    return SearchResult(hash_name=nome, lowest_price=Brl(usd * 5), sell_listings=n,
                        sell_price_usd_cents=usd)


def _pagina(nome, *listagens):
    return ItemPage(
        hash_name=nome,
        listings=[PageListing(i, Brl(c), e, None) for i, c, e in listagens],
        orderbook=OrderBook(None, None, 0, 0),
        history=[],
    )


class _Steam:
    """Busca falsa: fatia a lista de 10 em 10, como a Steam real.

    `limitar_busca={start: n}` responde 429 nas n primeiras tentativas
    daquele `start`; `usd_limitado=n` faz o mesmo com a cotação do dólar.
    """

    def __init__(self, resultados, limitar_busca=None, erro_no_start=None, erro=None,
                 usd_limitado=0, contador=None, ao_buscar=None):
        self.resultados = list(resultados)
        self.limitar_busca = dict(limitar_busca or {})
        self.erro_no_start = erro_no_start
        self.erro = erro or RuntimeError("HTTP 500")
        self.usd_limitado = usd_limitado
        self.contador = contador
        self.ao_buscar = ao_buscar
        self.chamadas = []
        self.usd_chamadas = 0
        self.emprestadas = []

    def usd_to_brl(self):
        self.usd_chamadas += 1
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.usd_limitado > 0:
            self.usd_limitado -= 1
            raise SteamLimitando("429")
        return 5.0

    def search_page(self, start=0, count=100, query=None):
        self.chamadas.append((start, query))
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.ao_buscar is not None:
            self.ao_buscar(start)
        if self.limitar_busca.get(start, 0) > 0:
            self.limitar_busca[start] -= 1
            raise SteamLimitando("429")
        if start == self.erro_no_start:
            raise self.erro
        return SearchPage(total_count=len(self.resultados),
                          results=self.resultados[start:start + 10])


class _Retratos:
    """`limitar={nome: n}` devolve a leitura em calma (429) nas n primeiras
    tentativas daquele nome, ligando a calma como o `Retratos` real."""

    def __init__(self, paginas, limitar=None, quebrar=(), antigo=(), contador=None,
                 erros=None, ao_pedir=None):
        self.paginas = paginas
        self.limitar = dict(limitar or {})
        self.quebrar = set(quebrar)
        self.antigo = set(antigo)
        self.contador = contador
        self.erros = dict(erros or {})
        self.ao_pedir = ao_pedir
        self.tempo = None  # o `_rodar` do teste liga o relógio simulado
        self.calma_ate = 0.0
        self.pedidos = []
        self.taxas = []
        self.emprestadas = []

    def _s(self):
        return self.tempo.s if self.tempo is not None else 0.0

    def em_calma(self):
        return self._s() < self.calma_ate

    def calma_restante_s(self):
        return max(0.0, self.calma_ate - self._s())

    def acalmar(self):
        self.calma_ate = self._s() + CALMA_S

    def obter(self, engine, hash_name, usd_to_brl, quando, forcar=False):
        assert forcar
        self.pedidos.append(hash_name)
        self.taxas.append(usd_to_brl)
        if self.ao_pedir is not None:
            self.ao_pedir(hash_name)
        if hash_name in self.erros:
            raise self.erros[hash_name]
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.limitar.get(hash_name, 0) > 0:
            self.limitar[hash_name] -= 1
            self.acalmar()
            return Leitura(None, None, True)
        if hash_name in self.quebrar:
            raise PageStructureError("pagina mudou")
        if hash_name in self.antigo:
            return Leitura(self.paginas[hash_name], quando - timedelta(minutes=1), False)
        return Leitura(self.paginas[hash_name], quando, False)


def _cotacao(valor=SimpleNamespace(usd_to_brl=5.0)):
    return SimpleNamespace(obter=lambda engine: valor)


def _rodar(engine, steam, retratos, quando=T0, cotacao=None, tempo=None):
    tempo = tempo or _Tempo(quando)
    retratos.tempo = tempo
    return executar_rodada(
        engine, steam=steam, retratos=retratos, cotacao=cotacao or _cotacao(),
        agora=tempo.agora, esperar=tempo.esperar, aceitar=_aceitar,
    )


def _listagens(engine):
    with engine.begin() as conn:
        return {(l.hash_name, l.listing_id) for l in repo.listar_listagens(conn)}


PAGINAS = {
    "Unusual A": _pagina("Unusual A", ("a1", 500, "Burning Flames"), ("a2", 900, "Sunbeams")),
    "Unusual B": _pagina("Unusual B", ("b1", 700, "Burning Flames")),
}
TAUNTS = [_r(f"Unusual Taunt: {i}") for i in range(10)]


# --- o caminho normal (comportamento que já existia) -----------------------

def test_primeira_rodada_le_a_fundo_so_os_cosmeticos_e_pagina_a_busca(engine):
    steam = _Steam([_r("Unusual A", n=2), *TAUNTS, _r("Unusual B")])
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, steam, retratos)

    assert steam.usd_chamadas == 1
    assert steam.chamadas == [(0, QUERY), (10, QUERY)]
    assert retratos.pedidos == ["Unusual A", "Unusual B"]
    assert (resumo.nomes_lidos, resumo.fundas_feitas, resumo.falhas, resumo.motivo) == (2, 2, 0, "ok")
    assert _listagens(engine) == {("Unusual A", "a1"), ("Unusual A", "a2"), ("Unusual B", "b1")}
    with engine.begin() as conn:
        rodada = repo.ultima_rodada(conn)
    assert (rodada.motivo_parada, rodada.nomes_lidos, rodada.fundas_feitas) == ("ok", 2, 2)


def test_assinatura_igual_dentro_do_prazo_nao_le_a_fundo(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos,
                    quando=T0 + timedelta(hours=3))

    assert retratos.pedidos == []
    assert (resumo.nomes_lidos, resumo.fundas_feitas) == (2, 0)


def test_assinatura_mudada_le_a_fundo_so_aquele_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B")]), retratos,
           quando=T0 + timedelta(hours=1))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_vencida_le_de_novo(engine):
    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A")]), retratos, quando=T0 + timedelta(hours=25))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_substitui_as_listagens_do_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A", n=2)]), _Retratos(PAGINAS))
    vendida = {"Unusual A": _pagina("Unusual A", ("a2", 900, "Sunbeams"))}

    _rodar(engine, _Steam([_r("Unusual A", n=1)]), _Retratos(vendida),
           quando=T0 + timedelta(hours=1))

    assert _listagens(engine) == {("Unusual A", "a2")}


def test_assinatura_mudada_sobrevive_a_falha_na_funda_e_e_relida_depois(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    resumo2 = _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
                     _Retratos(PAGINAS, quebrar={"Unusual A"}), quando=T0 + timedelta(hours=1))
    assert (resumo2.falhas, resumo2.motivo) == (1, "ok")

    retratos3 = _Retratos(PAGINAS)
    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
           retratos3, quando=T0 + timedelta(hours=2))

    assert retratos3.pedidos == ["Unusual A"]


def test_nome_quebrado_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, quebrar={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_retrato_antigo_nao_substitui_listagens_nem_marca_funda(engine):
    resumo = _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS, antigo={"Unusual A"}))

    assert resumo.fundas_feitas == 0
    assert _listagens(engine) == set()
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual A").funda_em is None


def test_nome_sumido_so_sai_depois_de_duas_rodadas_completas_sem_ele(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=1))
    assert ("Unusual B", "b1") in _listagens(engine)

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=2))
    assert ("Unusual B", "b1") not in _listagens(engine)


def test_sem_cotacao_da_chave_a_rodada_para_com_erro_sem_ir_a_steam(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), cotacao=_cotacao(None))

    assert resumo.motivo == "erro"
    assert (steam.usd_chamadas, steam.chamadas) == (0, [])


def test_espaco_extra_antes_de_cada_passo(engine):
    tempo = _Tempo()

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS), tempo=tempo)

    # cotação do dólar + 1 página da busca + 2 leituras fundas
    assert tempo.esperas == [ESPACO_EXTRA_S] * 4


def test_estourar_o_teto_de_paginas_rasas_conta_como_erro(engine, monkeypatch):
    monkeypatch.setattr(rodada_mod, "MAX_PAGINAS_RASAS", 1)
    resultados = [_r(f"Unusual {i}") for i in range(15)]
    steam = _Steam(resultados)
    retratos = _Retratos({})

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "erro"
    assert len(steam.chamadas) == 1
    assert retratos.pedidos == []


def test_nenhuma_conexao_emprestada_durante_as_requisicoes(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    steam = _Steam([_r("Unusual A"), _r("Unusual B")], contador=contador)
    retratos = _Retratos(PAGINAS, contador=contador)

    _rodar(engine, steam, retratos)

    assert steam.emprestadas == [0, 0]  # cotação do dólar + busca
    assert retratos.emprestadas == [0, 0]


def test_nenhuma_conexao_emprestada_durante_as_esperas(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    durante = []
    tempo = _Tempo(ao_esperar=lambda s: durante.append(contador["emprestadas"]))

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS, limitar={"Unusual A": 1}),
           tempo=tempo)

    assert durante and set(durante) == {0}


def test_excecao_qualquer_na_leitura_funda_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, erros={"Unusual A": ValueError("preco estranho")})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert retratos.pedidos == ["Unusual A", "Unusual B"]
    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_falha_ao_gravar_as_listagens_conta_falha_e_a_rodada_segue(engine, monkeypatch):
    original = repo.substituir_listagens

    def substituir(conn, nome, listagens, quando):
        if nome == "Unusual A":
            raise RuntimeError("value too long for type character varying(120)")
        return original(conn, nome, listagens, quando)

    monkeypatch.setattr(repo, "substituir_listagens", substituir)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual A").funda_em is None


def test_progresso_da_falha_e_gravado_antes_do_proximo_nome(engine):
    falhas_vistas = []

    def ao_pedir(nome):
        if nome == "Unusual B":
            with engine.begin() as conn:
                falhas_vistas.append(repo.ultima_rodada(conn).falhas)

    retratos = _Retratos(PAGINAS, erros={"Unusual A": KeyError("x")}, ao_pedir=ao_pedir)

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert falhas_vistas == [1]


def test_erro_que_nao_e_429_na_busca_para_com_erro_sem_apagar_nada(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS),
           quando=T0 + timedelta(hours=1))
    antes = _listagens(engine)
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A")], erro_no_start=0), retratos,
                    quando=T0 + timedelta(hours=2))

    assert resumo.motivo == "erro"
    assert retratos.calma_ate == 0.0
    assert retratos.pedidos == []
    assert _listagens(engine) == antes


def test_cada_leitura_funda_usa_a_cotacao_atual(engine):
    taxas = iter([SimpleNamespace(usd_to_brl=5.0), SimpleNamespace(usd_to_brl=5.1),
                  SimpleNamespace(usd_to_brl=5.2)])
    cotacao = SimpleNamespace(obter=lambda engine: next(taxas))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, cotacao=cotacao)

    assert retratos.taxas == [5.1, 5.2]


def test_cotacao_que_some_no_meio_para_a_rodada_com_erro(engine):
    valores = iter([SimpleNamespace(usd_to_brl=5.0), SimpleNamespace(usd_to_brl=5.0), None])
    cotacao = SimpleNamespace(obter=lambda engine: next(valores))
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, cotacao=cotacao)

    assert resumo.motivo == "erro"
    assert retratos.pedidos == ["Unusual A"]


# --- pausa e retomada no 429 -----------------------------------------------

def test_429_na_cotacao_do_dolar_pausa_e_retoma_antes_da_busca(engine):
    tempo = _Tempo()
    steam = _Steam([_r("Unusual A")], usd_limitado=1)

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=tempo)

    assert resumo.motivo == "ok"
    assert steam.usd_chamadas == 2
    assert steam.chamadas == [(0, QUERY)]
    assert tempo.pausas() == [300]


def test_429_na_busca_pausa_e_retoma_no_mesmo_start(engine):
    tempo = _Tempo()
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")], limitar_busca={10: 1})

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=tempo)

    assert resumo.motivo == "ok"
    assert steam.chamadas == [(0, QUERY), (10, QUERY), (10, QUERY)]
    assert tempo.pausas() == [300]
    assert _listagens(engine) == {("Unusual A", "a1"), ("Unusual A", "a2"), ("Unusual B", "b1")}


def test_429_na_funda_pausa_e_retoma_no_mesmo_nome(engine):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert retratos.pedidos == ["Unusual A", "Unusual A", "Unusual B"]
    assert resumo.fundas_feitas == 2
    assert tempo.pausas() == [300]


def test_pausas_crescem_e_a_rodada_desiste_depois_de_quatro(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    antes = _listagens(engine)
    tempo = _Tempo(T0 + timedelta(hours=1))
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 99})

    resumo = _rodar(engine, _Steam([_r("Unusual A", usd=1), _r("Unusual B", usd=1)]),
                    retratos, tempo=tempo)

    assert resumo.motivo == "429"
    assert tempo.pausas() == [300, 600, 1200, 1800]
    assert retratos.pedidos == ["Unusual A"] * (MAX_PAUSAS_SEGUIDAS + 1)
    assert _listagens(engine) == antes
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "429"


def test_429_persistente_na_busca_desiste_sem_ler_a_fundo(engine):
    retratos = _Retratos(PAGINAS)
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")], limitar_busca={10: 99})

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "429"
    assert steam.chamadas == [(0, QUERY)] + [(10, QUERY)] * (MAX_PAUSAS_SEGUIDAS + 1)
    assert retratos.pedidos == []


def test_sucesso_entre_pausas_zera_a_contagem(engine):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 2, "Unusual B": 2})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.pausas() == [300, 600, 300, 600]


def test_assinatura_mudada_sobrevive_a_429_persistente_e_e_relida_depois(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    resumo2 = _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
                     _Retratos(PAGINAS, limitar={"Unusual A": 99}),
                     quando=T0 + timedelta(hours=1))
    assert resumo2.motivo == "429"

    retratos3 = _Retratos(PAGINAS)
    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
           retratos3, quando=T0 + timedelta(hours=3))

    assert retratos3.pedidos == ["Unusual A", "Unusual B"]


def test_calma_ja_ligada_no_inicio_e_esperada_sem_contar_como_pausa(engine, capsys):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS)
    retratos.calma_ate = CALMA_S
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.esperas[0] == CALMA_S
    assert (steam.usd_chamadas, steam.chamadas) == (1, [(0, QUERY)])
    assert "pausa" not in capsys.readouterr().out


def test_calma_ligada_durante_o_espaco_extra_e_esperada_antes_de_requisitar(engine):
    retratos = _Retratos(PAGINAS)
    ligou = []

    def ao_esperar(segundos):
        if not ligou:
            ligou.append(True)
            retratos.calma_ate = tempo.s + CALMA_S

    tempo = _Tempo(ao_esperar=ao_esperar)
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.esperas[:2] == [ESPACO_EXTRA_S, CALMA_S - ESPACO_EXTRA_S]
    assert steam.usd_chamadas == 1


def test_log_diz_onde_veio_cada_429(engine, capsys):
    steam = _Steam([_r("Unusual A")], limitar_busca={0: 1}, usd_limitado=1)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1})

    resumo = _rodar(engine, steam, retratos)
    saida = capsys.readouterr().out

    assert resumo.motivo == "ok"
    assert ": 429 na cotação do dólar; pausa 1 de 4, até " in saida
    assert ": 429 na busca (página 1); pausa 1 de 4, até " in saida
    assert ": 429 na página de Unusual A; pausa 1 de 4, até " in saida


# --- cancelamento ------------------------------------------------------------

def test_stop_durante_a_pausa_termina_como_cancelada(engine):
    tempo = _Tempo(cancelar_se=lambda s: s >= 300)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 99})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "cancelada"
    assert retratos.pedidos == ["Unusual A"]
    assert _listagens(engine) == set()
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "cancelada"
        assert repo.ler_andamento(conn) is None


def test_stop_no_espaco_extra_para_sem_requisicao(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=_Tempo(cancelar_se=lambda s: True))

    assert resumo.motivo == "cancelada"
    assert (steam.usd_chamadas, steam.chamadas) == (0, [])


def test_rodada_cancelada_nao_apaga_nomes_sumidos(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=1))
    cancela_na_funda = _Tempo(T0 + timedelta(hours=2), cancelar_se=lambda s: s >= 300)

    _rodar(engine, _Steam([_r("Unusual A", usd=1)]), _Retratos(PAGINAS, limitar={"Unusual A": 1}),
           tempo=cancela_na_funda)

    assert ("Unusual B", "b1") in _listagens(engine)


# --- andamento e poda ----------------------------------------------------------

def test_andamento_acompanha_a_busca_e_a_funda_e_some_no_fim(engine):
    def andamento():
        with engine.begin() as conn:
            a = repo.ler_andamento(conn)
        return (a.fase, a.paginas_busca_lidas, a.paginas_busca_total, a.itens_lidos, a.itens_total)

    na_busca, na_funda = [], []
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")],
                   ao_buscar=lambda start: na_busca.append(andamento()))
    retratos = _Retratos(PAGINAS, ao_pedir=lambda nome: na_funda.append(andamento()))

    _rodar(engine, steam, retratos)

    assert na_busca == [("busca", 0, None, 0, None), ("busca", 1, 2, 0, None)]
    assert na_funda == [("paginas", 2, 2, 0, 2), ("paginas", 2, 2, 1, 2)]
    with engine.begin() as conn:
        assert repo.ler_andamento(conn) is None


def test_andamento_registra_a_pausa_e_a_limpa_ao_retomar(engine):
    durante, na_retomada = [], []

    def ao_esperar(segundos):
        if segundos >= 300:
            with engine.begin() as conn:
                a = repo.ler_andamento(conn)
            durante.append((a.fase, a.pausas_seguidas, a.pausado_ate - tempo.agora()))

    def ao_pedir(nome):
        if len(retratos.pedidos) == 2:
            with engine.begin() as conn:
                na_retomada.append(repo.ler_andamento(conn).pausado_ate)

    tempo = _Tempo(ao_esperar=ao_esperar)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1}, ao_pedir=ao_pedir)

    _rodar(engine, _Steam([_r("Unusual A")]), retratos, tempo=tempo)

    assert durante == [("paginas", 1, timedelta(minutes=5))]
    assert na_retomada == [None]


def test_rodada_poda_o_historico_ao_fechar(engine):
    with engine.begin() as conn:
        for i in range(25):
            quando = T0 - timedelta(hours=30 - i)
            rid = repo.abrir_rodada(conn, quando)
            repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                               falhas=0, motivo=repo.MOTIVO_429)

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS))

    with engine.begin() as conn:
        rodadas = repo.ultimas_rodadas(conn, 100)
    assert len(rodadas) == repo.MANTER_RODADAS
    assert rodadas[0].motivo_parada == "ok"
