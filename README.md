# tf2price

Spike de validação: mede uma vez o mercado de TF2 na Steam contra os preços
da backpack.tf e emite um veredito sobre construir ou não o app completo.

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

O último comando gera `tf2price/data/effects.json` a partir do schema
oficial do TF2 e precisa de `STEAM_API_KEY` configurada em `.env`.

## Uso

```bash
# ensaio rápido, poucas páginas e poucas candidatas
.venv/Scripts/python -m tf2price.spike.run --max-pages 2 --deep-limit 3 --out out/ensaio

# execução completa (15 a 30 minutos com o intervalo padrão de 3s)
.venv/Scripts/python -m tf2price.spike.run --out out
```

Requer `BPTF_API_KEY` configurada em `.env`; sem ela o comando encerra com
erro. As saídas vão para `out/relatorio.md` (veredito e análise) e
`out/oportunidades.csv` (lista bruta).

## Testes

```bash
.venv/Scripts/python -m pytest
```

Nenhum teste toca a rede.

## Documentos

- Spec: `docs/superpowers/specs/2026-09-19-tf2-arbitragem-spike-design.md`
- Plano: `docs/superpowers/plans/2026-09-19-tf2-arbitragem-spike.md`
- Verificações: `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`
  (pendente: depende da execução real, que depende das chaves de API)

## Consulta de Unusual

A aplicação atual. Você escolhe um chapéu Unusual e um efeito, e a tela diz quanto
ele custa na Steam, quanto vale na troca, e quanto alguém está disposto a pagar
agora.

```bash
.venv/Scripts/python -m tf2price.lookup.app
```

Abre em `http://127.0.0.1:8000`. A subida baixa o índice de preços da backpack.tf
uma vez; cada consulta depois custa duas requisições à Steam.

A tela separa com rigor dois níveis de dado, porque confundi-los invalidou a versão
anterior deste projeto:

- **por efeito** — as listagens do efeito escolhido e o preço da backpack.tf dele,
  sempre com a idade do preço à vista
- **todos os efeitos do item** — o livro de ofertas e o histórico de vendas, que a
  Steam não separa por efeito

Quando a backpack.tf não precifica o efeito escolhido, a tela diz isso em vez de
mostrar o preço de outro efeito.

### O que a varredura anterior descobriu, e por que foi aposentada

Uma versão que varria o mercado inteiro foi construída, executada e reprovada. Ela
comparava o preço de um efeito contra o preço sugerido de outro, porque os efeitos
que a backpack.tf precifica quase não se sobrepõem aos que estão à venda na Steam.
O relato está em `docs/superpowers/findings/2026-09-19-verificacoes-tecnicas.md`.

### O que o primeiro uso real mostrou

O preço da Steam fica, na mediana, **1,72× acima** do valor de troca. A arbitragem
que este projeto procurava corre na direção contrária. Os números estão em
`docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`.
