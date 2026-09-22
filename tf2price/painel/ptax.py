"""A PTAX sob demanda, no molde de `CotacaoSobDemanda` (`painel/consulta.py`).

Mesma divisão, e pelo mesmo motivo medido no Railway em 21/09/2026: `obter`
só lê (memória, banco) e é o que as rotas chamam; `renovar` vai à rede e só
o fio de fundo chama. Nenhuma requisição espera o Banco Central.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.engine import Engine

from tf2price.preco import repositorio as preco_repo
from tf2price.saneamento import mensagem_saneada
from tf2price.sources.bcb import BcbClient, Ptax

# A PTAX sai uma vez por dia útil, por volta das 13h. Buscar de hora em hora
# pega a do dia pouco depois de publicada, sem martelar o BC.
VALIDADE_PTAX = timedelta(hours=1)


class PtaxSobDemanda:
    def __init__(
        self,
        bcb: BcbClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bcb = bcb
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._ptax: Ptax | None = None
        self._buscado_em: datetime | None = None
        self._proxima_tentativa = 0.0
        self._trava = threading.Lock()

    def obter(self, engine: Engine) -> Ptax | None:
        """Só lê: memória, depois banco. **Nunca** vai à rede."""
        em_memoria = self._ptax
        if em_memoria is not None:
            return em_memoria
        # `renovar` segura a trava durante a rede; quem chega nesse
        # intervalo não espera o BC, responde com o que há.
        if not self._trava.acquire(blocking=False):
            return self._ptax
        try:
            if self._ptax is None:
                self._do_banco(engine)
            return self._ptax
        finally:
            self._trava.release()

    def renovar(self, engine: Engine, quando: datetime) -> Ptax | None:
        """Busca no BC se o que há está velho. **Só o fundo chama isto.**"""
        with self._trava:
            if self._ptax is None:
                self._do_banco(engine)
            guardada = self._ptax
            if (
                guardada is not None
                and self._buscado_em is not None
                and quando - self._buscado_em <= VALIDADE_PTAX
            ):
                return guardada
            if self._relogio() < self._proxima_tentativa:
                return guardada
            try:
                nova = self._bcb.ptax(quando.date())
            except Exception as erro:
                # Mesmo formato de `_registra_falha_sob_demanda` em
                # `consulta.py`, que não é importada aqui porque `consulta`
                # importa este módulo.
                print(
                    f"[sob-demanda] PtaxSobDemanda: {type(erro).__name__}: "
                    f"{mensagem_saneada(erro)}; nova tentativa em {self._espera:.0f}s",
                    flush=True,
                )
                self._proxima_tentativa = self._relogio() + self._espera
                # A velha, com a data dela à vista, vale mais que nada.
                return guardada

            self._ptax, self._buscado_em = nova, quando
            with engine.begin() as conn:
                preco_repo.guardar_ptax(conn, nova.valor, nova.data, quando)
            print(
                f"[ptax] R$ {nova.valor:.4f} de {nova.data:%d/%m} — guardada",
                flush=True,
            )
            return nova

    def _do_banco(self, engine: Engine) -> None:
        with engine.begin() as conn:
            guardada = preco_repo.ler_ptax(conn)
        if guardada is not None:
            valor, data_cotacao, buscado_em = guardada
            self._ptax = Ptax(valor, data_cotacao)
            self._buscado_em = buscado_em
