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
