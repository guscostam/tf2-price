# Administradores: promover, rebaixar e o superadmin intocável — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O superadmin (nomeado por `SUPERADMIN`) promove e rebaixa administradores em `/admin`; admins comuns passam a agir só sobre membros; ninguém mexe no superadmin.

**Architecture:** Uma regra pura em `tf2price/contas/permissoes.py` decide quem pode mexer em quem. As rotas de `/admin` decidem por ela, o template mostra os botões por ela e `servico.redefinir` revalida o link de reset por ela no momento do uso. O nome do superadmin chega ao app por `criar_app(..., superadmin=...)` e fica em `app.state.superadmin`. As escritas de admin comum que dependem de o alvo ser membro usam `UPDATE ... WHERE admin = false`.

**Tech Stack:** Python 3.12, FastAPI, Jinja, SQLAlchemy Core, pytest (SQLite em memória).

**Spec:** `docs/superpowers/specs/2026-09-22-administradores-design.md`

## Global Constraints

- Leia `AGENTS.md` antes de começar; ele vale para todas as tarefas.
- SQL só em `tf2price/contas/repositorio.py`; serviços e rotas não escrevem SQL.
- Compatível com SQLite (testes) e PostgreSQL (produção).
- Testes sem rede; o nome do superadmin entra nos testes por `criar_app(engine, superadmin="gusco")`, nunca pelo ambiente — exceto os testes da leitura da variável (Task 5), que usam `monkeypatch`.
- Texto da interface em inglês; comentários, docstrings e nomes em português, como o resto do código.
- Respostas de ação proibida: `HTMLResponse("Not allowed.", status_code=403)`. Alvo inexistente: `HTMLResponse("User not found.", status_code=404)` (já existe).
- Link de reset recusado: mesma resposta dos links inválidos, `404 "This invitation is no longer valid."`, e o convite **não** é consumido.
- Rótulo do superadmin na lista: `Owner`.
- Comando de teste (PowerShell): `.\.venv\Scripts\python.exe -m pytest <caminho> -v`.
- Commits terminam com as linhas:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_016eQWjrFAbWQ3YCoMkJXScN
  ```

## Mapa de arquivos

| Arquivo | Papel |
| --- | --- |
| `tf2price/contas/permissoes.py` (novo) | `eh_superadmin`, `pode_gerir`, `pode_mudar_admin`: funções puras |
| `tf2price/contas/repositorio.py` | `definir_admin`; `definir_ativo` ganha `so_se_membro` e devolve `bool` |
| `tf2price/contas/servico.py` | `redefinicao_autorizada`; `redefinir` exige `nome_super` |
| `tf2price/painel/app.py` | `criar_app(..., superadmin=None)`; leitura de `SUPERADMIN` e aviso no log |
| `tf2price/painel/acesso.py` | `/convite/{token}` recusa link de reset que perdeu a autorização |
| `tf2price/painel/admin.py` | rota `/admin/papel/{id}`; guardas em `redefinir` e `ativo` |
| `tf2price/painel/templates/admin.html` | botões por permissão; selo `Owner` |
| `tests/contas/test_permissoes.py` (novo) | tabela de permissões |
| `tests/contas/test_repositorio.py`, `tests/contas/test_servico.py`, `tests/painel/test_convite.py`, `tests/painel/test_admin.py`, `tests/painel/test_superadmin.py` (novo) | testes |
| `.env.example`, `README.md`, `AGENTS.md` | documentação |

---

### Task 1: Regra de permissões

**Files:**
- Create: `tf2price/contas/permissoes.py`
- Test: `tests/contas/test_permissoes.py`

**Interfaces:**
- Consumes: `tf2price.contas.modelo.Usuario` (dataclass com `id`, `nome`, `senha_hash`, `admin`, `ativo`, `criado_em`).
- Produces:
  - `eh_superadmin(usuario: Usuario, nome_super: str | None) -> bool`
  - `pode_gerir(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool` — Reset password e Disable/Reactivate
  - `pode_mudar_admin(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool` — Make admin / Remove admin

- [ ] **Step 1: Write the failing tests**

Crie `tests/contas/test_permissoes.py`:

```python
from __future__ import annotations

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.contas.permissoes import eh_superadmin, pode_gerir, pode_mudar_admin

SUPER = "gusco"


def _u(ident: int, nome: str, admin: bool = False, ativo: bool = True) -> Usuario:
    return Usuario(
        id=ident, nome=nome, senha_hash="hash", admin=admin, ativo=ativo,
        criado_em=db.agora(),
    )


DONO = _u(1, "gusco", admin=True)
COLEGA = _u(2, "colega", admin=True)
OUTRO_ADMIN = _u(3, "outro", admin=True)
AMIGA = _u(4, "amiga")


# --- eh_superadmin ---------------------------------------------------------


def test_superadmin_e_o_admin_ativo_com_o_nome_da_variavel():
    assert eh_superadmin(DONO, SUPER) is True


def test_sem_variavel_ninguem_e_superadmin():
    assert eh_superadmin(DONO, None) is False
    assert eh_superadmin(DONO, "") is False


def test_nome_de_outra_pessoa_nao_faz_superadmin():
    assert eh_superadmin(COLEGA, SUPER) is False


def test_membro_com_o_nome_da_variavel_nao_e_superadmin():
    """A variável pode nomear uma conta que ainda não existe; quem se
    cadastrar com esse nome por um convite de membro nasce membro."""
    assert eh_superadmin(_u(9, "gusco"), SUPER) is False


def test_admin_desativado_com_o_nome_da_variavel_nao_e_superadmin():
    assert eh_superadmin(_u(1, "gusco", admin=True, ativo=False), SUPER) is False


# --- pode_gerir (Reset password, Disable/Reactivate) -----------------------


def test_superadmin_gere_todo_mundo():
    for alvo in (AMIGA, COLEGA, DONO):
        assert pode_gerir(DONO, alvo, SUPER) is True


def test_admin_comum_gere_membros_e_a_si_mesmo():
    assert pode_gerir(COLEGA, AMIGA, SUPER) is True
    assert pode_gerir(COLEGA, COLEGA, SUPER) is True


def test_admin_comum_nao_gere_outro_admin_nem_o_superadmin():
    assert pode_gerir(COLEGA, OUTRO_ADMIN, SUPER) is False
    assert pode_gerir(COLEGA, DONO, SUPER) is False


def test_admin_comum_gere_membro_desativado():
    assert pode_gerir(COLEGA, _u(4, "amiga", ativo=False), SUPER) is True


def test_membro_nao_gere_ninguem():
    assert pode_gerir(AMIGA, AMIGA, SUPER) is False
    assert pode_gerir(AMIGA, _u(5, "outra"), SUPER) is False


def test_admin_desativado_nao_gere_ninguem():
    desativado = _u(2, "colega", admin=True, ativo=False)
    assert pode_gerir(desativado, AMIGA, SUPER) is False
    assert pode_gerir(desativado, desativado, SUPER) is False


def test_sem_variavel_o_dono_vira_admin_comum():
    """Falha fechada: ninguém fica exposto, só some o poder sobre admins."""
    assert pode_gerir(DONO, COLEGA, None) is False
    assert pode_gerir(DONO, AMIGA, None) is True


# --- pode_mudar_admin (Make admin / Remove admin) --------------------------


def test_superadmin_muda_o_papel_dos_outros():
    assert pode_mudar_admin(DONO, AMIGA, SUPER) is True
    assert pode_mudar_admin(DONO, COLEGA, SUPER) is True


def test_superadmin_nao_muda_o_proprio_papel():
    assert pode_mudar_admin(DONO, DONO, SUPER) is False


def test_admin_comum_nao_muda_papel_de_ninguem():
    for alvo in (AMIGA, OUTRO_ADMIN, DONO, COLEGA):
        assert pode_mudar_admin(COLEGA, alvo, SUPER) is False


def test_sem_variavel_ninguem_muda_papel():
    assert pode_mudar_admin(DONO, AMIGA, None) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_permissoes.py -v`
Expected: ERROR na coleta, `ModuleNotFoundError: No module named 'tf2price.contas.permissoes'`

- [ ] **Step 3: Write the implementation**

Crie `tf2price/contas/permissoes.py`:

```python
"""Quem pode mexer em quem na lista de pessoas do admin.

Funções puras: sem conexão, sem I/O. São a fonte única da regra — a rota
decide por elas, o template mostra os botões por elas e `servico.redefinir`
revalida por elas o link de redefinição no momento do uso.

O superadmin é a conta nomeada pela variável de ambiente `SUPERADMIN`. A
proteção dos admins não depende dela: admin comum não age sobre admin
nenhum, superadmin ou não. O que a variável dá é só o poder de gerir
admins; ausente ou errada, esse poder some, e não passa para mais ninguém.
"""

from __future__ import annotations

from tf2price.contas.modelo import Usuario


def eh_superadmin(usuario: Usuario, nome_super: str | None) -> bool:
    # Admin e ativo no banco, não só o nome: se a variável nomear uma conta
    # que ainda não existe, quem receber um convite de membro pode se
    # cadastrar com esse nome — e nasce membro, não superadmin.
    return (
        bool(nome_super)
        and usuario.nome == nome_super
        and usuario.admin
        and usuario.ativo
    )


def pode_gerir(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool:
    """Reset password e Disable/Reactivate.

    A própria conta entra como gerível; quem recusa desativar a si mesmo é a
    rota de ativo, com mensagem própria. Admin comum age só sobre membros:
    gerar o link de reset de outro admin seria tomar a conta dele, já que
    quem gera o link pode usá-lo.
    """
    if not (ator.admin and ator.ativo):
        return False
    if ator.id == alvo.id:
        return True
    if eh_superadmin(ator, nome_super):
        return True
    return not alvo.admin


def pode_mudar_admin(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool:
    """Make admin / Remove admin: só o superadmin, e nunca sobre si mesmo."""
    return eh_superadmin(ator, nome_super) and ator.id != alvo.id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_permissoes.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add tf2price/contas/permissoes.py tests/contas/test_permissoes.py
git commit -m "Regra de quem pode mexer em quem na lista de pessoas"
```
(com as linhas de atribuição das Global Constraints no corpo)

---

### Task 2: Repositório — mudar papel e desativar só membro

**Files:**
- Modify: `tf2price/contas/repositorio.py` (função `definir_ativo`, ~linha 64)
- Test: `tests/contas/test_repositorio.py`

**Interfaces:**
- Produces:
  - `definir_admin(conn: Connection, usuario_id: int, admin: bool) -> None`
  - `definir_ativo(conn: Connection, usuario_id: int, ativo: bool, *, so_se_membro: bool = False) -> bool` — devolve se a linha foi alterada. Chamadas antigas que ignoram o retorno continuam valendo.

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/contas/test_repositorio.py` (o helper `_usuario(conn, nome="gusco", admin=True)` e `AGORA` já existem no arquivo):

```python
def test_definir_admin_promove_e_rebaixa(engine):
    with engine.begin() as conn:
        ident = _usuario(conn, nome="amiga", admin=False)
        repo.definir_admin(conn, ident, True)
        assert repo.usuario_por_id(conn, ident).admin is True
        repo.definir_admin(conn, ident, False)
        assert repo.usuario_por_id(conn, ident).admin is False


def test_definir_ativo_devolve_se_mudou_a_linha(engine):
    with engine.begin() as conn:
        ident = _usuario(conn)
        assert repo.definir_ativo(conn, ident, False) is True
        assert repo.usuario_por_id(conn, ident).ativo is False
        assert repo.definir_ativo(conn, 999999, False) is False


def test_so_se_membro_desativa_membro(engine):
    with engine.begin() as conn:
        ident = _usuario(conn, nome="amiga", admin=False)
        assert repo.definir_ativo(conn, ident, False, so_se_membro=True) is True
        assert repo.usuario_por_id(conn, ident).ativo is False


def test_so_se_membro_nao_toca_em_admin(engine):
    """A conferência "o alvo é membro?" e a escrita num UPDATE só: uma
    promoção concorrente não deixa um admin comum desativar um admin."""
    with engine.begin() as conn:
        ident = _usuario(conn, nome="colega", admin=True)
        assert repo.definir_ativo(conn, ident, False, so_se_membro=True) is False
        assert repo.usuario_por_id(conn, ident).ativo is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_repositorio.py -v`
Expected: FAIL — `AttributeError: module 'tf2price.contas.repositorio' has no attribute 'definir_admin'`, e `assert None is True` / `TypeError: definir_ativo() got an unexpected keyword argument 'so_se_membro'` nos outros.

- [ ] **Step 3: Write the implementation**

Em `tf2price/contas/repositorio.py`, substitua `definir_ativo` por:

```python
def definir_ativo(
    conn: Connection, usuario_id: int, ativo: bool, *, so_se_membro: bool = False
) -> bool:
    """Liga ou desliga a conta e diz se alguma linha mudou.

    Com `so_se_membro`, o UPDATE só alcança a linha se ela não é admin. É
    assim que um admin comum grava: conferir em Python que o alvo é membro e
    só depois escrever deixaria uma promoção concorrente passar entre as
    duas coisas — as rotas correm em threads de verdade. Mesmo desenho de
    `consumir_convite`.
    """
    consulta = update(db.usuario).where(db.usuario.c.id == usuario_id)
    if so_se_membro:
        consulta = consulta.where(db.usuario.c.admin.is_(False))
    return conn.execute(consulta.values(ativo=ativo)).rowcount == 1


def definir_admin(conn: Connection, usuario_id: int, admin: bool) -> None:
    conn.execute(
        update(db.usuario).where(db.usuario.c.id == usuario_id).values(admin=admin)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas -v`
Expected: todos passam (os antigos de `test_repositorio.py` e `test_servico.py` que chamam `definir_ativo` ignorando o retorno inclusive).

- [ ] **Step 5: Commit**

```bash
git add tf2price/contas/repositorio.py tests/contas/test_repositorio.py
git commit -m "Repositório muda papel e desativa só membro atomicamente"
```

---

### Task 3: Link de reset revalidado no uso

**Files:**
- Modify: `tf2price/contas/servico.py` (função `redefinir`, imports)
- Modify: `tf2price/painel/app.py:40-52` (`criar_app`)
- Modify: `tf2price/painel/acesso.py:76-121` (`_convite_aberto`, `tela_convite`, `usar_convite`)
- Test: `tests/contas/test_servico.py`, `tests/painel/test_convite.py`

**Interfaces:**
- Consumes: `permissoes.pode_gerir` (Task 1); `repo.definir_admin` (Task 2).
- Produces:
  - `servico.redefinicao_autorizada(conn: Connection, convite: Convite, nome_super: str | None) -> bool`
  - `servico.redefinir(conn, token, *, senha: str, quando: datetime, nome_super: str | None) -> Usuario` — `nome_super` agora é keyword **obrigatório**.
  - `criar_app(engine, contexto=None, agendador=None, superadmin: str | None = None) -> FastAPI`, que guarda `app.state.superadmin`.

- [ ] **Step 1: Write the failing service tests**

Em `tests/contas/test_servico.py`:

1. No teste existente `test_redefinir_troca_a_senha_e_derruba_as_sessoes`, troque a chamada
   `servico.redefinir(conn, token, senha="senha novinha", quando=AGORA)` por
   `servico.redefinir(conn, token, senha="senha novinha", quando=AGORA, nome_super=None)`.
   (O dono é admin comum sem a variável, e a alvo é membro: continua autorizado.)

2. Acrescente, logo depois dele (`_dono`, `_com_conta`, `SENHA`, `AGORA`, `tokens` e `pytest` já existem no arquivo):

```python
def _admins_e_membro(conn):
    """dono (superadmin "dono"), colega (admin comum) e amiga (membro)."""
    dono = _dono(conn)
    _com_conta(conn, nome="colega", criado_por=dono)
    colega = repo.usuario_por_nome(conn, "colega").id
    repo.definir_admin(conn, colega, True)
    _com_conta(conn, nome="amiga", criado_por=dono)
    amiga = repo.usuario_por_nome(conn, "amiga").id
    return dono, colega, amiga


def _reset(conn, criado_por, alvo) -> str:
    return servico.convidar(
        conn, criado_por=criado_por, quando=AGORA,
        tipo=servico.TIPO_REDEFINICAO, alvo=alvo,
    )


def test_link_de_admin_comum_para_quem_virou_admin_e_recusado_sem_queimar(engine):
    """Sem a revalidação, o admin comum guardaria o link de um membro,
    esperaria a promoção e tomaria a conta de um admin."""
    with engine.begin() as conn:
        _, colega, amiga = _admins_e_membro(conn)
        token = _reset(conn, colega, amiga)
        repo.definir_admin(conn, amiga, True)

        with pytest.raises(servico.ConviteInvalido):
            servico.redefinir(
                conn, token, senha="senha novinha", quando=AGORA, nome_super="dono"
            )

        assert repo.convite_por_hash(conn, tokens.hash_de(token)).usado_em is None
        assert servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)


def test_link_de_quem_foi_rebaixado_e_recusado(engine):
    with engine.begin() as conn:
        _, colega, amiga = _admins_e_membro(conn)
        token = _reset(conn, colega, amiga)
        repo.definir_admin(conn, colega, False)

        with pytest.raises(servico.ConviteInvalido):
            servico.redefinir(
                conn, token, senha="senha novinha", quando=AGORA, nome_super="dono"
            )


def test_superadmin_redefine_a_senha_de_um_admin(engine):
    with engine.begin() as conn:
        dono, colega, _ = _admins_e_membro(conn)
        token = _reset(conn, dono, colega)
        servico.redefinir(
            conn, token, senha="senha novinha", quando=AGORA, nome_super="dono"
        )
        assert servico.entrar(conn, nome="colega", senha="senha novinha", quando=AGORA)


def test_sem_a_variavel_o_link_do_dono_para_um_admin_nao_vale(engine):
    with engine.begin() as conn:
        dono, colega, _ = _admins_e_membro(conn)
        token = _reset(conn, dono, colega)
        with pytest.raises(servico.ConviteInvalido):
            servico.redefinir(
                conn, token, senha="senha novinha", quando=AGORA, nome_super=None
            )


def test_admin_comum_redefine_a_propria_senha(engine):
    with engine.begin() as conn:
        _, colega, _ = _admins_e_membro(conn)
        token = _reset(conn, colega, colega)
        servico.redefinir(
            conn, token, senha="senha novinha", quando=AGORA, nome_super="dono"
        )
        assert servico.entrar(conn, nome="colega", senha="senha novinha", quando=AGORA)
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas\test_servico.py -v`
Expected: FAIL — `TypeError: redefinir() got an unexpected keyword argument 'nome_super'`.

- [ ] **Step 3: Implement in the service**

Em `tf2price/contas/servico.py`:

Imports — troque
```python
from tf2price.contas import repositorio as repo
from tf2price.contas import senhas, tokens
from tf2price.contas.modelo import Usuario
```
por
```python
from tf2price.contas import permissoes, senhas, tokens
from tf2price.contas import repositorio as repo
from tf2price.contas.modelo import Convite, Usuario
```

Acrescente, logo antes de `def redefinir`:

```python
def redefinicao_autorizada(
    conn: Connection, convite: Convite, nome_super: str | None
) -> bool:
    """O link de redefinição ainda vale para aquele alvo?

    Revalida no uso, e não só na geração, quem pode resetar a senha de quem:
    o link vale enquanto quem o gerou ainda poderia gerá-lo. Uma regra só
    cobre o link gerado para um membro que depois virou admin (senão o admin
    comum guardaria o link e tomaria a conta de um admin), a corrida entre
    gerar e promover, e o link de quem depois foi rebaixado ou desativado.
    """
    if convite.alvo is None or convite.criado_por is None:
        return False
    criador = repo.usuario_por_id(conn, convite.criado_por)
    alvo = repo.usuario_por_id(conn, convite.alvo)
    if criador is None or alvo is None:
        return False
    return permissoes.pode_gerir(criador, alvo, nome_super)
```

E substitua o começo de `redefinir`:

```python
def redefinir(
    conn: Connection, token: str, *, senha: str, quando: datetime
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_REDEFINICAO, quando)
    if convite.alvo is None:
        raise ConviteInvalido("convite inválido")
```

por

```python
def redefinir(
    conn: Connection,
    token: str,
    *,
    senha: str,
    quando: datetime,
    nome_super: str | None,
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_REDEFINICAO, quando)
    # Antes do hash e do consumo, como toda recusa aqui: a transação da
    # requisição fecha com commit mesmo no caminho de erro, e recusar depois
    # de consumir queimaria o link.
    if not redefinicao_autorizada(conn, convite, nome_super):
        raise ConviteInvalido("convite inválido")
```

O resto de `redefinir` fica igual.

- [ ] **Step 4: Run service tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\contas -v`
Expected: todos passam.

- [ ] **Step 5: Write the failing route test**

Acrescente ao fim de `tests/painel/test_convite.py` (imports `TestClient`, `criar_app`, `db`, `repo`, `servico`, `tokens` já existem):

```python
def test_link_de_reset_que_perdeu_a_autorizacao_da_404_e_nao_queima(engine):
    with engine.begin() as conn:
        repo.criar_usuario(conn, nome="dono", senha_hash="hash", admin=True, quando=db.agora())
        colega = repo.criar_usuario(
            conn, nome="colega", senha_hash="hash", admin=True, quando=db.agora()
        )
        amiga = repo.criar_usuario(
            conn, nome="amiga", senha_hash="hash", admin=False, quando=db.agora()
        )
        token = servico.convidar(
            conn, criado_por=colega, quando=db.agora(),
            tipo=servico.TIPO_REDEFINICAO, alvo=amiga,
        )
        repo.definir_admin(conn, amiga, True)

    cliente = TestClient(criar_app(engine, superadmin="dono"), follow_redirects=False)
    tela = cliente.get(f"/convite/{token}")
    assert tela.status_code == 404
    assert tela.text == "This invitation is no longer valid."

    envio = cliente.post(f"/convite/{token}", data={"senha": "senha novinha"})
    assert envio.status_code == 404
    assert envio.text == "This invitation is no longer valid."

    with engine.begin() as conn:
        assert repo.convite_por_hash(conn, tokens.hash_de(token)).usado_em is None
```

- [ ] **Step 6: Run route test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_convite.py -v`
Expected: FAIL — `TypeError: criar_app() got an unexpected keyword argument 'superadmin'`; `test_convite_de_redefinicao_troca_a_senha` também falha com `TypeError` de `redefinir` sem `nome_super`.

- [ ] **Step 7: Implement in app and route**

Em `tf2price/painel/app.py`, troque a assinatura e o começo de `criar_app`:

```python
def criar_app(
    engine: Engine,
    contexto: "Contexto | None" = None,
    agendador: Agendador | None = None,
    superadmin: str | None = None,
) -> FastAPI:
    app = FastAPI(title="briefcase.tf")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.engine = engine
    app.state.contexto = contexto
    # None nos testes e em qualquer app sem contexto: a página e o admin
    # dizem que a varredura não roda neste processo.
    app.state.agendador = agendador
    # Nome da conta dona do painel (`SUPERADMIN`). None: ninguém promove nem
    # rebaixa admins, e nenhum admin fica exposto — ver `contas/permissoes`.
    app.state.superadmin = superadmin
```

(o resto da função fica igual).

Em `tf2price/painel/acesso.py`, substitua `_convite_aberto` por:

```python
def _convite_aberto(conn: Connection, token: str, nome_super: str | None):
    """Convite utilizável, ou None. Não diz por que não serve."""
    convite = repo.convite_por_hash(conn, tokens.hash_de(token))
    if convite is None or convite.usado_em is not None:
        return None
    if convite.expira_em <= db.agora():
        return None
    # Link de reset que perdeu a autorização (o alvo virou admin, quem gerou
    # foi rebaixado) é só mais um link inválido. Sem isto a tela mostraria o
    # formulário de um link que `servico.redefinir` vai recusar.
    if convite.tipo == servico.TIPO_REDEFINICAO and not servico.redefinicao_autorizada(
        conn, convite, nome_super
    ):
        return None
    return convite
```

Em `tela_convite`, troque `convite = _convite_aberto(conn, token)` por
`convite = _convite_aberto(conn, token, request.app.state.superadmin)`.

Em `usar_convite`, troque `convite = _convite_aberto(conn, token)` por
`convite = _convite_aberto(conn, token, request.app.state.superadmin)`, e a chamada
`usuario = servico.redefinir(conn, token, senha=senha, quando=db.agora())` por:

```python
            usuario = servico.redefinir(
                conn, token, senha=senha, quando=db.agora(),
                nome_super=request.app.state.superadmin,
            )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_convite.py tests\contas -v`
Expected: todos passam.

- [ ] **Step 9: Commit**

```bash
git add tf2price/contas/servico.py tf2price/painel/app.py tf2price/painel/acesso.py tests/contas/test_servico.py tests/painel/test_convite.py
git commit -m "Revalida o link de reset no uso contra quem o gerou"
```

---

### Task 4: Admin — promover, rebaixar e botões por permissão

**Files:**
- Modify: `tf2price/painel/admin.py` (imports, `_tela_admin`, `gerar_redefinicao`, `mudar_ativo`, rota nova)
- Modify: `tf2price/painel/templates/admin.html` (seção `admin-people`)
- Test: `tests/painel/test_admin.py`

**Interfaces:**
- Consumes: `permissoes.eh_superadmin`, `permissoes.pode_gerir`, `permissoes.pode_mudar_admin` (Task 1); `repo.definir_admin`, `repo.definir_ativo(..., so_se_membro=...) -> bool` (Task 2); `criar_app(..., superadmin=...)` e `app.state.superadmin` (Task 3).
- Produces: rota `POST /admin/papel/{usuario_id}` com campo de formulário `admin` = `"1"` (promove) ou `"0"` (rebaixa).

- [ ] **Step 1: Write the failing tests**

Em `tests/painel/test_admin.py`:

1. Troque o helper `_entra` para aceitar o superadmin (os testes existentes continuam chamando sem ele, e ficam com `superadmin=None`):

```python
def _entra(engine, nome, admin, superadmin=None):
    with engine.begin() as conn:
        if admin:
            token = servico.convite_de_partida(conn, db.agora())
        else:
            dono = repo.usuario_por_nome(conn, "gusco")
            token = servico.convidar(conn, criado_por=dono.id if dono else None, quando=db.agora())
        servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=db.agora())
    cliente = TestClient(criar_app(engine, superadmin=superadmin))
    cliente.post("/entrar", data={"nome": nome, "senha": SENHA})
    return cliente
```

2. Acrescente ao fim do arquivo:

```python
# --- administradores e superadmin -----------------------------------------


@pytest.fixture
def dono(engine):
    """"gusco" é o superadmin: a primeira conta, e o nome na variável."""
    return _entra(engine, "gusco", admin=True, superadmin="gusco")


def _id(engine, nome):
    with engine.begin() as conn:
        return repo.usuario_por_nome(conn, nome).id


def _usuario(engine, nome):
    with engine.begin() as conn:
        return repo.usuario_por_nome(conn, nome)


def _colega(engine, nome="colega", superadmin="gusco"):
    """Admin comum: nasce membro e é promovido direto no banco."""
    cliente = _entra(engine, nome, admin=False, superadmin=superadmin)
    with engine.begin() as conn:
        repo.definir_admin(conn, repo.usuario_por_nome(conn, nome).id, True)
    return cliente


def test_superadmin_promove_e_rebaixa(dono, engine):
    _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")

    r = dono.post(f"/admin/papel/{alvo}", data={"admin": "1"})
    assert r.status_code == 200
    assert _usuario(engine, "amiga").admin is True
    assert "Remove admin" in r.text

    r = dono.post(f"/admin/papel/{alvo}", data={"admin": "0"})
    assert r.status_code == 200
    assert _usuario(engine, "amiga").admin is False
    assert "Make admin" in r.text


def test_promover_e_rebaixar_valem_na_requisicao_seguinte(dono, engine):
    """Sem derrubar a sessão: `admin` é relido do banco a cada requisição."""
    amiga = _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")
    assert amiga.get("/admin").status_code == 403

    dono.post(f"/admin/papel/{alvo}", data={"admin": "1"})
    assert amiga.get("/admin").status_code == 200

    dono.post(f"/admin/papel/{alvo}", data={"admin": "0"})
    assert amiga.get("/admin").status_code == 403


def test_admin_comum_nao_muda_papel_de_ninguem(dono, engine):
    colega = _colega(engine)
    _entra(engine, "amiga", admin=False)

    r = colega.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert r.text == "Not allowed."
    assert _usuario(engine, "amiga").admin is False

    r = colega.post(f"/admin/papel/{_id(engine, 'gusco')}", data={"admin": "0"})
    assert r.status_code == 403
    assert _usuario(engine, "gusco").admin is True


def test_admin_comum_nao_reseta_nem_desativa_admin(dono, engine):
    colega = _colega(engine)
    _colega(engine, nome="outro")

    for nome in ("gusco", "outro"):
        alvo = _id(engine, nome)
        r = colega.post(f"/admin/redefinir/{alvo}")
        assert r.status_code == 403
        assert r.text == "Not allowed."
        r = colega.post(f"/admin/ativo/{alvo}", data={"ativo": "0"})
        assert r.status_code == 403
        assert _usuario(engine, nome).ativo is True

    with engine.begin() as conn:
        resets = conn.execute(
            select(db.convite).where(db.convite.c.tipo == servico.TIPO_REDEFINICAO)
        ).all()
    assert resets == []


def test_admin_comum_continua_gerindo_membros(dono, engine):
    colega = _colega(engine)
    _entra(engine, "amiga", admin=False)
    alvo = _id(engine, "amiga")

    assert "/convite/" in colega.post(f"/admin/redefinir/{alvo}").text
    assert colega.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 200
    assert _usuario(engine, "amiga").ativo is False


def test_superadmin_reseta_e_desativa_admin(dono, engine):
    _colega(engine)
    alvo = _id(engine, "colega")

    assert "/convite/" in dono.post(f"/admin/redefinir/{alvo}").text
    assert dono.post(f"/admin/ativo/{alvo}", data={"ativo": "0"}).status_code == 200
    assert _usuario(engine, "colega").ativo is False


def test_superadmin_nao_se_rebaixa_nem_se_desativa(dono, engine):
    eu = _id(engine, "gusco")

    r = dono.post(f"/admin/papel/{eu}", data={"admin": "0"})
    assert r.status_code == 403
    r = dono.post(f"/admin/ativo/{eu}", data={"ativo": "0"})
    assert "You cannot disable your own account." in r.text

    gusco = _usuario(engine, "gusco")
    assert gusco.admin is True and gusco.ativo is True


def test_sem_superadmin_ninguem_muda_papel_nem_mexe_em_admin(admin, engine):
    """`admin` é o fixture antigo: "gusco" sem a variável, um admin comum."""
    _entra(engine, "amiga", admin=False)
    _colega(engine, superadmin=None)

    r = admin.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False

    assert admin.post(f"/admin/redefinir/{_id(engine, 'colega')}").status_code == 403
    assert "/admin/papel/" not in admin.get("/admin").text


def test_papel_exige_mesma_origem(dono, engine):
    _entra(engine, "amiga", admin=False)
    r = dono.post(
        f"/admin/papel/{_id(engine, 'amiga')}",
        data={"admin": "1"},
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False


def test_papel_para_usuario_inexistente_da_404(dono):
    r = dono.post("/admin/papel/999999", data={"admin": "1"})
    assert r.status_code == 404
    assert r.text == "User not found."


def test_membro_leva_403_no_papel(dono, engine):
    amiga = _entra(engine, "amiga", admin=False, superadmin="gusco")
    r = amiga.post(f"/admin/papel/{_id(engine, 'amiga')}", data={"admin": "1"})
    assert r.status_code == 403
    assert _usuario(engine, "amiga").admin is False


def _acao(caminho, ident):
    return f'action="/admin/{caminho}/{ident}"'


def test_botoes_vistos_pelo_superadmin(dono, engine):
    _colega(engine)
    _entra(engine, "amiga", admin=False)
    texto = dono.get("/admin").text
    eu, colega, amiga = (_id(engine, n) for n in ("gusco", "colega", "amiga"))

    for outro in (colega, amiga):
        for caminho in ("redefinir", "ativo", "papel"):
            assert _acao(caminho, outro) in texto
    assert _acao("redefinir", eu) in texto
    assert _acao("ativo", eu) not in texto
    assert _acao("papel", eu) not in texto

    assert "Owner · Active" in texto
    assert texto.count('data-confirm="Grant administrator access to this person?"') == 1
    assert texto.count('data-confirm="Remove administrator access from this person?"') == 1


def test_botoes_vistos_pelo_admin_comum(dono, engine):
    colega = _colega(engine)
    _colega(engine, nome="outro")
    _entra(engine, "amiga", admin=False)
    texto = colega.get("/admin").text
    eu, gusco, outro, amiga = (
        _id(engine, n) for n in ("colega", "gusco", "outro", "amiga")
    )

    assert "/admin/papel/" not in texto
    for admin_alheio in (gusco, outro):
        assert _acao("redefinir", admin_alheio) not in texto
        assert _acao("ativo", admin_alheio) not in texto
    assert _acao("redefinir", amiga) in texto
    assert _acao("ativo", amiga) in texto
    assert _acao("redefinir", eu) in texto
    assert _acao("ativo", eu) not in texto
    assert "Owner · Active" in texto
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_admin.py -v`
Expected: os testes antigos passam; os novos falham — `/admin/papel/*` responde 404/405 (rota inexistente) e as asserções de 403, `Owner` e botões falham.

- [ ] **Step 3: Implement the routes**

Em `tf2price/painel/admin.py`:

Imports — acrescente `permissoes` à linha dos imports de contas:

```python
from tf2price.contas import pedidos, permissoes
```

Logo depois de `ROTEADOR = APIRouter()`, acrescente:

```python
def _proibido() -> HTMLResponse:
    # Os botões proibidos não aparecem: só chega aqui requisição forjada ou
    # uma corrida com outra mudança de papel.
    return HTMLResponse("Not allowed.", status_code=403)
```

Substitua `_tela_admin` inteira por:

```python
def _tela_admin(
    request: Request,
    conn: Connection,
    usuario: Usuario,
    link=None,
    erro: str | None = None,
    varredura_msg: str | None = None,
):
    nome_super = request.app.state.superadmin
    return TEMPLATES.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            **_contexto_do_andamento(request, conn),
            "usuario": usuario,
            "usuarios": repo.listar_usuarios(conn),
            "pedidos": repo_pedidos.listar_pendentes(conn),
            "link": link,
            "erro": erro,
            "varredura": varredura_repo.ler_config(conn),
            "rodadas": varredura_repo.ultimas_rodadas(conn),
            "intervalo_minimo": varredura_repo.INTERVALO_MINIMO_MIN,
            "varredura_msg": varredura_msg,
            # A mesma regra das rotas, para os botões não prometerem o que a
            # rota recusa.
            "eh_superadmin": lambda u: permissoes.eh_superadmin(u, nome_super),
            "pode_gerir": lambda alvo: permissoes.pode_gerir(usuario, alvo, nome_super),
            "pode_mudar_admin": lambda alvo: permissoes.pode_mudar_admin(
                usuario, alvo, nome_super
            ),
        },
    )
```

Substitua o corpo de `gerar_redefinicao` por:

```python
    alvo = repo.usuario_por_id(conn, usuario_id)
    if alvo is None:
        # Sem isto o convite nasce com `alvo` apontando para ninguém: o
        # SQLite deixa passar, e a chave estrangeira do Postgres levanta.
        return HTMLResponse("User not found.", status_code=404)
    if not permissoes.pode_gerir(usuario, alvo, request.app.state.superadmin):
        # Quem gera o link pode usá-lo: resetar a senha de outro admin seria
        # tomar a conta dele.
        return _proibido()
    token = servico.convidar(
        conn,
        criado_por=usuario.id,
        quando=db.agora(),
        tipo=servico.TIPO_REDEFINICAO,
        alvo=usuario_id,
    )
    return _tela_admin(request, conn, usuario, link=f"/convite/{token}")
```

Substitua o corpo de `mudar_ativo` por:

```python
    if usuario_id == usuario.id:
        return _tela_admin(
            request,
            conn,
            usuario,
            erro="You cannot disable your own account.",
        )
    alvo = repo.usuario_por_id(conn, usuario_id)
    if alvo is None:
        # Sem isto, "sucesso" é um UPDATE que não bateu em linha nenhuma.
        return HTMLResponse("User not found.", status_code=404)
    nome_super = request.app.state.superadmin
    if not permissoes.pode_gerir(usuario, alvo, nome_super):
        return _proibido()
    ligado = ativo == "1"
    # Admin comum grava só se o alvo ainda for membro no instante do UPDATE:
    # a conferência acima leu antes, e uma promoção concorrente passaria
    # entre a leitura e a escrita.
    so_se_membro = not permissoes.eh_superadmin(usuario, nome_super)
    if not repo.definir_ativo(conn, usuario_id, ligado, so_se_membro=so_se_membro):
        return _proibido()
    if not ligado:
        # Desativar sem derrubar a sessão deixaria a pessoa dentro por
        # mais 30 dias.
        repo.apagar_sessoes_do_usuario(conn, usuario_id)
    return _tela_admin(request, conn, usuario)
```

Acrescente a rota nova logo depois de `mudar_ativo`:

```python
@ROTEADOR.post("/admin/papel/{usuario_id}", response_class=HTMLResponse,
                  dependencies=[Depends(ses.mesma_origem)])
def mudar_papel(
    request: Request,
    usuario_id: int,
    admin: str = Form(...),
    usuario: Usuario = Depends(ses.exigir_admin),
    conn: Connection = Depends(ses.conexao),
):
    alvo = repo.usuario_por_id(conn, usuario_id)
    if alvo is None:
        return HTMLResponse("User not found.", status_code=404)
    if not permissoes.pode_mudar_admin(usuario, alvo, request.app.state.superadmin):
        return _proibido()
    # Rebaixar não derruba a sessão: `usuario_da_sessao` relê `admin` do
    # banco a cada requisição, e o efeito já vale na próxima.
    repo.definir_admin(conn, usuario_id, admin == "1")
    return _tela_admin(request, conn, usuario)
```

Atualize a docstring do módulo para:
`"""Rotas de administração: convidar, redefinir senha, ativar/desativar e mudar papel."""`

- [ ] **Step 4: Implement the template**

Em `tf2price/painel/templates/admin.html`, substitua o bloco `{% for u in usuarios %} ... {% endfor %}` da seção `admin-people` por:

```jinja
  {% for u in usuarios %}
    <li class="admin-person">
      <div class="admin-person__identity">
        <strong>{{ u.nome }}</strong>
        <span>{{ 'Owner' if eh_superadmin(u) else ('Administrator' if u.admin else 'Member') }} · {{ 'Active' if u.ativo else 'Disabled' }}</span>
      </div>
      <div class="admin-person__actions">
        {% if pode_gerir(u) %}
        <form method="post" action="/admin/redefinir/{{ u.id }}">
          <button class="button button--quiet" type="submit">Reset password</button>
        </form>
        {% endif %}
        {% if pode_mudar_admin(u) %}
        <form method="post" action="/admin/papel/{{ u.id }}" data-confirm="{{ 'Remove administrator access from this person?' if u.admin else 'Grant administrator access to this person?' }}">
          <input type="hidden" name="admin" value="{{ '0' if u.admin else '1' }}">
          <button class="button {{ 'button--danger' if u.admin else 'button--quiet' }}" type="submit">{{ 'Remove admin' if u.admin else 'Make admin' }}</button>
        </form>
        {% endif %}
        {% if u.id != usuario.id and pode_gerir(u) %}
        <form method="post" action="/admin/ativo/{{ u.id }}"{% if u.ativo %} data-confirm="Disable this account and invalidate its sessions?"{% endif %}>
          <input type="hidden" name="ativo" value="{{ '0' if u.ativo else '1' }}">
          <button class="button {{ 'button--danger' if u.ativo else 'button--quiet' }}" type="submit">{{ 'Disable' if u.ativo else 'Reactivate' }}</button>
        </form>
        {% endif %}
      </div>
    </li>
  {% endfor %}
```

`briefcase.js` já confirma qualquer formulário com `data-confirm`; não precisa mudar.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel -v`
Expected: todos passam, inclusive `test_admin_copy_and_disable_confirmation` (sem superadmin, nenhum botão de papel aparece e a contagem do `data-confirm` de Disable continua 1) e os testes de acessibilidade e de UI em inglês.

- [ ] **Step 6: Commit**

```bash
git add tf2price/painel/admin.py tf2price/painel/templates/admin.html tests/painel/test_admin.py
git commit -m "Superadmin promove e rebaixa; admin comum age só sobre membros"
```

---

### Task 5: Variável `SUPERADMIN` na subida e documentação

**Files:**
- Modify: `tf2price/painel/app.py` (imports, funções novas, `servir`, `construir_aplicacao`)
- Create: `tests/painel/test_superadmin.py`
- Modify: `.env.example`, `README.md`, `AGENTS.md`, `docs/superpowers/specs/2026-09-22-administradores-design.md`

**Interfaces:**
- Consumes: `permissoes.eh_superadmin` (Task 1); `criar_app(..., superadmin=...)` (Task 3).
- Produces:
  - `aviso_do_superadmin(engine: Engine, nome: str | None) -> str | None` — a linha de log quando a variável não serve, ou `None`.
  - `preparar_superadmin(engine: Engine) -> str | None` — lê `SUPERADMIN` (sem espaços nas pontas; vazio vira `None`), imprime o aviso se houver e devolve o nome.

- [ ] **Step 1: Write the failing tests**

Crie `tests/painel/test_superadmin.py`:

```python
from __future__ import annotations

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.painel.app import aviso_do_superadmin, preparar_superadmin


def _usuario(engine, nome, admin=True, ativo=True):
    with engine.begin() as conn:
        ident = repo.criar_usuario(
            conn, nome=nome, senha_hash="hash", admin=admin, quando=db.agora()
        )
        if not ativo:
            repo.definir_ativo(conn, ident, False)


def test_sem_variavel_avisa(engine):
    aviso = aviso_do_superadmin(engine, None)
    assert aviso.startswith("[superadmin] SUPERADMIN ausente")


def test_nome_que_nao_existe_avisa(engine):
    aviso = aviso_do_superadmin(engine, "gusco")
    assert aviso.startswith('[superadmin] "gusco" não é um admin ativo')


def test_nome_de_membro_avisa(engine):
    _usuario(engine, "gusco", admin=False)
    assert aviso_do_superadmin(engine, "gusco") is not None


def test_nome_de_admin_desativado_avisa(engine):
    _usuario(engine, "gusco", ativo=False)
    assert aviso_do_superadmin(engine, "gusco") is not None


def test_admin_ativo_nao_avisa(engine):
    _usuario(engine, "gusco")
    assert aviso_do_superadmin(engine, "gusco") is None


def test_preparar_le_a_variavel_sem_espacos(engine, monkeypatch, capsys):
    _usuario(engine, "gusco")
    monkeypatch.setenv("SUPERADMIN", "  gusco  ")
    assert preparar_superadmin(engine) == "gusco"
    assert "[superadmin]" not in capsys.readouterr().out


def test_preparar_sem_variavel_devolve_none_e_avisa(engine, monkeypatch, capsys):
    monkeypatch.delenv("SUPERADMIN", raising=False)
    assert preparar_superadmin(engine) is None
    assert "[superadmin] SUPERADMIN ausente" in capsys.readouterr().out


def test_preparar_com_variavel_vazia_devolve_none(engine, monkeypatch):
    monkeypatch.setenv("SUPERADMIN", "   ")
    assert preparar_superadmin(engine) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_superadmin.py -v`
Expected: ERROR na coleta — `ImportError: cannot import name 'aviso_do_superadmin'`.

- [ ] **Step 3: Implement**

Em `tf2price/painel/app.py`:

Imports — acrescente `import os` junto de `import re`, e troque `from tf2price.contas import servico` por:

```python
from tf2price.contas import permissoes, servico
from tf2price.contas import repositorio as repo_contas
```

(`repo_contas`, e não `repo`, porque o módulo já importa `varredura_repo` e o nome curto ficaria ambíguo ao ler.)

Acrescente, logo antes de `def servir`:

```python
_SEM_GESTAO = "ninguém pode promover ou rebaixar administradores"


def aviso_do_superadmin(engine: Engine, nome: str | None) -> str | None:
    """A linha do log quando `SUPERADMIN` não serve, ou None quando serve.

    Não é erro fatal: sem superadmin o painel funciona e nenhum admin fica
    exposto — só não há quem promova ou rebaixe. Na primeira subida, antes
    de a conta nascer pelo convite de partida, o aviso é esperado; a conta
    vale como superadmin assim que existir, sem reiniciar.
    """
    if not nome:
        return f"[superadmin] SUPERADMIN ausente: {_SEM_GESTAO}"
    with engine.begin() as conn:
        usuario = repo_contas.usuario_por_nome(conn, nome)
    if usuario is None or not permissoes.eh_superadmin(usuario, nome):
        return f'[superadmin] "{nome}" não é um admin ativo: {_SEM_GESTAO}'
    return None


def preparar_superadmin(engine: Engine) -> str | None:
    """Lê `SUPERADMIN`, avisa no log se ela não serve e devolve o nome."""
    nome = (os.getenv("SUPERADMIN") or "").strip() or None
    aviso = aviso_do_superadmin(engine, nome)
    if aviso:
        print(aviso, flush=True)
    return nome
```

Em `servir`, depois do bloco do convite de partida (`if token: print(...)`), acrescente
`superadmin = preparar_superadmin(engine)` e troque a última linha por:

```python
    uvicorn.run(
        criar_app(engine, contexto, agendador, superadmin=superadmin),
        host="127.0.0.1",
        port=8000,
    )
```

Em `construir_aplicacao`, depois do bloco do convite de partida, acrescente
`superadmin = preparar_superadmin(engine)` e troque o `return` por:

```python
    return criar_app(engine, contexto, agendador, superadmin=superadmin)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_superadmin.py tests\painel\test_aquecimento.py -v`
Expected: todos passam.

- [ ] **Step 5: Document**

Em `.env.example`, acrescente ao fim:

```
# Nome exato da conta dona do painel (o superadmin). Só ela promove e rebaixa
# administradores, e ninguém mexe nela. Ausente, ou com um nome que não é um
# admin ativo, o painel funciona, mas ninguém promove nem rebaixa.
SUPERADMIN=
```

Em `README.md`, logo depois do parágrafo que termina em "`Dismiss` descarta o pedido.", acrescente:

```markdown
A conta nomeada em `SUPERADMIN` é a dona do painel: só ela promove e rebaixa
administradores (`Make admin` / `Remove admin` em `/admin`), e ninguém mexe
nela. Os outros administradores convidam, resetam senha e desativam apenas
membros. Sem a variável, o painel funciona, mas ninguém promove nem rebaixa.
```

Na lista de deploy do `README.md`, depois do passo 4 ("Na primeira subida, procure no log..."), acrescente:

```markdown
5. Depois de criar a conta, configure `SUPERADMIN` com o nome dela nas
   variáveis do serviço web.
```

Em `AGENTS.md`, na seção "Segurança e privacidade", acrescente um item ao fim da lista:

```markdown
- Quem pode mexer em quem na lista de pessoas mora em `contas/permissoes.py`;
  rotas, template do admin e revalidação do link de redefinição usam as mesmas
  funções. Não duplique a regra. Admin comum age só sobre membros: quem gera
  um link de reset pode usá-lo, então resetar outro admin é tomar a conta dele.
```

Em `docs/superpowers/specs/2026-09-22-administradores-design.md`, troque
`**Status:** aprovado, não implementado` por `**Status:** implementado`.

- [ ] **Step 6: Full verification**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: suíte inteira passa.

Run: `git diff --check`
Expected: nenhuma saída.

- [ ] **Step 7: Commit**

```bash
git add tf2price/painel/app.py tests/painel/test_superadmin.py .env.example README.md AGENTS.md docs/superpowers/specs/2026-09-22-administradores-design.md
git commit -m "Lê SUPERADMIN na subida e avisa no log quando ela não serve"
```

---

## Depois do merge (manual, fora do código)

Definir `SUPERADMIN` no Railway com o nome da conta atual do dono. Conferir no log da subida que **não** aparece a linha `[superadmin] ...`.
