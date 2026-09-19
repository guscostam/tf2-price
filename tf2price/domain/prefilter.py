from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tf2price.domain.money import Brl


class Classification(str, Enum):
    """Resultado da poda para um market_hash_name."""

    GUARANTEED = "garantida"
    CANDIDATE = "candidata"
    DISCARDED = "descartada"


@dataclass(frozen=True)
class ValueRange:
    """Faixa de valor justo em chaves, sobre todas as interpretações possíveis
    do nome — cada efeito de Unusual × craftável e não-craftável."""

    min_keys: float
    max_keys: float

    def __post_init__(self) -> None:
        if self.min_keys > self.max_keys:
            raise ValueError(
                f"faixa invertida: min_keys={self.min_keys} > max_keys={self.max_keys}"
            )


def classify(
    steam_lowest: Brl,
    value_range: ValueRange,
    key_brl: Brl,
    threshold: float,
) -> Classification:
    """Classifica um nome avaliando o cenário mais e o menos favorável.

    - Abaixo do piso: vale mesmo no PIOR cenário (não-craftável, pior efeito).
      Entra no líquido sem precisar de fetch profundo.
    - Abaixo do teto: só vale em ALGUM cenário. Precisa de fetch profundo
      para resolver as incógnitas.
    - Acima do teto: nenhuma listagem deste nome pode ser negócio. Descarta o
      nome inteiro, que é o que torna a varredura barata.
    """
    floor = key_brl * (value_range.min_keys * (1 - threshold))
    ceiling = key_brl * (value_range.max_keys * (1 - threshold))

    if steam_lowest < floor:
        return Classification.GUARANTEED
    if steam_lowest < ceiling:
        return Classification.CANDIDATE
    return Classification.DISCARDED
