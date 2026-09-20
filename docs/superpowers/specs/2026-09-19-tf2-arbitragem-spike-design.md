# Spike de validação — arbitragem TF2 Steam Market × backpack.tf

**Data:** 2026-09-19
**Status:** spec aprovado, pronto para plano de implementação
**Tipo:** spike de decisão, descartável por contrato

---

## 1. Por que este spike existe

O projeto completo (worker 24/7 na Railway, dashboard, alertas) depende de uma
premissa não verificada: **existem oportunidades reais em volume suficiente para
o app valer a pena.**

Ninguém sabe se o mercado tem três oportunidades por dia ou três por mês. Sem esse
número, construir o sistema completo é apostar semanas de trabalho numa intuição.

Este spike mede o mercado uma vez e responde com dados. Ele roda numa tarde,
localmente, sem banco, sem deploy e sem interface.

O spike **não é trabalho descartado**: os módulos `sources/` e `domain/` que ele
produz são os mesmos do projeto completo. O que é descartável é o script que os
amarra e o formato do relatório.

---

## 2. Perguntas que o spike responde

### Perguntas de mercado

1. **Quantas oportunidades existem agora**, nas faixas de ≥15%, ≥25% e ≥40% de desconto?
2. **De que tamanho**, em reais — valor absoluto do desconto por oportunidade?
3. **Quantas sobrevivem às guardas anti-falso-positivo?** Este é o número que importa.
   O bruto vai ser inflado; o líquido é o que decide o projeto.

### Verificações técnicas

4. **Preços derivados da Steam Market existem no índice da bp.tf e dá para detectá-los?**
   Maior incógnita técnica remanescente. Ver §6.
5. **Item de TF2 comprado na Market entra em trade hold?** Se entrar, por quantos dias?
   Afeta o tempo até realizar o valor em chaves.
6. **Qual o rate limit real da Steam** observado do IP de origem, em requisições por
   minuto antes do primeiro 429?

---

## 3. Contexto herdado do design

Decisões já fechadas na sessão de brainstorming, que o spike assume sem rediscutir:

- **Direção da oportunidade:** comprar barato na Steam Market, item valendo mais em chaves.
- **Câmbio:** preço da *Mann Co. Supply Crate Key* na própria Steam Market em BRL
  (`currency=7`). Cancela o prêmio de saldo travado dos dois lados da comparação.
- **Conservadorismo:** usar o piso da faixa da bp.tf (`value`, nunca `value_high`), e o
  preço total pago pelo comprador (preço + taxa). Errar para menos, não para mais.
- **Princípio da poda:** o `market_hash_name` é tudo que a passada rasa conhece. Avalie
  cada nome no cenário mais favorável dentro das incógnitas; se nem assim é pechincha,
  descarte o nome.

---

## 4. Escopo

### Dentro

- Passada rasa completa no mercado de TF2 (~200 requisições paginadas).
- Índice completo da bp.tf via `IGetPrices/v4` (1 requisição).
- Câmbio via preço da chave na Steam.
- Parsing de identidade e casamento com o índice da bp.tf.
- Avaliação completa dos itens **não-Unusual** — resolvidos só com a passada rasa.
- Contagem de **candidatos Unusual** pela regra de limite superior.
- Fetch profundo nos **20 melhores candidatos Unusual**, ordenados pelo desconto no
  cenário mais favorável, para confirmar se a oportunidade em Unusual é real ou
  artefato do parsing. Custa 20 requisições e é o dado de maior valor do spike.
- Relatório em Markdown + CSV das oportunidades encontradas.

### Fora

Nada abaixo é construído neste spike:

- Banco de dados, persistência, histórico.
- Worker contínuo, ciclos, cursor de retomada.
- Dashboard, interface web, FastAPI.
- Alertas, Discord, Telegram.
- Deploy na Railway.
- Fetch profundo em todos os nomes Unusual.
- Tratamento de spells e sheen/killstreaker.

Ignorar spells e sheen é seguro nesta fase: os dois só **aumentam** o valor do item.
Ignorá-los subestima o valor justo, o que produz oportunidades perdidas, nunca falsos
positivos. Erra na direção certa.

---

## 5. Arquitetura

Estrutura idêntica à do projeto completo, preenchida parcialmente. `domain/` é puro,
sem I/O, testável sem rede.

```
tf2price/
  sources/
    steam.py          # cliente HTTP Steam: busca paginada, listagens, rate limit, backoff
    backpacktf.py     # cliente bp.tf: IGetPrices/v4, IGetCurrencies/v1
  domain/
    money.py          # BRL, chaves, refined; conversões
    identity.py       # parse de market_hash_name -> item base + qualidade + modificadores
    valuation.py      # valor justo, desconto, guardas
    prefilter.py      # regra das três vias
  spike/
    run.py            # orquestra a passada única
    report.py         # gera Markdown + CSV
```

### Fluxo

```
1. bp.tf IGetCurrencies/v1    -> chave em refined e USD
2. bp.tf IGetPrices/v4        -> índice completo (~40 MB), em memória
3. Steam: preço da chave BRL  -> key_brl (o câmbio)
4. Steam: busca paginada      -> {hash_name, preço mínimo, nº de listagens}
5. Para cada nome: parse de identidade -> casa com o índice
6. Poda das três vias         -> garantida / candidata / descartada
7. Não-Unusual garantidos     -> avalia e registra
8. Top 20 candidatos Unusual  -> fetch profundo, resolve efeito e craftabilidade
9. Aplica guardas             -> bruto vs líquido
10. Relatório
```

### Regra das três vias

Para cada `hash_name`, enumerar as interpretações possíveis (todos os efeitos ×
craftável/não-craftável) e obter a faixa de valor justo:

| Condição | Classificação |
|---|---|
| `preço < valor_mínimo × (1 − limiar)` | **garantida** — vale mesmo no pior cenário |
| `preço < valor_máximo × (1 − limiar)` | **candidata** — depende de resolver as incógnitas |
| caso contrário | **descartada** |

### Cálculo

```
valor_justo_brl = valor_bptf_em_chaves × key_brl
desconto        = 1 − preço_total_steam / valor_justo_brl
lucro_revenda   = valor_justo_brl × 0,85 − preço_total_steam
```

A taxa de 15% da Steam sai do vendedor. Ela aparece só em `lucro_revenda`, nunca
no cálculo de desconto.

---

## 6. Guardas anti-falso-positivo

O spike reporta **bruto e líquido** separadamente. A diferença entre os dois é, por
si só, um resultado: mostra quanto do sinal aparente é lixo.

| # | Guarda | Motivo |
|---|---|---|
| 1 | Incógnitas não resolvidas | Ver abaixo. |
| 2 | `last_update` da bp.tf > 30 dias | Preço fantasma. Segunda maior fonte de lixo. |
| 3 | `value_high` mais de 25% acima de `value` | Preço mal estabelecido, comparação sem significado. |
| 4 | **Preço derivado da Steam Market** | Ver abaixo. |

### Guarda 1 — só se aplica a candidatas

Item *Não utilizável em criação* tem `market_hash_name` idêntico ao normal e vale uma
fração. É a maior fonte de falso positivo do projeto.

Mas a guarda **não se aplica a tudo**. A classificação das três vias já resolve o caso:

- **Garantida** — a via 1 provou que o item vale mesmo no pior cenário, ou seja, mesmo
  sendo não-craftável e com o pior efeito. Não precisa de guarda, e **entra no líquido
  sem fetch profundo**. É isto que permite avaliar os não-Unusual só com a passada rasa.
- **Candidata sem fetch profundo** — craftabilidade e efeito seguem incógnitos.
  **Excluída do líquido**, e contada à parte no relatório.
- **Candidata com fetch profundo** — incógnitas resolvidas. Entra ou sai pelo valor real.

O relatório separa as três. A contagem de candidatas excluídas por falta de fetch é o
que dimensiona o orçamento de requisições do projeto completo.

### Guarda 4 — o achado da pesquisa

A backpack.tf mantém em `/market` uma lista de preços da Steam Community Market, e
documenta que ela é usada *"para precificar itens não cobertos por sugestões de preço"*.

Consequência: para parte do catálogo, **o preço da bp.tf é derivado do preço da Steam**.
Comparar os dois nesses itens é circular. E como a bp.tf desconta os 15% de taxa ao
derivar, esses itens aparecem **sistematicamente com ~15% de desconto** — um andar
inteiro de falsos positivos, todos com a mesma cara de oportunidade.

**Hipótese de detecção**, a confirmar contra dados reais: itens cujo preço no
`IGetPrices` vem em `usd` em vez de `keys`/`metal` são suspeitos de origem Market.

**Teste:** isolar os itens precificados em `usd` e verificar se o desconto deles se
agrupa perto de 15%. Se agrupar, a hipótese está confirmada e a guarda é essa.
Se não agrupar, o spike reporta hipótese refutada e a detecção fica em aberto — com
a recomendação de cruzar contra a própria lista `/market` como alternativa.

---

## 7. Verificações técnicas a registrar

Não são suposições do design; são coisas a confirmar e anotar durante o spike.

| # | O que verificar | Por que importa |
|---|---|---|
| 1 | Parâmetros e limite real de paginação de `/market/search/render` | Define o custo da passada rasa |
| 2 | `currency=7` devolve BRL de fato | Todo o cálculo depende disso |
| 3 | Requisições por minuto até o primeiro 429 | Dimensiona o ciclo do projeto completo |
| 4 | Formato e tamanho real do `IGetPrices/v4` | Decide se cabe em memória ou precisa streaming |
| 5 | `★ Unusual Effect:` e *Não utilizável em criação* aparecem nas `descriptions` | Viabiliza resolver as incógnitas |
| 6 | Mapa de `priceindex` (bp.tf) → nome do efeito (Steam) | Sem ele, Unusual não casa |
| 7 | Trade hold em item comprado na Market | Afeta o tempo até realizar o lucro |
| 8 | `sell_price` da busca é o total pago pelo comprador, já com a taxa | Alimenta a maioria das oportunidades líquidas; se for o líquido do vendedor, todo desconto infla ~15% |

---

## 8. Critério de decisão

O spike termina com um veredito explícito, medido **sobre as oportunidades líquidas**
(pós-guardas), num snapshot único:

| Resultado | Veredito |
|---|---|
| ≥ 10 oportunidades ≥ 20% de desconto, valor médio ≥ R$ 50 | **Verde.** Construir o projeto completo como desenhado. |
| 3 a 9 oportunidades, ou valores baixos | **Amarelo.** Construir versão reduzida: worker + alerta no Discord, sem dashboard. |
| < 3 oportunidades | **Vermelho.** Não construir. O mercado não sustenta o app. |

Se o resultado cair em Amarelo ou Vermelho, o relatório deve indicar **onde** o sinal
morreu — mercado genuinamente seco, ou guarda específica comendo tudo. As duas coisas
levam a decisões diferentes.

---

## 9. Testes

O spike é descartável, mas `domain/` não é — ele vai para o projeto completo. Então:

- **`domain/identity.py`**: ~50 `market_hash_name` reais contra o parse esperado.
  Cobrir qualidades, tiers de killstreak, Australium, Festivized, desgaste de war paint.
- **`domain/valuation.py`**: conversões e cálculo de desconto.
- **`domain/prefilter.py`**: o teste de propriedade — *a poda nunca descarta uma
  pechincha*. Gera listagens sintéticas, roda a regra das três vias, afirma que toda
  listagem que é negócio caiu em "garantida" ou "candidata". É a única parte do sistema
  onde um bug é silencioso: todo o resto falha fazendo barulho, esse falharia fazendo
  você perder dinheiro sem nunca aparecer na tela.
- **`sources/`**: fixtures de JSON real gravado uma vez. Sem rede nos testes.

---

## 10. Riscos

| Risco | Mitigação |
|---|---|
| Rate limit trava a passada rasa | Backoff exponencial com jitter; a passada rasa é curta o bastante para tolerar pausas |
| Parser casa uma fração pequena dos nomes | Registrar nomes não casados com contador e reportar; taxa de casamento é resultado do spike |
| `IGetPrices` grande demais para a memória | Verificação #4; se necessário, parse em streaming |
| Hipótese da guarda 4 refutada | Previsto em §6; spike reporta e recomenda alternativa |

---

## 11. Decisões deliberadamente adiadas

- Canal do alerta (Discord webhook vs bot de Telegram).
- Modelo de dados do projeto completo.
- Estratégia de fetch profundo em escala para Unusuals.
- Fila adaptativa (opção C da sessão de brainstorming).

---

## 12. Pré-requisito

API key da backpack.tf, grátis, em `backpack.tf/developer/apikey/new` (login via Steam).
É ela que libera o `IGetPrices/v4`. Sem ela o spike não roda.
