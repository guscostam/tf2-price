from pathlib import Path
import re

import pytest

from .conftest import _contexto, cliente_logado


@pytest.fixture
def cliente(engine):
    return cliente_logado(engine, _contexto())


@pytest.mark.parametrize("path", ["/", "/cases", "/cases/new", "/sources", "/admin"])
def test_pages_have_skip_link_landmark_and_current_navigation(cliente, path):
    texto = cliente.get(path).text
    assert 'href="#main-content"' in texto
    assert 'id="main-content" class="app-main" tabindex="-1"' in texto
    assert texto.count('aria-current="page"') == 1


def test_dynamic_regions_and_search_help_are_labelled(cliente):
    texto = cliente.get("/cases/new").text
    assert 'for="q"' in texto
    assert texto.count('aria-live="polite"') >= 2
    assert 'aria-labelledby="analysis-title"' in texto
    assert 'aria-describedby="search-help"' in texto
    assert 'id="search-help"' in texto


def test_css_contains_responsive_and_reduced_motion_contracts():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    assert "@media (max-width: 48rem)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "button, input, select { min-height: 44px; }" in css
    assert ":focus-visible" in css
    assert "overflow-x: hidden" not in css
    hidden = re.search(r"\.visually-hidden\s*\{([^}]+)\}", css)
    assert hidden is not None
    assert "position: absolute" in hidden[1]
    assert "clip-path: inset(50%)" in hidden[1]


def test_paper_controls_and_dark_errors_have_readable_palette_roles():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    dossier = re.search(r"\.dossier\s*\{([^}]+)\}", css)[1]
    assert "--tinta: var(--charcoal)" in dossier
    assert ".dossier :focus-visible" in css
    assert "#q::placeholder { color: var(--ink-blue); opacity: 1; }" in css
    errors = re.search(
        r"\.error-state, \.status-badge--error, \.button--danger\s*\{([^}]+)\}", css
    )[1]
    assert "color: var(--paper)" in errors


def test_hidden_tab_pauses_loading_and_effect_animations():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    for selector in (".effect-layer", ".aura", ".loading-bar", "#espera"):
        assert f".page-hidden {selector}" in css
    assert "animation-play-state: paused" in css


def test_choice_selection_does_not_transition_through_unreadable_contrast():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    choice = re.search(r"\.choice-list button\s*\{([^}]+)\}", css)[1]
    # Foreground and background must switch together when selecting a choice.
    assert "transition: border-color .18s ease" in choice


def test_search_focus_ring_has_space_below_its_label():
    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    label = re.search(r"\.case-search label\s*\{([^}]+)\}", css)[1]
    # The 3px outline plus 3px offset must not paint over the label above it.
    assert "margin-bottom: .5rem" in label


def test_empty_overview_cta_has_a_paper_compatible_touch_target(cliente):
    texto = cliente.get("/").text
    recent = texto[texto.index('aria-labelledby="recent-title"'):]
    recent = recent[:recent.index("</section>")]
    assert '<a class="button button--primary" href="/cases/new">Open a new case</a>' in recent

    css = Path("tf2price/painel/static/briefcase.css").read_text(encoding="utf-8")
    button = re.search(r"^\.button\s*\{([^}]+)\}", css, re.MULTILINE)[1]
    assert "min-height: 44px" in button
    assert "padding: .65rem .9rem" in button
    assert "display: inline-flex" in button
    assert ".dossier :focus-visible { outline-color: var(--ink-blue); }" in css
    primary = re.search(r"\.button--primary\s*\{([^}]+)\}", css)[1]
    assert "background: var(--rust-stamp)" in primary
    assert "color: var(--paper)" in primary
