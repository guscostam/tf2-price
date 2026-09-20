from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tf2price.domain.money import Brl
from tf2price.lookup.app import Contexto, PageCache, criar_app
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import PageStructureError, parse_item_page

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOME = "Unusual Taunt: Chairholder"
CHAVE = Brl.from_float(11.73)


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


def _contexto(steam=None, paginas=None, indice=None, usd_to_brl=1.0):
    return Contexto(
        steam=steam or _SteamFalso(),
        paginas=paginas or _PaginasFalsas(_pagina()),
        index=indice or PriceIndex.from_payload(
            {"response": {"items": {}}}, key_in_refined=64.11
        ),
        key_brl=CHAVE,
        usd_to_brl=usd_to_brl,
        cache=PageCache(),
    )


@pytest.fixture
def cliente():
    ctx = _contexto()
    app = criar_app(ctx)
    cliente = TestClient(app)
    cliente.ctx = ctx
    return cliente


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


def test_mudanca_na_valve_vira_mensagem_e_nao_traceback():
    ctx = _contexto(paginas=_PaginasFalsas(erro=PageStructureError("renderContext sumiu")))
    cliente = TestClient(criar_app(ctx), raise_server_exceptions=False)

    r = cliente.get("/efeitos", params={"nome": NOME})

    assert r.status_code == 200
    assert "renderContext sumiu" in r.text


# --- taxa de conversão ---------------------------------------------------


def test_contexto_carrega_a_taxa_e_a_repassa_para_a_pagina():
    """A página da Steam alterna entre dólar e real; sem a taxa ela é lida errado."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas, usd_to_brl=5.15)
    cliente = TestClient(criar_app(ctx))

    cliente.get("/efeitos", params={"nome": NOME})

    assert ctx.usd_to_brl == 5.15
    assert paginas.taxas == [5.15]


def test_contexto_exige_a_taxa_explicitamente():
    """Sem valor padrão: um padrão deixa a conversão esquecível no chamador."""
    with pytest.raises(TypeError):
        Contexto(
            steam=_SteamFalso(),
            paginas=_PaginasFalsas(_pagina()),
            index=PriceIndex.from_payload({"response": {"items": {}}}, key_in_refined=64.11),
            key_brl=CHAVE,
        )


def test_busca_mantem_a_dupla_qualidade():
    """`Strange Unusual ...` são 28 de 100 nomes da busca real, e os mais caros.

    O filtro antigo (`startswith("Unusual ")`) descartava todos eles.
    """
    dupla = "Strange Unusual Bonk Boy"
    ctx = _contexto(steam=_SteamFalso(nomes=(NOME, dupla, "Strange Scattergun")))
    cliente = TestClient(criar_app(ctx))

    r = cliente.get("/buscar", params={"q": "Veil"})
    assert dupla in r.text
    assert "Strange Scattergun" not in r.text


def test_busca_descarta_o_unusualifier():
    """A ferramenta aplica um efeito; não tem um. Não há o que analisar nela."""
    ctx = _contexto(steam=_SteamFalso(nomes=(NOME, f"{NOME} Unusualifier")))
    cliente = TestClient(criar_app(ctx))

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


def _texto_da_analise(idade_dias: int) -> str:
    ctx = _contexto(indice=_indice_com_preco(idade_dias))
    cliente = TestClient(criar_app(ctx))
    return cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text


@pytest.mark.parametrize(
    "idade, classe, palavra",
    [
        (5, 'class="carimbo carimbo-fresco"', "fresco"),     # dentro do mês
        (200, 'class="carimbo "', "dias atrás"),             # meio-termo
        (900, 'class="carimbo carimbo-vencido"', "vencido"),  # o caso do Bonk Boy
    ],
)
def test_o_carimbo_reflete_a_idade_do_preco(idade, classe, palavra):
    texto = _texto_da_analise(idade)
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
