"""Todo o SQL de contas mora aqui.

Nenhuma rota e nenhum serviço escreve SQL: trocar de banco é mexer neste
arquivo e em `db.py`, não no painel.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection

from tf2price import db
from tf2price.contas.modelo import Convite, Sessao, Usuario


def _para_usuario(linha) -> Usuario:
    # bool() explícito: o SQLite devolve 0 e 1, e `admin is True` mentiria.
    return Usuario(
        id=linha.id,
        nome=linha.nome,
        senha_hash=linha.senha_hash,
        admin=bool(linha.admin),
        ativo=bool(linha.ativo),
        criado_em=linha.criado_em,
    )


def criar_usuario(
    conn: Connection, *, nome: str, senha_hash: str, admin: bool, quando: datetime
) -> int:
    resultado = conn.execute(
        insert(db.usuario).values(
            nome=nome, senha_hash=senha_hash, admin=admin, ativo=True, criado_em=quando
        )
    )
    return int(resultado.inserted_primary_key[0])


def usuario_por_nome(conn: Connection, nome: str) -> Usuario | None:
    linha = conn.execute(
        select(db.usuario).where(db.usuario.c.nome == nome)
    ).first()
    return _para_usuario(linha) if linha else None


def usuario_por_id(conn: Connection, usuario_id: int) -> Usuario | None:
    linha = conn.execute(
        select(db.usuario).where(db.usuario.c.id == usuario_id)
    ).first()
    return _para_usuario(linha) if linha else None


def listar_usuarios(conn: Connection) -> list[Usuario]:
    linhas = conn.execute(select(db.usuario).order_by(db.usuario.c.nome)).all()
    return [_para_usuario(linha) for linha in linhas]


def contar_usuarios(conn: Connection) -> int:
    return int(conn.execute(select(func.count()).select_from(db.usuario)).scalar_one())


def definir_ativo(
    conn: Connection, usuario_id: int, ativo: bool, *, so_se_membro: bool = False
) -> bool:
    """Liga ou desliga a conta e diz se o UPDATE alcançou a linha.

    Com `so_se_membro`, o UPDATE só alcança a linha se ela não é admin. É
    assim que um admin comum grava: conferir em Python que o alvo é membro e
    só depois escrever deixaria uma promoção concorrente passar entre as
    duas coisas — as rotas correm em threads de verdade. Mesmo desenho de
    `consumir_convite`.

    `rowcount` conta linhas alcançadas, não valores alterados — desativar
    quem já está desativado devolve True, e é isso que evita um 403 falso
    na rota.
    """
    consulta = update(db.usuario).where(db.usuario.c.id == usuario_id)
    if so_se_membro:
        consulta = consulta.where(db.usuario.c.admin.is_(False))
    return conn.execute(consulta.values(ativo=ativo)).rowcount == 1


def definir_admin(conn: Connection, usuario_id: int, admin: bool) -> None:
    conn.execute(
        update(db.usuario).where(db.usuario.c.id == usuario_id).values(admin=admin)
    )


def trocar_senha(conn: Connection, usuario_id: int, senha_hash: str) -> None:
    conn.execute(
        update(db.usuario)
        .where(db.usuario.c.id == usuario_id)
        .values(senha_hash=senha_hash)
    )


def criar_convite(
    conn: Connection,
    *,
    hash_do_token: str,
    tipo: str,
    concede_admin: bool,
    alvo: int | None,
    criado_por: int | None,
    criado_em: datetime,
    expira_em: datetime,
) -> None:
    conn.execute(
        insert(db.convite).values(
            hash_do_token=hash_do_token,
            tipo=tipo,
            concede_admin=concede_admin,
            alvo=alvo,
            criado_por=criado_por,
            criado_em=criado_em,
            expira_em=expira_em,
            usado_em=None,
            usado_por=None,
        )
    )


def convite_por_hash(conn: Connection, hash_do_token: str) -> Convite | None:
    linha = conn.execute(
        select(db.convite).where(db.convite.c.hash_do_token == hash_do_token)
    ).first()
    if linha is None:
        return None
    return Convite(
        hash_do_token=linha.hash_do_token,
        tipo=linha.tipo,
        concede_admin=bool(linha.concede_admin),
        alvo=linha.alvo,
        criado_por=linha.criado_por,
        criado_em=linha.criado_em,
        expira_em=linha.expira_em,
        usado_em=linha.usado_em,
        usado_por=linha.usado_por,
    )


def consumir_convite(
    conn: Connection, hash_do_token: str, *, usado_em: datetime
) -> bool:
    """Marca o convite como usado se ainda não estava, e diz se conseguiu.

    O `usado_em IS NULL` no WHERE é a atomicidade toda: duas requisições com
    o mesmo link viram dois UPDATE na mesma linha, o banco as serializa, e a
    segunda encontra a linha já marcada e afeta zero linhas. Conferir em
    Python o que o SELECT leu antes deixaria as duas passarem — as rotas
    correm em threads de verdade.

    Quem usou entra depois, por `registrar_quem_usou`: o id de um usuário
    recém-nascido só existe após o INSERT, e o consumo precisa vir antes
    dele.
    """
    resultado = conn.execute(
        update(db.convite)
        .where(
            db.convite.c.hash_do_token == hash_do_token,
            db.convite.c.usado_em.is_(None),
        )
        .values(usado_em=usado_em)
    )
    return resultado.rowcount == 1


def registrar_quem_usou(
    conn: Connection, hash_do_token: str, *, usado_por: int
) -> None:
    """Completa o consumo com o id de quem usou. Roda na mesma transação."""
    conn.execute(
        update(db.convite)
        .where(db.convite.c.hash_do_token == hash_do_token)
        .values(usado_por=usado_por)
    )


def criar_sessao(
    conn: Connection,
    *,
    hash_do_token: str,
    usuario_id: int,
    criado_em: datetime,
    expira_em: datetime,
) -> None:
    conn.execute(
        insert(db.sessao).values(
            hash_do_token=hash_do_token,
            usuario_id=usuario_id,
            criado_em=criado_em,
            expira_em=expira_em,
        )
    )


def sessao_por_hash(conn: Connection, hash_do_token: str) -> Sessao | None:
    linha = conn.execute(
        select(db.sessao).where(db.sessao.c.hash_do_token == hash_do_token)
    ).first()
    if linha is None:
        return None
    return Sessao(
        hash_do_token=linha.hash_do_token,
        usuario_id=linha.usuario_id,
        criado_em=linha.criado_em,
        expira_em=linha.expira_em,
    )


def apagar_sessao(conn: Connection, hash_do_token: str) -> None:
    conn.execute(delete(db.sessao).where(db.sessao.c.hash_do_token == hash_do_token))


def apagar_sessoes_do_usuario(conn: Connection, usuario_id: int) -> None:
    conn.execute(delete(db.sessao).where(db.sessao.c.usuario_id == usuario_id))


def registrar_tentativa(conn: Connection, nome: str, quando: datetime) -> None:
    conn.execute(insert(db.tentativa).values(nome=nome, quando=quando))


def contar_tentativas(conn: Connection, nome: str, desde: datetime) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(db.tentativa)
            .where(db.tentativa.c.nome == nome, db.tentativa.c.quando >= desde)
        ).scalar_one()
    )


def limpar_tentativas(conn: Connection, nome: str) -> None:
    conn.execute(delete(db.tentativa).where(db.tentativa.c.nome == nome))


def limpar_tentativas_antigas(conn: Connection, antes_de: datetime) -> None:
    """Apaga tentativas fora da janela do freio, de qualquer nome.

    É o único caminho de limpeza para quem erra o nome (nunca acerta a
    senha, então nunca passa por `limpar_tentativas`): sem isto, a tabela só
    cresce.
    """
    conn.execute(delete(db.tentativa).where(db.tentativa.c.quando < antes_de))
