from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
import time

import httpx
import pytest

from tf2price.sources.classificados import (
    ClassificadosClient,
    ClassificadosLimitando,
    Venda,
    snapshot_para_vendas,
)


SKU = "Massed Flies Team Captain"


def _anuncio(**changes):
    item = {
        "quality": 5,
        "defindex": 378,
        "quantity": 1,
        "attributes": [{"defindex": 134, "float_value": 12}],
    }
    anuncio = {"intent": "sell", "item": item, "currencies": {"keys": 12.5, "metal": 0.11}}
    anuncio.update(changes)
    return anuncio


def _snapshot(*anuncios, sku=SKU):
    return {"appid": 440, "sku": sku, "createdAt": int(time.time()), "listings": list(anuncios)}


def test_parser_aceita_venda_com_efeito_exato_e_decimais():
    assert snapshot_para_vendas(_snapshot(_anuncio()), SKU, 12).vendas == (
        Venda(chaves=Decimal("12.5"), metal=Decimal("0.11")),
    )


def test_parser_aceita_created_at_unix_seconds_observado_na_api():
    assert snapshot_para_vendas(_snapshot(), SKU, 12).vendas == ()


def test_parser_preserva_instante_original_do_snapshot():
    payload = _snapshot()
    payload["createdAt"] = int(time.time()) - 123
    snapshot = snapshot_para_vendas(payload, SKU, 12)
    assert snapshot.criado_em == datetime.fromtimestamp(payload["createdAt"], timezone.utc).replace(tzinfo=None)


def test_parser_aceita_metadados_e_atributos_padrao_observados_na_api():
    item = {
        "quality": 5,
        "defindex": 378,
        "quantity": 1,
        "attributes": [
            {"defindex": 134, "float_value": 12},
            {"defindex": 746, "float_value": 1},
            {"defindex": 292, "float_value": 64},
            {"defindex": 388, "float_value": 64},
        ],
        "id": "123",
        "inventory": 1,
        "level": 10,
        "origin": 0,
        "original_id": "123",
    }
    assert snapshot_para_vendas(_snapshot(_anuncio(item=item)), SKU, 12).vendas == (
        Venda(Decimal("12.5"), Decimal("0.11")),
    )


def test_parser_ignora_compras_e_outro_efeito():
    outro = _anuncio(item={"quality": 5, "defindex": 378, "quantity": 1, "attributes": [{"defindex": 134, "float_value": 13}]})
    assert snapshot_para_vendas(_snapshot(_anuncio(intent="buy"), outro), SKU, 12).vendas == ()


@pytest.mark.parametrize(
    "item",
    [
        {"quality": 6, "defindex": 378, "quantity": 1, "attributes": [{"defindex": 134, "float_value": 12}]},
        {"quality": 5, "defindex": 378, "quantity": 1, "attributes": []},
        {"quality": 5, "defindex": 378, "quantity": 1, "attributes": [{"defindex": 134, "float_value": 12}, {"defindex": 1009, "value": 1}]},
        {"quality": 5, "defindex": 378, "quantity": 1, "attributes": [{"defindex": 134, "float_value": 12}], "craftable": False},
        {"quality": 5, "defindex": 378, "quantity": 2, "attributes": [{"defindex": 134, "float_value": 12}]},
    ],
)
def test_parser_ignora_item_incomparavel(item):
    assert snapshot_para_vendas(_snapshot(_anuncio(item=item)), SKU, 12).vendas == ()


@pytest.mark.parametrize("currencies", [{"usd": 50}, {"keys": -1}, {"metal": "nan"}, {"keys": "1e999999"}, {"metal": "1000001"}, {}])
def test_parser_ignora_moeda_invalida(currencies):
    assert snapshot_para_vendas(_snapshot(_anuncio(currencies=currencies)), SKU, 12).vendas == ()


def test_parser_distingue_zero_vendas_confirmado():
    assert snapshot_para_vendas(_snapshot(), SKU, 12).vendas == ()


@pytest.mark.parametrize("created_at", [0, -1, True, "1790219196", None])
def test_parser_recusa_created_at_malformado(created_at):
    payload = _snapshot()
    payload["createdAt"] = created_at
    with pytest.raises(ValueError):
        snapshot_para_vendas(payload, SKU, 12)


@pytest.mark.parametrize("offset_s", [-6 * 60 * 60 - 1, 301])
def test_parser_recusa_snapshot_antigo_ou_futuro(offset_s):
    payload = _snapshot()
    payload["createdAt"] = int(time.time()) + offset_s
    with pytest.raises(ValueError):
        snapshot_para_vendas(payload, SKU, 12)


@pytest.mark.parametrize(
    "payload",
    [
        _snapshot(sku="Burning Flames Team Captain"),
        {"appid": 440, "sku": SKU},
        {"appid": 440, "listings": []},
        {"sku": SKU, "listings": []},
        {"appid": 440, "sku": SKU, "listings": None},
    ],
)
def test_parser_recusa_snapshot_divergente_ou_incompleto(payload):
    with pytest.raises(ValueError):
        snapshot_para_vendas(payload, SKU, 12)


def test_cliente_envia_token_cabecalho_sku_e_timeout():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=_snapshot(_anuncio()))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    snapshot = ClassificadosClient("SEGREDO_DE_TESTE", client=http).vendas(SKU, 12)
    assert snapshot.vendas == (Venda(Decimal("12.5"), Decimal("0.11")),)
    request = requests[0]
    assert request.url.path == "/api/classifieds/listings/snapshot"
    assert dict(request.url.params) == {"appid": "440", "sku": SKU}
    assert request.headers["X-Auth-Token"] == "SEGREDO_DE_TESTE"
    assert request.extensions["timeout"]["read"] > 0


def test_cliente_429_expoe_retry_after_sem_token():
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "42"})))
    with pytest.raises(ClassificadosLimitando) as error:
        ClassificadosClient("SEGREDO_DE_TESTE", client=http).vendas(SKU, 12)
    assert error.value.retry_after_s == 42
    assert "SEGREDO_DE_TESTE" not in str(error.value)
