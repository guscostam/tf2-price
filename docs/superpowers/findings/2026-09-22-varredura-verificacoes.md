# Verificações da varredura — 2026-09-22

Script: `verifica_pagina.py` (scratchpad, fora do repo), rodado com
`.\.venv\Scripts\python.exe` a partir da raiz do repo. Sem 429 na execução —
todas as 9 requisições (3 itens × 3 combinações de parâmetros) vieram
`200`, com 6s de espaçamento entre elas.

| Item | Sem parâmetro | `start=0&count=100` | `start=10&count=10` | `sell_orders` |
|---|---|---|---|---|
| Unusual Team Captain | 6 listagens | 6 listagens (mesmos ids) | `PageStructureError` (query ausente) | 6 |
| Unusual Brigade Helm | 5 listagens | 5 listagens (mesmos ids) | `PageStructureError` (query ausente) | 5 |
| Unusual Killer Exclusive | 15 listagens | 15 listagens (mesmos ids) | `PageStructureError` (query ausente) | 15 |

| # | Pergunta | Observado |
|---|---|---|
| 1 | A página do item aceita `count=100`? | **Não.** Para os 3 itens, `count=100` trouxe exatamente o mesmo número de listagens que a chamada sem parâmetro — inclusive os mesmos `listing_id` nos primeiros três, na mesma ordem. Isso vale inclusive para o Unusual Killer Exclusive, que tem `sell_orders=15` (> 10): 15 listagens sem parâmetro, 15 com `count=100`, nenhuma a mais. |
| 2 | Quantas listagens a página traz sem parâmetro? | Team Captain: 6. Brigade Helm: 5. Killer Exclusive: 15. Em todos os três, esse número bate exatamente com `orderbook.sell_orders` — ou seja, a página já embute todas as ofertas de venda existentes no `renderContext`, mesmo sem pedir mais. |
| 3 | `start=10&count=10` devolve outras listagens? | **Não** — nem as mesmas, nem outras. Nos 3 itens essa combinação quebrou o parser: `PageStructureError: query 'market_item_search' is missing from the page renderContext`. A página não devolveu a seção de listagens quando `start` ultrapassa o total disponível; não é um caso de "mesmas listagens repetidas", é ausência total dos dados. |

**Decisão para a Task 5:** "pular: a página ignora count; a tela mostra +N more on Steam"

A regra do plano é: se, para um item com `sell_orders > 10`, `count=100` trouxer
mais listagens que a chamada sem parâmetro, a Task 5 roda. O único item testado
com `sell_orders > 10` (Unusual Killer Exclusive, 15) não teve nenhum ganho —
15 listagens com e sem o parâmetro. Além disso, `start`/`count` fora do range
disponível não pagina; quebra a extração. A página do item não honra
paginação via `start`/`count`: ela embute, de fábrica, todas as listagens que
tem (aqui, sempre igual a `sell_orders`), e nada além disso é alcançável por
esses parâmetros. Task 5 não roda.

## Primeira rodada

Rodada real única, disparada por um script fora do repo
(`rodada_real.py`, scratchpad) que monta o contexto real
(`tf2price.painel.consulta.construir_contexto`, `.env` local) e chama
`tf2price.varredura.rodada.executar_rodada` contra a Steam e a backpack.tf de
verdade. Banco: SQLite descartável no scratchpad (`sqlite+pysqlite:///...`),
nunca o `DATABASE_URL` do usuário. `ESPACO_EXTRA_S` e o resto do espaçamento
não foram alterados.

### Números da rodada (Step 2 da spec)

| Métrica | Valor |
|---|---|
| Duração | 3546,2 s (59,1 min) |
| Motivo de parada | `ok` (nenhum 429) |
| Nomes lidos (passada rasa, únicos) | 604 |
| Nomes lidos a fundo (passada funda) | 604 (100% dos pendentes) |
| Falhas na passada funda | 0 |
| Passada rasa — chamadas a `aceitar` aceitas | 613 |
| Passada rasa — chamadas a `aceitar` rejeitadas | 1201 |
| Listagens armazenadas ao final | 5553 |
| Cobertura (`nomes` com `funda_em`, `listagens`) | 604 nomes, 5553 listagens |

Não houve 429 em nenhum ponto da rodada — nem na busca (passada rasa), nem nas
páginas de item (passada funda). As 604 fundas pendentes foram todas lidas com
sucesso, sem nenhuma falha de transporte ou `PageStructureError`.

**Nomes suspeitos rejeitados** (contém "Unusual", não é taunt, não é Strange,
não é Killstreak, não tem sufixo de wear/war paint — candidatos a cosmético
que o escopo está perdendo): **nenhum**. Todos os 1201 nomes rejeitados que
continham "Unusual" caíram em pelo menos uma das exclusões esperadas (taunt,
Strange, Killstreak, wear/war paint, ou simplesmente fora do
`cosmeticos.json`, mas sem sinal de nome com prefixo divergente tipo "The ").

### Preço da bp.tf e lucro (avaliados sobre as 5553 listagens armazenadas)

A primeira passagem usou `leitura.montar(...)` para tirar esses agregados e
gerou números errados por engano de método: `Pagina.linhas` é só a página 1
(no máximo `POR_PAGINA=50` linhas), não a lista completa — `Pagina.total` é
que é o agregado real. Os números abaixo foram recalculados chamando
`leitura.avaliar` diretamente em cada uma das 5553 listagens, sem paginar.
Isso é um erro do script de medição, não do código do produto (o contrato de
`Pagina` já separa `total` de `linhas`; só o script de verificação usou o
campo errado para o agregado).

| Métrica | Valor |
|---|---|
| Listagens com preço bp.tf utilizável para o efeito (`valor_bptf is not None`) | 4323 de 5553 (77,9%) |
| Lucrativas **sem** filtro de idade (`resultado.cents > 0`) | 516 |
| Lucrativas **com** filtro padrão de 90 dias (`IDADE_MAX_BPTF_PADRAO`) | 17 |
| Idade do preço bp.tf entre as 4323 com preço: mínima / mediana / máxima | 0 / 905 / 4609 dias |
| Dessas 4323, quantas têm idade ≤ 90 dias | 311 (7,2%) |

A mediana de idade do preço bp.tf usado (905 dias, ~2,5 anos) é muito maior
que os 90 dias do filtro padrão, e só 7,2% das listagens com preço têm um
preço bp.tf dentro da janela de 90 dias. É por isso que o filtro de idade
derruba 516 listagens "lucrativas" para 17: a maioria do que pareceria lucro
sem o filtro está medida contra um preço de anos atrás — exatamente o
falso positivo que a decisão de 2026-09-19 (comentário em
`tf2price/varredura/leitura.py`) já existia para evitar. Isto não é um
defeito: é a confirmação, com dado real, de que o filtro de 90 dias é
necessário e de que a maior parte do "lucro" bruto do scan é sinal velho, não
oportunidade real.

### Conferência cruzada (Step 3 da spec — 3 listagens contra o caminho de consulta)

Escolhidas 3 listagens com preço bp.tf. Para cada uma: leitura do retrato
armazenado (`tf2price.preco.repositorio.ler` + `serial.de_dict`) e
`tf2price.lookup.analysis.analyse(pagina, efeito, indice, key_brl)` — a mesma
função que a tela "Open case" usa.

| Item | Efeito | Preço da listagem aparece em `analyse.listings`? | É a mais barata do efeito? | `patient_exit.fair_value` bate com o valor do scan? | `patient_exit.age_days` bate com a idade do scan? |
|---|---|---|---|---|---|
| Unusual Sear Seer | Galactic Flame | Sim | Sim | Sim (R$ 4.376,25) | Sim (653 dias) |
| Unusual Hat with No Name | Sunbeams | Sim | Sim | Sim (R$ 3.034,20) | Sim (781 dias) |
| Unusual Smissmas Saxton | Defragmenting Reality | Sim | Sim | Sim (R$ 1.155,33) | Sim (1085 dias) |

As três bateram em tudo: o preço da listagem varrida está entre as listagens
do efeito devolvidas por `analyse`, e para a mais barata de cada efeito o
`patient_exit` (chaves, valor justo, idade) é idêntico ao que a linha da
varredura mostra. O caminho da varredura e o caminho da consulta pontual
concordam.

### Resultado

**DONE_WITH_CONCERNS.** Não foi encontrado nenhum defeito de código na
varredura, no escopo, na leitura da página ou na conferência cruzada com o
caminho de consulta — os três cross-checks bateram exatamente, zero falhas
nas 604 leituras fundas, zero 429, zero nome suspeito rejeitado. A
preocupação é de dado, não de código: o preço de referência da bp.tf para
Unusuals costuma ser muito velho (mediana de ~2,5 anos entre as listagens com
preço encontrado nesta rodada), o que faz a maior parte do "lucro" aparente
sem filtro de idade ser ruído. O filtro padrão de 90 dias já existe
justamente para isso e, nesta rodada real, reduziu 516 "lucrativas" brutas
para 17 prováveis — vale considerar se 90 dias ainda é a janela certa dado
quão raro é achar um preço mais fresco que isso para um efeito específico de
Unusual (só 7,2% das listagens com preço estavam dentro dela).
