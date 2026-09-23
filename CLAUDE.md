# CLAUDE.md

@AGENTS.md

## Prioridade do produto

O produto é a tela de consulta de um Unusual: decidir uma compra em segundos —
quanto vale na troca, quanto alguém paga agora, e há quanto tempo o preço de
referência não é atualizado.

A varredura (`tf2price/varredura/`) complementa a consulta, não a substitui. Ela
sai do mesmo IP, então nunca pode causar 429 para a consulta: gasta o mínimo de
requisições, espera a calma ligada por outros, cede a vez e pausa ao primeiro
429.

Proposta de varredura, worker, alerta ou ranking do mercado inteiro precisa ser
justificada, não presumida. O caminho padrão é melhorar a consulta e a
honestidade dos números que ela mostra.

## Sinais no log de produção (Railway)

As linhas que o painel imprime começam por um prefixo entre colchetes. Ao
investigar um problema em produção, procure primeiro por elas.

| Prefixo | Quando aparece | O que significa |
|---|---|---|
| `[partida]` | subida com o banco sem usuário | link de convite de administrador, válido por 24 h |
| `[superadmin]` | subida | `SUPERADMIN` ausente ou não é admin ativo: ninguém promove nem rebaixa. Esperado só na primeira subida, antes de a conta existir |
| `[aquecimento]` | subida | carga de cotação, índice e PTAX, com o tempo gasto. Se diz "ok em ~2s" e a página ainda demora, a causa é a partida do contêiner, não a carga |
| `[renovo]` | ciclo de fundo | a renovação da cotação ou da PTAX falhou; a tela segue com o dado velho e a idade à vista |
| `[sob-demanda]` | falha de busca | origem, erro e espera até a nova tentativa. `PtaxSobDemanda` é o que procurar quando a tela diz que a PTAX não carregou |
| `[ptax]` | ciclo de fundo | PTAX nova guardada no banco |
| `[retrato]` | consulta ou varredura | a Steam limitou (429) a página do item; calma de 5 min |
| `[varredura]` | fundo | 429 com pausa, resumo da rodada, rodada interrompida por reinício, erro do agendador |
