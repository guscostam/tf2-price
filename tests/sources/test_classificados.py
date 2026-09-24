from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
import json
import time

import httpx
import pytest

from tf2price.sources.classificados import (
    ClassificadosClient,
    ClassificadosLimitando,
    Venda,
    carregar_defindices,
    snapshot_para_vendas as _snapshot_para_vendas,
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


def snapshot_para_vendas(payload, sku, effect_id, defindices=frozenset({378})):
    return _snapshot_para_vendas(payload, sku, effect_id, defindices)


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


def test_parser_ignora_defindex_de_outro_item_mesmo_com_efeito_correto():
    item = {"quality": 5, "defindex": 999, "quantity": 1,
            "attributes": [{"defindex": 134, "float_value": 12}]}
    assert snapshot_para_vendas(
        _snapshot(_anuncio(item=item)), SKU, 12, frozenset({378})
    ).vendas == ()


def test_parser_aceita_qualquer_defindex_do_mesmo_nome_no_schema():
    item = {"quality": 5, "defindex": 999, "quantity": 1,
            "attributes": [{"defindex": 134, "float_value": 12}]}
    assert snapshot_para_vendas(
        _snapshot(_anuncio(item=item)), SKU, 12, frozenset({378, 999})
    ).vendas == (Venda(Decimal("12.5"), Decimal("0.11")),)


def test_parser_recusa_conjunto_de_defindices_ausente():
    with pytest.raises(ValueError, match="defindex unavailable"):
        snapshot_para_vendas(_snapshot(), SKU, 12, frozenset())


def test_loader_le_mapa_local_sem_rede(tmp_path):
    path = tmp_path / "ids.json"
    path.write_text(json.dumps({"Team Captain": [378, 999]}), encoding="utf-8")
    assert carregar_defindices(path)["Team Captain"] == frozenset({378, 999})


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
    snapshot = ClassificadosClient(
        "SEGREDO_DE_TESTE", client=http,
        defindices_por_nome={"Team Captain": frozenset({378})},
    ).vendas(SKU, 12, "Team Captain")
    assert snapshot.vendas == (Venda(Decimal("12.5"), Decimal("0.11")),)
    request = requests[0]
    assert request.url.path == "/api/classifieds/listings/snapshot"
    assert dict(request.url.params) == {"appid": "440", "sku": SKU}
    assert request.headers["X-Auth-Token"] == "SEGREDO_DE_TESTE"
    assert request.extensions["timeout"]["read"] > 0


def test_cliente_preserva_precisao_decimal_do_json():
    body = json.dumps(_snapshot(_anuncio())).replace(
        '"keys": 12.5', '"keys": 0.123456789123456789'
    )
    http = httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=body)
    ))
    snapshot = ClassificadosClient(
        "SEGREDO_DE_TESTE", client=http,
        defindices_por_nome={"Team Captain": frozenset({378})},
    ).vendas(SKU, 12, "Team Captain")
    assert snapshot.vendas[0].chaves == Decimal("0.123456789123456789")


def test_cliente_429_expoe_retry_after_sem_token():
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "42"})))
    with pytest.raises(ClassificadosLimitando) as error:
        ClassificadosClient(
            "SEGREDO_DE_TESTE", client=http,
            defindices_por_nome={"Team Captain": frozenset({378})},
        ).vendas(SKU, 12, "Team Captain")
    assert error.value.retry_after_s == 42
    assert "SEGREDO_DE_TESTE" not in str(error.value)


def test_cliente_sem_item_no_mapa_falha_antes_do_http():
    def handler(_request):
        pytest.fail("não deve consultar vendedores sem defindex conhecido")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    cliente = ClassificadosClient("SEGREDO_DE_TESTE", client=http, defindices_por_nome={})
    with pytest.raises(ValueError, match="defindex unavailable"):
        cliente.vendas(SKU, 12, "Team Captain")
