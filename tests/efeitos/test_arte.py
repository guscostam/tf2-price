from __future__ import annotations

from pathlib import Path

from tf2price.efeitos import arte

EFEITOS = Path(__file__).resolve().parent.parent / "fixtures" / "effects_sample.json"


def test_efeito_com_arte_vira_url(tmp_path):
    """Burning Flames é 13 na fixture de efeitos."""
    (tmp_path / "13.webp").write_bytes(b"nao importa")
    assert arte.url_do_efeito("Burning Flames", tmp_path, EFEITOS) == "/arte/13.webp"


def test_efeito_sem_arquivo_nao_inventa_url(tmp_path):
    """17% dos efeitos não têm arte na fonte. Eles não ganham aura genérica."""
    assert arte.url_do_efeito("Burning Flames", tmp_path, EFEITOS) is None


def test_efeito_fora_do_mapa_e_none(tmp_path):
    (tmp_path / "13.webp").write_bytes(b"nao importa")
    assert arte.url_do_efeito("Efeito Que Nao Existe", tmp_path, EFEITOS) is None


def test_nome_de_arquivo_nao_aceita_travessia(tmp_path):
    """O id vem do nosso mapa, mas a rota que serve isto recebe texto de fora."""
    assert arte.url_do_efeito("../../etc/passwd", tmp_path, EFEITOS) is None
