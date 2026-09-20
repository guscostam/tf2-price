# Consulta de Unusual — spec

**Data:** 2026-09-19
**Status:** aprovado, pronto para plano de implementação
**Substitui:** o app de varredura desenhado em `2026-09-19-tf2-arbitragem-spike-design.md`

---

## 1. Por que este desenho substitui o anterior

O spike de varredura foi executado e reprovado. As três causas estão em
`docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`:

1. **Preço de referência morto.** A idade mediana de um preço de Unusual na
   backpack.tf é de 749 dias; 2,3% têm menos de 30 dias.
2. **Comparação entre efeitos diferentes.** A backpack.tf precifica os efeitos que
   circulam na troca; a Steam carrega os comuns e baratos. No caso verificado a
   interseção era vazia — o relatório comparava um Midnight Whirlwind contra o
   preço de outro efeito.
3. **Custo de varredura.** 1.817 nomes, ~1h30 raspando página por página, com
   bloqueio por limite de taxa no meio.

Uma consulta sob demanda elimina os três. O efeito é informado pelo usuário, a
idade do preço vira informação na tela em vez de limiar escondido, e o custo cai
para **duas requisições por consulta**.

E abre acesso a um dado que a varredura nunca usou: o **livro de ofertas** da
Steam, que diz se existe comprador — a pergunta que a backpack.tf não responde.

---

## 2. O que a aplicação faz

Campo de busca → escolha do item → escolha do efeito → análise.

### Fluxo

| Passo | Ação | Requisições |
|---|---|---|
| 1 | Usuário digita parte do nome. App busca na Steam com `query=<texto>` e lista os nomes que casam. | 1 |
| 2 | Usuário escolhe um item. App abre a página de listagens e extrai tudo. | 1 |
| 3 | App mostra os **efeitos à venda agora**. Usuário escolhe um. | 0 |
| 4 | App mostra a análise. | 0 |

O índice de preços da backpack.tf é carregado uma vez na subida da aplicação e
mantido em memória.

---

## 3. Origem dos dados

Tudo da Steam vem de `window.SSR.renderContext` na página de listagens, que
contém um JSON com escape duplo. Caminho verificado em 2026-09-19:

```
renderContext.queryData -> queries[] -> por queryKey:
  ['market_item_search', ...]  -> state.data.pages[0].listings
  ['market', 'orderbook', ...] -> state.data
  ['market', 'pricehistory',…] -> state.data
```

### Por listagem
`listingid`, `strSubtotal` (preço ao comprador, já em BRL — `eCurrency: 7`),
`unFee`, e `description.descriptions[]` contendo `★ Unusual Effect: <nome>`.

### Livro de ofertas
`amtMaxBuyOrder`, `amtMinSellOrder`, `cBuyOrders`, `cSellOrders`,
`rgCompactBuyOrders`, `rgCompactSellOrders`.

### Histórico
Lista de `{time, price_median, purchases}`.

---

## 4. A regra de honestidade que governa a tela

**Nem todo dado é por efeito, e a tela tem que deixar isso explícito.** Confundir
os dois níveis foi o que invalidou o projeto anterior.

| Nível | Dados | Rótulo na tela |
|---|---|---|
| **Por efeito** | listagens filtradas pelo efeito escolhido; preço sugerido da bp.tf para aquele efeito | "para este efeito" |
| **Por item** | livro de ofertas, histórico de vendas | "todos os efeitos deste item" |

Nenhum número de um nível pode ser apresentado como se fosse do outro, nem entrar
num cálculo do outro sem rótulo.

---

## 5. Aritmética da taxa

Derivada de dados observados, não suposta. No Chairholder:
`strSubtotal = R$ 124,52`, `unFee = R$ 16,23`.

```
124,52 − 16,23 = 108,29        <- o vendedor recebe
108,29 × 0,15  =  16,24        <- confere com unFee
```

Logo, a taxa é 15% sobre o valor do vendedor, e o comprador paga a soma:

```
recebido_pelo_vendedor = preço_ao_comprador / 1,15
```

O preço exibido na página **é o total do comprador**. Não aplicar a taxa duas
vezes, e não usá-la no cálculo de desconto — só na conversão de saída.

---

## 6. Os dois vereditos

### Saída imediata (dado duro)

Vender para a melhor oferta de compra existente, agora.

```
recebido = amtMaxBuyOrder / 1,15
resultado_imediato = recebido − preço_pago
```

A ordem de compra vale para **qualquer exemplar daquele nome**, independentemente
do efeito. Portanto esse resultado é verificável e não depende de referência
externa nenhuma.

**Se `preço_pago < recebido`, é arbitragem dura:** comprar e vender na hora, com
lucro, sem troca e sem backpack.tf.

Exibir junto: `cBuyOrders`. Uma ordem é acidente; dezenas são mercado.

### Saída paciente (dado mole)

Trocar por chaves usando a backpack.tf como referência.

```
valor_justo_brl = valor_bptf_em_chaves × preço_da_chave_na_Steam_em_BRL
resultado_paciente = valor_justo_brl − preço_pago
```

Sempre acompanhado, com o mesmo destaque visual do número:

- **idade do preço** em dias
- aviso de que é **preço sugerido, não oferta de compra** — ninguém se comprometeu
  a pagar aquilo
- quando o efeito escolhido **não tem preço na bp.tf**, dizer isso e não exibir
  resultado paciente. Não substituir por outro efeito.

---

## 7. Métricas adicionais na tela

**Por efeito:** todas as listagens daquele efeito, da mais barata à mais cara, com
link direto. Quantas são.

**Por item:** menor pedido de venda, maior oferta de compra, spread entre os dois,
contagem de ordens dos dois lados, e o histórico de vendas com mediana e volume.

**Conversão:** preço em chaves, pela taxa da chave na própria Steam.

---

## 8. Arquitetura

Reaproveitado sem alteração:
- `tf2price/domain/money.py` — `Brl`
- `tf2price/domain/effects.py` — mapa de 569 efeitos
- `tf2price/sources/backpacktf.py` — índice de preços
- `tf2price/sources/ratelimit.py` — espaçamento e backoff
- `tf2price/sources/steam.py` — busca e `priceoverview`

Novo:

```
tf2price/
  sources/
    steam_page.py     # extrai renderContext: listagens+efeitos, orderbook, histórico
  lookup/
    analysis.py       # puro: dado o extraído + bp.tf, produz a análise
    app.py            # FastAPI: rotas
    templates/        # HTMX
```

`analysis.py` é puro e testável sem rede, como `domain/`. `steam_page.py` é I/O e
parsing, testado contra HTML gravado em fixture.

**Stack:** FastAPI + HTMX, execução local. Sem banco.

---

## 9. Fora de escopo

- Varredura de catálogo, worker contínuo, alertas.
- Banco de dados e histórico próprio.
- Deploy hospedado. O desenho não impede, mas não é feito agora.
- Compra automática.
- Itens que não sejam Unusual.
- Spells e killstreaker.

---

## 10. Riscos

| Risco | Tratamento |
|---|---|
| A Valve muda a estrutura do `renderContext` | Extrator isolado em um módulo; falha com mensagem clara nomeando o caminho esperado, nunca com `KeyError` cru |
| Limite de taxa | Duas requisições por consulta; o limitador existente já cobre |
| O efeito escolhido não tem preço na bp.tf | Previsto em §6: dizer, e omitir o resultado paciente |
| Nome de efeito da Steam não casa com o mapa | Registrar e exibir o efeito como texto, sem resultado paciente |

---

## 11. Verificação pendente herdada

`sell_price` da busca vem em **USD** e o texto em `$`. A busca aqui é usada só
para listar nomes, não preços, então o bug não se aplica — mas se algum preço
passar a vir da busca, a blindagem do §3 do findings tem que ser feita antes.
