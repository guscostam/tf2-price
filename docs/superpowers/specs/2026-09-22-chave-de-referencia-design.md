# Chave de referência em dinheiro — design

**Data:** 2026-09-22

**Status:** aprovado, não implementado

**Base funcional:** `master` em `a8e345b`

---

## 1. Por que

A saída pela troca converte o preço da backpack.tf em reais com o preço da
chave no mercado da Steam:

```
valor_sugerido = chaves_bptf × lowest_price_da_chave_na_Steam
```

O dono deposita saldo na Steam por PIX ou cartão, real por real, e mede o
resultado em dinheiro. A chave, para ele, é só régua: não vende nenhuma, quer
saber quanto N chaves valem em dinheiro. O preço da chave na Steam não é isso.
É preço em saldo preso, e ainda por cima o preço de **compra**, com a taxa
embutida.

Medido em 22/09/2026, uma chave:

| Fonte | Valor |
| --- | --- |
| Mercado da Steam, `lowest_price` (o que a tela usa) | R$ 11,68 (US$ 2,27) |
| Steam descontada a taxa (÷ 1,15) | R$ 10,16 |
| Dólar da backpack.tf × PTAX | ≈ R$ 8,50 (US$ 1,67 × 5,11) |

Para um Unusual de 100 chaves, a tela diz R$ 1.168 onde a referência em
dinheiro diz uns R$ 850: a troca aparece cerca de 37% melhor do que é.

De carona, a cotação da Steam está congelada na vida do processo (cache do
`priceoverview` sem validade) enquanto a tela a mostra como recém-buscada. O
conserto entra aqui porque mexe no mesmo código.

## 2. Decisões

| Tema | Decisão |
| --- | --- |
| O que a chave mede | valor em dinheiro, não saldo da Steam |
| Custo da compra | o preço pago na Steam, real por real (o saldo entra por PIX/cartão) |
| Dólar da chave | backpack.tf: `raw_usd_value × chave_em_ref`, do `IGetPrices` que já é baixado |
| Dólar em real | PTAX de venda do Banco Central, última disponível |
| Sites de venda de chave (mannco.store, marketplace.tf) | descartados: Cloudflare na frente, sem API pública |
| AwesomeAPI | descartada em favor da fonte oficial; a PTAX diária basta para uma régua |
| Desconto fixo sobre o preço da Steam | descartado: número inventado com cara de medido |
| Preço da Steam na tela | sai; dois preços de chave lado a lado convidam a usar o errado |
| Renovar o índice da bp.tf | fora do escopo; a tela passa a mostrar a idade dele |
| `tf2price/spike/` | fora do escopo; é histórico e continua com o preço da Steam |

## 3. Qual chave cada número usa

**Chave de referência** (dinheiro):

- saída pela troca: `valor_sugerido = chaves_bptf × referência`, e
  `resultado = valor_sugerido − preço_pago`;
- "N chaves" da listagem mais barata e a coluna de chaves de cada listagem;
- o prêmio (listagem ÷ valor sugerido), que segue do valor sugerido;
- a varredura Steam → troca (`varredura/leitura.py`), pelo mesmo caminho.

"N chaves" precisa usar a referência para a tela não se contradizer: com o
preço da Steam, uma listagem de R$ 1.000 apareceria como "86 chaves" ao lado de
uma bptf de 100 chaves, sugerindo lucro, enquanto o resultado em reais daria
prejuízo. Com a referência ela aparece como "118 chaves", e as duas leituras
concordam.

**Chave da Steam** (só onde o assunto é a própria Steam):

- a saída imediata (maior ordem de compra menos a taxa) não muda;
- a taxa dólar→real implícita da Steam (chave em BRL ÷ chave em USD no
  `priceoverview`) continua convertendo as páginas de listagem que a Steam
  devolve em dólar. Ali a PTAX estaria errada: o que importa é quanto a
  Steam cobra em reais.

**Na tela**, o timbre da cotação passa a mostrar a referência e a origem:

```
≈ R$ 8,50 por chave · US$ 1,67 (backpack.tf, de há 2 dias) × R$ 5,11 (PTAX de 21/09)
```

O "≈" é obrigatório: `raw_usd_value` vem com três casas (0,026), o que dá até
~2% de imprecisão na referência.

## 4. Fontes, renovação e falha

### 4.1 Dólar da chave (backpack.tf)

O `IGetPrices` traz, no nível de `response`, `raw_usd_value` (dólar por
unidade de `usd_currency`) e `usd_currency` (hoje `"metal"`, índice 5002, o
refined). Medido em 22/09/2026: `0.026`, `"metal"`, `5002`.

- `PriceIndex.from_payload` passa a guardar `raw_usd_value` e `usd_currency`.
- `PriceIndex.key_in_usd()` devolve `raw_usd_value × key_in_refined`, ou
  `None` se `raw_usd_value` faltar, não for positivo, ou se `usd_currency` não
  for `"metal"`. Moeda inesperada é recusa, não conta errada.
- `PriceIndex` ganha `carregado_em` (quando o payload foi baixado), que vira a
  idade do dólar da chave na tela.
- Sai `Currencies.key_in_usd`: lê `price.usd` do `IGetCurrencies`, campo que a
  backpack.tf não manda mais, e vale 0 hoje sem ninguém perceber. Sai também
  do fixture de `tests/sources/test_backpacktf.py` e do falso de
  `tests/painel/test_sob_demanda.py`.

O índice continua carregado uma vez por processo e nunca renovado
(`manter_quente` o deixa de fora de propósito). Isso não muda aqui; o que muda
é que a idade dele deixa de ficar escondida.

### 4.2 PTAX (Banco Central)

Cliente novo, `tf2price/sources/bcb.py`:

```
GET https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/
    CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)
    ?@dataInicial='MM-DD-AAAA'&@dataFinalCotacao='MM-DD-AAAA'&$format=json
```

- Janela: os 10 dias até hoje. Fim de semana e feriado se resolvem sozinhos.
- Fica com o item de `dataHoraCotacao` mais recente e lê `cotacaoVenda`.
- Lista vazia, JSON fora do formato ou valor não positivo levantam erro com
  mensagem clara; quem chama trata como falha de busca.

`PtaxSobDemanda`, no molde de `CotacaoSobDemanda`: `obter` só lê (memória,
depois banco) e nunca vai à rede; `renovar` busca se o que há está velho, com
a mesma calma de 300 s após falha. A validade é de 1 hora: a PTAX sai uma vez
por dia, e buscar mais que isso é inútil.

Persistência numa tabela nova de uma linha, `ptax` (`id` fixo em 1, `valor`
float, `data_cotacao` datetime, `buscado_em` datetime). Tabela nova, e não
coluna em `cotacao`, porque `create_all` não acrescenta coluna a tabela
existente e o projeto não tem migração.

`aquecer` e `manter_quente` renovam a PTAX ao lado da cotação da Steam, em
chamadas independentes: uma falha não impede a outra.

A tela mostra a **data da cotação** (`data_cotacao`), não a hora da busca.
Segunda de manhã aparece "PTAX de sexta", e isso é o correto.

### 4.3 Cotação da Steam: o descongelamento

`CotacaoSobDemanda.renovar` hoje chama `key_price()` e `usd_to_brl()`, que leem
`_priceoverview_cache` e `_usd_to_brl` do `SteamClient`, caches sem validade.
A renovação a cada 15 min regrava `buscado_em` com o mesmo número.

`SteamClient` ganha `esquecer_cotacao()`, que zera os dois caches, e `renovar`
o chama antes de buscar. `Cotacao.key_brl` continua gravado (é o numerador da
taxa implícita, e a tabela já o tem), mas deixa de ser exibido e de entrar em
qualquer conta de chaves.

### 4.4 A referência montada

Tipo novo e puro, `ChaveReferencia` (em `tf2price/preco/`, perto do retrato):

```python
@dataclass(frozen=True)
class ChaveReferencia:
    brl: Brl                 # o que as contas usam
    usd: float               # dólar da chave na bp.tf
    ptax: float
    ptax_data: datetime      # data da cotação do BC
    bptf_carregado_em: datetime
```

`montar_referencia(indice, ptax) -> ChaveReferencia | None` devolve `None` se
faltar o índice, a PTAX ou o `key_in_usd()`. `brl` arredonda uma vez só:
`Brl.from_cents(round(usd × 100 × ptax))`.

As rotas montam a referência a cada requisição, a partir do índice em memória e
da PTAX de `obter`. Nada de rede no caminho da requisição.

### 4.5 Quando a referência falta

- `analyse` e `patient_exit` recebem `ChaveReferencia | None` no lugar de
  `key_brl`. Com `None`, a saída pela troca fica indisponível com motivo
  próprio: "the key reference price is unavailable (backpack.tf dollar value
  or PTAX missing)". A ordem de checagem mantém os motivos atuais primeiro
  (efeito desconhecido, índice não carregado).
- `Analysis.price_in_keys` vira `float | None`; o template mostra "—" e a
  coluna de chaves das listagens some.
- A saída imediata, as listagens, o livro e o histórico continuam funcionando:
  dependem só da Steam.
- A varredura trata `None` como já trata a falta de `key_brl` hoje.
- O timbre diz qual parte falta (índice ou PTAX), em vez do genérico.

A Steam ainda é exigida para abrir a consulta (`SEM_COTACAO`), porque sem a
taxa implícita as listagens em dólar não viram real. Isso não muda.

## 5. Testes

- `PriceIndex`: `key_in_usd` com payload normal; `None` sem `raw_usd_value`,
  com zero e com `usd_currency` diferente de `"metal"`.
- `bcb`: payload com vários dias fica com o mais recente; lista vazia e formato
  inesperado levantam erro.
- `PtaxSobDemanda`: `obter` não vai à rede; `renovar` dentro da validade não
  busca; falha mantém a guardada com a data original; processo novo lê do
  banco.
- `CotacaoSobDemanda`: duas renovações separadas pela validade fazem duas
  buscas ao `priceoverview` (o teste do congelamento).
- `montar_referencia`: conta e arredondamento; `None` para cada falta.
- `analyse`: valor sugerido e "N chaves" pela referência; saída imediata
  inalterada; sem referência, motivo próprio e `price_in_keys` nulo.
- Varredura: `avaliar` com referência e sem.
- Templates: o timbre com as duas idades; "—" sem referência.
