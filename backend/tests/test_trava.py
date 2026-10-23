import os

import pytest

from searching.core.trava import ColetaEmAndamento, TravaColeta


def test_segunda_trava_e_recusada_e_liberada_ao_sair(tmp_path):
    caminho = tmp_path / "coleta.lock"
    with TravaColeta(caminho):
        with pytest.raises(ColetaEmAndamento):
            with TravaColeta(caminho):
                pass
    assert not caminho.exists()
    with TravaColeta(caminho):  # liberada, pode pegar de novo
        pass


def test_trava_de_processo_morto_e_reaproveitada(tmp_path):
    caminho = tmp_path / "coleta.lock"
    caminho.write_text("999999999")  # PID inexistente
    with TravaColeta(caminho):
        assert caminho.read_text() == str(os.getpid())


def test_trava_com_lixo_e_reaproveitada(tmp_path):
    caminho = tmp_path / "coleta.lock"
    caminho.write_text("não é um pid")
    with TravaColeta(caminho):
        pass
