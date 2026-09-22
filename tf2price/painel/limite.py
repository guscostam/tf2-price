"""Freio de envios por chave (hoje, IP), em memória do processo.

Vive só neste processo, como o freio da Steam: coerente com a réplica única
de produção. Um deploy o zera; o teto global de pedidos pendentes cobre essa
janela.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class LimitePorChave:
    def __init__(
        self,
        maximo: int,
        janela_s: float,
        maximo_de_chaves: int = 10_000,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maximo = maximo
        self._janela_s = janela_s
        self._maximo_de_chaves = maximo_de_chaves
        self._relogio = relogio
        self._trava = threading.Lock()
        self._eventos: dict[str, deque[float]] = {}

    def permitir(self, chave: str) -> bool:
        """Registra e devolve True se a chave ainda tem cota; senão, False.

        Sem `maximo_de_chaves`, um atacante que forja uma chave nova a cada
        envio (por exemplo variando o `X-Forwarded-For`) faria a memória
        crescer sem limite; por isso uma chave nova é recusada quando o teto
        já está cheio, enquanto chaves já presentes seguem a cota normal.
        """
        agora = self._relogio()
        vencido = agora - self._janela_s
        with self._trava:
            for outra in list(self._eventos):
                fila = self._eventos[outra]
                while fila and fila[0] <= vencido:
                    fila.popleft()
                if not fila:
                    del self._eventos[outra]
            if chave not in self._eventos and len(self._eventos) >= self._maximo_de_chaves:
                return False
            fila = self._eventos.setdefault(chave, deque())
            if len(fila) >= self._maximo:
                return False
            fila.append(agora)
            return True

    def chaves_ativas(self) -> int:
        with self._trava:
            return len(self._eventos)
