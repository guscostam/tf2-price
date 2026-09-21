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
