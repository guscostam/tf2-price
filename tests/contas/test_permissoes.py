from __future__ import annotations

from tf2price import db
from tf2price.contas.modelo import Usuario
from tf2price.contas.permissoes import eh_superadmin, pode_gerir, pode_mudar_admin

SUPER = "gusco"


def _u(ident: int, nome: str, admin: bool = False, ativo: bool = True) -> Usuario:
    return Usuario(
        id=ident, nome=nome, senha_hash="hash", admin=admin, ativo=ativo,
        criado_em=db.agora(),
    )


DONO = _u(1, "gusco", admin=True)
COLEGA = _u(2, "colega", admin=True)
OUTRO_ADMIN = _u(3, "outro", admin=True)
AMIGA = _u(4, "amiga")


# --- eh_superadmin ---------------------------------------------------------


def test_superadmin_e_o_admin_ativo_com_o_nome_da_variavel():
    assert eh_superadmin(DONO, SUPER) is True


def test_sem_variavel_ninguem_e_superadmin():
    assert eh_superadmin(DONO, None) is False
    assert eh_superadmin(DONO, "") is False


def test_nome_de_outra_pessoa_nao_faz_superadmin():
    assert eh_superadmin(COLEGA, SUPER) is False


def test_membro_com_o_nome_da_variavel_nao_e_superadmin():
    """A variável pode nomear uma conta que ainda não existe; quem se
    cadastrar com esse nome por um convite de membro nasce membro."""
    assert eh_superadmin(_u(9, "gusco"), SUPER) is False


def test_admin_desativado_com_o_nome_da_variavel_nao_e_superadmin():
    assert eh_superadmin(_u(1, "gusco", admin=True, ativo=False), SUPER) is False


# --- pode_gerir (Reset password, Disable/Reactivate) -----------------------


def test_superadmin_gere_todo_mundo():
    for alvo in (AMIGA, COLEGA, DONO):
        assert pode_gerir(DONO, alvo, SUPER) is True


def test_admin_comum_gere_membros_e_a_si_mesmo():
    assert pode_gerir(COLEGA, AMIGA, SUPER) is True
    assert pode_gerir(COLEGA, COLEGA, SUPER) is True


def test_admin_comum_nao_gere_outro_admin_nem_o_superadmin():
    assert pode_gerir(COLEGA, OUTRO_ADMIN, SUPER) is False
    assert pode_gerir(COLEGA, DONO, SUPER) is False


def test_admin_comum_gere_membro_desativado():
    assert pode_gerir(COLEGA, _u(4, "amiga", ativo=False), SUPER) is True


def test_membro_nao_gere_ninguem():
    assert pode_gerir(AMIGA, AMIGA, SUPER) is False
    assert pode_gerir(AMIGA, _u(5, "outra"), SUPER) is False


def test_admin_desativado_nao_gere_ninguem():
    desativado = _u(2, "colega", admin=True, ativo=False)
    assert pode_gerir(desativado, AMIGA, SUPER) is False
    assert pode_gerir(desativado, desativado, SUPER) is False


def test_sem_variavel_o_dono_vira_admin_comum():
    """Falha fechada: ninguém fica exposto, só some o poder sobre admins."""
    assert pode_gerir(DONO, COLEGA, None) is False
    assert pode_gerir(DONO, AMIGA, None) is True


# --- pode_mudar_admin (Make admin / Remove admin) --------------------------


def test_superadmin_muda_o_papel_dos_outros():
    assert pode_mudar_admin(DONO, AMIGA, SUPER) is True
    assert pode_mudar_admin(DONO, COLEGA, SUPER) is True


def test_superadmin_nao_muda_o_proprio_papel():
    assert pode_mudar_admin(DONO, DONO, SUPER) is False


def test_admin_comum_nao_muda_papel_de_ninguem():
    for alvo in (AMIGA, OUTRO_ADMIN, DONO, COLEGA):
        assert pode_mudar_admin(COLEGA, alvo, SUPER) is False


def test_sem_variavel_ninguem_muda_papel():
    assert pode_mudar_admin(DONO, AMIGA, None) is False
