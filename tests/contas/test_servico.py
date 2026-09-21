from __future__ import annotations

from datetime import timedelta

import pytest

from tf2price import db
from tf2price.contas import repositorio as repo
from tf2price.contas import servico, tokens
from tf2price.contas.senhas import SenhaCurta

AGORA = db.agora()
SENHA = "uma senha longa"


def _dono(conn) -> int:
    return repo.criar_usuario(
        conn, nome="dono", senha_hash="hash", admin=True, quando=AGORA
    )


# --- convite -------------------------------------------------------------


def test_convite_cria_conta_e_devolve_usuario(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.nome == "amiga"
    assert novo.admin is False
    assert novo.ativo is True


def test_o_token_em_claro_nao_fica_no_banco(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        assert repo.convite_por_hash(conn, token) is None


def test_convite_nao_serve_duas_vezes(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        servico.aceitar_convite(conn, token, nome="amiga", senha=SENHA, quando=AGORA)
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, token, nome="outra", senha=SENHA, quando=AGORA
            )


def test_dois_cliques_no_mesmo_link_criam_uma_conta_só(engine, monkeypatch):
    """A corrida de verdade, encenada.

    As rotas são `def` síncrono, então o uvicorn as roda num pool de threads:
    duas requisições com o mesmo link podem ambas ler o convite ainda não
    usado antes de qualquer uma marcar. Com o fixture de SQLite (uma conexão
    só, StaticPool) não dá para pôr duas threads de verdade nisso, então o
    segundo clique entra aqui como efeito colateral no meio da janela — entre
    a leitura do convite e o consumo, que é exatamente onde a outra thread
    cabia. O que se prova é que o consumo, e não a leitura, é quem decide.
    """
    original = repo.usuario_por_nome

    def também_o_outro_clique(conn, nome):
        # Este é o último ponto antes do consumo; a outra requisição chega
        # aqui e leva o convite.
        repo.consumir_convite(conn, alvo["hash"], usado_em=AGORA)
        monkeypatch.setattr(repo, "usuario_por_nome", original)
        return original(conn, nome)

    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        alvo = {"hash": repo.convite_por_hash(conn, tokens.hash_de(token)).hash_do_token}
        monkeypatch.setattr(repo, "usuario_por_nome", também_o_outro_clique)

        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, token, nome="amiga", senha=SENHA, quando=AGORA
            )
        # Só o "dono" do teste: o segundo clique não virou conta.
        assert [u.nome for u in repo.listar_usuarios(conn)] == ["dono"]


def test_senha_curta_nao_queima_o_convite(engine):
    """A recusa acontece antes do consumo, de propósito: a rota devolve a
    página de erro e a transação da requisição fecha com commit, então um
    convite consumido antes da recusa ficaria consumido para sempre."""
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        with pytest.raises(SenhaCurta):
            servico.aceitar_convite(
                conn, token, nome="amiga", senha="curta", quando=AGORA
            )
        # O link continua servindo para quem digitar uma senha de verdade.
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.nome == "amiga"


def test_nome_em_uso_nao_queima_o_convite(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        with pytest.raises(servico.NomeEmUso):
            servico.aceitar_convite(
                conn, token, nome="dono", senha=SENHA, quando=AGORA
            )
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.nome == "amiga"


def test_convite_expirado_e_recusado(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        depois = AGORA + servico.VALIDADE_CONVITE + timedelta(seconds=1)
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, token, nome="amiga", senha=SENHA, quando=depois
            )


def test_token_inventado_e_recusado(engine):
    with engine.begin() as conn:
        with pytest.raises(servico.ConviteInvalido):
            servico.aceitar_convite(
                conn, "token-que-nao-existe", nome="amiga", senha=SENHA, quando=AGORA
            )


def test_nome_ja_em_uso(engine):
    with engine.begin() as conn:
        dono = _dono(conn)
        token = servico.convidar(conn, criado_por=dono, quando=AGORA)
        with pytest.raises(servico.NomeEmUso):
            servico.aceitar_convite(
                conn, token, nome="dono", senha=SENHA, quando=AGORA
            )


def test_aceitar_convite_recusa_nome_maior_que_o_limite(engine):
    """Postgres tem `usuario.nome` como String(60); acima disso ele levanta."""
    nome_longo = "x" * (servico.NOME_MAXIMO + 1)
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        with pytest.raises(servico.NomeEmUso):
            servico.aceitar_convite(
                conn, token, nome=nome_longo, senha=SENHA, quando=AGORA
            )
        assert repo.usuario_por_nome(conn, nome_longo) is None


def test_convite_de_partida_so_existe_com_banco_vazio(engine):
    with engine.begin() as conn:
        token = servico.convite_de_partida(conn, AGORA)
        assert token is not None
        primeiro = servico.aceitar_convite(
            conn, token, nome="gusco", senha=SENHA, quando=AGORA
        )
        assert primeiro.admin is True
        assert servico.convite_de_partida(conn, AGORA) is None


def test_convite_comum_nunca_cria_administrador(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        novo = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
    assert novo.admin is False


# --- entrar e sessão -----------------------------------------------------


def _com_conta(conn, nome="amiga", criado_por=None) -> None:
    if criado_por is None:
        criado_por = _dono(conn)
    token = servico.convidar(conn, criado_por=criado_por, quando=AGORA)
    servico.aceitar_convite(conn, token, nome=nome, senha=SENHA, quando=AGORA)


def test_entrar_devolve_sessao_que_resolve_o_usuario(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        achado = servico.usuario_da_sessao(conn, sessao, AGORA)
    assert achado.nome == "amiga"


def test_senha_errada_nao_entra(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)


def test_nome_inexistente_da_o_mesmo_erro_da_senha_errada(engine):
    """Distinguir os dois conta a quem adivinha quais nomes existem."""
    with engine.begin() as conn:
        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome="ninguem", senha=SENHA, quando=AGORA)


def test_nome_maior_que_o_limite_e_recusado_sem_gravar_tentativa(engine):
    """Postgres tem `tentativa.nome` como String(60); sem a checagem, o
    INSERT da tentativa é quem levantaria, virando 500 anônimo."""
    nome_longo = "x" * (servico.NOME_MAXIMO + 1)
    with engine.begin() as conn:
        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome=nome_longo, senha=SENHA, quando=AGORA)
        assert repo.contar_tentativas(conn, nome_longo, AGORA - timedelta(days=1)) == 0


def test_sessao_expirada_nao_resolve(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        depois = AGORA + servico.VALIDADE_SESSAO + timedelta(seconds=1)
        assert servico.usuario_da_sessao(conn, sessao, depois) is None


def test_sair_invalida_a_sessao(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        servico.sair(conn, sessao)
        assert servico.usuario_da_sessao(conn, sessao, AGORA) is None


def test_usuario_desativado_perde_a_sessao_e_nao_entra(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        sessao = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        repo.definir_ativo(conn, repo.usuario_por_nome(conn, "amiga").id, False)
        assert servico.usuario_da_sessao(conn, sessao, AGORA) is None
        with pytest.raises(servico.ContaInativa):
            servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)


def test_sessao_inexistente_e_none(engine):
    with engine.begin() as conn:
        assert servico.usuario_da_sessao(conn, "nao-existe", AGORA) is None


# --- freio ---------------------------------------------------------------


def test_cinco_erros_bloqueiam_o_nome(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        # Agora nem a senha certa passa.
        with pytest.raises(servico.ContaBloqueada):
            servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)


def test_o_bloqueio_passa_depois_da_janela(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        depois = AGORA + servico.JANELA_DO_FREIO + timedelta(seconds=1)
        assert servico.entrar(conn, nome="amiga", senha=SENHA, quando=depois)


def test_entrar_apaga_tentativas_fora_da_janela(engine):
    """Tentativa contra nome inexistente nunca passa por `limpar_tentativas`
    (só quem acerta a senha passa por lá); sem esta limpeza a tabela só
    cresce."""
    with engine.begin() as conn:
        _com_conta(conn)
        antiga = AGORA - servico.JANELA_DO_FREIO - timedelta(minutes=1)
        recente = AGORA - timedelta(minutes=1)
        repo.registrar_tentativa(conn, "amiga", antiga)
        repo.registrar_tentativa(conn, "amiga", recente)

        with pytest.raises(servico.CredenciaisInvalidas):
            servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)

        desde_sempre = AGORA - timedelta(days=1)
        # A antiga sumiu; sobram a recente e a nova gravada por esta chamada.
        assert repo.contar_tentativas(conn, "amiga", desde_sempre) == 2


def test_acertar_a_senha_limpa_o_contador(engine):
    with engine.begin() as conn:
        _com_conta(conn)
        for _ in range(servico.FALHAS_ATE_BLOQUEIO - 1):
            with pytest.raises(servico.CredenciaisInvalidas):
                servico.entrar(conn, nome="amiga", senha="errada demais", quando=AGORA)
        servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)
        assert repo.contar_tentativas(conn, "amiga", AGORA - timedelta(minutes=15)) == 0


# --- redefinir -----------------------------------------------------------


def test_redefinir_troca_a_senha_e_derruba_as_sessoes(engine):
    with engine.begin() as conn:
        dono = _dono(conn)
        _com_conta(conn, nome="amiga", criado_por=dono)
        alvo = repo.usuario_por_nome(conn, "amiga").id
        antiga = servico.entrar(conn, nome="amiga", senha=SENHA, quando=AGORA)

        token = servico.convidar(
            conn, criado_por=dono, quando=AGORA, tipo="redefinicao", alvo=alvo
        )
        servico.redefinir(conn, token, senha="senha novinha", quando=AGORA)

        assert servico.usuario_da_sessao(conn, antiga, AGORA) is None
        assert servico.entrar(conn, nome="amiga", senha="senha novinha", quando=AGORA)


def test_entrar_direto_abre_sessao_sem_senha(engine):
    with engine.begin() as conn:
        token = servico.convidar(conn, criado_por=_dono(conn), quando=AGORA)
        usuario = servico.aceitar_convite(
            conn, token, nome="amiga", senha=SENHA, quando=AGORA
        )
        sessao = servico.entrar_direto(conn, usuario, quando=AGORA)
        assert servico.usuario_da_sessao(conn, sessao, AGORA).nome == "amiga"
