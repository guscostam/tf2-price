"""Saneamento de texto de terceiro antes de ir para o log.

Vive fora de `painel/` e de `preco/` de propósito: as duas camadas precisam
sanear mensagem de exceção antes de logar, e uma delas (`preco/retrato.py`)
fica abaixo de `painel/consulta.py` na pilha de import — colocar a função em
qualquer uma das duas criaria import circular para a outra.
"""

from __future__ import annotations


def mensagem_saneada(erro: Exception) -> str:
    """Corta a mensagem no primeiro '?', onde começa a query string.

    `BackpackTfClient._get` manda a chave da API como parâmetro `key=` na
    URL, e o `str()` de um `httpx.HTTPStatusError` inclui a URL inteira do
    pedido que falhou. A backpack.tf devolve 403 para quem não é navegador,
    então esse caminho é exercitado de verdade, não só em teoria — e o log
    não pode ser onde a chave aparece em claro.
    """
    return str(erro).split("?", 1)[0]
