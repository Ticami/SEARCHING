from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..core.validacao import Leitura


@dataclass(frozen=True)
class CandidatoBruto:
    """Anúncio encontrado na busca da loja (ainda sem nota de confiança)."""

    url: str
    titulo: str


class LojaAdapter(ABC):
    """Contrato único de uma loja. Seletores e textos próprios da loja ficam só no adaptador."""

    nome: str

    @abstractmethod
    def reconhece(self, url: str) -> bool:
        """True se a URL pertence a esta loja."""

    @abstractmethod
    def carregar(self, driver, url: str, timeout_s: float) -> Leitura:
        """Abre o produto e lê título, vendedor, preço PIX e sinais de erro (sem abrir menus)."""

    @abstractmethod
    def ler_cartao_1x(self, driver, timeout_s: float) -> str | None:
        """Lê o preço à vista no cartão de crédito (1x). Pode interagir com a página."""

    def ler_html(self, html: str, url_final: str, html_modal: str | None = None) -> Leitura:
        """Lê uma página já aberta por outra via (coleta assistida): HTML da página e, se houver, do menu de pagamento."""
        raise NotImplementedError(f"{self.nome} não suporta a coleta assistida")

    # --- recuperação de links (opcional: lojas sem suporte devolvem vazio) ---

    def codigo_produto(self, url: str) -> str | None:
        """Identificador estável do produto dentro da URL (ex.: o trecho /p/<código>/ da Magalu)."""
        return None

    def urls_base(self, url: str) -> list[str]:
        """URLs mais simples que costumam levar ao mesmo produto (sem parâmetros, só o caminho base)."""
        return []

    def url_busca(self, termo: str) -> str | None:
        """URL da busca da própria loja para o termo."""
        return None

    def buscar(self, driver, termo: str, timeout_s: float) -> list[CandidatoBruto]:
        """Abre a busca da loja e devolve os anúncios da primeira página."""
        return []
