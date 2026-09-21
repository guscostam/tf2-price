from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from tf2price import db
from tf2price.preco import repositorio as repo
from tf2price.preco import retrato as mod
from tf2price.preco import serial
from tf2price.sources.steam_page import parse_item_page

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "steam_listing_page.html"
NOME = "Unusual Taunt: Chairholder"
AGORA = db.agora()


def _pagina():
    return parse_item_page(FIXTURE.read_text(encoding="utf-8"), NOME, 1.0)


class _PaginasFalsas:
    """Conta chamadas e pode fingir o 429 da Steam."""

    def __init__(self, erro: Exception | None = None):
        self.chamadas = 0
        self.erro = erro

    def item_page(self, hash_name, usd_to_brl):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return _pagina()


class _Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora

    def avancar(self, s):
        self.agora += s


def test_primeira_leitura_busca_e_guarda(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    leitura = retratos.obter(engine, NOME, 1.0, AGORA)
    assert leitura.pagina.hash_name == NOME
    assert leitura.buscado_em == AGORA
    with engine.begin() as conn:
        assert repo.ler(conn, NOME) is not None
    assert paginas.chamadas == 1


def test_dentro_da_validade_nao_busca_de_novo(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    retratos.obter(engine, NOME, 1.0, AGORA)
    leitura = retratos.obter(engine, NOME, 1.0, AGORA + timedelta(minutes=14))
    assert paginas.chamadas == 1
    assert leitura.buscado_em == AGORA


def test_depois_da_validade_busca_de_novo(engine):
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    depois = AGORA + mod.VALIDADE + timedelta(seconds=1)
    retratos.obter(engine, NOME, 1.0, AGORA)
    leitura = retratos.obter(engine, NOME, 1.0, depois)
    assert paginas.chamadas == 2
    assert leitura.buscado_em == depois


def test_o_retrato_e_compartilhado_entre_pessoas(engine):
    """Duas pessoas no mesmo chapéu custam uma requisição, não duas."""
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    retratos.obter(engine, NOME, 1.0, AGORA)
    retratos.obter(engine, NOME, 1.0, AGORA + timedelta(minutes=1))
    assert paginas.chamadas == 1


def test_forcar_busca_mesmo_dentro_da_validade(engine):
    paginas = _PaginasFalsas()
    relogio = _Relogio()
    retratos = mod.Retratos(paginas, relogio=relogio)
    retratos.obter(engine, NOME, 1.0, AGORA)
    relogio.avancar(mod.PISO_PARA_FORCAR.total_seconds() + 1)
    retratos.obter(engine, NOME, 1.0, AGORA + timedelta(minutes=1), forcar=True)
    assert paginas.chamadas == 2


def test_forcar_duas_vezes_seguidas_respeita_o_piso(engine):
    """Sem piso, segurar o botão vira uma enxurrada na Steam."""
    paginas = _PaginasFalsas()
    retratos = mod.Retratos(paginas, relogio=_Relogio())
    retratos.obter(engine, NOME, 1.0, AGORA, forcar=True)
    retratos.obter(engine, NOME, 1.0, AGORA, forcar=True)
    assert paginas.chamadas == 1


def test_429_liga_a_calma_e_serve_o_guardado(engine):
    """A tela mostra o retrato velho dizendo a idade, em vez de quebrar."""
    bons = _PaginasFalsas()
    relogio = _Relogio()
    retratos = mod.Retratos(bons, relogio=relogio)
    retratos.obter(engine, NOME, 1.0, AGORA)

    bons.erro = RuntimeError("status 429")  # a Steam começa a recusar
    depois = AGORA + mod.VALIDADE + timedelta(minutes=1)
    leitura = retratos.obter(engine, NOME, 1.0, depois)
    assert leitura.pagina is not None
    assert leitura.buscado_em == AGORA
    assert leitura.limitando is True


def test_durante_a_calma_nenhuma_requisicao_sai(engine):
    ruins = _PaginasFalsas(erro=RuntimeError("status 429"))
    retratos = mod.Retratos(ruins, relogio=_Relogio())
    retratos.obter(engine, NOME, 1.0, AGORA)
    retratos.obter(engine, NOME, 1.0, AGORA)
    retratos.obter(engine, NOME, 1.0, AGORA)
    assert ruins.chamadas == 1


def test_nenhuma_conexao_fica_emprestada_durante_a_busca(engine):
    """A busca leva segundos; segurar conexão do pool nela esgota o Postgres.

    Mesma medição de `tests/painel/test_transacao.py`, aplicada na origem: é
    aqui que a decisão de abrir duas transações curtas em volta do `fetch`
    fica travada contra um refactor futuro.
    """
    from sqlalchemy import event

    estado = {"emprestadas": 0}
    event.listen(engine, "checkout", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] + 1))
    event.listen(engine, "checkin", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] - 1))

    class _Observa(_PaginasFalsas):
        def item_page(self, hash_name, usd_to_brl):
            self.durante = estado["emprestadas"]
            return super().item_page(hash_name, usd_to_brl)

    paginas = _Observa()
    mod.Retratos(paginas, relogio=_Relogio()).obter(engine, NOME, 1.0, AGORA)
    assert paginas.durante == 0


def test_sem_retrato_e_com_falha_a_leitura_vem_vazia(engine):
    ruins = _PaginasFalsas(erro=RuntimeError("status 429"))
    retratos = mod.Retratos(ruins, relogio=_Relogio())
    leitura = retratos.obter(engine, NOME, 1.0, AGORA)
    assert leitura.pagina is None
    assert leitura.limitando is True
