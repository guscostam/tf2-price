from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Brl:
    """Valor em reais, guardado em centavos inteiros.

    Float para dinheiro acumula erro e faz comparação de igualdade mentir.
    Todo o cálculo do spike decide compra ou não-compra por comparação de
    valores, então o tipo é inteiro por baixo e a conversão é explícita.
    """

    cents: int

    @classmethod
    def from_cents(cls, cents: int) -> "Brl":
        return cls(int(cents))

    @classmethod
    def from_float(cls, reais: float) -> "Brl":
        return cls(round(reais * 100))

    @property
    def as_float(self) -> float:
        return self.cents / 100

    def __add__(self, other: "Brl") -> "Brl":
        return Brl(self.cents + other.cents)

    def __sub__(self, other: "Brl") -> "Brl":
        return Brl(self.cents - other.cents)

    def __mul__(self, factor: float) -> "Brl":
        return Brl(round(self.cents * factor))

    def __str__(self) -> str:
        # Python formata no padrão en-US; trocamos os separadores via
        # marcador temporário para não embaralhar ponto com vírgula.
        formatted = f"{self.as_float:,.2f}"
        formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        return f"R$ {formatted}"

