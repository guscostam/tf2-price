from __future__ import annotations

import itertools
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


_SEQUENCIA = itertools.count()


def _oportunidade(
    desconto_reais: float,
    fair_reais: float = 200.0,
    guard: Guard = Guard.OK,
    hash_name: str | None = None,
) -> Opportunity:
    """Uma oportunidade; sem `hash_name`, de um item distinto a cada chamada.

    O veredito conta nomes distintos, não linhas. Um teste que pede N
    oportunidades está descrevendo N itens do mercado — se o padrão fosse
    um nome fixo, ele estaria descrevendo N listagens do mesmo chapéu, que
    é justamente o que não deve contar. Passar `hash_name` força o mesmo
    item para os testes que querem esse caso.
    """
    nome = hash_name if hash_name is not None else f"Unusual Hat #{next(_SEQUENCIA)}"
    fair_keys = fair_reais / 22.0
    pago = Brl.from_float(fair_reais - desconto_reais)
    return Opportunity(
        hash_name=nome,
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


def test_vinte_listagens_do_mesmo_item_nao_dao_verde():
    """Um item subprecificado não é um mercado.

    Um fetch profundo devolve até 100 listagens do mesmo hash_name. Contando
    linhas, um único chapéu barato com 20 listagens dispararia "construa a
    aplicação" sozinho — o falso positivo que o spec manda evitar.
    """
    todas = [_oportunidade(60.0, hash_name="Unusual Team Captain") for _ in range(20)]
    assert len(net_opportunities(todas)) == 20
    assert decide(todas) is Verdict.RED


def test_dez_nomes_distintos_dao_verde():
    todas = [_oportunidade(60.0, hash_name=f"Chapeu {i}") for i in range(10)]
    assert decide(todas) is Verdict.GREEN


def test_desconto_medio_e_calculado_sobre_os_nomes_colapsados():
    """A média sai de uma linha por nome, não de todas as linhas.

    Vinte listagens de um mesmo item com R$ 100 de desconto puxariam a
    média das linhas para R$ 81,70 e dariam VERDE. Colapsado, o mercado é
    um item de R$ 100 e nove de R$ 41: média de R$ 46,90, abaixo do corte.
    """
    repetido = [_oportunidade(100.0, hash_name="Unusual Team Captain") for _ in range(20)]
    outros = [_oportunidade(41.0, hash_name=f"Chapeu {i}") for i in range(9)]
    todas = repetido + outros

    assert len(net_opportunities(todas)) == 29
    assert decide(todas) is Verdict.YELLOW


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


def test_markdown_mostra_linhas_e_nomes_distintos():
    """Quem lê o relatório precisa ver a largura do sinal, não só o volume."""
    todas = [_oportunidade(60.0, hash_name="Unusual Team Captain") for _ in range(12)]
    todas += [_oportunidade(60.0, hash_name="Unusual Killer's Kabuto")]

    texto = render_markdown(
        opportunities=todas,
        key_brl=CHAVE,
        key_median_brl=CHAVE,
        total_names=100,
        unmatched=[],
        guaranteed_count=0,
        candidate_count=2,
        deep_fetched_count=2,
        requests_made=5,
        first_429_after=None,
        market_derived=None,
    )

    assert "13 oportunidades líquidas em 2 nomes distintos" in texto
    assert "| Faixa de desconto | Líquidas | Nomes distintos |" in texto
    assert "| >= 25% | 13 | 2 |" in texto


def test_markdown_declara_o_que_foi_excluido_antes_das_guardas():
    """A tabela de guardas sozinha mente por omissão.

    Itens em USD e candidatas sem fetch profundo são barrados a montante e
    nunca chegam a `check_guards`. Sem dizer isso, a tabela parece afirmar
    que essas duas guardas não pegaram nada.
    """
    from tf2price.spike.report import MarketDerivedAnalysis

    texto = render_markdown(
        opportunities=[_oportunidade(60.0)],
        key_brl=CHAVE,
        key_median_brl=CHAVE,
        total_names=100,
        unmatched=[],
        guaranteed_count=0,
        candidate_count=120,
        deep_fetched_count=20,
        requests_made=5,
        first_429_after=None,
        market_derived=MarketDerivedAnalysis(
            sample_size=317,
            median_discount=0.42,
            fraction_near_15pct=0.1,
            hypothesis_supported=False,
        ),
    )

    assert "Itens precificados em USD: 317" in texto
    assert "Candidatas sem fetch profundo: 100" in texto


def test_tabela_de_reprovacao_exclui_aprovadas():
    """A tabela de motivos de reprovação não deve listar oportunidades que passaram."""
    todas = [
        _oportunidade(60.0, guard=Guard.OK),
        _oportunidade(60.0, guard=Guard.STALE_PRICE),
        _oportunidade(60.0, guard=Guard.OK),
    ]
    texto = render_markdown(
        opportunities=todas,
        key_brl=CHAVE,
        key_median_brl=CHAVE,
        total_names=3,
        unmatched=[],
        guaranteed_count=0,
        candidate_count=3,
        deep_fetched_count=0,
        requests_made=1,
        first_429_after=None,
        market_derived=None,
    )
    assert "| preco_desatualizado |" in texto
    assert "| ok |" not in texto
