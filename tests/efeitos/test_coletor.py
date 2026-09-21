from __future__ import annotations

from tf2price.efeitos import coletor


def test_ids_a_coletar_ignora_os_sem_nome():
    """O schema tem entradas Attrib_ParticleNNN, que não são efeitos de verdade."""
    ids = coletor.ids_a_coletar()
    assert len(ids) > 400
    assert all(isinstance(i, int) for i in ids)


def test_gravar_cria_o_arquivo_com_o_id(tmp_path):
    caminho = coletor.gravar(13, b"bytes-da-arte", tmp_path)
    assert caminho.name == "13.webp"
    assert caminho.read_bytes() == b"bytes-da-arte"


def test_gravar_recusa_id_invalido(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        coletor.gravar(-1, b"x", tmp_path)
