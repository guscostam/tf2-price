# Market Scan com vendas ativas — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calcular potencial de revenda a partir do menor anúncio ativo de venda do mesmo cosmético Unusual e efeito no snapshot da backpack.tf.

**Architecture:** Um cliente autenticado lê o snapshot por `efeito + nome base` e extrai apenas vendas comparáveis. Um coletor lento em segundo plano persiste o menor preço por par; `/scan` lê o banco e calcula a diferença usando a chave de referência já existente. O índice de preços sugeridos continua como contexto separado.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy Core, FastAPI/Jinja, pytest.

## Global Constraints

- A identidade econômica é `(hash_name, efeito)`; qualidade 5 e atributo de efeito 134 precisam corresponder à requisição. Compras nunca entram no mínimo.
- Uma resposta bem-sucedida sem venda comparável é diferente de HTTP/parse/limite indisponível. Falha não altera preço nem instante do último sucesso.
- Persistir `createdAt` do snapshot como idade da fonte; buscar novamente o mesmo snapshot não renova sua idade.
- Só listagem Steam e leitura de vendas com até seis horas participam de `Potential resale`. Dado antigo permanece visível com idade real.
- `Potential resale` é preço pedido menos preço Steam, sem promessa de comprador, e usa a chave de referência backpack.tf USD × PTAX.
- Sem rede em imports, testes ou rota `/scan`; nenhuma conexão emprestada durante HTTP, espera ou backoff.
- Snapshot não tem contrato público de paginação ou limite; rotular como menor venda **observada** e espaçar conservadoramente as consultas. Respeitar 429/`Retry-After`.
- Nunca imprimir ou versionar credenciais, dados de vendedores, `.env` ou URL de banco.
- Usar o worktree `C:\Users\gusco\.codex\worktrees\market-scan-vendas\tf2-price`; a `.venv` da instalação original executa pytest.

## Arquivos e responsabilidades

- `tf2price/sources/classificados.py`, `tests/sources/test_classificados.py`: cliente e parser puro do snapshot.
- `tf2price/db.py`, `tf2price/varredura/vendas_repo.py`, `tests/varredura/test_vendas_repo.py`: tabela nova e leitura/escrita SQL por par.
- `tf2price/varredura/vendas_coletor.py`, `tests/varredura/test_vendas_coletor.py`: seleção, agendamento, rate limit e falha degradada.
- `tf2price/varredura/leitura.py`, `tests/varredura/test_leitura.py`: regra pura de potencial, filtro e ordenação.
- `tf2price/painel/app.py`, `tf2price/painel/varredura.py`, templates do scan, `tests/painel/test_scan.py`: inicialização e apresentação.
- `.env.example`, `README.md`, achado acima: configuração e significado do resultado.

### Task 1: Cliente e parser do snapshot

**Interfaces:** `snapshot_para_vendas(payload, sku: str, effect_id: int) -> tuple[Venda, ...]`, `Venda(chaves: Decimal, metal: Decimal)`, `ClassificadosClient(token).vendas(sku, effect_id) -> tuple[Venda, ...]`. Exceção específica para 429 com `retry_after_s`; demais erros não são ausência.

- [ ] Escrever testes com JSON pequeno: `sell` correto, `buy` ignorado, efeito diferente, qualidade diferente, moeda desconhecida, atributo especial incomparável, zero vendas confirmado, SKU divergente e resposta incompleta recusados. MockTransport prova `X-Auth-Token`, timeout e 429 sem revelar token.
- [ ] Rodar `C:\Users\gusco\Desktop\tf2-price\.venv\Scripts\python.exe -m pytest tests\sources\test_classificados.py` e verificar falha pela implementação ausente.
- [ ] Implementar cliente com request `GET https://backpack.tf/api/classifieds/listings/snapshot?appid=440&sku=<efeito nome>`; converter quantidades via `Decimal(str(x))`; usar somente `currencies.keys`/`metal`, jamais `price` float, nem listagem `buy`.
- [ ] Rodar o teste focado até passar; revisar diff; commit.

### Task 2: Cache por par e coletor de fundo

**Interfaces:** tabela nova `venda_efeito` com chave composta, quantidades decimais serializadas como texto, estado, `buscado_em`, `falhou_em`; `vendas_repo.ler_todas(conn)` e `gravar_sucesso`/`gravar_falha`; `VendasColetor.ciclo(parar)` com relógio e espera injetáveis.

- [ ] Escrever testes de repositório: dois efeitos isolados, ausência confirmada, idade preservada após falha, upsert em SQLite e validação dos campos antes da escrita.
- [ ] Escrever testes de coletor: selecionar par com listagem Steam recente, deduplicar por par, não repetir enquanto cache fresco, não manter conexão durante HTTP/espera, parar e adiar após 429/`Retry-After` com backoff injetado.
- [ ] Rodar os dois arquivos e observar as falhas esperadas.
- [ ] Criar tabela separada via `METADATA` (compatível com `create_all` no PostgreSQL existente); implementar consultas SQL no repositório; coordenar transações curtas no coletor. Usar intervalo inicial conservador de pelo menos 20 s entre requisições e calma após 429. O token ausente desativa apenas o coletor.
- [ ] Rodar testes focados até passar; revisar diff; commit.

### Task 3: Cálculo puro e classificação

**Interfaces:** `leitura.montar(..., vendas_por_par=...)` e `LinhaVarrida` expõem `valor_venda`, `potencial`, `idade_venda`, `estado_venda` sem reutilizar `resultado` do preço sugerido. Aba `revenda` seleciona apenas potencial positivo e fresco.

- [ ] Escrever testes para mínimo em chaves e metal, conversão a `Brl`, item/efeito exatos, sem vendedor, indisponível, venda e Steam antigas, preço sugerido ausente e ordenação pela diferença de venda.
- [ ] Rodar `tests\varredura\test_leitura.py` e observar falhas esperadas.
- [ ] Implementar regra sem depender de HTTP/SQL; usar `Decimal` para quantidades e arredondar apenas na fronteira de centavos. Conservar `resultado` atual como guide gap separado, mas não usá-lo na aba de revenda.
- [ ] Rodar teste focado até passar; revisar diff; commit.

### Task 4: Integração, interface e documentação

**Interfaces:** fábrica inicia o coletor somente quando `BPTF_USER_TOKEN` está presente; rota `/scan` lê cache no mesmo bloco curto das listagens. Template distingue `Lowest observed seller ask`, `Potential resale`, `Suggested backpack.tf price` e `Guide gap`.

- [ ] Escrever teste de rota com dublês e linhas persistidas: venda fresca positiva/negativa, sem venda, falha com dado antigo, nenhuma rede na rota; teste da fábrica sem token nem I/O obrigatório.
- [ ] Rodar `tests\painel\test_scan.py` e observar falhas esperadas.
- [ ] Ligar coletor à inicialização sem tocar a rede; atualizar filtros, ordenação, cópia, idades e links. Explicar que pedido não é venda concluída e que atributos do anúncio devem ser verificados antes da compra.
- [ ] Documentar `BPTF_USER_TOKEN` em `.env.example` e README sem valor real. Atualizar achado para refletir status da implementação.
- [ ] Rodar teste focado até passar; revisar diff; commit.

### Task 5: Verificação final

- [ ] Executar `C:\Users\gusco\Desktop\tf2-price\.venv\Scripts\python.exe -m pytest` no worktree.
- [ ] Executar `git diff --check` e `git status --short`; inspecionar o diff desde o plano anterior para descartar segredos e artefatos.
- [ ] Fazer revisão de código do conjunto, corrigir problemas importantes e repetir os testes afetados.
