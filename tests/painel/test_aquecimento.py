"""O aquecimento da subida.

Quem pagava o primeiro carregamento da cotação e do índice era a primeira
pessoa a abrir o painel depois de cada deploy, de dentro do `GET /`. Estes
testes prendem as três propriedades que fazem o aquecimento servir: ele
busca as duas, não segura a subida, e uma falha de terceiro não o derruba.
"""

from __future__ import annotations

import threading
import time

from tf2price.painel.app import (
    aquecer,
    aquecer_em_segundo_plano,
    criar_app,
    manter_quente,
)


class _Fonte:
    """Dublê de `CotacaoSobDemanda`/`IndiceSobDemanda`: conta e obedece."""

    def __init__(self, valor="carregado", demora_s: float = 0.0, erro=None) -> None:
        self._valor = valor
        self._demora = demora_s
        self._erro = erro
        self.chamadas = 0

    # `renovar` é o que o aquecimento chama na cotação (`obter` não vai à
    # rede); o índice só tem `obter`. O dublê atende os dois nomes.
    def renovar(self, *args):
        return self.obter(*args)

    def obter(self, *args):
        self.chamadas += 1
        if self._demora:
            time.sleep(self._demora)
        if self._erro:
            raise self._erro
        return self._valor


class _ContextoFalso:
    def __init__(self, cotacao, indice, ptax=None) -> None:
        self.cotacao = cotacao
        self.indice = indice
        self.ptax = ptax if ptax is not None else _Fonte()


def test_aquecer_busca_as_tres_e_diz_no_log(engine, capsys):
    ctx = _ContextoFalso(_Fonte(), _Fonte())

    aquecer(ctx, engine)

    assert ctx.cotacao.chamadas == 1
    assert ctx.ptax.chamadas == 1
    assert ctx.indice.chamadas == 1
    saida = capsys.readouterr().out
    assert "[aquecimento] cotação: ok" in saida
    assert "[aquecimento] PTAX: ok" in saida
    assert "[aquecimento] índice: ok" in saida


def test_ptax_que_falha_nao_impede_a_cotacao_nem_o_indice(engine, capsys):
    ctx = _ContextoFalso(_Fonte(), _Fonte(), ptax=_Fonte(valor=None))

    aquecer(ctx, engine)

    saida = capsys.readouterr().out
    assert "[aquecimento] PTAX: falhou" in saida
    assert ctx.cotacao.chamadas == 1 and ctx.indice.chamadas == 1


def test_fonte_que_devolve_none_aparece_como_falha_no_log(engine, capsys):
    """`obter` devolvendo None é como as duas classes dizem "o terceiro não
    respondeu" — elas engolem a exceção por dentro. O log não pode chamar
    isso de ok, senão o aquecimento esconde justamente o que interessa."""
    ctx = _ContextoFalso(_Fonte(valor=None), _Fonte())

    aquecer(ctx, engine)

    saida = capsys.readouterr().out
    assert "[aquecimento] cotação: falhou" in saida
    assert "sob demanda" in saida
    # E a segunda ainda é buscada: uma falha não aborta a outra.
    assert ctx.indice.chamadas == 1
    assert "[aquecimento] índice: ok" in saida


def test_excecao_inesperada_nao_derruba_o_aquecimento(engine, capsys):
    """`obter` não deveria levantar — mas se um erro nascer fora do `try`
    dela, o aquecimento registra e segue para a outra fonte."""
    ctx = _ContextoFalso(_Fonte(erro=RuntimeError("estourou fora do try")), _Fonte())

    aquecer(ctx, engine)

    saida = capsys.readouterr().out
    assert "RuntimeError" in saida
    assert ctx.indice.chamadas == 1


def test_aquecimento_nao_segura_a_subida(engine):
    """O ponto todo: a subida devolve na hora e o trabalho corre atrás.

    Sem o thread, `construir_aplicacao` só devolveria a aplicação depois de
    a Steam e a bp.tf responderem — o que no caminho ruim é um minuto.
    """
    ctx = _ContextoFalso(_Fonte(demora_s=0.3), _Fonte())

    inicio = time.monotonic()
    thread = aquecer_em_segundo_plano(ctx, engine)
    decorrido = time.monotonic() - inicio

    assert decorrido < 0.1, "a subida esperou o aquecimento"
    assert thread.daemon, (
        "o laço de `manter_quente` não termina e o backoff leva um minuto: "
        "um encerramento não pode esperar nenhum dos dois"
    )

    # A primeira passada acontece; depois o thread fica vivo de propósito,
    # renovando a cotação enquanto o processo viver.
    limite = time.monotonic() + 5
    while ctx.indice.chamadas == 0 and time.monotonic() < limite:
        time.sleep(0.02)
    assert ctx.cotacao.chamadas == 1
    assert ctx.indice.chamadas == 1
    assert thread.is_alive(), "o thread morreu em vez de manter a cotação quente"


def test_manter_quente_renova_a_cotacao_em_ciclo(engine):
    """Sem este laço, tirar a rede de `obter` congelaria a cotação no valor
    da subida: ninguém mais a buscaria nunca.

    O índice não entra no ciclo — ele é aquecido uma vez e não tem validade
    hoje; inventar uma aqui seria decidir de lado.
    """
    ctx = _ContextoFalso(_Fonte(), _Fonte())
    parar = threading.Event()

    def correr():
        manter_quente(ctx, engine, periodo_s=0.02, parar=parar)

    thread = threading.Thread(target=correr, daemon=True)
    thread.start()

    limite = time.monotonic() + 5
    while (
        min(ctx.cotacao.chamadas, ctx.ptax.chamadas) < 4
        and time.monotonic() < limite
    ):
        time.sleep(0.02)
    parar.set()
    thread.join(timeout=5)

    assert not thread.is_alive(), "`parar` não interrompeu o laço"
    assert ctx.cotacao.chamadas >= 4, "a cotação não está sendo renovada"
    assert ctx.ptax.chamadas >= 4, "a PTAX não está sendo renovada"
    assert ctx.indice.chamadas == 1, "o índice entrou no ciclo sem ser convidado"


def test_erro_no_banco_da_cotacao_nao_derruba_o_fio_nem_a_ptax(engine, capsys):
    """`renovar` só engole a falha do terceiro (Steam); um erro que nasça na
    leitura/escrita do NOSSO banco (um soluço do Postgres, por exemplo) tem
    que ser pego por `manter_quente`, senão mata o thread daemon e ninguém
    mais renova nada até reiniciar o processo — nem a PTAX, que não tem
    nada a ver com o erro da cotação."""
    ctx = _ContextoFalso(_Fonte(erro=RuntimeError("banco soluçou")), _Fonte())
    parar = threading.Event()

    def correr():
        manter_quente(ctx, engine, periodo_s=0.02, parar=parar)

    thread = threading.Thread(target=correr, daemon=True)
    thread.start()

    limite = time.monotonic() + 5
    while ctx.ptax.chamadas < 3 and time.monotonic() < limite:
        time.sleep(0.02)
    parar.set()
    thread.join(timeout=5)

    assert not thread.is_alive(), "o erro da cotação matou o fio de fundo"
    assert ctx.ptax.chamadas >= 3, "a PTAX parou de ser renovada"
    saida = capsys.readouterr().out
    assert "[renovo] cotação: RuntimeError" in saida


def test_preparar_varredura_fecha_rodadas_abertas_e_inicia_o_agendador(engine):
    from tf2price import db
    from tf2price.painel.app import preparar_varredura
    from tf2price.varredura import repositorio as varredura_repo
    from tf2price.varredura.agendador import Agendador

    with engine.begin() as conn:
        varredura_repo.abrir_rodada(conn, db.agora())
    iniciados = []

    agendador = preparar_varredura(engine, contexto=None, iniciar=iniciados.append)

    assert isinstance(agendador, Agendador)
    assert iniciados == [agendador]
    with engine.begin() as conn:
        assert varredura_repo.ultima_rodada(conn).motivo_parada == varredura_repo.MOTIVO_INTERROMPIDA


def test_criar_app_nao_aquece(engine):
    """O aquecimento mora nos pontos de entrada (`servir` e
    `construir_aplicacao`), nunca em `criar_app` — que é a costura dos
    testes. Movê-lo para cá faria a suíte inteira sair para a rede."""
    ctx = _ContextoFalso(_Fonte(), _Fonte())

    criar_app(engine, ctx)

    assert ctx.cotacao.chamadas == 0
    assert ctx.indice.chamadas == 0
    assert threading.active_count() >= 1


def test_preparar_vendas_so_inicia_com_token_sem_fazer_http(engine):
    from tf2price.painel.app import preparar_vendas
    from tf2price.varredura.vendas_coletor import VendasColetor

    ctx = _ContextoFalso(_Fonte(), _Fonte())
    iniciados = []
    assert preparar_vendas(engine, ctx, token="", iniciar=iniciados.append) is None
    coletor = preparar_vendas(engine, ctx, token="token-de-teste", iniciar=iniciados.append)
    assert isinstance(coletor, VendasColetor)
    assert iniciados == [coletor]
    assert ctx.indice.chamadas == 0
