# Market Scan Honest Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current guide-price comparison honest and give each scanned item–effect pair a direct path to inspect seller listings, while establishing whether automated seller quotes are accessible.

**Architecture:** The existing `patient_exit` calculation remains the guide-price difference. A pure URL helper maps a scanned unusual to a backpack.tf classifieds search for its exact effect. The scan templates name the guide as a suggestion and the difference as a guide gap. A bounded, read-only source probe decides whether a second implementation plan can add live seller quotes; until then no row is called a resale opportunity.

**Tech Stack:** Python 3.12+, FastAPI, Jinja/HTMX, SQLAlchemy Core, pytest, PowerShell.

## Global Constraints

- The economic identity is item plus effect; never substitute another effect's quote.
- The current scan covers ordinary Unusual cosmetics only; do not expand its scope to Strange Unusual, taunts, weapons, war paints, or Unusualifiers.
- The reference key uses the backpack.tf dollar value times BCB PTAX sell rate; do not use the Steam key price for trade calculations.
- Keep amounts as `Brl` integer cents and database instants as naive UTC.
- Keep `/scan` free of new remote calls. No import or test may use the network.
- Do not hold a database connection during HTTP, rate-limit waits, or backoff.
- Preserve existing Steam scan pacing, 429 handling, and one-production-replica assumption.
- Preserve existing work and local `.env` credentials. The probe never prints tokens, request URLs, or full responses.
- User-facing scan copy stays in English.

---

## Scope boundary

This plan delivers the safe behavior that is possible with the data and credentials currently configured in the repository. It does **not** label the guide gap as `Potential resale`: that label requires an actual, recent seller listing for the same item and effect. The approved [design](../specs/2026-09-23-market-scan-vendas-por-efeito-design.md) describes the automated collector. The public API currently answers 401 without a user token; its seller-listing response shape and usable rate limit have not been verified. Task 3 records that capability. If it is available, write the follow-on collector plan against the observed contract. If it is unavailable, this plan's UI and manual seller link are the approved fallback, with no invented quote.

## File map

| File | Responsibility |
| --- | --- |
| `tf2price/varredura/leitura.py` | Pure classifieds URL for the item–effect pair; attach it only to visible scan rows. Keep existing guide calculation intact. |
| `tf2price/painel/templates/scan.html` | Describe guide-age filter and guide-gap sorting. |
| `tf2price/painel/templates/_scan_tabela.html` | Relabel the result, show the seller link, explain that the guide gap is not an executable sale. |
| `tests/varredura/test_leitura.py` | URL identity and pagination tests without network. |
| `tests/painel/test_scan.py` | English copy, manual link, and preserved HTMX behavior. |
| `README.md` | Explain the distinction between guide gap and live sellers. |
| `docs/superpowers/findings/2026-09-23-classificados-source.md` | Record the bounded API probe and the automatic-source decision. |

### Task 1: Direct seller search for each visible pair

**Files:**
- Modify: `tf2price/varredura/leitura.py`
- Test: `tests/varredura/test_leitura.py`

**Interfaces:**
- Consumes: `parse_market_hash_name(str) -> ItemIdentity`, `effect_id_for(str, Path) -> int | None`, `urllib.parse.urlencode`.
- Produces: `url_vendas(hash_name: str, efeito: str | None, effects_path: Path = DEFAULT_EFFECTS_PATH) -> str | None`; `LinhaVarrida.vendas_url: str | None` for the template.

- [ ] **Step 1: Write a failing URL test**

Append to `tests/varredura/test_leitura.py`:

```python
def test_url_de_vendas_filtra_nome_qualidade_e_efeito():
    from urllib.parse import parse_qs, urlparse

    url = leitura.url_vendas("Unusual Team Captain", "Burning Flames", EFEITOS)
    assert url is not None
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https", "backpack.tf", "/classifieds"
    )
    assert parse_qs(parsed.query) == {
        "item": ["Team Captain"], "quality": ["5"],
        "tradable": ["1"], "craftable": ["1"], "particle": ["13"],
    }
    assert leitura.url_vendas("Unusual Team Captain", "Not In Schema", EFEITOS) is None
    assert leitura.url_vendas("Strange Unusual Team Captain", "Burning Flames", EFEITOS) is None
```

- [ ] **Step 2: Verify the failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_leitura.py::test_url_de_vendas_filtra_nome_qualidade_e_efeito -v`

Expected: FAIL because `url_vendas` does not exist.

- [ ] **Step 3: Implement the pure URL helper and row field**

In `tf2price/varredura/leitura.py`, import `effect_id_for` and `parse_market_hash_name`. Add the field to `LinhaVarrida`, set its default in the local `linha()` factory, and populate it only in the visible-row `replace` call:

```python
from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import parse_market_hash_name


def url_vendas(
    hash_name: str, efeito: str | None, effects_path: Path = DEFAULT_EFFECTS_PATH
) -> str | None:
    if not efeito:
        return None
    item = parse_market_hash_name(hash_name)
    particle = effect_id_for(efeito, effects_path)
    if item.quality_id != 5 or particle is None:
        return None
    return "https://backpack.tf/classifieds?" + urlencode({
        "item": item.base_name,
        "quality": 5,
        "tradable": 1,
        "craftable": 1,
        "particle": particle,
    })
```

Add `vendas_url: str | None` to `LinhaVarrida`. In the `base` dict inside `avaliar`, add `vendas_url=None`. In `montar`, replace the visible-row expression with:

```python
replace(
    l,
    arte=_arte(l.listagem, effects_path),
    vendas_url=url_vendas(l.listagem.hash_name, l.listagem.efeito, effects_path),
)
```

The URL opens the classifieds search for the nominal item and exact particle. It is a manual check, not evidence that a seller exists or that the Steam exemplar has every trade attribute assumed by the filter.

- [ ] **Step 4: Verify the focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\varredura\test_leitura.py -v`

Expected: PASS, including the new URL test and existing effect-price isolation tests.

- [ ] **Step 5: Commit the isolated change**

```powershell
git add tf2price/varredura/leitura.py tests/varredura/test_leitura.py
git commit -m "Liga pares varridos aos classificados do mesmo efeito"
```

### Task 2: Present the guide gap without claiming profit

**Files:**
- Modify: `tf2price/painel/templates/scan.html`
- Modify: `tf2price/painel/templates/_scan_tabela.html`
- Modify: `tests/painel/test_scan.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `LinhaVarrida.vendas_url` from Task 1 and all existing `LinhaVarrida` guide fields.
- Produces: English guide labels and a seller-search link; preserves the `aba=lucro` query value so old saved URLs continue to work.

- [ ] **Step 1: Write a failing presentation regression test**

Append to `tests/painel/test_scan.py`:

```python
def test_scan_distingue_preco_sugerido_de_vendas_ativas(engine):
    _semear(engine, [("1", 80000, "Burning Flames")])
    cliente = cliente_logado(engine, _contexto(indice=_indice()))

    texto = cliente.get("/scan").text

    assert "Below suggested price" in texto
    assert "Suggested backpack.tf price" in texto
    assert "Guide gap" in texto
    assert "A suggested price is not a buyer offer" in texto
    assert "View sellers" in texto
    assert "item=Team+Captain" in texto and "particle=13" in texto
    assert "Profitable" not in texto
```

- [ ] **Step 2: Verify the failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_scan.py::test_scan_distingue_preco_sugerido_de_vendas_ativas -v`

Expected: FAIL on the old `Profitable` and `Result` copy.

- [ ] **Step 3: Replace the misleading copy in both templates**

In `scan.html`, keep existing form names and option values. Replace only the
visible text in these existing lines:

```diff
- Max backpack.tf age (days)
+ Max suggested price age (days)
- Only with a usable backpack.tf price
+ Only with a usable suggested price
- Result (R$)
+ Guide gap (R$)
- Result (%)
+ Guide gap (%)
- backpack.tf price age
+ Suggested price age
```

Preserve each label's input/select markup and Jinja `selected` conditions. In
`_scan_tabela.html`, change the second tab text to `Below suggested price`
while keeping `aba='lucro'`. Replace headings `<th scope="col">backpack.tf
value</th>`, `<th scope="col">Result</th>`, and `<th scope="col">bp.tf
age</th>` with `Suggested backpack.tf price`, `Guide gap`, and `Suggested age`
respectively. Replace the current formula sentence with:

```html
<p class="scan-count">{{ pagina.total }} listings{% if pagina.paginas > 1 %} · page {{ pagina.pagina }} of {{ pagina.paginas }}{% endif %}
  · Guide gap = suggested backpack.tf value in keys × reference key price − Steam price.
  A suggested price is not a buyer offer; check active sellers before buying.</p>
```

Add one link beside `Open case` and `Steam` in each row:

```html
{% if l.vendas_url %}<a href="{{ l.vendas_url }}" target="_blank" rel="noopener noreferrer">View sellers</a>{% endif %}
```

Keep the existing positive/negative visual treatment, but never call the guide gap `profit` or `resale value` in UI text. The `resultado` field remains an internal historical name until live seller data has its own model.

- [ ] **Step 4: Update the affected README paragraph**

Replace the existing Market Scan result description with:

```markdown
Por enquanto, a diferença mostrada no Market Scan compara a listagem Steam com
o preço **sugerido** da backpack.tf para o mesmo efeito. Ela é uma diferença
contra a referência, não lucro confirmado nem uma oferta de compra. A aba
"Below suggested price" filtra diferenças positivas após o filtro de idade
do preço sugerido. Cada linha tem um link para conferir os anúncios ativos de
venda daquele item e efeito na backpack.tf. O scan não usa esses anúncios no
cálculo até existir uma fonte automática verificada para eles.
```

Preserve the surrounding paragraphs about key reference, scan scheduling, and admin controls.

- [ ] **Step 5: Run focused verification**

Run: `.\.venv\Scripts\python.exe -m pytest tests\painel\test_scan.py tests\varredura\test_leitura.py -v`

Expected: PASS. If a pre-existing test asserts the old label, update that assertion to the new wording without weakening its behavioral assertion.

- [ ] **Step 6: Commit the UI and README change**

```powershell
git add tf2price/painel/templates/scan.html tf2price/painel/templates/_scan_tabela.html tests/painel/test_scan.py README.md
git commit -m "Distingue diferenca do preco sugerido de lucro no scan"
```

### Task 3: Establish whether automated seller quotes are available

**Files:**
- Create: `docs/superpowers/findings/2026-09-23-classificados-source.md`

**Interfaces:**
- Consumes: local `BPTF_USER_TOKEN` if the owner configures one; never its value in source control, output, or logs.
- Produces: a documented `viável` or `indisponível` source decision with HTTP status, field names needed for exact item–effect matching, and observed limit response. A viable result is the input to a second plan for the collector and `Potential resale` computation.

- [ ] **Step 1: Confirm the public API contract**

Read `https://next.backpack.tf/developer` and `https://api.backpack.tf/api/swagger.json`. Record that the documented v2 classifieds listing index is account-owned, while v1 listing APIs are deprecated and rate limited. Do not substitute account-owned listings for the market-wide sellers the feature needs.

- [ ] **Step 2: Run one bounded read-only request if a local user token exists**

Run from PowerShell at the repository root. It reads `.env` but prints neither the token nor the request URL:

```powershell
@'
import os
import httpx
from dotenv import load_dotenv

load_dotenv('.env')
token = os.getenv('BPTF_USER_TOKEN', '').strip()
if not token:
    print('BPTF_USER_TOKEN absent; automatic source unavailable for this probe')
    raise SystemExit(0)
try:
    response = httpx.get(
        'https://backpack.tf/api/classifieds/listings/snapshot',
        params={'appid': 440, 'sku': 'Team Captain', 'token': token},
        timeout=15.0,
        follow_redirects=False,
    )
    print('status:', response.status_code)
    print('retry-after:', response.headers.get('Retry-After', 'absent'))
    if response.status_code == 200:
        value = response.json()
        print('root type:', type(value).__name__)
        if isinstance(value, dict):
            print('root keys:', sorted(value))
            for name, child in value.items():
                if isinstance(child, list):
                    print('array:', name, 'count:', len(child))
                    if child and isinstance(child[0], dict):
                        print('array field names:', name, sorted(child[0]))
except (httpx.HTTPError, ValueError) as error:
    print('probe error type:', type(error).__name__)
'@ | .\.venv\Scripts\python.exe -
```

Expected: either `BPTF_USER_TOKEN absent`, an HTTP status such as 200/401/429, or a sanitized error type. No automatic-source claim follows from 200 alone: confirm the response identifies each seller's **effect**, quality, intent, active status, price currency, and completeness of the seller set before declaring it viable. Do not probe more pairs after 429; honor `Retry-After`.

- [ ] **Step 3: Record the observed capability without secrets**

Create the findings document with the exact request target name (`Team Captain`), observation date, status, sanitized field names, ability or inability to isolate `Burning Flames` sales, and whether a complete minimum can be obtained within the published rate limit. Include one of two conclusions: `viável para planejar coletor` only when every required field and acceptable rate limit is observed; otherwise `indisponível para cotação automática neste momento`. Do not include listing account IDs, tokens, trade URLs, or raw payloads.

- [ ] **Step 4: Finish verification and commit findings**

Run: `.\.venv\Scripts\python.exe -m pytest`

Run: `git diff --check`

Expected: complete suite PASS; `git diff --check` has no output. Then:

```powershell
git add docs/superpowers/findings/2026-09-23-classificados-source.md
git commit -m "Registra viabilidade da fonte de anuncios da backpack tf"
```

## Plan self-review against the approved design

Tasks 1–2 implement the spec's no-source fallback and avoid a false claim of profit. Task 3 resolves the source boundary. The approved design's live seller cache, six-hour freshness rule, background worker, exact quote parser, and `Potential resale` result are **not** safely implementable from the current public API description alone. They belong to a second plan only if Task 3 demonstrates a market-wide seller feed with exact effect identity and workable request limits. If that feed is unavailable, this plan produces the complete fallback specified in the design.
