from __future__ import annotations

import re
from dataclasses import dataclass

QUALITY_UNIQUE = 6

# Ids do schema do TF2. Não são sequenciais e não devem ser "arrumados".
QUALITY_PREFIXES: dict[str, int] = {
    "Genuine": 1,
    "Vintage": 3,
    "Unusual": 5,
    "Strange": 11,
    "Haunted": 13,
    "Collector's": 14,
}

# Itens Unique cujo nome começa com uma palavra de qualidade. Sem esta lista,
# "Strange Part: Kills" viraria um "Part: Kills" de qualidade Strange, que não
# existe, e o item sumiria da análise sem aviso.
QUALITY_PREFIX_EXCEPTIONS: tuple[str, ...] = (
    "Strange Part:",
    "Strange Filter:",
    "Strange Count Transfer Tool",
    "Strange Bacon Grease",
    "Haunted Metal Scrap",
)

# Ordem importa: o mais longo tem que ser testado primeiro, senão
# "Professional Killstreak X" casaria como "Killstreak" deixando lixo atrás.
KILLSTREAK_PREFIXES: dict[str, int] = {
    "Professional Killstreak": 3,
    "Specialized Killstreak": 2,
    "Killstreak": 1,
}

WEARS: tuple[str, ...] = (
    "Factory New",
    "Minimal Wear",
    "Field-Tested",
    "Well-Worn",
    "Battle Scarred",
)

_WEAR_RE = re.compile(r"\s*\((" + "|".join(re.escape(w) for w in WEARS) + r")\)$")


@dataclass(frozen=True)
class ItemIdentity:
    """O que dá para saber de um item olhando só o nome.

    Tudo que NÃO está aqui — efeito de Unusual, craftabilidade, spells,
    sheen — é incógnita da passada rasa, e é o que a poda das três vias
    precisa tratar.
    """

    base_name: str
    quality_id: int
    killstreak: int
    australium: bool
    festivized: bool
    wear: str | None


def parse_market_hash_name(name: str) -> ItemIdentity:
    rest = name.strip()

    wear: str | None = None
    match = _WEAR_RE.search(rest)
    if match:
        wear = match.group(1)
        rest = rest[: match.start()].strip()

    quality_id = QUALITY_UNIQUE
    killstreak = 0
    australium = False
    festivized = False

    # A ordem dos prefixos variou ao longo de 15 anos de TF2. Em vez de
    # assumir uma sequência, consumimos gulosamente pela frente até nada
    # mais casar.
    changed = True
    while changed:
        changed = False

        for prefix, tier in KILLSTREAK_PREFIXES.items():
            if killstreak == 0 and rest.startswith(prefix + " "):
                killstreak = tier
                rest = rest[len(prefix) + 1 :]
                changed = True
                break
        if changed:
            continue

        if quality_id == QUALITY_UNIQUE and not rest.startswith(QUALITY_PREFIX_EXCEPTIONS):
            for prefix, qid in QUALITY_PREFIXES.items():
                if rest.startswith(prefix + " "):
                    quality_id = qid
                    rest = rest[len(prefix) + 1 :]
                    changed = True
                    break
        if changed:
            continue

        if not festivized and rest.startswith("Festivized "):
            festivized = True
            rest = rest[len("Festivized ") :]
            changed = True
            continue

        if not australium and rest.startswith("Australium "):
            australium = True
            rest = rest[len("Australium ") :]
            changed = True
            continue

    return ItemIdentity(
        base_name=rest,
        quality_id=quality_id,
        killstreak=killstreak,
        australium=australium,
        festivized=festivized,
        wear=wear,
    )


def bptf_name_candidates(identity: ItemIdentity, original: str) -> list[str]:
    """Nomes a tentar no índice da bp.tf, do mais específico ao mais genérico.

    A bp.tf mudou de convenção de nomenclatura várias vezes. Em vez de
    adivinhar qual vale hoje, tentamos em ordem e registramos qual funcionou.
    A distribuição das estratégias vencedoras é um resultado do spike.
    """
    candidates: list[str] = []

    def add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    add(original.strip())
    if identity.australium:
        add(f"Australium {identity.base_name}")
    add(identity.base_name)

    return candidates
