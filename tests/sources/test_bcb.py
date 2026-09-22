"""A PTAX do Banco Central.

Formato medido em 22/09/2026 no serviço Olinda: `value` é uma lista, um item
por dia útil, com `cotacaoVenda` e `dataHoraCotacao` em hora de Brasília.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from tf2price.sources.bcb import BcbClient, Ptax, parse_ptax

RESPOSTA = {
    "@odata.context": "https://was-p.bcnet.bcb.gov.br/olinda/...",
    "value": [
        {"cotacaoCompra": 5.15690, "cotacaoVenda": 5.15750,
         "dataHoraCotacao": "2026-09-18 13:03:34.742036"},
        {"cotacaoCompra": 5.11550, "cotacaoVenda": 5.11610,
         "dataHoraCotacao": "2026-09-22 13:03:30.646171"},
        # Fora de ordem de propósito: a leitura não pode confiar na ordem.
        {"cotacaoCompra": 5.11110, "cotacaoVenda": 5.11170,
         "dataHoraCotacao": "2026-09-21 13:06:51.445645"},
    ],
}


def test_fica_com_a_cotacao_de_venda_mais_recente():
    ptax = parse_ptax(RESPOSTA)
    assert ptax == Ptax(5.1161, datetime(2026, 9, 22, 13, 3, 30, 646171))


def test_microsegundos_com_cinco_digitos():
    # O BC manda "13:05:30.35873": cinco dígitos, sem zero à direita.
    ptax = parse_ptax({"value": [
        {"cotacaoVenda": 5.1527, "dataHoraCotacao": "2026-09-16 13:05:30.35873"},
    ]})
    assert ptax.data == datetime(2026, 9, 16, 13, 5, 30, 358730)


@pytest.mark.parametrize(
    "payload",
    [
        {"value": []},
        {},
        {"value": [{"dataHoraCotacao": "2026-09-22 13:03:30.1"}]},
        {"value": [{"cotacaoVenda": 5.1, "dataHoraCotacao": "ontem"}]},
        {"value": [{"cotacaoVenda": 0, "dataHoraCotacao": "2026-09-22 13:03:30.1"}]},
    ],
)
def test_resposta_fora_do_formato_levanta(payload):
    with pytest.raises(RuntimeError, match="PTAX"):
        parse_ptax(payload)


def test_cliente_pede_a_janela_de_dez_dias_ate_hoje():
    capturadas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(200, json=RESPOSTA)

    cliente = BcbClient(httpx.Client(transport=httpx.MockTransport(handler)))

    ptax = cliente.ptax(date(2026, 9, 22))

    assert ptax.valor == 5.1161
    pedido = capturadas[0]
    assert "CotacaoDolarPeriodo(" in pedido.url.path
    assert pedido.url.params["@dataInicial"] == "'09-12-2026'"
    assert pedido.url.params["@dataFinalCotacao"] == "'09-22-2026'"
    assert pedido.url.params["$format"] == "json"


def test_cliente_com_erro_http_levanta():
    cliente = BcbClient(httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ))
    with pytest.raises(httpx.HTTPStatusError):
        cliente.ptax(date(2026, 9, 22))
