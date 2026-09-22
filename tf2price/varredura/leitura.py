"""A página da varredura: cada listagem cruzada com a backpack.tf, na hora.

O resultado nunca é gravado. Ele sai da mesma `patient_exit` da tela de
consulta, contra o índice e a cotação que estão na memória agora. Quando a
bp.tf atualiza um preço, a página reflete sem nenhuma requisição à Steam.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH
from tf2price.domain.money import Brl
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.lookup.analysis import patient_exit
from tf2price.sources.backpacktf import PriceIndex
from tf2price.varredura.repositorio import ListagemVarrida

IDADE_MAX_BPTF_PADRAO = 90
POR_PAGINA = 50
ABAS = ("todas", "lucro")
ORDENS = ("resultado", "percentual", "preco", "idade_bptf")
SEM_COTACAO = "the key exchange rate has not loaded yet"
EFEITO_DESCONHECIDO = "Steam did not report the effect of this listing"


@dataclass(frozen=True)
class Filtros:
    aba: str = "todas"
    texto: str = ""
    efeito: str = ""
    preco_min: Brl | None = None
    preco_max: Brl | None = None
    idade_max_bptf_dias: int | None = IDADE_MAX_BPTF_PADRAO
    so_com_preco: bool = False
    ordem: str = "resultado"
    pagina: int = 1

    def query(self, **mudancas) -> str:
        """Query string destes filtros, com `mudancas` aplicadas: é o que as
        abas e a paginação usam para não perder o resto do filtro."""
        f = replace(self, **mudancas)
        pares = {
            "aba": f.aba,
            "q": f.texto,
            "efeito": f.efeito,
            "preco_min": _reais(f.preco_min),
            "preco_max": _reais(f.preco_max),
            "idade_max": "" if f.idade_max_bptf_dias is None else str(f.idade_max_bptf_dias),
            "ordem": f.ordem,
            "pagina": str(f.pagina),
        }
        if f.so_com_preco:
            pares["so_com_preco"] = "1"
        return urlencode(pares)


def _reais(valor: Brl | None) -> str:
    return "" if valor is None else f"{valor.cents // 100}.{valor.cents % 100:02d}"


def _brl(texto: str) -> Brl | None:
    """Texto de formulário em reais para `Brl`, sem passar por float."""
    texto = texto.strip().replace(",", ".")
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    if not valor.is_finite() or valor < 0:
        return None
    return Brl(int((valor * 100).to_integral_value()))


def _positivo(texto: str) -> int | None:
    try:
        valor = int(texto.strip())
    except ValueError:
        return None
    return valor if valor > 0 else None


def filtros_da_query(
    *, aba: str = "todas", q: str = "", efeito: str = "", preco_min: str = "",
    preco_max: str = "", idade_max: str = str(IDADE_MAX_BPTF_PADRAO),
    so_com_preco: str = "", ordem: str = "resultado", pagina: str = "1",
) -> Filtros:
    """Tudo aqui é texto de fora: valor inválido vira o padrão, nunca erro."""
    return Filtros(
        aba=aba if aba in ABAS else "todas",
        texto=q.strip()[:100],
        efeito=efeito.strip()[:120],
        preco_min=_brl(preco_min),
        preco_max=_brl(preco_max),
        idade_max_bptf_dias=_positivo(idade_max),
        so_com_preco=so_com_preco == "1",
        ordem=ordem if ordem in ORDENS else "resultado",
        pagina=_positivo(pagina) or 1,
    )


@dataclass(frozen=True)
class LinhaVarrida:
    listagem: ListagemVarrida
    preco_em_chaves: float | None
    chaves_bptf: float | None
    valor_bptf: Brl | None
    resultado: Brl | None
    percentual: float | None
    idade_bptf_dias: int | None
    motivo: str | None
    arte: str | None


@dataclass(frozen=True)
class Pagina:
    linhas: list[LinhaVarrida]
    total: int
    pagina: int
    paginas: int


def avaliar(
    listagem: ListagemVarrida,
    indice: PriceIndex | None,
    key_brl: Brl | None,
    agora_unix: int,
    idade_max_bptf_dias: int | None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> LinhaVarrida:
    arte = (
        arte_dos_efeitos.url_do_efeito(listagem.efeito, effects_path=effects_path)
        if listagem.efeito else None
    )

    def linha(**campos) -> LinhaVarrida:
        base = dict(
            listagem=listagem, preco_em_chaves=None, chaves_bptf=None, valor_bptf=None,
            resultado=None, percentual=None, idade_bptf_dias=None, motivo=None, arte=arte,
        )
        base.update(campos)
        return LinhaVarrida(**base)

    if key_brl is None or key_brl.cents <= 0:
        return linha(motivo=SEM_COTACAO)
    em_chaves = listagem.preco.cents / key_brl.cents
    if listagem.efeito is None:
        return linha(preco_em_chaves=em_chaves, motivo=EFEITO_DESCONHECIDO)

    saida = patient_exit(
        listagem.preco, listagem.hash_name, listagem.efeito, indice, key_brl,
        now=agora_unix, effects_path=effects_path,
    )
    if not saida.available:
        return linha(preco_em_chaves=em_chaves, motivo=saida.reason)
    if (
        idade_max_bptf_dias is not None
        and saida.age_days is not None
        and saida.age_days > idade_max_bptf_dias
    ):
        # O valor e a idade continuam à mostra; o resultado não. Um lucro
        # medido contra um preço de anos atrás é o falso positivo que
        # derrubou o spike de 2026-09-19.
        return linha(
            preco_em_chaves=em_chaves, chaves_bptf=saida.keys, valor_bptf=saida.fair_value,
            idade_bptf_dias=saida.age_days,
            motivo=f"backpack.tf price is older than {idade_max_bptf_dias} days",
        )
    percentual = (
        saida.result.cents / listagem.preco.cents if listagem.preco.cents > 0 else None
    )
    return linha(
        preco_em_chaves=em_chaves, chaves_bptf=saida.keys, valor_bptf=saida.fair_value,
        resultado=saida.result, percentual=percentual, idade_bptf_dias=saida.age_days,
    )


def _chave_de_ordem(ordem: str):
    # Sem resultado vai sempre para o fim; o id desempata para a ordem ser
    # estável entre uma página e a seguinte.
    if ordem == "preco":
        return lambda l: (l.listagem.preco.cents, l.listagem.listing_id)
    if ordem == "idade_bptf":
        return lambda l: (l.idade_bptf_dias is None, l.idade_bptf_dias or 0, l.listagem.listing_id)
    if ordem == "percentual":
        return lambda l: (l.percentual is None, -(l.percentual or 0.0), l.listagem.listing_id)
    return lambda l: (
        l.resultado is None, -(l.resultado.cents if l.resultado else 0), l.listagem.listing_id
    )


def montar(
    listagens: list[ListagemVarrida],
    indice: PriceIndex | None,
    key_brl: Brl | None,
    filtros: Filtros,
    agora_unix: int,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
) -> Pagina:
    linhas = [
        avaliar(l, indice, key_brl, agora_unix, filtros.idade_max_bptf_dias, effects_path)
        for l in listagens
    ]
    if filtros.so_com_preco:
        linhas = [l for l in linhas if l.resultado is not None]
    if filtros.aba == "lucro":
        linhas = [l for l in linhas if l.resultado is not None and l.resultado.cents > 0]
    linhas.sort(key=_chave_de_ordem(filtros.ordem))

    total = len(linhas)
    paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina = min(max(1, filtros.pagina), paginas)
    inicio = (pagina - 1) * POR_PAGINA
    return Pagina(linhas[inicio:inicio + POR_PAGINA], total, pagina, paginas)
