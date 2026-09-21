"""A consulta de Unusual: contexto e rotas.

O retrato compartilhado da página da Steam mora em `preco/retrato.py`; aqui
só há transporte e apresentação. O que decide número continua em
`lookup/analysis.py`, que não sabe que existe usuário.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.engine import Engine

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
        self._trava = threading.Lock()

    def obter(self) -> PriceIndex | None:
        # O atalho antes da trava: depois de carregado, isto é só uma leitura
        # de referência, e põr toda requisição da vida do processo a
        # disputar uma trava por ela seria pagar caro pelo caso raro.
        if self._indice is not None:
            return self._indice
        # A trava cobre a busca inteira: quem chegar durante ela espera o
        # resultado em vez de sair buscar o mesmo de novo. É o que faz o
        # aquecimento valer — senão a primeira visita, que chega junto com
        # ele, dispararia uma segunda busca idêntica.
        with self._trava:
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

# Mesma validade do retrato, pelo mesmo raciocínio: 15 minutos é o que separa
# "recente" de "vale pedir de novo" neste projeto. Uma cotação mais velha que
# isso manda buscar — mas, se a busca falhar, a velha continua servindo, com
# a idade à vista.
VALIDADE_COTACAO = timedelta(minutes=15)


@dataclass(frozen=True)
class Cotacao:
    """Preço da chave, taxa do dólar e quando isso foi lido da Steam.

    `buscado_em` não é enfeite nem é opcional: desde que a cotação passou a
    atravessar o deploy no banco, um número na tela pode ser de minutos ou de
    horas atrás, e a regra deste projeto é que todo número diga de quando é.
    Exigir o campo no construtor é o que impede uma cotação anônima de
    aparecer no timbre sem idade.
    """

    key_brl: Brl
    usd_to_brl: float
    buscado_em: datetime

    @property
    def usd_brl_formatado(self) -> Brl:
        return Brl.from_float(self.usd_to_brl)


class CotacaoSobDemanda:
    """A cotação da chave: memória, banco e, só em último caso, a Steam.

    O preço e a taxa vêm juntos porque saem do mesmo cliente e são inúteis
    separados: preço em chaves sem taxa de conversão não vira tela.

    Guardar no banco existe por uma medição, não por gosto: em 21/09/2026 um
    deploy real levou 429 da Steam na primeira requisição do processo — o IP
    do Railway já estava limitado antes de a gente pedir —, gastou 44,8s de
    backoff e o painel ficou 5 minutos sem preço de chave nenhum. Com a
    última cotação conhecida no banco, o processo novo já nasce com um número
    utilizável e não precisa falar com a Steam para abrir a tela.

    A ordem é de fora para dentro: memória, banco, rede. E a degradação é
    para o lado honesto — quando a busca falha, a cotação velha continua
    servindo com `buscado_em` intacto, e quem mostra diz a idade.

    Duas portas, e a divisão entre elas é a parte que importa: `obter` só lê
    (memória, banco) e é o que as rotas chamam; `renovar` é quem vai à rede,
    e só o thread de fundo chama. Nenhuma requisição espera a Steam por causa
    da cotação — ver o histórico medido na docstring de `obter`.
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
        self._trava = threading.Lock()

    def obter(self, engine: Engine) -> Cotacao | None:
        """Só lê: memória, depois banco. **Nunca** vai à rede.

        Esta linha foi aprendida caro. Quando `obter` ainda buscava, a
        validade de 15 min significava que, a cada 15 minutos, a primeira
        pessoa a abrir a página pagava a escada de backoff da Steam dentro
        do carregamento. Medido no log HTTP do Railway em 21/09/2026:
        `GET / 499 30173ms` — trinta segundos, e a pessoa desistiu — e um
        `GET / 200 11815ms` logo atrás, que era outra requisição esperando
        na trava o resto da busca da primeira. Todas as outras: 8 a 13 ms.

        A validade continua valendo para o *dado*, mas ela não pode ser
        cobrada de quem está olhando a tela: quem renova é `renovar`, do
        thread de fundo. Aqui devolve-se o que há, velho ou novo, e quem
        mostra diz a idade.
        """
        em_memoria = self._cotacao
        if em_memoria is not None:
            return em_memoria
        with self._trava:
            if self._cotacao is None:
                # Memória vazia é processo novo: o banco tem a última que
                # este serviço conheceu, e ler isso é um SELECT.
                self._cotacao = self._do_banco(engine)
            return self._cotacao

    def renovar(self, engine: Engine, quando: datetime) -> Cotacao | None:
        """Busca na Steam se o que há está velho. **Só o fundo chama isto.**

        Recebe o `engine`, e não uma conexão, pelo mesmo motivo de
        `Retratos.obter`: a busca leva segundos, e transações curtas com a
        rede **entre** elas é o que mantém zero conexões emprestadas durante
        esse tempo — o que `test_transacao.py` mede.
        """
        with self._trava:
            if self._cotacao is None:
                self._cotacao = self._do_banco(engine)
            # `guardada` é o que sobra se a rede não ajudar.
            guardada = self._cotacao
            if guardada is not None and self._recente(guardada, quando):
                return guardada
            if self._relogio() < self._proxima_tentativa:
                return guardada
            try:
                nova = Cotacao(
                    key_brl=self._steam.key_price(),
                    usd_to_brl=self._steam.usd_to_brl(),
                    buscado_em=quando,
                )
            except Exception as erro:
                _registra_falha_sob_demanda("CotacaoSobDemanda", erro, self._espera)
                self._proxima_tentativa = self._relogio() + self._espera
                # A velha, e não None: uma cotação de 20 minutos atrás com a
                # idade escrita na tela é mais útil que "indisponível", e a
                # chave não anda tanto nesse tempo.
                return guardada

            self._cotacao = nova
            with engine.begin() as conn:
                preco_repo.guardar_cotacao(
                    conn, nova.key_brl.cents, nova.usd_to_brl, quando
                )
            # Sucesso também vira linha de log: sem isto, o log conta quando
            # a cotação falhou e nunca quando ela voltou — e "voltou?" é
            # exatamente a pergunta que se faz olhando este log.
            print(
                f"[cotação] chave {nova.key_brl}, dólar {nova.usd_brl_formatado}"
                f" — guardada",
                flush=True,
            )
            return nova

    def _recente(self, cotacao: Cotacao, quando: datetime) -> bool:
        return quando - cotacao.buscado_em <= VALIDADE_COTACAO

    def _do_banco(self, engine: Engine) -> Cotacao | None:
        with engine.begin() as conn:
            guardada = preco_repo.ler_cotacao(conn)
        if guardada is None:
            return None
        centavos, taxa, buscado_em = guardada
        return Cotacao(
            key_brl=Brl.from_cents(centavos), usd_to_brl=taxa, buscado_em=buscado_em
        )


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
    # morria junto com ela). Depois o retrato passou a persistir e o
    # descasamento virou real: o processo novo de cada deploy calculava outra
    # `usd_to_brl` e, por até `VALIDADE` (15 min), servia o retrato antigo
    # convertido pela taxa velha ao lado de uma cotação nova.
    #
    # Desde que a cotação também persiste, o deploy deixou de ser o gatilho:
    # o processo novo herda a MESMA taxa, e as duas coisas agora têm a mesma
    # validade de 15 min. Sobrou a janela de quando a cotação é renovada e um
    # retrato de antes dela ainda vale. O erro numérico é desprezível (o real
    # não anda tanto em 15 min), mas é real — e é por isso que este
    # comentário existe: para quem for mexer aqui não presumir, pelo nome da
    # chave do retrato, que ela já inclui a taxa.
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
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    # Índice e cotação resolvidos antes de abrir a conexão, pelo mesmo motivo
    # de `_coluna`: os dois podem ir à rede na primeira chamada, e a
    # transação da lista de acompanhados tem de ser curta.
    indice = contexto.indice.obter()
    with request.app.state.engine.begin() as conn:
        linhas = linhas_acompanhadas(conn, cotacao, indice, usuario.id, agora)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="painel.html",
        context={
            "usuario": usuario,
            "cotacao": cotacao,
            # A idade da cotação no timbre. Antes de ela atravessar o deploy
            # no banco, era sempre "agora" por construção e não havia o que
            # dizer; agora ela pode ser de horas atrás, e aí omitir a idade
            # seria a única mentira da tela.
            "cotacao_idade": (
                _idade_por_extenso(cotacao.buscado_em, agora) if cotacao else None
            ),
            "linhas": linhas,
        },
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
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    if cotacao is None:
        return _erro(request, SEM_COTACAO, limpar_analise=True)
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
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    if cotacao is None:
        return _erro(request, SEM_COTACAO)
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
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    indice = contexto.indice.obter()
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
    agora = db.agora()
    cotacao = contexto.cotacao.obter(request.app.state.engine)
    if cotacao is not None:
        try:
            contexto.retratos.obter(
                request.app.state.engine, hash_name, cotacao.usd_to_brl,
                agora, forcar=True,
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
