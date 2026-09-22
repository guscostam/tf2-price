from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tf2price.painel.app import criar_app

from .conftest import _contexto, cliente_logado


def _anonimo(engine, contexto="padrao"):
    ctx = _contexto() if contexto == "padrao" else contexto
    return TestClient(criar_app(engine, ctx), follow_redirects=False)


def test_raiz_sem_sessao_mostra_a_landing(engine):
    r = _anonimo(engine).get("/")
    assert r.status_code == 200
    assert 'data-page="landing"' in r.text
    assert "Every Unusual Is a Case." in r.text


def test_landing_nao_depende_de_contexto(engine):
    r = _anonimo(engine, contexto=None).get("/")
    assert r.status_code == 200
    assert 'data-page="landing"' in r.text


def test_raiz_com_sessao_continua_sendo_o_overview(engine):
    r = cliente_logado(engine, _contexto()).get("/")
    assert r.status_code == 200
    assert 'data-page="overview"' in r.text
    assert 'data-page="landing"' not in r.text


def test_landing_tem_o_conteudo_da_spec(engine):
    texto = _anonimo(engine).get("/").text
    for trecho in (
        "Unusual Market Intelligence",
        "Evidence for this effect. Context for the item. A verdict before you buy.",
        'href="#access"',
        'href="#sample-case"',
        "How it works",
        "This effect is not all effects.",
        "Insufficient Data",
        "1.72×",
        'action="/access-request#access"',
        "Not affiliated with Valve, Steam, or backpack.tf.",
        'href="/entrar"',
    ):
        assert trecho in texto, trecho


def test_exemplo_e_rotulado_e_nao_inventa_item(engine):
    texto = _anonimo(engine).get("/").text
    assert "Sample case · Fictional values" in texto
    assert 'src="/arte/13.webp"' in texto
    # Só a marca e a arte real do efeito: nenhuma render de chapéu.
    assert texto.count("<img") == 2


def test_landing_e_acessivel_e_sem_javascript(engine):
    texto = _anonimo(engine).get("/").text
    assert '<html lang="en">' in texto
    assert texto.count("<h1") == 1
    assert 'href="#main-content"' in texto and 'id="main-content"' in texto
    assert "<script" not in texto
    assert '<label for="perfil_steam">' in texto
    assert '<label for="contato">' in texto
    assert '<label for="observacao">' in texto
    assert 'aria-hidden="true"' in texto and 'name="website"' in texto
    assert 'name="description"' in texto and 'property="og:title"' in texto
    assert "/static/briefcase.css" in texto and "/static/landing.css" in texto


def test_confirmacao_substitui_o_formulario(engine):
    texto = _anonimo(engine).get("/?requested=1").text
    assert 'role="status"' in texto and "Request filed." in texto
    assert 'action="/access-request#access"' not in texto


def test_css_da_landing_e_responsivo_e_respeita_movimento_reduzido(engine):
    cliente = _anonimo(engine)
    assert cliente.get("/static/landing.css").status_code == 200
    css = Path("tf2price/painel/static/landing.css").read_text(encoding="utf-8")
    assert "@media (max-width: 56rem)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
