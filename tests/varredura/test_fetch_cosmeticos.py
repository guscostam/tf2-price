from __future__ import annotations

import json

from scripts import fetch_cosmeticos


def test_gerador_escreve_nomes_e_todos_os_defindices_sem_rede(monkeypatch, tmp_path):
    itens = [
        {"item_name": "Team Captain", "defindex": 378, "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Team Captain", "defindex": 999, "item_class": "tf_wearable", "item_slot": "head"},
        {"item_name": "Taunt: Chairholder", "defindex": 31578, "item_class": "tf_wearable", "item_slot": "taunt"},
    ]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"items": itens}}

    chamadas = []
    monkeypatch.setenv("STEAM_API_KEY", "TEST_TOKEN")
    monkeypatch.setattr(fetch_cosmeticos, "load_dotenv", lambda: None)
    monkeypatch.setattr(fetch_cosmeticos.httpx, "get", lambda *args, **kwargs: (chamadas.append((args, kwargs)), Response())[1])
    monkeypatch.setattr(fetch_cosmeticos, "COSMETICOS_PATH", tmp_path / "cosmeticos.json")
    monkeypatch.setattr(fetch_cosmeticos, "COSMETICOS_DEFINDEX_PATH", tmp_path / "cosmeticos_defindices.json", raising=False)

    assert fetch_cosmeticos.main() == 0
    assert json.loads((tmp_path / "cosmeticos.json").read_text(encoding="utf-8")) == ["Team Captain"]
    assert json.loads((tmp_path / "cosmeticos_defindices.json").read_text(encoding="utf-8")) == {"Team Captain": [378, 999]}
    assert len(chamadas) == 1
