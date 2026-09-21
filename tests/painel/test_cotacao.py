"""A cotação da chave: memória, banco e, só em último caso, a Steam.

Guardar no banco não foi gosto: em 21/09/2026 um deploy real levou 429 da
Steam na primeira requisição do processo — o IP do Railway já estava limitado
antes de a gente pedir —, gastou 44,8s de backoff e o painel ficou 5 minutos
sem preço de chave nenhum. Estes testes prendem as duas metades disso: o
processo novo nasce com a última cotação conhecida, e a Steam fora do ar não
apaga o número da tela, só o envelhece.

O relógio de `espera_apos_falha_s` é falso e avançado à mão; `quando` (o
instante que vai para o banco) entra por parâmetro, como no resto do projeto.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.painel.consulta import VALIDADE_COTACAO, Cotacao, CotacaoSobDemanda
from tf2price.preco import repositorio as preco_repo

AGORA = db.agora()


class _RelogioFalso:
    """Um relógio monotônico que só anda quando o teste manda."""

    def __init__(self, agora: float = 0.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class _SteamClienteFalso:
    """Dublê do `SteamClient`: conta chamadas, falha e demora sob comando."""

    def __init__(self, demora_s: float = 0.0, chave: float = 11.73) -> None:
        self.chamadas = 0
        self.falhar = False
        self._demora = demora_s
        self._chave = chave

    def key_price(self) -> Brl:
        # Primeira chamada dentro de `Cotacao(...)`: contar aqui basta para
        # saber se o cliente foi ao ar.
        self.chamadas += 1
        if self._demora:
            time.sleep(self._demora)
        if self.falhar:
            raise RuntimeError("Steam fora do ar")
        return Brl.from_float(self._chave)

    def usd_to_brl(self) -> float:
        return 5.0


def _guardar(engine, *, chave_cents: int, quando) -> None:
    with engine.begin() as conn:
        preco_repo.guardar_cotacao(conn, chave_cents, 5.0, quando)


def _lido(engine):
    with engine.begin() as conn:
        return preco_repo.ler_cotacao(conn)


# --- memória ---------------------------------------------------------------


def test_sucesso_guarda_em_memoria_e_nao_consulta_de_novo(engine):
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    primeira = sob.obter(engine, AGORA)
    assert primeira is not None
    assert steam.chamadas == 1

    segunda = sob.obter(engine, AGORA)
    assert segunda is primeira
    assert steam.chamadas == 1


def test_sem_nada_em_lugar_nenhum_devolve_none(engine):
    """Banco vazio e Steam fora do ar: aí não há número, e a tela diz isso."""
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    assert sob.obter(engine, AGORA) is None
    assert steam.chamadas == 1


def test_dentro_do_intervalo_nao_tenta_de_novo(engine):
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter(engine, AGORA) is None
    assert steam.chamadas == 1

    relogio.avancar(50.0)
    assert sob.obter(engine, AGORA) is None
    assert steam.chamadas == 1


def test_depois_do_intervalo_tenta_de_novo(engine):
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.obter(engine, AGORA) is None

    relogio.avancar(100.0)
    steam.falhar = False
    assert sob.obter(engine, AGORA) is not None
    assert steam.chamadas == 2


def test_falha_fica_registrada_no_log(engine, capsys):
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=42.0, relogio=_RelogioFalso())

    sob.obter(engine, AGORA)

    saida = capsys.readouterr().out
    assert "CotacaoSobDemanda" in saida
    assert "RuntimeError" in saida
    assert "Steam fora do ar" in saida
    assert "nova tentativa" in saida


# --- o banco: atravessar o deploy ------------------------------------------


def test_a_busca_grava_no_banco(engine):
    steam = _SteamClienteFalso(chave=12.50)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    sob.obter(engine, AGORA)

    assert _lido(engine) == (1250, 5.0, AGORA)


def test_processo_novo_le_do_banco_e_nao_fala_com_a_steam(engine):
    """O ponto da persistência: instância nova (o que um deploy produz) com
    cotação recente guardada não gasta requisição no IP compartilhado."""
    _guardar(engine, chave_cents=1173, quando=AGORA)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.obter(engine, AGORA)

    assert steam.chamadas == 0, "falou com a Steam tendo cotação fresca no banco"
    assert cotacao is not None
    assert cotacao.key_brl == Brl.from_cents(1173)
    assert cotacao.buscado_em == AGORA


def test_cotacao_velha_no_banco_com_steam_fora_do_ar_ainda_serve(engine):
    """A degradação honesta: o número velho continua na tela, com a idade
    dele intacta, em vez de sumir."""
    velha = AGORA - VALIDADE_COTACAO - timedelta(minutes=5)
    _guardar(engine, chave_cents=1000, quando=velha)
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.obter(engine, AGORA)

    assert steam.chamadas == 1, "velha demais: tinha que ter tentado buscar"
    assert cotacao is not None
    assert cotacao.key_brl == Brl.from_cents(1000)
    # E o `buscado_em` não é remendado para agora: é a idade real do número.
    assert cotacao.buscado_em == velha


def test_cotacao_velha_no_banco_com_steam_de_pe_e_substituida(engine):
    velha = AGORA - VALIDADE_COTACAO - timedelta(minutes=5)
    _guardar(engine, chave_cents=1000, quando=velha)
    steam = _SteamClienteFalso(chave=12.00)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.obter(engine, AGORA)

    assert cotacao.key_brl == Brl.from_cents(1200)
    assert cotacao.buscado_em == AGORA
    assert _lido(engine) == (1200, 5.0, AGORA)


def test_na_fronteira_da_validade_ainda_vale(engine):
    """Exatamente 15 min conta como recente: sem o `<=`, todo minuto redondo
    viraria uma requisição a mais à Steam."""
    _guardar(engine, chave_cents=1173, quando=AGORA - VALIDADE_COTACAO)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    assert sob.obter(engine, AGORA) is not None
    assert steam.chamadas == 0


def test_idade_e_a_da_busca_nao_a_da_leitura(engine):
    """`buscado_em` é quando a Steam foi lida. Uma leitura depois não
    rejuvenesce o número — é essa data que o timbre mostra."""
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    primeira = sob.obter(engine, AGORA)
    depois = sob.obter(engine, AGORA + timedelta(minutes=5))

    assert depois.buscado_em == primeira.buscado_em == AGORA


# --- a trava: o aquecimento e a primeira visita chegam juntos --------------


def _em_paralelo(fn, vezes: int = 4) -> list:
    partida = threading.Barrier(vezes)
    saida: list = [None] * vezes

    def corpo(i: int) -> None:
        partida.wait()
        saida[i] = fn()

    threads = [threading.Thread(target=corpo, args=(i,)) for i in range(vezes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return saida


def test_chamadas_simultaneas_buscam_uma_vez_so(engine):
    """Aqui a busca duplicada custa requisições à Steam, que limita por IP —
    e no Railway o IP é o mesmo para todos."""
    steam = _SteamClienteFalso(demora_s=0.15)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    resultados = _em_paralelo(lambda: sob.obter(engine, AGORA))

    assert steam.chamadas == 1
    assert all(r is resultados[0] for r in resultados)
    assert resultados[0] is not None


def test_a_trava_nao_prende_depois_de_carregado(engine):
    """Carregado, `obter` devolve pela leitura curta, antes da trava."""
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())
    primeira = sob.obter(engine, AGORA)

    sob._trava.acquire()
    try:
        assert sob.obter(engine, AGORA) is primeira
    finally:
        sob._trava.release()


def test_falha_simultanea_respeita_a_espera_uma_vez_so(engine):
    steam = _SteamClienteFalso(demora_s=0.15)
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=_RelogioFalso())

    resultados = _em_paralelo(lambda: sob.obter(engine, AGORA))

    assert steam.chamadas == 1
    assert all(r is None for r in resultados)


def test_cotacao_exige_a_idade_no_construtor():
    """Uma cotação anônima não pode existir: o timbre mostra a idade dela, e
    um valor sem `buscado_em` viraria "idade desconhecida" na tela."""
    with pytest.raises(TypeError):
        Cotacao(key_brl=Brl.from_cents(1000), usd_to_brl=5.0)
