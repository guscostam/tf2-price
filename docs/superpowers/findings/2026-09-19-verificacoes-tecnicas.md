# Verificações técnicas do spike — 2026-09-19

Observado na execução real. Onde o plano supôs errado, o registro é o valor
real, não o suposto.

---

## Veredito

**VERMELHO** — mas não pelo motivo que o spec antecipava, e a distinção importa.

O spec previa que VERMELHO significaria "mercado seco". O que se observou é
diferente: **o método está bloqueado, não o mercado desmentido.**

- **0 oportunidades líquidas confirmadas.**
- **675 candidatas ficaram por resolver** — 93% dos nomes que casaram — porque o
  endpoint que revelaria o efeito de cada Unusual deixou de existir (ver §2.9).
- **Das 24 avaliáveis, 24 foram reprovadas por preço desatualizado.** Cem por cento.

E a causa raiz disso é o achado central do projeto:

> **A idade mediana de um preço de Unusual na backpack.tf é 749 dias.**
> Apenas 2,3% das 41.606 entradas de Unusual foram atualizadas nos últimos 30 dias.

A premissa do projeto — comparar o preço da Steam contra o valor de mercado da
backpack.tf — pressupõe que a backpack.tf tenha preço atual. Para Unusual, ela
tem um retrato de dois anos atrás.

| Corte de frescor | Entradas | Fração |
|---|---|---|
| ≤ 30 dias | 955 | 2,3% |
| ≤ 60 dias | 2.486 | 6,0% |
| ≤ 90 dias | 3.450 | 8,3% |
| ≤ 180 dias | 6.178 | 14,8% |
| ≤ 365 dias | 10.887 | 26,2% |
| ≤ 730 dias | 20.419 | 49,1% |

Afrouxar a guarda não resolve: comparar contra preço de 2024 produz exatamente o
falso positivo que a guarda existe para impedir.

---

## 0-bis. O erro de lógica que invalida as 24 "oportunidades"

Levantado pelo usuário: *"você está listando apenas o nome do hat unusual, e esse
hat tem vários efeitos com preços diferentes."*

Está certo, e a consequência é maior que o problema de frescor.

A classificação "garantida" compara o preço da Steam contra o **mínimo entre os
efeitos que a backpack.tf precifica**, assumindo que isso seja um piso para
qualquer listagem daquele nome. **Não é.** O mínimo é sobre os efeitos
*precificados*, não sobre os efeitos *existentes*.

### Verificação num caso

`Unusual Taunt: Chairholder`, o maior desconto da lista (56%):

| | |
|---|---|
| Efeitos à venda na Steam | Midnight Whirlwind, Silver Cyclone, Deep Dive, Screaming Tiger |
| Efeitos precificados na bp.tf | 8, do id 3213 (24 chaves) a Scorching Sensation (150 chaves) |
| **Interseção** | **vazia** |

O relatório comparou uma listagem de *Midnight Whirlwind* a R$ 124,52 contra o
preço do efeito *3213* a 24 chaves. São itens diferentes. O "desconto de 56%" não
compara nada.

### Por que é sistemático e não azar

A backpack.tf precifica os efeitos que **circulam no mercado de troca** — os caros
e desejados. A Steam Market carrega os efeitos **comuns e baratos**, porque
Unusual de alto valor é negociado fora da Steam (§2.7). Os dois catálogos quase
não se sobrepõem, por construção do mercado.

### Consequência

As 24 oportunidades do §0 estão **retiradas**. O número correto de oportunidades
confirmadas em Unusual não é zero por preço velho — é **desconhecido e não
apurável**, porque para cada listagem falta o preço do efeito que ela de fato tem.

O `ValueRange` como piso só é válido quando a faixa cobre as variantes realmente
existentes. Para Unusual na Steam, não cobre. A poda das três vias, que é o
coração do desenho, apoia-se nessa premissa e portanto não se sustenta neste
escopo.

### Achado lateral
O efeito de id 3213 não consta do mapa de 569 efeitos extraído do schema oficial
da Valve. O `priceindex` da backpack.tf e o schema da Valve também não se alinham
inteiramente.

---

## 1. As oito verificações

| # | Item | Observado |
|---|---|---|
| 1 | Paginação de `/market/search/render` | **10 itens por página.** O parâmetro `count` é ignorado — testado com 10, 50, 100 e 200, sempre `pagesize=10`. `norender=1` é obrigatório: sem ele o array `results` volta vazio e a resposta vem em HTML. O plano supunha 100/página. |
| 2 | `currency=7` devolve BRL? | **Não na busca.** `/market/search/render` responde sempre em USD e ignora `currency` e `country` — testado nas quatro combinações. `/market/priceoverview` **honra** `currency=7` corretamente. Essa assimetria causou o bug de §3. |
| 3 | Requisições até o primeiro 429 | **A 1s: 429 na requisição 128.** A 3s: primeiro 429 na 280, com 5 no total ao longo de 389. Cooldown medido: **1 minuto**. Rajada curta (20 requisições) não aciona nada nem a 0,25s — o limite é de janela, não instantâneo. |
| 4 | Tamanho do `IGetPrices/v4` | Coube em memória sem streaming. **2.728 itens** no índice de TF2. |
| 5 | Efeito e craftabilidade nas `descriptions` | **Inacessíveis.** Ver §2.9. O efeito aparece no HTML da página, a craftabilidade não foi encontrada. |
| 6 | Mapa `priceindex` → efeito | **569 efeitos** extraídos de `attribute_controlled_attached_particles` do schema oficial. Não pôde ser exercitado de fato, por §2.9. |
| 7 | Trade hold em item comprado na Market | **Não verificado.** Exige comprar um item. Segue em aberto. |
| 8 | `sell_price` é o total do comprador | **Está em dólar, não em real.** Ver §3 — esta era a verificação que a revisão final da branch acrescentou, e a que mais custou por não ter sido feita antes. |

---

## 2. Achados que mudaram o desenho

### 2.1 O mercado é o dobro do estimado
41.080 nomes de TF2 na Steam, contra ~20.000 supostos.

### 2.2 A varredura completa custa 20x mais do que o plano previa
4.108 requisições em vez de ~200, por causa da verificação #1. A 3s são 3h25.

### 2.3 O filtro de texto resolve isso
`query=Unusual` reduz 41.080 → **1.817 nomes** (4,4%), e 4.108 → **182 requisições**.
Com o escopo estreitado para Unusual, a varredura cai de 3h25 para ~10 minutos.

### 2.4 Unusual não é mais só chapéu
Existem `Unusual Professional Killstreak <arma>`, `Unusual <War Paint>` e
`Unusual Taunt: <nome>`. O parser trata os três.

### 2.5 Nomes com duas qualidades não são tratados
`Strange Unusual Sleighin' Style War Paint` tem duas palavras de qualidade. O
parser consome a primeira e para, resultando em qualidade Strange com nome base
`Unusual Sleighin' Style War Paint`, que não existe no índice. Esses itens caem
em "não casados" — falha conservadora, não falso positivo.

### 2.6 60% dos Unusual da Steam não têm preço na backpack.tf
1.088 de 1.817 nomes não casaram.

### 2.7 O topo do mercado de TF2 na Steam são ~R$ 2.000
E os cinco itens mais caros não são Unusual — são war paints, chemistry sets e
killstreaks. Unusual de alto valor é negociado fora da Steam.

### 2.8 A ordenação alfabética inviabiliza execução truncada
`Unusual ...` cai na letra U. A primeira varredura morreu com 3% lido e não viu
um Unusual sequer. Trocado para preço decrescente.

### 2.9 O endpoint de listagens individuais deixou de devolver JSON
`/market/listings/440/<nome>/render/` responde **HTTP 200 com HTML de ~380 KB**,
`content-type: text/html`, em todas as combinações testadas: `l=english`,
`language=english`, `country=BR`, header AJAX, User-Agent de navegador.

As variáveis `g_rgAssets` e `g_rgListingInfo`, que a página usava para carregar
os dados, **não existem mais**. O efeito do Unusual ainda aparece no HTML
renderizado; `converted_price` e `Not Usable in Crafting` não foram encontrados.

**Consequência:** sem esse endpoint, efeito e craftabilidade por listagem são
incognoscíveis. Toda candidata fica por resolver. Só sobrevivem as "garantidas",
que são baratas mesmo no pior efeito — e no escopo Unusual elas são 24 de 1.817.

---

## 3. O bug de moeda, e por que ele importa além do conserto

A primeira execução com escopo Unusual deu **VERDE**: 21 oportunidades, desconto
médio de R$ 130,39, maior de R$ 686,12.

Era falso. `parse_search_page` lia `sell_price` como centavos de real; são
centavos de dólar. Todo preço da Steam saiu ~5,4x menor, fabricando descontos de
40% a 80% em fila.

O que disparou a investigação não foi um teste — foi o padrão: **21 oportunidades
e todas acima de 40%, várias acima de 80%, num mercado com bots.** Verificação
manual de um caso: `Unusual Taunt: The Travel Agent`, relatado a R$ 6,25 contra
R$ 35,22 de valor justo (82% de desconto). Preço real: **R$ 32,25**. Desconto
real: **8%**, abaixo do limiar.

Corrigido derivando a taxa da própria economia da Steam — preço da chave em BRL
dividido pelo preço da chave em USD, ambos de `priceoverview`, que honra moeda.
Sem cotação externa.

**Comparação das duas execuções, mesmo mercado, mesmo minuto:**

| | Com o bug | Corrigido |
|---|---|---|
| Veredito | VERDE | **VERMELHO** |
| Oportunidades líquidas | 21 | **0** |
| Garantidas | 684 | **24** |
| Candidatas | 27 | **675** |

### Blindagem pendente
A busca ainda envia `currency=7` por precaução. Se a Steam voltar a honrá-lo, os
preços sairão 5x altos e o resultado será zero oportunidades — um **falso
negativo**, que é silencioso. A correção é verificar que `sell_price_text`
começa com `$` e falhar alto se não começar. **Não implementada.**

---

## 4. Qualidade do casamento de nomes

Escopo Unusual, 1.817 nomes:

| | |
|---|---|
| Casados | 729 (40%) |
| Não casados | 1.088 (60%) |
| Garantidas | 24 |
| Candidatas | 675 |

---

## 5. Hipótese da guarda 4

**Refutada por ausência de amostra.** Zero itens precificados em USD no índice da
backpack.tf dentro do escopo Unusual, então a hipótese de preços derivados da
Steam Market não pôde ser testada. A detecção por moeda não se sustenta como
sinal. Alternativa registrada: cruzar contra a lista `/market` da própria
backpack.tf.

---

## 6. Recomendação

**Não construir o aplicativo como desenhado.**

O motivo não é o mercado ser seco — é a fonte de referência não existir no estado
que o desenho pressupõe. Comparar preço da Steam contra a backpack.tf exige que a
backpack.tf tenha preço atual de Unusual. Ela tem preço de dois anos atrás para a
maioria deles, e o endpoint que revelaria o efeito de cada listagem foi desligado
pela Valve.

Três caminhos, se o interesse persistir:

1. **Trocar a fonte de referência.** Os *classifieds* da backpack.tf são anúncios
   vivos, não preços sugeridos envelhecidos. Exigem assinatura premium e acesso
   elevado à API. É o caminho que ataca a causa raiz.

2. **Raspar o HTML da página de listagens.** Recupera o efeito do Unusual, mas
   não recupera o preço por listagem em forma estruturada, e é frágil por
   natureza. Resolve o sintoma de §2.9, não o de §0.

3. **Abandonar o escopo Unusual.** A varredura do mercado inteiro tem itens de
   nome limpo cujo preço na backpack.tf é mais fresco. Menor valor por
   oportunidade, mas comparação que se sustenta.

O spike custou uma tarde e evitou semanas. É exatamente para isso que ele existe.
