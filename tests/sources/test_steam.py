from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import (
    SteamClient,
    parse_listings,
    parse_price_text,
    parse_search_page,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


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


def test_parse_search_page_le_total_e_resultados():
    page = parse_search_page(_fixture("steam_search_page.json"))
    assert page.total_count == 21543
    assert len(page.results) == 3


def test_parse_search_page_converte_sell_price_de_centavos():
    page = parse_search_page(_fixture("steam_search_page.json"))
    chave = page.results[0]
    assert chave.hash_name == "Mann Co. Supply Crate Key"
    assert chave.lowest_price == Brl.from_float(22.14)
    assert chave.sell_listings == 4821


def test_parse_search_page_sem_resultados():
    page = parse_search_page({"total_count": 0, "results": None})
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


def _cliente(payload: dict, capturadas: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capturadas is not None:
            capturadas.append(request)
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
        status = respostas.pop(0)
        if status == 429:
            return httpx.Response(429, text="")
        return httpx.Response(200, json=payload)

    limiter = RateLimiter(min_interval_s=0.0)
    client = SteamClient(
        limiter=limiter,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,  # não dorme de verdade no teste
    )

    page = client.search_page(start=0)

    assert page.total_count == 21543
    assert limiter.throttled == 2
    assert limiter.first_429_after == 1


def test_erro_persistente_levanta():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="")

    client = SteamClient(
        limiter=RateLimiter(min_interval_s=0.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="não respondeu"):
        client.search_page(start=0)
