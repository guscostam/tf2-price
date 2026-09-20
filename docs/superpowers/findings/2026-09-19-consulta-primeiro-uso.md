# Consulta de Unusual — primeiro uso real

**Data:** 2026-09-19
**Amostra:** 56 itens Unusual, 74 pares item-efeito, dos mais caros do mercado

---

## A resposta

**O preço da Steam fica, na mediana, 1,72× acima do valor de troca do mesmo item.**

A arbitragem que este projeto foi construído para encontrar — comprar barato na
Steam e ganhar valor em chaves — **corre na direção contrária**. Não é que ela seja
rara: ela é sistematicamente negativa.

| Métrica | Valor |
|---|---|
| Razão mediana Steam ÷ troca | **1,72×** |
| Razão mínima observada | 0,84× |
| Razão máxima observada | 13,80× |
| Pares com preço dos dois lados | 36 de 74 (49%) |
| Pares com Steam **abaixo** do valor de troca | **1 de 36** |
| Arbitragem dura (Steam abaixo da melhor oferta de compra) | **0** |

---

## A inversão que isso revela, e ela é acionável

Se um chapéu vale 245 chaves na troca e a chave custa R$ 11,66 na Steam, comprar
245 chaves custa **R$ 2.857**. O mesmo chapéu, listado direto na Steam, custa
**R$ 9.000**.

O caminho lucrativo não é comprar o item na Steam. É **comprar chaves na Steam e
trocá-las pelo item**. O prêmio que existe sobre os itens não existe sobre a chave,
porque a chave é a mercadoria mais líquida do jogo e seu preço é arbitrado por
milhares de negociações por dia.

Casos concretos da amostra:

| Item | Efeito | Na Steam | Valor de troca | Razão |
|---|---|---|---|---|
| Unusual HazMat Headcase | Nuts n' Bolts | R$ 8.999,99 | R$ 2.856,70 | 3,15× |
| Unusual Sheriff's Stetson | Snowfallen | R$ 8.849,09 | R$ 2.332,00 | 3,79× |
| Unusual Old Man Frost | Dead Presidents | R$ 3.998,98 | R$ 291,50 | 13,72× |

---

## O único caso favorável, e por que ele não é uma recomendação

`Unusual Sear Seer` / `Galactic Flame`: R$ 3.668,17 na Steam contra R$ 4.346,25 de
valor de troca — 16% abaixo, resultado de +R$ 678,08.

**O preço de referência tem 651 dias.** É exatamente a situação que a regra de
honestidade da tela existe para expor: o número aparece, e ao lado dele aparece a
idade, para quem lê decidir. Um preço de quase dois anos não sustenta uma compra
de três mil e seiscentos reais.

Um caso em 36, apoiado em referência de 2024, não é um mercado.

---

## O que funcionou melhor do que o esperado

**Metade dos efeitos à venda tem preço na backpack.tf.** 36 de 74 pares.

A fixture do projeto veio de um item onde nenhum dos quatro efeitos à venda tinha
preço, e eu projetei essa proporção sobre o mercado inteiro. Era azar de amostra,
não regra. A cobertura real é razoável — o problema nunca foi a ausência de preço,
foi a **idade** dele e o **sentido** da diferença.

---

## Verificação do caso conhecido

`Unusual Taunt: Chairholder` / `Deep Dive`, consultado pela tela:

| Campo | Valor |
|---|---|
| Listagens do efeito | R$ 180,44 e R$ 271,76 |
| Mais barata | R$ 180,44 (15,6 chaves) |
| Melhor oferta de compra | R$ 106,31 (39 ordens) |
| Líquido após taxa | R$ 92,44 |
| Saída imediata | **R$ −88,00** |
| Saída paciente | indisponível — a bp.tf não precifica os efeitos à venda |
| Histórico | mediana R$ 197,41 em 139 vendas |

A separação de níveis aparece corretamente na tela: as listagens e a saída paciente
sob "para este efeito", o livro de ofertas e o histórico sob "todos os efeitos
deste item — a Steam não separa".

---

## Achados técnicos

### O filtro da busca descartava 30% dos nomes — corrigido em `ef9fa70`
`startswith("Unusual ")` na rota de busca eliminou **24 de 80 nomes** lidos. Entre
os descartados estão itens de dupla qualidade como `Strange Unusual <War Paint>`,
que existem no mercado e são de alto valor.

Uma leitura de 100 nomes em 2026-09-20 confirmou a proporção: **28 descartados, todos
`Strange Unusual ...`**. O filtro agora casa a palavra inteira em qualquer posição do
nome e recupera os 28. A correção expôs um segundo defeito no mesmo caminho: o parser
de identidade consome um prefixo de qualidade só, então esses nomes procuravam preço
na bp.tf sob `Unusual Bonk Boy` em vez de `Bonk Boy` e nunca achariam — diriam "a
backpack.tf não precifica este efeito", indistinguível de um efeito de fato sem preço.

Na mesma leitura apareceu o defeito inverso, que ninguém tinha notado: as ferramentas
`Unusual Taunt: X Unusualifier` **passavam** pelo filtro antigo sem serem itens
Unusual. Elas aplicam um efeito, não o têm; a tela de efeitos abria vazia. Agora são
recusadas por nome.

### Verificação ponta a ponta da dupla qualidade (2026-09-20)
Consulta real pela tela, depois da correção do filtro:

`/buscar "Bonk Boy"` devolve **`Strange Unusual Bonk Boy` e `Unusual Bonk Boy`** —
o primeiro era descartado antes. E o preço de troca **resolveu**, pelo candidato
`Bonk Boy`: sem o descascamento do `Unusual ` que sobra na base, o item diria "a
backpack.tf não precifica este efeito", que seria falso.

`Strange Unusual Bonk Boy` / `Green Confetti`:

| Campo | Valor |
|---|---|
| Na Steam | R$ 6.621,30 (567,9 chaves) |
| Valor de troca | R$ 1.982,20 (170 chaves, **893 dias**) |
| Melhor oferta de compra | R$ 1.696,89 (31 ordens) |
| Mediana histórica | R$ 515,50 em 559 vendas |

**3,3× de prêmio da Steam sobre a troca**, o mais extremo medido até aqui, contra
mediana de 1,72× da amostra de 56 itens. A mediana histórica a um oitavo do preço
pedido diz que essas listagens não são o mercado: são âncoras paradas. Zero
`PageStructureError`.

### `uvicorn` não estava declarado
A função que sobe o servidor o importa, e a dependência faltava no `pyproject.toml`.
Só apareceu na primeira tentativa de rodar. Corrigido em `b38e08f`.

### Subida e custo
O índice da backpack.tf é baixado uma vez na subida. Consultas subsequentes custam
duas requisições à Steam, como o spec promete — verificado pelo cache de página.

### Nenhuma falha de estrutura
56 páginas lidas, zero `PageStructureError`. A extração do `renderContext` se
manteve estável durante toda a sessão.

---

## Recomendação

**A aplicação está correta e responde a pergunta. A resposta é que a estratégia não
funciona no sentido em que foi imaginada.**

Se o interesse persistir, o caminho que os dados apontam é o inverso do desenho
original: **usar a Steam para comprar chaves, não itens.** Isso não precisa desta
aplicação — precisa de uma conta na Steam e de um parceiro de troca.

A tela continua útil para uma decisão pontual: antes de comprar um Unusual
específico na Steam, ela diz em segundos quanto aquilo vale na troca, quanto alguém
está disposto a pagar agora, e há quanto tempo o preço de referência não é
atualizado. Para *não* fazer um mau negócio, ela serve. Para encontrar bons
negócios sistematicamente, o mercado não oferece a matéria-prima.
