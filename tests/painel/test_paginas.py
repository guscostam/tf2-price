import json
import threading

from fastapi.testclient import TestClient

from tf2price import db
from tf2price.painel.app import criar_app
from tf2price.painel.consulta import CotacaoSobDemanda, IndiceSobDemanda
from tf2price.preco import repositorio as preco_repo
from tf2price.preco import serial

from .conftest import CHAVE, NOME, _contexto, _pagina, cliente_logado


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


def test_overview_mostra_resumo_real_sem_vereditos(engine):
    cliente = cliente_logado(engine, _contexto())
    resposta = cliente.post(
        "/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"}
    )
    assert resposta.status_code == 200

    texto = cliente.get("/").text

    assert "Overview" in texto
    assert "Exchange rate" in texto
    assert "Case files" in texto
    assert "Recent cases" in texto
    trecho_contagem = texto[texto.index('id="cases-title"') :]
    trecho_contagem = trecho_contagem[: trecho_contagem.index("</section>")]
    assert "<strong>1</strong>" in trecho_contagem
    assert NOME in texto
    assert "Deep Dive" in texto
    for inventado in ("Good Buy", "Fair Price", "Confidence", "Market Index"):
        assert inventado not in texto


def test_sources_explica_os_dois_escopos(engine):
    texto = cliente_logado(engine, _contexto()).get("/sources").text

    assert "THIS EFFECT" in texto
    assert "ALL EFFECTS" in texto
    assert "suggested price" in texto
    assert "not a buy order" in texto
    assert "Refresh" not in texto
    assert "hx-get" not in texto


def test_sources_nao_afirma_online_sem_evidencia(engine):
    contexto = _contexto()
    contexto.indice = _IndiceSemRede()

    texto = cliente_logado(engine, contexto).get("/sources").text

    assert "Online" not in texto
    assert "Awaiting background load" in texto
    assert not contexto.indice.obter_chamado


def test_sources_steam_aguarda_quando_nao_ha_snapshot_salvo(engine):
    cliente = cliente_logado(engine, _contexto())

    texto_sem_casos = cliente.get("/sources").text
    assert "No stored case snapshots yet" in texto_sem_casos
    assert "Known through stored case snapshots" not in texto_sem_casos

    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    texto_sem_snapshot = cliente.get("/sources").text
    assert NOME in texto_sem_snapshot
    assert "No stored case snapshots yet" in texto_sem_snapshot
    assert "Known through stored case snapshots" not in texto_sem_snapshot


def test_sources_steam_confirma_snapshot_real_salvo(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        preco_repo.guardar(
            conn,
            NOME,
            json.dumps(serial.para_dict(_pagina())),
            db.agora(),
        )

    texto = cliente.get("/sources").text
    inicio_steam = texto.index("<h2>Steam Market</h2>")
    trecho_steam = texto[inicio_steam : texto.index("</section>", inicio_steam)]

    assert 'class="status-badge status-badge--ready"' in trecho_steam
    assert "Known through stored case snapshots" in trecho_steam
    assert "No stored case snapshots yet" not in trecho_steam


def test_new_case_preserva_indicador_e_destinos_htmx(engine):
    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/cases/new").text

    assert texto.count('hx-indicator="#case-loading"') == 1
    assert (
        'id="case-workflow" class="case-workflow" '
        'hx-indicator="#case-loading"'
    ) in texto
    assert 'hx-get="/buscar" hx-target="#items"' in texto
    for destino in ("case-loading", "items", "case-files", "effects", "analysis"):
        assert f'id="{destino}"' in texto


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
