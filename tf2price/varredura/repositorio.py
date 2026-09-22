"""SQL da varredura: configuração, assinaturas, listagens e rodadas.

Só a varredura escreve em `varredura_nome` e `listagem_varrida`, e nunca há
duas rodadas ao mesmo tempo (trava em `agendador.py`). Por isso os upserts
daqui não precisam do savepoint de `preco/repositorio.py`. A configuração é
a exceção: dois admins podem salvar juntos, e ela usa o savepoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.sources.steam_page import PageListing

MOTIVO_OK = "ok"
MOTIVO_429 = "429"
MOTIVO_ERRO = "erro"
MOTIVO_INTERROMPIDA = "interrompida"
MOTIVO_CANCELADA = "cancelada"

INTERVALO_MINIMO_MIN = 60
IDADE_MINIMA_FUNDA_H = 1
LINHA_DA_CONFIG = 1


# --- configuração -----------------------------------------------------------

@dataclass(frozen=True)
class Config:
    ligada: bool
    intervalo_min: int
    idade_max_funda_h: int


PADRAO = Config(ligada=False, intervalo_min=180, idade_max_funda_h=24)


def ler_config(conn: Connection) -> Config:
    t = db.varredura_config
    linha = conn.execute(select(t).where(t.c.id == LINHA_DA_CONFIG)).first()
    if linha is None:
        return PADRAO
    return Config(bool(linha.ligada), int(linha.intervalo_min), int(linha.idade_max_funda_h))


def _atualizar_config(conn: Connection, config: Config, quando: datetime):
    t = db.varredura_config
    return conn.execute(
        update(t).where(t.c.id == LINHA_DA_CONFIG).values(
            ligada=config.ligada,
            intervalo_min=config.intervalo_min,
            idade_max_funda_h=config.idade_max_funda_h,
            alterado_em=quando,
        )
    )


def gravar_config(conn: Connection, config: Config, quando: datetime) -> None:
    """Recusa abaixo do mínimo aqui também, e não só na rota: o mínimo existe
    para proteger a consulta do 429, e uma segunda porta de escrita não pode
    contorná-lo."""
    if config.intervalo_min < INTERVALO_MINIMO_MIN:
        raise ValueError(f"intervalo abaixo de {INTERVALO_MINIMO_MIN} min")
    if config.idade_max_funda_h < IDADE_MINIMA_FUNDA_H:
        raise ValueError(f"idade da leitura funda abaixo de {IDADE_MINIMA_FUNDA_H} h")
    if _atualizar_config(conn, config, quando).rowcount == 0:
        try:
            with conn.begin_nested():
                conn.execute(insert(db.varredura_config).values(
                    id=LINHA_DA_CONFIG,
                    ligada=config.ligada,
                    intervalo_min=config.intervalo_min,
                    idade_max_funda_h=config.idade_max_funda_h,
                    alterado_em=quando,
                ))
        except IntegrityError:
            _atualizar_config(conn, config, quando)


# --- assinaturas ------------------------------------------------------------

@dataclass(frozen=True)
class Assinatura:
    preco_usd_cents: int
    n_listagens: int
    funda_em: datetime | None


def ler_assinatura(conn: Connection, hash_name: str) -> Assinatura | None:
    t = db.varredura_nome
    linha = conn.execute(
        select(t.c.preco_usd_cents, t.c.n_listagens, t.c.funda_em).where(t.c.hash_name == hash_name)
    ).first()
    if linha is None:
        return None
    return Assinatura(int(linha.preco_usd_cents), int(linha.n_listagens), linha.funda_em)


def gravar_vista(
    conn: Connection, hash_name: str, preco_usd_cents: int, n_listagens: int, quando: datetime
) -> None:
    """Grava o que a passada rasa viu. Não toca `funda_em`: ter visto o nome na
    busca não é ter lido as listagens dele."""
    t = db.varredura_nome
    resultado = conn.execute(
        update(t).where(t.c.hash_name == hash_name).values(
            preco_usd_cents=preco_usd_cents, n_listagens=n_listagens, visto_em=quando
        )
    )
    if resultado.rowcount == 0:
        conn.execute(insert(t).values(
            hash_name=hash_name,
            preco_usd_cents=preco_usd_cents,
            n_listagens=n_listagens,
            n_guardadas=0,
            visto_em=quando,
            funda_em=None,
        ))


def marcar_para_funda(conn: Connection, hash_name: str) -> None:
    """Zera `funda_em` sem tocar a assinatura. Usada quando a passada rasa vê
    a assinatura de um nome mudar: se a leitura funda não terminar nesta
    rodada (429, página quebrada, transporte, reinício), a regra `funda_em is
    None` de `_precisa_funda` garante que a próxima rodada tente de novo, em
    vez de esperar `idade_max_funda_h` porque a assinatura nova já foi
    gravada e parece recente."""
    t = db.varredura_nome
    conn.execute(update(t).where(t.c.hash_name == hash_name).values(funda_em=None))


def substituir_listagens(
    conn: Connection, hash_name: str, listagens: list[PageListing], quando: datetime
) -> None:
    """Troca TODAS as listagens do nome pelas da leitura nova.

    Listagem vendida ou retirada some junto: nunca fica na tela uma listagem
    que a última leitura não viu.
    """
    t = db.listagem_varrida
    conn.execute(delete(t).where(t.c.hash_name == hash_name))
    vistas: set[str] = set()
    linhas = []
    for l in listagens:
        if not l.listing_id or l.listing_id in vistas:
            continue
        vistas.add(l.listing_id)
        linhas.append({
            "listing_id": l.listing_id,
            "hash_name": hash_name,
            "efeito": l.effect,
            "preco_cents": l.total_price.cents,
            "icone": l.icon_url,
            "lido_em": quando,
        })
    if linhas:
        conn.execute(insert(t), linhas)
    n = db.varredura_nome
    conn.execute(
        update(n).where(n.c.hash_name == hash_name).values(funda_em=quando, n_guardadas=len(linhas))
    )


def apagar_nao_vistos_desde(conn: Connection, limite: datetime) -> int:
    """Apaga nomes (e suas listagens) que a busca não viu desde `limite`."""
    n = db.varredura_nome
    sumidos = select(n.c.hash_name).where(n.c.visto_em < limite)
    conn.execute(delete(db.listagem_varrida).where(db.listagem_varrida.c.hash_name.in_(sumidos)))
    return conn.execute(delete(n).where(n.c.visto_em < limite)).rowcount


# --- rodadas ----------------------------------------------------------------

@dataclass(frozen=True)
class Rodada:
    id: int
    inicio: datetime
    fim: datetime | None
    nomes_lidos: int
    fundas_feitas: int
    falhas: int
    motivo_parada: str | None


def _rodada(linha) -> Rodada:
    return Rodada(
        id=int(linha.id),
        inicio=linha.inicio,
        fim=linha.fim,
        nomes_lidos=int(linha.nomes_lidos),
        fundas_feitas=int(linha.fundas_feitas),
        falhas=int(linha.falhas),
        motivo_parada=linha.motivo_parada,
    )


def abrir_rodada(conn: Connection, quando: datetime) -> int:
    resultado = conn.execute(insert(db.varredura_rodada).values(
        inicio=quando, nomes_lidos=0, fundas_feitas=0, falhas=0
    ))
    return int(resultado.inserted_primary_key[0])


def atualizar_progresso(
    conn: Connection, rodada_id: int, *, nomes_lidos: int, fundas_feitas: int, falhas: int
) -> None:
    t = db.varredura_rodada
    conn.execute(update(t).where(t.c.id == rodada_id).values(
        nomes_lidos=nomes_lidos, fundas_feitas=fundas_feitas, falhas=falhas
    ))


def fechar_rodada(
    conn: Connection, rodada_id: int, quando: datetime, *,
    nomes_lidos: int, fundas_feitas: int, falhas: int, motivo: str,
) -> None:
    t = db.varredura_rodada
    conn.execute(update(t).where(t.c.id == rodada_id).values(
        fim=quando, nomes_lidos=nomes_lidos, fundas_feitas=fundas_feitas,
        falhas=falhas, motivo_parada=motivo,
    ))


def fechar_abertas(conn: Connection, quando: datetime) -> int:
    """Na subida: rodada sem fim é de um processo que morreu no meio dela, e o
    andamento dela não descreve mais nada que esteja acontecendo."""
    t = db.varredura_rodada
    fechadas = conn.execute(
        update(t).where(t.c.fim.is_(None)).values(fim=quando, motivo_parada=MOTIVO_INTERROMPIDA)
    ).rowcount
    limpar_andamento(conn)
    return fechadas


def ultimas_rodadas(conn: Connection, n: int = 10) -> list[Rodada]:
    t = db.varredura_rodada
    return [_rodada(l) for l in conn.execute(
        select(t).order_by(t.c.inicio.desc(), t.c.id.desc()).limit(n)
    )]


def ultima_rodada(conn: Connection) -> Rodada | None:
    rodadas = ultimas_rodadas(conn, 1)
    return rodadas[0] if rodadas else None


def ultima_completa(conn: Connection) -> Rodada | None:
    t = db.varredura_rodada
    linha = conn.execute(
        select(t).where(t.c.motivo_parada == MOTIVO_OK)
        .order_by(t.c.inicio.desc(), t.c.id.desc()).limit(1)
    ).first()
    return _rodada(linha) if linha else None


MANTER_RODADAS = 20


def podar_rodadas(conn: Connection, manter: int = MANTER_RODADAS) -> int:
    """Apaga rodadas terminadas antigas. Ficam as `manter` mais recentes e a
    última completa, mesmo antiga: é o início dela que decide quais nomes
    sumiram do mercado (`executar_rodada`). Rodada aberta nunca sai.

    Os ids a guardar são lidos antes, em Python, para o DELETE não depender
    de LIMIT dentro de subconsulta, que cada dialeto trata de um jeito.
    """
    t = db.varredura_rodada
    guardar = {i for (i,) in conn.execute(
        select(t.c.id).order_by(t.c.inicio.desc(), t.c.id.desc()).limit(manter)
    )}
    completa = ultima_completa(conn)
    if completa is not None:
        guardar.add(completa.id)
    consulta = delete(t).where(t.c.fim.is_not(None))
    if guardar:
        consulta = consulta.where(t.c.id.not_in(guardar))
    return conn.execute(consulta).rowcount


# --- leitura para a página --------------------------------------------------

@dataclass(frozen=True)
class ListagemVarrida:
    listing_id: str
    hash_name: str
    efeito: str | None
    preco: Brl
    icone: str | None
    lido_em: datetime
    mais_na_steam: int


def listar_listagens(
    conn: Connection, *, texto: str = "", efeito: str = "",
    preco_min: Brl | None = None, preco_max: Brl | None = None,
) -> list[ListagemVarrida]:
    l = db.listagem_varrida
    n = db.varredura_nome
    consulta = select(
        l, (n.c.n_listagens - n.c.n_guardadas).label("mais_na_steam")
    ).select_from(l.join(n, l.c.hash_name == n.c.hash_name))
    if texto.strip():
        consulta = consulta.where(
            func.lower(l.c.hash_name).contains(texto.strip().lower(), autoescape=True)
        )
    if efeito:
        consulta = consulta.where(l.c.efeito == efeito)
    if preco_min is not None:
        consulta = consulta.where(l.c.preco_cents >= preco_min.cents)
    if preco_max is not None:
        consulta = consulta.where(l.c.preco_cents <= preco_max.cents)
    consulta = consulta.order_by(l.c.hash_name, l.c.preco_cents, l.c.listing_id)
    return [
        ListagemVarrida(
            listing_id=linha.listing_id,
            hash_name=linha.hash_name,
            efeito=linha.efeito,
            preco=Brl(int(linha.preco_cents)),
            icone=linha.icone,
            lido_em=linha.lido_em,
            mais_na_steam=max(0, int(linha.mais_na_steam)),
        )
        for linha in conn.execute(consulta)
    ]


def efeitos_varridos(conn: Connection) -> list[str]:
    l = db.listagem_varrida
    return [e for (e,) in conn.execute(
        select(l.c.efeito).where(l.c.efeito.is_not(None)).distinct().order_by(l.c.efeito)
    )]


@dataclass(frozen=True)
class Cobertura:
    nomes: int
    listagens: int


def cobertura(conn: Connection) -> Cobertura:
    # Nome coberto é nome com listagem guardada: um lido a fundo cuja
    # página veio vazia não cobre nada na tela.
    l = db.listagem_varrida
    nomes = conn.execute(select(func.count(func.distinct(l.c.hash_name)))).scalar_one()
    listagens = conn.execute(select(func.count()).select_from(db.listagem_varrida)).scalar_one()
    return Cobertura(nomes=int(nomes), listagens=int(listagens))


# --- andamento da rodada em curso ------------------------------------------

FASE_COTACAO = "cotacao"
FASE_BUSCA = "busca"
FASE_PAGINAS = "paginas"
LINHA_DO_ANDAMENTO = 1

_CAMPOS_DO_ANDAMENTO = frozenset({
    "fase", "paginas_busca_lidas", "paginas_busca_total", "itens_lidos",
    "itens_total", "pausado_ate", "pausas_seguidas",
})


@dataclass(frozen=True)
class Andamento:
    rodada_id: int
    fase: str
    paginas_busca_lidas: int
    paginas_busca_total: int | None
    itens_lidos: int
    itens_total: int | None
    pausado_ate: datetime | None
    pausas_seguidas: int
    atualizado_em: datetime


def iniciar_andamento(conn: Connection, rodada_id: int, quando: datetime) -> None:
    t = db.varredura_andamento
    conn.execute(delete(t))
    conn.execute(insert(t).values(
        id=LINHA_DO_ANDAMENTO, rodada_id=rodada_id, fase=FASE_COTACAO,
        paginas_busca_lidas=0, paginas_busca_total=None, itens_lidos=0,
        itens_total=None, pausado_ate=None, pausas_seguidas=0, atualizado_em=quando,
    ))


def atualizar_andamento(conn: Connection, quando: datetime, **campos) -> None:
    desconhecidos = set(campos) - _CAMPOS_DO_ANDAMENTO
    if desconhecidos:
        raise TypeError(f"campos de andamento desconhecidos: {sorted(desconhecidos)}")
    t = db.varredura_andamento
    conn.execute(
        update(t).where(t.c.id == LINHA_DO_ANDAMENTO).values(**campos, atualizado_em=quando)
    )


def ler_andamento(conn: Connection) -> Andamento | None:
    t = db.varredura_andamento
    linha = conn.execute(select(t).where(t.c.id == LINHA_DO_ANDAMENTO)).first()
    if linha is None:
        return None
    return Andamento(
        rodada_id=int(linha.rodada_id),
        fase=linha.fase,
        paginas_busca_lidas=int(linha.paginas_busca_lidas),
        paginas_busca_total=linha.paginas_busca_total,
        itens_lidos=int(linha.itens_lidos),
        itens_total=linha.itens_total,
        pausado_ate=linha.pausado_ate,
        pausas_seguidas=int(linha.pausas_seguidas),
        atualizado_em=linha.atualizado_em,
    )


def limpar_andamento(conn: Connection) -> None:
    conn.execute(delete(db.varredura_andamento))
