"""As regras de conta. Recebe conexão, não abre nenhuma; não escreve SQL.

Todo instante entra por parâmetro (`quando`) em vez de vir de `datetime.now`,
pelo mesmo motivo que `lookup/analysis` faz isso: teste de expiração precisa
mentir sobre o relógio sem esperar sete dias.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.engine import Connection

from tf2price.contas import permissoes, senhas, tokens
from tf2price.contas import repositorio as repo
from tf2price.contas.modelo import Convite, Usuario

VALIDADE_CONVITE = timedelta(days=7)
VALIDADE_CONVITE_DE_PARTIDA = timedelta(hours=24)
VALIDADE_SESSAO = timedelta(days=30)
JANELA_DO_FREIO = timedelta(minutes=15)
FALHAS_ATE_BLOQUEIO = 5

# Espelha o String(60) de `usuario.nome` e `tentativa.nome` em `db.py`. O
# SQLite não impõe esse limite e deixa passar; o Postgres levanta erro, e sem
# esta conferência antes o visitante anônimo recebe um 500 em vez de um
# recado.
NOME_MAXIMO = 60

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
    if len(nome) > NOME_MAXIMO:
        raise NomeEmUso(f"esse nome é longo demais (máximo {NOME_MAXIMO} caracteres)")
    if repo.usuario_por_nome(conn, nome) is not None:
        raise NomeEmUso("esse nome já está em uso")

    # O hash da senha antes de consumir o convite: `gerar` recusa senha curta,
    # e uma recusa depois do consumo queimaria o link. A rota devolve a página
    # de erro, e a transação da requisição fecha com commit — ela não volta
    # atrás.
    senha_hash = senhas.gerar(senha)

    # Consumir antes de criar a conta, não depois. Ler o convite e só então
    # marcá-lo deixava duas requisições com o mesmo link passarem pela
    # leitura antes de qualquer marca — dois cliques, duas contas. Num painel
    # fechado o convite é a política de porta inteira.
    if not repo.consumir_convite(conn, convite.hash_do_token, usado_em=quando):
        raise ConviteInvalido("convite inválido")

    ident = repo.criar_usuario(
        conn,
        nome=nome,
        senha_hash=senha_hash,
        admin=convite.concede_admin,
        quando=quando,
    )
    repo.registrar_quem_usou(conn, convite.hash_do_token, usado_por=ident)
    return repo.usuario_por_id(conn, ident)


def redefinicao_autorizada(
    conn: Connection, convite: Convite, nome_super: str | None
) -> bool:
    """O link de redefinição ainda vale para aquele alvo?

    Revalida no uso, e não só na geração, quem pode resetar a senha de quem:
    o link vale enquanto quem o gerou ainda poderia gerá-lo. Uma regra só
    cobre o link gerado para um membro que depois virou admin (senão o admin
    comum guardaria o link e tomaria a conta de um admin), a corrida entre
    gerar e promover, e o link de quem depois foi rebaixado ou desativado.
    """
    if convite.alvo is None or convite.criado_por is None:
        return False
    criador = repo.usuario_por_id(conn, convite.criado_por)
    alvo = repo.usuario_por_id(conn, convite.alvo)
    if criador is None or alvo is None:
        return False
    return permissoes.pode_gerir(criador, alvo, nome_super)


def redefinir(
    conn: Connection,
    token: str,
    *,
    senha: str,
    quando: datetime,
    nome_super: str | None,
) -> Usuario:
    convite = _convite_utilizavel(conn, token, TIPO_REDEFINICAO, quando)
    # Antes do hash e do consumo, como toda recusa aqui: a transação da
    # requisição fecha com commit mesmo no caminho de erro, e recusar depois
    # de consumir queimaria o link.
    #
    # Entre esta conferência e `trocar_senha` há o hash Argon2 e o consumo:
    # uma promoção que feche nessa janela equivale a "resetou enquanto era
    # membro e depois foi promovida", que o desenho já aceita — não vale um
    # `trocar_senha` condicional.
    if not redefinicao_autorizada(conn, convite, nome_super):
        raise ConviteInvalido("convite inválido")

    # Mesma ordem de `aceitar_convite`, pela mesma razão: hash antes (pode
    # recusar), consumo antes da escrita (duas requisições, um link).
    senha_hash = senhas.gerar(senha)
    if not repo.consumir_convite(conn, convite.hash_do_token, usado_em=quando):
        raise ConviteInvalido("convite inválido")

    repo.trocar_senha(conn, convite.alvo, senha_hash)
    # Trocar a senha derruba o que já estava aberto: se a troca foi por
    # suspeita, deixar a sessão antiga viva anularia a troca.
    repo.apagar_sessoes_do_usuario(conn, convite.alvo)
    repo.registrar_quem_usou(conn, convite.hash_do_token, usado_por=convite.alvo)
    return repo.usuario_por_id(conn, convite.alvo)


def entrar(conn: Connection, *, nome: str, senha: str, quando: datetime) -> str:
    """Devolve o token de sessão em claro, que vai para o cookie."""
    nome = nome.strip()
    if len(nome) > NOME_MAXIMO:
        # Recusa antes de gravar qualquer tentativa: um nome deste tamanho
        # nunca bate com uma conta real (o schema não permite), então não
        # há freio a proteger, só um INSERT que o Postgres recusaria.
        raise CredenciaisInvalidas("nome ou senha incorretos")

    limite_do_freio = quando - JANELA_DO_FREIO
    # Fora da janela do freio a linha não significa mais nada; sem isto,
    # `tentativa` só encolhe quando alguém acerta a senha, e é o único jeito
    # de um anônimo escrever no banco sem limite.
    repo.limpar_tentativas_antigas(conn, limite_do_freio)
    if repo.contar_tentativas(conn, nome, limite_do_freio) >= FALHAS_ATE_BLOQUEIO:
        raise ContaBloqueada("tentativas demais; espere alguns minutos")

    usuario = repo.usuario_por_nome(conn, nome)
    if usuario is None:
        # Sem conta para conferir senha, este caminho voltaria em ~1ms contra
        # os ~50-100ms do Argon2 no caminho de senha errada — e o relógio
        # denunciaria quais nomes existem, desfazendo de propósito a mensagem
        # única abaixo.
        senhas.confere_em_falso(senha)
        repo.registrar_tentativa(conn, nome, quando)
        raise CredenciaisInvalidas("nome ou senha incorretos")
    if not senhas.confere(usuario.senha_hash, senha):
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


def entrar_direto(conn: Connection, usuario: Usuario, *, quando: datetime) -> str:
    """Abre sessão sem conferir senha, para quem acabou de provar quem é.

    Usado só após aceitar convite ou redefinir senha: exigir a senha recém
    digitada de novo seria atrito sem ganho de segurança.
    """
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
