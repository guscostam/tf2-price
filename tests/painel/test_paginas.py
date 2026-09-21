import threading

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.painel.app import criar_app
from tf2price.painel.consulta import CotacaoSobDemanda, IndiceSobDemanda

from .conftest import CHAVE, _contexto, cliente_logado


class _IndiceSemRede:
    def __init__(self, valor=None):
        self.valor = valor
        self.obter_chamado = False

    def em_memoria(self):
        return self.valor

    def obter(self):
        self.obter_chamado = True
        raise AssertionError("page routes must not call the network-capable obter()")


def test_indice_pode_ser_lido_sem_disparar_cliente():
    class Cliente:
        def currencies(self):
            raise AssertionError("network called")

    indice = IndiceSobDemanda(Cliente())
    assert indice.em_memoria() is None


def test_paginas_autenticadas_existem(engine):
    cliente = cliente_logado(engine, _contexto())
    for caminho, marcador in (
        ("/", 'data-page="overview"'),
        ("/cases/new", 'data-page="new-case"'),
        ("/cases", 'data-page="case-files"'),
        ("/sources", 'data-page="sources"'),
    ):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200
        assert marcador in resposta.text


def test_renderizacao_inicial_das_paginas_nao_chama_indice(engine):
    contexto = _contexto()
    indice = _IndiceSemRede()
    contexto.indice = indice
    cliente = cliente_logado(engine, contexto)

    for caminho in ("/", "/cases/new", "/cases", "/sources"):
        assert cliente.get(caminho).status_code == 200

    assert not indice.obter_chamado


def test_paginas_nao_esperam_renovacao_da_cotacao(engine):
    class SteamBloqueada:
        def __init__(self):
            self.entrou_na_rede = threading.Event()
            self.liberar_rede = threading.Event()

        def key_price(self):
            self.entrou_na_rede.set()
            assert self.liberar_rede.wait(2)
            return CHAVE

        def usd_to_brl(self):
            return 1.0

    contexto = _contexto()
    cliente = cliente_logado(engine, contexto)
    steam = SteamBloqueada()
    contexto.cotacao = CotacaoSobDemanda(steam)

    renovacao = threading.Thread(
        target=contexto.cotacao.renovar, args=(engine, db.agora())
    )
    renovacao.start()
    assert steam.entrou_na_rede.wait(1)

    respostas = {}
    paginas_terminaram = threading.Event()

    def abrir_paginas():
        for caminho in ("/", "/cases/new", "/cases", "/sources"):
            respostas[caminho] = cliente.get(caminho).status_code
        paginas_terminaram.set()

    leitura = threading.Thread(target=abrir_paginas)
    leitura.start()
    terminaram_antes_da_rede = paginas_terminaram.wait(0.5)
    steam.liberar_rede.set()
    leitura.join(2)
    renovacao.join(2)

    assert terminaram_antes_da_rede, "page routes waited for quote network I/O"
    assert respostas == {
        "/": 200,
        "/cases/new": 200,
        "/cases": 200,
        "/sources": 200,
    }


def test_paginas_novas_exigem_autenticacao(engine):
    cliente = TestClient(criar_app(engine, _contexto()))

    for caminho in ("/cases/new", "/cases", "/sources"):
        resposta = cliente.get(caminho, follow_redirects=False)
        assert resposta.status_code == 303
        assert resposta.headers["location"] == "/entrar"
