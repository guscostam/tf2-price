from __future__ import annotations

import itertools

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.spike.run import MAX_SHALLOW_PAGES, _parse_args, _shallow_scan

RESULTADO = SearchResult(
    hash_name="Unusual Team Captain",
    lowest_price=Brl.from_float(100.0),
    sell_listings=5,
)

# _shallow_scan deduplica por hash_name, então as páginas de teste precisam
# de nomes distintos para exercitar a paginação — repetir o mesmo nome
# testaria a deduplicação, não o teto de segurança.
_SEQUENCIA = itertools.count()


def _resultado(nome: str) -> SearchResult:
    return SearchResult(hash_name=nome, lowest_price=Brl.from_float(100.0), sell_listings=5)


def _pagina_cheia(total_count: int, tamanho: int = 100) -> SearchPage:
    return SearchPage(
        total_count=total_count,
        results=[_resultado(f"Item {next(_SEQUENCIA)}") for _ in range(tamanho)],
    )


def _pagina_vazia() -> SearchPage:
    return SearchPage(total_count=0, results=[])


class _SteamFake:
    """Duck-type mínimo de SteamClient: só precisa de search_page."""

    def __init__(self, respostas) -> None:
        self._respostas = respostas
        self.chamadas = 0

    def search_page(self, start: int, count: int = 100) -> SearchPage:
        self.chamadas += 1
        return self._respostas(start)


def test_teto_de_seguranca_contem_api_degradada():
    """API degradada: total_count=0 mas results sempre não vazio.

    Sem um teto independente, o loop giraria para sempre. O teto de
    segurança precisa interromper exatamente em MAX_SHALLOW_PAGES chamadas.
    """
    steam = _SteamFake(lambda start: _pagina_cheia(total_count=0, tamanho=1))

    resultados, total = _shallow_scan(steam, max_pages=0)

    assert steam.chamadas == MAX_SHALLOW_PAGES
    assert len(resultados) == MAX_SHALLOW_PAGES
    assert total == 0


def test_passada_saudavel_para_no_total():
    """Com total_count real, a passada para assim que start >= total,
    bem antes do teto de segurança."""
    total_real = 350  # 4 páginas de 100, última parcial

    def responder(start: int) -> SearchPage:
        restante = max(total_real - start, 0)
        tamanho = min(100, restante)
        return SearchPage(
            total_count=total_real,
            results=[_resultado(f"Item {start + i}") for i in range(tamanho)],
        )

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == total_real
    assert total == total_real
    assert steam.chamadas == 4
    assert steam.chamadas < MAX_SHALLOW_PAGES


def test_pagina_vazia_interrompe_a_passada():
    """Uma página cheia seguida de uma vazia deve parar ali, mesmo sem
    total_count confiável."""
    paginas = [_pagina_cheia(total_count=0, tamanho=100), _pagina_vazia()]

    def responder(start: int) -> SearchPage:
        return paginas.pop(0)

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100
    assert steam.chamadas == 2


def test_pagina_que_falha_preserva_o_que_ja_foi_coletado():
    """Uma execução completa leva 15-30 min. Uma página que falha no meio
    não pode descartar as páginas anteriores: um catálogo parcial ainda
    gera relatório, uma exceção não gera nada."""
    paginas = [_pagina_cheia(total_count=1000, tamanho=100)]

    def responder(start: int) -> SearchPage:
        if paginas:
            return paginas.pop(0)
        raise RuntimeError("Steam não respondeu após backoff (último: status 500)")

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100
    assert total == 1000


def test_falha_de_rede_http_tambem_e_contida():
    paginas = [_pagina_cheia(total_count=1000, tamanho=100)]

    def responder(start: int) -> SearchPage:
        if paginas:
            return paginas.pop(0)
        raise httpx.ReadTimeout("tempo esgotado")

    steam = _SteamFake(responder)
    resultados, _ = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100


def test_erro_de_programacao_continua_estourando():
    """Escopo estreito de propósito: AttributeError é bug, não falha de
    rede, e precisa aparecer em vez de virar 'passada parcial'."""

    def responder(start: int) -> SearchPage:
        raise AttributeError("bug de verdade")

    with pytest.raises(AttributeError):
        _shallow_scan(_SteamFake(responder), max_pages=0)


def test_paginas_sobrepostas_rendem_cada_nome_uma_vez():
    """Durante os ~11 min da passada o mercado se move e itens migram entre
    páginas. Duplicata infla as contagens que alimentam o veredito — na
    direção de 'vale construir'."""
    paginas = [
        SearchPage(
            total_count=4,
            results=[_resultado("A"), _resultado("B")],
        ),
        SearchPage(
            total_count=4,
            results=[_resultado("B"), _resultado("C")],
        ),
        SearchPage(total_count=4, results=[]),
    ]

    def responder(start: int) -> SearchPage:
        return paginas.pop(0)

    resultados, _ = _shallow_scan(_SteamFake(responder), max_pages=0)

    nomes = [r.hash_name for r in resultados]
    assert nomes == ["A", "B", "C"]


# --- validação de argumentos ---------------------------------------------


def test_threshold_negativo_e_rejeitado():
    # (1 - threshold) > 1 SOBE o piso da poda em vez de baixá-lo e fabrica
    # classificações GARANTIDAS: falso positivo, o pior erro possível aqui.
    with pytest.raises(SystemExit):
        _parse_args(["--threshold", "-0.1"])


def test_threshold_maior_ou_igual_a_um_e_rejeitado():
    with pytest.raises(SystemExit):
        _parse_args(["--threshold", "1.0"])


@pytest.mark.parametrize(
    "argumento",
    [
        ["--deep-limit", "-1"],
        ["--max-pages", "-1"],
        ["--min-interval", "-1"],
    ],
)
def test_valores_negativos_sao_rejeitados(argumento):
    with pytest.raises(SystemExit):
        _parse_args(argumento)


def test_conjunto_valido_e_aceito():
    args = _parse_args(
        ["--threshold", "0.25", "--deep-limit", "5", "--max-pages", "2", "--min-interval", "0"]
    )

    assert args.threshold == 0.25
    assert args.deep_limit == 5
    assert args.max_pages == 2
    assert args.min_interval == 0.0


def test_padroes_seguem_inalterados():
    args = _parse_args([])

    assert args.threshold == 0.15
    assert args.deep_limit == 20
    assert args.max_pages == 0
    assert args.min_interval == 3.0
    assert args.out == "out"
