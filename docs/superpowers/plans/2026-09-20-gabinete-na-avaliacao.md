# O gabinete na avaliação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar o visual da avaliação pelo gabinete de espécimes aprovado no desenho: fundo escuro, a foto real do chapéu vinda da Steam, e a arte real do efeito se movendo atrás dele em campo de emissão.

**Architecture:** Três peças novas e pequenas — `efeitos/arte.py` resolve nome do efeito para arquivo local, `efeitos/coletor.py` baixa a arte uma vez pelo navegador, e uma rota estática serve as imagens. O parser da Steam ganha o `icon_url` que já vem na página e hoje é descartado. O resto é CSS e template.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, CSS próprio (sem framework), pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-painel-fechado-design.md`, §9 e §10.

---

## O que este plano NÃO faz

A planta de duas colunas aprovada no desenho tem, à esquerda, a lista de itens
acompanhados — e isso é o plano 2, que não existe ainda. Construir as duas
colunas agora entregaria uma coluna vazia. **A tela continua em coluna única**;
o gabinete, a placa, a foto e a aura entram na avaliação, que é onde o desenho
acontece de verdade. As duas colunas ficam para quando houver o que pôr na
esquerda.

## Verificações feitas antes de planejar

Medido nesta máquina, não suposto:

- **O `icon_url` já chega na página e é descartado.** Ele vive em
  `queryData → queries[N] → state → data → pages[0] → listings[N] → description
  → icon_url`. O `_query_data` já faz esse segundo parse, e `_efeito()` já lê
  `item["description"]`. A fixture `tests/fixtures/steam_listing_page.html` tem
  16 ocorrências — dá para testar sem rede.
- **O ícone é por listagem, não por item.** Chapéu pintado tem ícone próprio.
  Por isso ele vai em `PageListing`, e a tela usa o da listagem mais barata do
  efeito escolhido — não um "ícone do item", que mostraria a variante errada.
- **Quatro artes reais já estão baixadas** em `C:\Users\gusco\Downloads\`:
  `efeito_13.png` (Burning Flames), `efeito_6.png` (Green Confetti),
  `efeito_70.png` (Time Warp), `efeito_3229.png` (Deep Dive). Servem para
  construir e testar a tela antes da coleta completa.
- **A arte tem alfa real** (canto 0, 49% transparente) e o Cloudflare da
  backpack.tf recusa cliente que não seja navegador — daí a coleta ser única e
  feita na máquina do dono.

## Global Constraints

- Python 3.12+; a suíte roda com `.venv/Scripts/python -m pytest` (Windows).
  **Não use `-q`**: o `pyproject.toml` já traz um, e o segundo vira `-qq` e some
  com a linha-resumo.
- **Nenhum teste faz requisição de rede.**
- **CSS próprio, sem Tailwind nem framework.** As variáveis de tema ficam no
  `:root` de `base.html`, e cada regra não óbvia carrega o comentário que diz
  por que ela existe.
- **Nenhum dado aparece no lugar de outro.** Efeito sem arte **não** ganha aura
  genérica: recebe tratamento tipográfico e a marca de ausência.
- **Movimento respeita `prefers-reduced-motion`** e para quando a aba está
  oculta.
- Mensagens e nomes de código em português; comentários explicam por que.
- Commits em português, no imperativo, **sem rodapé de atribuição** — o dono
  removeu esses rodapés do histórico e o repositório é público.
- O deploy é automático a cada push na `master`; trabalhe em branch.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `tf2price/sources/steam_page.py` | ganha `icon_url` em `PageListing` |
| `tf2price/efeitos/arte.py` | nome do efeito → URL da arte local, ou ausência |
| `tf2price/efeitos/coletor.py` | coleta única, pelo navegador |
| `tf2price/data/efeitos/<id>.webp` | a arte, commitada |
| `tf2price/painel/app.py` | rota `/arte/{id}.webp` |
| `tf2price/painel/templates/base.html` | paleta do gabinete |
| `tf2price/painel/templates/_analise.html` | a placa com chapéu e aura |

## Sequência

1. `icon_url` no parser
2. `efeitos/arte.py`
3. rota que serve a arte
4. a tela: gabinete, placa, aura
5. `efeitos/coletor.py` e a coleta real

---

### Task 1: o `icon_url` que a página já entrega

**Files:**
- Modify: `tf2price/sources/steam_page.py`
- Test: `tests/sources/test_steam_page.py`

**Interfaces:**
- Produces: `PageListing.icon_url: str | None` e
  `steam_page.url_da_imagem(icon_url: str, tamanho: str = "330x192") -> str`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/sources/test_steam_page.py`:

```python
def test_listagem_traz_o_icone_do_item():
    """O icon_url já vem na página e era descartado.

    Ele é por listagem, não por item: chapéu pintado tem ícone próprio, então
    usar o de outra listagem mostraria a variante errada.
    """
    pagina = parse_item_page(_html(), NOME, 1.0)
    assert pagina.listings[0].icon_url
    assert len(pagina.listings[0].icon_url) > 40


def test_url_da_imagem_monta_o_endereco_da_cdn():
    assert url_da_imagem("abc123", "330x192").endswith("/economy/image/abc123/330x192")


def test_listagem_sem_icone_nao_quebra():
    """Ausência do campo é possível e não pode derrubar a página inteira."""
    from tf2price.sources.steam_page import _icone

    assert _icone({}) is None
    assert _icone({"description": {}}) is None
```

Acrescente `url_da_imagem` ao import do topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/sources/test_steam_page.py -k icone`
Expected: FAIL — `ImportError` em `url_da_imagem`, e `PageListing` sem `icon_url`

- [ ] **Step 3: Implementar**

Em `tf2price/sources/steam_page.py`, acrescente ao lado das outras constantes:

```python
# A CDN de economia da Steam serve o ícone a partir do caminho que vem na
# listagem. O tamanho é parte do caminho, não parâmetro de consulta.
CDN_IMAGEM = "https://community.cloudflare.steamstatic.com/economy/image"


def url_da_imagem(icon_url: str, tamanho: str = "330x192") -> str:
    return f"{CDN_IMAGEM}/{icon_url}/{tamanho}"
```

Acrescente o campo à dataclass `PageListing`:

```python
    icon_url: str | None
```

O auxiliar, ao lado de `_efeito`:

```python
def _icone(listagem: dict[str, Any]) -> str | None:
    """Caminho do ícone na CDN, ou None.

    Mesmo lugar de onde `_efeito` lê: a descrição da listagem.
    """
    valor = (listagem.get("description") or {}).get("icon_url")
    return str(valor) if valor else None
```

E em `_listagens`, dentro do `PageListing(...)`:

```python
                    icon_url=_icone(item),
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/sources/test_steam_page.py`
Expected: PASS

- [ ] **Step 5: Suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: tudo verde. Se algum teste construir `PageListing` à mão, ele vai
precisar do campo novo — acrescente `icon_url=None` nesses lugares e diga quais
no relatório.

```bash
git add -A && git commit -m "Le o icone do item que a pagina ja entregava"
```

---

### Task 2: `efeitos/arte.py` — do nome do efeito ao arquivo

**Files:**
- Create: `tf2price/efeitos/__init__.py` (vazio), `tf2price/efeitos/arte.py`
- Create: `tf2price/data/efeitos/.gitkeep`
- Test: `tests/efeitos/__init__.py` (vazio), `tests/efeitos/test_arte.py`

**Interfaces:**
- Consumes: `domain.effects.effect_id_for`, `domain.effects.DEFAULT_EFFECTS_PATH`.
- Produces: `arte.DIRETORIO: Path`, `arte.url_do_efeito(efeito: str, diretorio: Path | None = None, effects_path: Path | None = None) -> str | None`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/efeitos/test_arte.py`:

```python
from __future__ import annotations

from pathlib import Path

from tf2price.efeitos import arte

EFEITOS = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"


def test_efeito_com_arte_vira_url(tmp_path):
    """Burning Flames é 13 na fixture de efeitos."""
    (tmp_path / "13.webp").write_bytes(b"nao importa")
    assert arte.url_do_efeito("Burning Flames", tmp_path, EFEITOS) == "/arte/13.webp"


def test_efeito_sem_arquivo_nao_inventa_url(tmp_path):
    """17% dos efeitos não têm arte na fonte. Eles não ganham aura genérica."""
    assert arte.url_do_efeito("Burning Flames", tmp_path, EFEITOS) is None


def test_efeito_fora_do_mapa_e_none(tmp_path):
    (tmp_path / "13.webp").write_bytes(b"nao importa")
    assert arte.url_do_efeito("Efeito Que Nao Existe", tmp_path, EFEITOS) is None


def test_nome_de_arquivo_nao_aceita_travessia(tmp_path):
    """O id vem do nosso mapa, mas a rota que serve isto recebe texto de fora."""
    assert arte.url_do_efeito("../../etc/passwd", tmp_path, EFEITOS) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/efeitos -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tf2price.efeitos'`

- [ ] **Step 3: Implementar `tf2price/efeitos/arte.py`**

```python
"""Do nome do efeito ao arquivo de arte que nós servimos.

A arte é baixada uma vez pelo navegador (veja `coletor.py`) e vive no
repositório. Nunca é puxada ao vivo: o Cloudflare da backpack.tf recusa
requisição de servidor, e uma dependência que falha no caminho de renderização
não entra aqui.
"""

from __future__ import annotations

from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for

DIRETORIO = Path(__file__).resolve().parent.parent / "data" / "efeitos"


def url_do_efeito(
    efeito: str,
    diretorio: Path | None = None,
    effects_path: Path | None = None,
) -> str | None:
    """URL local da arte, ou None quando não temos a arte deste efeito.

    Devolver None é uma resposta legítima e frequente: parte dos efeitos não
    tem arte na fonte, e a tela trata essa ausência com tipografia em vez de
    inventar uma aura que não é a daquele efeito.
    """
    ident = effect_id_for(efeito, effects_path or DEFAULT_EFFECTS_PATH)
    if ident is None:
        return None
    arquivo = (diretorio or DIRETORIO) / f"{ident}.webp"
    if not arquivo.is_file():
        return None
    return f"/arte/{ident}.webp"
```

Crie também `tf2price/data/efeitos/.gitkeep` vazio, para o diretório existir no
repositório antes da coleta.

- [ ] **Step 4: Rodar, suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`
Expected: tudo verde

```bash
git add -A && git commit -m "Resolve a arte de um efeito, ou declara a ausencia"
```

---

### Task 3: a rota que serve a arte

**Files:**
- Modify: `tf2price/painel/app.py`
- Test: `tests/painel/test_arte.py`

**Interfaces:**
- Produces: rota `GET /arte/{nome}` servindo de `arte.DIRETORIO`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_arte.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app
from tests.painel.conftest import _contexto


@pytest.fixture
def cliente(engine, tmp_path, monkeypatch):
    from tf2price.efeitos import arte

    monkeypatch.setattr(arte, "DIRETORIO", tmp_path)
    (tmp_path / "13.webp").write_bytes(b"RIFF-fingindo-ser-webp")
    return TestClient(criar_app(engine, _contexto()))


def test_serve_a_arte_existente(cliente):
    r = cliente.get("/arte/13.webp")
    assert r.status_code == 200
    assert r.content == b"RIFF-fingindo-ser-webp"


def test_arte_inexistente_e_404(cliente):
    assert cliente.get("/arte/999999.webp").status_code == 404


@pytest.mark.parametrize(
    "nome", ["../../pyproject.toml", "..%2F..%2Fpyproject.toml", "13.webp/../../x"]
)
def test_travessia_de_caminho_e_recusada(cliente, nome):
    """A rota recebe texto de fora; o nome tem que ser conferido, não confiado."""
    r = cliente.get(f"/arte/{nome}")
    assert r.status_code in (403, 404)


def test_arte_nao_exige_sessao(cliente):
    """É imagem estática; exigir sessão só faria o navegador pedir duas vezes."""
    sem_sessao = TestClient(criar_app(cliente.app.state.engine, _contexto()))
    assert sem_sessao.get("/arte/13.webp").status_code == 200
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_arte.py`
Expected: FAIL com 404 em todas (a rota não existe)

- [ ] **Step 3: Implementar em `criar_app`**

Acrescente o import no topo de `app.py`:

```python
import re

from fastapi.responses import FileResponse

from tf2price.efeitos import arte as arte_dos_efeitos
```

E a rota, antes do `return app`:

```python
    # O nome só pode ser <digitos>.webp. Conferir com expressão regular em vez
    # de juntar caminho e torcer: esta rota recebe texto de fora.
    _NOME_DE_ARTE = re.compile(r"^\d{1,7}\.webp$")

    @app.get("/arte/{nome}")
    def servir_arte(nome: str) -> Response:
        if not _NOME_DE_ARTE.match(nome):
            return Response(status_code=404)
        arquivo = arte_dos_efeitos.DIRETORIO / nome
        if not arquivo.is_file():
            return Response(status_code=404)
        # A arte de um efeito nunca muda: cache longo evita pedir de novo a
        # cada avaliação aberta.
        return FileResponse(
            arquivo,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
```

- [ ] **Step 4: Rodar, suíte inteira e commit**

Run: `.venv/Scripts/python -m pytest`

```bash
git add -A && git commit -m "Serve a arte dos efeitos com cache longo"
```

---

### Task 4: a tela — gabinete, placa e aura

**Files:**
- Modify: `tf2price/painel/templates/base.html`, `tf2price/painel/templates/_analise.html`
- Modify: `tf2price/painel/consulta.py`
- Test: `tests/painel/test_consulta.py`

**Interfaces:**
- Consumes: `arte.url_do_efeito`, `steam_page.url_da_imagem`, `PageListing.icon_url`.
- Produces: contexto do template com `arte` e `chapeu` na rota `/analise`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/painel/test_consulta.py`:

```python
def test_avaliacao_mostra_o_chapeu_e_a_aura(engine, tmp_path, monkeypatch):
    """A foto é do item de verdade e a aura é a arte do efeito escolhido."""
    from tf2price.efeitos import arte

    monkeypatch.setattr(arte, "DIRETORIO", tmp_path)
    (tmp_path / "3229.webp").write_bytes(b"arte")  # Deep Dive

    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text

    assert "/arte/3229.webp" in texto
    assert "economy/image/" in texto


def test_efeito_sem_arte_recebe_tipografia_e_nao_aura(engine, tmp_path, monkeypatch):
    """Inventar aura genérica repetiria o erro que invalidou a primeira versão."""
    from tf2price.efeitos import arte

    monkeypatch.setattr(arte, "DIRETORIO", tmp_path)  # vazio: nenhuma arte

    cliente = cliente_logado(engine, _contexto())
    texto = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text

    assert "/arte/" not in texto
    assert "sem arte deste efeito" in texto
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/painel/test_consulta.py -k "chapeu or tipografia"`
Expected: FAIL — o template ainda não tem placa nenhuma

- [ ] **Step 3: Passar arte e chapéu no contexto**

Em `tf2price/painel/consulta.py`, no topo:

```python
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.sources.steam_page import url_da_imagem
```

E em `rota_analise`, no `TemplateResponse`:

```python
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_analise.html",
        context={
            "a": resultado,
            "arte": arte_dos_efeitos.url_do_efeito(efeito),
            # O ícone é o da listagem mais barata deste efeito: chapéu pintado
            # tem ícone próprio, e o de outra listagem seria outra variante.
            "chapeu": (
                url_da_imagem(resultado.cheapest.icon_url)
                if resultado.cheapest.icon_url
                else None
            ),
        },
    )
```

- [ ] **Step 4: A placa no `_analise.html`**

Substitua o bloco que hoje começa em `<h2>{{ a.effect }}</h2>` e vai até o fim
da `div.pago` por:

```html
<article class="avaliacao">
  <div class="placa">
    <div class="palco">
      {% if arte %}
      <img class="aura" src="{{ arte }}" alt="">
      <img class="aura" src="{{ arte }}" alt="">
      <img class="aura" src="{{ arte }}" alt="">
      {% endif %}
      {% if chapeu %}
      <img class="chapeu" src="{{ chapeu }}" alt="{{ a.hash_name }}">
      {% endif %}
      {% if not arte %}
      <div class="sem-arte">
        <span class="sem-arte-nome">{{ a.effect }}</span>
        <span class="sem-arte-marca">sem arte deste efeito</span>
      </div>
      {% endif %}
    </div>
  </div>

  <h2>{{ a.effect }}</h2>
  <p class="item-nome">{{ a.hash_name }}</p>

  <div class="pago">
    <span class="rotulo">você paga</span>
    <span class="numero-grande"><span class="cifrao">R$</span>{{ a.cheapest.total_price|string|replace("R$ ", "") }}</span>
    <span class="em-chaves">{{ a.price_in_keys|chaves }} chaves · listagem mais barata deste efeito</span>
  </div>
```

O resto do arquivo não muda.

- [ ] **Step 5: A paleta do gabinete em `base.html`**

Troque o bloco `:root` inteiro por:

```css
    :root {
      /* Gabinete de espécimes: fundo escuro, a aura do efeito como única
         fonte de cor viva. A cor vem da arte, não de código. */
      --papel:   #0b0e12;
      --slip:    #12161c;
      --tinta:   #e4e7ec;
      --tinta-2: #97a1b0;
      --carimbo: #e07a5f;
      --aprovado:#6ee7a8;
      --linha:   rgba(228, 231, 236, .18);
      --display: "Big Shoulders Display", "Haettenschweiler", "Arial Narrow", sans-serif;
      --corpo:   "Spectral", Georgia, serif;
      --mono:    "IBM Plex Mono", ui-monospace, Consolas, monospace;
    }
```

Troque a linha do `<link>` das fontes para incluir Spectral:

```html
  <link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=Spectral:wght@300;400;600&display=swap" rel="stylesheet">
```

Troque o fundo do corpo e do cartão:

```css
    body { background: var(--papel); }
    .guia {
      background: radial-gradient(120% 90% at 50% 0%, #1b2430 0%, var(--slip) 70%);
      border: 1px solid #222c38;
      box-shadow: 0 24px 60px -40px #000;
    }
    body::before { opacity: .03; }
```

E acrescente ao fim do `<style>`:

```css
    /* --- a placa do espécime ------------------------------------------ */
    .placa { margin: 0 0 1.2rem; border: 1px solid #222c38; background: #0c1015; }
    .palco { position: relative; height: 200px; overflow: hidden; }
    .chapeu {
      position: absolute; left: 50%; top: 54%; width: 120px;
      transform: translate(-50%, -50%); z-index: 2;
      filter: drop-shadow(0 10px 16px rgba(0, 0, 0, .7));
    }
    /* Campo de emissão: três cópias da mesma arte nascendo embaixo, subindo e
       morrendo em cima, defasadas. É o que uma partícula faz no jogo, e é o
       mais perto do efeito real sem existir vídeo dele. */
    .aura {
      position: absolute; left: 50%; top: 50%; width: 200px; height: 200px;
      transform: translate(-50%, -50%); mix-blend-mode: screen;
      pointer-events: none; animation: emite 3.6s linear infinite;
    }
    .aura:nth-of-type(2) { animation-delay: -2.4s; width: 150px; height: 150px; }
    .aura:nth-of-type(3) { animation-delay: -1.2s; width: 236px; height: 236px; opacity: .5; }
    @keyframes emite {
      0%   { transform: translate(-50%, -32%) scale(.8);  opacity: 0; }
      20%  { opacity: .95; }
      100% { transform: translate(-50%, -74%) scale(1.18); opacity: 0; }
    }
    /* Efeito sem arte não ganha aura inventada: ganha o próprio nome. */
    .sem-arte {
      position: absolute; inset: 0; display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: .5rem; text-align: center;
    }
    .sem-arte-nome {
      font-family: var(--mono); font-size: clamp(1rem, 4vw, 1.5rem);
      letter-spacing: .14em; text-transform: uppercase; color: var(--tinta-2);
      border-bottom: 1px solid var(--linha); padding-bottom: .4rem;
    }
    .sem-arte-marca {
      font-family: var(--mono); font-size: .66rem; letter-spacing: .12em;
      text-transform: uppercase; color: #6b7482;
    }
    /* Com dez avaliações abertas o movimento custa; parar quando ninguém
       está olhando é de graça. */
    @media (prefers-reduced-motion: reduce) { .aura { animation: none; } }
```

E acrescente ao `<script>` do `painel.html`:

```javascript
  // Aba oculta não precisa animar.
  document.addEventListener("visibilitychange", function () {
    document.querySelectorAll(".aura").forEach(function (a) {
      a.style.animationPlayState = document.hidden ? "paused" : "running";
    });
  });
```

- [ ] **Step 6: Rodar e conferir com os olhos**

Run: `.venv/Scripts/python -m pytest`
Expected: tudo verde

Depois copie as quatro artes já baixadas para poder ver a tela de verdade:

```bash
cp "C:/Users/gusco/Downloads/efeito_13.png" tf2price/data/efeitos/13.webp
cp "C:/Users/gusco/Downloads/efeito_6.png" tf2price/data/efeitos/6.webp
cp "C:/Users/gusco/Downloads/efeito_70.png" tf2price/data/efeitos/70.webp
cp "C:/Users/gusco/Downloads/efeito_3229.png" tf2price/data/efeitos/3229.webp
```

(São PNG com extensão trocada, só para o ensaio local. A coleta da Task 5
grava WebP de verdade e sobrescreve.)

Suba a aplicação e abra uma avaliação de um efeito com arte. **Não commite os
quatro arquivos de ensaio.**

- [ ] **Step 7: Commit**

```bash
git add tf2price/painel tf2price/sources tests
git commit -m "Veste a avaliacao com o gabinete, o chapeu real e a aura do efeito"
```

---

### Task 5: `efeitos/coletor.py` e a coleta real

**Files:**
- Create: `tf2price/efeitos/coletor.py`
- Test: `tests/efeitos/test_coletor.py`

**Interfaces:**
- Produces: `python -m tf2price.efeitos.coletor`, servindo em `127.0.0.1:8765`;
  `coletor.ids_a_coletar() -> list[int]`, `coletor.gravar(ident: int, dados: bytes) -> Path`.

**Por que pelo navegador:** o Cloudflare da backpack.tf devolve 403 a cliente
que não é navegador — medido, com e sem cabeçalhos falsos. O navegador do dono
passa. Então o navegador busca e envia para um servidor local, que grava.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/efeitos/test_coletor.py`:

```python
from __future__ import annotations

from tf2price.efeitos import coletor


def test_ids_a_coletar_ignora_os_sem_nome():
    """O schema tem entradas Attrib_ParticleNNN, que não são efeitos de verdade."""
    ids = coletor.ids_a_coletar()
    assert len(ids) > 400
    assert all(isinstance(i, int) for i in ids)


def test_gravar_cria_o_arquivo_com_o_id(tmp_path):
    caminho = coletor.gravar(13, b"bytes-da-arte", tmp_path)
    assert caminho.name == "13.webp"
    assert caminho.read_bytes() == b"bytes-da-arte"


def test_gravar_recusa_id_invalido(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        coletor.gravar(-1, b"x", tmp_path)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/efeitos/test_coletor.py`
Expected: FAIL com `ImportError`

- [ ] **Step 3: Implementar `tf2price/efeitos/coletor.py`**

```python
"""Coleta única da arte dos efeitos, feita pelo navegador do dono.

O Cloudflare da backpack.tf devolve 403 a cliente que não é navegador —
medido, com e sem cabeçalhos de navegador falsos. Então quem busca é o
navegador, numa página servida daqui, e quem grava é este servidor local.

Roda uma vez:

    python -m tf2price.efeitos.coletor

Abre http://127.0.0.1:8765, clica em começar, espera, e o relatório final diz
quantas vieram e quais faltaram.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH
from tf2price.efeitos.arte import DIRETORIO

PORTA = 8765
FONTE = "https://backpack.tf/images/440/particles/{id}_188x188.png"


def ids_a_coletar(effects_path: Path | None = None) -> list[int]:
    """Ids dos efeitos com nome de verdade.

    O schema traz entradas como `Attrib_Particle140`, que são reservas sem
    nome publicado e nunca aparecem no mercado.
    """
    mapa = json.loads((effects_path or DEFAULT_EFFECTS_PATH).read_text(encoding="utf-8"))
    return sorted(v for k, v in mapa.items() if not k.startswith("Attrib_Particle"))


def gravar(ident: int, dados: bytes, diretorio: Path | None = None) -> Path:
    if not isinstance(ident, int) or ident <= 0:
        raise ValueError(f"id inválido: {ident!r}")
    destino = diretorio or DIRETORIO
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{ident}.webp"
    caminho.write_bytes(dados)
    return caminho


PAGINA = """<!doctype html>
<meta charset="utf-8">
<title>Coletor de arte</title>
<style>
  body { font-family: system-ui; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; }
  progress { width: 100%; height: 1.2rem; }
  #faltaram { font-family: ui-monospace, monospace; font-size: .85rem; color: #b3261e; }
</style>
<h1>Coletor de arte dos efeitos</h1>
<p>Busca cada efeito na backpack.tf, converte para WebP e envia para este
servidor local, que grava em <code>tf2price/data/efeitos/</code>. Uma pausa de
300 ms entre as buscas, para não bater na fonte sem educação.</p>
<button id="ir">Começar</button>
<p><progress id="barra" value="0" max="1"></progress> <span id="conta"></span></p>
<p id="faltaram"></p>
<script>
const ids = IDS_AQUI;
document.getElementById("ir").onclick = async () => {
  const barra = document.getElementById("barra");
  const conta = document.getElementById("conta");
  barra.max = ids.length;
  let vieram = 0;
  const faltaram = [];
  for (let i = 0; i < ids.length; i++) {
    const id = ids[i];
    try {
      const r = await fetch(`https://backpack.tf/images/440/particles/${id}_188x188.png`);
      if (!r.ok) { faltaram.push(id); }
      else {
        const bmp = await createImageBitmap(await r.blob());
        const c = document.createElement("canvas");
        c.width = bmp.width; c.height = bmp.height;
        c.getContext("2d").drawImage(bmp, 0, 0);
        const webp = await new Promise(res => c.toBlob(res, "image/webp", 0.85));
        await fetch(`/gravar/${id}`, { method: "POST", body: webp });
        vieram++;
      }
    } catch (e) { faltaram.push(id); }
    barra.value = i + 1;
    conta.textContent = `${i + 1} de ${ids.length} — ${vieram} gravadas`;
    await new Promise(r => setTimeout(r, 300));
  }
  document.getElementById("faltaram").textContent =
    faltaram.length ? `sem arte na fonte (${faltaram.length}): ${faltaram.join(", ")}` : "todas vieram";
  await fetch("/fim", { method: "POST", body: JSON.stringify(faltaram) });
};
</script>
"""


class _Tratador(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        corpo = PAGINA.replace("IDS_AQUI", json.dumps(ids_a_coletar())).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self) -> None:  # noqa: N802
        tamanho = int(self.headers.get("Content-Length", 0))
        dados = self.rfile.read(tamanho)
        if self.path.startswith("/gravar/"):
            gravar(int(self.path.rsplit("/", 1)[1]), dados)
        elif self.path == "/fim":
            faltaram = json.loads(dados or b"[]")
            print(f"\nColeta terminada. Sem arte na fonte: {len(faltaram)}")
            if faltaram:
                print("ids:", ", ".join(str(i) for i in faltaram))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass  # o progresso aparece na página, não no terminal


def main() -> None:
    print(f"Abra http://127.0.0.1:{PORTA} e clique em Começar.")
    print(f"As imagens vão para {DIRETORIO}")
    HTTPServer(("127.0.0.1", PORTA), _Tratador).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar os testes e commitar a ferramenta**

Run: `.venv/Scripts/python -m pytest`

```bash
git add -A && git commit -m "Acrescenta o coletor de arte, que roda no navegador"
```

- [ ] **Step 5: A coleta real — precisa do dono**

Esta etapa **não é do implementador**. Ela roda na máquina do dono:

```bash
.venv/Scripts/python -m tf2price.efeitos.coletor
```

Abrir `http://127.0.0.1:8765`, clicar em Começar, esperar (com 300 ms entre
cada, ~547 efeitos levam uns 3 minutos), e anotar quantos faltaram.

Depois:

```bash
git add tf2price/data/efeitos
git commit -m "Acrescenta a arte dos efeitos, coletada uma vez"
```

## Cobertura da spec

| Seção | Onde |
|---|---|
| §9 coleta única pelo navegador | Task 5 |
| §9 arte commitada e servida por nós | Tasks 2 e 3 |
| §9 efeito sem arte não ganha imitação | Tasks 2 e 4 |
| §10 gabinete, placa, campo de emissão | Task 4 |
| §10 movimento respeita redução e aba oculta | Task 4 |

**Fora deste plano:** as duas colunas e a lista de acompanhados, que dependem
do plano 2.
