"""A consulta de Unusual: contexto e rotas.

O retrato compartilhado da página da Steam mora em `preco/retrato.py`; aqui
só há transporte e apresentação. O que decide número continua em
`lookup/analysis.py`, que não sabe que existe usuário.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.domain.identity import is_unusual_name
from tf2price.domain.money import Brl
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.lookup.analysis import analyse, effects_available
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES
from tf2price.preco.retrato import Retratos
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SteamClient
from tf2price.sources.steam_page import PageStructureError, SteamPageClient, url_da_imagem

BUSCA_MAX = 25
INTERVALO_S = 1.0


def _mensagem_saneada(erro: Exception) -> str:
    """Corta a mensagem no primeiro '?', onde começa a query string.

    `BackpackTfClient._get` manda a chave da API como parâmetro `key=` na
    URL, e o `str()` de um `httpx.HTTPStatusError` inclui a URL inteira do
    pedido que falhou. A backpack.tf devolve 403 para quem não é navegador,
    então esse caminho é exercitado de verdade, não só em teoria — e o log
    não pode ser onde a chave aparece em claro.
    """
    return str(erro).split("?", 1)[0]


def _registra_falha_sob_demanda(origem: str, erro: Exception, espera_s: float) -> None:
    """Log mínimo para uma falha de terceiro não esconder um bug nosso.

    `IndiceSobDemanda` e `CotacaoSobDemanda` capturam `Exception` de
    propósito: a resiliência a um terceiro fora do ar é o objetivo da
    classe, e um `AttributeError` de programação precisa do mesmo
    comportamento na tela (avisa e segue de pé) que uma falha de rede.
    Só que os dois não podem ficar igualmente silenciosos, senão o bug
    nunca é descoberto — daí o print, no mesmo padrão do convite de
    partida em `app.py`, que o Railway já capta no log do serviço.
    """
    print(
        f"[sob-demanda] {origem}: {type(erro).__name__}: {_mensagem_saneada(erro)}; "
        f"nova tentativa em {espera_s:.0f}s",
        flush=True,
    )

ROTEADOR = APIRouter(dependencies=[Depends(ses.usuario_obrigatorio)])


class IndiceSobDemanda:
    """Carrega o índice da bp.tf na primeira necessidade, não na subida.

    Um serviço hospedado não pode morrer na partida porque um terceiro está
    fora do ar; hoje `construir_contexto` fazia exatamente isso. Se falhar,
    devolve None — e a tela diz que falta o índice, que é diferente de dizer
    que o efeito não tem preço.
    """

    def __init__(
        self,
        cliente: BackpackTfClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cliente = cliente
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._indice: PriceIndex | None = None
        self._proxima_tentativa = 0.0

    def obter(self) -> PriceIndex | None:
        if self._indice is not None:
            return self._indice
        if self._relogio() < self._proxima_tentativa:
            return None
        try:
            moedas = self._cliente.currencies()
            self._indice = PriceIndex.from_payload(
                self._cliente.prices_payload(), moedas.key_in_refined
            )
        except Exception as erro:
            _registra_falha_sob_demanda("IndiceSobDemanda", erro, self._espera)
            self._proxima_tentativa = self._relogio() + self._espera
            return None
        return self._indice


SEM_COTACAO = (
    "a cotação da chave ainda não carregou; tente de novo em alguns minutos"
)


@dataclass(frozen=True)
class Cotacao:
    """Preço da chave e taxa do dólar, que a tela inteira usa para converter."""

    key_brl: Brl
    usd_to_brl: float

    @property
    def usd_brl_formatado(self) -> Brl:
        return Brl.from_float(self.usd_to_brl)


class CotacaoSobDemanda:
    """Busca a cotação na primeira necessidade, não na subida.

    As duas vêm juntas porque as duas saem do mesmo cliente da Steam e são
    inúteis separadas: preço em chaves sem taxa de conversão não vira tela.
    """

    def __init__(
        self,
        steam: SteamClient,
        espera_apos_falha_s: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._steam = steam
        self._espera = espera_apos_falha_s
        self._relogio = relogio
        self._cotacao: Cotacao | None = None
        self._proxima_tentativa = 0.0

    def obter(self) -> Cotacao | None:
        if self._cotacao is not None:
            return self._cotacao
        if self._relogio() < self._proxima_tentativa:
            return None
        try:
            self._cotacao = Cotacao(
                key_brl=self._steam.key_price(), usd_to_brl=self._steam.usd_to_brl()
            )
        except Exception as erro:
            _registra_falha_sob_demanda("CotacaoSobDemanda", erro, self._espera)
            self._proxima_tentativa = self._relogio() + self._espera
            return None
        return self._cotacao


SEM_RETRATO = (
    "não consegui ler os dados da Steam, e não há retrato guardado deste item"
)


@dataclass
class Contexto:
    steam: Any
    paginas: Any
    indice: IndiceSobDemanda
    # Preço da chave e taxa dólar->real, sob demanda. A página de listagens
    # ignora o parâmetro `currency` e alterna entre dólar e real entre
    # requisições, então o que vier em dólar precisa desta taxa para virar
    # real.
    #
    # O retrato compartilhado guarda a página já convertida e é chaveado só
    # pelo nome do item — e isso basta: a taxa é uma foto por processo
    # (`_usd_to_brl_rate` calcula uma vez por instância de SteamClient e
    # guarda), então ela não muda enquanto o retrato guardado vale.
    # Se um dia a taxa passar a ser reavaliada em tempo de execução, a
    # chave do retrato precisa incluí-la.
    cotacao: CotacaoSobDemanda
    retratos: Retratos


def _erro(request: Request, mensagem: str) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request, name="_erro.html", context={"mensagem": mensagem}
    )


def _contexto(request: Request) -> Contexto:
    return request.app.state.contexto


@ROTEADOR.get("/", response_class=HTMLResponse)
def painel(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    # A cotação pode não ter carregado ainda; o painel abre assim mesmo e o
    # timbre diz isso, em vez de a aplicação não subir.
    cotacao = _contexto(request).cotacao.obter()
    return TEMPLATES.TemplateResponse(
        request=request,
        name="painel.html",
        context={"usuario": usuario, "cotacao": cotacao},
    )


@ROTEADOR.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = ""):
    contexto = _contexto(request)
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


@ROTEADOR.get("/efeitos", response_class=HTMLResponse)
def efeitos(request: Request, nome: str):
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is None:
        return _erro(request, SEM_COTACAO)
    try:
        leitura = contexto.retratos.obter(
            request.app.state.engine, nome, cotacao.usd_to_brl, db.agora()
        )
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))
    if leitura.pagina is None:
        return _erro(request, SEM_RETRATO)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_efeitos.html",
        context={"nome": nome, "efeitos": effects_available(leitura.pagina)},
    )


@ROTEADOR.get("/analise", response_class=HTMLResponse)
def rota_analise(request: Request, nome: str, efeito: str):
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is None:
        return _erro(request, SEM_COTACAO)
    try:
        leitura = contexto.retratos.obter(
            request.app.state.engine, nome, cotacao.usd_to_brl, db.agora()
        )
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))
    if leitura.pagina is None:
        return _erro(request, SEM_RETRATO)
    pagina = leitura.pagina
    try:
        resultado = analyse(pagina, efeito, contexto.indice.obter(), cotacao.key_brl)
    except ValueError as erro:
        return _erro(request, str(erro))
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_analise.html",
        context={
            "a": resultado,
            "arte": arte_dos_efeitos.url_do_efeito(efeito),
            # O ícone é o da listagem mais barata deste efeito: chapéu pintado
            # tem ícone próprio, e o de outra listagem seria outra variante.
            "chapeu": (
                url_da_imagem(resultado.cheapest.icon_url)
                if resultado.cheapest.icon_url
                else None
            ),
        },
    )


def construir_contexto() -> Contexto:
    """Monta os clientes reais, sem tocar a rede: índice e cotação são sob demanda."""
    load_dotenv(".env")
    chave_api = os.getenv("BPTF_API_KEY", "").strip()
    if not chave_api:
        raise RuntimeError("BPTF_API_KEY não configurada. Veja .env.example.")

    bptf = BackpackTfClient(chave_api)

    limitador = RateLimiter(min_interval_s=INTERVALO_S)
    steam = SteamClient(limitador)
    paginas = SteamPageClient(limitador)
    return Contexto(
        steam=steam,
        paginas=paginas,
        indice=IndiceSobDemanda(bptf),
        cotacao=CotacaoSobDemanda(steam),
        retratos=Retratos(paginas),
    )
