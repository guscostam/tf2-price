# Redesign `briefcase.tf` — design

**Data:** 2026-09-21

**Status:** aprovado para planejamento

**Base funcional:** aplicação existente em `master`, após `8bb8748`

**Referência visual:** `C:\Users\gusco\Desktop\briefcase-tf-branding-completo\briefcase-tf-branding-package`

---

## 1. Objetivo

Transformar a interface atual do tf2price no produto **briefcase.tf**, usando a
direção visual aprovada **Dossier Desk / Black File**, sem alterar a honestidade
dos dados, a identidade econômica item–efeito ou as regras já comprovadas das
integrações.

O resultado deve parecer uma ferramenta independente de inteligência de mercado
para Unusuals de Team Fortress 2: editorial, industrial, burocrática e próxima do
universo cultural do jogo, mas sem fingir ser um produto oficial e sem copiar
personagens, marcas ou ilustrações oficiais.

Este é um redesign do produto real. O protótipo do pacote de marca é referência
de linguagem visual e fluxo, não uma especificação de funcionalidades ou dados.

## 2. Decisões centrais

| Tema | Decisão |
|---|---|
| Nome | `briefcase.tf` |
| Descriptor | `Unusual Market Intelligence` |
| Tagline | `Every Unusual Is a Case.` |
| Idioma da interface | inglês |
| Direção visual | `Dossier Desk / Black File` |
| Estrutura | app shell com navegação persistente |
| Página inicial | dashboard operacional `Overview` |
| Consulta | fluxo dedicado `New Case` |
| Itens acompanhados | uma única área `Case Files`; não haverá `Watchlist` duplicada |
| Dados | somente dados e cálculos reais já suportados pelo produto |
| Imagens | imagem original do item e arte real do efeito; nunca uma aura inventada |
| Vereditos do protótipo | não implementar `Good Buy`, `Fair Price` ou `Caution` sem regra de domínio aprovada |

`Insufficient Data` pode ser usado como estado de ausência, pois não atribui um
juízo de mercado. Ele não autoriza estimativa, interpolação ou substituição por
dados de outro efeito.

## 3. Regra de honestidade visual

O novo conceito reforça, em vez de esconder, os dois níveis de informação:

- **`THIS EFFECT`**: listagens do efeito escolhido e preço sugerido da
  backpack.tf para esse efeito;
- **`ALL EFFECTS`**: livro de ofertas e histórico que a Steam agrega para o nome
  do item, independentemente do efeito.

Esses níveis devem usar rótulos persistentes e superfícies visualmente distintas.
Um dado agregado nunca ocupa um campo reservado ao efeito específico. Quando não
houver preço ou listagem para o efeito pedido, a interface declara a ausência e
não mostra o valor de outro efeito.

Toda cotação, retrato ou preço persistido conserva e mostra a idade original. O
redesign não transforma dado antigo em dado recente e não confunde falha de fonte
com ausência real de mercado.

## 4. Fundação da marca

### 4.1 Paleta

| Token | Valor | Uso principal |
|---|---:|---|
| Charcoal | `#0E0F10` | fundo estrutural do app |
| Ink Panel | `#15242A` | navegação e painéis escuros |
| Ink Blue | `#29424B` | divisórias, cabeçalhos e superfícies secundárias |
| Active Blue | `#365866` | item ativo, foco contextual e seleção |
| Paper | `#E8E1D1` | dossiês, fichas e áreas editoriais |
| Rust Stamp | `#A4453A` | carimbos, erros e ações destrutivas |
| Warning | `#D2A53B` | dados antigos, limitação e cautela operacional |

O azul deve parecer tinta de arquivo, nunca azul digital saturado. Rust Stamp não
é cor decorativa genérica: fica reservado para carimbos, erro e destruição. As
superfícies de números, preços e tabelas permanecem limpas; textura só aparece em
papel, abas e molduras.

### 4.2 Tipografia

- **Roboto Slab**: títulos editoriais e nomes de dossiê;
- **Roboto Condensed**: navegação, rótulos e números de destaque;
- **Inter**: texto de interface e conteúdo corrido;
- **IBM Plex Mono**: identificadores, datas, idade de dados e microtexto técnico.

As fontes serão servidas pela própria aplicação em WOFF2, com as licenças
correspondentes, para evitar dependência de CDN em tempo de execução. A pilha CSS
terá fallbacks de sistema para carregamento e degradação previsíveis.

### 4.3 Marca

O símbolo é a maleta geométrica aprovada. O fecho com duas linhas representa a
comparação entre evidência do efeito e contexto agregado do item. A implementação
parte do SVG vetorial em `04-prototype/favicon.svg`; o nome e o descriptor serão
texto vivo, não texto rasterizado.

Somente ativos necessários ao produto serão copiados para o repositório: o SVG da
marca, favicons derivados, fontes e suas licenças. Os PNGs de mockup continuam
como referência externa e não serão enviados como assets da aplicação.

O rodapé ou uma área institucional curta deve afirmar que o projeto é independente
e feito por fãs, sem sugerir afiliação à Valve, Steam ou backpack.tf.

## 5. Arquitetura de informação

### 5.1 Navegação autenticada

O app shell contém:

1. **Overview** — estado operacional e resumo dos casos;
2. **New Case** — busca, escolha de efeito e avaliação;
3. **Case Files** — pares item–efeito acompanhados pelo usuário;
4. **Sources** — origem, escopo e estado conhecido das evidências;
5. **Administration** — somente para administradores;
6. identidade da conta e **Log out** no rodapé da navegação.

Não haverá `Market Index`, previsões, analytics inventados nem uma `Watchlist`
separada de `Case Files`.

### 5.2 Rotas de página

| Método e rota | Página |
|---|---|
| `GET /` | `Overview` |
| `GET /cases/new` | `New Case` |
| `GET /cases` | `Case Files` |
| `GET /sources` | `Sources` |
| `GET /admin` | `Administration` existente, redesenhada |
| `GET /entrar` | login, com interface em inglês |
| `GET /convite/{token}` | criação/redefinição de conta, com interface em inglês |

As rotas HTMX e mutáveis existentes — entre elas `/buscar`, `/efeitos`,
`/analise`, `/acompanhar`, `/atualizar/{hash_name}` e a remoção de acompanhado —
continuam como endpoints internos do fluxo e não são renomeadas por estética. A
rota `/` muda do painel composto atual para o `Overview`; a consulta passa a ter
URL canônica `/cases/new`. Como hoje não existem URLs públicas separadas para
`Case Files` ou `Sources`, não há outro redirecionamento legado a criar.

Nenhuma migração de banco é necessária: um `Case File` continua sendo o par
item–efeito já guardado em `acompanhado`.

## 6. Sistema de componentes

### 6.1 Estrutura

- **App Shell**: fundo Charcoal, navegação Ink Panel e área principal;
- **Sidebar Navigation**: marca, links, seleção atual, conta e saída;
- **Page Header**: eyebrow mono, título Slab e ação principal opcional;
- **Dossier**: superfície Paper para narrativa, busca e identificação do caso;
- **Evidence Panel**: superfície escura limpa para preço, tabela e métricas;
- **Scope Label**: `THIS EFFECT` ou `ALL EFFECTS`, nunca apenas por cor;
- **Source Stamp**: fonte, idade e estado conhecidos;
- **Status Badge**: estado com texto e, quando útil, ícone;
- **Action Set**: primária, secundária, silenciosa e destrutiva;
- **Empty/Error State**: título, explicação factual e próxima ação segura.

Esses componentes serão expressos por macros/partials Jinja e classes CSS com
tokens centralizados. O objetivo é evitar que cada template recrie botões,
carimbos, estados e rótulos de escopo com pequenas divergências.

### 6.2 Composição do item e efeito

A vitrine continua usando três camadas da arte real do efeito ao redor da imagem
original do item. A URL do item permanece derivada da listagem real da Steam e a
arte do efeito permanece o WebP empacotado correspondente ao id.

Quando não existir arte para o efeito, a vitrine mostra o item sem emissão e um
tratamento tipográfico explícito — nome do efeito e `Effect artwork unavailable`.
Não se usa brilho, fumaça, gradiente ou partícula genérica que possa parecer o
efeito solicitado.

## 7. Páginas e comportamento

### 7.1 Overview

O `Overview` é um dashboard operacional, não um terminal de coleta. Ele mostra:

- cotação conhecida e idade real, ou `Awaiting evidence`;
- quantidade de pares item–efeito acompanhados pelo usuário;
- casos salvos mais recentemente, usando `criado_em` existente;
- estado resumido dos retratos já armazenados;
- avisos conhecidos de indisponibilidade, limitação ou dado antigo;
- ações `Open Case`, `Refresh Evidence` e `New Case`, quando aplicáveis.

Abrir o `Overview` não inicia busca na Steam nem na backpack.tf. A
`CotacaoSobDemanda.obter` já respeita esse contrato para a cotação. O índice da
backpack.tf ainda possui um `obter()` que pode ir à rede; portanto esta página não
o chama. Se a interface precisar saber se o índice já foi aquecido, a implementação
deve expor uma leitura não bloqueante do valor em memória, sem alterar rate limit,
backoff ou cálculo do índice. Estado desconhecido aparece como desconhecido.

Os casos da página são derivados dos retratos persistidos. Ausência de retrato é
`Awaiting evidence`, não preço zero e não mercado vazio.

### 7.2 New Case

Fluxo progressivo em uma única página:

1. o usuário pesquisa um nome; `/buscar` substitui a lista de resultados;
2. escolher um item chama `/efeitos` e remove imediatamente qualquer efeito ou
   análise pertencente à seleção anterior;
3. a aplicação apresenta somente os efeitos encontrados no retrato real;
4. escolher um efeito chama `/analise` e substitui integralmente o dossiê;
5. `Save Case` chama o acompanhamento existente; não cria outro tipo de registro.

O dossiê de análise organiza os números atuais em:

- **Purchase Price — `THIS EFFECT`**;
- **Active Listings — `THIS EFFECT`**;
- **Immediate Exit — `THIS EFFECT × ALL EFFECTS`**, deixando explícito que o
  custo vem da listagem do efeito e a oferta de compra é agregada do item;
- **Patient Exit — `THIS EFFECT`**, com preço sugerido da backpack.tf e idade;
- **Item Context — `ALL EFFECTS`**, para livro e histórico agregados.

A página não apresenta faixa estimada, confidence score ou parecer de compra.
Resultados positivos e negativos podem conservar a aritmética existente, mas não
viram `Good Buy`, `Fair Price` ou `Caution` por decisão apenas visual.

### 7.3 Case Files

`Case Files` lista exclusivamente os pares já acompanhados pelo usuário. Cada
linha ou cartão mostra nome, efeito, imagem/arte quando conhecidas, idade do
retrato, disponibilidade das fontes e os resultados que os dados atuais permitem.

- `Open Case` reabre `New Case` com o mesmo item e efeito selecionados;
- `Refresh Evidence` reutiliza a atualização existente;
- `Remove Case` mantém validação de mesma origem e recebe confirmação visual;
- ausência de listagem do efeito não remove o caso automaticamente;
- a lista não armazena preço próprio: continua derivada do retrato compartilhado
  e das mesmas regras de análise usadas no detalhe.

Desktop pode usar tabela editorial ou linhas densas. Em viewport estreito, cada
registro vira cartão legível; a responsividade não pode esconder escopo, idade ou
estado da fonte.

### 7.4 Sources

Página somente de leitura que explica:

- o que vem da Steam e o que vem da backpack.tf;
- a diferença entre `THIS EFFECT` e `ALL EFFECTS`;
- como taxa, saída imediata e saída paciente são interpretadas;
- que preço sugerido não é oferta de compra;
- a idade conhecida da cotação, dos retratos e dos preços por efeito;
- estados já conhecidos pela aplicação.

A página não executa health checks, pings ou novas consultas. Ela não declara uma
fonte `Online` apenas porque nenhum erro foi registrado. Onde não houver instante
ou estado confiável, mostra `Unknown` ou uma explicação equivalente.

### 7.5 Authentication e Administration

Login continua sendo username e password; o código de acesso fictício do
protótipo não existe. Convites, redefinição de senha, usuários ativos e ações de
admin mantêm o comportamento atual, com todo o texto visível em inglês.

`Administration` só aparece no menu e só responde para administradores. Ações
destrutivas usam Rust Stamp, texto explícito e confirmação, sem enfraquecer a
autorização do servidor.

## 8. Fluxo de dados e HTMX

O redesign preserva as fronteiras atuais:

- busca e retrato podem fazer I/O externo somente nos caminhos já destinados a
  isso;
- nenhuma conexão ou transação de banco permanece aberta durante HTTP, rate
  limit, backoff ou espera;
- cotação em rota é memória/banco; renovação continua no trabalho de fundo;
- regras e cálculos continuam em `domain/` e `lookup/`, não nos templates;
- SQL continua nos repositórios.

Cada fragmento HTMX possui um alvo único e deve ser seguro contra estado antigo.
O contêiner do fluxo usa a sincronização do HTMX para substituir ou abortar a
requisição anterior quando uma nova escolha do mesmo nível é feita; item e efeito
selecionados também são devolvidos no fragmento para manter sua identidade
inspecionável. Além disso:

1. selecionar outro item limpa seleção de efeito e análise antes de carregar;
2. selecionar outro efeito substitui toda a análise anterior;
3. falha de busca substitui os resultados daquela busca por seu erro;
4. falha ao obter efeitos também limpa análise anterior;
5. falha de análise não deixa números do efeito anterior na tela;
6. salvar, atualizar ou remover mantém a lista de casos sincronizada por resposta
   OOB apenas quando o fragmento corresponde ao estado atual.

A identidade de item e efeito deve viajar junta nos formulários e respostas que
dependem dela. Uma resposta atrasada ou cancelada não pode sobrescrever a seleção
mais recente.

## 9. Estados e erros

Vocabulário visual comum:

| Estado | Significado |
|---|---|
| `Loading evidence` | requisição em andamento para a seleção identificada |
| `Awaiting evidence` | ainda não há retrato conhecido |
| `No listings for this effect` | consulta válida sem listagem do efeito pedido |
| `Price unavailable for this effect` | índice disponível, sem preço para o efeito |
| `Stale evidence` | dado antigo ainda utilizável, com idade original visível |
| `Rate limited` | fonte recusou temporariamente novas consultas |
| `Source unavailable` | falha temporária, distinta de ausência de mercado |
| `Insufficient Data` | não há evidência suficiente para aquele bloco |

Um erro parcial não apaga dados válidos de outra fonte, mas cada bloco declara a
própria fonte e condição. Exceções externas passam pelo saneamento existente;
stack traces, tokens, cabeçalhos, credenciais e URLs privadas nunca aparecem no
HTML nem são incorporados a logs novos.

## 10. Responsividade, movimento e acessibilidade

### 10.1 Desktop e mobile

No desktop, a navegação é uma sidebar fixa dentro do app shell. Em telas estreitas,
ela vira uma barra superior compacta com abertura explícita do menu. Não se tenta
manter uma sidebar esmagada.

A aplicação deve funcionar a partir de 400 px sem rolagem horizontal da página.
Tabelas podem virar cartões ou uma região de rolagem rotulada e focável quando a
estrutura tabular for indispensável.

### 10.2 Movimento

- transições de interface entre 150 e 250 ms;
- movimento funcional para seleção, abertura do menu e troca de estado;
- campo de emissão em três camadas somente onde a arte real está em destaque;
- animação reduzida ou removida sob `prefers-reduced-motion`;
- animações decorativas pausadas quando a aba não está visível.

### 10.3 Acessibilidade

- contraste WCAG AA para texto e controles;
- foco de teclado sempre visível e ordem de navegação previsível;
- controles touch com alvo mínimo de 44 × 44 px;
- cor nunca é o único indicador de escopo, erro ou estado;
- labels reais e mensagens associadas aos campos de formulário;
- após erro, foco direcionado ao resumo ou primeiro campo inválido;
- imagens informativas com texto alternativo útil;
- texturas e ornamentos ignorados por tecnologia assistiva;
- `aria-current` na navegação e atributos de expansão no menu mobile;
- regiões dinâmicas anunciam carregamento e resultado sem repetir a página inteira.

## 11. Segurança e privacidade

O redesign não altera as garantias existentes:

- cookie de sessão `HttpOnly`, `SameSite` adequado e `Secure` atrás do proxy;
- validação de mesma origem em toda rota mutável;
- tokens de convite e sessão persistidos somente em hash;
- convite inválido, usado e expirado continuam indistinguíveis para o visitante;
- login não revela se foi o usuário ou a senha que falhou;
- sessões continuam invalidadas em logout, desativação e redefinição de senha;
- o menu ocultar `Administration` não substitui autorização no servidor.

## 12. Limites de implementação

### 12.1 Dentro do escopo

- app shell, navegação e páginas definidas neste documento;
- tradução completa da interface visível para inglês;
- componentes Jinja/HTMX e tokens CSS reutilizáveis;
- marca, SVG, favicon e fontes locais;
- composição real de item e efeito;
- estados de loading, vazio, antigo, limitação e erro;
- ajustes mínimos de rotas e de leitura não bloqueante necessários ao dashboard;
- atualização dos testes e da documentação operacional afetada.

### 12.2 Fora do escopo

- novas fontes de mercado;
- previsão de preço, faixa estimada ou confidence score;
- recomendação `Good Buy`, `Fair Price` ou `Caution`;
- histórico por efeito quando a fonte só fornece agregado do item;
- `Market Index`, gráficos inventados ou analytics novos;
- novo modelo `Case`, alteração da chave de acompanhamento ou migração de banco;
- mudanças de semântica em dinheiro, identidade, cache, rate limiting ou backoff;
- compra automática, alertas, notificações ou cadastro público;
- edição casual de `effects.json` ou das artes WebP geradas.

## 13. Estratégia de testes

Os testes permanecem determinísticos e sem rede. A implementação deve cobrir:

1. rotas e autorização de `Overview`, `New Case`, `Case Files`, `Sources` e
   `Administration`;
2. presença e seleção correta dos itens de navegação por papel do usuário;
3. tradução dos formulários e mensagens públicas sem mudar sua neutralidade de
   segurança;
4. `Overview` sem chamada de rede, inclusive quando índice e cotação não estão
   carregados;
5. troca de item limpando efeitos e análise anteriores;
6. troca de efeito substituindo toda a análise anterior;
7. falhas de busca, retrato e análise sem conteúdo antigo residual, inclusive
   quando respostas chegam fora de ordem;
8. separação textual e estrutural de `THIS EFFECT` e `ALL EFFECTS`;
9. ausência de preço e de listagem sem substituição por outro efeito;
10. idade original preservada em retrato, cotação e preço reutilizados;
11. salvar, abrir, atualizar e remover `Case Files`, incluindo isolamento entre
    usuários e validação de mesma origem;
12. controles administrativos invisíveis e inacessíveis a não administradores;
13. fallback de arte sem efeito visual inventado;
14. atributos essenciais de foco, menu, regiões dinâmicas e redução de movimento.

Durante a implementação, cada grupo roda primeiro seus testes focados. Antes da
conclusão rodam a suíte completa e `git diff --check`; o diff é revisado para
segredos, arquivos gerados, bancos, caches e artefatos acidentais.

## 14. Critérios de aceite

O redesign está pronto quando:

- todas as páginas autenticadas usam a mesma identidade e navegação responsiva;
- toda interface visível está em inglês;
- o usuário reconhece sem ambiguidade o que pertence ao efeito e ao item;
- nenhum dado fictício do protótipo aparece na aplicação real;
- item e efeito continuam usando suas imagens reais, com fallback honesto;
- idade e indisponibilidade permanecem visíveis;
- dashboard e página de fontes não bloqueiam em consultas externas;
- respostas HTMX não deixam evidência antiga associada à seleção atual;
- autenticação, autorização, convites e isolamento continuam intactos;
- desktop, 400 px, teclado e redução de movimento foram verificados;
- testes focados, suíte completa e `git diff --check` passam.
