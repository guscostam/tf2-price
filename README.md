# tf2price

Spike de validação: mede uma vez o mercado de TF2 na Steam contra os preços
da backpack.tf e emite um veredito sobre construir ou não o app completo.

## Pré-requisitos

- Python 3.12+
- API key da backpack.tf: https://backpack.tf/developer/apikey/new (login via Steam)
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
