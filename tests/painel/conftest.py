from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import servico
from tf2price.domain.money import Brl
from tf2price.painel.app import criar_app
from tf2price.painel.consulta import Contexto, Cotacao
from tf2price.preco.retrato import Leitura
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import parse_item_page

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOME = "Unusual Taunt: Chairholder"
CHAVE = Brl.from_float(11.73)
SENHA = "uma senha longa"


def _pagina():
    html = (FIXTURES / "steam_listing_page.html").read_text(encoding="utf-8")
    # Taxa 1.0: a fixture declara BRL e nenhum teste daqui é sobre moeda.
    return parse_item_page(html, NOME, 1.0)


class _SteamFalso:
    def __init__(self, nomes=(NOME, "Unusual Team Captain")):
        self.nomes = nomes
        self.chamadas = 0

    def search_page(self, start=0, count=100, query=None):
        self.chamadas += 1
        return SearchPage(
            total_count=len(self.nomes),
            results=[
                SearchResult(hash_name=n, lowest_price=Brl.from_cents(1000), sell_listings=1)
                for n in self.nomes
            ],
        )


class _IndiceFalso:
    def __init__(self, indice=None):
        self.indice = indice

    def obter(self):
        return self.indice


class _CotacaoFalsa:
    def __init__(self, cotacao):
        self.cotacao = cotacao

    def obter(self):
        return self.cotacao


class _PaginasFalsas:
    def __init__(self, pagina=None, erro=None):
        self._pagina = pagina
        self._erro = erro
        self.chamadas = 0
        self.taxas: list[float] = []

    def item_page(self, hash_name, usd_to_brl):
        self.chamadas += 1
        self.taxas.append(usd_to_brl)
        if self._erro:
            raise self._erro
        return self._pagina


class _RetratosFalsos:
    """Duplo do retrato: busca direto na página falsa, sem validade nem calma.

    Essas regras (validade, piso, calma) já têm teste próprio em
    `tests/preco/test_retrato.py`; aqui só interessa que a rota saiba usar o
    resultado — inclusive deixar passar o erro que `paginas` levantar.

    Recebe uma função que devolve o `paginas` atual, não o objeto direto:
    `test_transacao.py` troca `ctx.paginas` depois de montar o contexto, e a
    busca tem que enxergar a troca, não a página falsa de quando o duplo foi
    criado.
    """

    def __init__(self, obter_paginas):
        self._obter_paginas = obter_paginas

    def obter(self, engine, hash_name, usd_to_brl, quando, forcar=False):
        pagina = self._obter_paginas().item_page(hash_name, usd_to_brl)
        return Leitura(pagina, db.agora(), False)


def _contexto(steam=None, paginas=None, indice=None, usd_to_brl=1.0):
    ctx = Contexto(
        steam=steam or _SteamFalso(),
        paginas=paginas or _PaginasFalsas(_pagina()),
        indice=_IndiceFalso(indice or PriceIndex.from_payload(
            {"response": {"items": {}}}, key_in_refined=64.11
        )),
        cotacao=_CotacaoFalsa(Cotacao(CHAVE, usd_to_brl)),
        retratos=None,
    )
    ctx.retratos = _RetratosFalsos(lambda: ctx.paginas)
    return ctx


def cliente_logado(engine, ctx):
    """TestClient autenticado, com a primeira conta vinda do convite de partida."""
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
        servico.aceitar_convite(
            conn, token, nome="gusco", senha=SENHA, quando=db.agora()
        )
    cliente = TestClient(criar_app(engine, ctx))
    cliente.post("/entrar", data={"nome": "gusco", "senha": SENHA})
    cliente.ctx = ctx
    return cliente
