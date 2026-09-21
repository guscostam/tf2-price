"""O que a página manda o navegador buscar fora daqui.

Script de terceiro sem `integrity` é uma porta: quem controlar o CDN passa a
executar JS na página com login. O teste vale para qualquer `<script src>`
externo que apareça depois, não só para o htmx de hoje — é por isso que ele
varre os templates em vez de conferir um hash escrito à mão.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / "tf2price" / "painel" / "templates"

_SCRIPT = re.compile(r"<script\b[^>]*\bsrc=[\"'](?P<src>[^\"']+)[\"'][^>]*>", re.I)


def _scripts_externos() -> list[tuple[Path, str]]:
    achados = []
    for arquivo in sorted(TEMPLATES.glob("*.html")):
        texto = arquivo.read_text(encoding="utf-8")
        for tag in _SCRIPT.finditer(texto):
            if tag.group("src").startswith(("http://", "https://", "//")):
                achados.append((arquivo, tag.group(0)))
    return achados


def test_existe_pelo_menos_um_para_conferir():
    """Rede de segurança: se o htmx sair da página, este arquivo para de
    provar qualquer coisa em silêncio."""
    assert _scripts_externos()


@pytest.mark.parametrize(
    "arquivo,tag", _scripts_externos(), ids=lambda v: getattr(v, "name", "")
)
def test_script_de_terceiro_tem_integrity_e_crossorigin(arquivo, tag):
    assert "integrity=" in tag, f"{arquivo.name}: script externo sem integrity"
    # Sem `crossorigin`, o navegador não consegue conferir o hash de outra
    # origem e recusa o arquivo — o htmx simplesmente não carregaria.
    assert "crossorigin=" in tag, f"{arquivo.name}: integrity sem crossorigin"


def test_a_versao_e_o_hash_andam_juntos():
    """Trocar a versão sem trocar o hash quebra a página; trocar o hash sem a
    versão também. Este teste falha se alguém mexer num só."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "htmx.org@1.9.12/dist/htmx.min.js" in base
    assert (
        "sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
        in base
    )
