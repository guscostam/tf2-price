"""`ItemPage` para dicionário e de volta, para o retrato caber numa coluna.

Guardar o HTML seria 266 KB por item; o retrato serializado é alguns KB. A
conversão é explícita, e não um `pickle`, porque este dado vai para o banco e
precisa continuar legível quando a forma do `ItemPage` mudar.
"""

from __future__ import annotations

from typing import Any

from tf2price.domain.money import Brl
from tf2price.sources.steam_page import ItemPage, OrderBook, PageListing, SalePoint

# Sobe quando a forma mudar. Um retrato gravado com versão diferente é
# descartado em vez de lido torto — ler campo que mudou de significado é
# exatamente como um preço vira outro.
VERSAO = 1


def _centavos(valor: Brl | None) -> int | None:
    return None if valor is None else valor.cents


def _brl(valor: int | None) -> Brl | None:
    return None if valor is None else Brl(int(valor))


def para_dict(pagina: ItemPage) -> dict[str, Any]:
    return {
        "versao": VERSAO,
        "hash_name": pagina.hash_name,
        "listings": [
            {
                "listing_id": l.listing_id,
                "total_price": l.total_price.cents,
                "effect": l.effect,
                "icon_url": l.icon_url,
            }
            for l in pagina.listings
        ],
        "orderbook": {
            "max_buy_order": _centavos(pagina.orderbook.max_buy_order),
            "min_sell_order": _centavos(pagina.orderbook.min_sell_order),
            "buy_orders": pagina.orderbook.buy_orders,
            "sell_orders": pagina.orderbook.sell_orders,
        },
        "history": [
            {"when": p.when, "median": p.median.cents, "purchases": p.purchases}
            for p in pagina.history
        ],
    }


def de_dict(dados: dict[str, Any]) -> ItemPage:
    if dados.get("versao") != VERSAO:
        raise ValueError(f"versão de retrato desconhecida: {dados.get('versao')!r}")
    livro = dados["orderbook"]
    return ItemPage(
        hash_name=dados["hash_name"],
        listings=[
            PageListing(
                listing_id=l["listing_id"],
                total_price=Brl(int(l["total_price"])),
                effect=l["effect"],
                icon_url=l["icon_url"],
            )
            for l in dados["listings"]
        ],
        orderbook=OrderBook(
            max_buy_order=_brl(livro["max_buy_order"]),
            min_sell_order=_brl(livro["min_sell_order"]),
            buy_orders=int(livro["buy_orders"]),
            sell_orders=int(livro["sell_orders"]),
        ),
        history=[
            SalePoint(when=int(p["when"]), median=Brl(int(p["median"])), purchases=int(p["purchases"]))
            for p in dados["history"]
        ],
    )
