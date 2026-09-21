from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Espaça requisições e registra o que aconteceu.

    Os contadores alimentam a verificação #3 do spec: quantas requisições
    o IP aguenta por minuto antes do primeiro 429. Esse número dimensiona
    o ciclo do projeto completo.

    Um limitador é compartilhado por todas as requisições do painel (nasce
    uma vez em `construir_contexto`), e as rotas da consulta são `def`
    síncrono — o uvicorn as roda num pool de threads, em paralelo de
    verdade. Por isso a trava: sem ela, duas threads leem o mesmo
    `_last_call`, dormem o mesmo intervalo ao mesmo tempo e saem juntas
    para a Steam, que é exatamente o que o espaçamento existe para impedir.
    """

    min_interval_s: float
    requests: int = 0
    throttled: int = 0
    first_429_after: int | None = None
    _last_call: float | None = field(default=None, repr=False, init=False)
    _trava: threading.Lock = field(
        default_factory=threading.Lock, repr=False, init=False, compare=False
    )

    def wait(self) -> None:
        # A trava fica presa durante o `sleep`, de propósito: serializar os
        # chamadores é o serviço prestado. Cada um acorda, marca a sua vez e
        # só então libera o seguinte, que passa a contar o intervalo dele a
        # partir daí.
        with self._trava:
            if self._last_call is not None:
                remaining = self.min_interval_s - (time.monotonic() - self._last_call)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_call = time.monotonic()
            self.requests += 1

    def record_throttle(self) -> None:
        # `+=` não é atômico (lê, soma, grava): sem a trava, dois 429 no
        # mesmo instante contam como um.
        with self._trava:
            self.throttled += 1
            if self.first_429_after is None:
                self.first_429_after = self.requests


def backoff_delays(attempts: int, base: float = 2.0, cap: float = 120.0) -> list[float]:
    """Atrasos exponenciais com jitter, como função pura.

    Pura para ser testável sem dormir de verdade. O jitter fica entre 50% e
    100% do valor bruto: espalha as tentativas sem nunca colapsar o atraso
    para perto de zero, que é o que transformaria o backoff em martelada.
    """
    delays: list[float] = []
    for attempt in range(attempts):
        raw = min(cap, base * (2**attempt))
        delays.append(raw * (0.5 + random.random() * 0.5))
    return delays
