from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.painel.consulta import CotacaoSobDemanda
from tf2price.preco import repositorio as preco_repo
from tf2price.preco.retrato import Retratos

from tests.painel.conftest import NOME, _contexto, _pagina, cliente_logado


def _contar_conexoes(motor) -> dict:
    """Conta conexões emprestadas pelo pool, a qualquer momento.

    Não depende de dialeto: mede a propriedade que interessa ao Postgres —
    conexão emprestada é conexão indisponível para os outros — sem depender
    de o SQLite levantar erro, que ele não levanta em leitura pura.
    """
    estado = {"emprestadas": 0}
    event.listen(motor, "checkout", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] + 1))
    event.listen(motor, "checkin", lambda *a: estado.__setitem__("emprestadas", estado["emprestadas"] - 1))
    return estado


class _PaginasQueObservamOPool:
    """Dublê que anota quantas conexões estavam emprestadas quando foi chamado.

    É o instante que importa: aqui, na aplicação de verdade, o processo está
    baixando dezenas de MB da backpack.tf com timeout de 180 s.
    """

    def __init__(self, contador, pagina):
        self.contador = contador
        self.pagina = pagina
        self.emprestadas_durante_o_io = None

    def item_page(self, hash_name, usd_to_brl):
        self.emprestadas_durante_o_io = self.contador["emprestadas"]
        return self.pagina


def test_nenhuma_conexao_fica_emprestada_durante_o_io(engine):
    """Uma consulta lenta não pode prender conexão do banco sem usá-la.

    A primeira carga do índice baixa dezenas de MB. Se a transação da
    requisição ficar aberta durante isso, algumas pessoas clicando depois de
    um deploy esgotam o pool do Postgres com conexões ociosas.

    Usa um `Retratos` de verdade, não `_RetratosFalsos` (o padrão de
    `_contexto`): o duplo busca direto na página falsa sem nunca abrir uma
    conexão, então mediria a garantia contra um código que não toca o banco
    — provando zero de qualquer jeito. É exatamente na rota que fala com a
    Steam que a garantia precisa valer contra o `Retratos` de verdade.
    """
    contador = _contar_conexoes(engine)
    ctx = _contexto()
    paginas = _PaginasQueObservamOPool(contador, _pagina())
    ctx.paginas = paginas
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)

    resposta = cliente.get("/efeitos", params={"nome": NOME})

    assert resposta.status_code == 200
    assert paginas.emprestadas_durante_o_io == 0


class _SteamQueObservaOPool:
    """Dublê do `SteamClient` que anota o pool durante a própria busca."""

    def __init__(self, contador):
        self.contador = contador
        self.emprestadas_durante_o_io = None

    def key_price(self) -> Brl:
        self.emprestadas_durante_o_io = self.contador["emprestadas"]
        return Brl.from_float(11.73)

    def usd_to_brl(self) -> float:
        return 5.0


def test_a_cotacao_nao_prende_conexao_durante_o_io(engine):
    """A mesma garantia para `CotacaoSobDemanda.renovar`, que lê e grava no
    banco em volta de uma busca na Steam.

    Chamado direto, e não por uma rota, porque quem chama `renovar` é o
    thread de fundo: nenhuma requisição faz isso mais — e é esse justamente
    o ponto do teste vizinho `test_rota_nunca_dispara_busca_de_cotacao`.

    Com uma `CotacaoSobDemanda` de verdade (o `_CotacaoFalsa` do `_contexto`
    não toca o banco e mediria zero de qualquer jeito), isto reprova a forma
    cómoda e errada: uma transação aberta em volta da busca, para ler o
    guardado e gravar o novo sem abrir duas.
    """
    contador = _contar_conexoes(engine)
    steam = _SteamQueObservaOPool(contador)
    sob = CotacaoSobDemanda(steam)

    assert sob.renovar(engine, db.agora()) is not None
    assert steam.emprestadas_durante_o_io == 0


def test_rota_nunca_dispara_busca_de_cotacao(engine):
    """O conserto da regressão, prendido no nível da rota.

    Com cotação vencida no banco (ou nenhuma), abrir a página não pode
    render uma única requisição à Steam. Medido no Railway antes do
    conserto: `GET / 499 30173ms`.
    """
    with engine.begin() as conn:
        preco_repo.guardar_cotacao(
            conn, 1000, 5.0, db.agora() - timedelta(days=1)
        )
    steam = _SteamQueObservaOPool(_contar_conexoes(engine))
    ctx = _contexto()
    ctx.cotacao = CotacaoSobDemanda(steam)
    cliente = cliente_logado(engine, ctx)

    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert steam.emprestadas_durante_o_io is None, (
        "a rota foi à Steam buscar cotação: a regressão dos 30s voltou"
    )
    # E a página mostra o número velho com a idade dele, em vez de nada.
    assert "lida <b>1 d</b>" in resposta.text


def test_rota_de_escrita_continua_funcionando(engine):
    """A mudança não pode quebrar quem legitimamente escreve no banco."""
    cliente = cliente_logado(engine, _contexto())
    assert cliente.get("/admin").status_code == 200
    assert cliente.post("/admin/convite").status_code == 200
