# tf2price

Uma tela local onde você escolhe um chapéu Unusual e um efeito, e ela diz quanto
ele custa na Steam, quanto vale na troca, e quanto alguém está disposto a pagar
agora.

## Pré-requisitos

- Python 3.12+
- API key da backpack.tf: https://next.backpack.tf/developer/ (login via Steam)
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

Abre em `http://127.0.0.1:8000`. Na primeira subida, com o banco vazio, o
terminal imprime um link de convite de administrador válido por 24 horas — é
por ele que a primeira conta nasce. Depois, novas contas saem de `/admin`.

Requer `BPTF_API_KEY` e `DATABASE_URL` no `.env`. A aplicação sobe mesmo quando
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

## Implantação (Railway)

1. Crie o serviço a partir do repositório e acrescente um serviço **Postgres** —
   o Railway injeta `DATABASE_URL` sozinho.
2. Configure `BPTF_API_KEY` nas variáveis do serviço web.
3. O `Procfile` já sobe com `--proxy-headers`, necessário para o cookie de
   sessão receber `Secure` atrás do proxy.
4. Na primeira subida, procure no log a linha `[partida] convite de
   administrador:` e abra o link.

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
histórico do git até `8f99176`.

## Documentos

- Spec da tela: `docs/superpowers/specs/2026-09-19-consulta-unusual-design.md`
- Plano da tela: `docs/superpowers/plans/2026-09-19-consulta-unusual.md`
- Primeiro uso real: `docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`
- Histórico da varredura: `docs/superpowers/specs/2026-09-19-tf2-arbitragem-spike-design.md`,
  `docs/superpowers/plans/2026-09-19-tf2-arbitragem-spike.md` e
  `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`
