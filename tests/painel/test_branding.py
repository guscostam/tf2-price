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


def test_base_usa_as_quatro_fontes_locais_sem_google_fonts(engine):
    resposta = TestClient(criar_app(engine)).get("/entrar")

    assert resposta.status_code == 200
    texto = resposta.text
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

    assert '--display: "Roboto Slab"' in texto
    assert '--condensed: "Roboto Condensed"' in texto
    assert '--corpo:   "Inter"' in texto
    assert '--mono:    "IBM Plex Mono"' in texto
    assert "font-family: var(--condensed)" in texto
