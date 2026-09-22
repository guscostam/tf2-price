"""A cotação da chave, e a divisão que importa nela.

`obter` só lê (memória, banco) e é o que as rotas chamam. `renovar` é quem
vai à rede, e só o thread de fundo chama. Essa divisão nasceu de duas
medições no Railway, nesta ordem:

1. 21/09/2026, log de deploy: a Steam respondeu 429 na primeira requisição do
   processo, o backoff gastou 44,8s e o painel ficou 5 minutos sem preço de
   chave — daí a cotação passar pelo banco, para o processo novo herdar a
   última conhecida.
2. No mesmo dia, log HTTP: `GET / 499 30173ms` e `GET / 200 11815ms`, contra
   8-13ms de todas as outras. Era a validade de 15 min mandando uma
   requisição de usuário buscar na Steam — daí a rede sair de `obter`.

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
VELHA = AGORA - VALIDADE_COTACAO - timedelta(minutes=5)


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

    def renovar_cotacao(self) -> tuple[Brl, float]:
        # A única porta de rede da cotação: contar aqui basta para saber se
        # o cliente foi ao ar.
        self.chamadas += 1
        if self._demora:
            time.sleep(self._demora)
        if self.falhar:
            raise RuntimeError("Steam fora do ar")
        return Brl.from_float(self._chave), 5.0


def _guardar(engine, *, chave_cents: int, quando) -> None:
    with engine.begin() as conn:
        preco_repo.guardar_cotacao(conn, chave_cents, 5.0, quando)


def _lido(engine):
    with engine.begin() as conn:
        return preco_repo.ler_cotacao(conn)


# --- `obter`: só lê, nunca vai à rede --------------------------------------


def test_obter_com_banco_vazio_nao_fala_com_a_steam(engine):
    """Sem nada em lugar nenhum, `obter` devolve None — e não tenta buscar.

    É o caso que custou 30 segundos de página em branco: antes, aqui é que
    a escada de backoff começava.
    """
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    assert sob.obter(engine) is None
    assert steam.chamadas == 0


def test_obter_le_do_banco_no_processo_novo(engine):
    _guardar(engine, chave_cents=1173, quando=AGORA)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.obter(engine)

    assert steam.chamadas == 0
    assert cotacao.key_brl == Brl.from_cents(1173)
    assert cotacao.buscado_em == AGORA


def test_obter_serve_a_velha_sem_tentar_renovar(engine):
    """A regressão que motivou a divisão: uma cotação vencida NÃO pode
    mandar quem está olhando a tela esperar a Steam. Ela sai velha, e quem
    mostra diz a idade."""
    _guardar(engine, chave_cents=1000, quando=VELHA)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.obter(engine)

    assert steam.chamadas == 0, "obter foi à rede: a regressão voltou"
    assert cotacao.key_brl == Brl.from_cents(1000)
    assert cotacao.buscado_em == VELHA


def test_obter_depois_da_primeira_leitura_usa_a_memoria(engine):
    _guardar(engine, chave_cents=1173, quando=AGORA)
    sob = CotacaoSobDemanda(_SteamClienteFalso(), relogio=_RelogioFalso())

    primeira = sob.obter(engine)
    assert sob.obter(engine) is primeira


def test_a_trava_nao_prende_quem_ja_tem_o_valor(engine):
    """Carregado, `obter` devolve pela leitura curta, antes da trava: nenhuma
    requisição da vida do processo disputa trava por causa do caso raro."""
    sob = CotacaoSobDemanda(_SteamClienteFalso(), relogio=_RelogioFalso())
    primeira = sob.renovar(engine, AGORA)

    sob._trava.acquire()
    try:
        assert sob.obter(engine) is primeira
    finally:
        sob._trava.release()


# --- `renovar`: a busca, e só no fundo -------------------------------------


def test_renovar_busca_e_grava_no_banco(engine, capsys):
    steam = _SteamClienteFalso(chave=12.50)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    sob.renovar(engine, AGORA)

    assert _lido(engine) == (1250, 5.0, AGORA)
    # Sucesso vira log: sem isto, o log conta quando falhou e nunca quando
    # voltou — e é essa a pergunta que se faz olhando este log.
    assert "[cotação]" in capsys.readouterr().out


def test_renovar_nao_busca_o_que_ainda_esta_recente(engine):
    _guardar(engine, chave_cents=1173, quando=AGORA)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    sob.renovar(engine, AGORA)

    assert steam.chamadas == 0


def test_na_fronteira_da_validade_ainda_vale(engine):
    """Exatamente 15 min conta como recente: sem o `<=`, todo minuto redondo
    viraria uma requisição a mais à Steam."""
    _guardar(engine, chave_cents=1173, quando=AGORA - VALIDADE_COTACAO)
    steam = _SteamClienteFalso()
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    sob.renovar(engine, AGORA)

    assert steam.chamadas == 0


def test_renovar_substitui_a_velha(engine):
    _guardar(engine, chave_cents=1000, quando=VELHA)
    steam = _SteamClienteFalso(chave=12.00)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.renovar(engine, AGORA)

    assert cotacao.key_brl == Brl.from_cents(1200)
    assert cotacao.buscado_em == AGORA
    assert _lido(engine) == (1200, 5.0, AGORA)


def test_renovar_com_steam_fora_do_ar_mantem_a_velha(engine):
    """A degradação honesta: o número velho continua servindo, com a idade
    dele intacta, em vez de sumir da tela."""
    _guardar(engine, chave_cents=1000, quando=VELHA)
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    cotacao = sob.renovar(engine, AGORA)

    assert steam.chamadas == 1, "velha demais: tinha que ter tentado buscar"
    assert cotacao.key_brl == Brl.from_cents(1000)
    # E o `buscado_em` não é remendado para agora: é a idade real do número.
    assert cotacao.buscado_em == VELHA
    # O banco também não é tocado: gravar a velha com data nova seria mentir.
    assert _lido(engine) == (1000, 5.0, VELHA)


def test_sem_nada_e_com_a_steam_fora_do_ar_devolve_none(engine):
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    assert sob.renovar(engine, AGORA) is None
    assert steam.chamadas == 1


def test_dentro_da_calma_nao_tenta_de_novo(engine):
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.renovar(engine, AGORA) is None
    assert steam.chamadas == 1

    relogio.avancar(50.0)
    assert sob.renovar(engine, AGORA) is None
    assert steam.chamadas == 1


def test_depois_da_calma_tenta_de_novo(engine):
    steam = _SteamClienteFalso()
    steam.falhar = True
    relogio = _RelogioFalso()
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=relogio)

    assert sob.renovar(engine, AGORA) is None

    relogio.avancar(100.0)
    steam.falhar = False
    assert sob.renovar(engine, AGORA) is not None
    assert steam.chamadas == 2


def test_falha_fica_registrada_no_log(engine, capsys):
    steam = _SteamClienteFalso()
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=42.0, relogio=_RelogioFalso())

    sob.renovar(engine, AGORA)

    saida = capsys.readouterr().out
    assert "CotacaoSobDemanda" in saida
    assert "RuntimeError" in saida
    assert "Steam fora do ar" in saida
    assert "nova tentativa" in saida


def test_idade_e_a_da_busca_nao_a_da_leitura(engine):
    """`buscado_em` é quando a Steam foi lida. Uma leitura depois não
    rejuvenesce o número — é essa data que o timbre mostra."""
    sob = CotacaoSobDemanda(_SteamClienteFalso(), relogio=_RelogioFalso())

    primeira = sob.renovar(engine, AGORA)
    depois = sob.obter(engine)

    assert depois.buscado_em == primeira.buscado_em == AGORA


# --- a trava entre dois renovos --------------------------------------------


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


def test_renovos_simultaneos_buscam_uma_vez_so(engine):
    """Hoje só o thread de fundo renova, então a disputa é improvável — mas a
    busca duplicada custa requisições ao IP que a Steam limita, e o preço de
    garantir isso é uma trava que ninguém no caminho da requisição toca."""
    steam = _SteamClienteFalso(demora_s=0.15)
    sob = CotacaoSobDemanda(steam, relogio=_RelogioFalso())

    resultados = _em_paralelo(lambda: sob.renovar(engine, AGORA))

    assert steam.chamadas == 1
    assert all(r is resultados[0] for r in resultados)
    assert resultados[0] is not None


def test_falha_simultanea_respeita_a_calma_uma_vez_so(engine):
    steam = _SteamClienteFalso(demora_s=0.15)
    steam.falhar = True
    sob = CotacaoSobDemanda(steam, espera_apos_falha_s=100.0, relogio=_RelogioFalso())

    resultados = _em_paralelo(lambda: sob.renovar(engine, AGORA))

    assert steam.chamadas == 1
    assert all(r is None for r in resultados)


def test_cotacao_exige_a_idade_no_construtor():
    """Uma cotação anônima não pode existir: o timbre mostra a idade dela, e
    um valor sem `buscado_em` viraria "idade desconhecida" na tela."""
    with pytest.raises(TypeError):
        Cotacao(key_brl=Brl.from_cents(1000), usd_to_brl=5.0)


def test_a_cotacao_e_a_busca_dividem_o_mesmo_cliente_da_steam(monkeypatch):
    """A canaário, e é de propósito: a calma que o `renovar` do fundo liga ao
    levar 429 protege também as buscas de quem está na tela, porque a calma
    vive no `SteamClient` e o `SteamClient` é um só.

    Na prática é quase sempre o fundo quem descobre o limite primeiro (ele
    renova de minuto em minuto), e aí a primeira busca da pessoa já falha na
    hora em vez de subir a escada de 31-62s.
    """
    from tf2price.painel.consulta import construir_contexto

    # `load_dotenv` não sobrescreve o que já está no ambiente, então isto
    # vale mesmo com um `.env` de verdade ao lado.
    monkeypatch.setenv("BPTF_API_KEY", "chave-de-teste")
    contexto = construir_contexto()

    assert contexto.cotacao._steam is contexto.steam
