"""Do nome do efeito ao arquivo de arte que nós servimos.

A arte é baixada uma vez pelo navegador (veja `coletor.py`) e vive no
repositório. Nunca é puxada ao vivo: o Cloudflare da backpack.tf recusa
requisição de servidor, e uma dependência que falha no caminho de renderização
não entra aqui.
"""

from __future__ import annotations

from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH, effect_id_for

DIRETORIO = Path(__file__).resolve().parent.parent / "data" / "efeitos"


def url_do_efeito(
    efeito: str,
    diretorio: Path | None = None,
    effects_path: Path | None = None,
) -> str | None:
    """URL local da arte, ou None quando não temos a arte deste efeito.

    Devolver None é uma resposta legítima e frequente: parte dos efeitos não
    tem arte na fonte, e a tela trata essa ausência com tipografia em vez de
    inventar uma aura que não é a daquele efeito.
    """
    ident = effect_id_for(efeito, effects_path or DEFAULT_EFFECTS_PATH)
    if ident is None:
        return None
    arquivo = (diretorio or DIRETORIO) / f"{ident}.webp"
    if not arquivo.is_file():
        return None
    return f"/arte/{ident}.webp"
