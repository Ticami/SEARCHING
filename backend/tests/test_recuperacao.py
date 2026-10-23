from dataclasses import dataclass

import pytest

from searching.adapters.base import CandidatoBruto, LojaAdapter
from searching.core.validacao import Leitura
from searching.links.recuperacao import Candidato, decidir, nota_confianca, recuperar


@dataclass
class P:
    """Produto mínimo (só o que a recuperação lê)."""

    nome_comercial: str
    marca: str = "Samsung"
    modelo: str = "Galaxy S25"
    armazenamento: str = "256GB"
    extras: str = ""
    url_atual: str = "https://l/antigo/p/velho1/te/x/?a=1"


S25 = P("Samsung Galaxy S25 256GB")
S25_ULTRA = P("Samsung Galaxy S25 Ultra 256GB", extras="ULTRA")
A17_128 = P("Samsung Galaxy A17 5G 128GB", modelo="Galaxy A17", armazenamento="128GB", extras="5G")


@pytest.mark.parametrize(
    "produto, titulo, esperado",
    [
        (S25, "Samsung Galaxy S25 5G, 256GB, 12GB RAM", 0.90),  # título idêntico ao cadastro
        (S25, "Samsung Galaxy S25 5G, 256GB, 12GB RAM", 0.90),
        (S25, "Celular Samsung Galaxy S25 Plus 5G, 256GB", 0.0),  # variante diferente
        (S25, "Celular Samsung Galaxy S25 Ultra 5G, 256GB", 0.0),  # S25 não vira Ultra
        (S25_ULTRA, "Celular Samsung Galaxy S25 5G, 256GB", 0.0),  # nem o contrário
        (S25, "Celular Samsung Galaxy S25 FE 5G, 256GB", 0.0),
        (S25, "Samsung Galaxy S25 5G, 512GB", 0.0),
        (A17_128, "Celular Samsung Galaxy A17 5G com IA, 128GB, 4GB RAM", 0.90),
        (A17_128, "Celular Samsung Galaxy A17 5G com IA, 256GB, 8GB RAM", 0.0),  # 128 GB não vira 256 GB
        (S25, "Samsung Galaxy S25 5G Edição Especial Colecionador, 256GB", 0.80),  # passa, mas título diferente
    ],
)
def test_nota_de_confianca(produto, titulo, esperado):
    assert nota_confianca(produto, titulo) == esperado


def test_mesmo_codigo_de_produto_sobe_a_nota():
    assert nota_confianca(S25, "Samsung Galaxy S25 5G, 256GB", mesmo_codigo=True) == 1.0
    assert nota_confianca(S25, "Samsung Galaxy S25 5G Edição Especial, 256GB", mesmo_codigo=True) == 0.90


def _c(url, nota, verificado=True):
    return Candidato(url, "t", nota, "busca", verificado)


def test_decidir_exige_limite_verificacao_e_ausencia_de_rival():
    assert decidir([_c("a", 0.90)], 0.90).url == "a"
    assert decidir([_c("a", 0.85)], 0.90) is None  # abaixo do limite
    assert decidir([_c("a", 1.0, verificado=False)], 0.90) is None  # página não confirmada
    assert decidir([_c("a", 0.90), _c("b", 0.90)], 0.90) is None  # empate: ambíguo (ex.: duas cores)
    assert decidir([_c("a", 1.0), _c("b", 0.90)], 0.90).url == "a"  # folga de 0,10 resolve
    assert decidir([_c("a", 0.90), _c("b", 0.0)], 0.90).url == "a"  # nota 0 não é rival
    assert decidir([], 0.90) is None


# ---------- estratégias, com loja falsa ----------
class DriverFalso:
    pass


class NavegadorFalso:
    def obter(self):
        return DriverFalso()


class LojaFalsa(LojaAdapter):
    nome = "Falsa"

    def __init__(self, paginas: dict[str, Leitura], busca: list[CandidatoBruto] | None = None, bases: list[str] | None = None):
        self.paginas, self.busca, self.bases = paginas, busca or [], bases or []
        self.abertas: list[str] = []
        self.buscas = 0

    def reconhece(self, url):
        return True

    def carregar(self, driver, url, timeout_s):
        self.abertas.append(url)
        return self.paginas.get(url, Leitura(url_final=url, url_de_produto=False, pagina_404=True))

    def ler_cartao_1x(self, driver, timeout_s):
        return None

    def codigo_produto(self, url):
        partes = url.split("/p/")
        return partes[1].split("/")[0] if len(partes) > 1 else None

    def urls_base(self, url):
        return self.bases

    def buscar(self, driver, termo, timeout_s):
        self.buscas += 1
        return self.busca


def _pagina(url, titulo="Samsung Galaxy S25 5G, 256GB, 12GB RAM", preco="R$ 3.799,00"):
    return Leitura(url_final=url, url_de_produto=True, titulo=titulo, pix_texto=preco)


def _rodar(loja, produto=S25, falha=None, limite=0.90):
    pausas = []
    rec = recuperar(NavegadorFalso(), loja, produto, falha, limite, 5.0, lambda: pausas.append(1))
    return rec, pausas


def test_estrategia_1_redirecionamento_para_pagina_de_produto():
    nova = "https://l/novo/p/novo1/"
    falha = _pagina(nova)
    loja = LojaFalsa({})
    rec, pausas = _rodar(loja, falha=falha)
    assert rec.escolhido.url == nova and rec.estrategia == "redirecionamento"
    assert loja.abertas == [] and loja.buscas == 0  # nenhuma requisição extra


def test_estrategia_2_caminho_base_com_mesmo_codigo():
    base = "https://l/antigo/p/velho1/"
    loja = LojaFalsa({base: _pagina(base)}, bases=[base])
    rec, _ = _rodar(loja, falha=Leitura(url_final=S25.url_atual, pagina_404=True, url_de_produto=False))
    assert rec.escolhido.url == base and rec.escolhido.nota == 1.0
    assert loja.buscas == 0  # parou na estratégia 2


def test_estrategia_3_busca_com_unico_candidato_confiavel():
    novo = "https://l/novo/p/novo2/"
    loja = LojaFalsa(
        {novo: _pagina(novo)},
        busca=[CandidatoBruto("https://l/u/p/ultra/", "Samsung Galaxy S25 Ultra 5G, 256GB"), CandidatoBruto(novo, "Samsung Galaxy S25 5G, 256GB, 12GB RAM")],
    )
    rec, pausas = _rodar(loja)
    assert rec.escolhido.url == novo and rec.escolhido.verificado
    assert [c.url for c in rec.candidatos] == [novo]  # o Ultra foi descartado pelas regras duras
    assert len(pausas) >= 2  # pausa antes da busca e antes de abrir o candidato


def test_busca_com_dois_candidatos_iguais_vai_para_revisao():
    a, b = "https://l/a/p/cor1/", "https://l/b/p/cor2/"
    loja = LojaFalsa({}, busca=[CandidatoBruto(a, "Samsung Galaxy S25 5G, 256GB"), CandidatoBruto(b, "Samsung Galaxy S25 5G, 256GB")])
    rec, _ = _rodar(loja)
    assert rec.escolhido is None
    assert {c.url for c in rec.candidatos} == {a, b}
    assert loja.abertas == []  # ambíguo: nem tenta abrir


def test_busca_so_com_variante_errada_nao_sugere_nada():
    loja = LojaFalsa({}, busca=[CandidatoBruto("https://l/u/p/ultra/", "Samsung Galaxy S25 Ultra 5G, 256GB"), CandidatoBruto("https://l/f/p/fe/", "Samsung Galaxy S25 FE 5G, 256GB")])
    rec, _ = _rodar(loja)
    assert rec.escolhido is None and rec.candidatos == []


def test_candidato_confiavel_cuja_pagina_nao_confirma_vai_para_revisao():
    novo = "https://l/novo/p/novo3/"
    loja = LojaFalsa({novo: _pagina(novo, preco=None)}, busca=[CandidatoBruto(novo, "Samsung Galaxy S25 5G, 256GB")])
    rec, _ = _rodar(loja)
    assert rec.escolhido is None  # abriu, mas sem preço: não aplica sozinho


def test_a17_128_nunca_vira_256():
    loja = LojaFalsa({}, busca=[CandidatoBruto("https://l/a/p/a256/", "Celular Samsung Galaxy A17 5G com IA, 256GB, 8GB RAM")])
    rec, _ = _rodar(loja, produto=A17_128)
    assert rec.escolhido is None and rec.candidatos == []


def test_bloqueio_durante_a_recuperacao_interrompe():
    base = "https://l/antigo/p/velho1/"
    loja = LojaFalsa({base: Leitura(url_final=base, titulo="Não é possível acessar a página", bloqueio=True)}, bases=[base])
    rec, _ = _rodar(loja)
    assert rec.bloqueada and rec.escolhido is None
    assert loja.buscas == 0  # não segue para a busca depois de um bloqueio
