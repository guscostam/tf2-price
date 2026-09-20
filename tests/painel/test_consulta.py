from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app
from tf2price.painel.consulta import Contexto, Cotacao, PageCache
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam_page import PageStructureError

from .conftest import (
    CHAVE,
    NOME,
    _contexto,
    _CotacaoFalsa,
    _IndiceFalso,
    _pagina,
    _PaginasFalsas,
    _SteamFalso,
    cliente_logado,
)


@pytest.fixture
def cliente(engine):
    return cliente_logado(engine, _contexto())


# --- rotas ---------------------------------------------------------------


def test_raiz_serve_o_formulario(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "form" in r.text.lower()


def test_busca_lista_os_nomes(cliente):
    r = cliente.get("/buscar", params={"q": "Chairholder"})
    assert r.status_code == 200
    assert NOME in r.text


def test_busca_vazia_nao_chama_a_steam(cliente):
    cliente.get("/buscar", params={"q": "  "})
    assert cliente.ctx.steam.chamadas == 0


def test_efeitos_lista_os_quatro_a_venda(cliente):
    r = cliente.get("/efeitos", params={"nome": NOME})
    assert r.status_code == 200
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text


def test_analise_mostra_preco_e_oferta(cliente):
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code == 200
    assert "180,44" in r.text        # listagem mais barata do efeito
    assert "106,31" in r.text        # melhor oferta de compra


def test_analise_de_efeito_sem_listagem_avisa(cliente):
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Burning Flames"})
    assert r.status_code == 200
    assert "Burning Flames" in r.text


# --- cache ---------------------------------------------------------------


def test_efeitos_e_analise_do_mesmo_item_buscam_a_pagina_uma_vez(cliente):
    cliente.get("/efeitos", params={"nome": NOME})
    cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert cliente.ctx.paginas.chamadas == 1


def test_cache_expira_pelo_relogio_injetado():
    agora = {"t": 0.0}
    cache = PageCache(ttl_s=10.0, clock=lambda: agora["t"])
    cache.put(NOME, _pagina())

    agora["t"] = 9.0
    assert cache.get(NOME) is not None

    agora["t"] = 11.0
    assert cache.get(NOME) is None


# --- falha de estrutura --------------------------------------------------


def test_mudanca_na_valve_vira_mensagem_e_nao_traceback(engine):
    ctx = _contexto(paginas=_PaginasFalsas(erro=PageStructureError("renderContext sumiu")))
    cliente = cliente_logado(engine, ctx)

    r = cliente.get("/efeitos", params={"nome": NOME})

    assert r.status_code == 200
    assert "renderContext sumiu" in r.text


# --- taxa de conversão ---------------------------------------------------


def test_contexto_carrega_a_taxa_e_a_repassa_para_a_pagina(engine):
    """A página da Steam alterna entre dólar e real; sem a taxa ela é lida errado."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas, usd_to_brl=5.15)
    cliente = cliente_logado(engine, ctx)

    cliente.get("/efeitos", params={"nome": NOME})

    assert ctx.cotacao.obter().usd_to_brl == 5.15
    assert paginas.taxas == [5.15]


def test_contexto_exige_a_cotacao_explicitamente():
    """Sem valor padrão: um padrão deixa a conversão esquecível no chamador."""
    with pytest.raises(TypeError):
        Contexto(
            steam=_SteamFalso(),
            paginas=_PaginasFalsas(_pagina()),
            indice=_IndiceFalso(
                PriceIndex.from_payload({"response": {"items": {}}}, key_in_refined=64.11)
            ),
        )


def test_busca_mantem_a_dupla_qualidade(engine):
    """`Strange Unusual ...` são 28 de 100 nomes da busca real, e os mais caros.

    O filtro antigo (`startswith("Unusual ")`) descartava todos eles.
    """
    dupla = "Strange Unusual Bonk Boy"
    ctx = _contexto(steam=_SteamFalso(nomes=(NOME, dupla, "Strange Scattergun")))
    cliente = cliente_logado(engine, ctx)

    r = cliente.get("/buscar", params={"q": "Veil"})
    assert dupla in r.text
    assert "Strange Scattergun" not in r.text


def test_busca_descarta_o_unusualifier(engine):
    """A ferramenta aplica um efeito; não tem um. Não há o que analisar nela."""
    ctx = _contexto(steam=_SteamFalso(nomes=(NOME, f"{NOME} Unusualifier")))
    cliente = cliente_logado(engine, ctx)

    r = cliente.get("/buscar", params={"q": "Chairholder"})
    assert "Unusualifier" not in r.text
    assert NOME in r.text


# --- a tela: carimbo e limpeza de estado ---------------------------------

def _indice_com_preco(idade_dias: int) -> PriceIndex:
    """Índice onde Deep Dive (id 3229 no mapa real) tem preço com essa idade."""
    agora = int(time.time())
    return PriceIndex.from_payload(
        {"response": {"items": {"Taunt: Chairholder": {"prices": {"5": {"Tradable": {
            "Craftable": {"3229": {
                "currency": "keys", "value": 20.0,
                "last_update": agora - idade_dias * 86400,
            }}
        }}}}}}},
        key_in_refined=64.11,
    )


def _texto_da_analise(engine, idade_dias: int) -> str:
    ctx = _contexto(indice=_indice_com_preco(idade_dias))
    cliente = cliente_logado(engine, ctx)
    return cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text


@pytest.mark.parametrize(
    "idade, classe, palavra",
    [
        (5, 'class="carimbo carimbo-fresco"', "fresco"),     # dentro do mês
        (200, 'class="carimbo "', "dias atrás"),             # meio-termo
        (900, 'class="carimbo carimbo-vencido"', "vencido"),  # o caso do Bonk Boy
    ],
)
def test_o_carimbo_reflete_a_idade_do_preco(engine, idade, classe, palavra):
    texto = _texto_da_analise(engine, idade)
    assert classe in texto
    assert palavra in texto
    # A asserção da classe sozinha é fraca: "carimbo " casa com todos os
    # estados. As outras duas variantes têm que estar ausentes.
    outras = {"carimbo-fresco", "carimbo-vencido", "carimbo-ausente"} - set(
        c for c in ("carimbo-fresco", "carimbo-vencido") if c in classe
    )
    for outra in outras:
        assert outra not in texto


def test_carimbo_de_ausencia_quando_a_bptf_nao_precifica(cliente):
    """O índice padrão do teste é vazio: nenhum efeito tem preço."""
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert "carimbo-ausente" in r.text
    assert "sem avaliação" in r.text


def test_busca_nova_apaga_efeito_e_avaliacao(cliente):
    """Sem isto, a avaliação do item anterior fica na tela sob outro item."""
    r = cliente.get("/buscar", params={"q": "Chairholder"})
    assert r.text.count('hx-swap-oob="true"') == 2
    assert 'id="efeitos"' in r.text and 'id="analise"' in r.text


def test_trocar_de_item_apaga_a_avaliacao(cliente):
    r = cliente.get("/efeitos", params={"nome": NOME})
    assert 'id="analise"' in r.text and 'hx-swap-oob="true"' in r.text


def test_a_cotacao_da_chave_aparece_no_timbre(cliente):
    """Os valores em chaves não significam nada sem o preço que os converteu."""
    assert str(CHAVE) in cliente.get("/").text


def test_analise_sem_indice_nao_mente_sobre_a_bptf(engine):
    ctx = _contexto()
    ctx.indice = _IndiceFalso(None)
    cliente = cliente_logado(engine, ctx)
    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"})
    assert "ainda não carregou" in r.text


def test_sem_cotacao_a_tela_diz_e_nao_quebra(engine):
    """A Steam limitando na subida nao pode derrubar o painel inteiro."""
    ctx = _contexto()
    ctx.cotacao = _CotacaoFalsa(None)
    cliente = cliente_logado(engine, ctx)

    assert "indisponível" in cliente.get("/").text
    assert "ainda não carregou" in cliente.get(
        "/analise", params={"nome": NOME, "efeito": "Deep Dive"}
    ).text


def test_a_consulta_exige_sessao(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    for caminho in ("/", "/buscar", "/efeitos", "/analise"):
        assert cliente.get(caminho, params={"q": "x", "nome": "x", "efeito": "x"}).status_code in (303, 401)
