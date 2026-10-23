from datetime import datetime

from sqlalchemy import select

from searching.adapters.base import LojaAdapter
from searching.core.coleta import executar_coleta
from searching.core.trava import TravaColeta
from searching.core.validacao import Leitura
from searching.db.models import Coleta, Execucao, Produto
from searching.db.session import criar_engine, iniciar_banco


class DriverFalso:
    def save_screenshot(self, caminho):
        with open(caminho, "wb") as f:
            f.write(b"png")
        return True


class NavegadorFalso:
    def __init__(self, headless=False):
        self.driver = DriverFalso()
        self.fechado = False

    def obter(self):
        return self.driver

    def reiniciar(self):
        return self.driver

    def fechar(self):
        self.fechado = True


class AdaptadorFalso(LojaAdapter):
    """Responde conforme a URL: 'ok', 'quebrado', 'explode' ou 'lento-depois-ok'."""

    nome = "Falsa"

    def __init__(self):
        self.chamadas = {}

    def reconhece(self, url):
        return True

    def carregar(self, driver, url, timeout_s):
        self.chamadas[url] = self.chamadas.get(url, 0) + 1
        if url.endswith("explode"):
            raise RuntimeError("boom")
        if "bloqueado" in url:
            return Leitura(url_final=url, titulo="Não é possível acessar a página", bloqueio=True)
        if url.endswith("quebrado"):
            return Leitura(url_final=url, pagina_404=True)
        titulo = "Celular Samsung Galaxy S25 5G, 256GB"
        if url.endswith("lento-depois-ok") and self.chamadas[url] == 1:
            return Leitura(url_final=url, titulo=titulo, pix_texto=None)  # 1ª leitura sem preço
        preco = "R$ 100,00" if url.endswith("salto") else "R$ 3.799,00"
        return Leitura(url_final=url, titulo=titulo, vendedor="Samsung", pix_texto=preco)

    def ler_cartao_1x(self, driver, timeout_s):
        return "R$ 3.998,95"


def _montar(tmp_path, urls):
    fabrica = iniciar_banco(criar_engine(tmp_path / "t.db"))
    with fabrica() as s:
        for i, url in enumerate(urls):
            s.add(Produto(nome_comercial=f"Samsung Galaxy S25 256GB v{i}", loja="Magazine Luiza", url_atual=url,
                          marca="Samsung", modelo="Galaxy S25", armazenamento="256GB", extras=""))
        s.commit()
    return fabrica


def _rodar(fabrica, tmp_path, adaptador, dormir=lambda s: None, **kw):
    navegadores = []

    def fabrica_navegador(headless=False):
        navegadores.append(NavegadorFalso(headless))
        return navegadores[-1]

    resumo = executar_coleta(
        fabrica, navegador_factory=fabrica_navegador, adaptador_de=lambda url: adaptador,
        dormir=dormir, prints_dir=tmp_path / "prints", trava=TravaColeta(tmp_path / "x.lock"), **kw,
    )
    return resumo, navegadores


def test_falha_em_um_produto_nao_derruba_os_outros(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/ok", "https://l/quebrado", "https://l/explode"])
    resumo, navegadores = _rodar(fabrica, tmp_path, AdaptadorFalso())

    assert (resumo["total"], resumo["ok"], resumo["falhas"]) == (3, 1, 2)
    assert navegadores[0].fechado
    with fabrica() as s:
        por_url = {c.produto.url_atual: c for c in s.scalars(select(Coleta))}
        assert por_url["https://l/ok"].status == "OK"
        assert por_url["https://l/ok"].preco_pix_centavos == 379900
        assert por_url["https://l/ok"].preco_cartao_1x_centavos == 399895
        assert por_url["https://l/quebrado"].status == "LINK_QUEBRADO"
        assert por_url["https://l/explode"].status == "ERRO_INESPERADO"
        assert "boom" in por_url["https://l/explode"].erro_detalhe
        # nenhuma coleta OK sem preço
        assert all(c.preco_pix_centavos for c in por_url.values() if c.status == "OK")
        execucao = s.scalars(select(Execucao)).one()
        assert execucao.finalizada_em is not None


def test_print_salvo_e_associado_a_coleta(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/ok"])
    _rodar(fabrica, tmp_path, AdaptadorFalso())
    with fabrica() as s:
        coleta = s.scalars(select(Coleta)).one()
        assert coleta.caminho_print.endswith(".png")
        hoje = datetime.now().strftime("%Y-%m-%d")
        assert list((tmp_path / "prints" / hoje).glob("*.png"))


def test_retentativa_quando_preco_nao_aparece(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/lento-depois-ok"])
    adaptador = AdaptadorFalso()
    resumo, _ = _rodar(fabrica, tmp_path, adaptador)
    assert adaptador.chamadas["https://l/lento-depois-ok"] == 2
    assert resumo["ok"] == 1


def test_link_quebrado_nao_gasta_retentativas(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/quebrado"])
    adaptador = AdaptadorFalso()
    _rodar(fabrica, tmp_path, adaptador)
    assert adaptador.chamadas["https://l/quebrado"] == 1


def test_variacao_acima_do_limite_vira_suspeito(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/ok"])
    adaptador = AdaptadorFalso()
    _rodar(fabrica, tmp_path, adaptador)  # 1ª coleta válida: R$ 3.799,00
    with fabrica() as s:
        s.get(Produto, 1).url_atual = "https://l/salto"  # agora o preço lido é R$ 100,00
        s.commit()
    resumo, _ = _rodar(fabrica, tmp_path, adaptador)
    assert resumo["por_status"] == {"SUSPEITO": 1}
    with fabrica() as s:
        assert s.scalars(select(Coleta).order_by(Coleta.id.desc())).first().status == "SUSPEITO"


def test_loja_e_interrompida_apos_dois_bloqueios_seguidos(tmp_path):
    urls = [f"https://l/bloqueado{i}" for i in range(4)]
    fabrica = _montar(tmp_path, urls)
    adaptador = AdaptadorFalso()
    pausas = []
    resumo, _ = _rodar(fabrica, tmp_path, adaptador, dormir=pausas.append)

    assert resumo["por_status"] == {"BLOQUEIO": 4}
    assert sum(adaptador.chamadas.values()) == 2  # só os 2 primeiros chegaram a pedir a página
    assert len(pausas) == 1  # pausa só entre as requisições feitas, nenhuma após os pulados
    with fabrica() as s:
        detalhes = [c.erro_detalhe for c in s.scalars(select(Coleta).order_by(Coleta.id))]
        assert "sem nova requisição" in detalhes[2] and "sem nova requisição" in detalhes[3]


def test_sucesso_zera_a_contagem_de_bloqueios(tmp_path):
    urls = ["https://l/bloqueado1", "https://l/ok", "https://l/bloqueado2", "https://l/ok2"]
    fabrica = _montar(tmp_path, urls)
    adaptador = AdaptadorFalso()
    _rodar(fabrica, tmp_path, adaptador)
    assert sum(adaptador.chamadas.values()) == 4  # nenhum foi pulado


def test_filtros_de_loja_e_modelo(tmp_path):
    fabrica = _montar(tmp_path, ["https://l/ok", "https://l/ok2"])
    resumo, _ = _rodar(fabrica, tmp_path, AdaptadorFalso(), stores=["amazon"])
    assert resumo["total"] == 0
    resumo, _ = _rodar(fabrica, tmp_path, AdaptadorFalso(), stores=["magalu"], include=["Samsung Galaxy S25 256GB"])
    assert resumo["total"] == 2
    resumo, _ = _rodar(fabrica, tmp_path, AdaptadorFalso(), include=["Samsung Galaxy A17 5G 128GB"])
    assert resumo["total"] == 0
    resumo, _ = _rodar(fabrica, tmp_path, AdaptadorFalso(), exclude=["Samsung Galaxy S25 256GB"])
    assert resumo["total"] == 0
