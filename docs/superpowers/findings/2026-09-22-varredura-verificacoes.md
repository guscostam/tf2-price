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
