"""Regras puras de validação da coleta (sem navegador): título x cadastro, sanidade de preço e status."""
import re
from dataclasses import dataclass

from .status import StatusColeta

# Extras que definem uma variante diferente do mesmo modelo (S25 != S25 Ultra).
# "5G" é tratado à parte: só é exigido quando consta no cadastro, porque as lojas
# costumam anunciar "S25 5G" para produtos cadastrados apenas como "S25".
_VARIANTES = ("FE", "ULTRA", "EDGE", "PLUS", "PRO", "MAX", "LITE")

_ARMAZENAMENTO_RE = re.compile(r"\b(\d{1,4})\s*(gb|tb)\b", re.IGNORECASE)


@dataclass
class Leitura:
    """O que o adaptador da loja conseguiu ler da página."""

    url_final: str = ""
    carregou: bool = True
    url_de_produto: bool = True
    titulo: str | None = None
    vendedor: str | None = None
    pix_texto: str | None = None
    cartao_texto: str | None = None
    bloqueio: bool = False
    pagina_404: bool = False
    indisponivel: bool = False


def _squash(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def _cabecalho(titulo: str) -> str:
    """Trecho do título que descreve o modelo: até a primeira vírgula e até o armazenamento."""
    head = titulo.split(",")[0]
    m = _ARMAZENAMENTO_RE.search(head)
    if m:
        head = head[: m.end()]
    # "S24+" -> "S24 plus"; "50+12+10MP" (câmeras) não é variante
    return re.sub(r"\b([a-z]+\d+)\+(?!\d)", r"\1 plus", head, flags=re.IGNORECASE)


def titulo_confere(titulo: str | None, marca: str, modelo: str, armazenamento: str, extras: str) -> tuple[bool, str]:
    """Compara o título lido com os atributos cadastrados. Regras duras: qualquer divergência reprova."""
    if not titulo:
        return False, "título vazio"
    head = _cabecalho(titulo)
    tokens = set(re.findall(r"[a-z0-9]+", head.lower()))

    if marca and _squash(marca) not in _squash(titulo):
        return False, f"marca '{marca}' não aparece no título"

    if modelo:
        # Aceita espaços em qualquer ponto ("Fold 7" = "Fold7"), mas o modelo não pode ser prefixo
        # de outro token ("S2" não casa com "S25"; "S25 5G" não vira "S255G").
        padrao = r"(?<![a-z0-9])" + r"\s*".join(re.escape(c) for c in _squash(modelo)) + r"(?![a-z0-9])"
        if not re.search(padrao, head.lower()):
            return False, f"modelo '{modelo}' não aparece no título"

    if armazenamento:
        no_titulo = {f"{n}{u}".lower() for n, u in _ARMAZENAMENTO_RE.findall(titulo)}
        if armazenamento.lower() not in no_titulo:
            return False, f"armazenamento {armazenamento} não aparece no título"

    cadastrados = {e.strip().upper() for e in (extras or "").split(",") if e.strip()}
    cadastrados = {"PLUS" if e == "+" else e for e in cadastrados}
    no_head = {v for v in _VARIANTES if v.lower() in tokens}
    cadastradas_variantes = cadastrados & set(_VARIANTES)
    if no_head != cadastradas_variantes:
        return False, f"variante do título {sorted(no_head)} difere do cadastro {sorted(cadastradas_variantes)}"
    if "5G" in cadastrados and "5g" not in tokens:
        return False, "5G consta no cadastro e não no título"

    return True, ""


def variacao_pct(atual_centavos: int, anterior_centavos: int) -> float:
    return abs(atual_centavos - anterior_centavos) / anterior_centavos * 100


def eh_suspeito(atual_centavos: int | None, ultimo_valido_centavos: int | None, limite_pct: float) -> bool:
    if atual_centavos is None or not ultimo_valido_centavos:
        return False
    return variacao_pct(atual_centavos, ultimo_valido_centavos) > limite_pct


def classificar(leitura: Leitura, preco_pix_centavos: int | None, marca: str, modelo: str, armazenamento: str, extras: str) -> tuple[StatusColeta, str]:
    """Devolve (status, detalhe). Nunca devolve OK sem preço válido."""
    if leitura.bloqueio:
        return StatusColeta.BLOQUEIO, "página de verificação/captcha"
    if leitura.pagina_404:
        return StatusColeta.LINK_QUEBRADO, "página não encontrada"
    if not leitura.url_de_produto:
        return StatusColeta.LINK_QUEBRADO, f"redirecionou para página que não é de produto: {leitura.url_final}"
    if not leitura.titulo:
        if not leitura.carregou:
            return StatusColeta.TIMEOUT, "página não carregou a tempo"
        return StatusColeta.LINK_QUEBRADO, "página sem título de produto"
    confere, motivo = titulo_confere(leitura.titulo, marca, modelo, armazenamento, extras)
    if not confere:
        return StatusColeta.PRODUTO_DIVERGENTE, motivo
    if leitura.indisponivel:
        return StatusColeta.INDISPONIVEL, "produto sem estoque"
    if preco_pix_centavos is None:
        return StatusColeta.PRECO_NAO_ENCONTRADO, "preço PIX não encontrado na página"
    return StatusColeta.OK, ""
