import pytest
from fastapi.testclient import TestClient

from tf2price.contas import servico
from tf2price.contas.senhas import SenhaCurta
from tf2price.painel import acesso
from tf2price.painel.app import criar_app

from .conftest import _contexto, cliente_logado

PORTUGUESE_UI = ("Entrar", "Administração", "Avaliação", "Acompanhados", "aguardando")


def test_public_login_has_no_old_portuguese_copy(engine):
    texto = TestClient(criar_app(engine, _contexto())).get("/entrar").text
    assert all(word not in texto for word in PORTUGUESE_UI)
    assert "htmx" not in texto
    assert 'data-app-nav' not in texto


@pytest.mark.parametrize("path", ["/", "/cases/new", "/cases", "/sources", "/admin", "/scan"])
def test_authenticated_pages_have_no_old_portuguese_copy(engine, path):
    resposta = cliente_logado(engine, _contexto()).get(path)
    assert resposta.status_code == 200
    assert all(word not in resposta.text for word in PORTUGUESE_UI)


@pytest.mark.parametrize("error, expected", [
    (servico.CredenciaisInvalidas("secret"), "Incorrect username or password."),
    (servico.ContaBloqueada("secret"), "Too many attempts. Wait a few minutes before trying again."),
    (servico.ContaInativa("secret"), "This account is disabled."),
    (SenhaCurta("secret"), "Password must contain at least 10 characters."),
    (servico.NomeEmUso("escolha um nome"), "Choose a username."),
    (servico.NomeEmUso("esse nome já está em uso"), "That username is already in use."),
    (servico.NomeEmUso("esse nome é longo demais (máximo 60 caracteres)"), "Username is too long. The maximum is 60 characters."),
    (servico.NomeEmUso("secret"), "The account could not be created."),
    (servico.ConviteInvalido("secret"), "The request could not be completed."),
    (RuntimeError("secret"), "The request could not be completed."),
])
def test_account_errors_have_stable_english_copy_without_raw_details(error, expected):
    assert acesso._account_error_message(error) == expected
