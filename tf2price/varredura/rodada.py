"""Uma rodada da varredura: passada rasa, seleção, passada funda.

A passada rasa lê a busca da Steam (10 nomes por requisição) e guarda, por
nome, o menor preço e o número de listagens, que é a assinatura. A funda abre
a página só dos nomes cuja assinatura mudou, que nunca foram lidos ou cuja
leitura passou do prazo. Numa rodada típica, isso é a busca mais algumas
dezenas de páginas, em vez de mil.

Toda requisição sai do mesmo IP da consulta, e a consulta é o produto. Por
isso a rodada dorme um intervalo extra antes de cada requisição, para com o
primeiro 429 e nunca segura conexão de banco durante a rede.
"""

from __future__ import annotations

import time
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


@dataclass
class Resumo:
    nomes_lidos: int = 0
    fundas_feitas: int = 0
    falhas: int = 0
    motivo: str = repo.MOTIVO_OK


def _precisa_funda(
    anterior: repo.Assinatura | None, visto: SearchResult, quando: datetime, config: repo.Config
) -> bool:
    if anterior is None or anterior.funda_em is None:
        return True
    if (anterior.preco_usd_cents, anterior.n_listagens) != (
        visto.sell_price_usd_cents, visto.sell_listings
    ):
        return True
    return quando - anterior.funda_em > timedelta(hours=config.idade_max_funda_h)


def executar_rodada(
    engine: Engine,
    *,
    steam: Any,
    retratos: Any,
    cotacao: Any,
    agora: Callable[[], datetime] = db.agora,
    dormir: Callable[[float], None] = time.sleep,
    aceitar: Callable[[str], bool] = e_cosmetico_unusual,
    espaco_extra_s: float = ESPACO_EXTRA_S,
) -> Resumo:
    inicio = agora()
    with engine.begin() as conn:
        config = repo.ler_config(conn)
        anterior_completa = repo.ultima_completa(conn)
        rodada_id = repo.abrir_rodada(conn, inicio)

    resumo = Resumo()
    try:
        resumo.motivo = _rodar(
            engine, rodada_id, resumo, config,
            steam=steam, retratos=retratos, cotacao=cotacao,
            agora=agora, dormir=dormir, aceitar=aceitar, espaco_extra_s=espaco_extra_s,
        )
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
        # Só uma rodada COMPLETA viu o mercado inteiro. E um nome some só
        # depois de duas completas sem ele: a busca ordena por preço e leva
        # minutos, e um item cujo preço mudou no meio pode trocar de página e
        # não ser visto uma vez sem ter saído do mercado.
        if resumo.motivo == repo.MOTIVO_OK and anterior_completa is not None:
            repo.apagar_nao_vistos_desde(conn, anterior_completa.inicio)
    print(f"[varredura] rodada {rodada_id}: {resumo.motivo}, {resumo.nomes_lidos} nomes, "
          f"{resumo.fundas_feitas} lidos a fundo, {resumo.falhas} falhas", flush=True)
    return resumo


def _rodar(
    engine: Engine, rodada_id: int, resumo: Resumo, config: repo.Config, *,
    steam: Any, retratos: Any, cotacao: Any,
    agora: Callable[[], datetime], dormir: Callable[[float], None],
    aceitar: Callable[[str], bool], espaco_extra_s: float,
) -> str:
    cot = cotacao.obter(engine)
    if cot is None:
        print("[varredura] sem cotação da chave: a página do item vem em dólar "
              "e não há taxa para converter", flush=True)
        return repo.MOTIVO_ERRO

    # --- passada rasa
    vistos: set[str] = set()
    pendentes: list[str] = []
    start = 0
    for _ in range(MAX_PAGINAS_RASAS):
        if retratos.em_calma():
            return repo.MOTIVO_429
        dormir(espaco_extra_s)
        try:
            pagina = steam.search_page(start=start, query=QUERY)
        except SteamLimitando:
            retratos.acalmar()
            return repo.MOTIVO_429
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
                if _precisa_funda(anterior, visto, quando, config):
                    pendentes.append(visto.hash_name)
            resumo.nomes_lidos = len(vistos)
            repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                     fundas_feitas=0, falhas=0)
        start += len(pagina.results)
        if start >= pagina.total_count:
            break

    # --- passada funda
    for nome in pendentes:
        if retratos.em_calma():
            return repo.MOTIVO_429
        dormir(espaco_extra_s)
        quando = agora()
        try:
            leitura = retratos.obter(engine, nome, cot.usd_to_brl, quando, forcar=True)
        except RuntimeError as erro:  # PageStructureError e falhas de transporte
            resumo.falhas += 1
            print(f"[varredura] {nome}: {type(erro).__name__}: {mensagem_saneada(erro)}", flush=True)
            continue
        if leitura.limitando:
            return repo.MOTIVO_429
        # Retrato devolvido do banco (piso de `forcar`: alguém acabou de
        # atualizar este item) não é leitura nova. Regravar com ele marcaria
        # como "lido agora" um dado de antes.
        if leitura.pagina is None or leitura.buscado_em != quando:
            continue
        with engine.begin() as conn:
            repo.substituir_listagens(conn, nome, leitura.pagina.listings, quando)
            resumo.fundas_feitas += 1
            repo.atualizar_progresso(conn, rodada_id, nomes_lidos=resumo.nomes_lidos,
                                     fundas_feitas=resumo.fundas_feitas, falhas=resumo.falhas)
    return repo.MOTIVO_OK
