"""PTAX do dólar, do serviço Olinda do Banco Central.

A PTAX de venda é o dólar comercial oficial do dia. Aqui ela converte em
reais o preço em dólar da chave segundo a backpack.tf: ver
`preco/referencia.py`. Não confundir com a taxa implícita da Steam
(`SteamClient.usd_to_brl`), que converte o que a própria Steam cobra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
# Dez dias cobrem fim de semana, feriado emendado e atraso de publicação: a
# PTAX só sai em dia útil, e pedir só "hoje" num sábado viria vazio.
JANELA_DIAS = 10


@dataclass(frozen=True)
class Ptax:
    valor: float  # reais por dólar, cotação de venda
    data: datetime  # quando o BC fechou esta cotação, em hora de Brasília


def _data_odata(dia: date) -> str:
    return f"'{dia:%m-%d-%Y}'"


def parse_ptax(payload: dict[str, Any]) -> Ptax:
    """A cotação de venda mais recente da resposta.

    Pega a maior `dataHoraCotacao`, e não a última da lista: nada na
    documentação do BC promete a ordem.
    """
    try:
        linhas = payload["value"]
        if not linhas:
            raise RuntimeError(
                f"PTAX: nenhuma cotação nos últimos {JANELA_DIAS} dias"
            )
        lidas = [
            (datetime.fromisoformat(linha["dataHoraCotacao"]), float(linha["cotacaoVenda"]))
            for linha in linhas
        ]
    except (KeyError, TypeError, ValueError) as erro:
        raise RuntimeError(
            f"PTAX: resposta do Banco Central fora do formato esperado "
            f"({type(erro).__name__})"
        ) from erro
    data, valor = max(lidas)
    if valor <= 0:
        raise RuntimeError("PTAX: cotação de venda não positiva")
    return Ptax(valor=valor, data=data)


class BcbClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._http = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "tf2price/0.1"},
            follow_redirects=True,
        )

    def ptax(self, hoje: date) -> Ptax:
        resposta = self._http.get(
            URL,
            params={
                "@dataInicial": _data_odata(hoje - timedelta(days=JANELA_DIAS)),
                "@dataFinalCotacao": _data_odata(hoje),
                "$format": "json",
            },
        )
        resposta.raise_for_status()
        return parse_ptax(resposta.json())
