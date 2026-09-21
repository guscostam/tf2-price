# briefcase.tf Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar a interface existente no produto `briefcase.tf`, com app shell responsivo, páginas `Overview`, `New Case`, `Case Files`, `Sources` e `Administration`, mantendo todos os dados e invariantes econômicos atuais.

**Architecture:** Rotas de página novas ficam em `painel/paginas.py`; endpoints HTMX e regras de análise permanecem em `painel/consulta.py`. Assets da marca, fontes, CSS e JavaScript passam a ser servidos localmente por `/static`, enquanto macros/partials Jinja centralizam navegação, estados, escopo dos dados e arquivos de caso. O dashboard usa somente memória e banco; rede continua restrita aos caminhos de consulta e ao aquecimento já existentes.

**Tech Stack:** Python 3.12+, FastAPI, Starlette StaticFiles, Jinja2, HTMX 1.9.12, CSS próprio, JavaScript sem framework, SQLAlchemy Core e pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-briefcase-tf-redesign-design.md`

## Global Constraints

- Interface pública integralmente em inglês; comentários técnicos e documentação interna podem continuar em português.
- Nome `briefcase.tf`, descriptor `Unusual Market Intelligence` e tagline `Every Unusual Is a Case.`.
- Paleta exata: Charcoal `#0E0F10`, Ink Panel `#15242A`, Ink Blue `#29424B`, Active Blue `#365866`, Paper `#E8E1D1`, Rust Stamp `#A4453A`, Warning `#D2A53B`.
- Tipografia: Roboto Slab, Roboto Condensed, Inter e IBM Plex Mono, todas servidas localmente em WOFF2; nenhuma requisição a Google Fonts em runtime.
- `THIS EFFECT` e `ALL EFFECTS` permanecem distintos em texto e estrutura. Nenhum preço ou listagem de outro efeito pode preencher ausência do efeito solicitado.
- Não implementar `Good Buy`, `Fair Price`, `Caution`, confidence score, faixa estimada, Market Index, gráfico inventado ou nova fonte.
- Imagem do item vem da listagem real da Steam; arte do efeito vem do WebP real empacotado. Ausência de arte recebe somente fallback tipográfico declarado.
- Cotação e retratos reaproveitados conservam `buscado_em`; toda idade exibida é a original.
- `GET /`, `GET /cases`, `GET /cases/new` e `GET /sources` não fazem I/O externo durante a renderização inicial.
- Nenhuma conexão ou transação permanece aberta durante HTTP, rate limit, backoff ou espera.
- SQL continua em repositórios; dinheiro continua em `Brl`; datas persistidas continuam UTC ingênuo.
- Testes nunca usam rede. Use dublês determinísticos e o engine SQLite existente.
- Preserve mesma origem, cookies, hash de tokens, isolamento por usuário e autorização de administrador.
- CSS sem framework; movimento respeita `prefers-reduced-motion` e pausa com a aba oculta.
- O layout funciona a 400 px sem rolagem horizontal da página e mantém alvos touch de pelo menos 44 × 44 px.
- Execute comandos com `.\.venv\Scripts\python.exe`; não acrescente `-q`, pois `pyproject.toml` já define `addopts = "-q"`.
- Commits em português, no imperativo, sem rodapé de atribuição.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `tf2price/painel/paginas.py` | páginas completas, contexto não bloqueante e navegação |
| `tf2price/painel/consulta.py` | endpoints HTMX, análise, casos e estados de fonte |
| `tf2price/painel/app.py` | montagem dos roteadores, static mount e handlers globais |
| `tf2price/painel/templates/base.html` | app shell autenticado |
| `tf2price/painel/templates/auth_base.html` | shell público de login/convite |
| `tf2price/painel/templates/_brand.html` | símbolo, wordmark e descriptor |
| `tf2price/painel/templates/_navigation.html` | menu responsivo e controle por papel |
| `tf2price/painel/templates/overview.html` | resumo operacional sem rede |
| `tf2price/painel/templates/new_case.html` | busca e fluxo progressivo de avaliação |
| `tf2price/painel/templates/case_files.html` | página dos pares acompanhados |
| `tf2price/painel/templates/sources.html` | metodologia e estados conhecidos |
| `tf2price/painel/templates/_case_files.html` | linhas/cartões reutilizáveis dos acompanhados |
| `tf2price/painel/templates/_analise.html` | dossiê da avaliação real |
| `tf2price/painel/static/briefcase.css` | tokens, layouts, componentes e responsividade |
| `tf2price/painel/static/briefcase.js` | menu mobile, limpeza HTMX e pausa de animação |
| `tf2price/painel/static/brand/briefcase.svg` | símbolo vetorial aprovado |
| `tf2price/painel/static/fonts/` | quatro famílias WOFF2 locais |
| `tf2price/painel/static/licenses/` | licenças e origem dos assets tipográficos |
| `tests/painel/test_branding.py` | assets, tokens e ausência de fontes externas |
| `tests/painel/test_paginas.py` | rotas, navegação e ausência de rede |
| `tests/painel/test_accessibility.py` | contratos estruturais de acessibilidade |

O arquivo `painel.html` deixa de existir após a migração para `overview.html` e
`new_case.html`. `_acompanhados.html` é substituído por `_case_files.html` somente
depois que todos os includes e respostas OOB forem atualizados na mesma task.

---

### Task 1: Assets locais e rota `/static`

**Files:**
- Create: `tf2price/painel/static/brand/briefcase.svg`
- Create: `tf2price/painel/static/fonts/*.woff2`
- Create: `tf2price/painel/static/licenses/*.txt`
- Create: `tf2price/painel/static/licenses/SOURCES.md`
- Modify: `tf2price/painel/app.py:1-70`
- Modify: `pyproject.toml:22-24`
- Test: `tests/painel/test_branding.py`

**Interfaces:**
- Produces: `STATIC_DIR: Path` e arquivos públicos em `/static/...`.
- Preserves: `/arte/{id}.webp` continua separado e com cache imutável.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/painel/test_branding.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app


def test_assets_da_marca_sao_servidos_sem_sessao(engine):
    cliente = TestClient(criar_app(engine))
    for caminho in (
        "/static/brand/briefcase.svg",
        "/static/fonts/roboto-slab-latin.woff2",
        "/static/fonts/roboto-condensed-latin.woff2",
        "/static/fonts/inter-latin.woff2",
        "/static/fonts/ibm-plex-mono-latin.woff2",
    ):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200, caminho
        assert resposta.content


def test_package_data_inclui_assets_estaticos():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"painel/static/*.css"' in pyproject
    assert '"painel/static/fonts/*.woff2"' in pyproject
    assert '"painel/static/brand/*.svg"' in pyproject
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_branding.py`

Expected: FAIL; `/static/...` devolve 404 e os globs ainda não existem.

- [ ] **Step 3: Adquirir somente os assets aprovados**

Crie os diretórios e copie o SVG aprovado:

```powershell
New-Item -ItemType Directory -Force -Path 'tf2price\painel\static\brand'
New-Item -ItemType Directory -Force -Path 'tf2price\painel\static\fonts'
New-Item -ItemType Directory -Force -Path 'tf2price\painel\static\licenses'
Copy-Item -LiteralPath 'C:\Users\gusco\Desktop\briefcase-tf-branding-completo\briefcase-tf-branding-package\04-prototype\favicon.svg' -Destination 'tf2price\painel\static\brand\briefcase.svg'
```

Baixe uma vez os subconjuntos latinos WOFF2 a partir da API oficial do Google
Fonts. Este comando é etapa de aquisição; os testes e a aplicação não o executam:

```powershell
$fontes = @{
  'roboto-slab-latin.woff2' = 'https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@100..900&display=swap'
  'roboto-condensed-latin.woff2' = 'https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@100..900&display=swap'
  'inter-latin.woff2' = 'https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap'
  'ibm-plex-mono-latin.woff2' = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@100..700&display=swap'
}
$cabecalhos = @{ 'User-Agent' = 'Mozilla/5.0 AppleWebKit/537.36 Chrome/140 Safari/537.36' }
foreach ($entrada in $fontes.GetEnumerator()) {
  $css = (Invoke-WebRequest -Uri $entrada.Value -Headers $cabecalhos).Content
  $bloco = [regex]::Match($css, '(?s)/\* latin \*/\s*@font-face\s*\{.*?url\((?<url>https://fonts\.gstatic\.com/[^)]+\.woff2)\)')
  if (-not $bloco.Success) { throw "Latin WOFF2 not found for $($entrada.Key)" }
  Invoke-WebRequest -Uri $bloco.Groups['url'].Value -OutFile (Join-Path 'tf2price\painel\static\fonts' $entrada.Key)
}
```

Baixe as licenças das fontes para arquivos separados:

```powershell
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/apache/robotoslab/LICENSE.txt' -OutFile 'tf2price\painel\static\licenses\ROBOTO-SLAB.txt'
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/apache/robotocondensed/LICENSE.txt' -OutFile 'tf2price\painel\static\licenses\ROBOTO-CONDENSED.txt'
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/ofl/inter/OFL.txt' -OutFile 'tf2price\painel\static\licenses\INTER.txt'
Invoke-WebRequest 'https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/OFL.txt' -OutFile 'tf2price\painel\static\licenses\IBM-PLEX-MONO.txt'
```

Crie `SOURCES.md` com este conteúdo exato:

```markdown
# Font sources

Retrieved on 2026-09-21 from the official Google Fonts CSS API and stored
locally so the application does not depend on a font CDN at runtime.

- Roboto Slab: `https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@100..900&display=swap`
- Roboto Condensed: `https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@100..900&display=swap`
- Inter: `https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap`
- IBM Plex Mono: `https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@100..700&display=swap`

The corresponding license texts are stored beside this file.
```

- [ ] **Step 4: Montar os assets estáticos**

Em `tf2price/painel/app.py`, importe `Path` e `StaticFiles`, declare o diretório
no nível do módulo e monte-o logo após criar o `FastAPI`:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"


def criar_app(engine: Engine, contexto: "Contexto | None" = None) -> FastAPI:
    app = FastAPI(title="briefcase.tf")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
```

Em `pyproject.toml`, substitua a lista de package data por:

```toml
[tool.setuptools.package-data]
tf2price = [
    "data/*.json",
    "data/efeitos/*.webp",
    "painel/templates/*.html",
    "painel/static/*.css",
    "painel/static/*.js",
    "painel/static/brand/*.svg",
    "painel/static/fonts/*.woff2",
    "painel/static/licenses/*.txt",
    "painel/static/licenses/*.md",
]
```

- [ ] **Step 5: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_branding.py tests\painel\test_arte.py`

Expected: PASS; `/arte` continua verde.

```powershell
git add pyproject.toml tf2price\painel\app.py tf2price\painel\static tests\painel\test_branding.py
git commit -m "Serve localmente os assets da marca briefcase.tf"
```

---

### Task 2: Rotas de página e leitura não bloqueante do índice

**Files:**
- Create: `tf2price/painel/paginas.py`
- Create: `tf2price/painel/templates/overview.html`
- Move: `tf2price/painel/templates/painel.html` → `tf2price/painel/templates/new_case.html`
- Create: `tf2price/painel/templates/case_files.html`
- Create: `tf2price/painel/templates/sources.html`
- Modify: `tf2price/painel/consulta.py:65-112,318-347,528-543`
- Modify: `tf2price/painel/app.py:45-55`
- Modify: `tests/painel/conftest.py:45-52`
- Modify: `tests/painel/test_consulta.py:30-36`
- Test: `tests/painel/test_paginas.py`

**Interfaces:**
- Produces: `IndiceSobDemanda.em_memoria() -> PriceIndex | None` sem I/O.
- Produces: rotas `GET /`, `/cases/new`, `/cases`, `/sources`.
- Consumes: `linhas_acompanhadas(...)` e `idade_por_extenso(...)`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/painel/test_paginas.py`:

```python
from tf2price.painel.consulta import IndiceSobDemanda

from .conftest import _contexto, cliente_logado


class _IndiceSemRede:
    def __init__(self, valor=None):
        self.valor = valor
        self.obter_chamado = False

    def em_memoria(self):
        return self.valor

    def obter(self):
        self.obter_chamado = True
        raise AssertionError("page routes must not call the network-capable obter()")


def test_indice_pode_ser_lido_sem_disparar_cliente():
    class Cliente:
        def currencies(self):
            raise AssertionError("network called")

    indice = IndiceSobDemanda(Cliente())
    assert indice.em_memoria() is None


def test_paginas_autenticadas_existem(engine):
    cliente = cliente_logado(engine, _contexto())
    for caminho, marcador in (
        ("/", 'data-page="overview"'),
        ("/cases/new", 'data-page="new-case"'),
        ("/cases", 'data-page="case-files"'),
        ("/sources", 'data-page="sources"'),
    ):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200
        assert marcador in resposta.text


def test_renderizacao_inicial_das_paginas_nao_chama_indice(engine):
    contexto = _contexto()
    indice = _IndiceSemRede()
    contexto.indice = indice
    cliente = cliente_logado(engine, contexto)

    for caminho in ("/", "/cases/new", "/cases", "/sources"):
        assert cliente.get(caminho).status_code == 200

    assert not indice.obter_chamado
```

Altere `test_raiz_serve_o_formulario` em `test_consulta.py` para esperar
`Overview`; acrescente um teste separado garantindo que `/cases/new` contém o
formulário de busca.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_paginas.py tests\painel\test_consulta.py -k "raiz or paginas or indice_pode"`

Expected: FAIL; método e rotas ainda não existem.

- [ ] **Step 3: Criar a leitura somente em memória**

Em `IndiceSobDemanda`, antes de `obter`, acrescente:

```python
    def em_memoria(self) -> PriceIndex | None:
        """Devolve o índice já aquecido sem trava, espera ou rede.

        A referência é publicada de uma vez por `obter`; ler `None` durante o
        aquecimento é correto para páginas que não podem bloquear.
        """
        return self._indice
```

Faça o primeiro atalho de `obter()` chamar `em_memoria()`. Acrescente o mesmo
método a `_IndiceFalso` em `tests/painel/conftest.py`.

Renomeie `_idade_por_extenso` para `idade_por_extenso` e atualize as chamadas
do próprio módulo; a função passa a ser interface compartilhada com páginas.

- [ ] **Step 4: Criar `paginas.py`**

Implemente a composição sem rede:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.painel import sessao as ses
from tf2price.painel.consulta import idade_por_extenso, linhas_acompanhadas
from tf2price.painel.templates import TEMPLATES

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])


def _estado(request: Request, usuario: Usuario) -> dict:
    contexto = request.app.state.contexto
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    indice = contexto.indice.em_memoria()
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, cotacao, indice, usuario.id, agora)
    return {
        "usuario": usuario,
        "cotacao": cotacao,
        "cotacao_idade": idade_por_extenso(cotacao.buscado_em, agora) if cotacao else None,
        "indice_pronto": indice is not None,
        "linhas": linhas,
    }


@ROTEADOR.get("/", response_class=HTMLResponse)
def overview(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    estado = _estado(request, usuario)
    estado["recentes"] = list(reversed(estado["linhas"]))[:5]
    return TEMPLATES.TemplateResponse(request=request, name="overview.html", context=estado)


@ROTEADOR.get("/cases/new", response_class=HTMLResponse)
def new_case(request: Request, nome: str = "", efeito: str = "",
             usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="new_case.html",
        context={**_estado(request, usuario), "initial_name": nome, "initial_effect": efeito},
    )


@ROTEADOR.get("/cases", response_class=HTMLResponse)
def case_files(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    return TEMPLATES.TemplateResponse(
        request=request, name="case_files.html", context=_estado(request, usuario)
    )


@ROTEADOR.get("/sources", response_class=HTMLResponse)
def sources(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    return TEMPLATES.TemplateResponse(
        request=request, name="sources.html", context=_estado(request, usuario)
    )
```

Mova `painel.html` para `new_case.html` sem alterar o formulário, includes ou
ids. Troque apenas título/cabeçalho para `New Case` e envolva o conteúdo atual em
`<div data-page="new-case">...</div>`.

Os outros três templates iniciais usam esta forma, trocando nome e marcador:

```html
{% extends "base.html" %}
{% block titulo %}Overview · briefcase.tf{% endblock %}
{% block cabecalho %}Overview{% endblock %}
{% block conteudo %}
<div data-page="overview"></div>
{% endblock %}
```

`case_files.html` usa `Case Files`/`case-files`; `sources.html` usa
`Sources`/`sources`. O conteúdo completo entra nas tasks 4 e 7.

- [ ] **Step 5: Ligar o roteador e remover a raiz antiga**

Em `criar_app`, inclua `paginas.ROTEADOR` junto de `consulta.ROTEADOR` quando há
contexto. Remova somente a função `painel()` e o decorator `GET /` de
`consulta.py`; mantenha todos os endpoints HTMX.

- [ ] **Step 6: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_paginas.py tests\painel\test_consulta.py tests\painel\test_sob_demanda.py tests\painel\test_transacao.py`

Expected: PASS e nenhuma chamada externa.

```powershell
git add tf2price\painel tests\painel
git commit -m "Separa paginas completas sem bloquear em fontes externas"
```

---

### Task 3: App shell, marca e navegação responsiva

**Files:**
- Create: `tf2price/painel/templates/auth_base.html`
- Create: `tf2price/painel/templates/_brand.html`
- Create: `tf2price/painel/templates/_navigation.html`
- Create: `tf2price/painel/static/briefcase.css`
- Create: `tf2price/painel/static/briefcase.js`
- Replace: `tf2price/painel/templates/base.html`
- Modify: `tf2price/painel/templates/entrar.html`
- Modify: `tf2price/painel/templates/convite.html`
- Modify: `tf2price/painel/templates/admin.html`
- Modify: `tf2price/painel/templates/overview.html`
- Modify: `tf2price/painel/templates/new_case.html`
- Modify: `tf2price/painel/templates/case_files.html`
- Modify: `tf2price/painel/templates/sources.html`
- Test: `tests/painel/test_branding.py`
- Test: `tests/painel/test_paginas.py`

**Interfaces:**
- Produces: blocos Jinja `title`, `page_title`, `page_eyebrow`, `page_actions`, `content`, `body_attrs`.
- Produces: `data-nav-toggle`, `data-app-nav`, `aria-current="page"` e `body.nav-open`.

- [ ] **Step 1: Acrescentar testes estruturais**

```python
def test_shell_usa_marca_assets_locais_e_ingles(cliente):
    texto = cliente.get("/").text
    assert '<html lang="en">' in texto
    assert "briefcase.tf" in texto
    assert "Unusual Market Intelligence" in texto
    assert "/static/briefcase.css" in texto
    assert "/static/briefcase.js" in texto
    assert "fonts.googleapis.com" not in texto


def test_menu_tem_as_paginas_e_marca_a_atual(cliente):
    texto = cliente.get("/cases/new").text
    for rotulo in ("Overview", "New Case", "Case Files", "Sources", "Administration"):
        assert rotulo in texto
    assert 'href="/cases/new" aria-current="page"' in texto
    assert 'aria-controls="app-navigation"' in texto


def test_administration_link_is_hidden_from_non_admin(engine):
    from fastapi.testclient import TestClient
    from tf2price import db
    from tf2price.contas import repositorio, servico
    from tf2price.painel.app import criar_app
    from .conftest import SENHA, _contexto, cliente_logado

    cliente_logado(engine, _contexto())  # creates the initial administrator
    with engine.begin() as conn:
        admin = repositorio.usuario_por_nome(conn, "gusco")
        token = servico.convidar(conn, criado_por=admin.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome="reader", senha=SENHA, quando=db.agora())
    reader = TestClient(criar_app(engine, _contexto()))
    reader.post("/entrar", data={"nome": "reader", "senha": SENHA})

    assert "Administration" not in reader.get("/").text
```

Use a fixture `cliente` já autenticada ou declare-a com `cliente_logado`.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_branding.py tests\painel\test_paginas.py`

Expected: FAIL; o base atual ainda é português e usa Google Fonts.

- [ ] **Step 3: Criar os partials da marca e navegação**

`_brand.html`:

```html
<a class="brand" href="/" aria-label="briefcase.tf overview">
  <img class="brand__mark" src="/static/brand/briefcase.svg" alt="" width="36" height="36">
  <span class="brand__copy">
    <strong>briefcase.tf</strong>
    <small>Unusual Market Intelligence</small>
  </span>
</a>
```

`_navigation.html` deve comparar `request.url.path` e emitir links nesta ordem:

```html
<nav id="app-navigation" class="app-nav" aria-label="Primary navigation" data-app-nav>
  {% include "_brand.html" %}
  <div class="app-nav__links">
    <a href="/"{% if request.url.path == "/" %} aria-current="page"{% endif %}>Overview</a>
    <a href="/cases/new"{% if request.url.path == "/cases/new" %} aria-current="page"{% endif %}>New Case</a>
    <a href="/cases"{% if request.url.path == "/cases" %} aria-current="page"{% endif %}>Case Files</a>
    <a href="/sources"{% if request.url.path == "/sources" %} aria-current="page"{% endif %}>Sources</a>
    {% if usuario.admin %}
    <a href="/admin"{% if request.url.path == "/admin" %} aria-current="page"{% endif %}>Administration</a>
    {% endif %}
  </div>
  <div class="app-nav__account">
    <span>{{ usuario.nome }}</span>
    <form method="post" action="/sair"><button type="submit">Log out</button></form>
  </div>
</nav>
```

- [ ] **Step 4: Substituir `base.html` e criar `auth_base.html`**

O base autenticado deve ter esta estrutura, mantendo o script HTMX atual com
versão, integrity e crossorigin inalterados:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{% block title %}briefcase.tf{% endblock %}</title>
  <link rel="icon" href="/static/brand/briefcase.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/briefcase.css">
  <script src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"
          integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
          crossorigin="anonymous"></script>
</head>
<body{% block body_attrs %}{% endblock %}>
  <a class="skip-link" href="#main-content">Skip to content</a>
  <button class="nav-toggle" type="button" aria-expanded="false"
          aria-controls="app-navigation" data-nav-toggle>Menu</button>
  <div class="app-shell">
    {% include "_navigation.html" %}
    <main id="main-content" class="app-main" tabindex="-1">
      <header class="page-header">
        <p class="page-header__eyebrow">{% block page_eyebrow %}Black File{% endblock %}</p>
        <h1>{% block page_title %}briefcase.tf{% endblock %}</h1>
        {% block page_actions %}{% endblock %}
      </header>
      {% block content %}{% endblock %}
    </main>
  </div>
  <script src="/static/briefcase.js" defer></script>
</body>
</html>
```

`auth_base.html` usa a mesma folha e favicon, mas não renderiza menu, conta nem
HTMX:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{% block title %}briefcase.tf{% endblock %}</title>
  <link rel="icon" href="/static/brand/briefcase.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/briefcase.css">
</head>
<body class="auth-page">
  <main class="auth-shell">
    {% include "_brand.html" %}
    <section class="auth-card" aria-labelledby="auth-title">
      {% block content %}{% endblock %}
    </section>
  </main>
</body>
</html>
```

Faça `entrar.html` e `convite.html` estenderem `auth_base.html`; cada um declara
`<h1 id="auth-title">` dentro de `content`.

Migre todos os templates de página na mesma alteração: `titulo` → `title`,
`cabecalho` → `page_title`, `conteudo` → `content` e `corpo_attrs` →
`body_attrs`. Remova usos de `subtitulo`; a cotação passa para o conteúdo do
Overview na Task 4. Preserve os quatro atributos `data-page` criados na Task 2.

- [ ] **Step 5: Criar os tokens e o comportamento do menu**

Comece `briefcase.css` com as fontes e tokens exatos:

```css
@font-face { font-family: "Roboto Slab"; src: url("/static/fonts/roboto-slab-latin.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "Roboto Condensed"; src: url("/static/fonts/roboto-condensed-latin.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "Inter"; src: url("/static/fonts/inter-latin.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "IBM Plex Mono"; src: url("/static/fonts/ibm-plex-mono-latin.woff2") format("woff2"); font-weight: 100 700; font-display: swap; }

:root {
  --charcoal: #0E0F10;
  --ink-panel: #15242A;
  --ink-blue: #29424B;
  --active-blue: #365866;
  --paper: #E8E1D1;
  --rust-stamp: #A4453A;
  --warning: #D2A53B;
  --font-display: "Roboto Slab", Georgia, serif;
  --font-condensed: "Roboto Condensed", "Arial Narrow", sans-serif;
  --font-interface: "Inter", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", Consolas, monospace;
  --sidebar-width: 17rem;
}
*, *::before, *::after { box-sizing: border-box; }
html { color-scheme: dark; }
body { margin: 0; min-width: 20rem; background: var(--charcoal); color: var(--paper); font-family: var(--font-interface); }
.app-shell { min-height: 100vh; display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); }
.app-nav { position: sticky; top: 0; height: 100vh; padding: 1.25rem; background: var(--ink-panel); display: flex; flex-direction: column; }
.app-main { min-width: 0; padding: clamp(1rem, 3vw, 3rem); }
.app-nav__links a { min-height: 44px; display: flex; align-items: center; padding: .65rem .75rem; color: var(--paper); text-decoration: none; }
.app-nav__links a[aria-current="page"] { background: var(--active-blue); }
:focus-visible { outline: 3px solid var(--warning); outline-offset: 3px; }
```

Em `briefcase.js`:

```javascript
(() => {
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-app-nav]");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      document.body.classList.toggle("nav-open", open);
    });
  }

  document.addEventListener("visibilitychange", () => {
    document.querySelectorAll(".effect-layer").forEach((layer) => {
      layer.style.animationPlayState = document.hidden ? "paused" : "running";
    });
  });
})();
```

- [ ] **Step 6: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_branding.py tests\painel\test_paginas.py tests\painel\test_admin.py`

```powershell
git add tf2price\painel tests\painel
git commit -m "Cria o app shell e a navegacao briefcase.tf"
```

---

### Task 4: Overview e Sources com estado conhecido, nunca health check

**Files:**
- Modify: `tf2price/painel/templates/overview.html`
- Modify: `tf2price/painel/templates/sources.html`
- Create: `tf2price/painel/templates/_recent_cases.html`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tests/painel/test_paginas.py`
- Modify: `tests/painel/test_transacao.py` se o nome da rota raiz aparecer em comentários/asserts

**Interfaces:**
- Consumes: contexto `_estado` de `paginas.py`.
- Produces: `Overview` com cotação, contagem, recentes e avisos; `Sources` sem probes.

- [ ] **Step 1: Escrever testes de conteúdo e ausência de rede**

```python
def test_overview_mostra_resumo_real_sem_vereditos(cliente):
    texto = cliente.get("/").text
    assert "Overview" in texto
    assert "Exchange rate" in texto
    assert "Case files" in texto
    assert "Recent cases" in texto
    for inventado in ("Good Buy", "Fair Price", "Confidence", "Market Index"):
        assert inventado not in texto


def test_sources_explica_os_dois_escopos(cliente):
    texto = cliente.get("/sources").text
    assert "THIS EFFECT" in texto
    assert "ALL EFFECTS" in texto
    assert "suggested price" in texto
    assert "not a buy order" in texto


def test_sources_nao_afirma_online_sem_evidencia(engine):
    contexto = _contexto()
    contexto.indice = _IndiceSemRede()
    texto = cliente_logado(engine, contexto).get("/sources").text
    assert "Online" not in texto
    assert "Awaiting background load" in texto
```

Adicione um caso acompanhado no teste de Overview e confirme que a contagem e o
par item–efeito aparecem; não teste um número fictício.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_paginas.py`

- [ ] **Step 3: Implementar o `Overview`**

Use apenas os campos do contexto. Estrutura mínima:

```html
{% extends "base.html" %}
{% block title %}Overview · briefcase.tf{% endblock %}
{% block page_eyebrow %}Operational desk{% endblock %}
{% block page_title %}Overview{% endblock %}
{% block page_actions %}<a class="button button--primary" href="/cases/new">Open a new case</a>{% endblock %}
{% block content %}
<div data-page="overview" class="overview-grid">
  <section class="metric-card" aria-labelledby="exchange-title">
    <p class="scope-label">STEAM REFERENCE</p>
    <h2 id="exchange-title">Exchange rate</h2>
    {% if cotacao %}
      <strong>{{ cotacao.key_brl }}</strong>
      <p>Key price · captured {{ cotacao_idade }}</p>
    {% else %}
      <strong>Awaiting evidence</strong>
      <p>The background worker has not loaded a usable quote yet.</p>
    {% endif %}
  </section>
  <section class="metric-card" aria-labelledby="cases-title">
    <p class="scope-label">YOUR FILES</p>
    <h2 id="cases-title">Case files</h2>
    <strong>{{ linhas|length }}</strong>
    <p>Saved item–effect pairs</p>
  </section>
  <section class="dossier overview-recent" aria-labelledby="recent-title">
    <h2 id="recent-title">Recent cases</h2>
    {% include "_recent_cases.html" %}
  </section>
</div>
{% endblock %}
```

Crie `_recent_cases.html` como lista somente de leitura:

```html
{% if recentes %}
<ol class="recent-cases">
  {% for case in recentes %}
  <li>
    <a href="/cases/new?nome={{ case.hash_name|urlencode }}&efeito={{ case.efeito|urlencode }}">
      <strong>{{ case.hash_name }}</strong><span>{{ case.efeito }}</span>
    </a>
    {% if case.idade %}<small>Steam snapshot · {{ case.idade }}</small>{% endif %}
    {% if case.motivo %}<small>{{ case.motivo }}</small>{% endif %}
  </li>
  {% endfor %}
</ol>
{% else %}
<div class="empty-state">
  <strong>No case files yet</strong>
  <a href="/cases/new">Open a new case</a>
</div>
{% endif %}
```

Não inclua formulários mutáveis nesta lista resumida.

- [ ] **Step 4: Implementar `Sources`**

Crie três fichas: Steam Market, backpack.tf e Exchange Rate. Para o índice use
somente `indice_pronto`:

```html
{% extends "base.html" %}
{% block title %}Sources · briefcase.tf{% endblock %}
{% block page_eyebrow %}Evidence provenance{% endblock %}
{% block page_title %}Sources{% endblock %}
{% block content %}
<div data-page="sources" class="sources-grid">
  <section class="source-card">
    <p class="scope-label">THIS EFFECT + ALL EFFECTS</p>
    <h2>Steam Market</h2>
    <p>Steam supplies the item image and listings for the selected effect. Its order book and sales history cover all effects for the item.</p>
    <span class="status-badge">Known through stored case snapshots</span>
    {% if linhas %}
    <ul class="source-evidence-list">
      {% for case in linhas %}
      <li><strong>{{ case.hash_name }} · {{ case.efeito }}</strong><span>{{ case.idade or "Awaiting evidence" }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}
  </section>
  <section class="source-card">
    <p class="scope-label">THIS EFFECT</p>
    <h2>backpack.tf</h2>
    <p>Community suggested prices are effect-specific references, not buy orders.</p>
    <span class="status-badge {{ 'status-badge--ready' if indice_pronto else 'status-badge--waiting' }}">
      {{ "Loaded for this process" if indice_pronto else "Awaiting background load" }}
    </span>
  </section>
  <section class="source-card">
    <p class="scope-label">CONVERSION</p>
    <h2>Exchange Rate</h2>
    {% if cotacao %}<p>{{ cotacao.key_brl }} per key · captured {{ cotacao_idade }}</p>{% else %}<p>Awaiting evidence</p>{% endif %}
  </section>
</div>
<p class="fan-disclaimer">
  briefcase.tf is an independent fan-made project. It is not affiliated with
  Valve, Steam, or backpack.tf.
</p>
{% endblock %}
```

Explique textualmente que listagens são `THIS EFFECT`, livro/histórico são
`ALL EFFECTS`, e que preço sugerido não é oferta. Não inclua botão de refresh
nem chamada HTMX nesta página.

- [ ] **Step 5: Estilizar superfícies sem textura de dados**

Acrescente `.overview-grid`, `.metric-card`, `.dossier`, `.source-card`,
`.status-badge` e `.scope-label`. Papel/textura fica em `.dossier`; métricas e
fontes usam fundos sólidos Ink Panel/Ink Blue. Use:

```css
.overview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.sources-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
.metric-card, .source-card, .evidence-panel { padding: 1.25rem; background: var(--ink-panel); border: 1px solid var(--ink-blue); }
.metric-card strong { display: block; font: 700 clamp(2rem, 5vw, 3.5rem)/1 var(--font-condensed); font-variant-numeric: tabular-nums; }
.dossier { position: relative; padding: 1.5rem; background: var(--paper); color: var(--charcoal); border: 1px solid rgba(14, 15, 16, .3); }
.overview-recent { grid-column: 1 / -1; }
.scope-label, .dossier-id, .source-stamp { font: 500 .72rem/1.3 var(--font-mono); letter-spacing: .1em; text-transform: uppercase; }
.status-badge { display: inline-flex; align-items: center; min-height: 1.75rem; padding: .25rem .5rem; border: 1px solid currentColor; font: 600 .75rem var(--font-condensed); text-transform: uppercase; }
.status-badge--ready { color: var(--paper); }
.status-badge--waiting { color: var(--warning); }
.recent-cases { list-style: none; margin: 0; padding: 0; display: grid; gap: .75rem; }
.recent-cases a { display: flex; flex-direction: column; color: inherit; }
.source-evidence-list { list-style: none; margin: 1rem 0 0; padding: 0; display: grid; gap: .5rem; }
.source-evidence-list li { display: flex; justify-content: space-between; gap: 1rem; font-size: .82rem; }
```

- [ ] **Step 6: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_paginas.py tests\painel\test_transacao.py`

```powershell
git add tf2price\painel tests\painel
git commit -m "Entrega Overview e Sources sem consultas externas"
```

---

### Task 5: New Case, sincronização HTMX e estados em inglês

**Files:**
- Modify: `tf2price/painel/templates/new_case.html`
- Modify: `tf2price/painel/templates/_itens.html`
- Modify: `tf2price/painel/templates/_efeitos.html`
- Modify: `tf2price/painel/templates/_erro.html`
- Modify: `tf2price/painel/static/briefcase.js`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tf2price/painel/consulta.py:114-118,267-270,301-367,394-464`
- Modify: `tests/painel/test_consulta.py`
- Modify: `tests/painel/test_acompanhar.py`

**Interfaces:**
- Produces: `#case-workflow`, `#items`, `#effects`, `#analysis` e atributo `data-case-request`.
- Preserves: endpoints `/buscar`, `/efeitos`, `/analise` e respostas OOB.
- Produces: cancelamento de requisição anterior por `hx-sync="#case-workflow:replace"`.

- [ ] **Step 1: Escrever/atualizar os testes de regressão**

```python
def test_new_case_define_um_unico_grupo_de_sincronizacao(cliente):
    texto = cliente.get("/cases/new").text
    assert 'id="case-workflow"' in texto
    assert 'hx-sync="#case-workflow:replace"' in texto
    assert 'data-case-request="search"' in texto


def test_fragmentos_carregam_identidade_e_limpeza_em_ingles(cliente):
    busca = cliente.get("/buscar", params={"q": "Chairholder"}).text
    assert 'data-case-request="item"' in busca
    assert 'id="effects"' in busca and 'hx-swap-oob="true"' in busca
    assert "Waiting for an item" in busca
    assert "Waiting for an effect" in busca


def test_erro_de_item_limpa_analise_com_estado_ingles(engine):
    contexto = _contexto(paginas=_PaginasFalsas(erro=PageStructureError("renderContext missing")))
    resposta = cliente_logado(engine, contexto).get("/efeitos", params={"nome": NOME})
    assert "Source unavailable" in resposta.text
    assert "Waiting for an effect" in resposta.text
    assert "180,44" not in resposta.text
```

Atualize as asserções portuguesas equivalentes nos testes existentes, sem
remover as provas de limpeza OOB, idade, rate limit e ausência do efeito.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_consulta.py tests\painel\test_acompanhar.py -k "busca_nova or erro_limpa or new_case or fragmentos"`

- [ ] **Step 3: Implementar o esqueleto de `New Case`**

```html
{% extends "base.html" %}
{% block title %}New Case · briefcase.tf{% endblock %}
{% block page_eyebrow %}Case intake{% endblock %}
{% block page_title %}New Case{% endblock %}
{% block body_attrs %} data-case-page{% endblock %}
{% block content %}
<div data-page="new-case" id="case-workflow" class="case-workflow">
  <section class="dossier case-search" aria-labelledby="search-title">
    <p class="dossier-id">FILE / NEW</p>
    <h2 id="search-title">Identify the item</h2>
    <label for="q">Steam Market name</label>
    <input id="q" name="q" autocomplete="off" placeholder="e.g. Chairholder"
           hx-get="/buscar" hx-target="#items" hx-trigger="keyup changed delay:400ms"
           hx-sync="#case-workflow:replace" hx-indicator="#case-loading"
           data-case-request="search">
    <div id="case-loading" class="loading-indicator" role="status" aria-live="polite">
      <span class="loading-bar" aria-hidden="true"></span><span>Loading evidence</span>
    </div>
    <p class="field-help">Partial names work. Strange Unusual quality is preserved; Unusualifier tools are excluded.</p>
    <div id="items" class="choice-list" aria-live="polite"></div>
  </section>
  <section class="dossier" aria-labelledby="effect-title">
    <h2 id="effect-title">Choose the effect</h2>
    <div id="effects" class="choice-list" aria-live="polite"><p class="empty-state">Waiting for an item</p></div>
  </section>
  <section class="analysis-region" aria-labelledby="analysis-title">
    <h2 id="analysis-title" class="visually-hidden">Case analysis</h2>
    <div id="analysis" aria-live="polite"><p class="empty-state">Waiting for an effect</p></div>
  </section>
  <aside class="case-drawer" aria-labelledby="drawer-title">
    <h2 id="drawer-title">Case drawer</h2>
    <div id="acompanhados">{% include "_acompanhados.html" %}</div>
  </aside>
  {% if initial_name and initial_effect %}
  <div class="visually-hidden" hx-get="/efeitos"
       hx-vals='{"nome": {{ initial_name|tojson }}, "efeito": {{ initial_effect|tojson }}}'
       hx-target="#effects" hx-trigger="load" hx-sync="#case-workflow:replace"></div>
  {% endif %}
</div>
{% endblock %}
```

O id e o partial antigos permanecem até Task 7; a troca para `#case-files` e
`_case_files.html` ocorre junto de todos os chamadores para não deixar uma task
intermediária com include inexistente ou alvo HTMX quebrado.

- [ ] **Step 4: Atualizar os fragmentos e ids como uma unidade**

Em `_itens.html`, use OOB para `#effects` e `#analysis`, e dê aos botões:

```html
<button type="button" hx-get="/efeitos"
        hx-vals='{"nome": {{ nome|tojson }}}'
        hx-target="#effects" hx-sync="#case-workflow:replace"
        data-case-request="item">{{ nome }}</button>
```

Em `_efeitos.html`, use `#analysis`, preserve o aviso de efeito ausente e emita
cada escolha assim:

```html
<button type="button" hx-get="/analise"
        hx-vals='{"nome": {{ nome|tojson }}, "efeito": {{ e|tojson }}}'
        hx-target="#analysis" hx-sync="#case-workflow:replace"
        data-case-request="effect"{% if e == efeito_atual %} class="is-selected"{% endif %}>{{ e }}</button>
```

Troque todos os estados vazios por `Waiting for an item`, `Waiting for an effect`,
`No readable effect listings were found` e `No Unusual matches are on sale`.

Em `_erro.html`, use:

```html
<div class="error-state" role="alert">
  <strong>Source unavailable</strong>
  <p>{{ mensagem }}</p>
</div>
```

Quando `limpar_analise`, envie `#analysis` OOB com `Waiting for an effect`.

- [ ] **Step 5: Limpar dependências imediatamente no browser**

Acrescente dentro do IIFE de `briefcase.js`:

```javascript
  const empty = (id, message) => {
    const target = document.getElementById(id);
    if (target) target.innerHTML = `<p class="empty-state">${message}</p>`;
  };

  document.addEventListener("htmx:beforeRequest", (event) => {
    const level = event.detail.elt.dataset.caseRequest;
    if (level === "search") {
      empty("effects", "Waiting for an item");
      empty("analysis", "Waiting for an effect");
    } else if (level === "item") {
      empty("analysis", "Waiting for an effect");
    }
  });

  document.addEventListener("click", (event) => {
    const choice = event.target.closest(".choice-list button");
    if (!choice) return;
    choice.parentElement.querySelectorAll("button").forEach((button) => {
      button.removeAttribute("data-selected");
    });
    choice.setAttribute("data-selected", "");
  });
```

Não injete nomes ou mensagens provenientes do servidor por `innerHTML`; essas
duas strings são literais fixas.

Acrescente o layout do fluxo:

```css
.case-workflow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(16rem, 22rem); gap: 1rem; align-items: start; }
.case-search, .analysis-region { grid-column: 1; }
.case-drawer { grid-column: 2; grid-row: 1 / span 3; position: sticky; top: 1rem; }
.choice-list { display: grid; gap: .5rem; margin-top: 1rem; }
.choice-list button { width: 100%; min-height: 44px; padding: .7rem .8rem; border: 1px solid var(--ink-blue); background: transparent; color: inherit; text-align: left; }
.choice-list button:hover, .choice-list button[data-selected], .choice-list button.is-selected { background: var(--active-blue); }
.loading-indicator { display: none; font: 500 .72rem var(--font-mono); color: var(--warning); }
.loading-indicator.htmx-request { display: grid; gap: .35rem; }
.loading-bar { display: block; height: 2px; background: var(--warning); transform-origin: left; animation: loading-pulse 1.1s ease-in-out infinite; }
@keyframes loading-pulse { 0%, 100% { transform: scaleX(0); } 50% { transform: scaleX(1); } }
.empty-state { color: color-mix(in srgb, var(--paper) 65%, transparent); }
.error-state { padding: 1rem; border: 2px solid var(--rust-stamp); border-left-width: .4rem; }
```

- [ ] **Step 6: Traduzir os estados de apresentação em `consulta.py`**

Use exatamente:

```python
SEM_COTACAO = "The key exchange rate has not loaded yet. Try again in a few minutes."
SEM_RETRATO = "Steam data is unavailable and there is no stored snapshot for this item."
SEM_LISTAGEM_DO_EFEITO = "No listings for this effect in the current snapshot."
```

Em `idade_por_extenso`, devolva `unknown age` e `now`; `min`, `h` e `d` não
mudam. Em `LinhaAcompanhada`, traduza os quatro motivos visíveis para:
`Awaiting evidence`, `Stored snapshot uses an older format; refresh to replace it`,
`No listings for this effect in the current snapshot` e
`This case could not be evaluated`.

- [ ] **Step 7: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_consulta.py tests\painel\test_acompanhar.py tests\painel\test_transacao.py`

```powershell
git add tf2price\painel tests\painel
git commit -m "Organiza o fluxo New Case e elimina estado HTMX antigo"
```

---

### Task 6: Dossiê da análise e separação visual dos escopos

**Files:**
- Replace: `tf2price/painel/templates/_analise.html`
- Modify: `tf2price/painel/templates/_analise_resposta.html`
- Modify: `tf2price/painel/templates/_carimbo_steam.html`
- Modify: `tf2price/painel/templates/_efeitos.html`
- Modify: `tf2price/painel/templates.py`
- Modify: `tf2price/lookup/analysis.py:18-29,160-171`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tests/painel/test_consulta.py`

**Interfaces:**
- Consumes: `Analysis`, `arte`, `chapeu`, `retrato_idade`, `retrato_limitando`.
- Produces: cinco painéis com rótulos `THIS EFFECT`, `ALL EFFECTS` e o cruzamento explícito.

- [ ] **Step 1: Escrever os testes de conteúdo honesto**

```python
def test_analysis_uses_approved_scope_headings(cliente):
    texto = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text
    for titulo in ("Purchase Price", "Active Listings", "Immediate Exit", "Patient Exit", "Item Context"):
        assert titulo in texto
    assert texto.count("THIS EFFECT") >= 3
    assert texto.count("ALL EFFECTS") >= 2
    assert "THIS EFFECT × ALL EFFECTS" in texto


def test_analysis_does_not_invent_a_verdict(cliente):
    texto = cliente.get("/analise", params={"nome": NOME, "efeito": "Deep Dive"}).text
    for inventado in ("Good Buy", "Fair Price", "Caution", "Confidence"):
        assert inventado not in texto


def test_missing_art_fallback_is_declared_in_english(engine, tmp_path, monkeypatch):
    from tf2price.efeitos import arte
    monkeypatch.setattr(arte, "DIRETORIO", tmp_path)
    texto = cliente_logado(engine, _contexto()).get(
        "/analise", params={"nome": NOME, "efeito": "Deep Dive"}
    ).text
    assert 'class="effect-layer"' not in texto
    assert "Effect artwork unavailable" in texto
```

Mantenha os testes existentes da foto real, arte real, idades independentes,
efeito ausente e ausência de preço.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_consulta.py -k "scope_headings or verdict or missing_art"`

- [ ] **Step 3: Acrescentar o filtro inglês de keys**

Em `templates.py`:

```python
def _keys(value: float) -> str:
    return f"{value:.1f}"


TEMPLATES.env.filters["keys"] = _keys
```

Migre os novos templates para `|keys`; preserve `|chaves` temporariamente até
nenhum template antigo usá-lo.

- [ ] **Step 4: Reestruturar `_analise.html`**

O artigo raiz deve identificar a seleção:

```html
<article class="case-dossier" data-item-name="{{ a.hash_name }}" data-effect-name="{{ a.effect }}">
  <header class="case-dossier__header">
    <p class="dossier-id">CASE / {{ a.hash_name|upper }}</p>
    <h2>{{ a.effect }}</h2>
    <p>{{ a.hash_name }}</p>
    {% include "_carimbo_steam.html" %}
  </header>
  <div class="evidence-visual">
    {% if arte %}
      <img class="effect-layer" src="{{ arte }}" alt="" aria-hidden="true">
      <img class="effect-layer" src="{{ arte }}" alt="" aria-hidden="true">
      <img class="effect-layer" src="{{ arte }}" alt="" aria-hidden="true">
    {% endif %}
    {% if chapeu %}<img class="item-image" src="{{ chapeu }}" alt="{{ a.hash_name }}">{% endif %}
    {% if not arte %}<p class="effect-fallback"><strong>{{ a.effect }}</strong><span>Effect artwork unavailable</span></p>{% endif %}
  </div>
```

Depois, crie exatamente estes painéis e feche o artigo:

```html
  <div class="evidence-grid">
    <section class="evidence-panel" data-scope="effect">
      <p class="scope-label">THIS EFFECT</p>
      <h3>Purchase Price</h3>
      <strong class="evidence-price">{{ a.cheapest.total_price }}</strong>
      <p>{{ a.price_in_keys|keys }} keys · cheapest listing for this effect</p>
      <form hx-post="/acompanhar" hx-target="#acompanhados">
        <input type="hidden" name="nome" value="{{ a.hash_name }}">
        <input type="hidden" name="efeito" value="{{ a.effect }}">
        <button type="submit" class="button button--primary">Save Case</button>
      </form>
    </section>

    <section class="evidence-panel" data-scope="effect">
      <p class="scope-label">THIS EFFECT</p>
      <h3>Active Listings</h3>
      {% for listing in a.listings %}
      <div class="evidence-row">
        <span>{{ "Only listing" if a.listings|length == 1 else "Listing " ~ loop.index }}</span>
        <strong>{{ listing.total_price }}</strong>
        <small>{{ (listing.total_price.cents / a.key_brl.cents)|keys }} keys</small>
      </div>
      {% endfor %}
      <p class="evidence-note">
        <a href="https://steamcommunity.com/market/listings/440/{{ a.hash_name|urlencode }}">Open on Steam</a>.
        Steam groups every effect on one page; verify the effect before buying.
      </p>
    </section>

    <section class="evidence-panel" data-scope="crossed">
      <p class="scope-label">THIS EFFECT × ALL EFFECTS</p>
      <h3>Immediate Exit</h3>
      {% if a.immediate.top_bid %}
      <div class="evidence-row"><span>Highest buy order · {{ a.immediate.buy_orders }} orders</span><strong>{{ a.immediate.top_bid }}</strong></div>
      <div class="evidence-row"><span>Net after Steam fee</span><strong>{{ a.immediate.net_received }}</strong></div>
      <div class="evidence-row evidence-row--total"><span>Result</span><strong>{{ a.immediate.result }}</strong></div>
      <p class="evidence-note">The purchase is specific to this effect. The buy order covers all effects for the item.</p>
      {% else %}
      <p class="empty-state">No open buy order exists for this item.</p>
      {% endif %}
    </section>

    <section class="evidence-panel" data-scope="effect">
      <p class="scope-label">THIS EFFECT</p>
      <h3>Patient Exit</h3>
      {% if a.patient.available %}
      <p class="source-stamp">backpack.tf · {{ a.patient.age_days }} days old</p>
      <div class="evidence-row"><span>Suggested value · {{ a.patient.keys|keys }} keys</span><strong>{{ a.patient.fair_value }}</strong></div>
      <div class="evidence-row evidence-row--total"><span>Result</span><strong>{{ a.patient.result }}</strong></div>
      <p class="evidence-note">Suggested price, not a buy order. No buyer has committed to pay this value.</p>
      {% else %}
      <p class="source-stamp">backpack.tf · Insufficient Data</p>
      <p>{{ a.patient.reason }}.</p>
      <p class="evidence-note">A different effect price is never substituted here.</p>
      {% endif %}
    </section>

    <section class="evidence-panel" data-scope="aggregate">
      <p class="scope-label">ALL EFFECTS</p>
      <h3>Item Context</h3>
      <p class="evidence-note">Steam does not split these figures by effect.</p>
      <div class="evidence-row"><span>Lowest sell order</span><strong>{{ a.orderbook.min_sell_order }}</strong></div>
      <div class="evidence-row"><span>Highest buy order</span><strong>{{ a.orderbook.max_buy_order }}</strong></div>
      <div class="evidence-row"><span>Open orders</span><strong>{{ a.orderbook.buy_orders }} buy · {{ a.orderbook.sell_orders }} sell</strong></div>
      {% if a.history_median %}
      <div class="evidence-row"><span>History median · {{ a.history_purchases }} sales</span><strong>{{ a.history_median }}</strong></div>
      {% endif %}
    </section>
  </div>
</article>
```

Os cálculos continuam vindos de `Analysis`; a única divisão no template é a
conversão visual de cada listagem para keys que já existe hoje. O formulário
continua enviando `nome` e `efeito` juntos. Task 7 troca seu alvo de
`#acompanhados` para `#case-files` junto com a migração do partial.

- [ ] **Step 5: Traduzir razões puras sem mudar a regra**

Em `lookup/analysis.py`, altere somente o texto:

```python
RAZAO_EFEITO_DESCONHECIDO = (
    "the effect is not in the Valve schema map, so it cannot be matched on backpack.tf"
)
RAZAO_SEM_PRECO = "backpack.tf does not price this effect for this item"
RAZAO_SEM_INDICE = (
    "the backpack.tf price index has not loaded yet; try again in a few minutes"
)
```

O `ValueError` de `analyse` vira
`No listings for effect {effect!r} in this snapshot`. Atualize apenas testes que
afirmam a mensagem; testes numéricos e de identidade não mudam.

- [ ] **Step 6: Preservar os carimbos e movimento reais**

Traduza `_carimbo_steam.html` para `snapshot`, `Steam rate limited` e a idade
existente. Use este bloco para preservar as três fases reais:

```css
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.evidence-panel[data-scope="effect"] { border-top: 3px solid var(--paper); }
.evidence-panel[data-scope="crossed"] { border-top: 3px solid var(--warning); }
.evidence-panel[data-scope="aggregate"] { border-top: 3px double var(--active-blue); }
.evidence-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .75rem; align-items: baseline; padding: .45rem 0; border-bottom: 1px dotted var(--ink-blue); }
.evidence-row strong, .evidence-price { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.evidence-row--total { margin-top: .5rem; border-top: 1px solid var(--paper); border-bottom: 0; }
.evidence-note { max-width: 58ch; color: color-mix(in srgb, var(--paper) 70%, transparent); }
.evidence-visual { position: relative; min-height: 16rem; overflow: hidden; background: var(--charcoal); }
.item-image { position: absolute; z-index: 2; left: 50%; top: 55%; width: min(11rem, 42vw); transform: translate(-50%, -50%); filter: drop-shadow(0 1rem 1.5rem rgba(0, 0, 0, .7)); }
.effect-layer { position: absolute; left: 50%; top: 52%; width: 13rem; height: 13rem; transform: translate(-50%, -50%); mix-blend-mode: screen; pointer-events: none; animation: evidence-emission 3.6s linear infinite; }
.effect-layer:nth-of-type(2) { width: 10rem; height: 10rem; animation-delay: -2.4s; }
.effect-layer:nth-of-type(3) { width: 15rem; height: 15rem; animation-delay: -1.2s; opacity: .5; }
@keyframes evidence-emission {
  0% { transform: translate(-50%, -32%) scale(.8); opacity: 0; }
  20% { opacity: .95; }
  100% { transform: translate(-50%, -74%) scale(1.18); opacity: 0; }
}
.source-stamp { color: var(--warning); font-family: var(--font-mono); text-transform: uppercase; }
.error-state, .status-badge--error, .button--danger { color: var(--rust-stamp); }
```

Rust Stamp fica em erro/limitação/destruição; Warning fica em stale. Não crie
verde que implique aprovação comercial.

- [ ] **Step 7: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\lookup tests\painel\test_consulta.py tests\painel\test_acompanhar.py`

```powershell
git add tf2price\lookup tf2price\painel tests
git commit -m "Transforma a avaliacao em um dossie de evidencias"
```

---

### Task 7: Case Files e ações seguras

**Files:**
- Replace: `tf2price/painel/templates/case_files.html`
- Create: `tf2price/painel/templates/_case_files.html`
- Modify: `tf2price/painel/templates/new_case.html`
- Modify: `tf2price/painel/templates/_analise_resposta.html`
- Modify: `tf2price/painel/templates/_efeitos.html`
- Modify: `tf2price/painel/consulta.py:546-693`
- Modify: `tf2price/painel/templates.py`
- Delete: `tf2price/painel/templates/_acompanhados.html`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tests/painel/test_acompanhar.py`
- Modify: `tests/painel/test_consulta.py`

**Interfaces:**
- Produces: invólucro estável `#case-files`; respostas de salvar/remover/atualizar usam o mesmo partial.
- Preserves: chave `(usuario_id, hash_name, efeito)` e isolamento por usuário.

- [ ] **Step 1: Escrever testes da página e dos controles**

```python
def test_case_files_lists_saved_pair_with_real_age(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    texto = cliente.get("/cases").text
    assert NOME in texto and "Deep Dive" in texto
    assert "Open case" in texto
    assert "Refresh evidence" in texto
    assert "Remove case" in texto


def test_open_case_keeps_item_and_effect_together(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    texto = cliente.get("/cases").text
    assert "/cases/new?nome=" in texto
    assert "efeito=Deep%20Dive" in texto or "efeito=Deep+Dive" in texto


def test_remove_case_requires_explicit_confirmation(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    texto = cliente.get("/cases").text
    assert 'hx-confirm="Remove this case file?"' in texto


def test_saving_a_case_does_not_load_the_price_index(engine):
    class IndexAlreadyUnknown:
        def em_memoria(self):
            return None

        def obter(self):
            raise AssertionError("saving a case must not load backpack.tf")

    contexto = _contexto()
    contexto.indice = IndexAlreadyUnknown()
    resposta = cliente_logado(engine, contexto).post(
        "/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"}
    )
    assert resposta.status_code == 200
```

Atualize os testes OOB para esperar exatamente um `id="case-files"`, nunca um
invólucro aninhado.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_acompanhar.py -k "case_files or open_case or confirmation or aninhar"`

- [ ] **Step 3: Criar `_case_files.html`**

Use o partial completo:

```html
{% if linhas %}
<div class="case-files-list">
{% for l in linhas %}
<article class="case-file{% if l.selecionado %} case-file--selected{% endif %}">
  <div class="case-file__identity">
    <p class="case-file__item">{{ l.hash_name }}</p>
    <p class="case-file__effect">{{ l.efeito }}</p>
  </div>
  <div class="case-file__evidence">
    {% if l.preco %}<strong>{{ l.preco }}</strong>{% else %}<strong>Insufficient Data</strong><p>{{ l.motivo }}</p>{% endif %}
    {% if l.idade %}<small>Steam snapshot · {{ l.idade }}{% if l.premio %} · backpack.tf reference · {{ l.premio_idade }}{% endif %}</small>{% endif %}
  </div>
  <div class="case-file__actions">
    <a class="button button--quiet" href="/cases/new?nome={{ l.hash_name|urlencode }}&efeito={{ l.efeito|urlencode }}">Open case</a>
    <form hx-post="/atualizar/{{ l.hash_name|urlencode }}" hx-target="#case-files">
      <button type="submit" class="button button--quiet">Refresh evidence</button>
    </form>
    <form hx-delete="/acompanhar/{{ l.id }}" hx-target="#case-files" hx-confirm="Remove this case file?">
      <button type="submit" class="button button--danger">Remove case</button>
    </form>
  </div>
</article>
{% endfor %}
</div>
{% else %}
<div class="empty-state">
  <strong>No case files yet</strong>
  <a class="button button--primary" href="/cases/new">Open a new case</a>
</div>
{% endif %}
```

`case_files.html` é a página completa:

```html
{% extends "base.html" %}
{% block title %}Case Files · briefcase.tf{% endblock %}
{% block page_eyebrow %}Evidence archive{% endblock %}
{% block page_title %}Case Files{% endblock %}
{% block page_actions %}<a class="button button--primary" href="/cases/new">Open a new case</a>{% endblock %}
{% block content %}
<section data-page="case-files" aria-labelledby="case-files-title">
  <h2 id="case-files-title" class="visually-hidden">Saved item and effect pairs</h2>
  <div id="case-files">{% include "_case_files.html" %}</div>
</section>
{% endblock %}
```

- [ ] **Step 4: Atualizar os alvos e respostas OOB atomicamente**

Troque `_coluna` para renderizar `_case_files.html`. Em
`_analise_resposta.html` e `_efeitos.html`, emita:

```html
<div id="case-files" hx-swap-oob="true">
  {% include "_case_files.html" %}
</div>
```

Em `new_case.html` e `case_files.html`, o include fica dentro de um único
`<div id="case-files">`. Só então remova `_acompanhados.html`.
Como nenhum template restante usa `|chaves`, remova `_chaves` e o registro
`TEMPLATES.env.filters["chaves"]` de `templates.py`; `|keys` permanece.

Acrescente ao CSS:

```css
.case-files-list { display: grid; gap: .75rem; }
.case-file { display: grid; grid-template-columns: minmax(12rem, 1.4fr) minmax(11rem, 1fr) auto; gap: 1rem; align-items: center; padding: 1rem; background: var(--ink-panel); border: 1px solid var(--ink-blue); }
.case-file--selected { border-color: var(--warning); }
.case-file__item { margin: 0; font-family: var(--font-display); }
.case-file__effect { margin: .25rem 0 0; font-family: var(--font-mono); }
.case-file__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .5rem; }
.case-file__actions form { margin: 0; }
.button { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: .65rem .9rem; border: 1px solid currentColor; font: 700 .85rem var(--font-condensed); text-transform: uppercase; text-decoration: none; cursor: pointer; }
.button--primary { background: var(--rust-stamp); color: var(--paper); }
.button--quiet { background: transparent; color: var(--paper); }
.button--danger { background: transparent; color: var(--rust-stamp); }
```

- [ ] **Step 5: Manter as ações e segurança existentes**

Não mude os decorators de mesma origem nem os filtros por usuário. O POST de
save, DELETE e refresh continuam abrindo transações curtas, terminando-as antes
de qualquer leitura que possa buscar rede. Troque `_coluna` para usar
`contexto.indice.em_memoria()`; salvar e remover não podem iniciar o download do
índice. `Refresh evidence` pode fazer I/O externo pelo caminho existente, mas
sem conexão emprestada; a montagem da lista depois dele continua só em memória
e banco.

- [ ] **Step 6: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_acompanhar.py tests\painel\test_transacao.py tests\painel\test_consulta.py`

```powershell
git add -A
git commit -m "Reune os acompanhados em Case Files"
```

---

### Task 8: Autenticação, convites e administração em inglês

**Files:**
- Modify: `tf2price/painel/acesso.py`
- Modify: `tf2price/painel/admin.py`
- Modify: `tf2price/painel/app.py:34-46`
- Modify: `tf2price/painel/sessao.py:65-77`
- Modify: `tf2price/sources/steam_page.py:100-175,310-347`
- Modify: `tf2price/sources/steam.py:45-48,260-323,395-409`
- Modify: `tf2price/painel/templates/entrar.html`
- Modify: `tf2price/painel/templates/convite.html`
- Replace: `tf2price/painel/templates/admin.html`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tf2price/painel/static/briefcase.js`
- Modify: `tests/painel/test_entrar.py`
- Modify: `tests/painel/test_convite.py`
- Modify: `tests/painel/test_admin.py`
- Test: `tests/painel/test_english_ui.py`

**Interfaces:**
- Produces: `_account_error_message(error: Exception) -> str` em `acesso.py`.
- Preserves: respostas neutras, status codes, cookies, consumo atômico e autorização.

- [ ] **Step 1: Escrever os testes de segurança e idioma**

```python
def test_login_error_is_neutral_and_english(cliente):
    resposta = cliente.post("/entrar", data={"nome": "missing", "senha": "wrong password"})
    assert "Incorrect username or password" in resposta.text
    assert "missing" not in resposta.text


def test_dead_invites_remain_indistinguishable_in_english(cliente, engine):
    inexistente = cliente.get("/convite/not-a-token")
    expirado = cliente.get(f"/convite/{_convite(engine, validade=timedelta(seconds=-1))}")
    assert inexistente.status_code == expirado.status_code == 404
    assert inexistente.text == expirado.text == "This invitation is no longer valid."


def test_admin_copy_is_english(admin):
    texto = admin.get("/admin").text
    for rotulo in ("Administration", "Generate invitation", "People", "Reset password"):
        assert rotulo in texto
    assert 'data-confirm="Disable this account and invalidate its sessions?"' in texto
```

Crie `test_english_ui.py`:

```python
import pytest
from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app

from .conftest import _contexto, cliente_logado

PORTUGUESE_UI = ("Entrar", "Administração", "Avaliação", "Acompanhados", "aguardando")


def test_public_login_has_no_old_portuguese_copy(engine):
    texto = TestClient(criar_app(engine, _contexto())).get("/entrar").text
    assert all(word not in texto for word in PORTUGUESE_UI)


@pytest.mark.parametrize("path", ["/", "/cases/new", "/cases", "/sources", "/admin"])
def test_authenticated_pages_have_no_old_portuguese_copy(engine, path):
    texto = cliente_logado(engine, _contexto()).get(path).text
    assert all(word not in texto for word in PORTUGUESE_UI)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_entrar.py tests\painel\test_convite.py tests\painel\test_admin.py tests\painel\test_english_ui.py`

- [ ] **Step 3: Mapear erros de conta na borda HTTP**

Em `acesso.py`:

```python
def _account_error_message(error: Exception) -> str:
    if isinstance(error, servico.CredenciaisInvalidas):
        return "Incorrect username or password."
    if isinstance(error, servico.ContaBloqueada):
        return "Too many attempts. Wait a few minutes before trying again."
    if isinstance(error, servico.ContaInativa):
        return "This account is disabled."
    if isinstance(error, SenhaCurta):
        return "Password must contain at least 10 characters."
    if isinstance(error, servico.NomeEmUso):
        mensagens = {
            "escolha um nome": "Choose a username.",
            "esse nome já está em uso": "That username is already in use.",
        }
        texto = str(error)
        if texto.startswith("esse nome é longo demais"):
            return "Username is too long. The maximum is 60 characters."
        return mensagens.get(texto, "The account could not be created.")
    return "The request could not be completed."
```

Use esse helper nos dois `TemplateResponse` de erro. Não altere mensagens
internas do domínio nem exponha `str(error)` desconhecido.

- [ ] **Step 4: Traduzir respostas HTTP e templates**

Use exatamente:

- convite morto: `This invitation is no longer valid.`;
- 403 admin: `This page is restricted to administrators.`;
- usuário inexistente: `User not found.`;
- autodesativação: `You cannot disable your own account.`.

Login usa `Username`, `Password`, `Sign in` e a frase
`This is an invitation-only workspace.`. Convite usa `Create account` ou
`Set a new password`, mantendo `autocomplete`, `minlength=10` e autofocus.

Admin usa `Generate invitation`, `The link is shown once. Copy it now.`,
`People`, `Reset password`, `Disable` e `Reactivate`. Não mude nenhum action,
campo oculto ou condição `u.id != usuario.id`. No formulário que desativa uma
conta ativa, acrescente
`data-confirm="Disable this account and invalidate its sessions?"`; não use o
atributo na reativação.

Acrescente ao IIFE de `briefcase.js`:

```javascript
  document.addEventListener("submit", (event) => {
    const message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });
```

- [ ] **Step 5: Traduzir diagnósticos que podem chegar à tela**

Altere somente o texto das exceções, sem tocar em tipos, catches, backoff ou
rate limiter. Em `steam_page.py`, use as seguintes formas:

```python
raise PageStructureError(f"unexpected price format: {text!r}")
raise PageStructureError(f"{RENDER_CONTEXT_MARKER!r} was not found on the Steam page")
raise PageStructureError("renderContext is not a JSON string")
raise PageStructureError(f"renderContext could not be decoded: {erro}")
raise PageStructureError("renderContext.queryData is missing or is not a string")
raise PageStructureError(f"queryData could not be decoded: {erro}")
raise PageStructureError(f"query {fragmento!r} is missing from the page renderContext")
raise PageStructureError(
    f"{parte} uses currency {moeda!r}; expected "
    f"{CURRENCY_USD} (USD) or {CURRENCY_BRL} (BRL)"
)
```

As duas falhas finais do cliente de página usam:

```python
raise classe(f"Steam rejected the request: {mensagem_saneada(erro)}") from erro
mensagem = f"Steam did not respond after backoff (last result: {ultimo})"
```

Em `steam.py`, traduza `_LISTINGS_NOT_JSON` para
`Steam listings endpoint did not return JSON; per-listing effect and craftability data cannot be resolved`.
Use `Steam is rate limiting this server; try again in a few minutes` nos dois
caminhos de calma/429 e
`Steam did not respond after backoff (last result: {last_reason})` no erro final.
Preserve `last_reason`, status HTTP e nomes técnicos. Em `sessao.py`, o detail
403 vira `request origin does not match`.

Atualize somente as asserções textuais em `tests/sources/test_steam.py`,
`tests/sources/test_steam_page.py`, `tests/painel/test_terceiros.py` e testes de
rota afetados. Nenhum teste novo faz rede.

- [ ] **Step 6: Verificar e commitar**

Run: `.\.venv\Scripts\python.exe -m pytest tests\sources tests\painel\test_entrar.py tests\painel\test_convite.py tests\painel\test_admin.py tests\painel\test_terceiros.py tests\painel\test_english_ui.py`

```powershell
git add tf2price\painel tf2price\sources tests
git commit -m "Traduz autenticacao e administracao sem enfraquecer seguranca"
```

---

### Task 9: Acessibilidade, responsividade, documentação e verificação final

**Files:**
- Create: `tests/painel/test_accessibility.py`
- Modify: `tf2price/painel/static/briefcase.css`
- Modify: `tf2price/painel/static/briefcase.js`
- Modify: templates identificados pelos testes
- Modify: `README.md`

**Interfaces:**
- Produces: comportamento a 400 px, foco visível, menu acessível e redução de movimento.
- Preserves: todos os contratos funcionais das tasks anteriores.

- [ ] **Step 1: Escrever os contratos estruturais que falham**

```python
from pathlib import Path


def test_pages_have_skip_link_landmark_and_current_navigation(cliente):
    texto = cliente.get("/cases").text
    assert 'href="#main-content"' in texto
    assert 'id="main-content"' in texto
    assert 'aria-current="page"' in texto


def test_dynamic_regions_and_forms_are_labelled(cliente):
    texto = cliente.get("/cases/new").text
    assert 'for="q"' in texto
    assert texto.count('aria-live="polite"') >= 2
    assert 'aria-labelledby="analysis-title"' in texto


def test_css_contains_responsive_and_reduced_motion_contracts():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    assert "@media (max-width: 48rem)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "min-height: 44px" in css
    assert ":focus-visible" in css
    assert "overflow-x: hidden" not in css


def test_mobile_menu_has_escape_and_focus_return():
    javascript = Path("tf2price/painel/static/briefcase.js").read_text(encoding="utf-8")
    assert 'event.key === "Escape"' in javascript
    assert "toggle.focus()" in javascript
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_accessibility.py`

- [ ] **Step 3: Fechar responsividade e movimento**

Acrescente ao CSS:

```css
.nav-toggle { display: none; min-width: 44px; min-height: 44px; }
.button, button, input, select { min-height: 44px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

@media (max-width: 48rem) {
  .nav-toggle { display: inline-flex; position: fixed; z-index: 30; top: .75rem; right: .75rem; }
  .app-shell { display: block; }
  .app-nav { position: fixed; z-index: 20; inset: 0 0 0 auto; width: min(21rem, 88vw); height: 100dvh; transform: translateX(100%); transition: transform 200ms ease; }
  .nav-open .app-nav { transform: translateX(0); }
  .app-main { padding-top: 4.5rem; }
  .overview-grid, .case-workflow, .evidence-grid { grid-template-columns: 1fr; }
  .case-file { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
}
```

Garanta que tabelas indispensáveis usem um wrapper com `role="region"`,
`tabindex="0"` e nome acessível. Em 400 px, prefira cartões para Case Files.

Substitua o trecho de menu em `briefcase.js` por uma função de fechamento única,
para que Escape devolva o foco ao controle:

```javascript
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-app-nav]");
  if (toggle && nav) {
    const setOpen = (open, restoreFocus = false) => {
      toggle.setAttribute("aria-expanded", String(open));
      document.body.classList.toggle("nav-open", open);
      if (!open && restoreFocus) toggle.focus();
    };
    toggle.addEventListener("click", () => {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && document.body.classList.contains("nav-open")) {
        setOpen(false, true);
      }
    });
    nav.addEventListener("click", (event) => {
      if (event.target.closest("a") && window.matchMedia("(max-width: 48rem)").matches) {
        setOpen(false);
      }
    });
  }
```

- [ ] **Step 4: Atualizar o README**

Substitua o nome público e a descrição da UI sem alterar comandos operacionais.
Documente:

```markdown
## Product interface

The web product is named **briefcase.tf — Unusual Market Intelligence**.
Its interface is in English and separates evidence for `THIS EFFECT` from
Steam context for `ALL EFFECTS`. It is an independent fan-made project and is
not affiliated with Valve, Steam, or backpack.tf.

Authenticated navigation: `Overview`, `New Case`, `Case Files`, `Sources`, and
`Administration` for administrators.
```

Mantenha o comando Railway, variáveis e instruções de ambiente atuais.

- [ ] **Step 5: Rodar a suíte focada e a suíte inteira**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\painel
.\.venv\Scripts\python.exe -m pytest
git diff --check
```

Expected: `413+ passed`, somente warnings de dependências já conhecidos, e
nenhum erro de whitespace.

- [ ] **Step 6: Fazer QA visual contra as referências aprovadas**

Suba a aplicação:

```powershell
.\.venv\Scripts\python.exe -m tf2price.painel.app
```

Compare no browser com `02-ui-approved/03-login.png` até
`02-ui-approved/08-insufficient-data.png`, nos viewports 1440×900, 768×1024 e
400×850. Verifique:

- sidebar desktop e menu mobile sem corte;
- hierarquia Slab/Condensed/Inter/Mono;
- Paper somente em dossiers e framing;
- superfícies de dados limpas;
- `THIS EFFECT` e `ALL EFFECTS` sempre legíveis;
- item e efeito reais, inclusive fallback sem arte;
- foco por teclado e retorno de foco ao fechar menu;
- loading, vazio, stale, rate limited e erro sem conteúdo antigo residual;
- zero scroll horizontal da página em 400 px;
- animação pausada com aba oculta e reduzida pelo sistema.

Não aceite como solução dados fictícios do protótipo para preencher uma tela
vazia. Corrija somente CSS/markup; se o QA revelar mudança de regra, pare e
volte à spec.

- [ ] **Step 7: Revisar o diff e commitar**

```powershell
git status --short
git diff --stat
git diff --check
git add README.md tf2price\painel tests\painel
git commit -m "Conclui o redesign acessivel do briefcase.tf"
```

Confirme antes do commit que `.env`, banco local, caches, screenshots de QA e
mockups externos não entraram no índice.

---

## Spec Coverage

| Requisito da spec | Task |
|---|---|
| marca, paleta, tipografia local e símbolo | 1 e 3 |
| app shell e menu por papel | 3 |
| rotas `Overview`, `New Case`, `Case Files`, `Sources` | 2 |
| Overview e Sources sem rede | 2 e 4 |
| fluxo item → efeito → análise | 5 |
| limpeza HTMX e resposta atrasada | 5 |
| dossiê e escopos honestos | 6 |
| imagem/arte reais e fallback tipográfico | 6 |
| acompanhamento como Case Files, sem novo modelo | 7 |
| autenticação, convite e admin preservados | 8 |
| interface pública em inglês | 5, 6, 7 e 8 |
| responsividade, teclado, contraste e reduced motion | 9 |
| README, suíte completa e diff auditado | 9 |

## Stop Conditions

- Se qualquer página inicial precisar chamar `IndiceSobDemanda.obter()`, não
  faça a chamada: use `em_memoria()` e mostre estado desconhecido.
- Se um mockup exigir dado que o backend não possui, mostre `Insufficient Data`;
  não acrescente estimativa.
- Se a Steam não separar um número por efeito, rotule-o `ALL EFFECTS`.
- Se um efeito estiver sem preço ou listagem, não procure substituto.
- Se uma alteração exigir migração de banco, novo source client ou mudança de
  cálculo, pare: ela está fora desta spec e precisa de desenho próprio.
