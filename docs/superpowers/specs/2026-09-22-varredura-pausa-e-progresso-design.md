# Varredura: pausa no 429, progresso e limpeza do histórico — design

**Data:** 2026-09-22

**Status:** implementado

**Base funcional:** `master` em `e7a7c84` (varredura de cosméticos Unusual já em produção)

---

## 1. Por que

Em produção, as duas primeiras rodadas disparadas pelo "Run now" terminaram
segundos depois de começar. O log do Railway mostra:

```
[varredura] rodada 1: 429, 0 nomes, 0 lidos a fundo, 0 falhas
[varredura] rodada 2: 429, 0 nomes, 0 lidos a fundo, 0 falhas
```

A Steam respondeu 429 à primeira requisição, e o IP do Railway já chega
limitado (o mesmo foi medido num deploy em 21/09). A rodada foi desenhada para
desistir no primeiro 429, que protege a consulta, mas no Railway isso quer
dizer que ela quase nunca passa da primeira página. A rodada local de 22/09,
feita no IP do dono, levou 59 min e não tomou nenhum 429.

O dono percebeu isso como "o scan para quando eu saio da página". Sair da
página não tem efeito nenhum: a rodada vive num thread do servidor. O que
faltou foi ver o que estava acontecendo. Daí as outras duas partes: o
progresso visível no admin, e o histórico, que nunca é apagado.

## 2. Decisões

| Tema | Decisão |
| --- | --- |
| 429 no meio da rodada | pausa e retoma o mesmo passo; desiste só após 4 pausas seguidas sem sucesso |
| Pausas | 5, 10, 20 e depois 30 min; qualquer requisição bem-sucedida zera a contagem |
| Diagnóstico | o log diz onde veio o 429: cotação do dólar, busca (qual página) ou página de um item |
| Interromper | botão "Stop scan" no admin; interrompe inclusive durante a pausa |
| Progresso | bloco "Current scan" no admin, atualizado a cada 5 s por HTMX enquanto há rodada |
| Histórico | limpeza automática ao fechar cada rodada: ficam as 20 mais recentes e a última completa |

Fora do escopo: mudar o intervalo mínimo, mudar o espaçamento de ~5 s entre
requisições, notificar o admin fora do painel, e a cotação congelada (bug
anterior, registrado à parte).

## 3. Pausa e retomada

### 3.1 Regra

Quando uma requisição da rodada termina em 429, a rodada **não termina**. Ela:

1. grava que está pausada e até quando;
2. espera a pausa, de forma interrompível (seção 4);
3. tenta **o mesmo passo** outra vez: a mesma página da busca (mesmo `start`)
   ou o mesmo chapéu. Nada é pulado nem lido em dobro.

A pausa n (n = pausas seguidas, a partir de 1) dura `PAUSAS = (5, 10, 20, 30)`
minutos. Se a tentativa feita **depois da quarta pausa seguida** também levar
429, a rodada termina com `motivo_parada = 429`, como hoje. Isso dá ~65 min
(5+10+20+30) sem nenhuma requisição bem-sucedida. Uma requisição bem-sucedida
zera a contagem, e a próxima pausa volta a ser de 5 min.

A pausa nunca é menor que a calma ainda em curso dos `Retratos` e do
`SteamClient`: ao fim da pausa, se sobrar calma de um dos dois
(`calma_restante_s()` de cada um, vale a maior), a rodada espera mais, e isso
conta como a mesma pausa. Antes de esperar a sobra, o andamento passa a mostrar
o novo fim esperado, para o admin nunca ver "Resuming at" com uma hora passada.

A calma esperada antes de cada passo (seção 3.2) é também a maior das duas. A
do `SteamClient` (60 s, `CALMA_APOS_429_S`) é ligada ainda pela renovação da
cotação em segundo plano e pela busca de usuário, que usam o mesmo cliente;
com ela ligada, o cliente recusa com `SteamLimitando` **sem** requisição, e
essa recusa não pode ser tratada como um 429 da rodada.

### 3.2 O que conta como 429

- `SteamLimitando` levantado pela busca ou pela cotação do dólar.
- `Leitura.limitando` devolvido por `Retratos.obter` na passada funda.
- A calma já ligada antes de uma requisição (um usuário acabou de bater no
  429), seja a dos `Retratos` ou a do `SteamClient`: a rodada espera o que falta
  da calma, e isso **não** conta como pausa seguida nem liga a calma dos
  `Retratos`, porque a rodada não fez requisição nenhuma.

### 3.3 Onde veio o 429

Hoje a taxa dólar→real é buscada de forma implícita dentro de
`steam.search_page` (duas requisições ao `priceoverview` na primeira chamada do
processo). A rodada passa a chamar `steam.usd_to_brl()` explicitamente antes da
passada rasa, como um passo próprio com a mesma regra de pausa. Assim o log
distingue os três lugares:

```
[varredura] rodada 3: 429 na cotação do dólar; pausa 1 de 4, até 14:32 UTC
[varredura] rodada 3: 429 na busca (página 12); pausa 2 de 4, até 14:52 UTC
[varredura] rodada 3: 429 na página de Unusual Team Captain; pausa 1 de 4, até 15:10 UTC
```

### 3.4 Convivência com a consulta

Nada muda na proteção da consulta: todo 429 liga a calma dos `Retratos` (a
consulta mostra retratos guardados, com a idade) e a do `SteamClient`. A pausa
só faz a rodada **voltar** depois da calma em vez de ir embora. No pior caso, a
rodada faz 5 tentativas do mesmo passo (a primeira e uma depois de cada uma das
4 pausas). Cada tentativa pode fazer até 2 requisições HTTP, por causa da única
retentativa do cliente; a primeira tentativa da cotação do dólar pode fazer até
4, porque são duas chamadas ao `priceoverview`. Isso dá na ordem de 10
requisições em ~65 minutos contra um IP limitado.

## 4. Interromper ("Stop scan")

- O `Agendador` ganha um `threading.Event` de cancelamento, novo a cada rodada.
  `parar_rodada() -> bool` o liga e devolve falso se não houver rodada.
- A rodada recebe a espera como uma função `esperar(segundos) -> bool`, que
  devolve verdadeiro se foi cancelada. É `evento.wait` em produção e um dublê
  nos testes. O espaço extra de ~4 s, a espera da calma e as pausas passam por
  ela, de modo que o cancelamento é atendido na próxima espera: uma requisição
  já em curso, com a retentativa e o backoff do cliente, termina antes.
- Motivo novo: `MOTIVO_CANCELADA = "cancelada"`, com o rótulo "Stopped by admin".
  Uma rodada cancelada não apaga nomes sumidos, como qualquer rodada incompleta.
- Rota `POST /admin/varredura/parar` (admin, mesma origem). Ela responde com a
  página do admin e a mensagem "Stopping the scan…" ou "No scan is running.".

## 5. Progresso no admin

### 5.1 Dados

`create_all` não acrescenta colunas a uma tabela que já existe, e
`varredura_rodada` já existe em produção. O andamento vai, então, para uma
**tabela nova** de uma linha só, `varredura_andamento` (id sempre 1):

| Coluna | Significado |
| --- | --- |
| `rodada_id` | a rodada a que o andamento se refere |
| `fase` | `cotacao`, `busca` ou `paginas` |
| `paginas_busca_lidas`, `paginas_busca_total` | progresso da busca (total = ⌈`total_count`/10⌉, nulo até a primeira página) |
| `itens_lidos`, `itens_total` | progresso da passada funda (total = nº de pendentes) |
| `pausado_ate` | fim da pausa atual (UTC ingênuo), nulo fora de pausa |
| `pausas_seguidas` | contagem da regra da seção 3.1 |
| `atualizado_em` | último instante escrito |

A rodada escreve essa linha em transações curtas, que nunca atravessam
requisições nem esperas: ao mudar de fase, a cada página da busca, a cada
item e ao entrar e sair de uma pausa. Os contadores de `varredura_rodada`
(`nomes_lidos`, `fundas_feitas`, `falhas`) continuam como estão.

A pausa não é uma fase: `fase` continua sendo a do trabalho em curso
(`cotacao`, `busca` ou `paginas`), e a pausa é marcada por `pausado_ate` não
nulo. Assim a tela sabe de qual fase a rodada vai voltar ao terminar a
pausa.

### 5.2 Tela

- Rota `GET /admin/varredura/andamento` (admin) devolve o fragmento
  `_varredura_andamento.html`. O `/admin` o inclui na seção "Market scan".
- **Com rodada em curso** (`agendador.rodando`), o fragmento carrega
  `hx-get="/admin/varredura/andamento" hx-trigger="every 5s" hx-swap="outerHTML"`
  e mostra: há quanto tempo começou, a fase com barra e "X of Y", itens vistos,
  falhas e o botão "Stop scan". Em pausa, mostra "Paused: Steam is rate limiting
  this server · Resuming at HH:MM UTC (pause N of 4)".
- **Sem rodada**, o fragmento não tem o gatilho, então o polling para sozinho, e
  mostra "No scan running". Ao terminar uma rodada, a próxima atualização
  mostra também o resultado dela (o rótulo de `ROTULO_DA_PARADA`).
- A barra é um `<progress>` nativo, com texto equivalente para leitores de
  tela e nenhuma cor nova (a paleta permite só as 7 cores da marca).
- O botão "Run now" fica desabilitado enquanto há rodada, como hoje.

## 6. Limpeza automática do histórico

Na mesma transação que fecha uma rodada, `repositorio.podar_rodadas(conn,
manter=20)` apaga as rodadas **terminadas** que não estão entre as 20 mais
recentes e que não são a última completa (`motivo_parada = ok`). Uma rodada
aberta nunca é apagada. A tabela do admin continua mostrando as 10 últimas.

A última completa fica mesmo quando é antiga, porque `executar_rodada` usa o
início dela como referência para apagar os nomes sumidos. O intervalo do
agendador usa a última rodada, que sempre está entre as 20.

## 7. Falhas

| Situação | Comportamento |
| --- | --- |
| 429 em qualquer passo | pausa e retoma (seção 3); após 4 pausas seguidas, `429` |
| Stop durante requisição ou espera | termina como `cancelada` na próxima checagem |
| Erro de banco ao gravar o andamento | tratado como hoje: a rodada termina como `erro` |
| Reinício do processo em pausa | a rodada aberta vira `interrompida` na subida, e `varredura_andamento` é limpa |
| Agendador ausente (app sem contexto) | o fragmento mostra "The scanner is not available in this process." |

## 8. Testes

Sem rede e sem sono real (relógio, `esperar` e clientes falsos), em SQLite:

- **Pausa:**
  - Um 429 na busca pausa e retoma no mesmo `start`.
  - Um 429 numa página de item pausa e retoma no mesmo chapéu.
  - Um 429 na cotação do dólar pausa antes da busca.
  - As pausas seguem 5, 10, 20, 30 e 30 min.
  - Depois de 4 pausas seguidas, a rodada termina como `429` sem apagar nada.
  - Uma requisição bem-sucedida entre pausas zera a contagem.
  - A calma já ligada antes da requisição não conta como pausa.
- **Log:** a linha diz o lugar do 429.
- **Stop:** o cancelamento durante a espera termina como `cancelada` sem novas
  requisições, e `parar_rodada` sem rodada devolve falso.
- **Andamento:**
  - A linha reflete cada fase e cada contador.
  - Nenhuma conexão fica emprestada durante as requisições e esperas.
  - O fragmento com rodada tem o gatilho de 5 s, e sem rodada não tem.
  - O texto de pausa aparece.
  - As rotas exigem admin, e o `POST` também exige mesma origem.
- **Poda:**
  - Com 25 rodadas terminadas, sobram 20.
  - Uma completa antiga sobrevive quando as 20 recentes pararam por 429.
  - A rodada aberta nunca é apagada.
