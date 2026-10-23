"""Recuperação automática de links quebrados: estratégias em ordem, nota de confiança e decisão.

Regras duras (marca, modelo, armazenamento e variantes) vêm de core.validacao.titulo_confere: um candidato
que as viola tem nota 0 e é descartado, então um S25 nunca vira S25 Ultra nem um A17 de 128 GB o de 256 GB.
"""
import logging
import re
from dataclasses import asdict, dataclass

from ..core.precos import parse_preco_centavos
from ..core.status import StatusColeta
from ..core.validacao import Leitura, classificar, titulo_confere

log = logging.getLogger("searching.recuperacao")

# Palavras de marketing que podem aparecer no título sem mudar o produto.
_RUIDO = {"celular", "smartphone", "com", "ia", "ai", "5g", "novo", "dual", "chip"}
MARGEM_AMBIGUIDADE = 0.05
MAX_SUGESTOES = 3


@dataclass
class Candidato:
    url: str
    titulo: str
    nota: float
    estrategia: str
    verificado: bool = False  # a página foi aberta e tem título compatível e preço

    def como_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recuperacao:
    candidatos: list[Candidato]
    escolhido: Candidato | None = None  # só preenchido quando pode ser aplicado sozinho
    bloqueada: bool = False  # a loja bloqueou durante a recuperação: nada foi decidido

    @property
    def estrategia(self) -> str | None:
        ref = self.escolhido or (self.candidatos[0] if self.candidatos else None)
        return ref.estrategia if ref else None


def _tokens_essenciais(texto: str) -> str:
    """Texto sem ruído de marketing e sem armazenamento (o armazenamento já é checado nas regras duras)."""
    palavras = re.findall(r"[a-z0-9]+", texto.lower())
    return "".join(p for p in palavras if p not in _RUIDO and not re.fullmatch(r"\d{1,4}(gb|tb)", p))


def _cabecalho(titulo: str) -> str:
    head = titulo.split(",")[0]
    m = re.search(r"\b\d{1,4}\s*(gb|tb)\b", head, flags=re.IGNORECASE)
    return head[: m.end()] if m else head


def nota_confianca(produto, titulo: str | None, mesmo_codigo: bool = False) -> float:
    """0 se violar uma regra dura; senão 0,80 + 0,10 (título idêntico ao cadastro) + 0,10 (mesmo código do produto)."""
    ok, _ = titulo_confere(titulo, produto.marca, produto.modelo, produto.armazenamento, produto.extras)
    if not ok:
        return 0.0
    nota = 0.80
    if _tokens_essenciais(_cabecalho(titulo)) == _tokens_essenciais(produto.nome_comercial):
        nota += 0.10
    if mesmo_codigo:
        nota += 0.10
    return round(nota, 2)


def decidir(candidatos: list[Candidato], limite: float) -> Candidato | None:
    """Escolhe o candidato só se ele for verificado, atingir o limite e não houver rival quase empatado."""
    validos = sorted((c for c in candidatos if c.nota > 0), key=lambda c: c.nota, reverse=True)
    if not validos:
        return None
    topo = validos[0]
    if not topo.verificado or topo.nota < limite:
        return None
    rivais = [c for c in validos[1:] if c.url != topo.url and topo.nota - c.nota < MARGEM_AMBIGUIDADE]
    return None if rivais else topo


def _avaliar(adaptador, produto, leitura: Leitura, estrategia: str, codigo_antigo: str | None) -> Candidato | None:
    """Transforma uma página aberta em candidato, exigindo título compatível e preço para 'verificado'."""
    if not leitura.url_de_produto or not leitura.titulo:
        return None
    mesmo = bool(codigo_antigo) and adaptador.codigo_produto(leitura.url_final) == codigo_antigo
    nota = nota_confianca(produto, leitura.titulo, mesmo)
    if nota == 0:
        return None
    pix = parse_preco_centavos(leitura.pix_texto)
    status, _ = classificar(leitura, pix, produto.marca, produto.modelo, produto.armazenamento, produto.extras)
    return Candidato(leitura.url_final, leitura.titulo, nota, estrategia, verificado=status == StatusColeta.OK)


def _unicos(candidatos: list[Candidato]) -> list[Candidato]:
    melhores: dict[str, Candidato] = {}
    for c in candidatos:
        atual = melhores.get(c.url)
        if atual is None or (c.verificado, c.nota) > (atual.verificado, atual.nota):
            melhores[c.url] = c
    return sorted(melhores.values(), key=lambda c: (c.nota, c.verificado), reverse=True)


def recuperar(navegador, adaptador, produto, leitura_falha: Leitura | None, limite: float, timeout_s: float, pausar) -> Recuperacao:
    """Tenta achar o anúncio novo. `pausar()` é chamado antes de cada requisição à loja (ritmo moderado)."""
    codigo_antigo = adaptador.codigo_produto(produto.url_atual)
    candidatos: list[Candidato] = []

    def fechar(bloqueada: bool = False) -> Recuperacao:
        todos = _unicos(candidatos)
        return Recuperacao(todos[:MAX_SUGESTOES], None if bloqueada else decidir(todos, limite), bloqueada)

    # 1. A página final do redirecionamento já é de produto?
    if leitura_falha and leitura_falha.bloqueio:
        return fechar(bloqueada=True)
    if leitura_falha and leitura_falha.url_final and leitura_falha.url_final != produto.url_atual:
        cand = _avaliar(adaptador, produto, leitura_falha, "redirecionamento", codigo_antigo)
        if cand:
            candidatos.append(cand)
            if decidir(candidatos, limite):
                return fechar()

    # 2. Link limpo e caminho base do produto (na Magalu, /p/<código>/).
    for url in adaptador.urls_base(produto.url_atual)[:2]:
        try:
            pausar()
            leitura = adaptador.carregar(navegador.obter(), url, timeout_s)
        except Exception as exc:
            log.warning("falha ao abrir %s: %s", url, exc)
            continue
        if leitura.bloqueio:
            return fechar(bloqueada=True)
        cand = _avaliar(adaptador, produto, leitura, "url_base", codigo_antigo)
        if cand:
            candidatos.append(cand)
            if decidir(candidatos, limite):
                return fechar()

    # 3. Busca da própria loja pelo nome comercial.
    try:
        pausar()
        brutos = adaptador.buscar(navegador.obter(), produto.nome_comercial, timeout_s)
    except Exception as exc:
        log.warning("falha na busca de %s: %s", produto.nome_comercial, exc)
        return fechar()

    da_busca = []
    for b in brutos:
        mesmo = bool(codigo_antigo) and adaptador.codigo_produto(b.url) == codigo_antigo
        nota = nota_confianca(produto, b.titulo, mesmo)
        if nota > 0:
            da_busca.append(Candidato(b.url, b.titulo, nota, "busca"))
    da_busca.sort(key=lambda c: c.nota, reverse=True)
    candidatos.extend(da_busca)

    # Só vale tentar aplicar sozinho se o líder isolado já passaria no limite; aí confirmamos abrindo a página.
    if da_busca and da_busca[0].nota >= limite:
        topo = da_busca[0]
        rivais = [c for c in da_busca[1:] if topo.nota - c.nota < MARGEM_AMBIGUIDADE]
        if not rivais:
            try:
                pausar()
                leitura = adaptador.carregar(navegador.obter(), topo.url, timeout_s)
                if leitura.bloqueio:
                    return fechar(bloqueada=True)
                verificado = _avaliar(adaptador, produto, leitura, "busca", codigo_antigo)
                if verificado:
                    # a versão verificada (URL final, após redirecionamentos) substitui a da lista da busca
                    candidatos.remove(topo)
                    candidatos.append(verificado)
            except Exception as exc:
                log.warning("falha ao verificar %s: %s", topo.url, exc)
    return fechar()
