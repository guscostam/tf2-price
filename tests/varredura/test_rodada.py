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
from tf2price.varredura.rodada import ESPACO_EXTRA_S, QUERY, executar_rodada

T0 = db.agora()


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
    """Busca falsa: fatia a lista inteira de 10 em 10, como a Steam real."""

    def __init__(self, resultados, erro_no_start=None, contador=None):
        self.resultados = list(resultados)
        self.erro_no_start = erro_no_start
        self.contador = contador
        self.chamadas = []
        self.emprestadas = []

    def search_page(self, start=0, count=100, query=None):
        self.chamadas.append((start, query))
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if start == self.erro_no_start:
            raise SteamLimitando("429")
        return SearchPage(total_count=len(self.resultados),
                          results=self.resultados[start:start + 10])


class _Retratos:
    def __init__(self, paginas, limitar_em=None, quebrar=(), antigo=(), contador=None):
        self.paginas = paginas
        self.limitar_em = limitar_em
        self.quebrar = set(quebrar)
        self.antigo = set(antigo)
        self.contador = contador
        self.calma = False
        self.pedidos = []
        self.emprestadas = []

    def em_calma(self):
        return self.calma

    def acalmar(self):
        self.calma = True

    def obter(self, engine, hash_name, usd_to_brl, quando, forcar=False):
        assert forcar
        self.pedidos.append(hash_name)
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if hash_name == self.limitar_em:
            self.calma = True
            return Leitura(None, None, True)
        if hash_name in self.quebrar:
            raise PageStructureError("pagina mudou")
        if hash_name in self.antigo:
            return Leitura(self.paginas[hash_name], quando - timedelta(minutes=1), False)
        return Leitura(self.paginas[hash_name], quando, False)


def _cotacao(valor=SimpleNamespace(usd_to_brl=5.0)):
    return SimpleNamespace(obter=lambda engine: valor)


def _rodar(engine, steam, retratos, quando=T0, cotacao=None, dormir=None):
    return executar_rodada(
        engine, steam=steam, retratos=retratos, cotacao=cotacao or _cotacao(),
        agora=lambda: quando, dormir=dormir or (lambda s: None), aceitar=_aceitar,
    )


def _listagens(engine):
    with engine.begin() as conn:
        return {(l.hash_name, l.listing_id) for l in repo.listar_listagens(conn)}


PAGINAS = {
    "Unusual A": _pagina("Unusual A", ("a1", 500, "Burning Flames"), ("a2", 900, "Sunbeams")),
    "Unusual B": _pagina("Unusual B", ("b1", 700, "Burning Flames")),
}


def test_primeira_rodada_le_a_fundo_so_os_cosmeticos_e_pagina_a_busca(engine):
    # 12 resultados: exige duas páginas da busca (start 0 e 10).
    extras = [_r(f"Unusual Taunt: {i}") for i in range(10)]
    steam = _Steam([_r("Unusual A", n=2), *extras, _r("Unusual B")])
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, steam, retratos)

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

    # PADRAO: 24 h de idade máxima da leitura funda.
    _rodar(engine, _Steam([_r("Unusual A")]), retratos, quando=T0 + timedelta(hours=25))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_substitui_as_listagens_do_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A", n=2)]), _Retratos(PAGINAS))
    vendida = {"Unusual A": _pagina("Unusual A", ("a2", 900, "Sunbeams"))}

    _rodar(engine, _Steam([_r("Unusual A", n=1)]), _Retratos(vendida),
           quando=T0 + timedelta(hours=1))

    assert _listagens(engine) == {("Unusual A", "a2")}


def test_429_na_leitura_funda_para_a_rodada_sem_apagar_nada(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    antes = _listagens(engine)
    retratos = _Retratos(PAGINAS, limitar_em="Unusual A")

    resumo = _rodar(engine, _Steam([_r("Unusual A", usd=1), _r("Unusual B", usd=1)]),
                    retratos, quando=T0 + timedelta(hours=1))

    assert resumo.motivo == "429"
    assert retratos.pedidos == ["Unusual A"]  # B nem foi pedido
    assert _listagens(engine) == antes
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "429"


def test_429_na_busca_liga_a_calma_do_retrato_e_para(engine):
    retratos = _Retratos(PAGINAS)
    steam = _Steam([_r("Unusual A")] + [_r(f"Unusual Taunt: {i}") for i in range(15)],
                   erro_no_start=10)

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "429"
    assert retratos.calma
    assert retratos.pedidos == []  # a funda não começa depois de uma rasa interrompida


def test_assinatura_mudada_sobrevive_ao_429_na_funda_e_e_relida_depois(engine):
    # Rodada 1: assinatura original de A e B.
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    # Rodada 2: as duas assinaturas mudam, mas o 429 na primeira leitura
    # funda (A) para a rodada antes de B ser lido.
    resumo2 = _rodar(
        engine,
        _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
        _Retratos(PAGINAS, limitar_em="Unusual A"),
        quando=T0 + timedelta(hours=1),
    )
    assert resumo2.motivo == "429"

    # Rodada 3: as MESMAS assinaturas mudadas, com um retrato limpo (sem
    # 429). A mudança de assinatura da rodada 2 não pode ter se perdido: os
    # dois nomes têm que ser lidos a fundo de novo.
    retratos3 = _Retratos(PAGINAS)
    resumo3 = _rodar(
        engine,
        _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
        retratos3,
        quando=T0 + timedelta(hours=2),
    )

    assert retratos3.pedidos == ["Unusual A", "Unusual B"]
    assert resumo3.fundas_feitas == 2


def test_assinatura_mudada_sobrevive_a_falha_na_funda_e_e_relida_depois(engine):
    # Rodada 1: assinatura original de A e B.
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    # Rodada 2: as duas assinaturas mudam, mas a leitura funda de A quebra
    # (PageStructureError). A rodada segue e conta a falha, sem 429.
    resumo2 = _rodar(
        engine,
        _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
        _Retratos(PAGINAS, quebrar={"Unusual A"}),
        quando=T0 + timedelta(hours=1),
    )
    assert (resumo2.falhas, resumo2.motivo) == (1, "ok")

    # Rodada 3: as MESMAS assinaturas mudadas. A funda que falhou em A não
    # pode ter se perdido: só A precisa ser lido a fundo de novo (B já foi
    # lido com sucesso na rodada 2, dentro do prazo).
    retratos3 = _Retratos(PAGINAS)
    _rodar(
        engine,
        _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
        retratos3,
        quando=T0 + timedelta(hours=2),
    )

    assert retratos3.pedidos == ["Unusual A"]


def test_nome_quebrado_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, quebrar={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_retrato_antigo_nao_substitui_listagens_nem_marca_funda(engine):
    retratos = _Retratos(PAGINAS, antigo={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A")]), retratos)

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


def test_sem_cotacao_a_rodada_para_com_erro_sem_ir_a_steam(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), cotacao=_cotacao(None))

    assert resumo.motivo == "erro"
    assert steam.chamadas == []


def test_espaco_extra_antes_de_cada_requisicao(engine):
    esperas = []

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS),
           dormir=esperas.append)

    # 1 página da busca + 2 leituras fundas
    assert esperas == [ESPACO_EXTRA_S] * 3


def test_estourar_o_teto_de_paginas_rasas_conta_como_erro(engine, monkeypatch):
    monkeypatch.setattr(rodada_mod, "MAX_PAGINAS_RASAS", 1)
    # 15 resultados = 2 páginas de busca; o teto de 1 impede alcançar a
    # segunda, então a rodada nunca vê o mercado inteiro.
    resultados = [_r(f"Unusual {i}") for i in range(15)]
    steam = _Steam(resultados)
    paginas = {f"Unusual {i}": _pagina(f"Unusual {i}", (f"L{i}", 500, "Burning Flames"))
              for i in range(15)}
    retratos = _Retratos(paginas)

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "erro"
    assert len(steam.chamadas) == 1
    assert retratos.pedidos == []  # o teto para antes da passada funda


def test_nenhuma_conexao_emprestada_durante_as_requisicoes(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    steam = _Steam([_r("Unusual A"), _r("Unusual B")], contador=contador)
    retratos = _Retratos(PAGINAS, contador=contador)

    _rodar(engine, steam, retratos)

    assert steam.emprestadas == [0]
    assert retratos.emprestadas == [0, 0]
