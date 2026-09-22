"""A chave de referência: quanto uma chave vale em dinheiro.

A backpack.tf dá o dólar da chave (`PriceIndex.key_in_usd`) e o Banco Central
dá o dólar em reais (PTAX). O produto é a régua que converte "N chaves" em
reais em toda conta de troca. O preço da chave na Steam não serve para isso:
é saldo preso, e o preço de compra com a taxa embutida. Medido em
22/09/2026: R$ 11,68 na Steam contra ≈ R$ 8,50 aqui. Ver
`specs/2026-09-22-chave-de-referencia-design.md`.

Montada a cada requisição, do que já está em memória (índice) e no banco
(PTAX). Nunca vai à rede.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tf2price.domain.money import Brl
from tf2price.sources.backpacktf import PriceIndex
from tf2price.sources.bcb import Ptax

FALTA_INDICE = "the backpack.tf price index has not loaded yet"
FALTA_PTAX = "the PTAX dollar rate from the Central Bank of Brazil has not loaded yet"
FALTA_DOLAR_BPTF = "backpack.tf did not report a usable dollar value for the key"


@dataclass(frozen=True)
class ChaveReferencia:
    brl: Brl  # o que as contas usam
    usd: float  # dólar da chave na bp.tf
    ptax: float  # reais por dólar
    ptax_data: datetime  # quando o BC fechou a cotação
    bptf_carregado_em: datetime  # idade do dólar da chave

    @property
    def ptax_formatada(self) -> Brl:
        return Brl.from_float(self.ptax)


def montar_referencia(
    indice: PriceIndex | None, ptax: Ptax | None
) -> ChaveReferencia | None:
    if indice is None or ptax is None:
        return None
    usd = indice.key_in_usd()
    if usd is None:
        return None
    # Arredonda uma vez só, na conversão final para centavos.
    brl = Brl.from_cents(round(usd * 100 * ptax.valor))
    if brl.cents <= 0:
        return None
    return ChaveReferencia(
        brl=brl,
        usd=usd,
        ptax=ptax.valor,
        ptax_data=ptax.data,
        bptf_carregado_em=indice.carregado_em,
    )


def motivo_sem_referencia(indice: PriceIndex | None, ptax: Ptax | None) -> str | None:
    """Qual parte falta, para o timbre não ser genérico. None se nada falta."""
    if indice is None:
        return FALTA_INDICE
    if ptax is None:
        return FALTA_PTAX
    if montar_referencia(indice, ptax) is None:
        return FALTA_DOLAR_BPTF
    return None
