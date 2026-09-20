from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from tf2price.domain.identity import is_unusual_name
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import analyse, effects_available
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SteamClient
from tf2price.sources.steam_page import ItemPage, PageStructureError, SteamPageClient

CACHE_TTL_S = 300.0
BUSCA_MAX = 25
INTERVALO_S = 1.0

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class PageCache:
    """Guarda a ItemPage por hash_name com TTL curto.

    O spec promete duas requisições por consulta. Sem isto, escolher o efeito
    e depois ver a análise buscariam a mesma página duas vezes.
    """

    def __init__(
        self,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._itens: dict[str, tuple[float, ItemPage]] = {}

    def get(self, chave: str) -> ItemPage | None:
        registro = self._itens.get(chave)
        if registro is None:
            return None
        quando, pagina = registro
        if self._clock() - quando > self._ttl:
            del self._itens[chave]
            return None
        return pagina

    def put(self, chave: str, pagina: ItemPage) -> None:
        self._itens[chave] = (self._clock(), pagina)


@dataclass
class Contexto:
    steam: Any
    paginas: Any
    index: PriceIndex
    key_brl: Brl
    # Taxa dólar->real do próprio SteamClient. A página de listagens ignora
    # o parâmetro `currency` e alterna entre dólar e real entre requisições,
    # então o que vier em dólar precisa desta taxa para virar real.
    #
    # O cache de páginas guarda ItemPage já convertida e é chaveado só pelo
    # nome do item — e isso basta: a taxa é uma foto por processo
    # (`_usd_to_brl_rate` calcula uma vez por instância de SteamClient e
    # guarda), então ela não muda enquanto alguma entrada do cache vive.
    # Se um dia a taxa passar a ser reavaliada em tempo de execução, a
    # chave do cache precisa incluí-la.
    #
    # Sem valor padrão, pelo mesmo motivo de `parse_item_page`: um padrão
    # deixa a conversão esquecível em quem monta o contexto.
    usd_to_brl: float
    cache: PageCache = field(default_factory=PageCache)


def _erro(request: Request, mensagem: str) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request, name="_erro.html", context={"mensagem": mensagem}
    )


def criar_app(contexto: Contexto) -> FastAPI:
    app = FastAPI(title="Consulta de Unusual")

    def pagina_do_item(nome: str) -> ItemPage:
        em_cache = contexto.cache.get(nome)
        if em_cache is not None:
            return em_cache
        pagina = contexto.paginas.item_page(nome, contexto.usd_to_brl)
        contexto.cache.put(nome, pagina)
        return pagina

    @app.get("/", response_class=HTMLResponse)
    def raiz(request: Request):
        return TEMPLATES.TemplateResponse(request=request, name="index.html", context={})

    @app.get("/buscar", response_class=HTMLResponse)
    def buscar(request: Request, q: str = ""):
        termo = q.strip()
        if not termo:
            return TEMPLATES.TemplateResponse(
                request=request, name="_itens.html", context={"nomes": []}
            )
        try:
            pagina = contexto.steam.search_page(start=0, count=BUSCA_MAX, query=termo)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        nomes = [r.hash_name for r in pagina.results if is_unusual_name(r.hash_name)]
        return TEMPLATES.TemplateResponse(
            request=request, name="_itens.html", context={"nomes": nomes[:BUSCA_MAX]}
        )

    @app.get("/efeitos", response_class=HTMLResponse)
    def efeitos(request: Request, nome: str):
        try:
            pagina = pagina_do_item(nome)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        return TEMPLATES.TemplateResponse(
            request=request,
            name="_efeitos.html",
            context={"nome": nome, "efeitos": effects_available(pagina)},
        )

    @app.get("/analise", response_class=HTMLResponse)
    def rota_analise(request: Request, nome: str, efeito: str):
        try:
            pagina = pagina_do_item(nome)
        except (RuntimeError, PageStructureError) as erro:
            return _erro(request, str(erro))

        try:
            resultado = analyse(pagina, efeito, contexto.index, contexto.key_brl)
        except ValueError as erro:
            return _erro(request, str(erro))

        return TEMPLATES.TemplateResponse(
            request=request, name="_analise.html", context={"a": resultado}
        )

    return app


def construir_contexto() -> Contexto:
    """Monta os clientes reais e carrega o índice da backpack.tf uma vez."""
    load_dotenv(".env")
    chave_api = os.getenv("BPTF_API_KEY", "").strip()
    if not chave_api:
        raise RuntimeError("BPTF_API_KEY não configurada. Veja .env.example.")

    bptf = BackpackTfClient(chave_api)
    moedas = bptf.currencies()
    index = PriceIndex.from_payload(bptf.prices_payload(), moedas.key_in_refined)

    limitador = RateLimiter(min_interval_s=INTERVALO_S)
    steam = SteamClient(limitador)
    return Contexto(
        steam=steam,
        paginas=SteamPageClient(limitador),
        index=index,
        key_brl=steam.key_price(),
        usd_to_brl=steam.usd_to_brl(),
    )


def servir() -> None:
    """Ponto de entrada: python -m tf2price.lookup.app"""
    import uvicorn

    uvicorn.run(criar_app(construir_contexto()), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    servir()
