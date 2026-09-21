from __future__ import annotations

from tf2price.sources.ratelimit import RateLimiter, backoff_delays


def test_contador_de_requisicoes():
    limiter = RateLimiter(min_interval_s=0.0)
    for _ in range(3):
        limiter.wait()
    assert limiter.requests == 3


def test_primeiro_429_registra_em_que_requisicao_aconteceu():
    limiter = RateLimiter(min_interval_s=0.0)
    limiter.wait()
    limiter.wait()
    limiter.record_throttle()
    limiter.wait()
    limiter.record_throttle()

    assert limiter.first_429_after == 2
    assert limiter.throttled == 2


def test_sem_429_o_marcador_fica_nulo():
    limiter = RateLimiter(min_interval_s=0.0)
    limiter.wait()
    assert limiter.first_429_after is None


def test_espacamento_respeita_o_intervalo_minimo():
    import time

    limiter = RateLimiter(min_interval_s=0.05)
    inicio = time.monotonic()
    limiter.wait()
    limiter.wait()
    assert time.monotonic() - inicio >= 0.05


def test_backoff_cresce_e_respeita_o_teto():
    delays = backoff_delays(attempts=8, base=2.0, cap=30.0)
    assert len(delays) == 8
    assert all(d > 0 for d in delays)
    assert max(delays) <= 30.0


def test_backoff_tem_jitter_mas_fica_na_metade_de_cima():
    # jitter entre 50% e 100% do valor bruto: nunca colapsa para quase zero
    delays = backoff_delays(attempts=1, base=2.0, cap=100.0)
    assert 1.0 <= delays[0] <= 2.0


def test_threads_em_paralelo_nao_furam_o_intervalo():
    """O caso real: as rotas da consulta são `def` síncrono, então o uvicorn
    as roda num pool de threads e o mesmo limitador atende várias ao mesmo
    tempo.

    Sem trava, as três últimas threads leem o mesmo `_last_call`, dormem o
    mesmo intervalo simultaneamente e saem juntas — o total mede um intervalo
    só, e a Steam vê uma rajada. Com trava elas se enfileiram, e o total mede
    três.
    """
    import threading
    import time

    intervalo = 0.05
    limiter = RateLimiter(min_interval_s=intervalo)
    partida = threading.Barrier(4)

    def chamar() -> None:
        partida.wait()
        limiter.wait()

    threads = [threading.Thread(target=chamar) for _ in range(4)]
    inicio = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    decorrido = time.monotonic() - inicio

    assert limiter.requests == 4
    # 3 intervalos com folga para o escalonador; sem a trava fica em ~1.
    assert decorrido >= intervalo * 2.5


def test_contagem_de_429_nao_se_perde_entre_threads():
    import threading

    limiter = RateLimiter(min_interval_s=0.0)
    limiter.wait()
    partida = threading.Barrier(20)

    def marcar() -> None:
        partida.wait()
        limiter.record_throttle()

    threads = [threading.Thread(target=marcar) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert limiter.throttled == 20
