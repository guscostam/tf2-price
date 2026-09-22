"""Quando rodar a varredura, e nunca duas ao mesmo tempo.

Vive no processo do painel, num thread daemon, como o aquecimento da
cotação. Isso só é seguro com uma réplica (AGENTS.md): trava e calma são da
memória deste processo.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine

from tf2price import db
from tf2price.saneamento import mensagem_saneada
from tf2price.varredura import repositorio as repo
from tf2price.varredura.rodada import executar_rodada

# De quanto em quanto tempo o fundo acorda para olhar a configuração. Não é o
# intervalo das rodadas: esse vem do painel admin.
PERIODO_S = 60.0


class Agendador:
    def __init__(
        self,
        engine: Engine,
        rodar: Callable[[threading.Event], Any],
        agora: Callable[[], datetime] = db.agora,
    ) -> None:
        self._engine = engine
        self._rodar = rodar
        self._agora = agora
        # Adquirida sem bloquear, por quem vai rodar. `Lock` (e não `RLock`)
        # porque "Run now" a adquire no thread da requisição e a solta no
        # thread da rodada.
        self._trava = threading.Lock()
        # Um evento por rodada: `parar_rodada` o liga, e a rodada o usa como
        # espera (`Event.wait` devolve verdadeiro quando foi ligado).
        self._cancelar = threading.Event()

    @property
    def rodando(self) -> bool:
        return self._trava.locked()

    def vencida(self) -> bool:
        with self._engine.begin() as conn:
            config = repo.ler_config(conn)
            ultima = repo.ultima_rodada(conn)
        if not config.ligada:
            return False
        if ultima is None:
            return True
        # Conta do FIM da última rodada: a primeira lê ~1000 páginas e dura
        # mais que o intervalo; contado do início, a seguinte sairia logo em
        # seguida e o piso que protege a consulta do 429 não valeria nada.
        # Rodada ainda aberta (sem fim) já é barrada pela trava.
        referencia = ultima.fim or ultima.inicio
        return self._agora() - referencia >= timedelta(minutes=config.intervalo_min)

    def _comecar(self) -> bool:
        if not self._trava.acquire(blocking=False):
            return False
        # Criado ANTES de soltar o thread: um Stop que chegue antes de a
        # rodada começar ainda cai no evento dela, e não no da anterior.
        self._cancelar = threading.Event()
        return True

    def tentar_rodar(self) -> bool:
        """Roda no thread de quem chamou. Falso se já havia rodada em curso."""
        if not self._comecar():
            return False
        self._executar_segurando()
        return True

    def disparar_em_segundo_plano(self) -> bool:
        """Para o "Run now": a requisição volta na hora, a rodada leva minutos."""
        if not self._comecar():
            return False
        threading.Thread(
            target=self._executar_segurando, name="varredura-manual", daemon=True
        ).start()
        return True

    def parar_rodada(self) -> bool:
        """Para o "Stop scan". Falso se não havia rodada. A rodada atende na
        próxima espera: no máximo uma requisição depois, ou no meio da pausa."""
        if not self.rodando:
            return False
        self._cancelar.set()
        return True

    def _executar_segurando(self) -> None:
        try:
            self._rodar(self._cancelar)
        finally:
            self._trava.release()

    def ciclo(self, parar: threading.Event, periodo_s: float = PERIODO_S) -> None:
        while not parar.wait(periodo_s):
            try:
                if self.vencida():
                    self.tentar_rodar()
            except Exception as erro:
                # Um bug numa rodada não pode matar o agendador para sempre:
                # ninguém veria, e a página só envelheceria.
                print(f"[varredura] agendador: {type(erro).__name__}: "
                      f"{mensagem_saneada(erro)}", flush=True)


def construir_agendador(engine: Engine, contexto: Any) -> Agendador:
    def rodar(cancelar: threading.Event):
        return executar_rodada(
            engine,
            steam=contexto.steam,
            retratos=contexto.retratos,
            cotacao=contexto.cotacao,
            esperar=cancelar.wait,
        )

    return Agendador(engine, rodar)


def iniciar_em_segundo_plano(agendador: Agendador) -> threading.Thread:
    thread = threading.Thread(
        target=agendador.ciclo, args=(threading.Event(),), name="varredura", daemon=True
    )
    thread.start()
    return thread
