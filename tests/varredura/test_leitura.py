from __future__ import annotations

from pathlib import Path

import pytest

from tf2price import db
from tf2price.domain.money import Brl
from tf2price.lookup.analysis import RAZAO_SEM_INDICE, RAZAO_SEM_PRECO, RAZAO_SEM_REFERENCIA
from tf2price.sources.backpacktf import PriceIndex
from tf2price.varredura import leitura
from tf2price.varredura.repositorio import ListagemVarrida

EFEITOS = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"
AGORA = 1_790_000_000
CHAVE = Brl.from_cents(1000)  # R$ 10,00 a chave: conta de cabeça


def _indice(dias=10, chaves=100.0, efeito_id="13"):
    return PriceIndex.from_payload({"response": {"items": {
        "Team Captain": {"prices": {"5": {"Tradable": {"Craftable": {
            efeito_id: {"currency": "keys", "value": chaves, "last_update": AGORA - dias * 86400},
        }}}}},
    }}}, key_in_refined=64.11)


def _l(ident, centavos, efeito="Burning Flames", nome="Unusual Team Captain", mais=0):
    return ListagemVarrida(ident, nome, efeito, Brl(centavos), None, db.agora(), mais)


def _avaliar(listagem, indice=None, chave=CHAVE, idade_max=90):
    return leitura.avaliar(listagem, indice if indice is not None else _indice(), chave,
                           AGORA, idade_max, effects_path=EFEITOS)


def test_resultado_e_o_da_saida_paciente():
    # 100 chaves x R$ 10 = R$ 1.000; paga R$ 800 -> +R$ 200 (25%).
    linha = _avaliar(_l("1", 80000))
    assert linha.valor_bptf == Brl(100000)
    assert linha.chaves_bptf == 100.0
    assert linha.resultado == Brl(20000)
    assert linha.percentual == pytest.approx(0.25)
    assert linha.idade_bptf_dias == 10
    assert linha.preco_em_chaves == pytest.approx(80.0)
    assert linha.motivo is None


def test_efeito_sem_preco_nunca_herda_o_de_outro_efeito():
    # O índice só precifica Burning Flames (13); Sunbeams (17) fica sem.
    linha = _avaliar(_l("1", 80000, efeito="Sunbeams"))
    assert (linha.resultado, linha.valor_bptf) == (None, None)
    assert linha.motivo == RAZAO_SEM_PRECO


def test_efeito_desconhecido_nao_tem_resultado():
    linha = _avaliar(_l("1", 80000, efeito=None))
    assert linha.resultado is None
    assert linha.motivo == leitura.EFEITO_DESCONHECIDO


def test_sem_referencia_nao_tem_resultado():
    linha = _avaliar(_l("1", 80000), chave=None)
    assert (linha.resultado, linha.preco_em_chaves) == (None, None)
    assert linha.motivo == RAZAO_SEM_REFERENCIA


def test_sem_indice_diz_que_o_indice_nao_carregou():
    linha = leitura.avaliar(_l("1", 80000), None, CHAVE, AGORA, 90, effects_path=EFEITOS)
    assert linha.motivo == RAZAO_SEM_INDICE


def test_preco_velho_mostra_valor_e_idade_mas_nao_resultado():
    linha = _avaliar(_l("1", 80000), indice=_indice(dias=200), idade_max=90)
    assert linha.valor_bptf == Brl(100000)
    assert linha.idade_bptf_dias == 200
    assert linha.resultado is None
    assert linha.motivo == "backpack.tf price is older than 90 days"


def test_sem_limite_de_idade_o_preco_velho_conta():
    linha = _avaliar(_l("1", 80000), indice=_indice(dias=200), idade_max=None)
    assert linha.resultado == Brl(20000)


def _montar(listagens, **filtros):
    return leitura.montar(listagens, _indice(), CHAVE, leitura.Filtros(**filtros),
                          AGORA, effects_path=EFEITOS)


def test_aba_lucro_so_tem_resultado_positivo():
    listagens = [_l("ganha", 80000), _l("perde", 150000), _l("sem", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens, aba="lucro").linhas] == ["ganha"]
    assert _montar(listagens).total == 3


def test_so_com_preco_tira_as_linhas_sem_resultado():
    listagens = [_l("ganha", 80000), _l("sem", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens, so_com_preco=True).linhas] == ["ganha"]


def test_ordenacoes():
    listagens = [_l("a", 90000), _l("b", 50000), _l("c", 1, efeito="Sunbeams")]
    assert [l.listagem.listing_id for l in _montar(listagens).linhas] == ["b", "a", "c"]
    assert [l.listagem.listing_id for l in _montar(listagens, ordem="preco").linhas] == ["c", "b", "a"]
    assert [l.listagem.listing_id for l in _montar(listagens, ordem="percentual").linhas] == ["b", "a", "c"]


def test_paginacao_limita_e_corrige_pagina_fora_do_intervalo():
    listagens = [_l(f"{i:03}", 80000 + i) for i in range(leitura.POR_PAGINA + 5)]
    segunda = _montar(listagens, pagina=2)
    assert (segunda.total, segunda.pagina, segunda.paginas, len(segunda.linhas)) == (55, 2, 2, 5)
    assert _montar(listagens, pagina=99).pagina == 2


def test_arte_so_e_calculada_para_as_linhas_da_pagina(monkeypatch):
    # A arte olha o disco (`is_file`) por listagem: com milhares de linhas,
    # só a página devolvida precisa dela.
    pedidos = []

    def url_do_efeito(efeito, effects_path=None):
        pedidos.append(efeito)
        return f"/arte/{efeito}"

    monkeypatch.setattr(leitura.arte_dos_efeitos, "url_do_efeito", url_do_efeito)
    listagens = [_l(f"{i:03}", 80000 + i) for i in range(leitura.POR_PAGINA + 5)]

    segunda = _montar(listagens, pagina=2)

    assert len(pedidos) == 5
    assert [l.arte for l in segunda.linhas] == ["/arte/Burning Flames"] * 5


def test_filtros_da_query_valida_tudo():
    f = leitura.filtros_da_query(aba="lucro", q="  team ", efeito="Sunbeams",
                                 preco_min="10.50", preco_max="abc", idade_max="",
                                 so_com_preco="1", ordem="preco", pagina="-3")
    assert f == leitura.Filtros(aba="lucro", texto="team", efeito="Sunbeams",
                                preco_min=Brl(1050), preco_max=None,
                                idade_max_bptf_dias=None, so_com_preco=True,
                                ordem="preco", pagina=1)


def test_filtros_da_query_recusa_valores_desconhecidos():
    f = leitura.filtros_da_query(aba="x", ordem="y", idade_max="0", preco_min="-5")
    assert (f.aba, f.ordem, f.idade_max_bptf_dias, f.preco_min) == ("todas", "resultado", None, None)


def test_filtros_padrao():
    assert leitura.filtros_da_query() == leitura.Filtros()
    assert leitura.Filtros().idade_max_bptf_dias == 90


def test_query_preserva_filtros_e_troca_so_o_pedido():
    f = leitura.Filtros(texto="team", preco_min=Brl(1050), so_com_preco=True)
    q = f.query(pagina=3)
    assert "q=team" in q and "preco_min=10.50" in q and "so_com_preco=1" in q
    assert "pagina=3" in q


@pytest.mark.parametrize("texto", ["9" * 5000, "1e5000", "10000000.01"])
def test_preco_absurdo_vira_padrao_e_a_query_nao_quebra(texto):
    f = leitura.filtros_da_query(preco_min=texto, preco_max=texto)
    assert (f.preco_min, f.preco_max) == (None, None)
    assert "preco_min=&" in f.query()


def test_preco_no_teto_e_aceito():
    assert leitura.filtros_da_query(preco_min="10000000").preco_min == Brl(1_000_000_000)
