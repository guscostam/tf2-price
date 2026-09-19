from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Espaça requisições e registra o que aconteceu.

    Os contadores alimentam a verificação #3 do spec: quantas requisições
    o IP aguenta por minuto antes do primeiro 429. Esse número dimensiona
    o ciclo do projeto completo.
    """

    min_interval_s: float
    requests: int = 0
    throttled: int = 0
    first_429_after: int | None = None
    _last_call: float | None = field(default=None, repr=False, init=False)

    def wait(self) -> None:
        if self._last_call is not None:
            remaining = self.min_interval_s - (time.monotonic() - self._last_call)
            if remaining > 0:
                time.sleep(remaining)
        self._last_call = time.monotonic()
        self.requests += 1

    def record_throttle(self) -> None:
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
