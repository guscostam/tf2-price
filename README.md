# briefcase.tf

Uma tela local onde você escolhe um chapéu Unusual e um efeito, e ela diz quanto
ele custa na Steam, quanto vale na troca, e quanto alguém está disposto a pagar
agora.

## Product interface

The web product is named **briefcase.tf — Unusual Market Intelligence**.
Its interface is in English and separates evidence for `THIS EFFECT` from
Steam context for `ALL EFFECTS`. It is an independent fan-made project and is
not affiliated with Valve, Steam, or backpack.tf.

Authenticated navigation: `Overview`, `New Case`, `Case Files`, `Sources`, and
`Administration` for administrators.

## Pré-requisitos

- Python 3.12+
- API key da backpack.tf: https://next.backpack.tf/developer/ (login via Steam)
- Access Token da backpack.tf para vendas do Market Scan: https://next.backpack.tf/account/api-access
- Steam Web API key, só para gerar o mapa de efeitos: https://steamcommunity.com/dev/apikey

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env    # preencha BPTF_API_KEY e STEAM_API_KEY
.venv/Scripts/python scripts/fetch_effects.py
```

O último comando gera `tf2price/data/effects.json` a partir do schema oficial do
TF2 e precisa de `STEAM_API_KEY` configurada em `.env`.

## Uso

```bash
.venv/Scripts/python -m tf2price.painel.app
```

Abre em `http://127.0.0.1:8000`. Sem sessão, a raiz mostra a landing pública,
onde qualquer pessoa pode pedir acesso informando o perfil da Steam e um
contato; com sessão, a raiz é o Overview. Na primeira subida, com o banco
vazio, o terminal imprime um link de convite de administrador válido por 24
horas — é por ele que a primeira conta nasce. Depois, novas contas saem de
`/admin`, que também lista os pedidos de acesso pendentes: `Create invite`
gera o link para enviar à pessoa, `Dismiss` descarta o pedido.

A conta nomeada em `SUPERADMIN` é a dona do painel: só ela promove e rebaixa
administradores (`Make admin` / `Remove admin` em `/admin`), e ninguém mexe
nela. Os outros administradores convidam, resetam senha e desativam apenas
membros. Sem a variável, o painel funciona, mas ninguém promove nem rebaixa.

Requer `BPTF_API_KEY` e `DATABASE_URL` no `.env`. `BPTF_USER_TOKEN` habilita a
coleta de anúncios de venda no Market Scan; sem ele, a consulta pontual e o
preço sugerido seguem disponíveis. A aplicação sobe mesmo quando
a Steam ou a backpack.tf estão fora do ar: a cotação e o índice de preços são
buscados na primeira necessidade, e a tela diz quando algum deles ainda não
carregou.

A tela separa com rigor dois níveis de dado, porque confundi-los invalidou a
primeira versão deste projeto:

- **por efeito** — as listagens do efeito escolhido e o preço da backpack.tf
  dele, sempre com a idade do preço à vista
- **todos os efeitos do item** — o livro de ofertas e o histórico de vendas, que
  a Steam não separa por efeito

Quando a backpack.tf não precifica o efeito escolhido, a tela diz isso em vez de
mostrar o preço de outro efeito.

A busca aceita a dupla qualidade (`Strange Unusual ...`), que é quase um terço
dos nomes e a faixa mais cara do mercado, e recusa as ferramentas
`Unusual Taunt: X Unusualifier` — elas aplicam um efeito, não o têm.

A página **Market Scan** lista as listagens de cosméticos Unusual varridas em
segundo plano. O admin liga, desliga e define o intervalo entre rodadas em
`/admin` (mínimo de 60 min).

O Market Scan mostra o menor anúncio de venda **observado** na backpack.tf
para o mesmo item e efeito, quando uma leitura autenticada recente contém um
exemplar comparável. A aba "Potential resale" mostra a diferença positiva
entre esse pedido e o preço Steam quando as duas leituras têm até seis horas.
O efeito e o ID do cosmético são conferidos contra o mapa do schema da Valve
gerado por `scripts/fetch_cosmeticos.py`.
É uma possibilidade de revenda, não lucro confirmado: preço pedido não prova
que haverá comprador. Atributos do exemplar Steam e do anúncio precisam ser
conferidos antes da compra. A coleta ocorre em segundo plano, com cache por
item e efeito, espaçamento de ao menos 20 segundos entre consultas e pausa
após limite da API. Sem vendedor comparável, falha da API e dado antigo são
estados diferentes; uma falha preserva a idade do último sucesso.

O preço **sugerido** da backpack.tf e a diferença "Guide gap" permanecem
separados. A aba "Below suggested price" filtra essa diferença pelo limite
de idade escolhido. Nenhuma delas representa uma oferta de compra. Linhas com
efeito conhecido oferecem link para conferir manualmente os vendedores.

A chave de referência é o valor da chave em dinheiro: o dólar da
chave segundo a backpack.tf vezes a PTAX do Banco Central. O preço da chave na
Steam só converte as listagens que a Steam devolve em dólar. O admin também vê o
progresso da rodada em curso e pode interrompê-la com "Stop scan"; num limite da
Steam (429) a rodada pausa e retoma sozinha, e só desiste depois de ~65 min sem
nenhuma requisição dar certo. Um reinício do serviço no meio de uma rodada a
marca como "Interrupted by a restart", e a próxima rodada espera um intervalo
inteiro contado do reinício.

## Implantação (Railway)

1. Crie o serviço a partir do repositório e acrescente um serviço **Postgres** —
   o Railway injeta `DATABASE_URL` sozinho.
2. Configure `BPTF_API_KEY` nas variáveis do serviço web.
3. O `Procfile` já sobe com `--proxy-headers`, necessário para o cookie de
   sessão receber `Secure` atrás do proxy.
4. Na primeira subida, procure no log a linha `[partida] convite de
   administrador:` e abra o link.
5. Depois de criar a conta, configure `SUPERADMIN` com o nome dela nas
   variáveis do serviço web. Na subida seguinte, o log não deve ter nenhuma
   linha `[superadmin]`; se tiver, o nome na variável não é um admin ativo.

Uma réplica só: o freio de requisições à Steam e o período de calma vivem na
memória do processo.

## Testes

```bash
.venv/Scripts/python -m pytest
```

Nenhum teste toca a rede.

## O que este projeto já respondeu

**O preço da Steam fica, na mediana, 1,72× acima do valor de troca.** A arbitragem
de comprar barato na Steam e ganhar valor em chaves corre na direção contrária, e
não por ser rara: por ser sistematicamente negativa. Zero arbitragem dura em 74
pares item-efeito. Os números estão em
`docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`.

Por isso a tela serve para **não** fazer um mau negócio pontual, e não para
encontrar bons negócios em série.

### A varredura aposentada

Uma primeira versão varria o mercado inteiro em busca de oportunidades. Foi
construída, executada e reprovada: ela comparava o preço de um efeito contra o
preço sugerido de outro, porque os efeitos que a backpack.tf precifica quase não
se sobrepõem aos que estão à venda na Steam. O código saiu do repositório quando
a tela provou ser o produto; o relato está em
`docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md` e o código, no
histórico do git até `520d654`.

## Documentos

- Spec da tela: `docs/superpowers/specs/2026-09-19-consulta-unusual-design.md`
- Plano da tela: `docs/superpowers/plans/2026-09-19-consulta-unusual.md`
- Primeiro uso real: `docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`
- Histórico da varredura: `docs/superpowers/specs/2026-09-19-tf2-arbitragem-spike-design.md`,
  `docs/superpowers/plans/2026-09-19-tf2-arbitragem-spike.md` e
  `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`
