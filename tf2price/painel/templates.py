"""Template Jinja2 único, compartilhado por todos os roteadores do painel."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _chaves(valor: float) -> str:
    """Quantidade de chaves com vírgula decimal, como o resto da tela."""
    return f"{valor:.1f}".replace(".", ",")


TEMPLATES.env.filters["chaves"] = _chaves
