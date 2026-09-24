"""Cruza listagens Steam, preço sugerido e vendas cacheadas por item e efeito.

Os resultados são calculados na leitura, sem consulta remota nesta camada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for
from tf2price.domain.identity import parse_market_hash_name
from tf2price.domain.money import Brl
from tf2price.efeitos import arte as arte_dos_efeitos
from tf2price.lookup.analysis import RAZAO_SEM_REFERENCIA, patient_exit
from tf2price.sources.backpacktf import PriceIndex
from tf2price.varredura.repositorio import ListagemVarrida

IDADE_MAX_BPTF_PADRAO = 90
POR_PAGINA = 50
ABAS = ("todas", "lucro", "revenda")
ORDENS = ("resultado", "percentual", "preco", "idade_bptf", "guia")
IDADE_MAX_VENDA = timedelta(hours=6)
EFEITO_DESCONHECIDO = "Steam did not report the effect of this listing"
PRECO_MAXIMO = Decimal("10000000")  # Limita preco da query para sempre poder formatar de volta


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


def url_vendas(
    hash_name: str, efeito: str | None, effects_path: Path = DEFAULT_EFFECTS_PATH
) -> str | None:
    if not efeito:
        return None
    item = parse_market_hash_name(hash_name)
    particle = effect_id_for(efeito, effects_path)
    if item.quality_id != 5 or particle is None:
        return None
    return "https://backpack.tf/classifieds?" + urlencode({
        "item": item.base_name,
        "quality": 5,
        "tradable": 1,
        "craftable": 1,
        "particle": particle,
    })


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
    if valor > PRECO_MAXIMO:
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
    vendas_url: str | None
    valor_venda: Brl | None
    chaves_venda: Decimal | None
    potencial: Brl | None
    percentual_venda: float | None
    estado_venda: str
    venda_buscada_em: datetime | None
    venda_falhou_em: datetime | None


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
    agora_unix: int | float,
    idade_max_bptf_dias: int | None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
    com_arte: bool = True,
    venda: Any | None = None,
) -> LinhaVarrida:
    arte = _arte(listagem, effects_path) if com_arte else None
    agora = datetime.fromtimestamp(agora_unix, timezone.utc).replace(tzinfo=None)
    estado_venda = "indisponivel" if venda is None else venda.estado
    venda_buscada_em = None if venda is None else venda.buscado_em
    venda_falhou_em = None if venda is None else venda.falhou_em
    relacao_atual = Decimal(str(indice.key_in_refined)) if indice is not None else None
    relacao_selecao = None if venda is None else getattr(venda, "metal_por_chave", None)
    taxa_compativel = relacao_atual is not None and relacao_selecao == relacao_atual
    if venda is not None and venda.estado == "encontrado" and not taxa_compativel:
        estado_venda = "stale"
    valor_venda: Brl | None = None
    chaves_venda: Decimal | None = None
    potencial: Brl | None = None
    percentual_venda: float | None = None
    if (venda is not None and venda.estado == "encontrado" and taxa_compativel
            and key_brl is not None and key_brl.cents > 0):
        chaves = venda.chaves
        metal = venda.metal
        relacao = relacao_atual
        if (
            isinstance(chaves, Decimal) and isinstance(metal, Decimal)
            and chaves >= 0 and metal >= 0
            and (metal == 0 or (relacao is not None and relacao > 0))
        ):
            chaves_venda = chaves + (metal / relacao if metal else Decimal(0))
            if chaves_venda > 0:
                centavos = int((chaves_venda * key_brl.cents).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                valor_venda = Brl(centavos)
                idade_venda = agora - venda.buscado_em if venda.buscado_em else None
                idade_steam = agora - listagem.lido_em
                if (
                    idade_venda is not None and timedelta(0) <= idade_venda <= IDADE_MAX_VENDA
                    and timedelta(0) <= idade_steam <= IDADE_MAX_VENDA
                ):
                    potencial = valor_venda - listagem.preco
                    percentual_venda = (
                        potencial.cents / listagem.preco.cents if listagem.preco.cents > 0 else None
                    )
                else:
                    estado_venda = "stale"
        if valor_venda is None:
            estado_venda = "indisponivel"
    elif venda is not None and venda.estado == "sem_vendas_confirmado" and venda.buscado_em is not None:
        idade_venda = agora - venda.buscado_em
        if not timedelta(0) <= idade_venda <= IDADE_MAX_VENDA:
            estado_venda = "stale"

    def linha(**campos) -> LinhaVarrida:
        base = dict(
            listagem=listagem, preco_em_chaves=None, chaves_bptf=None, valor_bptf=None,
            resultado=None, percentual=None, idade_bptf_dias=None, motivo=None, arte=arte,
            vendas_url=None,
            valor_venda=valor_venda, chaves_venda=chaves_venda,
            potencial=potencial, percentual_venda=percentual_venda,
            estado_venda=estado_venda, venda_buscada_em=venda_buscada_em,
            venda_falhou_em=venda_falhou_em,
        )
        base.update(campos)
        return LinhaVarrida(**base)

    if key_brl is None or key_brl.cents <= 0:
        return linha(motivo=RAZAO_SEM_REFERENCIA)
    em_chaves = listagem.preco.cents / key_brl.cents
    if listagem.efeito is None:
        return linha(preco_em_chaves=em_chaves, motivo=EFEITO_DESCONHECIDO)

    saida = patient_exit(
        listagem.preco, listagem.hash_name, listagem.efeito, indice, key_brl,
        now=int(agora_unix), effects_path=effects_path,
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


def _arte(listagem: ListagemVarrida, effects_path: Path) -> str | None:
    # Olha o disco (`is_file`): cara demais para milhares de linhas.
    if not listagem.efeito:
        return None
    return arte_dos_efeitos.url_do_efeito(listagem.efeito, effects_path=effects_path)


def _chave_de_ordem(ordem: str):
    # Sem resultado vai sempre para o fim; o id desempata para a ordem ser
    # estável entre uma página e a seguinte.
    if ordem == "preco":
        return lambda l: (l.listagem.preco.cents, l.listagem.listing_id)
    if ordem == "idade_bptf":
        return lambda l: (l.idade_bptf_dias is None, l.idade_bptf_dias or 0, l.listagem.listing_id)
    if ordem == "percentual":
        return lambda l: (l.percentual_venda is None, -(l.percentual_venda or 0.0), l.listagem.listing_id)
    if ordem == "guia":
        return lambda l: (
            l.resultado is None, -(l.resultado.cents if l.resultado else 0), l.listagem.listing_id
        )
    return lambda l: (
        l.potencial is None, -(l.potencial.cents if l.potencial else 0), l.listagem.listing_id
    )


def montar(
    listagens: list[ListagemVarrida],
    indice: PriceIndex | None,
    key_brl: Brl | None,
    filtros: Filtros,
    agora_unix: int | float,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
    vendas_por_par: Mapping[tuple[str, str], Any] | None = None,
) -> Pagina:
    vendas = vendas_por_par or {}
    linhas = [
        avaliar(l, indice, key_brl, agora_unix, filtros.idade_max_bptf_dias, effects_path,
                com_arte=False, venda=vendas.get((l.hash_name, l.efeito)) if l.efeito else None)
        for l in listagens
    ]
    if filtros.so_com_preco and filtros.aba != "revenda":
        linhas = [l for l in linhas if l.resultado is not None]
    if filtros.aba == "lucro":
        linhas = [l for l in linhas if l.resultado is not None and l.resultado.cents > 0]
    if filtros.aba == "revenda":
        linhas = [l for l in linhas if l.potencial is not None and l.potencial.cents > 0]
    linhas.sort(key=_chave_de_ordem(filtros.ordem))

    total = len(linhas)
    paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina = min(max(1, filtros.pagina), paginas)
    inicio = (pagina - 1) * POR_PAGINA
    # A arte só é buscada para as linhas que a página vai mostrar.
    visiveis = [
        replace(
            l,
            arte=_arte(l.listagem, effects_path),
            vendas_url=url_vendas(l.listagem.hash_name, l.listagem.efeito, effects_path),
        )
        for l in linhas[inicio:inicio + POR_PAGINA]
    ]
    return Pagina(visiveis, total, pagina, paginas)
