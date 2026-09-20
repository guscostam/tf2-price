"""As regras de conta. Recebe conexão, não abre nenhuma; não escreve SQL.

Todo instante entra por parâmetro (`quando`) em vez de vir de `datetime.now`,
pelo mesmo motivo que `lookup/analysis` faz isso: teste de expiração precisa
mentir sobre o relógio sem esperar sete dias.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.engine import Connection

from tf2price.contas import repositorio as repo
from tf2price.contas import senhas, tokens
from tf2price.contas.modelo import Usuario

VALIDADE_CONVITE = timedelta(days=7)
VALIDADE_CONVITE_DE_PARTIDA = timedelta(hours=24)
VALIDADE_SESSAO = timedelta(days=30)
JANELA_DO_FREIO = timedelta(minutes=15)
FALHAS_ATE_BLOQUEIO = 5

TIPO_CONTA = "conta"
TIPO_REDEFINICAO = "redefinicao"


class ErroDeConta(Exception):
    """Raiz dos erros esperados de conta."""


class ConviteInvalido(ErroDeConta):
    """Inexistente, expirado ou já usado — a tela não distingue os três."""


class NomeEmUso(ErroDeConta):
    pass


class CredenciaisInvalidas(ErroDeConta):
    """Nome que não existe ou senha errada — a tela não distingue os dois."""


class ContaInativa(ErroDeConta):
    pass


class ContaBloqueada(ErroDeConta):
    pass


def convidar(
    conn: Connection,
    *,
    criado_por: int | None,
    quando: datetime,
    tipo: str = TIPO_CONTA,
    concede_admin: bool = False,
    alvo: int | None = None,
    validade: timedelta | None = None,
) -> str:
    """Cria o convite e devolve o token em claro, que só existe no link."""
    claro, resumo = tokens.novo()
    repo.criar_convite(
        conn,
        hash_do_token=resumo,
        tipo=tipo,
        concede_admin=concede_admin,
        alvo=alvo,
        criado_por=criado_por,
        criado_em=quando,
        expira_em=quando + (validade or VALIDADE_CONVITE),
    )
    return claro


def convite_de_partida(conn: Connection, quando: datetime) -> str | None:
    """Primeiro acesso: com o banco vazio, gera um convite de administrador.

    Devolve `None` quando já existe alguém — assim a subida pode chamar isto
    sempre, sem risco de abrir uma porta num painel já povoado.
    """
    if repo.contar_usuarios(conn) > 0:
        return None
    return convidar(
        conn,
        criado_por=None,
        quando=quando,
        concede_admin=True,
        validade=VALIDADE_CONVITE_DE_PARTIDA,
    )


def _convite_utilizavel(conn: Connection, token: str, tipo: str, quando: datetime):
    convite = repo.convite_por_hash(conn, tokens.hash_de(token))
    if convite is None or convite.tipo != tipo:
        raise ConviteInvalido("convite inválido")
    if convite.usado_em is not None:
        raise ConviteInvalido("convite inválido")
    if convite.expira_em <= quando:
        raise ConviteInvalido("convite inválido")
    return convite


def aceitar_convite(
    conn: Connection, token: str, *, nome: str, senha: str, quando: datetime
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_CONTA, quando)
    nome = nome.strip()
    if not nome:
        raise NomeEmUso("escolha um nome")
    if repo.usuario_por_nome(conn, nome) is not None:
        raise NomeEmUso("esse nome já está em uso")

    ident = repo.criar_usuario(
        conn,
        nome=nome,
        senha_hash=senhas.gerar(senha),
        admin=convite.concede_admin,
        quando=quando,
    )
    repo.marcar_convite_usado(
        conn, convite.hash_do_token, usado_em=quando, usado_por=ident
    )
    return repo.usuario_por_id(conn, ident)


def redefinir(
    conn: Connection, token: str, *, senha: str, quando: datetime
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_REDEFINICAO, quando)
    if convite.alvo is None:
        raise ConviteInvalido("convite inválido")

    repo.trocar_senha(conn, convite.alvo, senhas.gerar(senha))
    # Trocar a senha derruba o que já estava aberto: se a troca foi por
    # suspeita, deixar a sessão antiga viva anularia a troca.
    repo.apagar_sessoes_do_usuario(conn, convite.alvo)
    repo.marcar_convite_usado(
        conn, convite.hash_do_token, usado_em=quando, usado_por=convite.alvo
    )
    return repo.usuario_por_id(conn, convite.alvo)


def entrar(conn: Connection, *, nome: str, senha: str, quando: datetime) -> str:
    """Devolve o token de sessão em claro, que vai para o cookie."""
    nome = nome.strip()
    if repo.contar_tentativas(conn, nome, quando - JANELA_DO_FREIO) >= FALHAS_ATE_BLOQUEIO:
        raise ContaBloqueada("tentativas demais; espere alguns minutos")

    usuario = repo.usuario_por_nome(conn, nome)
    if usuario is None or not senhas.confere(usuario.senha_hash, senha):
        repo.registrar_tentativa(conn, nome, quando)
        raise CredenciaisInvalidas("nome ou senha incorretos")
    if not usuario.ativo:
        raise ContaInativa("esta conta está desativada")

    repo.limpar_tentativas(conn, nome)
    claro, resumo = tokens.novo()
    repo.criar_sessao(
        conn,
        hash_do_token=resumo,
        usuario_id=usuario.id,
        criado_em=quando,
        expira_em=quando + VALIDADE_SESSAO,
    )
    return claro


def usuario_da_sessao(
    conn: Connection, token: str, quando: datetime
) -> Usuario | None:
    if not token:
        return None
    sessao = repo.sessao_por_hash(conn, tokens.hash_de(token))
    if sessao is None or sessao.expira_em <= quando:
        return None
    usuario = repo.usuario_por_id(conn, sessao.usuario_id)
    if usuario is None or not usuario.ativo:
        return None
    return usuario


def sair(conn: Connection, token: str) -> None:
    if token:
        repo.apagar_sessao(conn, tokens.hash_de(token))
