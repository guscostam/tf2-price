"""Unidade para o backoff de `IndiceSobDemanda` e `CotacaoSobDemanda`.

Os testes de rota (`test_consulta.py`) usam `_IndiceFalso`/`_CotacaoFalsa`,
que substituem a classe inteira e nunca exercitam a lógica do intervalo.
Aqui o relógio é falso e avançado à mão, e o cliente é um dublê que conta
chamadas — assim uma comparação invertida ou um off-by-one no backoff
aparece.
"""

from __future__ import annotations

from tf2price.domain.money import Brl
from tf2price.painel.consulta import CotacaoSobDemanda, IndiceSobDemanda
from tf2price.sources.backpacktf import Currencies, PriceIndex

CHAVE_SECRETA = "segredo-que-nao-pode-vazar"


class _RelogioFalso:
    """Um relógio que só anda quando o teste manda."""

    def __init__(self, agora: float = 0.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class _ClienteBptfFalso:
    """Dublê do `BackpackTfClient`: conta chamadas e falha sob comando."""

    def __init__(self, key_in_refined: float = 64.11) -> None:
        self._key_in_refined = key_in_refined
        self.chamadas = 0
        self.falhar = False

    def currencies(self) -> Currencies:
        self.chamadas += 1
        if self.falhar:
            raise RuntimeError("bp.tf fora do ar")
        return Currencies(key_in_refined=self._key_in_refined, key_in_usd=0.0)

    def prices_payload(self) -> dict:
        return {"response": {"items": {}}}


class _SteamClienteFalso:
    """Dublê do `SteamClient`: conta chamadas e falha sob comando."""

    def __init__(self) -> None:
        self.chamadas = 0
        self.falhar = False

    def key_price(self) -> Brl:
        # `key_price` é a primeira chamada dentro de `Cotacao(...)`; contar
        # aqui basta para saber se o cliente foi ao ar de novo.
        self.chamadas += 1
        if self.falhar:
            raise RuntimeError("Steam fora do ar")
        return Brl.from_float(11.73)

    def usd_to_brl(self) -> float:
        return 5.0


# --- IndiceSobDemanda ------------------------------------------------------


def test_indice_sucesso_guarda_e_nao_consulta_de_novo():
    cliente = _ClienteBptfFalso()
    sob = IndiceSobDemanda(cliente, relogio=_RelogioFalso())

    primeiro = sob.obter()
    assert isinstance(primeiro, PriceIndex)
    assert cliente.chamadas == 1

    segundo = sob.obter()
    assert segundo is primeiro
    assert cliente.chamadas == 1  # resultado guardado, cliente não é chamado de novo


def test_indice_falha_devolve_none():
    cliente = _ClienteBptfFalso()
    cliente.falhar = True
    sob = IndiceSobDemanda(cliente, relogio=_RelogioFalso())

    assert sob.obter() is None
    assert cliente.chamadas == 1


def test_indice_dentro_do_intervalo_nao_tenta_de_novo():
    cliente = _ClienteBptfFalso()
    cliente.falhar = True
    relogio = _RelogioFalso()
    sob = IndiceSobDemanda(cliente, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter() is None
    assert cliente.chamadas == 1

    relogio.avancar(50.0)  # ainda dentro dos 100s de espera
    assert sob.obter() is None
    assert cliente.chamadas == 1  # nenhuma nova tentativa


def test_indice_depois_do_intervalo_tenta_de_novo():
    cliente = _ClienteBptfFalso()
    cliente.falhar = True
    relogio = _RelogioFalso()
    sob = IndiceSobDemanda(cliente, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter() is None
    assert cliente.chamadas == 1

    relogio.avancar(100.0)  # intervalo cumprido
    cliente.falhar = False  # o terceiro volta ao ar
    resultado = sob.obter()

    assert isinstance(resultado, PriceIndex)
    assert cliente.chamadas == 2


# --- CotacaoSobDemanda ------------------------------------------------------


def test_cotacao_sucesso_guarda_e_nao_consulta_de_novo():
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    primeira = sob.obter()
    assert primeira is not None
    assert steam.chamadas == 1

    segunda = sob.obter()
    assert segunda is primeira
    assert steam.chamadas == 1


def test_cotacao_falha_devolve_none():
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    assert sob.obter() is None
    assert steam.chamadas == 1


def test_cotacao_dentro_do_intervalo_nao_tenta_de_novo():
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter() is None
    assert steam.chamadas == 1

    relogio.avancar(50.0)
    assert sob.obter() is None
    assert steam.chamadas == 1


def test_cotacao_depois_do_intervalo_tenta_de_novo():
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter() is None
    assert steam.chamadas == 1

    relogio.avancar(100.0)
    steam.falhar = False
    resultado = sob.obter()

    assert resultado is not None
    assert steam.chamadas == 2


# --- Achado 2: a falha não pode ser silenciosa -----------------------------


def test_falha_do_indice_fica_registrada_no_log(capsys):
    cliente = _ClienteBptfFalso()
    cliente.falhar = True
    sob = IndiceSobDemanda(cliente, espera_apos_falha_s=42.0, relogio=_RelogioFalso())

    sob.obter()

    saida = capsys.readouterr().out
    assert "IndiceSobDemanda" in saida
    assert "RuntimeError" in saida
    assert "bp.tf fora do ar" in saida
    assert "nova tentativa" in saida


def test_falha_da_cotacao_fica_registrada_no_log(capsys):
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=42.0, relogio=_RelogioFalso())

    sob.obter()

    saida = capsys.readouterr().out
    assert "CotacaoSobDemanda" in saida
    assert "RuntimeError" in saida
    assert "Steam fora do ar" in saida
    assert "nova tentativa" in saida


def test_falha_com_url_na_mensagem_nao_vaza_a_chave_no_log(capsys):
    """A mensagem de um `httpx.HTTPStatusError` inclui a URL inteira do
    pedido, e `BackpackTfClient._get` manda a chave da API na query string.
    O log tem que cortar isso — o tipo da exceção continua lá, o segredo não.
    """
    cliente = _ClienteBptfFalso()
    relogio = _RelogioFalso()
    sob = IndiceSobDemanda(cliente, relogio=relogio)

    erro = RuntimeError(
        f"Client error '403 Forbidden' for url "
        f"'https://backpack.tf/api/IGetPrices/v4?key={CHAVE_SECRETA}&appid=440'"
    )

    def _falha():
        cliente.chamadas += 1
        raise erro

    cliente.currencies = _falha
    sob.obter()

    saida = capsys.readouterr().out
    assert CHAVE_SECRETA not in saida
    assert "RuntimeError" in saida
    assert "IndiceSobDemanda" in saida
