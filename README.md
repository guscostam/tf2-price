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
.venv/Scripts/python -m tf2price.lookup.app
```

Abre em `http://127.0.0.1:8000`. A subida baixa o índice de preços da backpack.tf
uma vez; cada consulta depois custa duas requisições à Steam.

A tela separa com rigor dois níveis de dado, porque confundi-los invalidou a
primeira versão deste projeto:

- **por efeito** — as listagens do efeito escolhido e o preço da backpack.tf dele,
  sempre com a idade do preço à vista
- **todos os efeitos do item** — o livro de ofertas e o histórico de vendas, que a
  Steam não separa por efeito

Quando a backpack.tf não precifica o efeito escolhido, a tela diz isso em vez de
mostrar o preço de outro efeito.

A busca aceita a dupla qualidade (`Strange Unusual ...`), que é quase um terço
dos nomes e a faixa mais cara do mercado, e recusa as ferramentas
`Unusual Taunt: X Unusualifier` — elas aplicam um efeito, não o têm.

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
