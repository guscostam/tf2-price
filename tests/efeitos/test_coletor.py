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


def test_verificar_agrupa_apenas_bytes_repetidos(tmp_path):
    """Dois arquivos com os mesmos bytes são placeholder; o diferente, não."""
    coletor.gravar(1, b"placeholder-generico", tmp_path)
    coletor.gravar(2, b"placeholder-generico", tmp_path)
    coletor.gravar(3, b"arte de verdade", tmp_path)

    grupos = coletor.verificar(tmp_path)

    assert len(grupos) == 1
    (ids,) = grupos.values()
    assert sorted(ids) == [1, 2]
