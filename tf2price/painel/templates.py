"""Template Jinja2 único, compartilhado por todos os roteadores do painel."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

def _keys(value: float) -> str:
    return f"{value:.1f}"


TEMPLATES.env.filters["keys"] = _keys
