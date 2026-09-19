from __future__ import annotations

from dataclasses import replace

import pytest

from tf2price.domain.money import Brl
from tf2price.domain.prefilter import Classification
from tf2price.domain.valuation import Guard, evaluate
from tf2price.spike.pipeline import Opportunity
from tf2price.spike.report import (
    Verdict,
    decide,
    net_opportunities,
    render_csv,
    render_markdown,
)

CHAVE = Brl.from_float(22.00)


def _oportunidade(
    desconto_reais: float, fair_reais: float = 200.0, guard: Guard = Guard.OK
) -> Opportunity:
    fair_keys = fair_reais / 22.0
    pago = Brl.from_float(fair_reais - desconto_reais)
    return Opportunity(
        hash_name="Unusual Team Captain",
        listing_id="L1",
        effect="Burning Flames",
        craftable=True,
        steam_total=pago,
        valuation=evaluate(pago, fair_keys, CHAVE),
        classification=Classification.CANDIDATE,
        guard=guard,
        deep_fetched=True,
    )


def test_liquidas_excluem_reprovadas_pela_guarda():
    todas = [_oportunidade(60.0), _oportunidade(60.0, guard=Guard.STALE_PRICE)]
    assert len(net_opportunities(todas)) == 1


def test_liquidas_excluem_desconto_negativo():
    assert net_opportunities([_oportunidade(-10.0)]) == []


def test_veredito_verde():
    # 10 oportunidades com 30% de desconto e R$ 60 de valor absoluto
    todas = [_oportunidade(60.0) for _ in range(10)]
    assert decide(todas) is Verdict.GREEN


def test_veredito_amarelo_por_quantidade():
    todas = [_oportunidade(60.0) for _ in range(5)]
    assert decide(todas) is Verdict.YELLOW


def test_veredito_amarelo_por_valor_baixo():
    # quantidade suficiente, mas desconto médio de R$ 45 fica abaixo do corte
    todas = [_oportunidade(45.0) for _ in range(12)]
    assert decide(todas) is Verdict.YELLOW


def test_veredito_vermelho():
    assert decide([_oportunidade(60.0) for _ in range(2)]) is Verdict.RED


def test_veredito_vermelho_com_lista_vazia():
    assert decide([]) is Verdict.RED


def test_desconto_fraco_nao_conta_para_o_veredito():
    # 15% de desconto está abaixo do corte de 20%
    fracas = [_oportunidade(30.0) for _ in range(20)]
    assert decide(fracas) is Verdict.RED


def test_csv_tem_cabecalho_e_uma_linha_por_oportunidade():
    linhas = render_csv([_oportunidade(60.0), _oportunidade(70.0)]).strip().splitlines()
    assert linhas[0].startswith("hash_name,")
    assert len(linhas) == 3


def test_csv_escapa_virgula_no_nome():
    oportunidade = replace(_oportunidade(60.0), hash_name='Item, com vírgula')
    assert '"Item, com vírgula"' in render_csv([oportunidade])


def test_markdown_traz_o_veredito_e_as_contagens():
    texto = render_markdown(
        opportunities=[_oportunidade(60.0) for _ in range(10)],
        key_brl=CHAVE,
        key_median_brl=Brl.from_float(22.49),
        total_names=21543,
        unmatched=["Item Estranho"],
        guaranteed_count=8,
        candidate_count=120,
        deep_fetched_count=20,
        requests_made=231,
        first_429_after=None,
        market_derived=None,
    )
    assert "VERDE" in texto
    assert "21543" in texto
    assert "Item Estranho" in texto


def test_markdown_lista_nomes_nao_casados_por_frequencia():
    texto = render_markdown(
        opportunities=[],
        key_brl=CHAVE,
        key_median_brl=CHAVE,
        total_names=3,
        unmatched=["A", "B", "A", "A", "B"],
        guaranteed_count=0,
        candidate_count=0,
        deep_fetched_count=0,
        requests_made=1,
        first_429_after=None,
        market_derived=None,
    )
    posicao_a = texto.index("| A |")
    posicao_b = texto.index("| B |")
    assert posicao_a < posicao_b


def test_analise_da_guarda_4_confirma_agrupamento_em_15pct():
    from tf2price.spike.report import analyse_market_derived

    # câmbio implícito: usd_por_chave = 0.0363 * 69.44 = 2.5207
    #                   brl_por_usd  = 22.00 / 2.5207 = 8.7277
    # item de US$ 10 -> R$ 87,28. Listado a 85% disso -> R$ 74,19
    usd_items = [(10.0, Brl.from_float(74.19)) for _ in range(40)]

    analise = analyse_market_derived(
        usd_items=usd_items,
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )

    assert analise.sample_size == 40
    assert analise.median_discount == pytest.approx(0.15, abs=0.01)
    assert analise.fraction_near_15pct == pytest.approx(1.0)
    assert analise.hypothesis_supported is True


def test_analise_da_guarda_4_refuta_quando_espalhado():
    from tf2price.spike.report import analyse_market_derived

    usd_items = [(10.0, Brl.from_float(20.0 + i * 3)) for i in range(40)]
    analise = analyse_market_derived(
        usd_items=usd_items,
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )
    assert analise.hypothesis_supported is False


def test_analise_da_guarda_4_com_amostra_pequena_nao_conclui():
    from tf2price.spike.report import analyse_market_derived

    analise = analyse_market_derived(
        usd_items=[(10.0, Brl.from_float(74.19))],
        raw_usd_per_refined=0.0363,
        key_in_refined=69.44,
        key_brl=CHAVE,
    )
    assert analise.hypothesis_supported is False
