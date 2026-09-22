"""Quem pode mexer em quem na lista de pessoas do admin.

Funções puras: sem conexão, sem I/O. São a fonte única da regra — a rota
decide por elas, o template mostra os botões por elas e `servico.redefinir`
revalida por elas o link de redefinição no momento do uso.

O superadmin é a conta nomeada pela variável de ambiente `SUPERADMIN`. A
proteção dos admins não depende dela: admin comum não age sobre admin
nenhum, superadmin ou não. O que a variável dá é só o poder de gerir
admins; ausente ou errada, esse poder some, e não passa para mais ninguém.
"""

from __future__ import annotations

from tf2price.contas.modelo import Usuario


def eh_superadmin(usuario: Usuario, nome_super: str | None) -> bool:
    # Admin e ativo no banco, não só o nome: se a variável nomear uma conta
    # que ainda não existe, quem receber um convite de membro pode se
    # cadastrar com esse nome — e nasce membro, não superadmin.
    return (
        bool(nome_super)
        and usuario.nome == nome_super
        and usuario.admin
        and usuario.ativo
    )


def pode_gerir(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool:
    """Reset password e Disable/Reactivate.

    A própria conta entra como gerível; quem recusa desativar a si mesmo é a
    rota de ativo, com mensagem própria. Admin comum age só sobre membros:
    gerar o link de reset de outro admin seria tomar a conta dele, já que
    quem gera o link pode usá-lo.
    """
    if not (ator.admin and ator.ativo):
        return False
    if ator.id == alvo.id:
        return True
    if eh_superadmin(ator, nome_super):
        return True
    return not alvo.admin


def pode_mudar_admin(ator: Usuario, alvo: Usuario, nome_super: str | None) -> bool:
    """Make admin / Remove admin: só o superadmin, e nunca sobre si mesmo."""
    return eh_superadmin(ator, nome_super) and ator.id != alvo.id
