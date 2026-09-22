"""Pedidos de acesso: o que a landing aceita e como o admin os resolve.

A entrada é pública. Por isso o perfil da Steam só passa se tiver exatamente
uma das duas formas que a Steam usa, e é gravado numa forma canônica: é essa
forma que o admin abre como link, e é por ela que dois pedidos da mesma
pessoa se reconhecem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTATO_MAXIMO = 200
OBSERVACAO_MAXIMA = 1000

# `[0-9]` e não `\d`: em `str`, `\d` aceita dígitos de qualquer escrita.
# `fullmatch` ancora nas duas pontas sem o furo do `$` antes de "\n".
_PERFIL = re.compile(
    r"(?:https?://)?(?:www\.)?steamcommunity\.com/"
    r"(?:id/(?P<nome>[A-Za-z0-9_-]{2,32})|profiles/(?P<id>[0-9]{17}))/?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Pedido:
    perfil_steam: str
    contato: str
    observacao: str | None


def normalizar_perfil_steam(texto: str) -> str | None:
    casou = _PERFIL.fullmatch(texto.strip(" \t"))
    if casou is None:
        return None
    if casou["id"]:
        return f"https://steamcommunity.com/profiles/{casou['id']}"
    # A Steam não diferencia maiúsculas no nome personalizado.
    return f"https://steamcommunity.com/id/{casou['nome'].lower()}"


def validar_pedido(
    perfil_steam: str, contato: str, observacao: str
) -> tuple[Pedido | None, dict[str, str]]:
    erros: dict[str, str] = {}
    perfil = normalizar_perfil_steam(perfil_steam)
    if perfil is None:
        erros["perfil_steam"] = (
            "Enter a steamcommunity.com/id/… or steamcommunity.com/profiles/… link."
        )
    contato = contato.strip()
    if not contato:
        erros["contato"] = "Tell us where to send the invite."
    elif len(contato) > CONTATO_MAXIMO:
        erros["contato"] = f"Use at most {CONTATO_MAXIMO} characters."
    observacao = observacao.strip()
    if len(observacao) > OBSERVACAO_MAXIMA:
        erros["observacao"] = f"Use at most {OBSERVACAO_MAXIMA} characters."
    if erros:
        return None, erros
    return Pedido(perfil_steam=perfil, contato=contato, observacao=observacao or None), {}
