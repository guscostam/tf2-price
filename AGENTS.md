# AGENTS.md

## Escopo e objetivo

Este guia vale para toda a árvore do repositório. Use-o para localizar a área
responsável por uma mudança, preservar as decisões de domínio já comprovadas e
verificar o trabalho sem depender de serviços externos. O `README.md` explica o
uso do produto; specs e planos em `docs/` registram decisões e contexto
histórico. Não altere comportamento apenas para fazê-lo divergir desses
documentos: confirme primeiro o estado atual no código e nos testes.

## Produto e limites do domínio

O tf2price consulta o preço de um Unusual do TF2 na Steam e na backpack.tf para
ajudar a avaliar uma compra pontual. A unidade econômica é o par item-efeito:
dois chapéus com o mesmo nome e efeitos diferentes podem valer quantias muito
diferentes.

A interface combina dois níveis que devem permanecer explícitos:

- dados **por efeito**: listagens do efeito escolhido e preço da backpack.tf
  para esse efeito;
- dados **agregados do item**: livro de ofertas e histórico de vendas que a
  Steam publica para todos os efeitos juntos.

Nunca apresente o preço de outro efeito quando o efeito solicitado estiver sem
preço ou sem listagem. Também não descreva livro ou histórico agregado como se
fosse específico do efeito. Preserve as regras de identidade em `domain/`,
inclusive qualidade dupla, exceções de prefixo e exclusão de ferramentas que
aplicam efeito mas não são um item com aquele efeito.

## Stack e comandos

O projeto requer Python 3.12+ e usa FastAPI, templates Jinja com interações HTMX,
SQLAlchemy Core e pytest. No PowerShell, a preparação padrão é:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Se `.env` já existir, preserve o arquivo e as credenciais locais: não o
sobrescreva com o exemplo. O `.env` local precisa das variáveis descritas em
`.env.example`; não inclua seus valores em commits, testes, logs ou
documentação. Com o ambiente preparado, use:

```powershell
# aplicação local
.\.venv\Scripts\python.exe -m tf2price.painel.app

# suíte completa
.\.venv\Scripts\python.exe -m pytest

# teste focado (troque o caminho pelo arquivo ou nó da área alterada)
.\.venv\Scripts\python.exe -m pytest tests\painel\test_transacao.py
```

Produção usa a fábrica ASGI e os parâmetros definidos no `Procfile`:

```text
uvicorn --factory tf2price.painel.app:construir_aplicacao --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*
```

Não invente comandos de lint, formatação, migração ou build que o repositório
não configure.

## Mapa do repositório

- `tf2price/domain/`: tipos e regras puras do domínio, como `Brl`, identidade
  de itens e catálogo de efeitos.
- `tf2price/sources/`: clientes da Steam e backpack.tf, interpretação das
  respostas, limites de requisição e backoff.
- `tf2price/lookup/`: análise que cruza listagens, preços e câmbio sem cuidar de
  HTTP, rotas ou persistência.
- `tf2price/preco/`: serialização, repositórios e retrato compartilhado de preço
  com validade, idade e comportamento degradado.
- `tf2price/contas/`: usuários, senhas, tokens, convites, sessões e regras de
  autenticação.
- `tf2price/acompanhamento/`: persistência dos pares item-efeito acompanhados
  por cada usuário.
- `tf2price/painel/`: aplicação FastAPI, composição de dependências, rotas,
  autenticação, templates Jinja/HTMX e trabalho de aquecimento em segundo plano.
- `tf2price/data/`: `effects.json` e artes WebP empacotadas com a aplicação.
- `scripts/`: geração explícita de dados, hoje iniciada por
  `scripts/fetch_effects.py`.
- `tests/`: testes por área e fixtures determinísticas; espelham as fronteiras
  relevantes do pacote.
- `docs/`: specs, planos e achados históricos; consulte-os quando a mudança
  tocar uma decisão anterior, sem tratá-los como substituto do código atual.

## Fluxo de trabalho para mudanças

1. Leia o código da área e seus testes antes de editar. Siga as dependências até
   entender em qual camada a regra pertence.
2. Inspecione `git status` e o diff; preserve alterações alheias e não reformate
   ou reverta arquivos fora do escopo.
3. Para bug, escreva um teste de regressão que reproduza a falha. Em dinheiro,
   identidade, autenticação, transações, cache, concorrência ou integrações,
   cubra também falhas e degradação, não só o caminho feliz.
4. Faça a menor mudança coerente com as responsabilidades acima. Mantenha
   efeitos colaterais nas bordas e regras de domínio testáveis isoladamente.
5. Rode os testes focados durante a implementação. Ao final, revise o diff e
   rode a suíte completa antes de afirmar que a mudança terminou.

## Convenções de implementação

- Escreva regras de domínio como funções e tipos pequenos, explícitos e
  determinísticos. Injete relógio, clientes e outras fontes variáveis quando
  isso permitir testes sem espera nem rede.
- Represente dinheiro com `Brl`, que guarda centavos inteiros. Não use `float`
  para quantias monetárias; reserve-o para razões, como câmbio USD/BRL ou
  multiplicadores, e converta para `Brl` na fronteira monetária.
- Persista instantes em UTC ingênuo, como o valor retornado por `db.agora()`.
  Não misture datetimes com e sem fuso nem use horário local no banco.
- Preserve o instante original (`buscado_em` ou equivalente) ao reaproveitar
  cotação, retrato ou preço. O dado pode envelhecer; sua idade não pode ser
  reiniciada sem uma busca realmente bem-sucedida.
- Mantenha imports livres de I/O de rede e de inicialização que dependa de
  terceiros. Carregamento de `.env`, criação da aplicação e clientes pertencem
  aos pontos de entrada explícitos.
- Em FastAPI/Jinja/HTMX, mantenha os destinos de swap e respostas parciais
  coerentes: uma falha não pode deixar na tela a análise de um item ou efeito
  anterior como se fosse a resposta atual.

## Invariantes obrigatórios

- O efeito faz parte da identidade econômica e da chave do acompanhamento.
  Ausência de preço ou listagem para um efeito nunca autoriza usar outro.
- Preço e listagem por efeito devem continuar visualmente separados do livro e
  histórico agregados do item.
- Toda cotação, retrato ou preço persistido mostrado ao usuário deve conservar
  e expor sua idade real, inclusive quando antigo é melhor que indisponível.
- Nenhum import ou teste pode acessar a rede. Rotas não devem bloquear à espera
  da renovação da cotação.
- Nenhuma conexão ou transação de banco pode permanecer aberta durante HTTP,
  espera de rate limit, backoff ou qualquer outro I/O externo.
- Compatibilidade entre SQLite nos testes e PostgreSQL em produção é requisito;
  não dependa de permissividade, coerção ou semântica exclusiva de um dialeto.

## Banco de dados e transações

Use SQLAlchemy Core, não ORM. SQL deve permanecer nos módulos de repositório;
serviços recebem conexões e coordenam regras, em vez de esconder novas
transações. Mantenha transações curtas e faça validação ou trabalho caro fora
delas quando a atomicidade não exigir o contrário.

Antes de I/O externo, conclua e devolva ao pool qualquer conexão usada para ler
o cache. Depois da resposta, abra outra transação curta apenas para persistir o
resultado. Se uma operação precisa ser atômica — por exemplo, consumir convite
antes de criar conta — preserve a ordem e verifique concorrência explicitamente.

Os testes usam SQLite em memória com `StaticPool`, enquanto produção usa
PostgreSQL. Limites que o SQLite não impõe, comportamento de datas, concorrência
e conexões emprestadas precisam de validação explícita no código ou em testes
independentes do dialeto.

## Integrações externas, cache e concorrência

Para dados remotos, siga a ordem **memória → banco → rede**. Compartilhe caches
por processo ou no banco quando o dado for global; não faça uma chamada por
usuário quando uma resposta pode atender todos. Se a atualização falhar, sirva
o último dado válido com a idade visível e diferencie indisponibilidade de
ausência real no mercado.

Proteja estado compartilhado com travas. Preserve o `RateLimiter`, backoff
exponencial com jitter e o período de calma após limitação; não contorne essas
proteções em caminhos forçados. A trava do limitador serializa chamadas entre
threads, e as travas dos caches evitam renovação duplicada.

`CotacaoSobDemanda.obter` consulta apenas memória e banco: não acessa a rede. A
renovação da cotação pertence a `CotacaoSobDemanda.renovar` e é executada
exclusivamente pelo trabalho de fundo; rotas respondem com a cotação antiga ou
com o estado ainda indisponível em vez de renová-la.

Essa regra de renovação em segundo plano é específica da cotação. Outras buscas
remotas existentes, especialmente retratos via `Retratos.obter`, podem ocorrer
sincronicamente em uma rota. Mesmo nesses caminhos, conclua a leitura do banco e
devolva a conexão ao pool antes do I/O externo; abra outra transação curta apenas
depois da resposta, se for necessário persistir o resultado.

Mantenha uma única réplica de produção enquanto rate limiters, travas e períodos
de calma viverem somente na memória local do processo. Escalar réplicas exige
primeiro coordenar esse estado entre processos.

## Segurança e privacidade

- Persista somente o hash de tokens de convite e sessão; o token em claro só
  existe na entrega ao usuário ou no cookie correspondente.
- Invalide sessões ao sair, desativar conta e redefinir senha. Preserve consumo
  atômico e expiração de convites e mensagens que não revelem se usuário, token
  ou senha específicos existem.
- Exija validação de mesma origem em rotas mutáveis. Não remova as dependências
  de origem ao reorganizar rotas ou formulários.
- Mantenha cookies de sessão `HttpOnly`, com política `SameSite` adequada e
  `Secure` quando a aplicação está atrás do proxy. O comando de produção deve
  continuar interpretando os cabeçalhos encaminhados pelo Railway.
- Nunca grave credenciais, tokens, cabeçalhos sensíveis ou URLs de banco em
  logs e mensagens de erro. Passe exceções de terceiros pelo saneamento já
  existente antes de expô-las ou imprimi-las.

## Testes

Os testes não usam rede nem exigem Steam, backpack.tf, Railway ou PostgreSQL.
Forneça dublês determinísticos para clientes de terceiros, relógio, sono,
aleatoriedade e concorrência. Não introduza `sleep` real quando for possível
injetar relógio/eventos ou testar a função pura.

Coloque testes perto da responsabilidade alterada e reutilize fixtures apenas
quando elas preservarem a propriedade que se quer provar. Para transações, por
exemplo, conte conexões emprestadas pelo pool; uma leitura do SQLite pode não
abrir transação real e produzir um falso positivo. Para concorrência, force a
interlevação relevante e confirme tanto o resultado quanto o número de chamadas
externas.

Execute primeiro o arquivo ou nó afetado com pytest e, antes de concluir, a
suíte completa. Uma mudança documental também deve passar por `git diff --check`.

## Dados gerados e deploy

As dependências têm `pyproject.toml` como fonte de verdade. O
`requirements.txt` contém apenas `.` e serve de ponte para o construtor do
Railway instalar o próprio projeto; não mantenha uma segunda lista manual ali.

`tf2price/data/effects.json` e `tf2price/data/efeitos/*.webp` são dados gerados e
empacotados, não arquivos de edição casual. Atualize-os pelo fluxo gerador
correspondente e revise quantidade, origem e diff. Não regrave ou inclua em
massa artefatos que não sejam necessários à mudança.

O deploy usa PostgreSQL, variáveis de ambiente e o `Procfile`. Não coloque
credenciais reais no repositório nem acrescente publicação automática como
etapa de verificação. Alterações no startup devem preservar inicialização sem
rede obrigatória e o comportamento degradado quando terceiros estão fora do ar.

## Checklist de conclusão

- [ ] O diff contém apenas arquivos e mudanças necessárias, sem apagar ou
  sobrescrever trabalho alheio.
- [ ] O teste focado e a suíte completa passaram; `git diff --check` não relata
  problemas de whitespace.
- [ ] Nenhum segredo, token, `.env`, URL privada ou dado pessoal entrou no diff,
  em fixtures, logs ou mensagens de erro.
- [ ] Imports e testes permanecem sem rede; chamadas externas têm dublês,
  timeout, rate limiting, backoff e comportamento de falha apropriados.
- [ ] Nenhuma conexão ou transação fica aberta durante I/O externo, espera ou
  trabalho desnecessariamente longo.
- [ ] Dinheiro continua em `Brl`/centavos, datas persistidas continuam em UTC
  ingênuo e dados reaproveitados mostram a idade original.
- [ ] A separação entre efeito e agregado do item permanece explícita, inclusive
  nos casos sem preço ou sem listagem.
- [ ] README, specs ou documentação operacional foram atualizados quando a
  interface, configuração ou decisão correspondente mudou.
- [ ] Arquivos gerados e empacotados só mudaram quando necessário e pelo fluxo
  correto; o diff não contém artefatos, caches ou bancos locais acidentais.
