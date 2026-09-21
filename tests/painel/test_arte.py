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
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


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
