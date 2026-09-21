"""A consulta de Unusual: contexto e rotas.

O retrato compartilhado da página da Steam mora em `preco/retrato.py`; aqui
só há transporte e apresentação. O que decide número continua em
`lookup/analysis.py`, que não sabe que existe usuário.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from tf2price import db
from tf2price.acompanhamento import repositorio as acompanhamento
from tf2price.contas.modelo import Usuario
from tf2price.domain.identity import is_unusual_name
from tf2price.domain.money import Brl
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.lookup.analysis import analyse, effects_available
from tf2price.painel import sessao as ses
from tf2price.painel.templates import TEMPLATES
from tf2price.preco import repositorio as preco_repo
from tf2price.preco import serial
from tf2price.preco.retrato import Retratos
from tf2price.sources.backpacktf import BackpackTfClient, PriceIndex
from tf2price.sources.ratelimit import RateLimiter
from tf2price.sources.steam import SteamClient
from tf2price.sources.steam_page import PageStructureError, SteamPageClient, url_da_imagem
from tf2price.saneamento import mensagem_saneada

BUSCA_MAX = 25
INTERVALO_S = 1.0


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
        f"[sob-demanda] {origem}: {type(erro).__name__}: {mensagem_saneada(erro)}; "
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
    # pelo nome do item, sem a taxa. Isso já foi seguro quando o cache vivia
    # só na memória do processo (a taxa era uma foto por processo, e o cache
    # morria junto com ela) — mas o retrato agora persiste no banco e
    # sobrevive ao processo: a cada deploy, o processo novo calcula outra
    # `usd_to_brl`, e por até `VALIDADE` (15 min) ele serve o retrato antigo,
    # convertido pela taxa velha, ao lado de uma cotação já nova. O erro
    # numérico é desprezível (o real não anda tanto em 15 min), mas é real —
    # e é por isso que este comentário existe: para quem for mexer aqui não
    # presumir, pelo nome da chave, que ela já inclui a taxa.
    cotacao: CotacaoSobDemanda
    retratos: Retratos


def _erro(request: Request, mensagem: str, *, limpar_analise: bool = False) -> HTMLResponse:
    """`limpar_analise` manda `_erro.html` também esvaziar `#analise` por fora
    de banda — necessário quando o alvo da resposta é outro bloco (`/efeitos`
    mira `#efeitos`) e uma avaliação de um item anterior ficaria na tela.
    Rotas cujo próprio alvo já é `#analise` (como `/analise`) não precisam
    disso: a troca normal já substitui o bloco."""
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_erro.html",
        context={"mensagem": mensagem, "limpar_analise": limpar_analise},
    )


def _contexto(request: Request) -> Contexto:
    return request.app.state.contexto


@ROTEADOR.get("/", response_class=HTMLResponse)
def painel(request: Request, usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    # A cotação pode não ter carregado ainda; o painel abre assim mesmo e o
    # timbre diz isso, em vez de a aplicação não subir.
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    # Índice e cotação resolvidos antes de abrir a conexão, pelo mesmo motivo
    # de `_coluna`: os dois podem ir à rede na primeira chamada, e a
    # transação da lista de acompanhados tem de ser curta.
    indice = contexto.indice.obter()
    agora = db.agora()
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, cotacao, indice, usuario.id, agora)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="painel.html",
        context={"usuario": usuario, "cotacao": cotacao, "linhas": linhas},
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


def _contexto_da_analise(
    resultado, efeito: str, retrato_idade: str, retrato_limitando: bool
) -> dict[str, Any]:
    """Contexto de `_analise.html`, comum a `/analise` e a `/efeitos` (esta
    quando o clique já pede um efeito aberto, como o de um acompanhado).

    `retrato_idade` e `retrato_limitando` são a idade do retrato da Steam e
    se ela está em calma — a outra idade que a tela precisa mostrar, e que
    antes desta correção era descartada: sem ela, um retrato de horas atrás
    parecia "agora".
    """
    return {
        "a": resultado,
        "arte": arte_dos_efeitos.url_do_efeito(efeito),
        # O ícone é o da listagem mais barata deste efeito: chapéu pintado
        # tem ícone próprio, e o de outra listagem seria outra variante.
        "chapeu": (
            url_da_imagem(resultado.cheapest.icon_url)
            if resultado.cheapest.icon_url
            else None
        ),
        "retrato_idade": retrato_idade,
        "retrato_limitando": retrato_limitando,
    }


SEM_LISTAGEM_DO_EFEITO = "sem listagem deste efeito agora"


@ROTEADOR.get("/efeitos", response_class=HTMLResponse)
def efeitos(request: Request, nome: str, efeito: str = "",
            usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    # Sem `conn: Connection = Depends(ses.conexao)` de propósito: esta rota
    # fala com a Steam, e `test_transacao.py` exige zero conexões do pool
    # emprestadas durante esse instante. `usuario` é de graça — o FastAPI
    # reaproveita o resultado já calculado pela dependência do roteador.
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is None:
        return _erro(request, SEM_COTACAO, limpar_analise=True)
    agora = db.agora()
    try:
        leitura = contexto.retratos.obter(
            request.app.state.engine, nome, cotacao.usd_to_brl, agora
        )
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro), limpar_analise=True)
    if leitura.pagina is None:
        return _erro(request, SEM_RETRATO, limpar_analise=True)
    pagina = leitura.pagina
    retrato_idade = _idade_por_extenso(leitura.buscado_em, agora)
    indice = contexto.indice.obter()
    contexto_analise: dict[str, Any] = {}
    if efeito:
        # O botão de um acompanhado pede a lista e a avaliação num só clique.
        # Se o efeito já não está à venda nesta página, `analyse` levanta
        # ValueError; a lista aparece normal e a avaliação avisa a ausência —
        # nunca o preço de outro efeito, que vale outra ordem de grandeza.
        try:
            resultado = analyse(pagina, efeito, indice, cotacao.key_brl)
        except ValueError:
            # "sem listagem deste efeito agora" é uma afirmação sobre o
            # PRESENTE, sentada em cima de um retrato que pode ter horas — na
            # calma do 429 nenhuma busca sai, e ele envelhece sem teto. Sem a
            # idade e o aviso de limitação, a frase mente dizendo que o item
            # sumiu do mercado quando o que sumiu foi a nossa visão dele.
            contexto_analise = {
                "efeito_ausente": SEM_LISTAGEM_DO_EFEITO,
                "retrato_idade": retrato_idade,
                "retrato_limitando": leitura.limitando,
            }
        else:
            contexto_analise = _contexto_da_analise(
                resultado, efeito, retrato_idade, leitura.limitando
            )
    # A esquerda tem de concordar com a direita: se o retrato estava vencido,
    # a busca acima trouxe um novo, e sem atualizar `#acompanhados` também
    # aqui a coluna esquerda ficaria mostrando o preço velho ao lado do novo
    # que a direita acabou de exibir. A linha do efeito aberto sai marcada,
    # para dar pra saber de qual linha a direita está falando.
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(
            conn, cotacao, indice, usuario.id, agora,
            selecionado=(nome, efeito) if efeito else None,
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_efeitos.html",
        context={
            "nome": nome,
            "efeitos": effects_available(pagina),
            "efeito_atual": efeito,
            "linhas": linhas,
            **contexto_analise,
        },
    )


@ROTEADOR.get("/analise", response_class=HTMLResponse)
def rota_analise(request: Request, nome: str, efeito: str,
                  usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    # `usuario` é de graça (mesmo motivo de `/efeitos`: o FastAPI reaproveita
    # o resultado já calculado pela dependência do roteador) — precisa dele
    # só agora, para marcar a linha aberta em `#acompanhados`.
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is None:
        return _erro(request, SEM_COTACAO)
    agora = db.agora()
    try:
        leitura = contexto.retratos.obter(
            request.app.state.engine, nome, cotacao.usd_to_brl, agora
        )
    except (RuntimeError, PageStructureError) as erro:
        return _erro(request, str(erro))
    if leitura.pagina is None:
        return _erro(request, SEM_RETRATO)
    pagina = leitura.pagina
    indice = contexto.indice.obter()
    try:
        resultado = analyse(pagina, efeito, indice, cotacao.key_brl)
    except ValueError as erro:
        return _erro(request, str(erro))
    retrato_idade = _idade_por_extenso(leitura.buscado_em, agora)
    # A esquerda tem de concordar com a direita: sem isto, clicar noutro
    # efeito da mesma lista (que só troca `#analise`) deixava a marca antiga
    # na esquerda. Aberta depois de resolvida toda a rede acima, pelo mesmo
    # motivo de `_coluna`: a transação do banco tem de ser curta.
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(
            conn, cotacao, indice, usuario.id, agora, selecionado=(nome, efeito),
        )
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_analise_resposta.html",
        context={
            **_contexto_da_analise(resultado, efeito, retrato_idade, leitura.limitando),
            "linhas": linhas,
        },
    )


@dataclass(frozen=True)
class LinhaAcompanhada:
    id: int
    hash_name: str
    efeito: str
    preco: Brl | None
    # Número puro, não texto: o template formata com o filtro `chaves`
    # (vírgula decimal), como o resto da tela.
    premio: float | None
    idade: str | None
    motivo: str | None
    selecionado: bool = False
    # Idade do preço da bp.tf que entrou no `premio` — não a do retrato da
    # Steam. As duas idades pertencem a metades diferentes da conta do ×, e
    # `premio_idade` só vem preenchida quando `premio` também vem.
    premio_idade: str | None = None


def _idade_por_extenso(quando: datetime | None, agora: datetime) -> str:
    """`quando` é `datetime | None` no tipo de `Leitura.buscado_em`: hoje só é
    seguro chamar isto com um valor porque `pagina` e `buscado_em` são
    sempre setados juntos em `preco/retrato.py`, e cada rota já retornou se
    `pagina is None`. Esse invariante vale, mas não está no tipo nem em
    teste — tratar o `None` aqui explicitamente é mais honesto que confiar
    nele silenciosamente."""
    if quando is None:
        return "idade desconhecida"
    minutos = int((agora - quando).total_seconds() // 60)
    if minutos < 1:
        return "agora"
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    return f"{horas} h" if horas < 24 else f"{horas // 24} d"


def linhas_acompanhadas(
    conn, cotacao, indice, usuario_id, agora, selecionado: tuple[str, str] | None = None
) -> list[LinhaAcompanhada]:
    """O que a coluna esquerda mostra, calculado na hora.

    Recebe a cotação e o índice já resolvidos, e não o `Contexto`: os dois são
    carregados sob demanda e podem ir à rede na primeira chamada. Resolvê-los
    aqui dentro seguraria a conexão do banco durante esse download, que é
    justamente o que `test_transacao.py` proíbe.

    Nada de preço guardado: a linha sai do mesmo `analyse` do detalhe, então a
    esquerda nunca discorda da direita.

    `selecionado`, quando dado, é o par `(hash_name, efeito)` aberto agora na
    direita — a linha correspondente sai marcada, para a esquerda dizer de
    qual linha a direita está falando.
    """
    saida = []
    for a in acompanhamento.listar(conn, usuario_id):
        marcado = selecionado is not None and (a.hash_name, a.efeito) == selecionado
        guardado = preco_repo.ler(conn, a.hash_name)
        if guardado is None or cotacao is None:
            saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito, None, None, None,
                                          "sem dado ainda", selecionado=marcado))
            continue
        dados, buscado_em = guardado
        idade = _idade_por_extenso(buscado_em, agora)
        try:
            pagina = serial.de_dict(json.loads(dados))
        except (ValueError, KeyError, TypeError):
            # Retrato salvo numa forma que este processo não lê mais (p.ex.
            # `VERSAO` subiu). Isto é um problema NOSSO, de banco — bem
            # diferente de "sem listagem deste efeito agora", que é uma
            # afirmação sobre o mercado. Separado do `except` de `analyse`
            # logo abaixo por isso: os dois nunca podem soar iguais.
            saida.append(LinhaAcompanhada(
                a.id, a.hash_name, a.efeito, None, None, idade,
                "retrato salvo numa forma antiga; será regravado na próxima busca",
                selecionado=marcado,
            ))
            continue
        try:
            resultado = analyse(pagina, a.efeito, indice, cotacao.key_brl)
        except ValueError:
            saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito, None, None, idade,
                                          "sem listagem deste efeito agora", selecionado=marcado))
            continue
        except Exception as erro:
            # Rede de segurança por linha, não reversão da separação acima:
            # esta função é o caminho crítico de `GET /` e de
            # `DELETE /acompanhar`. Um `KeyError`/`TypeError` de uma linha
            # ruim sem isto derrubaria o painel inteiro — e trancaria a
            # pessoa para fora de remover justo o item que quebrou.
            #
            # Mas rede de segurança silenciosa é rede de segurança que
            # esconde o bug para sempre: `_registra_falha_sob_demanda`, logo
            # acima neste arquivo, já tomou essa decisão para o outro
            # `except Exception` do módulo, com o mesmo argumento. O print
            # é o que o Railway capta no log do serviço.
            print(
                f"[linha-acompanhada] {a.hash_name} ({a.efeito}): "
                f"{type(erro).__name__}: {mensagem_saneada(erro)}",
                flush=True,
            )
            saida.append(LinhaAcompanhada(a.id, a.hash_name, a.efeito, None, None, idade,
                                          "não consegui avaliar esta linha", selecionado=marcado))
            continue
        premio = None
        premio_idade = None
        dias_bptf = resultado.patient.age_days
        if (
            resultado.patient.available
            and resultado.patient.fair_value.cents > 0
            # Mesmo limiar de "vencido" que `_analise.html` usa: o numerador
            # do × vem da Steam (a idade do retrato) e o denominador vem da
            # bp.tf, que pode ter anos. Com a referência vencida, o ×
            # somaria uma idade à outra sem dizer isso — melhor sumir.
            and dias_bptf is not None and dias_bptf <= 365
        ):
            premio = resultado.cheapest.total_price.cents / resultado.patient.fair_value.cents
            premio_idade = f"{dias_bptf} d"
        saida.append(LinhaAcompanhada(
            a.id, a.hash_name, a.efeito, resultado.cheapest.total_price, premio, idade, None,
            selecionado=marcado, premio_idade=premio_idade,
        ))
    return saida


def _coluna(request: Request, usuario_id: int) -> HTMLResponse:
    """Monta a coluna esquerda, resolvendo a rede antes de tocar no banco."""
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    indice = contexto.indice.obter()
    agora = db.agora()
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, cotacao, indice, usuario_id, agora)
    return TEMPLATES.TemplateResponse(
        request=request, name="_acompanhados.html", context={"linhas": linhas}
    )


# Nenhuma destas três rotas declara `conn`: cada uma abre a sua transação
# curta, e `_coluna` pode ir à rede antes de abrir a dela. Declarar `conn`
# como dependência prenderia a conexão durante esse instante.
@ROTEADOR.post("/acompanhar", response_class=HTMLResponse,
               dependencies=[Depends(ses.mesma_origem)])
def acompanhar(request: Request, nome: str = Form(...), efeito: str = Form(...),
               usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    with request.app.state.engine.begin() as conn:
        acompanhamento.adicionar(conn, usuario_id=usuario.id, hash_name=nome,
                                 efeito=efeito, quando=db.agora())
    return _coluna(request, usuario.id)


@ROTEADOR.delete("/acompanhar/{ident}", response_class=HTMLResponse,
                 dependencies=[Depends(ses.mesma_origem)])
def parar_de_acompanhar(request: Request, ident: int,
                        usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    with request.app.state.engine.begin() as conn:
        acompanhamento.remover(conn, usuario.id, ident)
    return _coluna(request, usuario.id)


@ROTEADOR.post("/atualizar/{hash_name:path}", response_class=HTMLResponse,
               dependencies=[Depends(ses.mesma_origem)])
def atualizar(request: Request, hash_name: str,
              usuario: Usuario = Depends(ses.usuario_obrigatorio)):
    contexto = _contexto(request)
    cotacao = contexto.cotacao.obter()
    if cotacao is not None:
        try:
            contexto.retratos.obter(
                request.app.state.engine, hash_name, cotacao.usd_to_brl,
                db.agora(), forcar=True,
            )
        except (RuntimeError, PageStructureError) as erro:
            # O botão ↻ é o que a pessoa aperta bem quando a linha diz "sem
            # dado ainda" — é o caminho com mais chance de achar a Steam
            # ruim, e era o único, entre as quatro rotas que chamam
            # `retratos.obter`, sem captura: timeout, 503 ou HTML mudado
            # virava 500 depois de a network nem ter quebrado de verdade.
            # A coluna segue sem retrato novo, o que já é uma resposta
            # honesta: nada mudou.
            print(f"[atualizar] {hash_name}: {mensagem_saneada(erro)}", flush=True)
    return _coluna(request, usuario.id)


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
