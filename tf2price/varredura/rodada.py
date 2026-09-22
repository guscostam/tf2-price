"""Uma rodada da varredura: cotação do dólar, passada rasa, passada funda.

A passada rasa lê a busca da Steam (10 nomes por requisição) e guarda, por
nome, o menor preço e o número de listagens, que é a assinatura. A funda abre
a página só dos nomes cuja assinatura mudou, que nunca foram lidos ou cuja
leitura passou do prazo.

Toda requisição sai do mesmo IP da consulta, e a consulta é o produto. Por
isso a rodada espera um intervalo extra antes de cada passo, espera a calma de
quem bateu no 429 antes dela, e nunca segura conexão de banco durante a rede.

Num 429, a rodada não desiste: pausa (5, 10, 20, depois 30 min) e tenta o
mesmo passo de novo. Medido em produção em 22/09/2026: o IP do Railway levava
429 na primeira requisição, e a rodada que desistia ali terminava com 0 nomes.
Ela só desiste depois de 4 pausas seguidas sem nenhuma requisição dar certo.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.ratelimit import SteamLimitando
from tf2price.sources.steam import SearchResult
from tf2price.varredura import repositorio as repo
from tf2price.varredura.escopo import e_cosmetico_unusual

QUERY = "Unusual"
# Com o RateLimiter de 1 s, a varredura sai a cada ~5 s. Medido em
# 2026-09-19: 429 na 128ª requisição a 1 s, cinco 429 em 389 a 3 s. Uma
# consulta de usuário espera no máximo uma requisição da varredura.
ESPACO_EXTRA_S = 4.0
# Freio contra um `total_count` absurdo: 4.000 nomes, o dobro do medido.
MAX_PAGINAS_RASAS = 400
ITENS_POR_PAGINA_DA_BUSCA = 10
# Minutos da n-ésima pausa seguida depois de um 429; da quarta em diante, 30.
PAUSAS_MIN = (5, 10, 20, 30)
# Uma tentativa depois da quarta pausa que também leve 429 encerra a rodada:
# ~65 min batendo num IP limitado já é resposta.
MAX_PAUSAS_SEGUIDAS = 4


@dataclass
class Resumo:
    nomes_lidos: int = 0
    fundas_feitas: int = 0
    falhas: int = 0
    motivo: str = repo.MOTIVO_OK


class _Cancelada(Exception):
    """O admin apertou Stop."""


class _Esgotada(Exception):
    """4 pausas seguidas sem nenhuma requisição dar certo."""


def _esperar_sem_cancelamento(segundos: float) -> bool:
    return threading.Event().wait(segundos)


class _Freio:
    """Espera, calma, pausa e cancelamento de uma rodada, num lugar só."""

    def __init__(
        self, engine: Engine, rodada_id: int, retratos: Any, steam: Any,
        esperar: Callable[[float], bool], agora: Callable[[], datetime],
        espaco_extra_s: float,
    ) -> None:
        self._engine = engine
        self._rodada_id = rodada_id
        self._retratos = retratos
        self._steam = steam
        self._esperar_fn = esperar
        self._agora = agora
        self._espaco_extra_s = espaco_extra_s
        self.pausas_seguidas = 0

    def _esperar(self, segundos: float) -> None:
        if segundos > 0 and self._esperar_fn(segundos):
            raise _Cancelada

    def _calma_restante_s(self) -> float:
        # Duas calmas: a da página (`Retratos`, 5 min) e a do `SteamClient`
        # (1 min), que a renovação da cotação e a busca de usuário também
        # ligam. Com a do cliente ligada, ele recusa SEM requisição; tratar
        # essa recusa como 429 queimaria uma pausa e esticaria a calma da
        # página para os usuários.
        return max(self._retratos.calma_restante_s(), self._steam.calma_restante_s())

    def _esperar_calma(self) -> None:
        # Calma ligada por outro (um usuário bateu no 429): espera o que falta,
        # sem contar como pausa, porque a rodada não fez requisição nenhuma.
        while (resta := self._calma_restante_s()) > 0:
            self._esperar(resta)

    def antes_de_requisitar(self) -> None:
        self._esperar_calma()
        self._esperar(self._espaco_extra_s)
        # Um usuário pode ter batido no 429 durante o espaço extra.
        self._esperar_calma()

    def sucesso(self) -> None:
        if self.pausas_seguidas:
            self.pausas_seguidas = 0
            self.gravar(pausas_seguidas=0)

    def limitado(self, onde: str) -> None:
        """Pausa depois de um 429 em `onde`; quem chama tenta o mesmo passo."""
        self._retratos.acalmar()
        if self.pausas_seguidas >= MAX_PAUSAS_SEGUIDAS:
            print(f"[varredura] rodada {self._rodada_id}: 429 {onde}; "
                  f"{MAX_PAUSAS_SEGUIDAS} pausas seguidas sem sucesso, desistindo", flush=True)
            raise _Esgotada
        self.pausas_seguidas += 1
        minutos = PAUSAS_MIN[min(self.pausas_seguidas, len(PAUSAS_MIN)) - 1]
        ate = self._agora() + timedelta(minutes=minutos)
        print(f"[varredura] rodada {self._rodada_id}: 429 {onde}; pausa "
              f"{self.pausas_seguidas} de {MAX_PAUSAS_SEGUIDAS}, até {ate:%H:%M} UTC", flush=True)
        self.gravar(pausado_ate=ate, pausas_seguidas=self.pausas_seguidas)
        self._esperar(minutos * 60)
        # A pausa nunca é menor que a calma ainda em curso.
        self._esperar_calma()
        self.gravar(pausado_ate=None)

    def gravar(self, **campos) -> None:
        with self._engine.begin() as conn:
            repo.atualizar_andamento(conn, self._agora(), **campos)


def _assinatura_mudou(anterior: repo.Assinatura, visto: SearchResult) -> bool:
    return (anterior.preco_usd_cents, anterior.n_listagens) != (
        visto.sell_price_usd_cents, visto.sell_listings
    )


def _precisa_funda(
    anterior: repo.Assinatura | None, visto: SearchResult, quando: datetime, config: repo.Config
) -> bool:
    if anterior is None or anterior.funda_em is None:
        return True
    if _assinatura_mudou(anterior, visto):
        return True
    return quando - anterior.funda_em > timedelta(hours=config.idade_max_funda_h)


def executar_rodada(
    engine: Engine,
    *,
    steam: Any,
    retratos: Any,
    cotacao: Any,
    agora: Callable[[], datetime] = db.agora,
    esperar: Callable[[float], bool] = _esperar_sem_cancelamento,
    aceitar: Callable[[str], bool] = e_cosmetico_unusual,
    espaco_extra_s: float = ESPACO_EXTRA_S,
) -> Resumo:
    """`esperar(segundos)` devolve verdadeiro quando a rodada foi cancelada:
    em produção é o `threading.Event.wait` que o `Agendador` cria por rodada."""
    inicio = agora()
    with engine.begin() as conn:
        config = repo.ler_config(conn)
        anterior_completa = repo.ultima_completa(conn)
        rodada_id = repo.abrir_rodada(conn, inicio)
        repo.iniciar_andamento(conn, rodada_id, inicio)

    resumo = Resumo()
    freio = _Freio(engine, rodada_id, retratos, steam, esperar, agora, espaco_extra_s)
    try:
        resumo.motivo = _rodar(
            engine, rodada_id, resumo, config, freio,
            steam=steam, retratos=retratos, cotacao=cotacao, agora=agora, aceitar=aceitar,
        )
    except _Cancelada:
        resumo.motivo = repo.MOTIVO_CANCELADA
    except _Esgotada:
        resumo.motivo = repo.MOTIVO_429
    except Exception as erro:
        print(f"[varredura] rodada {rodada_id}: {type(erro).__name__}: "
              f"{mensagem_saneada(erro)}", flush=True)
        resumo.motivo = repo.MOTIVO_ERRO

    with engine.begin() as conn:
        repo.fechar_rodada(
            conn, rodada_id, agora(),
            nomes_lidos=resumo.nomes_lidos, fundas_feitas=resumo.fundas_feitas,
            falhas=resumo.falhas, motivo=resumo.motivo,
        )
        repo.limpar_andamento(conn)
        # Só uma rodada COMPLETA viu o mercado inteiro. E um nome some só
        # depois de duas completas sem ele: a busca ordena por preço e leva
        # minutos, e um item cujo preço mudou no meio pode trocar de página e
        # não ser visto uma vez sem ter saído do mercado.
        if resumo.motivo == repo.MOTIVO_OK and anterior_completa is not None:
            repo.apagar_nao_vistos_desde(conn, anterior_completa.inicio)
        repo.podar_rodadas(conn)
    print(f"[varredura] rodada {rodada_id}: {resumo.motivo}, {resumo.nomes_lidos} nomes, "
          f"{resumo.fundas_feitas} lidos a fundo, {resumo.falhas} falhas", flush=True)
    return resumo


def _rodar(
    engine: Engine, rodada_id: int, resumo: Resumo, config: repo.Config, freio: _Freio, *,
    steam: Any, retratos: Any, cotacao: Any,
    agora: Callable[[], datetime], aceitar: Callable[[str], bool],
) -> str:
    if cotacao.obter(engine) is None:
        print("[varredura] sem cotação da chave: a página do item vem em dólar "
              "e não há taxa para converter", flush=True)
        return repo.MOTIVO_ERRO

    # --- cotação do dólar: a busca responde em dólar e o `SteamClient`
    # converte com esta taxa. Antes ela era buscada escondida dentro da
    # primeira busca, e um 429 ali não dizia de onde veio.
    while True:
        freio.antes_de_requisitar()
        try:
            steam.usd_to_brl()
        except SteamLimitando:
            freio.limitado("na cotação do dólar")
            continue
        freio.sucesso()
        break

    # --- passada rasa
    freio.gravar(fase=repo.FASE_BUSCA)
    vistos: set[str] = set()
    pendentes: list[str] = []
    start = 0
    paginas_lidas = 0
    while True:
        if paginas_lidas >= MAX_PAGINAS_RASAS:
            # O teto estourou sem alcançar `total_count`: a rodada não viu o
            # mercado inteiro, então não pode contar como completa nem
            # liberar a exclusão de nomes "não vistos".
            print(f"[varredura] rodada {rodada_id}: teto de {MAX_PAGINAS_RASAS} páginas rasas "
                  f"estourado sem terminar a busca", flush=True)
            return repo.MOTIVO_ERRO
        freio.antes_de_requisitar()
        try:
            pagina = steam.search_page(start=start, query=QUERY)
        except SteamLimitando:
            freio.limitado(f"na busca (página {paginas_lidas + 1})")
            continue
        freio.sucesso()
        paginas_lidas += 1
        if not pagina.results:
            break
        quando = agora()
        with engine.begin() as conn:
            for visto in pagina.results:
                if not aceitar(visto.hash_name) or visto.hash_name in vistos:
                    continue
                vistos.add(visto.hash_name)
                anterior = repo.ler_assinatura(conn, visto.hash_name)
                repo.gravar_vista(conn, visto.hash_name, visto.sell_price_usd_cents,
                                  visto.sell_listings, quando)
                if anterior is not None and _assinatura_mudou(anterior, visto):
                    # A assinatura nova já foi gravada acima; se a funda não
                    # terminar nesta rodada, `funda_em is None` faz a próxima
                    # tentar de novo, em vez de perder a mudança por até
                    # `idade_max_funda_h`.
                    repo.marcar_para_funda(conn, visto.hash_name)
                if _precisa_funda(anterior, visto, quando, config):
                    pendentes.append(visto.hash_name)
            resumo.nomes_lidos = len(vistos)
            repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                     fundas_feitas=0, falhas=0)
            repo.atualizar_andamento(
                conn, quando, paginas_busca_lidas=paginas_lidas,
                paginas_busca_total=math.ceil(pagina.total_count / ITENS_POR_PAGINA_DA_BUSCA),
            )
        start += len(pagina.results)
        if start >= pagina.total_count:
            break

    # --- passada funda
    freio.gravar(fase=repo.FASE_PAGINAS, itens_lidos=0, itens_total=len(pendentes))
    for lidos, nome in enumerate(pendentes, start=1):
        motivo = _ler_a_fundo(engine, rodada_id, resumo, nome, freio,
                              retratos=retratos, cotacao=cotacao, agora=agora)
        if motivo is not None:
            return motivo
        freio.gravar(itens_lidos=lidos)
    return repo.MOTIVO_OK


def _ler_a_fundo(
    engine: Engine, rodada_id: int, resumo: Resumo, nome: str, freio: _Freio, *,
    retratos: Any, cotacao: Any, agora: Callable[[], datetime],
) -> str | None:
    """Lê um nome a fundo. Devolve um motivo só quando a rodada deve parar."""
    while True:
        freio.antes_de_requisitar()
        # Relida a cada tentativa (só memória e banco, sem rede): o retrato
        # gravado nos `Retratos` é o mesmo que a consulta mostra, e tem que
        # sair com a taxa atual, não com a do início de uma rodada que dura
        # horas.
        cot = cotacao.obter(engine)
        if cot is None:
            print("[varredura] a cotação da chave sumiu no meio da rodada", flush=True)
            return repo.MOTIVO_ERRO
        quando = agora()
        # Qualquer falha de UM nome (página quebrada, parser, transporte, ou
        # o PostgreSQL recusando um campo longo demais na gravação) conta
        # como falha dele e a rodada segue. Se escapasse, a rodada pararia
        # com "erro" e, como os pendentes seguem a ordem da busca, o mesmo
        # nome travaria todas as rodadas seguintes. O 429 fica FORA destes
        # `try`: ele pausa, não é falha do nome.
        try:
            leitura = retratos.obter(engine, nome, cot.usd_to_brl, quando, forcar=True)
        except Exception as erro:
            _falhou(engine, rodada_id, resumo, nome, erro)
            return None
        if leitura.limitando:
            freio.limitado(f"na página de {nome}")
            continue
        freio.sucesso()
        # Retrato devolvido do banco (piso de `forcar`: alguém acabou de
        # atualizar este item) não é leitura nova. Regravar com ele marcaria
        # como "lido agora" um dado de antes.
        if leitura.pagina is None or leitura.buscado_em != quando:
            return None
        try:
            with engine.begin() as conn:
                repo.substituir_listagens(conn, nome, leitura.pagina.listings, quando)
                repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                         fundas_feitas=resumo.fundas_feitas + 1,
                                         falhas=resumo.falhas)
        except Exception as erro:
            _falhou(engine, rodada_id, resumo, nome, erro)
            return None
        resumo.fundas_feitas += 1
        return None


def _falhou(engine: Engine, rodada_id: int, resumo: Resumo, nome: str, erro: Exception) -> None:
    resumo.falhas += 1
    print(f"[varredura] {nome}: {type(erro).__name__}: {mensagem_saneada(erro)}", flush=True)
    with engine.begin() as conn:
        repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                 fundas_feitas=resumo.fundas_feitas, falhas=resumo.falhas)
