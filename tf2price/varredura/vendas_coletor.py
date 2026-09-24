"""Coleta lenta de anúncios ativos, desacoplada da rota do Market Scan."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Protocol

from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.domain.effects import effect_id_for
from tf2price.domain.identity import parse_market_hash_name
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.classificados import ClassificadosLimitando, Venda
from tf2price.sources.ratelimit import backoff_delays
from tf2price.varredura import vendas_repo as repo
from tf2price.varredura.escopo import e_cosmetico_unusual

IDADE_MAXIMA = timedelta(hours=6)
CALMA_FALHA = timedelta(hours=1)
INTERVALO_CHAMADAS_S = 20.0
PERIODO_S = 60.0


class ClienteVendas(Protocol):
    def vendas(self, sku: str, effect_id: int, item_name: str) -> SnapshotLido: ...


class SnapshotLido(Protocol):
    vendas: tuple[Venda, ...]
    criado_em: datetime


class VendasColetor:
    def __init__(
        self,
        engine: Engine,
        client: ClienteVendas,
        *,
        key_in_refined: Callable[[], Decimal | None],
        agora: Callable[[], datetime] = db.agora,
        esperar: Callable[[float], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        backoff: Callable[[int], float] | None = None,
    ) -> None:
        self._engine = engine
        self._client = client
        self._key_in_refined = key_in_refined
        self._agora = agora
        self._esperar = esperar
        self._monotonic = monotonic
        self._backoff = backoff or (lambda n: backoff_delays(n, base=30.0, cap=300.0)[-1])
        self._ultima_chamada: float | None = None
        self._falhas_seguidas = 0

    def _espera(self, parar: threading.Event, segundos: float) -> bool:
        return (self._esperar or parar.wait)(max(0.0, segundos))

    def _aguardar_intervalo(self, parar: threading.Event) -> bool:
        if self._ultima_chamada is None:
            return False
        restante = INTERVALO_CHAMADAS_S - (self._monotonic() - self._ultima_chamada)
        return restante > 0 and self._espera(parar, restante)

    def rodar_uma_passada(self, parar: threading.Event) -> None:
        agora = self._agora()
        with self._engine.begin() as conn:
            pares = repo.pares_recentes(conn, agora - IDADE_MAXIMA)
            cache = repo.ler_todas(conn)
        for hash_name, efeito in pares:
            if parar.is_set():
                return
            taxa_original = self._key_in_refined()
            taxa = Decimal(str(taxa_original)) if taxa_original is not None else None
            anterior = cache.get((hash_name, efeito))
            if anterior is not None:
                taxa_compativel = (
                    anterior.estado != repo.ENCONTRADO
                    or (taxa is not None and anterior.metal_por_chave == taxa)
                )
                if (taxa_compativel and anterior.buscado_em is not None
                        and agora - anterior.buscado_em < IDADE_MAXIMA):
                    continue
                if anterior.falhou_em is not None and agora - anterior.falhou_em < CALMA_FALHA:
                    continue
            if not e_cosmetico_unusual(hash_name):
                continue
            identidade = parse_market_hash_name(hash_name)
            nome_base = identidade.base_name
            efeito_id = effect_id_for(efeito)
            if not nome_base or efeito_id is None:
                continue
            sku = f"{efeito} {nome_base}"
            if self._aguardar_intervalo(parar):
                return
            self._ultima_chamada = self._monotonic()
            try:
                snapshot = self._client.vendas(sku, efeito_id, nome_base)
                menor = self._menor(snapshot.vendas, taxa)
            except ClassificadosLimitando as erro:
                with self._engine.begin() as conn:
                    repo.gravar_falha(conn, hash_name, efeito, self._agora())
                self._falhas_seguidas += 1
                self._espera(parar, max(
                    INTERVALO_CHAMADAS_S,
                    erro.retry_after_s or 0.0,
                    self._backoff(self._falhas_seguidas),
                ))
                return
            except Exception:
                with self._engine.begin() as conn:
                    repo.gravar_falha(conn, hash_name, efeito, self._agora())
                self._falhas_seguidas += 1
                if self._espera(parar, max(INTERVALO_CHAMADAS_S, self._backoff(self._falhas_seguidas))):
                    return
                continue
            self._falhas_seguidas = 0
            with self._engine.begin() as conn:
                if menor is None:
                    repo.gravar_sucesso(conn, hash_name, efeito, None, None, snapshot.criado_em)
                else:
                    repo.gravar_sucesso(
                        conn, hash_name, efeito, menor.chaves, menor.metal,
                        snapshot.criado_em, metal_por_chave=taxa,
                    )

    def _menor(self, vendas: tuple[Venda, ...], taxa: Decimal | None) -> Venda | None:
        if not vendas:
            return None
        if taxa is None or not taxa.is_finite() or taxa <= 0:
            raise ValueError("cotação metal/chave indisponível")
        return min(vendas, key=lambda v: v.chaves + v.metal / taxa)

    def ciclo(self, parar: threading.Event, periodo_s: float = PERIODO_S) -> None:
        while not parar.is_set():
            try:
                self.rodar_uma_passada(parar)
            except Exception as erro:
                print(f"[vendas] coletor: {type(erro).__name__}: "
                      f"{mensagem_saneada(erro)}", flush=True)
            if self._espera(parar, periodo_s):
                return
