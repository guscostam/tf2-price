from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from tf2price import db
from tf2price.contas import repositorio_pedidos as repo
from tf2price.painel.app import criar_app
from tf2price.painel.limite import LimitePorChave
from tf2price.painel.publico import chave_do_cliente

from .conftest import _contexto, cliente_logado


def _anonimo(engine, contexto="padrao"):
    ctx = _contexto() if contexto == "padrao" else contexto
    return TestClient(criar_app(engine, ctx), follow_redirects=False)


VALIDO = {
    "perfil_steam": "steamcommunity.com/id/Gusco",
    "contato": "gusco no Discord",
    "observacao": "",
    "website": "",
}


def _request(headers=None, client=("10.0.0.1", 123)):
    scope = {
        "type": "http",
        "headers": [
            (nome.lower().encode(), valor.encode())
            for nome, valor in (headers or {}).items()
        ],
        "client": client,
    }
    return Request(scope)


def test_chave_do_cliente_sem_cabecalho_usa_o_client_host():
    assert chave_do_cliente(_request()) == "10.0.0.1"


def test_chave_do_cliente_usa_o_ultimo_item_do_xff():
    r = _request(headers={"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
    assert chave_do_cliente(r) == "9.9.9.9"


def test_chave_do_cliente_ignora_espacos_e_item_vazio_no_fim():
    r = _request(headers={"X-Forwarded-For": "1.2.3.4, 9.9.9.9, "})
    assert chave_do_cliente(r) == "9.9.9.9"


def test_chave_do_cliente_agrupa_ipv6_pela_rede_64():
    r = _request(headers={"X-Forwarded-For": "2001:db8:1:2:aaaa::1"})
    assert chave_do_cliente(r) == "2001:db8:1:2::/64"


def test_chave_do_cliente_lixo_cai_para_o_client_host():
    r = _request(headers={"X-Forwarded-For": "nao-e-ip"})
    assert chave_do_cliente(r) == "10.0.0.1"


def _pendentes(engine):
    with engine.begin() as conn:
        return repo.listar_pendentes(conn)


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


def test_pedido_valido_grava_e_confirma(engine):
    r = _anonimo(engine).post("/access-request", data=VALIDO)
    assert r.status_code == 303
    assert r.headers["location"] == "/?requested=1#access"
    [pedido] = _pendentes(engine)
    assert pedido.perfil_steam == "https://steamcommunity.com/id/gusco"
    assert pedido.contato == "gusco no Discord"


def test_pedido_invalido_volta_com_erros_e_valores(engine):
    r = _anonimo(engine).post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "https://evil.example/<b>x</b>", "contato": " "},
    )
    assert r.status_code == 422
    assert "Check the highlighted fields." in r.text
    assert "Enter a steamcommunity.com/id/" in r.text
    assert "Tell us where to send the invite." in r.text
    assert 'aria-invalid="true"' in r.text
    assert 'value="https://evil.example/&lt;b&gt;x&lt;/b&gt;"' in r.text
    assert _pendentes(engine) == []


def test_perfil_ja_pendente_recebe_a_mesma_resposta(engine):
    cliente = _anonimo(engine)
    primeira = cliente.post("/access-request", data=VALIDO)
    segunda = cliente.post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "https://steamcommunity.com/id/gusco/"},
    )
    assert (segunda.status_code, segunda.headers["location"]) == (
        primeira.status_code, primeira.headers["location"]
    )
    assert len(_pendentes(engine)) == 1


def test_honeypot_parece_sucesso_e_nao_grava(engine):
    r = _anonimo(engine).post("/access-request", data={**VALIDO, "website": "http://spam"})
    assert r.status_code == 303
    assert r.headers["location"] == "/?requested=1#access"
    assert _pendentes(engine) == []


def test_quarto_envio_do_mesmo_ip_na_hora_e_recusado(engine):
    relogio = [1000.0]
    cliente = _anonimo(engine)
    cliente.app.state.limite_pedidos = LimitePorChave(
        maximo=3, janela_s=3600, relogio=lambda: relogio[0]
    )
    for n in range(3):
        dados = {**VALIDO, "perfil_steam": f"steamcommunity.com/id/p{n}x"}
        assert cliente.post("/access-request", data=dados).status_code == 303
    r = cliente.post("/access-request", data={**VALIDO, "perfil_steam": "steamcommunity.com/id/p9x"})
    assert r.status_code == 429
    assert "Too many requests from this connection." in r.text
    assert len(_pendentes(engine)) == 3
    relogio[0] += 3600
    r = cliente.post("/access-request", data={**VALIDO, "perfil_steam": "steamcommunity.com/id/p9x"})
    assert r.status_code == 303


def test_teto_de_pendentes_fecha_os_pedidos(engine):
    with engine.begin() as conn:
        for n in range(200):
            repo.criar_pedido(conn, perfil_steam=f"https://steamcommunity.com/id/p{n}x",
                              contato="c", observacao=None, quando=db.agora())
    r = _anonimo(engine).post("/access-request", data=VALIDO)
    assert r.status_code == 503
    assert "Access requests are temporarily closed." in r.text
    assert len(_pendentes(engine)) == 200


def test_pedido_de_outra_origem_e_recusado(engine):
    r = _anonimo(engine).post(
        "/access-request", data=VALIDO,
        headers={"Origin": "https://site-de-outro.example"},
    )
    assert r.status_code == 403
    assert _pendentes(engine) == []


def test_forjar_o_comeco_do_xff_nao_abre_balde_novo(engine):
    cliente = _anonimo(engine, contexto=None)
    for n in range(3):
        dados = {**VALIDO, "perfil_steam": f"steamcommunity.com/id/p{n}x"}
        r = cliente.post(
            "/access-request",
            data=dados,
            headers={"X-Forwarded-For": f"6.6.6.{n}, 203.0.113.7"},
        )
        assert r.status_code == 303
    r = cliente.post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "steamcommunity.com/id/p9x"},
        headers={"X-Forwarded-For": "6.6.6.99, 203.0.113.7"},
    )
    assert r.status_code == 429


def test_dois_clientes_com_ultimo_item_diferente_nao_dividem_a_cota(engine):
    cliente = _anonimo(engine, contexto=None)
    for n in range(3):
        dados = {**VALIDO, "perfil_steam": f"steamcommunity.com/id/q{n}x"}
        r = cliente.post(
            "/access-request",
            data=dados,
            headers={"X-Forwarded-For": f"1.1.1.{n}, 203.0.113.8"},
        )
        assert r.status_code == 303
    # outro cliente (último item diferente): seu 1º envio não é bloqueado
    r = cliente.post(
        "/access-request",
        data={**VALIDO, "perfil_steam": "steamcommunity.com/id/r1x"},
        headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.9"},
    )
    assert r.status_code == 303


def test_limite_padrao_do_app_e_tres_por_hora(engine):
    cliente = _anonimo(engine, contexto=None)
    codigos = [
        cliente.post("/access-request",
                     data={**VALIDO, "perfil_steam": f"steamcommunity.com/id/q{n}x"}).status_code
        for n in range(4)
    ]
    assert codigos == [303, 303, 303, 429]
