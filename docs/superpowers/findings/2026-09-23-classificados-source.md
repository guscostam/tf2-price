# Fonte de vendas dos classificados da backpack.tf

**Observação:** 23 de setembro de 2026. **Item alvo:** `Team Captain`; efeito a isolar: `Burning Flames`.

## Contrato público

O [Developer Centre](https://next.backpack.tf/developer) informa que as APIs v1 de listagens foram descontinuadas e têm limite de requisições mais restrito. Também informa que respostas HTTP 429 têm cabeçalho `Retry-After`, mas não publica ali um orçamento numérico de leitura de anúncios de outros vendedores.

No [OpenAPI público](https://api.backpack.tf/api/swagger.json), `GET /v2/classifieds/listings` é descrito como índice paginável das listagens **da conta autenticada** (`Get account listings`). O `GET /classifieds/listings/v1` é descrito como listagens do usuário da sessão, está marcado como obsoleto e como fortemente limitado. Nenhum dos dois comprova acesso ao conjunto de vendedores do mercado. O OpenAPI consultado também não documenta `GET /classifieds/listings/snapshot` nem seus parâmetros, campos de resposta, paginação ou limite de leitura. O limite de 10 requisições por minuto que ele informa para operações em lote refere-se à **criação/remoção** de listagens da conta; não é um limite de consulta de vendedores.

## Sondagem disponível

Não havia `BPTF_USER_TOKEN` no ambiente local consultado nem no `.env` da instalação original; o worktree não possui `.env`. Assim, a sondagem autenticada e limitada prevista no plano não pôde ser executada. Uma única requisição GET **anônima**, já realizada em 23 de setembro de 2026, tentou `GET /api/classifieds/listings/snapshot` com `appid=440` e SKU `Unusual Team Captain`, sem token, e retornou **HTTP 401** com indicação de token inválido. Não houve novas tentativas anônimas. O corpo não continha listagens utilizáveis; nenhum nome de campo de anúncio foi observado. A resposta de limite (HTTP 429 ou `Retry-After`) não foi observada.

Para declarar a fonte viável, uma resposta autorizada teria de permitir selecionar somente anúncios ativos de **venda** do item `Team Captain` com qualidade Unusual e efeito `Burning Flames`, identificar a moeda e o valor pedido e demonstrar que a paginação cobre todos os vendedores comparáveis. Os nomes concretos desses campos no endpoint de mercado seguem **desconhecidos**; não se deve deduzi-los do modelo de listagens da própria conta. Também são desconhecidos o limite aplicável à leitura do mercado e se é possível obter o menor preço de venda completo dentro dele. O HTTP 401 não prova ausência de anúncios nem impossibilidade permanente de acesso com uma credencial válida.

## Decisão em 23 de setembro

**Indisponível para cotação automática neste momento.** Não é possível isolar automaticamente as vendas de `Burning Flames` nem afirmar um menor anúncio, pois não se obteve uma resposta autorizada de vendedores do mercado. A interface deve conservar a comparação com o preço sugerido e o link para conferência manual, sem apresentá-los como revenda executável. Um coletor e o cálculo de `Potential resale` exigem outra avaliação após existir acesso autorizado a uma fonte de mercado: verificar os campos reais de identidade, intenção, atividade e moeda, a cobertura/paginação e o limite de leitura observado, sem expor credenciais ou dados de vendedores.

## Sondagem autenticada posterior — 24 de setembro de 2026

O dono configurou `BPTF_USER_TOKEN` localmente e na Railway. Sem imprimir o token ou dados de usuários, uma requisição autenticada a `GET /api/classifieds/listings/snapshot` com `appid=440` e `sku=Massed Flies Team Captain` retornou HTTP 200, `sku` correspondente e 14 listagens: uma `sell` e 13 `buy`. A listagem de venda continha `currencies.keys`, `item.quality=5`, `item.defindex=378` e um atributo de efeito `defindex=134`, `float_value=12` (Massed Flies). O objeto da resposta trouxe `createdAt` contemporâneo à consulta. A consulta genérica `Unusual Team Captain` retornou oito compras e nenhuma venda; por isso o coletor deve consultar o nome específico **efeito + item** e nunca interpretar a consulta genérica como ausência de vendedores daquele efeito. `Burning Flames Team Captain` retornou seis compras e nenhuma venda; a variante `Unusual Team Captain Burning Flames` retornou lista vazia.

O endpoint não apresentou campo de paginação na resposta observada. Não houve HTTP 429 nem `Retry-After` nas sondagens. O orçamento de leitura segue sem contrato público; o coletor deve usar espaçamento conservador, respeitar 429 e manter a idade real do último sucesso. O campo `item.attributes` pode trazer atributos adicionais do exemplar; a implementação precisa recusar variantes cuja comparabilidade com o item Steam nominal não possa ser sustentada. Esta sondagem torna viável implementar o sinal de menor venda **observada no snapshot**, com estados separados para ausência, falha e dado antigo; não demonstra liquidez ou garantia de revenda.
