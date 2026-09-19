from __future__ import annotations

from tf2price.domain.money import Brl
from tf2price.sources.steam import SearchPage, SearchResult
from tf2price.spike.run import MAX_SHALLOW_PAGES, _shallow_scan

RESULTADO = SearchResult(
    hash_name="Unusual Team Captain",
    lowest_price=Brl.from_float(100.0),
    sell_listings=5,
)


def _pagina_cheia(total_count: int, tamanho: int = 100) -> SearchPage:
    return SearchPage(
        total_count=total_count,
        results=[RESULTADO] * tamanho,
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
        return SearchPage(total_count=total_real, results=[RESULTADO] * tamanho)

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
