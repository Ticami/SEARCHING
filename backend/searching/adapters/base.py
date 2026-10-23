from abc import ABC, abstractmethod

from ..core.validacao import Leitura


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
