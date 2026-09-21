from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.contas import repositorio, servico
from tf2price.painel.app import criar_app

from .conftest import SENHA, _contexto, cliente_logado


@pytest.fixture
def cliente(engine):
    return cliente_logado(engine, _contexto())


def _cores_hex_css(css):
    # Ignore text/URLs/comments, then inspect declaration values, not selectors.
    css = re.sub(
        r"""/\*.*?\*/|url\((?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^)])*\)|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""",
        "",
        css,
        flags=re.IGNORECASE | re.DOTALL,
    )
    valores = re.findall(r"(?:^|[;{])\s*[\w-]+\s*:\s*([^;{}]+)", css)
    return {
        cor.lower()
        for valor in valores
        for cor in re.findall(
            r"(?<![\w-])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![\w-])",
            valor,
            flags=re.IGNORECASE,
        )
    }


def test_leitura_de_cores_ignora_urls_texto_comentarios_e_seletores():
    css = """
    /* color: #fff; */
    #bad { background: url("/assets/#abcdef"); content: "#123456"; }
    #fff { background-image: URL(/assets/#112233); font-family: "Text #123"; }
    .a { color: #E8E1D1; border: 1px solid #e8e1d1; --ink: #0e0f10; }
    """
    assert _cores_hex_css(css) == {"#e8e1d1", "#0e0f10"}


def test_css_usa_apenas_as_sete_cores_hex_aprovadas(engine):
    cliente = TestClient(criar_app(engine))
    resposta = cliente.get("/static/briefcase.css")
    assert resposta.status_code == 200
    paleta = {
        "#0e0f10", "#15242a", "#29424b", "#365866",
        "#e8e1d1", "#a4453a", "#d2a53b",
    }
    assert _cores_hex_css(resposta.text) == paleta


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


def test_base_usa_as_quatro_fontes_locais_sem_google_fonts(engine):
    cliente = TestClient(criar_app(engine))
    resposta = cliente.get("/entrar")

    assert resposta.status_code == 200
    texto = resposta.text
    assert "fonts.googleapis.com" not in texto
    assert "fonts.gstatic.com" not in texto
    assert '/static/briefcase.css' in texto
    resposta_css = cliente.get("/static/briefcase.css")
    assert resposta_css.status_code == 200
    texto = resposta_css.text
    assert "fonts.googleapis.com" not in texto
    assert "fonts.gstatic.com" not in texto

    fontes = {
        "Roboto Slab": "/static/fonts/roboto-slab-latin.woff2",
        "Roboto Condensed": "/static/fonts/roboto-condensed-latin.woff2",
        "Inter": "/static/fonts/inter-latin.woff2",
        "IBM Plex Mono": "/static/fonts/ibm-plex-mono-latin.woff2",
    }
    for familia, caminho in fontes.items():
        assert f'font-family: "{familia}"' in texto
        assert f'url("{caminho}")' in texto

    assert '--font-display: "Roboto Slab"' in texto
    assert '--font-condensed: "Roboto Condensed"' in texto
    assert '--font-interface: "Inter"' in texto
    assert '--font-mono: "IBM Plex Mono"' in texto
    assert "font-family: var(--font-condensed)" in texto


def test_ibm_plex_mono_declara_os_pesos_locais_que_a_tela_usa(engine):
    cliente = TestClient(criar_app(engine))
    texto = cliente.get("/static/briefcase.css").text
    fontes = (
        ("/static/fonts/ibm-plex-mono-latin.woff2", 400),
        ("/static/fonts/ibm-plex-mono-latin-500.woff2", 500),
        ("/static/fonts/ibm-plex-mono-latin-600.woff2", 600),
    )

    for caminho, peso in fontes:
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200, caminho
        assert resposta.content.startswith(b"wOF2")
        declaracao = (
            f'font-family: "IBM Plex Mono"; src: url("{caminho}") '
            f'format("woff2"); font-weight: {peso};'
        )
        assert declaracao in texto

    assert 'font-family: "IBM Plex Mono"' in texto
    assert "font-weight: 100 700" not in texto


def test_shell_usa_marca_assets_locais_e_ingles(cliente):
    texto = cliente.get("/").text
    assert '<html lang="en">' in texto
    assert "briefcase.tf" in texto
    assert "Unusual Market Intelligence" in texto
    assert "/static/brand/briefcase.svg" in texto
    assert "/static/briefcase.css" in texto
    assert "/static/briefcase.js" in texto
    assert "fonts.googleapis.com" not in texto
    assert 'href="#main-content"' in texto
    assert 'id="main-content" class="app-main" tabindex="-1"' in texto
    assert 'htmx.org@1.9.12/dist/htmx.min.js' in texto
    assert 'integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"' in texto
    assert 'crossorigin="anonymous"' in texto
    assert cliente.get("/static/briefcase.js").status_code == 200


@pytest.mark.parametrize("caminho", ["/", "/cases/new", "/cases", "/sources", "/admin"])
def test_menu_tem_as_paginas_e_marca_so_a_atual(cliente, caminho):
    texto = cliente.get(caminho).text
    for rotulo in ("Overview", "New Case", "Case Files", "Sources", "Administration"):
        assert rotulo in texto
    assert f'href="{caminho}" aria-current="page"' in texto
    assert texto.count('aria-current="page"') == 1
    assert 'aria-controls="app-navigation"' in texto
    assert 'aria-expanded="false"' in texto
    assert 'data-nav-toggle' in texto and 'data-app-nav' in texto
    assert '<form method="post" action="/sair">' in texto
    assert texto.count("<main ") == 1


def test_administration_link_is_hidden_from_non_admin(engine):
    cliente_logado(engine, _contexto())
    with engine.begin() as conn:
        admin = repositorio.usuario_por_nome(conn, "gusco")
        token = servico.convidar(conn, criado_por=admin.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome="reader", senha=SENHA, quando=db.agora())
    reader = TestClient(criar_app(engine, _contexto()))
    reader.post("/entrar", data={"nome": "reader", "senha": SENHA})

    assert "Administration" not in reader.get("/").text


def test_autenticacao_tem_shell_proprio_sem_conta_menu_ou_htmx(engine):
    cliente = TestClient(criar_app(engine, _contexto()))
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, db.agora())
    for caminho in ("/entrar", f"/convite/{token}"):
        texto = cliente.get(caminho).text
        assert '<html lang="en">' in texto
        assert 'class="auth-shell"' in texto
        assert '<h1 id="auth-title">' in texto
        assert 'aria-labelledby="auth-title"' in texto
        assert 'href="/static/briefcase.css"' in texto
        assert 'href="/static/brand/briefcase.svg"' in texto
        assert 'data-app-nav' not in texto
        assert 'action="/sair"' not in texto
        assert 'htmx' not in texto
