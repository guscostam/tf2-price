# Market Scan com anúncios de venda por efeito — design

**Data:** 2026-09-23

**Status:** design aprovado; implementação pendente

## Problema e objetivo

O Market Scan atual chama de `Profitable` a diferença positiva entre uma
listagem Steam e o preço sugerido pela backpack.tf para o mesmo item e efeito.
Esse preço sugerido pode divergir muito do que os donos do unusual estão
pedindo hoje: a oferta do efeito, a procura e a raridade mudam sem que o índice
seja atualizado. O filtro atual de 90 dias evita muitos preços antigos, mas não
transforma uma sugestão em anúncio de mercado.

O objetivo é comparar cada listagem Steam com o **menor anúncio ativo de venda**
na backpack.tf para o mesmo par item–efeito. Uma diferença positiva será
`potencial de revenda`, nunca lucro confirmado: anúncio de venda não prova que
existe comprador naquele preço. O preço sugerido permanece visível, separado e
com sua idade real, para contexto.

## Alternativas consideradas

1. Consultar vendas por item–efeito e usar o menor anúncio comparável. É a
   opção escolhida: observa diretamente o preço pedido hoje, sem tentar
   atribuir um prêmio subjetivo a efeitos raros ou bonitos.
2. Usar o preço sugerido para selecionar candidatos e consultar apenas suas
   vendas. Economiza requisições, mas perde oportunidades em que o anúncio de
   venda está acima do índice sugerido — justamente o caso relatado.
3. Estimar um multiplicador por raridade ou popularidade. Abrange mais pares,
   mas não tem validação suficiente para sustentar uma decisão de compra.

## Contratos dos dados e cálculo

- A chave de cache e comparação é `(hash_name, efeito)` com identidade
  normalizada pelas regras existentes em `domain/`. Nunca usar anúncio de outro
  efeito, de outra qualidade ou de ferramenta que apenas aplica um efeito.
- A cotação de venda precisa identificar o item, o efeito, o lado `sell`, o
  preço em chaves e/ou metal, e que a oferta está ativa. Ignorar ofertas cuja
  identidade ou moeda não possa ser interpretada com segurança. Quando a fonte
  informar variantes relevantes como `craftable`, usar apenas as comparáveis
  com o item ordinário esperado pela varredura.
- O parser atual de listagens Steam expõe `listing_id`, preço, efeito e ícone;
  não expõe todos os atributos do exemplar, como craftability. A comparação é
  nominal por item–efeito, e a interface deve orientar a conferência do anúncio
  concreto antes da compra. Ela não pode afirmar equivalência de atributos que
  a Steam não informou.
- Entre anúncios de venda comparáveis, usar o menor preço, sem média e sem
  misturar o preço sugerido. Converter chaves e metal pela cotação de referência
  já usada no projeto: dólar da chave na backpack.tf × PTAX de venda; metal é
  convertido com a relação metal/chave da backpack.tf. O preço Steam já está em
  `Brl`. Toda quantia monetária calculada termina em `Brl`/centavos, sem `float`
  como representação de dinheiro.
- `potencial = valor_do_menor_anúncio_de_venda − preço_da_listagem_Steam`.
  Exemplo: Steam equivalente a 80 chaves e menor venda a 100 chaves dá
  +20 chaves de diferença potencial. Uma oferta de compra a 60 chaves não
  muda esse cálculo nem o transforma em lucro executável.
- A melhor compra do mesmo par pode ser mostrada como contexto de liquidez se
  vier na mesma resposta e for verificável, mas não entra no cálculo nem
  justifica requisição adicional nesta etapa.

## Coleta e persistência

O scanner Steam continua descobrindo as listagens como hoje. Um coletor de
vendas da backpack.tf roda em segundo plano, desacoplado da rota `/scan` e da
renovação de PTAX. Ele deduplica os pares item–efeito das listagens armazenadas
e compartilha uma leitura entre todas as listagens Steam do mesmo par. O estado
persistido por par distingue `encontrado` e `sem_vendas_confirmado`, guarda o
instante da última leitura bem-sucedida e registra separadamente a última
falha como `indisponível`. Uma falha de rede não regrava o instante da leitura
nem converte falha em ausência de vendedores.

As chamadas são espaçadas e respeitam `Retry-After`, backoff e período de calma
após 429; o coletor para ou adia quando a fonte limita requisições. Uma
conexão de banco é devolvida ao pool antes de qualquer HTTP ou espera. O
trabalho de fundo prioriza pares com listagem Steam recente e cotação de venda
ausente ou vencida, sem multiplicar chamadas pelo número de usuários ou de
listagens. A rota lê somente memória e banco.

Uma leitura de venda e a listagem Steam precisam ter **até 6 horas** de idade
para entrar na aba de oportunidades. Valores mais velhos continuam visíveis
com sua idade original, mas não participam do resultado potencial nem da
ordenação por oportunidade. O limite evita apresentar anúncios possivelmente
removidos como oportunidades atuais; ainda assim, o usuário deve verificar
ambos os anúncios antes de negociar.

## Verificação da fonte antes da implementação do coletor

A [documentação pública da backpack.tf](https://next.backpack.tf/developer)
informa que as APIs v1 de listagens são depreciadas e limitadas. A
[OpenAPI pública](https://api.backpack.tf/api/swagger.json) não documenta uma
busca v2 de todas as vendas de um item. A primeira tarefa do plano de
implementação é uma prova pequena e sem persistência de produção, com alguns
pares item–efeito conhecidos,
para confirmar que uma fonte autorizada entrega anúncios ativos, identidade
exata, preço e limites de requisição que o processo consegue respeitar.
Registrar respostas saneadas e quantidades, nunca credenciais ou tokens.

Se nenhuma fonte de leitura automática satisfizer esse contrato, não fazer
scraping ou inferir um preço a partir do índice sugerido. Nesse caso, a mudança
da interface ainda corrige o sinal enganoso: o índice passa a ser rotulado
`preço sugerido`, a aba `Profitable` deixa de prometer lucro e cada par oferece
link para a conferência manual das vendas na backpack.tf. O estado de mercado
fica `indisponível`, sem resultado potencial automático. A falta de acesso à
fonte deve ser documentada antes de qualquer extensão do coletor.

## Interface e estados

- Trocar `Profitable` por `Potential resale` na interface em inglês. A aba só
  inclui diferenças positivas calculadas com duas leituras de até 6 horas.
- Mostrar, em colunas distintas, o preço Steam, o menor anúncio de venda da
  backpack.tf, a diferença potencial e o preço sugerido da backpack.tf. Mostrar
  a idade da listagem Steam, da leitura das vendas e do preço sugerido.
- `No matching sellers` significa resposta bem-sucedida sem anúncio de venda
  comparável. `Unavailable` significa falha ou fonte inacessível. `Stale`
  significa que há dado anterior, com idade preservada, mas insuficiente para
  classificar oportunidade. Nenhum desses estados vira zero ou herda valor de
  outro efeito.
- Os filtros e a ordenação de diferença/percentual usam a referência de venda
  ativa. O filtro de idade do preço sugerido continua disponível apenas para
  essa coluna de contexto e não altera a avaliação de venda. Filtros de preço
  Steam, texto e efeito preservam o comportamento atual. Links para a Steam,
  para a consulta do par e para as vendas na backpack.tf tornam a conferência
  manual possível.
- O texto da página explica que preço pedido não é venda concluída. A aba de
  oportunidades é um sinal de diferença entre mercados, sujeito à retirada de
  anúncios, negociação e atributos não informados pela Steam.

## Responsabilidades e testes

O cliente da fonte e o parser de anúncios ficam em `sources/`; o repositório
SQL e o agendamento em `varredura/`; a regra pura de seleção do menor anúncio,
conversão e cálculo em `varredura/leitura.py` ou módulo pequeno adjacente; a
rota e os templates só compõem e apresentam dados. Não mudar `patient_exit` da
consulta pontual sem um design próprio: ela ainda responde à pergunta sobre o
índice sugerido.

Testes determinísticos cobrem: efeito, nome e qualidade exatos; exclusão de
compras e anúncios incomparáveis; mínimo entre múltiplos vendedores; chaves e
metal; ausência confirmada versus falha; preservação da idade após falha;
ambas as leituras vencidas; 429 e backoff sem conexão emprestada; deduplicação
por par; classificação e ordenação da aba; rota sem HTTP. Nenhum teste ou
import usa rede. O teste focado e a suíte completa passam antes da conclusão.

## Fora do escopo

Não há estimativa automática de raridade, gosto ou quantidade de exemplares
existentes; nenhuma garantia de comprador, lucro realizado ou execução da
troca; nenhuma ampliação da varredura para outras qualidades ou categorias;
nenhuma busca remota durante a renderização da rota.
