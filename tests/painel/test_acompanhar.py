from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tf2price import db
from tf2price.acompanhamento import repositorio as repo
from tf2price.contas import repositorio as contas
from tf2price.contas import servico
from tf2price.painel.app import criar_app
from tf2price.painel.consulta import chave_de_referencia, linhas_acompanhadas
from tf2price.preco import repositorio as preco_repo
from tf2price.preco import serial
from tf2price.preco.retrato import Retratos
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.bcb import Ptax
from tf2price.sources.steam_page import SteamLimitando
from .conftest import (
    NOME, USD_DO_TESTE, _contexto, _pagina, _PaginasFalsas, _PtaxFalsa, cliente_logado,
)

SENHA = "uma senha longa"


def _indice_com_preco(idade_dias: int) -> PriceIndex:
    """Índice onde Deep Dive (id 3229 no mapa real) tem preço com essa idade.

    Mesma fixture de `test_consulta.py`, reescrita aqui: os dois arquivos
    testam camadas diferentes (rota de detalhe vs. coluna de acompanhados) e
    não vale a pena acoplar um ao outro por causa de um índice falso.
    """
    agora = int(time.time())
    return PriceIndex.from_payload(
        {"response": {**USD_DO_TESTE, "items": {"Taunt: Chairholder": {"prices": {"5": {"Tradable": {
            "Craftable": {"3229": {
                "currency": "keys", "value": 20.0,
                "last_update": agora - idade_dias * 86400,
            }}
        }}}}}}},
        key_in_refined=64.11,
    )


def test_acompanhar_guarda_e_aparece_na_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code == 200
    assert "Deep Dive" in r.text
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_case_files_lists_saved_pair_with_real_age(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    seis_minutos_atras = db.agora() - timedelta(minutes=6)
    with engine.begin() as conn:
        preco_repo.guardar(
            conn,
            NOME,
            json.dumps(serial.para_dict(_pagina())),
            seis_minutos_atras,
        )

    texto = cliente.get("/cases").text

    assert NOME in texto and "Deep Dive" in texto
    assert "Steam snapshot · 6 min" in texto
    assert "Open case" in texto
    assert "Refresh evidence" in texto
    assert "Remove case" in texto


def test_case_file_and_actions_name_the_exact_item_effect_pair(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    texto = cliente.get("/cases").text

    identidade = f"{NOME} — Deep Dive"
    assert f'aria-label="Case file: {identidade}"' in texto
    assert f'aria-label="Open case: {identidade}"' in texto
    assert f'aria-label="Refresh evidence: {identidade}"' in texto
    assert f'aria-label="Remove case: {identidade}"' in texto


def test_selected_case_file_exposes_current_state_to_assistive_technology(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    texto = cliente.get(
        "/analise", params={"nome": NOME, "efeito": "Deep Dive"}
    ).text

    inicio = texto.index("case-file--selected")
    caso_selecionado = texto[inicio:inicio + 500]
    assert 'aria-current="true"' in caso_selecionado
    assert "Current case" in caso_selecionado


def test_open_case_keeps_item_and_effect_together(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    texto = cliente.get("/cases").text

    assert "/cases/new?nome=" in texto
    assert "efeito=Deep%20Dive" in texto or "efeito=Deep+Dive" in texto


def test_remove_case_requires_explicit_confirmation(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    texto = cliente.get("/cases").text

    assert 'hx-confirm="Remove this case file?"' in texto


def test_saving_a_case_does_not_load_the_price_index(engine):
    class IndexAlreadyUnknown:
        def em_memoria(self):
            return None

        def obter(self):
            raise AssertionError("saving a case must not load backpack.tf")

    contexto = _contexto()
    contexto.indice = IndexAlreadyUnknown()

    resposta = cliente_logado(engine, contexto).post(
        "/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"}
    )

    assert resposta.status_code == 200


def test_acompanhar_duas_vezes_nao_duplica(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        assert len(repo.listar(conn, eu.id)) == 1


def test_remover_tira_da_lista(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
    r = cliente.delete(f"/acompanhar/{ident}")
    assert r.status_code == 200
    with engine.begin() as conn:
        assert repo.listar(conn, eu.id) == []


def test_ninguem_remove_o_item_de_outra_pessoa_pela_rota(engine):
    """O isolamento tem de valer na rota, não só no repositório."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
        # uma segunda pessoa, com sessão própria
        token = servico.convidar(conn, criado_por=eu.id, quando=db.agora())
        servico.aceitar_convite(conn, token, nome="outra", senha=SENHA, quando=db.agora())

    outro = TestClient(criar_app(engine, _contexto()))
    outro.post("/entrar", data={"nome": "outra", "senha": SENHA})
    r = outro.delete(f"/acompanhar/{ident}")

    assert r.status_code in (404, 200)
    with engine.begin() as conn:
        assert len(repo.listar(conn, eu.id)) == 1


def test_acompanhar_exige_sessao(engine):
    cliente = TestClient(criar_app(engine, _contexto()), follow_redirects=False)
    r = cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    assert r.status_code in (303, 401)


def test_item_sem_retrato_diz_que_nao_ha_dado_ainda(engine):
    """Acompanhar um item nunca aberto não pode deixar a linha em branco."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": "Unusual Chapeu Nunca Aberto", "efeito": "Smoking"})
    assert "Awaiting evidence" in cliente.get("/cases").text


def test_abrir_acompanhado_com_efeito_a_venda_preenche_efeito_e_avaliacao(engine):
    """Reproduz o clique num acompanhado: os dois blocos têm que fechar juntos.

    Antes da correção o botão chamava `/analise` e pulava `/efeitos`; a
    avaliação vinha certa, mas o bloco EFEITO continuava dizendo "aguardando
    item" — a tela se contradizendo.
    """
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Deep Dive"})

    assert r.status_code == 200
    assert "Waiting for an item" not in r.text
    assert "Waiting for an effect" not in r.text
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text
    assert "180,44" in r.text  # listagem mais barata do efeito, de _analise.html
    assert 'id="analysis"' in r.text and 'hx-swap-oob="true"' in r.text
    # o efeito aberto fica marcado na lista, e só ele
    assert r.text.count('class="is-selected"') == 1


def test_abrir_acompanhado_com_efeito_sumido_mostra_lista_e_avisa_ausencia(engine):
    """O efeito acompanhado pode não estar mais à venda nesta página.

    A lista de efeitos tem que aparecer normal, e a avaliação tem que avisar
    a ausência — nunca mostrar o preço de outro efeito no lugar: o mesmo
    chapéu com outro efeito vale outra ordem de grandeza.
    """
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Burning Flames"})

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Burning Flames"})

    assert r.status_code == 200
    for efeito in ("Deep Dive", "Midnight Whirlwind", "Screaming Tiger", "Silver Cyclone"):
        assert efeito in r.text
    assert "No listings for this effect in the current snapshot." in r.text
    assert "180,44" not in r.text  # preço de Deep Dive não pode aparecer no lugar


# --- o efeito ausente também tem idade (achado N1) -------------------------


def test_efeito_ausente_mostra_a_idade_do_retrato(engine):
    """"sem listagem deste efeito agora" é uma afirmação sobre o PRESENTE,
    sentada em cima de um retrato que pode ter horas — o mesmo defeito já
    coberto no partial dos Case Files (achado I4), aqui no bloco da direita."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas)
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    velho = db.agora() - timedelta(minutes=6)
    with engine.begin() as conn:
        preco_repo.guardar(conn, NOME, json.dumps(serial.para_dict(_pagina())), velho)

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Burning Flames"})

    assert r.status_code == 200
    assert "No listings for this effect in the current snapshot." in r.text
    assert "6 min" in r.text


def test_efeito_ausente_com_steam_limitando_avisa_os_dois(engine):
    """No 429, o ramo de ausência tem de dizer a idade E que a Steam está
    limitando — a mesma regra do §12 que já vale para o ramo de sucesso."""
    velho = db.agora() - timedelta(hours=3)
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas)
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    with engine.begin() as conn:
        preco_repo.guardar(conn, NOME, json.dumps(serial.para_dict(_pagina())), velho)
    paginas._erro = SteamLimitando("status 429")

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Burning Flames"})

    assert r.status_code == 200
    assert "No listings for this effect in the current snapshot." in r.text
    assert "3 h" in r.text
    assert "Steam rate limited" in r.text


# --- a idade não pode sumir quando mais importa (achado I4) ---------------


def test_linha_sem_listagem_ainda_mostra_a_idade_do_retrato(engine):
    """"Sem listagem deste efeito agora" é uma afirmação sobre o PRESENTE —
    não pode aparecer sem dizer de que idade é o retrato por trás dela.

    Usa um `Retratos` de verdade: `_RetratosFalsos` (o padrão de `_contexto`)
    nunca grava no banco, então a linha ficaria em "sem dado ainda" e o
    teste não exercitaria o caminho que existe para provar.
    """
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas)
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Burning Flames"})
    cliente.get("/efeitos", params={"nome": NOME})  # popula o retrato guardado

    r = cliente.get("/cases/new")

    assert "No listings for this effect in the current snapshot" in r.text
    assert "Steam snapshot" in r.text


# --- retrato de versão antiga não pode soar como "sumiu do mercado" (N9) --


def test_retrato_de_versao_antiga_avisa_que_sera_regravado(engine):
    """Diferente de "sem listagem deste efeito agora": ali o problema é do
    mercado (o efeito não está à venda), aqui o problema é NOSSO (a forma
    do retrato mudou) — as duas mensagens nunca podem soar iguais."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        preco_repo.guardar(
            conn, NOME,
            json.dumps({
                "versao": 999, "hash_name": NOME,
                "listings": [], "orderbook": {}, "history": [],
            }),
            db.agora(),
        )

    r = cliente.get("/cases/new")

    assert "Stored snapshot uses an older format; refresh to replace it" in r.text
    assert "No listings for this effect in the current snapshot" not in r.text


# --- uma linha ruim não pode trancar ninguém para fora (achado N3) --------


def test_linha_com_erro_inesperado_nao_derruba_o_painel(engine, monkeypatch, capsys):
    """A separação dos `except` (ValueError vs. o resto) está certa e não é
    revertida aqui: um `KeyError`/`TypeError` de uma linha ruim, sem uma
    rede de segurança final, derrubaria `GET /` e `DELETE /acompanhar`
    inteiros — e a pessoa não teria como remover justo o item que quebra,
    trancada para fora.

    Mas a rede de segurança tem de logar: uma linha educada na tela e nada
    no log do Railway é como este bug ficaria invisível para sempre."""
    from tf2price.painel import consulta

    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas)
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.get("/efeitos", params={"nome": NOME})  # popula o retrato guardado

    def _quebra(*args, **kwargs):
        raise KeyError("campo inesperado")

    monkeypatch.setattr(consulta, "analyse", _quebra)

    r = cliente.get("/cases/new")
    assert r.status_code == 200
    assert "This case could not be evaluated" in r.text
    assert "KeyError" in capsys.readouterr().out

    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        ident = repo.listar(conn, eu.id)[0].id
    r = cliente.delete(f"/acompanhar/{ident}")
    assert r.status_code == 200
    with engine.begin() as conn:
        assert repo.listar(conn, eu.id) == []


# --- o × não pode carregar a idade errada (achado I5) ----------------------


def test_premio_desaparece_quando_a_referencia_da_bptf_esta_vencida(engine):
    """O × cruza a Steam (numerador) com a bp.tf (denominador). Com a
    referência vencida (> 365 dias, o mesmo limiar de `_analise.html`), a
    linha não pode somar uma idade fresca a uma velha sem dizer isso —
    melhor sumir o ×."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas, indice=_indice_com_preco(900))
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.get("/efeitos", params={"nome": NOME})

    r = cliente.get("/cases/new")

    assert "Steam snapshot" in r.text
    assert "backpack.tf reference" not in r.text


def test_premio_mostra_a_idade_da_bptf_junto_da_idade_do_retrato(engine):
    """Quando o × aparece, a linha mostra as DUAS idades — a do retrato da
    Steam e a da referência da bp.tf — porque pertencem a metades diferentes
    da conta."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas, indice=_indice_com_preco(12))
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.get("/efeitos", params={"nome": NOME})

    r = cliente.get("/cases/new")

    assert "Steam snapshot" in r.text
    assert "backpack.tf reference · 12 d" in r.text


# --- o × usa a chave de referência, não a da Steam (achado de review) -----
#
# `_case_files.html` nunca imprime o NÚMERO do prêmio como texto — só usa
# `l.premio` como booleano para decidir se mostra "backpack.tf reference ·
# {idade}" ao lado da idade do retrato da Steam (ver o template). Com a PTAX
# padrão dos fixtures (R$ 10,00) a referência e a chave da Steam dão o mesmo
# R$ 11,73, então nem o número nem a presença do texto provariam qual das
# duas alimenta a conta. Por isso: (1) uma PTAX diferente (R$ 5,00), que
# separa os dois valores, e (2) uma chamada direta a `linhas_acompanhadas` —
# a mesma função que a rota HTTP chama — para inspecionar `l.premio`, já que
# o HTML não expõe o número.


def test_o_premio_dos_case_files_usa_a_chave_de_referencia_nao_a_da_steam(engine):
    ctx = _contexto(indice=_indice_com_preco(5))
    ctx.ptax = _PtaxFalsa(Ptax(5.0, datetime(2026, 9, 21, 13, 6)))
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        preco_repo.guardar(conn, NOME, json.dumps(serial.para_dict(_pagina())), db.agora())

    with engine.begin() as conn:
        eu = contas.usuario_por_nome(conn, "gusco")
        indice = ctx.indice.em_memoria()
        referencia = chave_de_referencia(ctx, engine, indice)
        linhas = linhas_acompanhadas(
            conn, referencia.brl if referencia else None, indice, eu.id, db.agora(),
        )

    assert len(linhas) == 1
    # 180,44 é a listagem mais barata do efeito na fixture (mesma de
    # test_analise_mostra_preco_e_oferta). 117,40 = 20 chaves × R$ 5,87 (a
    # referência com esta PTAX: round(0,0183 × 64,11 × 100 × 5,0) = 587
    # centavos). 234,60 = 20 × R$ 11,73 seria a conta com a chave da Steam.
    premio_com_referencia = 18044 / 11740
    premio_com_a_chave_da_steam = 18044 / 23460
    assert linhas[0].premio == pytest.approx(premio_com_referencia, rel=1e-6)
    assert linhas[0].premio != pytest.approx(premio_com_a_chave_da_steam, rel=1e-2)


def test_case_files_sem_ptax_mostra_o_preco_e_esconde_o_premio(engine):
    ctx = _contexto(indice=_indice_com_preco(5))
    ctx.ptax = _PtaxFalsa(None)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    with engine.begin() as conn:
        preco_repo.guardar(conn, NOME, json.dumps(serial.para_dict(_pagina())), db.agora())

    texto = cliente.get("/cases").text

    assert "180,44" in texto
    assert "backpack.tf reference" not in texto


# --- esquerda e direita concordam, sem aninhar (achado I6) -----------------


def test_efeitos_marca_a_linha_aberta_na_coluna_esquerda(engine):
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Midnight Whirlwind"})

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Deep Dive"})

    assert r.status_code == 200
    assert r.text.count("case-file--selected") == 1
    trecho = r.text[r.text.index("case-file--selected"):][:500]
    assert "Deep Dive" in trecho
    assert "Midnight Whirlwind" not in trecho


def test_efeitos_sem_efeito_nao_marca_nenhuma_linha(engine):
    """Chamada pela busca de itens, sem `efeito`: nenhuma linha é "a aberta"."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    r = cliente.get("/efeitos", params={"nome": NOME})

    assert r.status_code == 200
    assert "case-file--selected" not in r.text


def test_efeitos_atualiza_case_files_sem_aninhar_o_involucro(engine):
    """O id="case-files" mora no invólucro de `new_case.html`; o fragmento
    `_case_files.html` não o declara. Se o fora-de-banda não carregasse o
    id (substituindo o invólucro inteiro), cada resposta aninharia um
    `#case-files` dentro do outro.

    Estendido (achado N8) para cobrir também `/analise`: é a rota que os
    botões de efeito chamam (`_efeitos.html`), e ela também manda a coluna
    fora de banda agora."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})

    for rota in ("/efeitos", "/analise"):
        for _ in range(2):
            r = cliente.get(rota, params={"nome": NOME, "efeito": "Deep Dive"})
            assert r.status_code == 200
            assert r.text.count('id="case-files"') == 1


def test_analise_marca_a_linha_aberta_na_coluna_esquerda(engine):
    """Reproduz a sequência real: abrir o acompanhado A e clicar noutro
    efeito na lista — que só chama `/analise` (`_efeitos.html` manda o botão
    de efeito para `#analise`, não para `#efeitos`). Sem `/analise` mandar a
    coluna fora de banda, A seguia marcado enquanto a direita já mostrava
    outro efeito."""
    cliente = cliente_logado(engine, _contexto())
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Midnight Whirlwind"})

    r = cliente.get("/analise", params={"nome": NOME, "efeito": "Midnight Whirlwind"})

    assert r.status_code == 200
    assert r.text.count("case-file--selected") == 1
    trecho = r.text[r.text.index("case-file--selected"):][:500]
    assert "Midnight Whirlwind" in trecho
    assert "Deep Dive" not in trecho


def test_efeitos_atualiza_o_preco_na_esquerda_quando_o_retrato_estava_vencido(engine):
    """Antes da correção, `/efeitos` não devolvia os Case Files: se o
    retrato estava vencido e a busca trouxe um novo, a esquerda ficava com o
    preço velho ao lado do novo que a direita acabou de mostrar."""
    paginas = _PaginasFalsas(_pagina())
    ctx = _contexto(paginas=paginas)
    ctx.retratos = Retratos(paginas)
    cliente = cliente_logado(engine, ctx)
    cliente.post("/acompanhar", data={"nome": NOME, "efeito": "Deep Dive"})
    # Um retrato vencido (> 15 min) força a busca de um novo dentro de /efeitos.
    velho = db.agora() - timedelta(minutes=20)
    with engine.begin() as conn:
        preco_repo.guardar(conn, NOME, json.dumps(serial.para_dict(_pagina())), velho)

    r = cliente.get("/efeitos", params={"nome": NOME, "efeito": "Deep Dive"})

    assert r.status_code == 200
    assert paginas.chamadas == 1  # buscou de novo por estar vencido
    # O preço mais barato do efeito aparece na linha do acompanhado
    # (esquerda), concordando com a avaliação (direita, que já é coberta
    # por `test_efeitos_marca_a_linha_aberta_na_coluna_esquerda` e pelos
    # testes de `test_acompanhar.py` que checam "180,44" em `_analise.html`).
    inicio = r.text.index('id="case-files"')
    trecho_esquerda = r.text[inicio:]
    assert "180,44" in trecho_esquerda
