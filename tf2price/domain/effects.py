from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_EFFECTS_PATH = Path(__file__).resolve().parent.parent / "data" / "effects.json"


@lru_cache(maxsize=4)
def load_effect_map(path: Path = DEFAULT_EFFECTS_PATH) -> dict[str, int]:
    """Nome do efeito de Unusual para o id usado como priceindex na bp.tf.

    O caminho é parâmetro com default para o módulo continuar testável sem
    tocar no arquivo de produção.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"effects.json não encontrado em {path}. "
            "Rode: .venv/Scripts/python scripts/fetch_effects.py"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): int(effect_id) for name, effect_id in raw.items()}


@lru_cache(maxsize=4)
def _normalized_map(path: Path) -> dict[str, int]:
    return {name.strip().casefold(): eid for name, eid in load_effect_map(path).items()}


def effect_id_for(name: str, path: Path = DEFAULT_EFFECTS_PATH) -> int | None:
    """Busca tolerante a caixa e espaços.

    A Steam devolve o efeito dentro de uma string de descrição; espaço
    extra ou diferença de caixa não deveria fazer o item sumir da análise.
    """
    return _normalized_map(path).get(name.strip().casefold())
