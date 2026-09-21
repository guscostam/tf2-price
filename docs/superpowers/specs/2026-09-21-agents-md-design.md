# Design do AGENTS.md do tf2price

## Objetivo

Criar um `AGENTS.md` detalhado, na raiz do repositório, que permita a um agente
entender o produto, localizar responsabilidades, alterar o código com segurança
e verificar o trabalho sem depender de conhecimento fora do projeto.

O documento deve ser operacional: cada orientação importante precisa apontar
uma ação, um comando ou uma restrição concreta. As specs e os planos existentes
continuam como histórico de decisões, mas o agente não deve precisar lê-los para
realizar uma mudança comum.

## Estrutura

O guia será organizado pelas decisões que um agente precisa tomar durante o
trabalho:

1. propósito e limites do produto;
2. mapa da arquitetura e responsabilidade dos módulos;
3. preparação do ambiente, execução e comandos de teste;
4. fluxo de trabalho e critérios de conclusão;
5. convenções de implementação para domínio, FastAPI, templates, persistência e
   testes;
6. invariantes que não podem ser quebrados;
7. segurança, integrações externas e comportamento degradado;
8. checklist final de verificação.

O mapa arquitetural será por áreas, não um catálogo de todos os arquivos. Serão
citados arquivos de entrada e exemplos estáveis quando ajudarem a localizar o
código.

## Conteúdo específico do projeto

O `AGENTS.md` registrará, no mínimo:

- Python 3.12+, FastAPI, Jinja/HTMX, SQLAlchemy Core e pytest;
- execução local por `python -m tf2price.painel.app` e produção pela fábrica
  `tf2price.painel.app:construir_aplicacao`;
- testes sem rede, com SQLite em memória, e produção com Postgres;
- dinheiro representado em centavos por `Brl`, nunca por `float`;
- datas persistidas como UTC sem informação de fuso;
- separação rigorosa entre dados por efeito e dados agregados do item;
- obrigação de mostrar a idade de preços, cotações e retratos persistidos;
- proibição de I/O de rede durante imports e de conexões de banco mantidas
  durante I/O externo;
- ordem memória → banco → rede, caches compartilhados, rate limiting, backoff e
  reaproveitamento honesto de dados antigos;
- diferença entre `CotacaoSobDemanda.obter`, que não acessa a rede, e
  `renovar`, executado em segundo plano;
- uma única réplica em produção enquanto limitadores e períodos de calma forem
  locais ao processo;
- tokens armazenados somente como hash, sessões invalidadas nos fluxos
  apropriados, validação de origem e mensagens/logs sem segredos;
- `requirements.txt` mantido como ponte do Railway, com dependências definidas
  em `pyproject.toml`;
- `effects.json` e artes WebP como dados do pacote, alterados apenas pelo fluxo
  de geração correspondente;
- testes próximos à área alterada e suíte completa antes da conclusão.

## Fluxo esperado para mudanças futuras

O agente deve primeiro ler o código e os testes da área afetada, preservar
mudanças não relacionadas e converter todo bug corrigido em teste de regressão.
Deve executar testes focados durante a implementação e a suíte completa antes de
afirmar que o trabalho terminou. Mudanças em fronteiras críticas — dinheiro,
identidade de itens, autenticação, transações, cache, concorrência ou terceiros —
devem incluir casos de falha, não apenas o caminho feliz.

## Fora de escopo

O guia não vai:

- reproduzir integralmente README, specs ou planos;
- documentar cada função e rota;
- inventar ferramentas de lint, formatação ou migração que o projeto não usa;
- exigir acesso real à Steam, backpack.tf, Railway ou Postgres para rodar os
  testes;
- alterar código, configuração ou comportamento da aplicação.

## Critérios de aceitação

- Existe um único `AGENTS.md` na raiz e seu escopo cobre todo o repositório.
- Todos os comandos documentados correspondem à configuração atual.
- As regras específicas podem ser confirmadas no código ou nos testes.
- O texto distingue obrigações de contexto histórico.
- O documento é detalhado, mas evita listas frágeis de cada arquivo.
- Nenhuma instrução pede segredos, rede ou serviços externos para a verificação
  padrão.
