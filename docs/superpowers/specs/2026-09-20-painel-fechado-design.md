# Painel fechado de avaliação de Unusual — design

**Data:** 2026-09-20
**Estado do projeto na partida:** `master` em `dbc7cc3`, 193 testes, aplicação local
de um usuário só, sem banco e sem sessão.
**Substitui:** nada. Envolve a consulta existente
(`docs/superpowers/specs/2026-09-19-consulta-unusual-design.md`) numa aplicação
com contas.

---

## 1. O que é

Uma aplicação hospedada onde **pessoas convidadas pelo dono** acompanham Unusuais
específicos. Cada pessoa tem a sua lista; a avaliação de um item é a mesma análise
que já existe, com os dois níveis rotulados e a idade do preço à vista.

Não há cadastro público, não há e-mail, não há varredura de mercado, não há alerta.
Quem entra, entra por um link que o dono gerou.

## 2. Decisões desta sessão, e por quê

| Decisão | Escolha | Motivo |
|---|---|---|
| Escopo | consulta + itens salvos por pessoa | menor escopo que justifica login; sem dado por pessoa a conta não guarda nada |
| Hospedagem | Railway | escolha do dono |
| Banco | **PostgreSQL** do Railway | não depende do disco do serviço; backup gerenciado; recriar o app não leva os usuários junto |
| Acesso ao banco | SQLAlchemy Core (não ORM) | mesmo código em Postgres na produção e **SQLite em memória nos testes**, que rodam em 0,5 s e sem serviço de pé |
| Contas | convite por link | o dono nunca vê senha de ninguém; nada de senha por mensageiro |
| Atualização de preço | retrato compartilhado + sob demanda | a Steam limita por IP, e no Railway todos saem pelo mesmo IP |
| Direção visual | gabinete de espécimes | é a única que usa aquilo que faz um Unusual ser um Unusual |
| Movimento | campo de emissão, três camadas | é o que uma partícula faz no jogo: nasce embaixo, sobe, morre |
| Planta | duas colunas | única que acomoda a análise inteira sem empurrar a vitrine para fora da tela |

## 3. Verificações feitas antes de desenhar

Medido em 2026-09-20, não suposto:

- **Arte de efeito existe e serve para compor.** `backpack.tf/images/440/particles/<id>_188x188.png`
  devolve PNG 188×188 com alfa real — pixel do canto `[0,0,0,0]`, 49% totalmente
  transparente, 0% totalmente opaco. Indexada pelo **mesmo id** que
  `tf2price/data/effects.json` já guarda.
- **Cobertura: 33 de 40 ids sorteados (83%).** Média de 36 KB por imagem. Os 547
  efeitos nomeados do schema cabem em ~20 MB em PNG, ~8 MB em WebP.
- **O Cloudflare da backpack.tf recusa cliente que não é navegador.** Todas as
  tentativas por script deram 403, com e sem cabeçalhos de navegador. Um `<img>`
  apontando para lá a partir de outra origem **não carrega** — verificado numa
  página real. Navegador na origem deles carrega.
- **Animação pronta do efeito não existe.** A Valve publica só `nome → id`; as
  imagens da wiki oficial do TF2 são screenshots de jogo inteiro (personagem,
  cenário) e não compõem; a backpack.tf serve PNG estático.
- **A Steam limita mesmo.** Algumas dezenas de requisições em poucos minutos
  produziram 429 tanto na busca quanto na página de listagens.

Consequência de projeto: **a arte é baixada uma vez e servida por nós**, nunca
puxada ao vivo de terceiro no caminho de renderização.

## 4. Arquitetura

O que existe hoje não muda: `domain/` e `sources/` ficam intactos, e
`lookup/analysis.py` continua puro — é ele que decide os números e ele não sabe
que existe usuário. Isso mantém os 193 testes atuais valendo.

| Peça | O que faz | Como se usa | Do que depende |
|---|---|---|---|
| `tf2price/db.py` | declara o schema uma vez, abre conexão, aplica versões | `engine()`, `criar_schema()` | SQLAlchemy |
| `tf2price/contas/repositorio.py` | usuário, convite, sessão, tentativa | funções que recebem conexão | `db` |
| `tf2price/contas/senhas.py` | gera e confere hash Argon2id | `gerar()`, `confere()` | argon2-cffi |
| `tf2price/contas/servico.py` | convidar, aceitar convite, entrar, sair, redefinir | funções puras de regra + repositório | repositório, senhas |
| `tf2price/acompanhamento/repositorio.py` | lista de itens por usuário | CRUD por `usuario_id` | `db` |
| `tf2price/preco/serial.py` | `ItemPage` ↔ dicionário | `para_dict()`, `de_dict()` | `sources/steam_page` |
| `tf2price/preco/retrato.py` | retrato compartilhado com validade e freio | `obter(hash_name)`, `forcar(hash_name)` | `db`, `serial`, `sources/steam_page` |
| `tf2price/efeitos/arte.py` | id do efeito → arquivo, ou ausência declarada | `caminho(efeito) -> Path \| None` | `data/efeitos/` |
| `tf2price/efeitos/coletor.py` | ferramenta de coleta única | `python -m tf2price.efeitos.coletor` | nenhuma do painel |
| `tf2price/painel/app.py` | rotas e sessão | ponto de entrada | todas acima + `lookup/analysis` |

**Regra de fronteira:** todo SQL vive dentro dos três repositórios. Nenhuma rota
escreve SQL. Trocar de banco é mexer em `db.py` e nos repositórios, não no painel.

**Uma réplica só.** O freio de requisições e o período de calma vivem na memória
do processo. Subir duas réplicas quebra os dois, e isso está escrito aqui para não
ser descoberto em produção.

## 5. Modelo de dados

```
usuario(id, nome único, senha_hash, admin bool, ativo bool, criado_em)
convite(hash_do_token PK, tipo, concede_admin bool, alvo, criado_por, criado_em, expira_em, usado_em, usado_por)
sessao(hash_do_token PK, usuario_id, criado_em, expira_em)
acompanhado(id, usuario_id, hash_name, efeito, criado_em)   -- único (usuario_id, hash_name, efeito)
retrato(hash_name PK, json, buscado_em)                      -- compartilhado por todos
tentativa(id, nome, quando)                                  -- freio de login
```

`tipo` do convite é `conta` ou `redefinicao`: o mesmo mecanismo serve para criar
conta e para trocar senha esquecida. `concede_admin` só é verdadeiro no convite de
partida descrito em §6 — um convite comum nunca cria administrador. `alvo` só
é usado no convite de redefinição: é de quem é a senha que aquele link troca.

O `retrato` guarda a `ItemPage` serializada, não HTML — alguns KB por item em vez
de 266 KB. `serial.py` tem teste de ida e volta: serializar e desserializar
devolve a mesma `ItemPage`.

**A lista do painel não guarda preço.** Cada linha é calculada na hora a partir do
`retrato` mais o índice da bp.tf, pelo mesmo `analysis.analyse` do detalhe. Assim a
coluna da esquerda nunca discorda da direita.

## 6. Contas, convite e sessão

**O primeiro acesso.** Na subida, se a tabela `usuario` estiver vazia, a aplicação
grava **no log** um link de convite de administrador, válido por 24 horas. O dono
lê o log do Railway, abre o link e cria a própria conta. Nenhuma senha em variável
de ambiente, nenhum usuário padrão.

**Convite.** Em `/admin` o dono gera um link com token de 32 bytes aleatórios,
válido por 7 dias e de uso único. O banco guarda **só o SHA-256 do token** — banco
vazado não vira convite válido. A pessoa abre o link, escolhe nome e senha, e a
conta nasce ativa.

**Senha.** Argon2id (`argon2-cffi`), parâmetros padrão da biblioteca. Mínimo de 10
caracteres. O dono nunca vê nem digita senha de ninguém.

**Sessão.** Token de 32 bytes no banco, guardado em hash, validade de 30 dias,
revogável — o dono consegue derrubar alguém sem trocar segredo nenhum. Cookie
`HttpOnly`, `SameSite=Lax`, e `Secure` ligado quando a requisição chega por HTTPS.
Fixar `Secure` sempre impediria entrar em `http://127.0.0.1` no desenvolvimento;
decidir pelo esquema da requisição mantém a produção segura sem quebrar a máquina
local.

**Freio de login.** Cinco falhas no mesmo nome em 15 minutos seguram aquele nome
por 15 minutos. Um painel exposto na internet sem isso vira alvo de força bruta em
uma semana.

**CSRF.** Cookie `SameSite=Lax` já barra POST de outro site. Além disso, toda rota
que muda estado confere o cabeçalho `Origin` contra o host da requisição e recusa
quando não bate. Sem token de formulário: com HTMX e origem única, ele custaria
complexidade sem cobrir risco novo.

**Desativar alguém:** `ativo = false` derruba as sessões na próxima requisição e
impede login. Os itens acompanhados ficam guardados.

## 7. Acompanhamento

Um acompanhado é o trio `(usuário, hash_name, efeito)` — efeito faz parte da
chave, porque o mesmo chapéu com efeito diferente é outro item econômico.

Botão **acompanhar** na avaliação; remover pela coluna esquerda. Toda leitura e
toda escrita filtram por `usuario_id`; o teste de isolamento é obrigatório.

Quando o retrato não tem mais listagem do efeito salvo — o item foi vendido — a
linha diz **"sem listagem deste efeito agora"** e mantém o item na lista. Não
apaga sozinho e não mostra o preço de outro efeito.

Quando ainda não existe retrato nenhum daquele chapéu — item salvo há pouco, ou
retrato nunca buscado neste banco — a linha diz **"sem dado ainda"** e oferece
atualizar. A tela nunca fica em branco esperando a Steam.

## 8. Retrato compartilhado e o limite da Steam

- Validade de **15 minutos**. Dois usuários no mesmo chapéu custam uma requisição.
- **Atualizar** força a busca, com piso de **60 segundos** por item.
- **429 da Steam liga um período de calma de 5 minutos**: nenhuma busca nova sai, e
  a tela mostra o retrato guardado dizendo *"a Steam está limitando — este dado tem
  23 min"*. Nunca esconde o número e nunca finge que é fresco.
- A idade do retrato aparece em toda linha e no detalhe. É o vocabulário nativo
  deste projeto e vale também para o dado da Steam, não só para o da bp.tf.

**O índice da bp.tf deixa de ser pré-condição de subida.** Hoje a aplicação morre
se a bp.tf não responder na partida; um serviço hospedado não pode. Ele passa a ser
carregado sob demanda, com nova tentativa, e enquanto não existir a saída paciente
aparece como **indisponível por falta do índice** — distinta de "a bp.tf não
precifica este efeito", que é outra coisa e já tem texto próprio.

## 9. A arte dos efeitos

**Coleta, uma vez.** `python -m tf2price.efeitos.coletor` sobe um servidor em
`127.0.0.1:8765` e abre uma página. O **navegador** busca cada
`particles/<id>_188x188.png` com pausa de 300 ms — é ele que passa pelo Cloudflare
—, converte para WebP preservando o alfa, e envia cada imagem ao servidor local,
que grava em `tf2price/data/efeitos/<id>.webp`. Ao fim, imprime quantas vieram e
**quais ids faltaram**, substituindo a estimativa de 83% por um número real.

~8 MB para os 547 efeitos nomeados, commitados no repositório. Servidos por
`/arte/{id}.webp` com cache longo.

A arte é de terceiro: renders da backpack.tf sobre partículas da Valve. Num painel
fechado entre convidados isso é aceitável, e fica registrado aqui.

**Efeito sem arte não ganha imitação.** A placa mostra o chapéu sozinho e o nome do
efeito recebe tratamento tipográfico — nome grande na fonte mono, com um fio fino —
mais a marca discreta *sem arte deste efeito*. Este projeto já reprovou uma versão
inteira por apresentar um dado no lugar de outro; uma aura genérica parecendo o
efeito repetiria o erro em outra moeda.

## 10. A tela

**Direção:** gabinete de espécimes. Fundo escuro com vinheta radial, serifada
(Spectral) nos nomes, IBM Plex Mono em todo número com `tabular-nums`, e a aura do
efeito como única fonte de cor viva — a cor vem da arte, não de código.

**Planta em duas colunas.** Esquerda: acompanhados e busca. Direita: a avaliação
inteira, com os quatro blocos e as etiquetas de nível que já existem. Clicar num
acompanhado troca só a direita.

**Movimento.** Campo de emissão de três camadas apenas no detalhe: cada cópia nasce
embaixo, sobe e morre, em fases defasadas. Na lista, uma camada pulsando. As
animações param sob `prefers-reduced-motion` e quando a aba fica oculta
(`visibilitychange`) — com dez cartões isso deixa de ser detalhe.

**Entrar** é uma placa só, com a aura ciclando entre alguns efeitos.

**Estreito.** Vira uma coluna, com os acompanhados numa faixa rolável no topo.
Continua valendo a régua do projeto: 400 px sem rolagem horizontal, contraste de
texto pequeno em 4,5:1 ou mais, foco visível.

## 11. Rotas

```
GET  /entrar                  POST /entrar                  POST /sair
GET  /convite/{token}         POST /convite/{token}
GET  /                        painel
GET  /buscar?q=               fragmento: itens
GET  /efeitos?nome=           fragmento: efeitos à venda
GET  /avaliacao?nome=&efeito= fragmento: coluna direita
POST /acompanhar              DELETE /acompanhar/{id}
POST /atualizar/{hash_name}     -- hash_name percent-encoded: os nomes têm espaço e apóstrofo
GET  /admin                   POST /admin/convite           POST /admin/redefinir/{usuario_id}
GET  /arte/{id}.webp
```

Tudo exige sessão, menos `/entrar` e `/convite/{token}`. `/admin` exige `admin`.

## 12. Erros

| Situação | O que a tela diz |
|---|---|
| Steam em 429 | mostra o retrato guardado e a idade, dizendo que a Steam está limitando |
| Steam fora do ar, sem retrato | "não consegui ler os dados da Steam", com o motivo |
| Estrutura da página mudou | `PageStructureError` com a parte que falhou, como hoje |
| Índice da bp.tf indisponível | saída paciente indisponível **por falta do índice** |
| bp.tf não precifica o efeito | texto atual, distinto do anterior |
| Convite expirado, usado ou inválido | uma mensagem só, sem distinguir os três — distinguir entrega informação a quem está tentando adivinhar token |
| Login errado | uma mensagem só para nome e senha, pelo mesmo motivo |

## 13. Testes

Os 193 atuais continuam valendo e nenhum teste novo toca a rede. Em SQLite na
memória:

- repositórios: criar, ler, apagar, e as restrições de unicidade
- convite: criar, aceitar, reusar (recusa), expirado (recusa), token inválido
- login: acerto, erro, e o freio disparando na sexta tentativa
- sessão: válida, expirada, revogada, usuário desativado
- **isolamento**: A não lê, não atualiza e não apaga item de B
- retrato: dentro da validade não busca; fora, busca; `forcar` respeita o piso de
  60 s; 429 liga a calma e a leitura seguinte serve o guardado
- `serial.py`: ida e volta devolve a mesma `ItemPage`
- arte: id com arquivo, id sem arquivo, id fora do mapa
- rotas: fumaça de cada uma, com e sem sessão

Uma suíte curta de fumaça pode apontar para um Postgres real por
`TF2PRICE_DATABASE_URL`, pulada por padrão. Ela existe para pegar diferença de
dialeto entre o SQLite dos testes e o Postgres da produção.

## 14. Implantação

Railway, **uma réplica**. Serviço web mais serviço Postgres.

```
uvicorn tf2price.painel.app:app --host 0.0.0.0 --port $PORT
```

Variáveis: `DATABASE_URL` (injetada pelo Railway) e `BPTF_API_KEY`. Não há segredo
de assinatura de sessão, porque a sessão é token no banco.

## 15. Fora de escopo

Alertas e notificações; worker de fundo; gráfico de histórico ao longo do tempo;
e-mail; cadastro público; varredura de mercado; outras moedas; aplicativo móvel;
compra automática. Nada disso entra agora.

## 16. Riscos conhecidos

1. **A arte depende de um terceiro que bloqueia servidor.** Mitigado por ser
   coleta única e cópia local, mas se a backpack.tf mudar o caminho, uma coleta
   futura quebra. A coleta atual continua valendo.
2. **Testes em SQLite, produção em Postgres.** Mitigado pelo subconjunto comum de
   SQL, pelo SQL confinado nos repositórios e pela suíte opcional contra Postgres.
3. **Uma réplica só.** Freio e período de calma são de processo. Escalar exige
   movê-los para o banco.
4. **A Steam pode apertar o limite.** O painel degrada mostrando dado velho com a
   idade à vista, que é o comportamento correto, mas se apertar muito a
   experiência piora e não há o que fazer do nosso lado.
5. **17% dos efeitos sem arte** na amostra. O número real sai do relatório da
   coleta; o plano B é tipográfico e declarado.

## 17. Ordem sugerida de construção

Cada etapa termina com a suíte verde e a aplicação de pé.

1. `db.py` e os repositórios, com os testes em SQLite na memória
2. contas: senha, convite, sessão, freio — ainda sem tela
3. `painel/` mínimo: entrar, sair, convite, e a consulta de hoje atrás da sessão
4. `preco/serial.py` e `preco/retrato.py`, com o cache substituindo o `PageCache`
   de memória
5. acompanhamento: salvar, listar, remover, isolamento
6. `efeitos/coletor.py`, a coleta real, e o relatório de quais ids faltaram
7. a tela nova: gabinete, duas colunas, campo de emissão, estados de ausência
8. `/admin`, o convite de partida pelo log, e a implantação no Railway
