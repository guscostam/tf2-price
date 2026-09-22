"""O retrato compartilhado de um item: validade, força e calma após 429.

Esta é a única peça que pede a página da Steam. Ela existe porque a Steam
limita por IP, e no Railway todo mundo sai pelo mesmo IP: sem um retrato
compartilhado, dez pessoas olhando o mesmo chapéu custariam dez requisições.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.engine import Engine

from tf2price.preco import repositorio as repo
from tf2price.preco import serial
from tf2price.sources.steam_page import ItemPage, SteamLimitando
from tf2price.saneamento import mensagem_saneada

VALIDADE = timedelta(minutes=15)
# Sem piso, segurar o botão de atualizar vira enxurrada na Steam.
PISO_PARA_FORCAR = timedelta(seconds=60)
CALMA_APOS_429 = timedelta(minutes=5)


@dataclass(frozen=True)
class Leitura:
    """O retrato e o que a tela precisa dizer sobre ele.

    `buscado_em` nunca é escondido: a idade do dado é a regra que governa
    este projeto, e agora vale também para o que veio da Steam.
    """

    pagina: ItemPage | None
    buscado_em: datetime | None
    limitando: bool


class Retratos:
    def __init__(
        self,
        paginas: Any,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._paginas = paginas
        self._relogio = relogio
        # De processo, não de banco: a spec assume uma réplica só, e está
        # escrito lá. Duas réplicas partiriam este freio ao meio.
        self._calma_ate = 0.0
        self._ultima_busca: dict[str, float] = {}

    def obter(
        self,
        engine: Engine,
        hash_name: str,
        usd_to_brl: float,
        quando: datetime,
        forcar: bool = False,
    ) -> Leitura:
        """Recebe o `engine`, e não uma conexão, de propósito.

        A busca na Steam leva segundos. Duas transações curtas — uma para ler,
        outra para gravar — com a busca **entre** elas é o que mantém zero
        conexões emprestadas durante a rede, que é o que o Postgres do Railway
        exige e o que `test_transacao.py` mede.
        """
        with engine.begin() as conn:
            guardado = repo.ler(conn, hash_name)
        pagina, buscado_em = None, None
        if guardado is not None:
            dados, buscado_em = guardado
            try:
                pagina = serial.de_dict(json.loads(dados))
            except (ValueError, KeyError, TypeError):
                # Retrato de uma forma antiga: descartar é mais honesto que
                # ler torto, e a próxima busca regrava.
                pagina, buscado_em = None, None

        if not self._vale_buscar(hash_name, buscado_em, quando, forcar):
            return Leitura(pagina, buscado_em, self.em_calma())

        try:
            nova = self._paginas.item_page(hash_name, usd_to_brl)
        except SteamLimitando as erro:
            # Pelo TIPO, não farejando "429" na mensagem: essa string podia
            # vir de um preço, um id de listagem ou um nome de item e ligar
            # a calma à toa, e um 429 real podia perder a marca na mensagem
            # final do backoff (que só guarda a última tentativa) e nunca
            # ligar a calma. `SteamLimitando` já resolveu isso no laço.
            self.acalmar()
            print(f"[retrato] Steam limitando: {mensagem_saneada(erro)}; calma de "
                  f"{int(CALMA_APOS_429.total_seconds())}s", flush=True)
            return Leitura(pagina, buscado_em, True)

        self._ultima_busca[hash_name] = self._relogio()
        with engine.begin() as conn:
            repo.guardar(conn, hash_name, json.dumps(serial.para_dict(nova)), quando)
        return Leitura(nova, quando, False)

    def em_calma(self) -> bool:
        return self._relogio() < self._calma_ate

    def acalmar(self) -> None:
        """Liga a calma por fora. A varredura chama isto quando a BUSCA da
        Steam (não a página) responde 429: é o mesmo IP, e a consulta que
        viesse logo depois bateria no mesmo limite."""
        self._calma_ate = self._relogio() + CALMA_APOS_429.total_seconds()

    def calma_restante_s(self) -> float:
        """Quanto falta da calma, em segundos. A varredura espera isto antes
        de requisitar quando a calma foi ligada por outro (um usuário)."""
        return max(0.0, self._calma_ate - self._relogio())

    def _vale_buscar(
        self,
        hash_name: str,
        buscado_em: datetime | None,
        quando: datetime,
        forcar: bool,
    ) -> bool:
        if self.em_calma():
            return False
        if forcar:
            ultima = self._ultima_busca.get(hash_name)
            return ultima is None or self._relogio() - ultima >= PISO_PARA_FORCAR.total_seconds()
        if buscado_em is None:
            return True
        return quando - buscado_em > VALIDADE
