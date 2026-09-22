from __future__ import annotations

import threading

from tf2price.painel.limite import LimitePorChave


class _Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


def test_permite_ate_o_maximo_e_recusa_o_seguinte():
    limite = LimitePorChave(maximo=3, janela_s=3600, relogio=_Relogio())
    assert [limite.permitir("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_chaves_sao_independentes():
    limite = LimitePorChave(maximo=1, janela_s=3600, relogio=_Relogio())
    assert limite.permitir("a")
    assert limite.permitir("b")
    assert not limite.permitir("a")


def test_janela_deslizante_libera_quando_o_mais_antigo_vence():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=2, janela_s=3600, relogio=relogio)
    assert limite.permitir("a")
    relogio.agora += 1800
    assert limite.permitir("a")
    assert not limite.permitir("a")
    relogio.agora += 1800  # o primeiro completou uma hora
    assert limite.permitir("a")
    assert not limite.permitir("a")


def test_recusa_nao_consome_cota():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=1, janela_s=60, relogio=relogio)
    assert limite.permitir("a")
    for _ in range(10):
        assert not limite.permitir("a")
    relogio.agora += 60
    assert limite.permitir("a")


def test_chaves_vencidas_saem_da_memoria():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=3, janela_s=60, relogio=relogio)
    for n in range(50):
        limite.permitir(f"ip-{n}")
    relogio.agora += 60
    limite.permitir("outro")
    # Sem limpeza, cada IP que passou uma vez ficaria para sempre na memória.
    assert limite.chaves_ativas() == 1


def test_teto_de_chaves_recusa_chave_nova_mas_aceita_existente():
    relogio = _Relogio()
    limite = LimitePorChave(maximo=5, janela_s=3600, maximo_de_chaves=2, relogio=relogio)
    assert limite.permitir("a")
    assert limite.permitir("b")
    # teto cheio: chave nova é recusada e não passa a existir
    assert not limite.permitir("c")
    assert limite.chaves_ativas() == 2
    # chave já presente segue a regra normal mesmo com o teto cheio
    assert limite.permitir("a")
    # depois que a janela vence, chave nova volta a entrar
    relogio.agora += 3600
    assert limite.permitir("c")


def test_concorrencia_nao_deixa_passar_alem_do_maximo():
    limite = LimitePorChave(maximo=5, janela_s=3600, relogio=_Relogio())
    barreira = threading.Barrier(20)
    resultados = []

    def tenta():
        barreira.wait()
        resultados.append(limite.permitir("a"))

    fios = [threading.Thread(target=tenta) for _ in range(20)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert resultados.count(True) == 5
