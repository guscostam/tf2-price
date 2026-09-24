from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

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

    def vendas(self, sku, effect_id, item_name):
        self.chamadas.append((sku, effect_id, item_name))
        resposta = next(self.respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if hasattr(resposta, "vendas") else SimpleNamespace(vendas=resposta, criado_em=T0)


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
    assert cliente.chamadas == [("Burning Flames Team Captain", 13, "Team Captain")]
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
    assert (registro.chaves, registro.metal, registro.metal_por_chave) == (
        Decimal("2"), Decimal("0"), Decimal("50"))


def test_refaz_selecao_quando_relacao_metal_chave_muda(engine):
    _listagem(engine, "1")
    ofertas = (Venda(Decimal("1"), Decimal("0")), Venda(Decimal("0"), Decimal("50")))
    cliente = Cliente([ofertas, ofertas])
    taxa = [Decimal("60")]
    coletor = VendasColetor(
        engine, cliente, key_in_refined=lambda: taxa[0], agora=lambda: T0,
        esperar=lambda _: False, monotonic=lambda: 0.0,
    )
    coletor.rodar_uma_passada(Parar())
    taxa[0] = Decimal("40")
    coletor.rodar_uma_passada(Parar())
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")]
    assert len(cliente.chamadas) == 2
    assert (registro.chaves, registro.metal, registro.metal_por_chave) == (
        Decimal("1"), Decimal("0"), Decimal("40"))
    assert registro.buscado_em == T0


def test_consulta_sku_do_efeito_em_vez_do_item_generico(engine):
    _listagem(engine, "1", efeito="Massed Flies")
    cliente = Cliente([()])
    _coletor(engine, cliente).rodar_uma_passada(Parar())
    assert cliente.chamadas == [("Massed Flies Team Captain", 12, "Team Captain")]


def test_nao_aplica_venda_unusual_comum_a_qualidade_dupla(engine):
    _listagem(engine, "1", nome="Strange Unusual Bonk Boy")
    _listagem(engine, "2", nome="Unusual Strange Bonk Boy")
    cliente = Cliente([])

    _coletor(engine, cliente).rodar_uma_passada(Parar())

    assert cliente.chamadas == []
    with engine.begin() as conn:
        assert vendas_repo.ler_todas(conn) == {}


def test_snapshot_repetido_preserva_created_at_original(engine):
    _listagem(engine, "1")
    criado_em = T0 - timedelta(hours=7)
    snapshot = SimpleNamespace(
        vendas=(Venda(Decimal("8"), Decimal("2")),), criado_em=criado_em,
    )
    cliente = Cliente([snapshot, snapshot])
    coletor = _coletor(engine, cliente)
    coletor.rodar_uma_passada(Parar())
    coletor.rodar_uma_passada(Parar())
    with engine.begin() as conn:
        registro = vendas_repo.ler_todas(conn)[("Unusual Team Captain", "Burning Flames")]
    assert len(cliente.chamadas) == 2
    assert registro.buscado_em == criado_em


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
        def vendas(self, sku, effect_id, item_name):
            observadas.append(emprestadas)
            return super().vendas(sku, effect_id, item_name)

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


def test_ciclo_sobrevive_falha_transitoria_do_banco(engine, monkeypatch):
    coletor = _coletor(engine, Cliente([]))
    tentativas = []
    esperas = []

    def passada(_):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise RuntimeError("falha temporaria do banco")

    monkeypatch.setattr(coletor, "rodar_uma_passada", passada)
    coletor._esperar = lambda segundos: esperas.append(segundos) or len(esperas) == 2

    coletor.ciclo(Parar(), periodo_s=1)

    assert len(tentativas) == 2
    assert esperas == [1, 1]
