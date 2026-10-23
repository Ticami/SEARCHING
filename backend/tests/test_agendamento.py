import json

from searching import agendamento
from searching.db.models import Execucao
from searching.db.session import criar_engine, iniciar_banco
from datetime import datetime, timedelta


def test_config_padrao_e_todos_os_dias_as_12h(tmp_path):
    cfg = agendamento.carregar_config(tmp_path / "nao_existe.json")
    assert cfg["times"] == ["12:00"]
    assert cfg["days"] == agendamento.TODOS_OS_DIAS
    assert cfg["enabled"] is False


def test_config_salva_e_recarrega(tmp_path):
    caminho = tmp_path / "config.json"
    agendamento.salvar_config({"enabled": True, "times": ["09:00"], "days": ["mon"], "stores": ["magalu"]}, caminho)
    cfg = agendamento.carregar_config(caminho)
    assert cfg["enabled"] and cfg["times"] == ["09:00"] and cfg["stores"] == ["magalu"]
    assert cfg["include"] == []  # chaves ausentes recebem o padrão


def test_config_corrompida_volta_ao_padrao(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text("{ não é json")
    assert agendamento.carregar_config(caminho)["times"] == ["12:00"]


def test_filtros_da_agenda(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps({"stores": ["magalu"], "include": ["Samsung Galaxy S25 256GB"]}))
    assert agendamento.filtros_da_agenda(caminho) == (["magalu"], ["Samsung Galaxy S25 256GB"], [])


def test_validacao_de_horario_e_dias():
    assert agendamento.horario_valido("12:00") and agendamento.horario_valido("00:05")
    assert not agendamento.horario_valido("24:00") and not agendamento.horario_valido("9:00")
    assert agendamento.normalizar_dias(["seg", "Sex", "xyz", "mon"]) == ["mon", "fri"]


def test_comando_de_instalacao_para_o_usuario():
    cmd = agendamento.comando_instalacao(["09:00", "18:30"], ["mon", "fri"])
    assert "instalar_agendamento.ps1" in cmd and "-Horas 09:00,18:30" in cmd and "-Dias Mon,Fri" in cmd


def test_ultima_execucao(tmp_path):
    fabrica = iniciar_banco(criar_engine(tmp_path / "t.db"))
    with fabrica() as s:
        assert agendamento.ultima_execucao(s) is None
        inicio = datetime(2026, 10, 23, 12, 0, 0)
        s.add(Execucao(iniciada_em=inicio - timedelta(days=1), finalizada_em=inicio - timedelta(days=1), origem="agendada", total=1))
        s.add(Execucao(iniciada_em=inicio, finalizada_em=inicio + timedelta(minutes=7), origem="agendada", total=12, ok=10, falhas=2))
        s.commit()
        ultima = agendamento.ultima_execucao(s)
        assert (ultima["total"], ultima["ok"], ultima["falhas"], ultima["duracao_s"]) == (12, 10, 2, 420)
        assert ultima["em_andamento"] is False
