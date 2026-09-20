from __future__ import annotations

import itertools
import json
from pathlib import Path

import httpx
import pytest

from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import Currencies
from tf2price.sources.steam import SearchPage, SearchResult, parse_search_page
from tf2price.spike import run
from tf2price.spike.run import MAX_SHALLOW_PAGES, _parse_args, _shallow_scan, main

RESULTADO = SearchResult(
    hash_name="Unusual Team Captain",
    lowest_price=Brl.from_float(100.0),
    sell_listings=5,
)

# _shallow_scan deduplica por hash_name, então as páginas de teste precisam
# de nomes distintos para exercitar a paginação — repetir o mesmo nome
# testaria a deduplicação, não o teto de segurança.
_SEQUENCIA = itertools.count()


def _resultado(nome: str) -> SearchResult:
    return SearchResult(hash_name=nome, lowest_price=Brl.from_float(100.0), sell_listings=5)


def _pagina_cheia(total_count: int, tamanho: int = 100) -> SearchPage:
    return SearchPage(
        total_count=total_count,
        results=[_resultado(f"Item {next(_SEQUENCIA)}") for _ in range(tamanho)],
    )


def _pagina_vazia() -> SearchPage:
    return SearchPage(total_count=0, results=[])


class _SteamFake:
    """Duck-type mínimo de SteamClient: só precisa de search_page."""

    def __init__(self, respostas) -> None:
        self._respostas = respostas
        self.chamadas = 0
        self.queries_recebidas: list[str | None] = []

    def search_page(self, start: int, count: int = 100, query: str | None = None) -> SearchPage:
        self.chamadas += 1
        self.queries_recebidas.append(query)
        return self._respostas(start)


def test_teto_de_seguranca_contem_api_degradada():
    """API degradada: total_count=0 mas results sempre não vazio.

    Sem um teto independente, o loop giraria para sempre. O teto de
    segurança precisa interromper exatamente em MAX_SHALLOW_PAGES chamadas.
    """
    steam = _SteamFake(lambda start: _pagina_cheia(total_count=0, tamanho=1))

    resultados, total = _shallow_scan(steam, max_pages=0)

    assert steam.chamadas == MAX_SHALLOW_PAGES
    assert len(resultados) == MAX_SHALLOW_PAGES
    assert total == 0


def test_passada_saudavel_para_no_total():
    """Com total_count real, a passada para assim que start >= total,
    bem antes do teto de segurança."""
    total_real = 350  # 4 páginas de 100, última parcial

    def responder(start: int) -> SearchPage:
        restante = max(total_real - start, 0)
        tamanho = min(100, restante)
        return SearchPage(
            total_count=total_real,
            results=[_resultado(f"Item {start + i}") for i in range(tamanho)],
        )

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == total_real
    assert total == total_real
    assert steam.chamadas == 4
    assert steam.chamadas < MAX_SHALLOW_PAGES


def test_pagina_vazia_interrompe_a_passada():
    """Uma página cheia seguida de uma vazia deve parar ali, mesmo sem
    total_count confiável."""
    paginas = [_pagina_cheia(total_count=0, tamanho=100), _pagina_vazia()]

    def responder(start: int) -> SearchPage:
        return paginas.pop(0)

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100
    assert steam.chamadas == 2


def test_pagina_que_falha_preserva_o_que_ja_foi_coletado():
    """Uma execução completa leva 15-30 min. Uma página que falha no meio
    não pode descartar as páginas anteriores: um catálogo parcial ainda
    gera relatório, uma exceção não gera nada."""
    paginas = [_pagina_cheia(total_count=1000, tamanho=100)]

    def responder(start: int) -> SearchPage:
        if paginas:
            return paginas.pop(0)
        raise RuntimeError("Steam não respondeu após backoff (último: status 500)")

    steam = _SteamFake(responder)
    resultados, total = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100
    assert total == 1000


def test_falha_de_rede_http_tambem_e_contida():
    paginas = [_pagina_cheia(total_count=1000, tamanho=100)]

    def responder(start: int) -> SearchPage:
        if paginas:
            return paginas.pop(0)
        raise httpx.ReadTimeout("tempo esgotado")

    steam = _SteamFake(responder)
    resultados, _ = _shallow_scan(steam, max_pages=0)

    assert len(resultados) == 100


def test_erro_de_programacao_continua_estourando():
    """Escopo estreito de propósito: AttributeError é bug, não falha de
    rede, e precisa aparecer em vez de virar 'passada parcial'."""

    def responder(start: int) -> SearchPage:
        raise AttributeError("bug de verdade")

    with pytest.raises(AttributeError):
        _shallow_scan(_SteamFake(responder), max_pages=0)


def test_paginas_sobrepostas_rendem_cada_nome_uma_vez():
    """Durante os ~11 min da passada o mercado se move e itens migram entre
    páginas. Duplicata infla as contagens que alimentam o veredito — na
    direção de 'vale construir'."""
    paginas = [
        SearchPage(
            total_count=4,
            results=[_resultado("A"), _resultado("B")],
        ),
        SearchPage(
            total_count=4,
            results=[_resultado("B"), _resultado("C")],
        ),
        SearchPage(total_count=4, results=[]),
    ]

    def responder(start: int) -> SearchPage:
        return paginas.pop(0)

    resultados, _ = _shallow_scan(_SteamFake(responder), max_pages=0)

    nomes = [r.hash_name for r in resultados]
    assert nomes == ["A", "B", "C"]


def test_shallow_scan_repassa_a_query_para_o_cliente():
    """O escopo da aplicação estreitou para Unusuals: _shallow_scan precisa
    repassar `query` para toda chamada de search_page, não só a primeira."""
    steam = _SteamFake(lambda start: _pagina_cheia(total_count=0, tamanho=1))

    _shallow_scan(steam, max_pages=3, query="Unusual")

    assert steam.chamadas == 3
    assert steam.queries_recebidas == ["Unusual"] * 3


def test_shallow_scan_sem_query_repassa_none():
    steam = _SteamFake(lambda start: _pagina_vazia())

    _shallow_scan(steam, max_pages=0)

    assert steam.queries_recebidas == [None]


# --- validação de argumentos ---------------------------------------------


def test_threshold_negativo_e_rejeitado():
    # (1 - threshold) > 1 SOBE o piso da poda em vez de baixá-lo e fabrica
    # classificações GARANTIDAS: falso positivo, o pior erro possível aqui.
    with pytest.raises(SystemExit):
        _parse_args(["--threshold", "-0.1"])


def test_threshold_maior_ou_igual_a_um_e_rejeitado():
    with pytest.raises(SystemExit):
        _parse_args(["--threshold", "1.0"])


@pytest.mark.parametrize(
    "argumento",
    [
        ["--deep-limit", "-1"],
        ["--max-pages", "-1"],
        ["--min-interval", "-1"],
    ],
)
def test_valores_negativos_sao_rejeitados(argumento):
    with pytest.raises(SystemExit):
        _parse_args(argumento)


def test_conjunto_valido_e_aceito():
    args = _parse_args(
        ["--threshold", "0.25", "--deep-limit", "5", "--max-pages", "2", "--min-interval", "0"]
    )

    assert args.threshold == 0.25
    assert args.deep_limit == 5
    assert args.max_pages == 2
    assert args.min_interval == 0.0


def test_padroes_seguem_inalterados():
    args = _parse_args([])

    assert args.threshold == 0.15
    assert args.deep_limit == 200
    assert args.max_pages == 0
    assert args.min_interval == 3.0
    assert args.out == "out"
    assert args.query == "Unusual"


def test_query_vazio_explicito_e_aceito():
    # Vazio é a forma documentada de varrer o mercado inteiro: não pode ser
    # rejeitado como se fosse um valor inválido.
    args = _parse_args(["--query", ""])

    assert args.query == ""


# --- main(): as duas proteções de uma execução de 15-30 min ---------------
#
# Nenhum teste daqui para baixo toca a rede: BackpackTfClient e SteamClient
# são substituídos por dublês, e o que sobra de real (PriceIndex,
# shallow_pass, o relatório) roda sobre as fixtures JSON do repositório.

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# Chave escolhida para que "Unusual Team Captain" (R$ 890,00 na fixture da
# busca) caia entre o piso e o teto da poda — CANDIDATE, e portanto alvo do
# fetch profundo. A R$ 30,00: piso = 9 * 0,85 * 30 = R$ 229,50; teto =
# 45 * 0,85 * 30 = R$ 1.147,50 (a faixa do Team Captain na fixture de preços
# vai de 9 a 45 chaves).
CHAVE_BRL = Brl.from_float(30.00)
CHAVE_MEDIANA_BRL = Brl.from_float(31.00)


def _fixture(nome: str) -> dict:
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


class _BptfFake:
    """Duck-type de BackpackTfClient: main() só chama estes dois métodos."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def currencies(self) -> Currencies:
        return Currencies.from_payload(_fixture("bptf_currencies.json"))

    def prices_payload(self) -> dict:
        return _fixture("bptf_prices.json")


def _pagina_da_fixture() -> SearchPage:
    payload = _fixture("steam_search_page.json")
    # O total_count da fixture é o mercado inteiro (21543). Aqui a busca
    # devolve tudo o que existe de uma vez; se o total anunciado ficasse
    # maior que o coletado, main() marcaria o catálogo como PARCIAL e o
    # banner de execução incompleta apareceria por um motivo que NÃO é o
    # testado — e o teste do caminho feliz passaria a ser uma mentira.
    payload["total_count"] = len(payload["results"])
    return parse_search_page(payload)


class _SteamMainFake:
    """Duck-type de SteamClient para main(): busca, preço da chave, listagens.

    `listagens` é chamada uma vez por candidata do fetch profundo; é o ponto
    onde os testes injetam a falha que o embrulho do estágio profundo tem
    que conter.
    """

    def __init__(self, listagens) -> None:
        self._listagens = listagens
        self.nomes_buscados: list[str] = []

    def key_price(self) -> Brl:
        return CHAVE_BRL

    def key_median_price(self) -> Brl:
        return CHAVE_MEDIANA_BRL

    def search_page(self, start: int, count: int = 100, query: str | None = None) -> SearchPage:
        if start:
            return SearchPage(total_count=0, results=[])
        return _pagina_da_fixture()

    def listings(self, hash_name: str, count: int = 100):
        self.nomes_buscados.append(hash_name)
        return self._listagens(hash_name)


def _preparar_main(monkeypatch, tmp_path, listagens) -> tuple[list[str], _SteamMainFake]:
    """Troca os colaboradores de main() por dublês e devolve o argv."""
    steam = _SteamMainFake(listagens)

    # main() chama load_dotenv(), que procura um .env subindo a partir de
    # run.py — ou seja, acharia um .env na raiz do repositório mesmo com o
    # cwd em outro lugar. Hoje não existe nenhum, mas o teste não pode
    # depender disso: anular a função deixa o ambiente do teste sendo o
    # único ambiente. (BPTF_API_KEY é fixada via monkeypatch.setenv abaixo;
    # load_dotenv não sobrescreve variáveis já definidas, então o setenv
    # sozinho já bastaria para a chave — a anulação cobre o resto.)
    monkeypatch.setattr(run, "load_dotenv", lambda *args, **kwargs: None)
    # Valor de fachada. O portão de main() só exige string não vazia, e a
    # chave nunca sai daqui: BackpackTfClient foi substituído.
    monkeypatch.setenv("BPTF_API_KEY", "chave-de-fachada")

    monkeypatch.setattr(run, "BackpackTfClient", _BptfFake)
    monkeypatch.setattr(run, "SteamClient", lambda limiter: steam)

    efeitos = tmp_path / "effects.json"
    efeitos.write_text(
        (FIXTURES / "effects_sample.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(run, "DEFAULT_EFFECTS_PATH", efeitos)

    return ["--out", str(tmp_path / "out")], steam


def _sem_listagens(hash_name: str) -> list:
    """Fetch profundo que completa sem devolver nada.

    Devolver listagens reais faria `resolve_deep` consultar o mapa de
    efeitos de PRODUÇÃO (tf2price/data/effects.json), que não existe neste
    repositório — a FileNotFoundError resultante cairia no embrulho e
    levantaria o banner, contaminando justamente o teste do caminho feliz.
    O que este dublê precisa provar é só que o estágio profundo terminou.
    """
    return []


# --- Fix 1: precondição do mapa de efeitos --------------------------------


def test_mapa_de_efeitos_ausente_aborta_antes_de_qualquer_rede(
    monkeypatch, tmp_path, capsys
):
    """O mapa de efeitos só seria lido no primeiro Unusual do fetch profundo,
    ~15 min depois do início, e FileNotFoundError NÃO é capturado pelo except
    estreito do laço: a execução morreria depois de gastar as requisições
    caras. A checagem tem que falhar já na largada — e dizer como consertar.
    """
    monkeypatch.setattr(run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("BPTF_API_KEY", "chave-de-fachada")
    ausente = tmp_path / "nao-existe" / "effects.json"
    monkeypatch.setattr(run, "DEFAULT_EFFECTS_PATH", ausente)

    codigo = main(["--out", str(tmp_path / "out")])

    assert codigo == 1
    erro = capsys.readouterr().err
    assert str(ausente) in erro
    # Sem o nome do script gerador a mensagem diagnostica sem resolver.
    assert "scripts/fetch_effects.py" in erro


# --- Fix 2: o relatório sobrevive a um fetch profundo que explode ---------


def test_fetch_profundo_que_explode_ainda_escreve_o_relatorio(monkeypatch, tmp_path):
    """A passada rasa custa ~11 min. Uma exceção inesperada no estágio
    profundo não pode descartá-la: o relatório e o CSV têm que chegar ao
    disco, marcados como incompletos, e main tem que devolver 1.

    ValueError de propósito: é Exception, mas não é RuntimeError nem
    httpx.HTTPError, então atravessa o except estreito de cada candidata e
    só é contida pelo embrulho externo — que é o que este teste exercita.
    É também uma falha plausível de verdade (parse de payload torto).
    """

    def explodir(hash_name: str):
        raise ValueError("converted_price não numérico no payload da Steam")

    argv, steam = _preparar_main(monkeypatch, tmp_path, explodir)

    codigo = main(argv)

    relatorio = tmp_path / "out" / "relatorio.md"
    csv = tmp_path / "out" / "oportunidades.csv"

    assert steam.nomes_buscados == ["Unusual Team Captain"]
    assert relatorio.exists()
    assert csv.exists()

    texto = relatorio.read_text(encoding="utf-8")
    assert "AVISO: EXECUÇÃO INCOMPLETA" in texto
    assert "ValueError" in texto
    assert codigo == 1


def test_fetch_profundo_sem_falha_nao_marca_o_relatorio(monkeypatch, tmp_path):
    """Par do teste acima: sem falha, nada de banner e código 0.

    Sem este par, o teste anterior passaria mesmo se o banner fosse emitido
    incondicionalmente — ou seja, não provaria nada sobre a proteção.
    """
    argv, steam = _preparar_main(monkeypatch, tmp_path, _sem_listagens)

    codigo = main(argv)

    relatorio = tmp_path / "out" / "relatorio.md"
    assert relatorio.exists()
    assert (tmp_path / "out" / "oportunidades.csv").exists()

    texto = relatorio.read_text(encoding="utf-8")
    assert "EXECUÇÃO INCOMPLETA" not in texto
    assert steam.nomes_buscados == ["Unusual Team Captain"]
    assert codigo == 0


# --- Fix 3: Ctrl-C também descarrega o relatório --------------------------


def test_ctrl_c_no_fetch_profundo_descarrega_o_relatorio(monkeypatch, tmp_path):
    """KeyboardInterrupt não herda de Exception: sem tratamento próprio, um
    Ctrl-C jogaria fora os ~11 min da passada rasa. Parar cedo e ficar com o
    resultado parcial é o comportamento normal de quem acompanha uma
    execução de meia hora — mas a interrupção não pode ser engolida, ou
    parar viraria 'sucesso'.
    """

    def interromper(hash_name: str):
        raise KeyboardInterrupt

    argv, _ = _preparar_main(monkeypatch, tmp_path, interromper)

    with pytest.raises(KeyboardInterrupt):
        main(argv)

    relatorio = tmp_path / "out" / "relatorio.md"
    assert relatorio.exists()
    assert (tmp_path / "out" / "oportunidades.csv").exists()

    texto = relatorio.read_text(encoding="utf-8")
    assert "AVISO: EXECUÇÃO INCOMPLETA" in texto
    assert "KeyboardInterrupt" in texto
