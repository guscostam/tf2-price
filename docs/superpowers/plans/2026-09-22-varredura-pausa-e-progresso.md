# Varredura: pausa no 429, progresso e poda — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A rodada da varredura pausa e retoma no 429 em vez de desistir, o admin vê o progresso ao vivo e pode interromper a rodada, e o histórico de rodadas se poda sozinho.

**Architecture:** A rodada ganha um `_Freio` interno que concentra espera entre requisições, calma, pausa crescente, retomada e cancelamento. A espera passa a ser uma função `esperar(segundos) -> bool` (cancelada?), que em produção é o `threading.Event.wait` de cada rodada, criado pelo `Agendador`. O andamento ao vivo vai para uma tabela nova de uma linha, `varredura_andamento`, lida por um fragmento HTMX no `/admin` que se atualiza a cada 5 s.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 + HTMX 1.9.12, SQLAlchemy Core (SQLite nos testes, PostgreSQL em produção), pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-varredura-pausa-e-progresso-design.md`

## Global Constraints

- Leia `AGENTS.md` antes de começar. Valem todos os invariantes dele.
- Nenhum import e nenhum teste acessa a rede ou dorme de verdade. Relógio, espera e clientes são injetados.
- Nenhuma conexão ou transação de banco fica aberta durante uma requisição ou uma espera.
- Instantes em UTC ingênuo (`db.agora()`). SQL só nos módulos `repositorio.py`. Sem `ON CONFLICT`/`MERGE`, e nada que só um dialeto aceite.
- `create_all` não acrescenta colunas a tabelas existentes: dado novo vai em **tabela nova**.
- Interface em inglês; nenhum texto em português chega à tela. A paleta do CSS só admite as 7 cores hex da marca (`tests/painel/test_branding.py`).
- Rotas mutáveis exigem `Depends(ses.mesma_origem)`; rotas do admin exigem `ses.exigir_admin`.
- Valores exatos: pausas `PAUSAS_MIN = (5, 10, 20, 30)` minutos (a 4ª em diante usa 30); `MAX_PAUSAS_SEGUIDAS = 4`; `MANTER_RODADAS = 20`; polling `every 5s`; motivo novo `MOTIVO_CANCELADA = "cancelada"` com rótulo `"Stopped by admin"`.
- Log de pausa, exatamente neste formato: `[varredura] rodada {id}: 429 {onde}; pausa {n} de 4, até {HH:MM} UTC`, com `{onde}` sendo `na cotação do dólar`, `na busca (página {n})` ou `na página de {hash_name}`.
- Comandos (PowerShell, na raiz): teste focado `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_rodada.py -v`; suíte `.\.venv\Scripts\python.exe -m pytest -p no:warnings; echo $LASTEXITCODE` (o `pyproject` já põe `-q`; leia o código de saída).
- Mensagem de commit em português, terminando com:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WstGxhhpa1wsEBwaCqjWJ1
  ```

## Decisões que refinam a spec

1. **Pausa não é uma fase.** A spec lista `pausada` entre as fases. No plano, a fase continua sendo a do trabalho em curso (`cotacao`, `busca`, `paginas`) e a pausa é `pausado_ate` não nulo. Assim a tela sabe de qual fase a rodada vai voltar ("Reading item pages · Paused…"). A Task 4 registra isso na spec.
2. **O teto de páginas conta páginas lidas**, não tentativas: uma retomada depois de pausa não gasta o teto.
3. **`itens_lidos` conta nomes processados** (lidos, pulados por retrato antigo ou com falha), para a barra chegar ao fim.

---

## Mapa de arquivos

| Arquivo | Mudança |
|---|---|
| `tf2price/db.py` | tabela `varredura_andamento` |
| `tf2price/varredura/repositorio.py` | `MOTIVO_CANCELADA`, fases, `Andamento` e funções, `podar_rodadas`, `fechar_abertas` limpa o andamento |
| `tf2price/preco/retrato.py` | `Retratos.calma_restante_s()` |
| `tf2price/varredura/rodada.py` | reescrita com `_Freio`: pausa, retomada, cancelamento, andamento, poda |
| `tf2price/varredura/agendador.py` | evento de cancelamento por rodada, `parar_rodada()`, `rodar(cancelar)` |
| `tf2price/painel/varredura.py` | rótulo "Stopped by admin", `ha_quanto_tempo` |
| `tf2price/painel/admin.py` | rotas `GET /admin/varredura/andamento` e `POST /admin/varredura/parar` |
| `tf2price/painel/templates/_varredura_andamento.html` (novo), `admin.html` | bloco "Current scan" |
| `tf2price/painel/static/briefcase.css` | `.scan-progress` |
| testes | `tests/varredura/test_repositorio.py`, `test_rodada.py` (reescrito), `test_agendador.py`, `tests/preco/test_retrato.py`, `tests/painel/test_admin_varredura.py` |

---

### Task 1: Dados — andamento, poda, cancelada e calma restante

**Files:**
- Modify: `tf2price/db.py` (depois de `varredura_rodada`)
- Modify: `tf2price/varredura/repositorio.py`
- Modify: `tf2price/preco/retrato.py` (classe `Retratos`)
- Test: `tests/varredura/test_repositorio.py`, `tests/preco/test_retrato.py`

**Interfaces:**
- Produces (em `tf2price.varredura.repositorio`):
  - `MOTIVO_CANCELADA = "cancelada"`; `FASE_COTACAO = "cotacao"`, `FASE_BUSCA = "busca"`, `FASE_PAGINAS = "paginas"`; `MANTER_RODADAS = 20`
  - `Andamento(rodada_id: int, fase: str, paginas_busca_lidas: int, paginas_busca_total: int | None, itens_lidos: int, itens_total: int | None, pausado_ate: datetime | None, pausas_seguidas: int, atualizado_em: datetime)`
  - `iniciar_andamento(conn, rodada_id, quando) -> None`; `atualizar_andamento(conn, quando, **campos) -> None` (levanta `TypeError` para campo desconhecido); `ler_andamento(conn) -> Andamento | None`; `limpar_andamento(conn) -> None`
  - `podar_rodadas(conn, manter: int = MANTER_RODADAS) -> int`
  - `fechar_abertas(conn, quando) -> int` passa a também limpar o andamento
- Produces (em `tf2price.preco.retrato.Retratos`): `calma_restante_s() -> float`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/varredura/test_repositorio.py`:

```python
def test_andamento_nasce_zerado_atualiza_e_some(engine):
    with engine.begin() as conn:
        assert repo.ler_andamento(conn) is None
        rid = repo.abrir_rodada(conn, T0)
        repo.iniciar_andamento(conn, rid, T0)
        assert repo.ler_andamento(conn) == repo.Andamento(
            rodada_id=rid, fase=repo.FASE_COTACAO, paginas_busca_lidas=0,
            paginas_busca_total=None, itens_lidos=0, itens_total=None,
            pausado_ate=None, pausas_seguidas=0, atualizado_em=T0,
        )
        depois = T0 + timedelta(minutes=1)
        repo.atualizar_andamento(conn, depois, fase=repo.FASE_PAGINAS, itens_lidos=3,
                                 itens_total=10, pausado_ate=depois, pausas_seguidas=1)
        andamento = repo.ler_andamento(conn)
        assert (andamento.fase, andamento.itens_lidos, andamento.itens_total) == ("paginas", 3, 10)
        assert (andamento.pausado_ate, andamento.pausas_seguidas, andamento.atualizado_em) == (depois, 1, depois)
        repo.limpar_andamento(conn)
        assert repo.ler_andamento(conn) is None


def test_iniciar_andamento_substitui_o_de_outra_rodada(engine):
    with engine.begin() as conn:
        repo.iniciar_andamento(conn, 1, T0)
        repo.atualizar_andamento(conn, T0, itens_lidos=7)
        repo.iniciar_andamento(conn, 2, T0)
        andamento = repo.ler_andamento(conn)
        assert (andamento.rodada_id, andamento.itens_lidos) == (2, 0)


def test_atualizar_andamento_recusa_campo_desconhecido(engine):
    with engine.begin() as conn:
        repo.iniciar_andamento(conn, 1, T0)
        with pytest.raises(TypeError):
            repo.atualizar_andamento(conn, T0, fase_errada="x")


def test_fechar_abertas_limpa_o_andamento(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, T0)
        repo.iniciar_andamento(conn, rid, T0)
        repo.fechar_abertas(conn, T0)
        assert repo.ler_andamento(conn) is None


def _rodadas_terminadas(conn, n, motivo=repo.MOTIVO_429, a_partir=T0):
    ids = []
    for i in range(n):
        quando = a_partir + timedelta(hours=i)
        rid = repo.abrir_rodada(conn, quando)
        repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=motivo)
        ids.append(rid)
    return ids


def test_podar_guarda_as_20_mais_recentes(engine):
    with engine.begin() as conn:
        ids = _rodadas_terminadas(conn, 25)
        assert repo.podar_rodadas(conn) == 5
        assert [r.id for r in repo.ultimas_rodadas(conn, 100)] == list(reversed(ids[5:]))


def test_podar_guarda_a_ultima_completa_mesmo_antiga(engine):
    with engine.begin() as conn:
        (completa,) = _rodadas_terminadas(conn, 1, motivo=repo.MOTIVO_OK,
                                          a_partir=T0 - timedelta(days=5))
        _rodadas_terminadas(conn, 25)
        repo.podar_rodadas(conn)
        restantes = {r.id for r in repo.ultimas_rodadas(conn, 100)}
    assert completa in restantes
    assert len(restantes) == repo.MANTER_RODADAS + 1


def test_podar_nunca_apaga_a_rodada_aberta(engine):
    with engine.begin() as conn:
        aberta = repo.abrir_rodada(conn, T0 - timedelta(days=9))
        _rodadas_terminadas(conn, 25)
        repo.podar_rodadas(conn)
        assert aberta in {r.id for r in repo.ultimas_rodadas(conn, 100)}
```

Confira que `import pytest` e `from datetime import timedelta` já estão no topo do arquivo (estão).

Acrescente a `tests/preco/test_retrato.py`:

```python
def test_calma_restante_conta_para_baixo(engine):
    relogio = _Relogio()
    retratos = mod.Retratos(_PaginasFalsas(), relogio=relogio)
    assert retratos.calma_restante_s() == 0.0

    retratos.acalmar()
    assert retratos.calma_restante_s() == mod.CALMA_APOS_429.total_seconds()

    relogio.avancar(100)
    assert retratos.calma_restante_s() == mod.CALMA_APOS_429.total_seconds() - 100

    relogio.avancar(10_000)
    assert retratos.calma_restante_s() == 0.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_repositorio.py tests\preco\test_retrato.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'ler_andamento'`, `'Retratos' object has no attribute 'calma_restante_s'`)

- [ ] **Step 3: Tabela nova em `tf2price/db.py`**

Depois da tabela `varredura_rodada`:

```python
varredura_andamento = Table(
    "varredura_andamento",
    METADATA,
    # Uma linha só (id 1): o andamento da rodada em curso, que o admin lê a
    # cada 5 s. Tabela própria, e não colunas em `varredura_rodada`, porque
    # `create_all` não acrescenta colunas a uma tabela que já existe.
    Column("id", Integer, primary_key=True),
    Column("rodada_id", Integer, nullable=False),
    Column("fase", String(20), nullable=False),
    Column("paginas_busca_lidas", Integer, nullable=False),
    Column("paginas_busca_total", Integer, nullable=True),
    Column("itens_lidos", Integer, nullable=False),
    Column("itens_total", Integer, nullable=True),
    # Não nulo = pausada depois de um 429, até este instante (UTC).
    Column("pausado_ate", DateTime, nullable=True),
    Column("pausas_seguidas", Integer, nullable=False),
    Column("atualizado_em", DateTime, nullable=False),
)
```

- [ ] **Step 4: Repositório**

Em `tf2price/varredura/repositorio.py`:

1. Junto dos outros motivos, acrescente `MOTIVO_CANCELADA = "cancelada"`.
2. Troque `fechar_abertas` por:

```python
def fechar_abertas(conn: Connection, quando: datetime) -> int:
    """Na subida: rodada sem fim é de um processo que morreu no meio dela, e o
    andamento dela não descreve mais nada que esteja acontecendo."""
    t = db.varredura_rodada
    fechadas = conn.execute(
        update(t).where(t.c.fim.is_(None)).values(fim=quando, motivo_parada=MOTIVO_INTERROMPIDA)
    ).rowcount
    limpar_andamento(conn)
    return fechadas
```

3. Depois de `ultima_completa`, acrescente:

```python
MANTER_RODADAS = 20


def podar_rodadas(conn: Connection, manter: int = MANTER_RODADAS) -> int:
    """Apaga rodadas terminadas antigas. Ficam as `manter` mais recentes e a
    última completa, mesmo antiga: é o início dela que decide quais nomes
    sumiram do mercado (`executar_rodada`). Rodada aberta nunca sai.

    Os ids a guardar são lidos antes, em Python, para o DELETE não depender
    de LIMIT dentro de subconsulta, que cada dialeto trata de um jeito.
    """
    t = db.varredura_rodada
    guardar = {i for (i,) in conn.execute(
        select(t.c.id).order_by(t.c.inicio.desc(), t.c.id.desc()).limit(manter)
    )}
    completa = ultima_completa(conn)
    if completa is not None:
        guardar.add(completa.id)
    consulta = delete(t).where(t.c.fim.is_not(None))
    if guardar:
        consulta = consulta.where(t.c.id.not_in(guardar))
    return conn.execute(consulta).rowcount


# --- andamento da rodada em curso ------------------------------------------

FASE_COTACAO = "cotacao"
FASE_BUSCA = "busca"
FASE_PAGINAS = "paginas"
LINHA_DO_ANDAMENTO = 1

_CAMPOS_DO_ANDAMENTO = frozenset({
    "fase", "paginas_busca_lidas", "paginas_busca_total", "itens_lidos",
    "itens_total", "pausado_ate", "pausas_seguidas",
})


@dataclass(frozen=True)
class Andamento:
    rodada_id: int
    fase: str
    paginas_busca_lidas: int
    paginas_busca_total: int | None
    itens_lidos: int
    itens_total: int | None
    pausado_ate: datetime | None
    pausas_seguidas: int
    atualizado_em: datetime


def iniciar_andamento(conn: Connection, rodada_id: int, quando: datetime) -> None:
    t = db.varredura_andamento
    conn.execute(delete(t))
    conn.execute(insert(t).values(
        id=LINHA_DO_ANDAMENTO, rodada_id=rodada_id, fase=FASE_COTACAO,
        paginas_busca_lidas=0, paginas_busca_total=None, itens_lidos=0,
        itens_total=None, pausado_ate=None, pausas_seguidas=0, atualizado_em=quando,
    ))


def atualizar_andamento(conn: Connection, quando: datetime, **campos) -> None:
    desconhecidos = set(campos) - _CAMPOS_DO_ANDAMENTO
    if desconhecidos:
        raise TypeError(f"campos de andamento desconhecidos: {sorted(desconhecidos)}")
    t = db.varredura_andamento
    conn.execute(
        update(t).where(t.c.id == LINHA_DO_ANDAMENTO).values(**campos, atualizado_em=quando)
    )


def ler_andamento(conn: Connection) -> Andamento | None:
    t = db.varredura_andamento
    linha = conn.execute(select(t).where(t.c.id == LINHA_DO_ANDAMENTO)).first()
    if linha is None:
        return None
    return Andamento(
        rodada_id=int(linha.rodada_id),
        fase=linha.fase,
        paginas_busca_lidas=int(linha.paginas_busca_lidas),
        paginas_busca_total=linha.paginas_busca_total,
        itens_lidos=int(linha.itens_lidos),
        itens_total=linha.itens_total,
        pausado_ate=linha.pausado_ate,
        pausas_seguidas=int(linha.pausas_seguidas),
        atualizado_em=linha.atualizado_em,
    )


def limpar_andamento(conn: Connection) -> None:
    conn.execute(delete(db.varredura_andamento))
```

- [ ] **Step 5: `Retratos.calma_restante_s`**

Em `tf2price/preco/retrato.py`, logo depois de `em_calma`:

```python
    def calma_restante_s(self) -> float:
        """Quanto falta da calma, em segundos. A varredura espera isto antes
        de requisitar quando a calma foi ligada por outro (um usuário)."""
        return max(0.0, self._calma_ate - self._relogio())
```

- [ ] **Step 6: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_repositorio.py tests\preco\test_retrato.py tests\test_db.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tf2price/db.py tf2price/varredura/repositorio.py tf2price/preco/retrato.py tests/varredura/test_repositorio.py tests/preco/test_retrato.py
git commit -m "Guarda o andamento da rodada, poda o historico e expoe a calma restante"
```

---

### Task 2: A rodada pausa, retoma e pode ser cancelada

**Files:**
- Modify (reescrita completa): `tf2price/varredura/rodada.py`
- Modify (reescrita completa): `tests/varredura/test_rodada.py`

**Interfaces:**
- Consumes: Task 1 (`MOTIVO_CANCELADA`, fases, `iniciar_andamento`, `atualizar_andamento`, `limpar_andamento`, `podar_rodadas`; `Retratos.calma_restante_s`); o existente `SteamClient.usd_to_brl()` (levanta `SteamLimitando` em 429).
- Produces:
  - `PAUSAS_MIN = (5, 10, 20, 30)`, `MAX_PAUSAS_SEGUIDAS = 4`, `ITENS_POR_PAGINA_DA_BUSCA = 10`
  - `executar_rodada(engine, *, steam, retratos, cotacao, agora=db.agora, esperar=_esperar_sem_cancelamento, aceitar=e_cosmetico_unusual, espaco_extra_s=ESPACO_EXTRA_S) -> Resumo`. **O parâmetro `dormir` deixa de existir.** `esperar(segundos) -> bool` devolve `True` quando a rodada foi cancelada; em produção é `threading.Event.wait`.
  - O `retratos` recebido precisa de `em_calma()`, `calma_restante_s()`, `acalmar()`, `obter(...)`.

O arquivo de teste é reescrito porque todos os testes dependiam de `dormir` e de "429 para a rodada", que deixa de ser verdade. Os testes antigos cujo comportamento não muda estão abaixo, só com os dublês novos.

- [ ] **Step 1: Reescrever `tests/varredura/test_rodada.py`**

Substitua o arquivo inteiro por:

```python
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import event

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.preco.retrato import Leitura
from tf2price.sources.ratelimit import SteamLimitando
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, PageStructureError
from tf2price.varredura import repositorio as repo
from tf2price.varredura import rodada as rodada_mod
from tf2price.varredura.rodada import (
    ESPACO_EXTRA_S, MAX_PAUSAS_SEGUIDAS, QUERY, executar_rodada,
)

T0 = db.agora()
CALMA_S = 300.0


class _Tempo:
    """Relógio simulado: `esperar` avança o tempo na hora, sem dormir.

    `cancelar_se(segundos)` decide se a espera volta cancelada, que é o que
    `threading.Event.wait` devolve quando o admin aperta Stop. `ao_esperar`
    deixa o teste olhar o banco no meio de uma espera, antes de o tempo andar.
    """

    def __init__(self, inicio=T0, cancelar_se=None, ao_esperar=None):
        self.inicio = inicio
        self.s = 0.0
        self.esperas: list[float] = []
        self.cancelar_se = cancelar_se
        self.ao_esperar = ao_esperar

    def agora(self):
        return self.inicio + timedelta(seconds=self.s)

    def esperar(self, segundos):
        self.esperas.append(segundos)
        if self.ao_esperar is not None:
            self.ao_esperar(segundos)
        self.s += segundos
        return bool(self.cancelar_se and self.cancelar_se(segundos))

    def pausas(self):
        return [e for e in self.esperas if e >= 60]


def _aceitar(nome: str) -> bool:
    return nome.startswith("Unusual ") and "Taunt" not in nome


def _r(nome, usd=1000, n=1):
    return SearchResult(hash_name=nome, lowest_price=Brl(usd * 5), sell_listings=n,
                        sell_price_usd_cents=usd)


def _pagina(nome, *listagens):
    return ItemPage(
        hash_name=nome,
        listings=[PageListing(i, Brl(c), e, None) for i, c, e in listagens],
        orderbook=OrderBook(None, None, 0, 0),
        history=[],
    )


class _Steam:
    """Busca falsa: fatia a lista de 10 em 10, como a Steam real.

    `limitar_busca={start: n}` responde 429 nas n primeiras tentativas
    daquele `start`; `usd_limitado=n` faz o mesmo com a cotação do dólar.
    """

    def __init__(self, resultados, limitar_busca=None, erro_no_start=None, erro=None,
                 usd_limitado=0, contador=None, ao_buscar=None):
        self.resultados = list(resultados)
        self.limitar_busca = dict(limitar_busca or {})
        self.erro_no_start = erro_no_start
        self.erro = erro or RuntimeError("HTTP 500")
        self.usd_limitado = usd_limitado
        self.contador = contador
        self.ao_buscar = ao_buscar
        self.chamadas = []
        self.usd_chamadas = 0
        self.emprestadas = []

    def usd_to_brl(self):
        self.usd_chamadas += 1
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.usd_limitado > 0:
            self.usd_limitado -= 1
            raise SteamLimitando("429")
        return 5.0

    def search_page(self, start=0, count=100, query=None):
        self.chamadas.append((start, query))
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.ao_buscar is not None:
            self.ao_buscar(start)
        if self.limitar_busca.get(start, 0) > 0:
            self.limitar_busca[start] -= 1
            raise SteamLimitando("429")
        if start == self.erro_no_start:
            raise self.erro
        return SearchPage(total_count=len(self.resultados),
                          results=self.resultados[start:start + 10])


class _Retratos:
    """`limitar={nome: n}` devolve a leitura em calma (429) nas n primeiras
    tentativas daquele nome, ligando a calma como o `Retratos` real."""

    def __init__(self, paginas, limitar=None, quebrar=(), antigo=(), contador=None,
                 erros=None, ao_pedir=None):
        self.paginas = paginas
        self.limitar = dict(limitar or {})
        self.quebrar = set(quebrar)
        self.antigo = set(antigo)
        self.contador = contador
        self.erros = dict(erros or {})
        self.ao_pedir = ao_pedir
        self.tempo = None  # o `_rodar` do teste liga o relógio simulado
        self.calma_ate = 0.0
        self.pedidos = []
        self.taxas = []
        self.emprestadas = []

    def _s(self):
        return self.tempo.s if self.tempo is not None else 0.0

    def em_calma(self):
        return self._s() < self.calma_ate

    def calma_restante_s(self):
        return max(0.0, self.calma_ate - self._s())

    def acalmar(self):
        self.calma_ate = self._s() + CALMA_S

    def obter(self, engine, hash_name, usd_to_brl, quando, forcar=False):
        assert forcar
        self.pedidos.append(hash_name)
        self.taxas.append(usd_to_brl)
        if self.ao_pedir is not None:
            self.ao_pedir(hash_name)
        if hash_name in self.erros:
            raise self.erros[hash_name]
        if self.contador is not None:
            self.emprestadas.append(self.contador["emprestadas"])
        if self.limitar.get(hash_name, 0) > 0:
            self.limitar[hash_name] -= 1
            self.acalmar()
            return Leitura(None, None, True)
        if hash_name in self.quebrar:
            raise PageStructureError("pagina mudou")
        if hash_name in self.antigo:
            return Leitura(self.paginas[hash_name], quando - timedelta(minutes=1), False)
        return Leitura(self.paginas[hash_name], quando, False)


def _cotacao(valor=SimpleNamespace(usd_to_brl=5.0)):
    return SimpleNamespace(obter=lambda engine: valor)


def _rodar(engine, steam, retratos, quando=T0, cotacao=None, tempo=None):
    tempo = tempo or _Tempo(quando)
    retratos.tempo = tempo
    return executar_rodada(
        engine, steam=steam, retratos=retratos, cotacao=cotacao or _cotacao(),
        agora=tempo.agora, esperar=tempo.esperar, aceitar=_aceitar,
    )


def _listagens(engine):
    with engine.begin() as conn:
        return {(l.hash_name, l.listing_id) for l in repo.listar_listagens(conn)}


PAGINAS = {
    "Unusual A": _pagina("Unusual A", ("a1", 500, "Burning Flames"), ("a2", 900, "Sunbeams")),
    "Unusual B": _pagina("Unusual B", ("b1", 700, "Burning Flames")),
}
TAUNTS = [_r(f"Unusual Taunt: {i}") for i in range(10)]


# --- o caminho normal (comportamento que já existia) -----------------------

def test_primeira_rodada_le_a_fundo_so_os_cosmeticos_e_pagina_a_busca(engine):
    steam = _Steam([_r("Unusual A", n=2), *TAUNTS, _r("Unusual B")])
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, steam, retratos)

    assert steam.usd_chamadas == 1
    assert steam.chamadas == [(0, QUERY), (10, QUERY)]
    assert retratos.pedidos == ["Unusual A", "Unusual B"]
    assert (resumo.nomes_lidos, resumo.fundas_feitas, resumo.falhas, resumo.motivo) == (2, 2, 0, "ok")
    assert _listagens(engine) == {("Unusual A", "a1"), ("Unusual A", "a2"), ("Unusual B", "b1")}
    with engine.begin() as conn:
        rodada = repo.ultima_rodada(conn)
    assert (rodada.motivo_parada, rodada.nomes_lidos, rodada.fundas_feitas) == ("ok", 2, 2)


def test_assinatura_igual_dentro_do_prazo_nao_le_a_fundo(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos,
                    quando=T0 + timedelta(hours=3))

    assert retratos.pedidos == []
    assert (resumo.nomes_lidos, resumo.fundas_feitas) == (2, 0)


def test_assinatura_mudada_le_a_fundo_so_aquele_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B")]), retratos,
           quando=T0 + timedelta(hours=1))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_vencida_le_de_novo(engine):
    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A")]), retratos, quando=T0 + timedelta(hours=25))

    assert retratos.pedidos == ["Unusual A"]


def test_leitura_funda_substitui_as_listagens_do_nome(engine):
    _rodar(engine, _Steam([_r("Unusual A", n=2)]), _Retratos(PAGINAS))
    vendida = {"Unusual A": _pagina("Unusual A", ("a2", 900, "Sunbeams"))}

    _rodar(engine, _Steam([_r("Unusual A", n=1)]), _Retratos(vendida),
           quando=T0 + timedelta(hours=1))

    assert _listagens(engine) == {("Unusual A", "a2")}


def test_assinatura_mudada_sobrevive_a_falha_na_funda_e_e_relida_depois(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    resumo2 = _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
                     _Retratos(PAGINAS, quebrar={"Unusual A"}), quando=T0 + timedelta(hours=1))
    assert (resumo2.falhas, resumo2.motivo) == (1, "ok")

    retratos3 = _Retratos(PAGINAS)
    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
           retratos3, quando=T0 + timedelta(hours=2))

    assert retratos3.pedidos == ["Unusual A"]


def test_nome_quebrado_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, quebrar={"Unusual A"})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_retrato_antigo_nao_substitui_listagens_nem_marca_funda(engine):
    resumo = _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS, antigo={"Unusual A"}))

    assert resumo.fundas_feitas == 0
    assert _listagens(engine) == set()
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual A").funda_em is None


def test_nome_sumido_so_sai_depois_de_duas_rodadas_completas_sem_ele(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=1))
    assert ("Unusual B", "b1") in _listagens(engine)

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=2))
    assert ("Unusual B", "b1") not in _listagens(engine)


def test_sem_cotacao_da_chave_a_rodada_para_com_erro_sem_ir_a_steam(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), cotacao=_cotacao(None))

    assert resumo.motivo == "erro"
    assert (steam.usd_chamadas, steam.chamadas) == (0, [])


def test_espaco_extra_antes_de_cada_passo(engine):
    tempo = _Tempo()

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS), tempo=tempo)

    # cotação do dólar + 1 página da busca + 2 leituras fundas
    assert tempo.esperas == [ESPACO_EXTRA_S] * 4


def test_estourar_o_teto_de_paginas_rasas_conta_como_erro(engine, monkeypatch):
    monkeypatch.setattr(rodada_mod, "MAX_PAGINAS_RASAS", 1)
    resultados = [_r(f"Unusual {i}") for i in range(15)]
    steam = _Steam(resultados)
    retratos = _Retratos({})

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "erro"
    assert len(steam.chamadas) == 1
    assert retratos.pedidos == []


def test_nenhuma_conexao_emprestada_durante_as_requisicoes(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    steam = _Steam([_r("Unusual A"), _r("Unusual B")], contador=contador)
    retratos = _Retratos(PAGINAS, contador=contador)

    _rodar(engine, steam, retratos)

    assert steam.emprestadas == [0, 0]  # cotação do dólar + busca
    assert retratos.emprestadas == [0, 0]


def test_nenhuma_conexao_emprestada_durante_as_esperas(engine):
    contador = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: contador.__setitem__("emprestadas", contador["emprestadas"] - 1))
    durante = []
    tempo = _Tempo(ao_esperar=lambda s: durante.append(contador["emprestadas"]))

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS, limitar={"Unusual A": 1}),
           tempo=tempo)

    assert durante and set(durante) == {0}


def test_excecao_qualquer_na_leitura_funda_conta_falha_e_a_rodada_segue(engine):
    retratos = _Retratos(PAGINAS, erros={"Unusual A": ValueError("preco estranho")})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert retratos.pedidos == ["Unusual A", "Unusual B"]
    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}


def test_falha_ao_gravar_as_listagens_conta_falha_e_a_rodada_segue(engine, monkeypatch):
    original = repo.substituir_listagens

    def substituir(conn, nome, listagens, quando):
        if nome == "Unusual A":
            raise RuntimeError("value too long for type character varying(120)")
        return original(conn, nome, listagens, quando)

    monkeypatch.setattr(repo, "substituir_listagens", substituir)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))

    assert (resumo.falhas, resumo.fundas_feitas, resumo.motivo) == (1, 1, "ok")
    assert _listagens(engine) == {("Unusual B", "b1")}
    with engine.begin() as conn:
        assert repo.ler_assinatura(conn, "Unusual A").funda_em is None


def test_progresso_da_falha_e_gravado_antes_do_proximo_nome(engine):
    falhas_vistas = []

    def ao_pedir(nome):
        if nome == "Unusual B":
            with engine.begin() as conn:
                falhas_vistas.append(repo.ultima_rodada(conn).falhas)

    retratos = _Retratos(PAGINAS, erros={"Unusual A": KeyError("x")}, ao_pedir=ao_pedir)

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos)

    assert falhas_vistas == [1]


def test_erro_que_nao_e_429_na_busca_para_com_erro_sem_apagar_nada(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS),
           quando=T0 + timedelta(hours=1))
    antes = _listagens(engine)
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A")], erro_no_start=0), retratos,
                    quando=T0 + timedelta(hours=2))

    assert resumo.motivo == "erro"
    assert retratos.calma_ate == 0.0
    assert retratos.pedidos == []
    assert _listagens(engine) == antes


def test_cada_leitura_funda_usa_a_cotacao_atual(engine):
    taxas = iter([SimpleNamespace(usd_to_brl=5.0), SimpleNamespace(usd_to_brl=5.1),
                  SimpleNamespace(usd_to_brl=5.2)])
    cotacao = SimpleNamespace(obter=lambda engine: next(taxas))
    retratos = _Retratos(PAGINAS)

    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, cotacao=cotacao)

    assert retratos.taxas == [5.1, 5.2]


def test_cotacao_que_some_no_meio_para_a_rodada_com_erro(engine):
    valores = iter([SimpleNamespace(usd_to_brl=5.0), SimpleNamespace(usd_to_brl=5.0), None])
    cotacao = SimpleNamespace(obter=lambda engine: next(valores))
    retratos = _Retratos(PAGINAS)

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, cotacao=cotacao)

    assert resumo.motivo == "erro"
    assert retratos.pedidos == ["Unusual A"]


# --- pausa e retomada no 429 -----------------------------------------------

def test_429_na_cotacao_do_dolar_pausa_e_retoma_antes_da_busca(engine):
    tempo = _Tempo()
    steam = _Steam([_r("Unusual A")], usd_limitado=1)

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=tempo)

    assert resumo.motivo == "ok"
    assert steam.usd_chamadas == 2
    assert steam.chamadas == [(0, QUERY)]
    assert tempo.pausas() == [300]


def test_429_na_busca_pausa_e_retoma_no_mesmo_start(engine):
    tempo = _Tempo()
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")], limitar_busca={10: 1})

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=tempo)

    assert resumo.motivo == "ok"
    assert steam.chamadas == [(0, QUERY), (10, QUERY), (10, QUERY)]
    assert tempo.pausas() == [300]
    assert _listagens(engine) == {("Unusual A", "a1"), ("Unusual A", "a2"), ("Unusual B", "b1")}


def test_429_na_funda_pausa_e_retoma_no_mesmo_nome(engine):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert retratos.pedidos == ["Unusual A", "Unusual A", "Unusual B"]
    assert resumo.fundas_feitas == 2
    assert tempo.pausas() == [300]


def test_pausas_crescem_e_a_rodada_desiste_depois_de_quatro(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    antes = _listagens(engine)
    tempo = _Tempo(T0 + timedelta(hours=1))
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 99})

    resumo = _rodar(engine, _Steam([_r("Unusual A", usd=1), _r("Unusual B", usd=1)]),
                    retratos, tempo=tempo)

    assert resumo.motivo == "429"
    assert tempo.pausas() == [300, 600, 1200, 1800]
    assert retratos.pedidos == ["Unusual A"] * (MAX_PAUSAS_SEGUIDAS + 1)
    assert _listagens(engine) == antes
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "429"


def test_429_persistente_na_busca_desiste_sem_ler_a_fundo(engine):
    retratos = _Retratos(PAGINAS)
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")], limitar_busca={10: 99})

    resumo = _rodar(engine, steam, retratos)

    assert resumo.motivo == "429"
    assert steam.chamadas == [(0, QUERY)] + [(10, QUERY)] * (MAX_PAUSAS_SEGUIDAS + 1)
    assert retratos.pedidos == []


def test_sucesso_entre_pausas_zera_a_contagem(engine):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 2, "Unusual B": 2})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.pausas() == [300, 600, 300, 600]


def test_assinatura_mudada_sobrevive_a_429_persistente_e_e_relida_depois(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    resumo2 = _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
                     _Retratos(PAGINAS, limitar={"Unusual A": 99}),
                     quando=T0 + timedelta(hours=1))
    assert resumo2.motivo == "429"

    retratos3 = _Retratos(PAGINAS)
    _rodar(engine, _Steam([_r("Unusual A", usd=999), _r("Unusual B", usd=999)]),
           retratos3, quando=T0 + timedelta(hours=3))

    assert retratos3.pedidos == ["Unusual A", "Unusual B"]


def test_calma_ja_ligada_no_inicio_e_esperada_sem_contar_como_pausa(engine, capsys):
    tempo = _Tempo()
    retratos = _Retratos(PAGINAS)
    retratos.calma_ate = CALMA_S
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.esperas[0] == CALMA_S
    assert (steam.usd_chamadas, steam.chamadas) == (1, [(0, QUERY)])
    assert "pausa" not in capsys.readouterr().out


def test_calma_ligada_durante_o_espaco_extra_e_esperada_antes_de_requisitar(engine):
    retratos = _Retratos(PAGINAS)
    ligou = []

    def ao_esperar(segundos):
        if not ligou:
            ligou.append(True)
            retratos.calma_ate = tempo.s + CALMA_S

    tempo = _Tempo(ao_esperar=ao_esperar)
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, retratos, tempo=tempo)

    assert resumo.motivo == "ok"
    assert tempo.esperas[:2] == [ESPACO_EXTRA_S, CALMA_S - ESPACO_EXTRA_S]
    assert steam.usd_chamadas == 1


def test_log_diz_onde_veio_cada_429(engine, capsys):
    steam = _Steam([_r("Unusual A")], limitar_busca={0: 1}, usd_limitado=1)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1})

    resumo = _rodar(engine, steam, retratos)
    saida = capsys.readouterr().out

    assert resumo.motivo == "ok"
    assert ": 429 na cotação do dólar; pausa 1 de 4, até " in saida
    assert ": 429 na busca (página 1); pausa 1 de 4, até " in saida
    assert ": 429 na página de Unusual A; pausa 1 de 4, até " in saida


# --- cancelamento ------------------------------------------------------------

def test_stop_durante_a_pausa_termina_como_cancelada(engine):
    tempo = _Tempo(cancelar_se=lambda s: s >= 300)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 99})

    resumo = _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), retratos, tempo=tempo)

    assert resumo.motivo == "cancelada"
    assert retratos.pedidos == ["Unusual A"]
    assert _listagens(engine) == set()
    with engine.begin() as conn:
        assert repo.ultima_rodada(conn).motivo_parada == "cancelada"
        assert repo.ler_andamento(conn) is None


def test_stop_no_espaco_extra_para_sem_requisicao(engine):
    steam = _Steam([_r("Unusual A")])

    resumo = _rodar(engine, steam, _Retratos(PAGINAS), tempo=_Tempo(cancelar_se=lambda s: True))

    assert resumo.motivo == "cancelada"
    assert (steam.usd_chamadas, steam.chamadas) == (0, [])


def test_rodada_cancelada_nao_apaga_nomes_sumidos(engine):
    _rodar(engine, _Steam([_r("Unusual A"), _r("Unusual B")]), _Retratos(PAGINAS))
    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS), quando=T0 + timedelta(hours=1))
    cancela_na_funda = _Tempo(T0 + timedelta(hours=2), cancelar_se=lambda s: s >= 300)

    _rodar(engine, _Steam([_r("Unusual A", usd=1)]), _Retratos(PAGINAS, limitar={"Unusual A": 1}),
           tempo=cancela_na_funda)

    assert ("Unusual B", "b1") in _listagens(engine)


# --- andamento e poda ----------------------------------------------------------

def test_andamento_acompanha_a_busca_e_a_funda_e_some_no_fim(engine):
    def andamento():
        with engine.begin() as conn:
            a = repo.ler_andamento(conn)
        return (a.fase, a.paginas_busca_lidas, a.paginas_busca_total, a.itens_lidos, a.itens_total)

    na_busca, na_funda = [], []
    steam = _Steam([_r("Unusual A"), *TAUNTS, _r("Unusual B")],
                   ao_buscar=lambda start: na_busca.append(andamento()))
    retratos = _Retratos(PAGINAS, ao_pedir=lambda nome: na_funda.append(andamento()))

    _rodar(engine, steam, retratos)

    assert na_busca == [("busca", 0, None, 0, None), ("busca", 1, 2, 0, None)]
    assert na_funda == [("paginas", 2, 2, 0, 2), ("paginas", 2, 2, 1, 2)]
    with engine.begin() as conn:
        assert repo.ler_andamento(conn) is None


def test_andamento_registra_a_pausa_e_a_limpa_ao_retomar(engine):
    durante, na_retomada = [], []

    def ao_esperar(segundos):
        if segundos >= 300:
            with engine.begin() as conn:
                a = repo.ler_andamento(conn)
            durante.append((a.fase, a.pausas_seguidas, a.pausado_ate - tempo.agora()))

    def ao_pedir(nome):
        if len(retratos.pedidos) == 2:
            with engine.begin() as conn:
                na_retomada.append(repo.ler_andamento(conn).pausado_ate)

    tempo = _Tempo(ao_esperar=ao_esperar)
    retratos = _Retratos(PAGINAS, limitar={"Unusual A": 1}, ao_pedir=ao_pedir)

    _rodar(engine, _Steam([_r("Unusual A")]), retratos, tempo=tempo)

    assert durante == [("paginas", 1, timedelta(minutes=5))]
    assert na_retomada == [None]


def test_rodada_poda_o_historico_ao_fechar(engine):
    with engine.begin() as conn:
        for i in range(25):
            quando = T0 - timedelta(hours=30 - i)
            rid = repo.abrir_rodada(conn, quando)
            repo.fechar_rodada(conn, rid, quando, nomes_lidos=0, fundas_feitas=0,
                               falhas=0, motivo=repo.MOTIVO_429)

    _rodar(engine, _Steam([_r("Unusual A")]), _Retratos(PAGINAS))

    with engine.begin() as conn:
        rodadas = repo.ultimas_rodadas(conn, 100)
    assert len(rodadas) == repo.MANTER_RODADAS
    assert rodadas[0].motivo_parada == "ok"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_rodada.py -v`
Expected: FAIL (`ImportError: cannot import name 'MAX_PAUSAS_SEGUIDAS'`)

- [ ] **Step 3: Reescrever `tf2price/varredura/rodada.py`**

Substitua o arquivo inteiro por:

```python
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
        self, engine: Engine, rodada_id: int, retratos: Any,
        esperar: Callable[[float], bool], agora: Callable[[], datetime],
        espaco_extra_s: float,
    ) -> None:
        self._engine = engine
        self._rodada_id = rodada_id
        self._retratos = retratos
        self._esperar_fn = esperar
        self._agora = agora
        self._espaco_extra_s = espaco_extra_s
        self.pausas_seguidas = 0

    def _esperar(self, segundos: float) -> None:
        if segundos > 0 and self._esperar_fn(segundos):
            raise _Cancelada

    def _esperar_calma(self) -> None:
        # Calma ligada por outro (um usuário bateu no 429): espera o que falta,
        # sem contar como pausa, porque a rodada não fez requisição nenhuma.
        while (resta := self._retratos.calma_restante_s()) > 0:
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
    freio = _Freio(engine, rodada_id, retratos, esperar, agora, espaco_extra_s)
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
```

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_rodada.py -v`
Expected: PASS (todos).

Se algum falhar, investigue antes de mexer no teste: cada asserção acima descreve uma regra da spec. `tests\varredura\test_agendador.py` ainda passa nesta task, porque o agendador só muda na Task 3 e continua chamando `executar_rodada` sem `dormir`.

- [ ] **Step 5: Suíte e commit**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:warnings; echo $LASTEXITCODE` → `0`

```bash
git add tf2price/varredura/rodada.py tests/varredura/test_rodada.py
git commit -m "Pausa e retoma a rodada no 429 em vez de desistir"
```

---

### Task 3: Agendador com cancelamento por rodada

**Files:**
- Modify: `tf2price/varredura/agendador.py`
- Modify: `tests/varredura/test_agendador.py`

**Interfaces:**
- Consumes: `executar_rodada(..., esperar=...)` (Task 2).
- Produces: `Agendador(engine, rodar: Callable[[threading.Event], Any], agora=db.agora)`; `Agendador.parar_rodada() -> bool`. `construir_agendador` passa `esperar=cancelar.wait`.

- [ ] **Step 1: Ajustar os testes existentes e escrever os novos**

Em `tests/varredura/test_agendador.py`:
- troque todo `rodar=lambda: None` por `rodar=lambda cancelar: None`;
- em `test_nunca_duas_rodadas_ao_mesmo_tempo` e `test_ciclo_roda_quando_vence_e_sobrevive_a_erro`, troque `def rodar():` por `def rodar(cancelar):`.

Acrescente no fim:

```python
def test_parar_rodada_liga_o_evento_da_rodada_em_curso(engine):
    entrou = threading.Event()
    viu_cancelamento = []

    def rodar(cancelar):
        entrou.set()
        viu_cancelamento.append(cancelar.wait(5))

    agendador = Agendador(engine, rodar=rodar)
    assert agendador.disparar_em_segundo_plano()
    assert entrou.wait(5)

    assert agendador.parar_rodada()

    for _ in range(100):
        if not agendador.rodando:
            break
        threading.Event().wait(0.01)
    assert viu_cancelamento == [True]


def test_parar_sem_rodada_devolve_falso(engine):
    assert not Agendador(engine, rodar=lambda cancelar: None).parar_rodada()


def test_cada_rodada_recebe_um_evento_novo(engine):
    eventos = []
    agendador = Agendador(engine, rodar=eventos.append)

    agendador.tentar_rodar()
    eventos[0].set()
    agendador.tentar_rodar()

    assert eventos[0] is not eventos[1]
    assert not eventos[1].is_set()


def test_construir_agendador_passa_o_cancelamento_como_espera(engine, monkeypatch):
    from types import SimpleNamespace

    from tf2price.varredura import agendador as agendador_mod

    capturado = {}
    monkeypatch.setattr(agendador_mod, "executar_rodada",
                        lambda engine, **kwargs: capturado.update(kwargs))
    contexto = SimpleNamespace(steam="s", retratos="r", cotacao="c")
    evento = threading.Event()

    agendador_mod.construir_agendador(engine, contexto)._rodar(evento)

    assert capturado == {"steam": "s", "retratos": "r", "cotacao": "c", "esperar": evento.wait}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_agendador.py -v`
Expected: FAIL (os testes antigos quebram porque `rodar` ainda é chamado sem argumento; `parar_rodada` não existe)

- [ ] **Step 3: Implementar em `tf2price/varredura/agendador.py`**

No `__init__`, depois de criar `self._trava`, acrescente:

```python
        # Um evento por rodada: `parar_rodada` o liga, e a rodada o usa como
        # espera (`Event.wait` devolve verdadeiro quando foi ligado).
        self._cancelar = threading.Event()
```

Troque a anotação de `rodar` no `__init__` para `rodar: Callable[[threading.Event], Any]`.

Troque `tentar_rodar`, `disparar_em_segundo_plano` e `_executar_segurando` por:

```python
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
```

Troque `construir_agendador` por:

```python
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
```

- [ ] **Step 4: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura tests\painel\test_aquecimento.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tf2price/varredura/agendador.py tests/varredura/test_agendador.py
git commit -m "Permite parar a rodada em curso pelo agendador"
```

---

### Task 4: Progresso e "Stop scan" no admin, e documentação

**Files:**
- Modify: `tf2price/painel/varredura.py`
- Modify: `tf2price/painel/admin.py`
- Create: `tf2price/painel/templates/_varredura_andamento.html`
- Modify: `tf2price/painel/templates/admin.html`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `docs/superpowers/specs/2026-09-22-varredura-pausa-e-progresso-design.md`, `README.md`
- Test: `tests/painel/test_admin_varredura.py`

**Interfaces:**
- Consumes: `repo.ler_andamento`, `repo.ultima_rodada`, `repo.MOTIVO_CANCELADA`, `repo.FASE_*` (Task 1); `MAX_PAUSAS_SEGUIDAS` (Task 2); `Agendador.parar_rodada()`, `.rodando` (Task 3).
- Produces: `GET /admin/varredura/andamento`, `POST /admin/varredura/parar`; `ha_quanto_tempo(quando, agora) -> str` em `tf2price.painel.varredura`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/painel/test_admin_varredura.py`, troque a classe `_AgendadorFalso` por:

```python
class _AgendadorFalso:
    def __init__(self, livre=True):
        self.livre = livre
        self.disparos = 0
        self.paradas = 0
        self.rodando = not livre

    def disparar_em_segundo_plano(self):
        self.disparos += 1
        return self.livre

    def parar_rodada(self):
        self.paradas += 1
        return self.rodando
```

Acrescente no topo `from datetime import datetime`, e no fim:

```python
def _rodada_aberta(engine, **campos):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, db.agora())
        repo.iniciar_andamento(conn, rid, db.agora())
        if campos:
            repo.atualizar_andamento(conn, db.agora(), **campos)


def test_admin_inclui_o_bloco_de_andamento(engine):
    assert 'id="varredura-andamento"' in _entra(engine).get("/admin").text


def test_andamento_sem_rodada_nao_se_atualiza(engine):
    texto = _entra(engine, agendador=_AgendadorFalso()).get("/admin/varredura/andamento").text
    assert "No scan running." in texto
    assert "hx-trigger" not in texto


def test_andamento_com_rodada_se_atualiza_e_mostra_o_progresso(engine):
    _rodada_aberta(engine, fase=repo.FASE_PAGINAS, itens_lidos=120, itens_total=604)
    cliente = _entra(engine, agendador=_AgendadorFalso(livre=False))

    texto = cliente.get("/admin/varredura/andamento").text

    assert 'hx-trigger="every 5s"' in texto
    assert "Reading item pages" in texto
    assert "120 of 604" in texto
    assert "Stop scan" in texto


def test_andamento_da_busca(engine):
    _rodada_aberta(engine, fase=repo.FASE_BUSCA, paginas_busca_lidas=34, paginas_busca_total=180)
    texto = _entra(engine, agendador=_AgendadorFalso(livre=False)).get("/admin/varredura/andamento").text
    assert "Reading search pages" in texto
    assert "34 of 180" in texto


def test_andamento_em_pausa(engine):
    _rodada_aberta(engine, fase=repo.FASE_PAGINAS, itens_lidos=1, itens_total=2,
                   pausado_ate=datetime(2026, 9, 22, 14, 32), pausas_seguidas=2)
    texto = _entra(engine, agendador=_AgendadorFalso(livre=False)).get("/admin/varredura/andamento").text
    assert "Paused: Steam is rate limiting this server" in texto
    assert "Resuming at 14:32 UTC (pause 2 of 4)" in texto


def test_andamento_mostra_o_resultado_da_ultima_rodada(engine):
    with engine.begin() as conn:
        rid = repo.abrir_rodada(conn, db.agora())
        repo.fechar_rodada(conn, rid, db.agora(), nomes_lidos=0, fundas_feitas=0,
                           falhas=0, motivo=repo.MOTIVO_CANCELADA)
    texto = _entra(engine, agendador=_AgendadorFalso()).get("/admin/varredura/andamento").text
    assert "Stopped by admin" in texto
    assert "cancelada" not in texto


def test_andamento_sem_agendador(engine):
    texto = _entra(engine).get("/admin/varredura/andamento").text
    assert "The scanner is not available in this process." in texto


def test_andamento_exige_admin(engine):
    _entra(engine)
    comum = _entra(engine, nome="amiga", admin=False)
    assert comum.get("/admin/varredura/andamento").status_code == 403


def test_stop_com_rodada(engine):
    agendador = _AgendadorFalso(livre=False)
    r = _entra(engine, agendador=agendador).post("/admin/varredura/parar")
    assert agendador.paradas == 1
    assert "Stopping the scan…" in r.text


def test_stop_sem_rodada(engine):
    r = _entra(engine, agendador=_AgendadorFalso()).post("/admin/varredura/parar")
    assert "No scan is running." in r.text


def test_stop_sem_agendador(engine):
    assert "No scan is running." in _entra(engine).post("/admin/varredura/parar").text


def test_stop_exige_mesma_origem(engine):
    r = _entra(engine, agendador=_AgendadorFalso(livre=False)).post(
        "/admin/varredura/parar", headers={"origin": "https://outro.site"})
    assert r.status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_admin_varredura.py -v`
Expected: FAIL (404 nas rotas novas; `varredura-andamento` ausente)

- [ ] **Step 3: `tf2price/painel/varredura.py`**

Em `ROTULO_DA_PARADA`, acrescente a entrada `repo.MOTIVO_CANCELADA: "Stopped by admin",`. Depois de `_ha`, acrescente:

```python
def ha_quanto_tempo(quando, agora) -> str:
    """"5 min ago", "just now": a mesma frase do /scan, para o admin."""
    return _ha(idade_por_extenso(quando, agora))
```

- [ ] **Step 4: `tf2price/painel/admin.py`**

Troque o import `from tf2price.painel.varredura import ROTULO_DA_PARADA` por:

```python
from tf2price.painel.varredura import ROTULO_DA_PARADA, ha_quanto_tempo
from tf2price.varredura.rodada import MAX_PAUSAS_SEGUIDAS
```

Acrescente, antes de `_tela_admin`:

```python
def _contexto_do_andamento(request: Request, conn: Connection) -> dict:
    """O que o bloco "Current scan" precisa, na página inteira e no fragmento."""
    agendador = request.app.state.agendador
    agora = db.agora()
    return {
        "disponivel": agendador is not None,
        "rodando": bool(agendador and agendador.rodando),
        "andamento": varredura_repo.ler_andamento(conn),
        "ultima": varredura_repo.ultima_rodada(conn),
        "rotulo_da_parada": ROTULO_DA_PARADA,
        "max_pausas": MAX_PAUSAS_SEGUIDAS,
        "ha": lambda quando: ha_quanto_tempo(quando, agora),
    }
```

Em `_tela_admin`, apague a linha `agendador = request.app.state.agendador` e as chaves `"rodando"` e `"rotulo_da_parada"` do `context`, e acrescente `**_contexto_do_andamento(request, conn),` como primeira entrada do `context`.

Acrescente no fim do arquivo:

```python
@ROTEADOR.get("/admin/varredura/andamento", response_class=HTMLResponse)
def andamento_da_varredura(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_varredura_andamento.html",
        context=_contexto_do_andamento(request, conn),
    )


@ROTEADOR.post("/admin/varredura/parar", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def parar_varredura(
    request: Request,
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    agendador = request.app.state.agendador
    if agendador is None or not agendador.parar_rodada():
        return _tela_admin(request, conn, usuario, erro="No scan is running.")
    return _tela_admin(request, conn, usuario, varredura_msg="Stopping the scan…")
```

- [ ] **Step 5: Fragmento `tf2price/painel/templates/_varredura_andamento.html`**

```html
<div id="varredura-andamento" class="scan-progress" aria-live="polite"
     {% if rodando %}hx-get="/admin/varredura/andamento" hx-trigger="every 5s" hx-swap="outerHTML"{% endif %}>
  <p class="scope-label">CURRENT SCAN</p>
  {% if not disponivel %}
  <p>The scanner is not available in this process.</p>
  {% elif rodando %}
    {% if ultima %}<p>Started {{ ha(ultima.inicio) }}</p>{% endif %}
    {% if andamento and andamento.pausado_ate %}
    <p class="evidence-note evidence-note--stale">Paused: Steam is rate limiting this server · Resuming at {{ andamento.pausado_ate.strftime('%H:%M') }} UTC (pause {{ andamento.pausas_seguidas }} of {{ max_pausas }})</p>
    {% endif %}
    {% if not andamento or andamento.fase == 'cotacao' %}
    <p>Loading the exchange rate…</p>
    {% elif andamento.fase == 'busca' %}
    <p>Reading search pages{% if andamento.paginas_busca_total %} · {{ andamento.paginas_busca_lidas }} of {{ andamento.paginas_busca_total }}{% endif %}</p>
    {% if andamento.paginas_busca_total %}<progress max="{{ andamento.paginas_busca_total }}" value="{{ andamento.paginas_busca_lidas }}">{{ andamento.paginas_busca_lidas }} of {{ andamento.paginas_busca_total }}</progress>{% endif %}
    {% else %}
    <p>Reading item pages · {{ andamento.itens_lidos }} of {{ andamento.itens_total or 0 }}</p>
    {% if andamento.itens_total %}<progress max="{{ andamento.itens_total }}" value="{{ andamento.itens_lidos }}">{{ andamento.itens_lidos }} of {{ andamento.itens_total }}</progress>{% endif %}
    {% endif %}
    {% if ultima %}<p class="scan-sub">{{ ultima.nomes_lidos }} items seen · {{ ultima.fundas_feitas }} re-read · {{ ultima.falhas }} failures</p>{% endif %}
    <form method="post" action="/admin/varredura/parar">
      <button class="button button--danger" type="submit">Stop scan</button>
    </form>
  {% else %}
  <p>No scan running.</p>
  {% if ultima and ultima.fim %}<p class="scan-sub">Last scan: {{ rotulo_da_parada.get(ultima.motivo_parada, ultima.motivo_parada) }} · finished {{ ha(ultima.fim) }}</p>{% endif %}
  {% endif %}
</div>
```

- [ ] **Step 6: Incluir no `admin.html` e CSS**

Em `tf2price/painel/templates/admin.html`, na seção `admin-scan`, logo depois do `<form method="post" action="/admin/varredura/rodar">…</form>`, acrescente:

```html
  {% include "_varredura_andamento.html" %}
```

No fim de `tf2price/painel/static/briefcase.css`:

```css
.scan-progress { display: grid; gap: .5rem; padding: 1rem; border: 1px solid var(--ink-blue); }
.scan-progress p { margin: 0; }
.scan-progress progress { width: 100%; max-width: 32rem; accent-color: var(--warning); }
```

- [ ] **Step 7: Rodar os testes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -q -p no:warnings; echo $LASTEXITCODE`
Expected: `0` (inclui `test_english_ui`, `test_accessibility` e `test_branding`)

- [ ] **Step 8: Documentação**

1. Na spec `docs/superpowers/specs/2026-09-22-varredura-pausa-e-progresso-design.md`, §5.1: troque a linha da coluna `fase` para dizer `cotacao`, `busca` ou `paginas`, e acrescente uma frase dizendo que a pausa é marcada por `pausado_ate` não nulo, e não por uma fase, para a tela saber de qual fase a rodada vai voltar. Troque "Status: aprovado para planejamento" por "Status: implementado".
2. No `README.md`, no parágrafo sobre o Market Scan, acrescente uma frase: o admin vê o progresso da rodada em curso e pode interrompê-la com "Stop scan"; num limite da Steam (429) a rodada pausa e retoma sozinha, e só desiste depois de ~65 min sem nenhuma requisição dar certo.

Run: `git diff --check` → sem saída.

- [ ] **Step 9: Suíte e commit**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:warnings; echo $LASTEXITCODE` → `0`

```bash
git add tf2price/painel/varredura.py tf2price/painel/admin.py tf2price/painel/templates/_varredura_andamento.html tf2price/painel/templates/admin.html tf2price/painel/static/briefcase.css tests/painel/test_admin_varredura.py docs/superpowers/specs/2026-09-22-varredura-pausa-e-progresso-design.md README.md
git commit -m "Mostra o progresso da varredura no admin e permite parar a rodada"
```
