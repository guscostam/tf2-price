# Varredura de cosméticos Unusual — design

**Data:** 2026-09-22

**Status:** aprovado para planejamento

**Base funcional:** aplicação existente em `master`, após `6fe9133`

---

## 1. Objetivo

Varrer automaticamente, num intervalo configurável no painel admin, **todas as
listagens de cosméticos Unusual** da Steam Community Market e mostrá-las numa
página do painel. Cada listagem diz se comprá-la na Steam e trocá-la pelo valor
da backpack.tf dá lucro ou prejuízo.

A varredura **complementa** a tela de consulta, não a substitui. O produto
continua sendo a decisão pontual (ver a memória "o objetivo real é a tela de
consulta"). Por isso a varredura nunca pode prejudicar a consulta: ela gasta o
mínimo de requisições, cede a vez e para ao primeiro 429.

### O que já se sabe sobre o resultado

Pelos achados de 2026-09-19 (`docs/superpowers/findings/`), a Steam fica, na
mediana, **1,72× acima** do valor de troca, e o preço de Unusual na backpack.tf
tem **749 dias de idade na mediana**. Então a maioria das linhas vai sair
negativa, e as positivas vão tender a ter preço de referência velho. A página
existe para achar a exceção, e **a idade do preço da backpack.tf é filtro, não
só coluna**.

## 2. Decisões centrais

| Tema | Decisão |
| --- | --- |
| Operação avaliada | Steam → troca: comprar a listagem na Steam, valer o preço da bp.tf em chaves |
| Fórmula | a mesma `patient_exit` da consulta: `chaves_bptf × preço_da_chave − preço_da_listagem` |
| Escopo de itens | todo cosmético Unusual (`item_class == "tf_wearable"` no schema da Valve), chapéu ou misc |
| Fora do escopo | taunts, armas, war paints, Strange Unusual (qualidade dupla), Unusualifiers |
| Granularidade | **uma linha por listagem**, não só a mais barata por efeito |
| Estratégia de varredura | rodada em dois níveis: passada rasa barata; passada funda só onde a assinatura mudou |
| Lucro | calculado na leitura, nunca gravado |
| Quem vê a página | todo usuário logado |
| Quem configura | só admin |
| Onde roda | thread de fundo no próprio processo (produção tem réplica única) |

Fora do escopo: alertas, notificações, Discord/Telegram, outras direções de
operação (troca → Steam, Steam → Steam), spells, e varredura de itens que não
são cosméticos.

## 3. Arquitetura

### 3.1 Módulo `tf2price/varredura/`

- **`escopo.py`** (puro, sem I/O): `e_cosmetico_unusual(hash_name) -> bool`.
  Usa `parse_market_hash_name` de `domain/identity.py` para exigir qualidade
  Unusual **sem** segunda qualidade, e confere o nome base contra o conjunto de
  cosméticos em `tf2price/data/cosmeticos.json`. Taunts, armas e war paints
  caem por não serem `tf_wearable`; Strange Unusual cai pela qualidade dupla;
  Unusualifiers pela regra de exclusão que já existe em `domain/`.
- **`rodada.py`**: orquestra uma rodada (seção 4). Recebe `SteamClient`,
  `SteamPageClient`, engine, relógio e sono por injeção.
- **`agendador.py`**: thread de fundo e trava de rodada única (seção 5).
- **`repositorio.py`**: todo o SQL das tabelas novas (SQLAlchemy Core).
- **`leitura.py`** (puro sobre dados já carregados): cruza listagens com o
  índice da bp.tf e a cotação, e aplica filtros, ordenação e paginação (seção 6).

### 3.2 Dado gerado: `tf2price/data/cosmeticos.json`

Esta é a lista de nomes base dos itens com `item_class == "tf_wearable"`,
extraída de `IEconItems_440/GetSchemaItems` (é paginado; segue `next` até o
fim). Ela é gerada por `scripts/fetch_cosmeticos.py`, com `STEAM_API_KEY`, no
mesmo molde de `scripts/fetch_effects.py`. Fica empacotada e não é editada à
mão, e o import não acessa a rede.

### 3.3 Tabelas

| Tabela | Colunas |
| --- | --- |
| `varredura_config` | `id` (sempre 1), `ligada` (bool), `intervalo_min` (int), `idade_max_funda_h` (int), `alterado_em` |
| `varredura_nome` | `hash_name` (PK), `menor_preco_cents`, `n_listagens` (a assinatura), `visto_em`, `funda_em` (nulo até a primeira leitura funda) |
| `listagem_varrida` | `listing_id` (PK), `hash_name`, `efeito`, `preco_cents`, `icone`, `lido_em` |
| `varredura_rodada` | `id`, `inicio`, `fim` (nulo enquanto roda), `nomes_lidos`, `fundas_feitas`, `falhas`, `motivo_parada` (`ok` / `429` / `erro` / `interrompida`) |

Dinheiro em centavos inteiros, instantes em UTC ingênuo (`db.agora()`).
Padrões iniciais de `varredura_config`: desligada, 180 min, 24 h.

`listagem_varrida.efeito` é nulo quando a Steam não informa o efeito. Essas
linhas aparecem com "effect unknown" e sem resultado, e nunca herdam preço.

## 4. A rodada

1. **Passada rasa.** `SteamClient.search_page(query="Unusual")` página a
   página (~180 requisições com 10 itens cada, medido em 2026-09-19). Para cada
   resultado que `e_cosmetico_unusual` aceita, guarda a assinatura
   (`menor_preco_cents`, `n_listagens`) e `visto_em` numa transação curta.
2. **Seleção da passada funda.** Um nome vai para a passada funda se:
   - a assinatura mudou desde a última leitura, **ou**
   - `funda_em` é nulo, **ou**
   - `funda_em` é mais velho que `idade_max_funda_h`.
3. **Passada funda**, nome a nome:
   1. `Retratos.obter(..., forcar=True)` busca a página do item e grava o
      retrato como a consulta faria. Com isso a tela de consulta fica
      instantânea para o item. O `obter` engole o `SteamLimitando` e devolve a
      `Leitura` com a calma ligada, então é esse sinal que para a rodada. A
      rodada só regrava as listagens quando a `Leitura` é **nova**
      (`buscado_em == quando`). Um retrato antigo devolvido por calma ou pelo
      piso de `forcar` nunca substitui listagens nem atualiza `funda_em`.
   2. Se `n_listagens` passa do que a página trouxe, busca as páginas
      seguintes de listagens (ver seção 9, verificação 1).
   3. Numa transação curta, **apaga todas as `listagem_varrida` do nome e
      insere as atuais**, e atualiza `funda_em`. Uma listagem vendida ou
      retirada some.
4. **Nomes que sumiram da passada rasa** (sem listagem nenhuma) têm as
   listagens apagadas ao fim de uma rodada **completa** (`motivo_parada = ok`).
   Uma rodada parada por 429 não apaga nada, porque não viu o mercado inteiro.

Nenhuma conexão com o banco fica aberta durante HTTP: cada passo lê, fecha,
faz a requisição e abre outra transação curta para gravar.

## 5. Agendamento e convivência com a consulta

- **Agendador.** Um thread daemon nasce na subida, ao lado do aquecimento, e
  a cada 60 s lê `varredura_config`. Começa uma rodada quando `ligada` é
  verdadeiro e a última rodada começou há mais de `intervalo_min`.
- **Uma rodada por vez.** Uma trava (`threading.Lock`, adquirida sem
  bloquear) serve ao agendador e ao botão "run now". Se já há rodada em
  curso, o botão diz isso e não faz nada.
- **Espaçamento próprio.** O `RateLimiter` compartilhado é uma trava simples,
  não uma fila de prioridade. A varredura dorme um intervalo extra
  (`ESPACO_EXTRA_S`, constante no código) entre as suas requisições, deixando
  a trava livre na maior parte do tempo. Uma consulta de usuário espera no
  máximo uma requisição da varredura.
- **Calma.** Antes de cada requisição, a rodada verifica a calma dos
  `Retratos`. Se está em calma, a rodada para com `motivo_parada = 429`.
- **Reinício do processo.** Na subida, qualquer rodada com `fim` nulo é
  fechada como `interrompida`. Não há retomada explícita: `funda_em` por nome
  faz a próxima rodada pular o que já foi lido.

## 6. A página "Market scan"

Nova aba do painel, para qualquer usuário logado, com a interface em inglês.

**Cabeçalho de estado:** fim da última rodada completa, rodada em curso (com
progresso), última parada por 429, total de nomes e listagens cobertos.

**Duas abas sobre a mesma tabela:** `All listings` e `Profitable` (resultado
> 0).

**Colunas:** arte do efeito · item · efeito · preço na Steam (R$ e chaves) ·
valor na bp.tf (chaves e R$) · **resultado** (R$ e %, verde/vermelho) · idade
do preço da bp.tf · idade da leitura da listagem · links para a tela de
consulta (item + efeito) e para a página do item na Steam.

**Resultado indisponível**, com o motivo que a `patient_exit` já devolve:
efeito desconhecido, índice da bp.tf não carregado, ou "backpack.tf does not
price this effect". **Nunca se usa o preço de outro efeito.** Sem cotação da
chave, a coluna de resultado inteira fica indisponível, com o aviso que a
consulta já mostra.

**Filtros** (na query string): texto no nome do item; efeito; faixa de preço na
Steam; **idade máxima do preço da bp.tf (padrão 90 dias)**; "só com preço na
bp.tf".

**Ordenação:** resultado em R$ (padrão), resultado em %, preço, idade do preço
da bp.tf.

**Paginação:** 50 por página, trocada via HTMX. O repositório traz as
listagens já filtradas por texto, efeito e preço. `leitura.py` calcula o
resultado em `Brl`, filtra por idade e lucro, ordena e pagina. Com milhares de
linhas isso é barato, e o câmbio não entra em SQL.

## 7. Painel admin

Seção nova em `/admin`:

- ligar/desligar a varredura;
- intervalo entre rodadas, **mínimo de 60 min**, validado no servidor;
- idade máxima da leitura funda, em horas (mínimo 1);
- botão `Run now`;
- as últimas 10 rodadas: início, duração, nomes, fundas, falhas e motivo de
  parada.

As rotas mutáveis exigem admin e validação de mesma origem, como as existentes.

## 8. Falhas

| Situação | Comportamento |
| --- | --- |
| 429 na passada funda (`Leitura` em calma) ou `SteamLimitando` na rasa | a rodada para e grava `429`; a calma dos `Retratos` vale para todos. Na passada rasa, o `SteamLimitando` também liga a calma dos `Retratos`, para a consulta não bater logo em seguida |
| `PageStructureError` ou outro erro num nome | pula o nome, soma em `falhas` e segue; as listagens antigas ficam com a idade real à mostra |
| Falha na passada rasa | a rodada para com `erro`; nada é apagado |
| Índice da bp.tf ou cotação indisponível | a página mostra as listagens e o resultado como indisponível; a varredura não depende deles |
| Processo reiniciado | a rodada aberta vira `interrompida` na subida |

## 9. Verificações antes de implementar

1. **Paginação de listagens na página do item.** O endpoint
   `/market/listings/.../render/` devolve HTML desde 2026-09-19, e a página traz
   só a primeira página de listagens. É preciso verificar se a página aceita
   `start`/`count` (ou outro parâmetro) para trazer as seguintes. **Se não
   aceitar**, a varredura guarda só as listagens que a página traz, e a linha
   do item mostra "N more on Steam" com o link. Nenhuma requisição é
   inventada.
2. **Quantas listagens a página traz** por padrão (supostamente 10).
3. **Quantos nomes a passada rasa aceita** como cosmético Unusual, para
   dimensionar o custo da primeira rodada, que é toda funda.

## 10. Testes

Sem rede, com clientes falsos, relógio e sono injetados, no SQLite em memória.

- **`escopo`:** aceita chapéu Unusual e misc Unusual; recusa taunt, Strange
  Unusual, arma com killstreak, war paint e Unusualifier.
- **`rodada`:** assinatura igual e dentro do prazo pula a funda; assinatura
  diferente, `funda_em` nulo ou vencido aprofundam; a funda substitui as
  listagens do nome; o 429 para a rodada sem apagar nada; nome quebrado não
  derruba a rodada; nomes sumidos só são apagados em rodada completa; nenhuma
  conexão emprestada durante a requisição (contando conexões do pool).
- **`agendador`:** não inicia com a varredura desligada nem antes do
  intervalo; duas tentativas simultâneas geram uma rodada só; rodada aberta
  vira `interrompida` na subida.
- **`leitura`:** resultado igual ao da `patient_exit`; efeito sem preço nunca
  herda de outro; efeito nulo sem resultado; filtro de idade; aba Profitable;
  ordenação; paginação.
- **Rotas:** a página exige login; a seção admin exige admin; intervalo abaixo
  de 60 é recusado; mesma origem exigida; resposta HTMX não mistura a página
  anterior.
