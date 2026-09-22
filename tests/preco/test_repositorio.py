from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import event, insert
from sqlalchemy.sql.dml import Update

from tf2price import db
from tf2price.preco import repositorio as repo

AGORA = db.agora()


def test_guardar_e_ler(engine):
    with engine.begin() as conn:
        repo.guardar(conn, "Unusual Team Captain", '{"a": 1}', AGORA)
        lido = repo.ler(conn, "Unusual Team Captain")
    assert lido is not None
    dados, quando = lido
    assert dados == '{"a": 1}'
    assert quando == AGORA


def test_ler_item_nunca_visto_e_none(engine):
    with engine.begin() as conn:
        assert repo.ler(conn, "Item Que Ninguem Abriu") is None


def test_guardar_de_novo_substitui_e_atualiza_a_hora(engine):
    """O retrato é um só por item: o segundo sobrescreve, não duplica."""
    depois = AGORA + timedelta(minutes=20)
    with engine.begin() as conn:
        repo.guardar(conn, "X", '{"v": 1}', AGORA)
        repo.guardar(conn, "X", '{"v": 2}', depois)
        dados, quando = repo.ler(conn, "X")
    assert dados == '{"v": 2}'
    assert quando == depois


def test_nomes_com_apostrofo_e_acento(engine):
    """`Strange Unusual Villain's Veil` existe e já mordeu este projeto."""
    nome = "Strange Unusual Villain's Veil"
    with engine.begin() as conn:
        repo.guardar(conn, nome, "{}", AGORA)
        assert repo.ler(conn, nome) is not None


def test_guardar_sob_insert_concorrente_nao_quebra(engine):
    """Duas pessoas pedindo o MESMO chapéu nunca visto ao mesmo tempo: as
    rotas são síncronas e o uvicorn as roda em threads de verdade, então as
    duas buscam a Steam em paralelo e as duas veem zero linhas no `update`
    antes de qualquer uma commitar o `insert`.

    Sem threads reais para não depender de timing, um ouvinte do próprio
    SQLAlchemy grava a linha "da outra transação" no instante exato entre o
    `update` de `guardar` (que viu zero linhas) e o `insert` dela — o mesmo
    ponto em que a segunda requisição de verdade chegaria. Sem o savepoint em
    volta do insert, a `IntegrityError` da chave duplicada sobe inteira até
    aqui e este teste falha; com ele, `guardar` percebe a colisão e refaz o
    update em cima do que a "outra" gravou.
    """
    nome = "Unusual Corrida"
    disparado = {"sim": False}

    def _grava_a_outra_transacao(conn, clauseelement, *args, **kwargs):
        if disparado["sim"] or not isinstance(clauseelement, Update):
            return
        if clauseelement.table is not db.retrato:
            return
        disparado["sim"] = True
        conn.execute(
            insert(db.retrato).values(
                hash_name=nome, json='{"de": "outra-thread"}', buscado_em=AGORA
            )
        )

    event.listen(engine, "after_execute", _grava_a_outra_transacao)
    try:
        with engine.begin() as conn:
            repo.guardar(conn, nome, '{"de": "esta-thread"}', AGORA)
    finally:
        event.remove(engine, "after_execute", _grava_a_outra_transacao)

    assert disparado["sim"], "a corrida não chegou a ser simulada"
    with engine.begin() as conn:
        dados, quando = repo.ler(conn, nome)
    # O que importa aqui não é quem venceu a corrida — é que nenhuma
    # IntegrityError escapou de `guardar` e o retrato ficou gravado.
    assert dados == '{"de": "esta-thread"}'


# --- PTAX ------------------------------------------------------------------


def test_ptax_guardada_e_lida(engine):
    data = datetime(2026, 9, 21, 13, 6, 51)
    quando = datetime(2026, 9, 22, 10, 0)
    with engine.begin() as conn:
        repo.guardar_ptax(conn, 5.1117, data, quando)
    with engine.begin() as conn:
        assert repo.ler_ptax(conn) == (5.1117, data, quando)


def test_ptax_nova_substitui_a_velha(engine):
    with engine.begin() as conn:
        repo.guardar_ptax(conn, 5.0, datetime(2026, 9, 18), datetime(2026, 9, 19))
        repo.guardar_ptax(conn, 5.1, datetime(2026, 9, 21), datetime(2026, 9, 22))
    with engine.begin() as conn:
        assert repo.ler_ptax(conn)[0] == 5.1


def test_sem_ptax_guardada_le_none(engine):
    with engine.begin() as conn:
        assert repo.ler_ptax(conn) is None
