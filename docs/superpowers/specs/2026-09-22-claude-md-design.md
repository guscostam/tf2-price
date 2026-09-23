# CLAUDE.md

**Data:** 2026-09-22

**Status:** implementado

## Objetivo

Dar ao Claude Code as mesmas regras que o `AGENTS.md` já dá aos outros agentes,
sem manter duas cópias, e acrescentar o que hoje só vive na memória local do
Claude: a prioridade do produto e o significado das linhas do log de produção.

O Claude Code lê `CLAUDE.md`, não `AGENTS.md`. Por isso o `CLAUDE.md` importa o
`AGENTS.md` inteiro com `@AGENTS.md`, e qualquer defasagem do `AGENTS.md` passa a
orientar o Claude também. As defasagens encontradas são corrigidas no mesmo
trabalho.

## Parte 1: `CLAUDE.md` na raiz

Em português, com três partes, nesta ordem:

1. A linha `@AGENTS.md`, sozinha, logo abaixo do título. É a fonte de verdade das
   regras; o `CLAUDE.md` não repete nada dela.
2. **Prioridade do produto.**
   - O produto é a tela de consulta de um Unusual: decidir uma compra em
     segundos (quanto vale na troca, quanto alguém paga agora, há quanto tempo o
     preço de referência não é atualizado).
   - A varredura (`tf2price/varredura/`) complementa a consulta. Sai do mesmo IP,
     então nunca pode causar 429 para ela: gasta o mínimo de requisições, espera
     a calma ligada por outros, cede a vez e pausa ao primeiro 429.
   - Proposta de varredura, worker, alerta ou ranking do mercado inteiro precisa
     ser justificada, não presumida. O caminho padrão é melhorar a consulta e a
     honestidade dos números que ela mostra.
3. **Sinais no log de produção (Railway).** Uma tabela com prefixo, quando
   aparece e o que significa:

   | Prefixo | Quando aparece | O que significa |
   |---|---|---|
   | `[partida]` | subida com o banco sem usuário | link de convite de administrador, válido por 24 h |
   | `[superadmin]` | subida | `SUPERADMIN` ausente ou não é admin ativo: ninguém promove nem rebaixa. Esperado só na primeira subida |
   | `[aquecimento]` | subida | carga de cotação, índice e PTAX, com o tempo gasto. "ok em ~2s" e página ainda lenta: a causa é a partida do contêiner, não a carga |
   | `[renovo]` | ciclo de fundo | a renovação da cotação ou da PTAX falhou; a tela segue com o dado velho e a idade à vista |
   | `[sob-demanda]` | falha de busca | origem, erro e espera até a nova tentativa. `PtaxSobDemanda` é o que procurar quando a tela diz que a PTAX não carregou |
   | `[ptax]` | ciclo de fundo | PTAX nova guardada no banco |
   | `[retrato]` | consulta ou varredura | a Steam limitou (429) a página do item; calma de 5 min |
   | `[varredura]` | fundo | 429 com pausa, resumo da rodada, rodada interrompida por reinício, erro do agendador |

Variáveis de ambiente não entram: `.env.example` e README já as cobrem.

## Parte 2: correções pontuais no `AGENTS.md`

1. **Mapa do repositório:** acrescentar `tf2price/efeitos/` (coleta dos efeitos
   e geração das artes WebP).
2. **`tf2price/sources/`:** clientes da Steam, backpack.tf **e Banco Central
   (PTAX)**.
3. **`scripts/`:** citar `scripts/fetch_effects.py` e
   `scripts/fetch_cosmeticos.py`.
4. **Chave de referência:**
   - `tf2price/preco/` passa a mencionar a chave de referência
     (`preco/referencia.py`).
   - Novo item em "Invariantes obrigatórios": toda conta de troca usa a chave de
     referência, o dólar da chave na backpack.tf vezes a PTAX de venda do Banco
     Central. O preço da chave na Steam só converte as listagens que a Steam
     devolve em dólar.
   - A regra de renovação só pelo trabalho de fundo, hoje escrita para
     `CotacaoSobDemanda`, passa a valer também para `PtaxSobDemanda`: `obter`
     lê apenas memória e banco, `renovar` vai à rede e só o fundo a chama.

O resto do `AGENTS.md` não muda.

## Fora de escopo

- Reescrever ou reorganizar o `AGENTS.md`.
- Fluxo de spec e plano, estilo de commit e idioma no `CLAUDE.md` (considerados
  e descartados pelo dono).
- Qualquer mudança de código, configuração ou teste.

## Verificação

- Cada prefixo de log e cada caminho citado confere com `grep` no código.
- `git diff --check` sem problemas.
- A suíte completa passa, como pede o checklist do `AGENTS.md`, mesmo sem mudança
  de código.
