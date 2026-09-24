from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import event, insert

from tf2price import db
from tf2price.sources.classificados import ClassificadosLimitando, Venda
from tf2price.varredura import vendas_repo
from tf2price.varredura.vendas_coletor import VendasColetor

T0 = datetime(2026, 9, 24, 12)


class Parar:
    def __init__(self):
        self.ativo = False

    def is_set(self):
        return self.ativo


class Cliente:
    def __init__(self, respostas):
        self.respostas = iter(respostas)
        self.chamadas = []

    def vendas(self, sku, effect_id):
        self.chamadas.append((sku, effect_id))
        resposta = next(self.respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def _listagem(engine, ident, nome="Unusual Team Captain", efeito="Burning Flames", instante=T0):
    with engine.begin() as conn:
        conn.execute(insert(db.listagem_varrida).values(
            listing_id=ident, hash_name=nome, efeito=efeito,
            preco_cents=100, icone=None, lido_em=instante,
        ))


def _coletor(engine, cliente, *, instante=T0, espera=None, taxa=Decimal("50"), monotonic=None):
    return VendasColetor(
        engine, cliente, key_in_refined=lambda: taxa, agora=lambda: instante,
        esperar=espera or (lambda _: False), monotonic=monotonic or (lambda: 0.0),
        backoff=lambda _: 40.0,
    )


def test_seleciona_apenas_steam_recente_deduplica_e_nao_rele_ate_vencer(engine):
    _listagem(engine, "1")
    _listagem(engine, "2")
    _listagem(engine, "3", nome="Unusual Old Hat", instante=T0 - timedelta(hours=7))
    cliente = Cliente([(Venda(Decimal("10"), Decimal("0")),)])
    coletor = _coletor(engine, cliente)
    coletor.rodar_uma_passada(Parar())
    coletor.rodar_uma_passada(Parar())
    assert cliente.chamadas == [("Burning Flames Team Captain", 13)]
    with engine.begin() as conn:
        assert vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")].chaves == Decimal("10")


def test_escolhe_minimo_convertendo_metal_por_chave(engine):
    _listagem(engine, "1")
    cliente = Cliente([(
        Venda(Decimal("2"), Decimal("0")),
        Venda(Decimal("1"), Decimal("60")),
    )])
    _coletor(engine, cliente, taxa=Decimal("50")).rodar_uma_passada(Parar())
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")]
    assert (registro.chaves, registro.metal) == (Decimal("2"), Decimal("0"))


def test_consulta_sku_do_efeito_em_vez_do_item_generico(engine):
    _listagem(engine, "1", efeito="Massed Flies")
    cliente = Cliente([()])
    _coletor(engine, cliente).rodar_uma_passada(Parar())
    assert cliente.chamadas == [("Massed Flies Team Captain", 12)]


def test_sem_cotacao_metal_nao_grava_ausencia(engine):
    _listagem(engine, "1")
    cliente = Cliente([(Venda(Decimal("1"), Decimal("5")),)])
    _coletor(engine, cliente, taxa=None).rodar_uma_passada(Parar())
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")]
    assert (registro.estado, registro.buscado_em, registro.falhou_em) == ("indisponivel", None, T0)


def test_cotacao_float_de_razao_e_convertida_sem_float_monetario(engine):
    _listagem(engine, "1")
    cliente = Cliente([(
        Venda(Decimal("2"), Decimal("0")),
        Venda(Decimal("1"), Decimal("60")),
    )])
    _coletor(engine, cliente, taxa=50.0).rodar_uma_passada(Parar())
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")]
    assert (registro.chaves, registro.metal) == (Decimal("2"), Decimal("0"))


def test_nao_segura_conexao_durante_http_ou_espera(engine):
    _listagem(engine, "1")
    _listagem(engine, "2", nome="Unusual Brigade Helm")
    emprestadas = 0
    observadas = []

    def checkout(*_):
        nonlocal emprestadas
        emprestadas += 1

    def checkin(*_):
        nonlocal emprestadas
        emprestadas -= 1

    event.listen(engine.pool, "checkout", checkout)
    event.listen(engine.pool, "checkin", checkin)

    class Observador(Cliente):
        def vendas(self, sku, effect_id):
            observadas.append(emprestadas)
            return super().vendas(sku, effect_id)

    cliente = Observador([(), ()])
    tempos = iter([0.0, 0.0, 0.0, 20.0, 20.0])
    esperas = []

    def esperar(segundos):
        observadas.append(emprestadas)
        esperas.append(segundos)
        return False

    try:
        _coletor(engine, cliente, espera=esperar, monotonic=lambda: next(tempos)).rodar_uma_passada(Parar())
    finally:
        event.remove(engine.pool, "checkout", checkout)
        event.remove(engine.pool, "checkin", checkin)
    assert observadas == [0, 0, 0]
    assert esperas == [20.0]


def test_429_respeita_retry_after_e_interrompe_passada(engine):
    _listagem(engine, "1")
    _listagem(engine, "2", nome="Unusual Brigade Helm")
    cliente = Cliente([ClassificadosLimitando(90), ()])
    esperas = []
    coletor = _coletor(engine, cliente, espera=lambda s: esperas.append(s) or False)
    coletor.rodar_uma_passada(Parar())
    assert len(cliente.chamadas) == 1
    assert esperas == [90]
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Brigade Helm", "Burning Flames")]
    assert (registro.estado, registro.falhou_em) == ("indisponivel", T0)
