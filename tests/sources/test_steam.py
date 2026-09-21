from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter, SteamLimitando
from tf2price.sources.steam import (
    CALMA_APOS_429_S,
    CURRENCY_USD,
    SteamClient,
    parse_listings,
    parse_price_text,
    parse_search_page,
    parse_usd_price_text,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# A busca responde em DÓLAR (currency é ignorado lá), então todo teste do
# parser precisa de uma taxa explícita. 5,0 é escolhida só para a conta
# ficar conferível de olho: 2214 centavos de dólar -> 11070 centavos de real.
TAXA_REDONDA = 5.0

# Resposta do priceoverview em USD usada pelo transporte de teste. A chave
# em BRL vale R$ 22,14 (steam_priceoverview.json) e aqui US$ 3,69, então a
# taxa derivada é 2214/369 = 6,0 exatos — a ordem de grandeza medida na API
# real é ~5,4, e o valor exato só existe para a conta fechar sem resíduo.
PRICEOVERVIEW_USD = {
    "success": True,
    "lowest_price": "$3.69",
    "volume": "6,482",
    "median_price": "$3.75",
}
TAXA_DO_TRANSPORTE = 6.0


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- parsers puros -------------------------------------------------------


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("R$ 22,14", 2214),
        ("R$ 1.234,50", 123450),
        ("R$ 0,99", 99),
        ("R$ 12.345.678,90", 1234567890),
    ],
)
def test_parse_price_text(texto, centavos):
    assert parse_price_text(texto) == Brl.from_cents(centavos)


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("R$ 1.234", 123400),
        ("R$ 22", 2200),
    ],
)
def test_parse_price_text_formas_sem_centavos(texto, centavos):
    assert parse_price_text(texto) == Brl.from_cents(centavos)


def test_parse_price_text_rejeita_formato_en_us():
    # "22.14" tem um ponto seguido de só 2 dígitos: não é pt-BR (seria
    # ambíguo com milhar). Interpretar como pt-BR daria 2214,00 — 100x
    # o valor real. É melhor falhar alto do que silenciosamente errado.
    with pytest.raises(ValueError):
        parse_price_text("R$ 22.14")


def test_parse_price_text_rejeita_grupo_de_milhar_malformado():
    # "1.23,45": o grupo antes da vírgula não tem exatamente 3 dígitos,
    # então não é um formato pt-BR inequívoco.
    with pytest.raises(ValueError):
        parse_price_text("R$ 1.23,45")


@pytest.mark.parametrize(
    "texto,centavos",
    [
        ("$22.14", 2214),
        ("$1,880.07 USD", 188007),
        ("$0.99", 99),
        ("$3.69", 369),
        ("$12", 1200),
        ("$1,234", 123400),
    ],
)
def test_parse_usd_price_text(texto, centavos):
    assert parse_usd_price_text(texto) == centavos


def test_parse_usd_price_text_rejeita_formato_ptbr():
    # "R$ 22,14" chegando aqui significaria que o cache do priceoverview
    # devolveu o payload em real para o pedido em dólar. Falhar alto é o
    # ponto: uma taxa calculada sobre a moeda errada sai 1,0 e reintroduz
    # exatamente o bug que esta correção mata.
    with pytest.raises(ValueError):
        parse_usd_price_text("R$ 22,14")


def test_parse_search_page_le_total_e_resultados():
    page = parse_search_page(_fixture("steam_search_page.json"), TAXA_REDONDA)
    assert page.total_count == 21543
    assert len(page.results) == 3


def test_parse_search_page_converte_sell_price_de_centavos():
    # sell_price vem em centavos de DÓLAR: 2214 * 5,0 = 11070 centavos de
    # real. Ler 2214 como centavos de real era o bug — dava R$ 22,14 para
    # um item de R$ 110,70.
    page = parse_search_page(_fixture("steam_search_page.json"), TAXA_REDONDA)
    chave = page.results[0]
    assert chave.hash_name == "Mann Co. Supply Crate Key"
    assert chave.lowest_price == Brl.from_cents(11070)
    assert chave.sell_listings == 4821


def test_parse_search_page_converte_todos_os_resultados():
    page = parse_search_page(_fixture("steam_search_page.json"), TAXA_REDONDA)
    assert [r.lowest_price for r in page.results] == [
        Brl.from_cents(11070),  # 2214 * 5
        Brl.from_cents(445000),  # 89000 * 5
        Brl.from_cents(79950),  # 15990 * 5
    ]


def test_parse_search_page_taxa_1_nao_altera_o_valor():
    # Guarda contra a conversão ser pulada em silêncio (ou aplicada duas
    # vezes): com taxa 1,0 o número tem que sair idêntico ao da resposta.
    page = parse_search_page(_fixture("steam_search_page.json"), 1.0)
    assert [r.lowest_price.cents for r in page.results] == [2214, 89000, 15990]


def test_parse_search_page_arredonda_uma_vez_na_conversao():
    payload = {"total_count": 1, "results": [{"hash_name": "X", "sell_listings": 1, "sell_price": 333}]}
    # 333 * 5,4 = 1798,2 -> 1798 centavos, arredondado uma única vez.
    page = parse_search_page(payload, 5.4)
    assert page.results[0].lowest_price == Brl.from_cents(1798)


def test_parse_search_page_sem_resultados():
    page = parse_search_page({"total_count": 0, "results": None}, TAXA_REDONDA)
    assert page.results == []


def test_parse_listings_ignora_listagem_sem_preco_convertido():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    assert len(listings) == 2


def test_parse_listings_soma_preco_e_taxa():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    primeira = next(l for l in listings if l.listing_id == "1111111111111111111")
    assert primeira.total_price == Brl.from_cents(89000)


def test_parse_listings_extrai_efeito_de_unusual():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    primeira = next(l for l in listings if l.listing_id == "1111111111111111111")
    assert primeira.effect == "Burning Flames"
    assert primeira.craftable is True
    assert primeira.spelled is False


def test_parse_listings_detecta_nao_craftavel_e_spell():
    listings = parse_listings(_fixture("steam_listings_unusual.json"))
    segunda = next(l for l in listings if l.listing_id == "2222222222222222222")
    assert segunda.effect == "Green Confetti"
    assert segunda.craftable is False
    assert segunda.spelled is True
    assert segunda.total_price == Brl.from_cents(133500)


def test_parse_listings_pula_quando_asset_nao_encontrado_em_nenhum_contexto():
    # asset.id "zzz9" aparece em listinginfo mas não existe em assets[440][*].
    # Craftability é desconhecida nesse caso, então a listagem deve ser
    # pulada em vez de assumida craftável por padrão.
    payload = {
        "listinginfo": {
            "9999999999999999999": {
                "listingid": "9999999999999999999",
                "converted_price": 50000,
                "converted_fee": 5600,
                "asset": {"currency": 0, "appid": 440, "contextid": "2", "id": "zzz9", "amount": "1"},
            }
        },
        "assets": {
            "440": {
                "2": {
                    "outro_id": {
                        "appid": 440,
                        "contextid": "2",
                        "id": "outro_id",
                        "descriptions": [{"value": "Level 10 Hat"}],
                    }
                }
            }
        },
    }

    listings = parse_listings(payload)

    assert listings == []


def test_parse_listings_asset_presente_sem_linha_de_nao_craftavel_e_craftavel():
    # Guarda de regressão: um asset presente cujas descrições simplesmente
    # não mencionam "( Not Usable in Crafting )" continua craftável e não
    # deve ser pulado pela correção do caso "asset ausente".
    payload = {
        "listinginfo": {
            "8888888888888888888": {
                "listingid": "8888888888888888888",
                "converted_price": 30000,
                "converted_fee": 3300,
                "asset": {"currency": 0, "appid": 440, "contextid": "2", "id": "www1", "amount": "1"},
            }
        },
        "assets": {
            "440": {
                "2": {
                    "www1": {
                        "appid": 440,
                        "contextid": "2",
                        "id": "www1",
                        "market_hash_name": "Team Captain",
                        "descriptions": [{"value": "Level 10 Hat"}],
                    }
                }
            }
        },
    }

    listings = parse_listings(payload)

    assert len(listings) == 1
    assert listings[0].craftable is True


# --- cliente HTTP --------------------------------------------------------


def _e_priceoverview(request: httpx.Request) -> bool:
    return "priceoverview" in request.url.path


def _priceoverview_response(request: httpx.Request) -> httpx.Response:
    """Serve o priceoverview POR MOEDA.

    search_page passou a derivar a taxa USD->BRL de duas chamadas a este
    endpoint, então o transporte de teste precisa distinguir currency=7 de
    currency=1. Devolver o payload em real para o pedido em dólar faria
    parse_usd_price_text estourar — que é o comportamento desejado, e é
    por isso que o transporte não pode "ajudar" respondendo igual aos dois.
    """
    if request.url.params.get("currency") == str(CURRENCY_USD):
        return httpx.Response(200, json=PRICEOVERVIEW_USD)
    return httpx.Response(200, json=_fixture("steam_priceoverview.json"))


def _cliente(payload: dict, capturadas: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capturadas is not None:
            capturadas.append(request)
        if _e_priceoverview(request):
            return _priceoverview_response(request)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_page_envia_currency_brl_e_idioma_ingles():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)

    params = capturadas[0].url.params
    assert params["currency"] == "7"
    assert params["l"] == "english"
    assert params["appid"] == "440"
    assert params["norender"] == "1"


def test_listings_escapa_o_nome_na_url():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_listings_unusual.json"), capturadas),
    )

    client.listings("Unusual Team Captain")

    assert "Unusual%20Team%20Captain" in str(capturadas[0].url)


def test_key_price_usa_a_listagem_mais_barata():
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_priceoverview.json")),
    )
    assert client.key_price() == Brl.from_float(22.14)


def test_key_median_price_le_a_mediana():
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_priceoverview.json")),
    )
    assert client.key_median_price() == Brl.from_float(22.49)


def test_429_e_repetido_com_backoff_e_registrado():
    respostas = [429, 429, 200]
    payload = _fixture("steam_search_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_priceoverview(request):
            # A taxa USD->BRL é buscada depois da página; ela não consome a
            # sequência de respostas que este teste está exercitando.
            return _priceoverview_response(request)
        status = respostas.pop(0)
        if status == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, json=payload)

    limiter = RateLimiter(min_interval_s=0.0)
    client = SteamClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,  # não dorme de verdade no teste
        max_retries=2,
    )

    page = client.search_page(start=0)

    assert page.total_count == 21543
    assert limiter.throttled == 2
    assert limiter.first_429_after == 1


def test_429_persistente_levanta_steam_limitando():
    """Desistir com 429 tem tipo próprio, para a calma e a tela poderem
    distinguir "o IP passou do limite" de "a Steam não respondeu"."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(SteamLimitando, match="Steam is rate limiting this server"):
        client.search_page(start=0)


def test_5xx_persistente_nao_e_steam_limitando():
    """A distinção que o tipo existe para fazer: a Steam falhando não é o IP
    barrado, e chamar os dois de limitação ligaria a calma à toa."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="Steam did not respond after backoff") as capturado:
        client.search_page(start=0)
    assert not isinstance(capturado.value, SteamLimitando)


def test_falha_5xx_persistente_para_apos_uma_retentativa():
    tentativas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tentativas["n"] += 1
        return httpx.Response(500, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError):
        client.search_page(start=0)

    assert tentativas["n"] == 2


class _RelogioFalso:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


def test_depois_de_desistir_com_429_a_calma_recusa_sem_ir_a_rede():
    """O conserto do `/buscar 499 3648ms` medido no Railway: com o IP
    limitado, cada busca pagava a própria escada de 31-62s. Agora a primeira
    paga, liga a calma, e as seguintes falham na hora — sem uma requisição."""
    pedidos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos["n"] += 1
        return httpx.Response(429, text="")

    relogio = _RelogioFalso()
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        relogio=relogio,
    )

    with pytest.raises(SteamLimitando):
        client.search_page(start=0)
    gastos = pedidos["n"]
    assert gastos > 1, "a escada nem subiu; o teste não está medindo o que diz"

    with pytest.raises(SteamLimitando, match="try again in a few minutes"):
        client.search_page(start=0)
    assert pedidos["n"] == gastos, "a calma deixou passar requisição"

    # Passada a calma, volta a tentar.
    relogio.agora += CALMA_APOS_429_S
    with pytest.raises(SteamLimitando):
        client.search_page(start=0)
    assert pedidos["n"] > gastos


def test_429_que_termina_em_sucesso_nao_liga_a_calma():
    """Uma sequência 429, 429, 200 acabou bem: ligar a calma aí puniria a
    chamada seguinte por um estrangulamento que já passou."""
    respostas = [429, 429, 200, 200]
    payload = _fixture("steam_search_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_priceoverview(request):
            return _priceoverview_response(request)
        status = respostas.pop(0)
        if status == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, json=payload)

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        max_retries=2,
    )

    assert client.search_page(start=0).total_count == 21543
    # A segunda chamada passa: se a calma tivesse ligado, isto levantaria.
    assert client.search_page(start=0).total_count == 21543


def test_5xx_e_repetido_e_nao_conta_como_throttle():
    # 5xx é a Steam falhando, não o IP sendo barrado. Repetir é certo;
    # contar como 429 corromperia a medição de quantas requisições o IP
    # aguenta antes do primeiro throttle, que é entregável do spike.
    respostas = [500, 200]
    payload = _fixture("steam_search_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_priceoverview(request):
            return _priceoverview_response(request)
        status = respostas.pop(0)
        if status == 500:
            return httpx.Response(500, text="")
        return httpx.Response(200, json=payload)

    limiter = RateLimiter(min_interval_s=0.0)
    client = SteamClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    page = client.search_page(start=0)

    assert page.total_count == 21543
    assert limiter.throttled == 0
    assert limiter.first_429_after is None


def test_timeout_e_repetido():
    # Um timeout estoura antes de existir resposta: sem retry, ele derrubaria
    # uma passada de ~11 minutos na primeira oscilação de rede.
    tentativas = {"n": 0}
    payload = _fixture("steam_search_page.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if _e_priceoverview(request):
            # Só as tentativas da própria busca são contadas aqui.
            return _priceoverview_response(request)
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise httpx.ReadTimeout("tempo esgotado", request=request)
        return httpx.Response(200, json=payload)

    limiter = RateLimiter(min_interval_s=0.0)
    client = SteamClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    page = client.search_page(start=0)

    assert page.total_count == 21543
    assert tentativas["n"] == 2
    assert limiter.throttled == 0


def test_404_falha_na_primeira_tentativa():
    # 4xx que não é 429 significa pedido errado. Repetir um pedido errado
    # só queima orçamento de requisições.
    tentativas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        tentativas["n"] += 1
        return httpx.Response(404, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.search_page(start=0)

    assert tentativas["n"] == 1


def test_search_page_envia_query_quando_informado():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0, query="Unusual")

    assert capturadas[0].url.params["query"] == "Unusual"


def test_search_page_sem_query_nao_envia_o_parametro():
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)

    assert "query" not in capturadas[0].url.params


def test_search_page_query_vazio_nao_envia_o_parametro():
    # Vazio não é o mesmo que ausente: a forma ausente é a que varre o
    # catálogo inteiro, então "" precisa se comportar como None, não como
    # um filtro que casa com tudo.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0, query="")

    assert "query" not in capturadas[0].url.params


def test_search_page_ordena_por_preco_decrescente():
    # Sem sort explícito a Steam ordena por popularidade, que muda durante a
    # varredura: itens migram entre páginas e viram duplicata ou buraco.
    #
    # Decrescente por preço, e não alfabética, porque a varredura pode não
    # terminar: em ordem de nome os Unusual caem na letra U e uma execução
    # truncada não vê nenhum. Por preço, os caros vêm primeiro.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)

    params = capturadas[0].url.params
    assert params["sort_column"] == "price"
    assert params["sort_dir"] == "desc"


def test_preco_da_chave_usa_uma_unica_requisicao():
    # Dois GETs seriam duas fotos de um mercado em movimento: o menor preço
    # de um instante e a mediana de outro.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_priceoverview.json"), capturadas),
    )

    assert client.key_price() == Brl.from_float(22.14)
    assert client.key_median_price() == Brl.from_float(22.49)
    assert len(capturadas) == 1


def test_cache_do_priceoverview_nao_vaza_entre_instancias():
    capturadas: list[httpx.Request] = []
    payload = _fixture("steam_priceoverview.json")

    primeiro = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(payload, capturadas),
    )
    primeiro.key_price()

    segundo = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(payload, capturadas),
    )
    segundo.key_price()

    assert len(capturadas) == 2


def test_search_page_converte_o_preco_em_dolar_para_real():
    # A busca responde em dólar e ignora currency=7 (medido em 2026-09-19).
    # A chave da fixture sai por 2214 centavos de DÓLAR; com a taxa de 6,0
    # derivada do priceoverview, o preço em real é 13284 centavos.
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json")),
    )

    page = client.search_page(start=0)

    assert page.results[0].lowest_price == Brl.from_cents(round(2214 * TAXA_DO_TRANSPORTE))
    assert page.results[0].lowest_price == Brl.from_cents(13284)


def test_taxa_e_a_chave_em_brl_dividida_pela_chave_em_usd():
    # R$ 22,14 / US$ 3,69 = 6,0. O teste amarra a definição da taxa: se ela
    # virasse USD/BRL, ou uma cotação externa, o número mudaria.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    page = client.search_page(start=0)

    brl_cents = parse_price_text(_fixture("steam_priceoverview.json")["lowest_price"]).cents
    usd_cents = parse_usd_price_text(PRICEOVERVIEW_USD["lowest_price"])
    taxa = brl_cents / usd_cents
    assert taxa == 6.0
    assert page.results[0].lowest_price == Brl.from_cents(round(2214 * taxa))

    moedas = {
        r.url.params["currency"] for r in capturadas if "priceoverview" in r.url.path
    }
    assert moedas == {"7", "1"}


def test_taxa_e_calculada_uma_vez_por_instancia():
    # Duas páginas não podem custar dois pares de priceoverview: a taxa é
    # calculada uma vez e guardada na instância.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)
    client.search_page(start=100)

    priceoverviews = [r for r in capturadas if "priceoverview" in r.url.path]
    assert len(priceoverviews) == 2


def test_cache_do_priceoverview_e_por_moeda():
    # A chave em real continua vindo em reais depois de a taxa ter pedido a
    # mesma chave em dólar. Um cache de payload único devolveria o dólar
    # aqui — ou o real para o pedido em dólar — e a taxa sairia 1,0.
    capturadas: list[httpx.Request] = []
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_search_page.json"), capturadas),
    )

    client.search_page(start=0)

    assert client.key_price() == Brl.from_float(22.14)
    assert client.key_median_price() == Brl.from_float(22.49)
    # O pedido em BRL da taxa já preencheu o cache: nenhuma requisição nova.
    priceoverviews = [r for r in capturadas if "priceoverview" in r.url.path]
    assert len(priceoverviews) == 2


def test_taxa_nao_vaza_entre_instancias():
    capturadas: list[httpx.Request] = []
    payload = _fixture("steam_search_page.json")

    primeiro = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(payload, capturadas),
    )
    primeiro.search_page(start=0)

    segundo = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(payload, capturadas),
    )
    segundo.search_page(start=0)

    priceoverviews = [r for r in capturadas if "priceoverview" in r.url.path]
    assert len(priceoverviews) == 4


def test_listings_levanta_runtime_error_quando_a_steam_devolve_html():
    # Medido em 2026-09-19: o endpoint passou a devolver a página HTML
    # inteira com status 200. O JSONDecodeError que vazava daqui não é
    # RuntimeError nem httpx.HTTPError, então o except por alvo de quem
    # chama não o pegava e o estágio profundo inteiro morria no alvo 1/27.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<!DOCTYPE html><html><head><title>Steam Community Market</title></head></html>",
            headers={"content-type": "text/html; charset=UTF-8"},
        )

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="Steam listings endpoint did not return JSON"):
        client.listings("Unusual Team Captain")


def test_listings_com_html_nao_deixa_jsondecodeerror_escapar():
    # O contrato com quem chama é (RuntimeError, httpx.HTTPError). Qualquer
    # outra exceção derruba o estágio inteiro.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    try:
        client.listings("Unusual Team Captain")
    except (RuntimeError, httpx.HTTPError) as error:
        assert "Steam listings endpoint did not return JSON" in str(error)
        # 380 KB de corpo não entram na mensagem de erro.
        assert len(str(error)) < 400
    else:
        raise AssertionError("listings deveria ter falhado com HTML")


def test_listings_com_json_continua_parseando():
    # Guarda de regressão da detecção: o caminho feliz não pode ser
    # sacrificado pela checagem de content-type.
    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=_cliente(_fixture("steam_listings_unusual.json")),
    )

    listings = client.listings("Unusual Team Captain")

    assert len(listings) == 2
    assert {l.effect for l in listings} == {"Burning Flames", "Green Confetti"}
