# Administradores: promover, rebaixar e o superadmin intocável — design

**Data:** 2026-09-22

**Status:** implementado

**Base funcional:** `master` em `8220513`

---

## 1. Por que

A página `/admin` não tem como dar administrador a outra pessoa: o único admin
que existe nasce do convite de partida, e o convite comum sempre cria membro.
O dono quer promover e rebaixar admins, com uma condição: o superadmin — ele
mesmo — é intocável.

Ler o código mostrou que a condição precisa ir além do "ninguém tira o admin
dele". Hoje qualquer admin gera um link de **Reset password** para qualquer
pessoa, e quem gera o link pode usá-lo: troca a senha do outro e entra como
ele. Também desativa qualquer um que não seja ele mesmo. Com um admin só, isso
não tem vítima. Com dois, é a tomada de conta de um pelo outro. Por isso as
ações que já existem também mudam.

## 2. Decisões

| Tema | Decisão |
| --- | --- |
| Quem promove e rebaixa | só o superadmin |
| Admin comum | age só sobre membros: não reseta senha nem desativa outro admin |
| Identificação do superadmin | variável de ambiente `SUPERADMIN` com o nome da conta |
| Validade do superadmin | o nome bate **e** a conta é `admin` e `ativo` no banco |
| Variável ausente ou errada | ninguém é superadmin; ninguém promove nem rebaixa; nenhum admin fica exposto |
| Superadmin sobre si | pode resetar a própria senha; não se rebaixa nem se desativa |
| Admin comum sobre si | pode resetar a própria senha; não se desativa nem se rebaixa |
| Link de reset | revalidado no uso: vale só se quem o gerou ainda poderia gerá-lo para aquele alvo |
| Rebaixar | não derruba a sessão; `admin` é relido do banco a cada requisição |
| Rótulo na tela | "Owner" na linha do superadmin |
| Convite que já nasce admin | fora do escopo; promove-se depois de a conta existir |

### Por que variável de ambiente, e por que ela falha fechada

As alternativas eram o menor `id` (implícito) e uma coluna `superadmin`
(explícita, mas `db.criar_schema` usa `create_all`, que não acrescenta coluna a
tabela existente, e o projeto não tem migração). O dono escolheu a variável.

A fragilidade da variável — erro de digitação, conta renomeada, variável
esquecida no deploy — não expõe ninguém, porque a proteção dos admins não
depende dela: admin comum não age sobre admin nenhum, superadmin ou não. O que
a variável dá é só o poder de gerir admins. Errada, esse poder some até alguém
corrigi-la; não passa para outra pessoa.

A exigência de `admin` e `ativo` no banco fecha o caso restante: se a variável
nomeia uma conta que ainda não existe, quem receber um convite de membro pode
se cadastrar com esse nome, mas nasce membro e não vira superadmin.

## 3. Regras de permissão

`ator` é quem está logado (sempre admin, pois `/admin` exige `exigir_admin`);
`alvo` é a linha da lista.

| Ação | Ator superadmin | Ator admin comum |
| --- | --- | --- |
| Reset password | qualquer conta, inclusive a própria | a própria e membros |
| Disable / Reactivate | qualquer conta, exceto a própria | membros |
| Make admin / Remove admin | qualquer conta, exceto a própria | nenhuma |

Consequência: a linha do superadmin, vista por um admin comum, não tem ação
nenhuma. Vista pelo próprio superadmin, tem só Reset password.

Promover uma conta desativada é permitido: não dá acesso a ninguém enquanto ela
estiver desativada, e esconder o botão seria regra sem ganho.

## 4. Onde cada peça mora

### `tf2price/contas/permissoes.py` (novo)

Funções puras, sem conexão nem I/O. São a fonte única da regra: a rota decide
por elas, o template mostra botões por elas e `servico.redefinir` revalida o
link por elas.

- `eh_superadmin(usuario, nome_super: str | None) -> bool` — `nome_super`
  não vazio, igual a `usuario.nome`, e `usuario.admin and usuario.ativo`.
- `pode_gerir(ator, alvo, nome_super) -> bool` — Reset password e
  Disable/Reactivate. Falso se `ator` não é admin ativo. Verdadeiro se
  `ator.id == alvo.id` (a rota de ativo continua recusando desativar a si
  mesmo, como hoje). Verdadeiro se `ator` é superadmin. Senão, verdadeiro só
  se `alvo` não é admin.
- `pode_mudar_admin(ator, alvo, nome_super) -> bool` — `ator` é superadmin e
  `ator.id != alvo.id`.

### `tf2price/contas/repositorio.py`

- `definir_admin(conn, usuario_id, admin: bool) -> None`.
- `definir_ativo(conn, usuario_id, ativo, *, so_se_membro=False) -> bool` —
  com `so_se_membro`, o `UPDATE` leva `WHERE admin = false` e o retorno diz
  se alguma linha mudou. Admin comum sempre desativa por este caminho: a
  conferência em Python ("o alvo é membro?") e a escrita viram uma coisa só,
  e uma promoção concorrente não deixa passar a desativação de um admin. É o
  mesmo desenho de `consumir_convite`.

### `tf2price/contas/servico.py`

Nova função `redefinicao_autorizada(conn, convite, nome_super) -> bool`:
carrega `criador = usuario_por_id(convite.criado_por)` e
`alvo = usuario_por_id(convite.alvo)`, e devolve falso se algum dos dois não
existe ou se `not pode_gerir(criador, alvo, nome_super)`.

`redefinir(conn, token, *, senha, quando, nome_super)` a chama **antes** de
gerar o hash e de consumir o convite; se falso, levanta `ConviteInvalido` — a
mesma mensagem de link inválido de hoje.

Isso cobre três casos com uma regra: o link gerado para um membro que depois
foi promovido; a corrida entre gerar o link e promover; e o link gerado por
quem depois foi rebaixado ou desativado. A recusa vem antes do consumo, então
não queima o convite (a transação da requisição fecha com commit mesmo no
caminho de erro).

### `tf2price/painel/admin.py`

- Nova rota `POST /admin/papel/{usuario_id}`, campo `admin=1|0`, com
  `mesma_origem`. 404 se o alvo não existe; 403 se
  `not pode_mudar_admin(...)`. Senão `definir_admin` e a tela do admin.
- `POST /admin/redefinir/{id}`: 403 se `not pode_gerir(...)`.
- `POST /admin/ativo/{id}`: mantém a recusa de desativar a si mesmo e o 404;
  403 se `not pode_gerir(...)`; ator não superadmin grava com
  `so_se_membro=True` e responde 403 se nada mudou.
- O 403 é texto puro (`"Not allowed."`), no formato dos 404 que já existem. Os
  botões proibidos não aparecem, então só requisição forjada ou corrida chega
  a ele.
- `_tela_admin` passa ao template `nome_super` e as três funções de
  `permissoes`, para os botões usarem a mesma regra.

### `tf2price/painel/acesso.py`

- `POST /convite/{token}`: a chamada a `servico.redefinir` passa
  `nome_super=request.app.state.superadmin`.
- `GET /convite/{token}` e o `_convite_aberto` do `POST`: um link de
  redefinição que `redefinicao_autorizada` recusa é tratado como os outros
  inválidos — `404 "This invitation is no longer valid."`. Sem isto o `GET`
  mostraria o formulário de um link que o `POST` vai recusar. Com isto, o
  `ConviteInvalido` de `redefinir` fica só como defesa em profundidade.

### `tf2price/painel/app.py`

- `criar_app(engine, contexto=None, agendador=None, superadmin: str | None = None)`
  guarda `app.state.superadmin`. Os testes passam o nome direto, sem
  ambiente.
- `construir_aplicacao` lê `os.getenv("SUPERADMIN")` depois do `load_dotenv`
  e, na subida, confere numa transação curta se há um admin ativo com esse
  nome. Se a variável falta ou não bate, escreve no log:
  `[superadmin] SUPERADMIN ausente: ninguém pode promover ou rebaixar administradores`
  ou `[superadmin] "<nome>" não é um admin ativo: ...`. Não é erro fatal: o
  painel sobe.

### `tf2price/painel/templates/admin.html`

Na lista **People**:

- linha do superadmin: `Owner · Active` no lugar de `Administrator · Active`;
- **Reset password** só se `pode_gerir`;
- **Disable / Reactivate** só se `pode_gerir` e não é a própria linha;
- **Make admin** (membro) ou **Remove admin** (admin) só se `pode_mudar_admin`,
  ambos com `data-confirm` ("Grant administrator access to this person?" /
  "Remove administrator access from this person?").

## 5. Testes

Sem rede, SQLite em memória, como o resto da suíte.

**`tests/contas/test_permissoes.py` (novo)** — cada célula da tabela da
seção 3, e ainda: `nome_super` `None` e vazio; nome que bate com um membro;
nome que bate com um admin desativado; ator admin desativado.

**`tests/painel/test_admin.py`**:

- superadmin promove membro e rebaixa admin; a lista reflete na hora;
- admin comum recebe 403 em `/admin/papel/*`;
- admin comum recebe 403 ao resetar ou desativar outro admin e o superadmin;
- ninguém rebaixa nem desativa o superadmin, nem ele mesmo;
- com `superadmin=None`, `/admin/papel/*` dá 403 para todos;
- `/admin/papel/*` exige mesma origem e dá 404 para alvo inexistente;
- botões aparecem e somem conforme a tabela, visto pelo superadmin e por um
  admin comum; selo "Owner" na linha certa;
- rebaixado perde `/admin` na requisição seguinte, sem sair.

**Revalidação do link (`tests/contas/test_servico.py` e rota do convite)**:

- admin comum gera link para membro; o superadmin o promove; o link é recusado
  no `GET` e no `POST` (404) e continua **não consumido** (`usado_em` nulo);
- `servico.redefinir` chamado direto com esse link levanta `ConviteInvalido`
  sem consumir;
- link gerado por admin que depois foi rebaixado é recusado;
- link gerado pelo superadmin para um admin é aceito.

**Desativação condicional (`tests/contas/test_repositorio.py`)** —
`definir_ativo(..., so_se_membro=True)` num admin devolve `False` e não muda
a linha.

## 6. Documentação e deploy

- `.env.example`: `SUPERADMIN=` com comentário ("nome exato da conta dona do
  painel; sem ela ninguém promove ou rebaixa administradores").
- `README.md`: um parágrafo na seção de administração sobre promover,
  rebaixar e a variável.
- **Passo manual:** definir `SUPERADMIN` no Railway com o nome da conta atual
  do dono. Sem isso o painel funciona, mas ninguém promove admins.
