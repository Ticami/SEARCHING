import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..core.precos import PRECO_RE
from ..core.validacao import Leitura
from .base import LojaAdapter

# --- Seletores e textos da Magazine Luiza (único lugar a mexer se o layout mudar) ---
SEL_TITULO = ["h1[data-testid='heading-product-title']", "h1[itemprop='name']", "h1"]
SEL_PRECO_PIX = "[data-testid='price-value']"
SEL_VENDEDOR = ["[data-testid='seller-info-name']", "[data-testid='seller-name']"]
SEL_ABRIR_PAGAMENTO = "div[data-testid='rave-payment-card-link'][role='button']"
SEL_MODAL = "[role='dialog'], [data-testid='payment-modal']"
SEL_ABA_CREDITO = "span[data-testid='tab-header-item-Cartão de crédito']"
SEL_LINHAS_CREDITO = "tr[data-testid*='payment-table-Cartão de crédito-item']"

PREFIXOS_VENDEDOR = ("Vendido e entregue por", "Vendido por", "Entregue por", "Loja:")
# Página de bloqueio da própria Magalu ("Não é possível acessar a página (Erro 403)"): vale mesmo com <h1>.
TEXTOS_BLOQUEIO_FORTE = ("erro 403", "erro 429", "não é possível acessar a página")
# Sinais fracos: só contam se a página não tem título de produto (captcha pode ser mencionado no rodapé).
TEXTOS_BLOQUEIO = (
    "captcha",
    "verificação de segurança",
    "verifying you are human",
    "access denied",
    "acesso negado",
    "unusual traffic",
    "tráfego incomum",
)
TEXTOS_404 = ("página não encontrada", "não encontramos a página", "página não existe", "erro 404")
TEXTOS_INDISPONIVEL = ("produto indisponível", "indisponível no momento", "avise-me quando", "produto esgotado")

_PRODUTO_RE = re.compile(r"/p/[^/]+/")


def _limpar_vendedor(texto: str) -> str | None:
    for prefixo in PREFIXOS_VENDEDOR:
        texto = texto.replace(prefixo, "")
    texto = texto.strip()
    return texto or None


class MagaluAdapter(LojaAdapter):
    nome = "Magazine Luiza"

    def reconhece(self, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        return any(k in host for k in ("magazineluiza", "magalu", "magazinevoce"))

    @staticmethod
    def url_e_produto(url: str) -> bool:
        return bool(_PRODUTO_RE.search(urlparse(url or "").path))

    @staticmethod
    def parse_pagina(html: str, url_final: str, carregou: bool = True) -> Leitura:
        """Extrai a leitura do HTML renderizado. Função pura: testável com páginas salvas."""
        soup = BeautifulSoup(html or "", "html.parser")

        titulo = None
        for sel in SEL_TITULO:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                titulo = el.get_text(" ", strip=True)
                break

        pix_texto = None
        el = soup.select_one(SEL_PRECO_PIX)
        if el:
            m = PRECO_RE.search(el.get_text(" ", strip=True))
            pix_texto = m.group(0) if m else None

        vendedor = None
        for sel in SEL_VENDEDOR:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                vendedor = _limpar_vendedor(el.get_text(" ", strip=True))
                break

        texto = soup.get_text(" ", strip=True).lower()
        return Leitura(
            url_final=url_final,
            carregou=carregou,
            url_de_produto=MagaluAdapter.url_e_produto(url_final),
            titulo=titulo,
            vendedor=vendedor,
            pix_texto=pix_texto,
            bloqueio=any(t in texto for t in TEXTOS_BLOQUEIO_FORTE)
            or (titulo is None and any(t in texto for t in TEXTOS_BLOQUEIO)),
            pagina_404=any(t in texto for t in TEXTOS_404) and pix_texto is None,
            indisponivel=pix_texto is None and any(t in texto for t in TEXTOS_INDISPONIVEL),
        )

    def carregar(self, driver, url: str, timeout_s: float) -> Leitura:
        driver.get(url)
        if "//m.magazineluiza.com.br" in driver.current_url:
            driver.get(driver.current_url.replace("//m.magazineluiza.com.br", "//www.magazineluiza.com.br"))

        carregou = True
        try:
            WebDriverWait(driver, timeout_s, poll_frequency=0.2).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, f"{SEL_PRECO_PIX}, h1")
            )
        except Exception:
            carregou = False
        return self.parse_pagina(driver.page_source, driver.current_url, carregou)

    def ler_cartao_1x(self, driver, timeout_s: float) -> str | None:
        deadline = time.monotonic() + timeout_s

        def restante() -> float:
            return max(1.0, deadline - time.monotonic())

        def clicar(el) -> bool:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.3)
                ActionChains(driver).move_to_element(el).pause(0.1).click(el).perform()
                return True
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", el)
                    return True
                except Exception:
                    return False

        try:
            abrir = WebDriverWait(driver, restante()).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_ABRIR_PAGAMENTO))
            )
            if not clicar(abrir):
                return None
            WebDriverWait(driver, restante()).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, SEL_MODAL))
            )
            aba = WebDriverWait(driver, restante()).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_ABA_CREDITO))
            ).find_element(By.XPATH, "ancestor::div[@role='tab'][1]")
            if not clicar(aba):
                return None
            WebDriverWait(driver, restante()).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_LINHAS_CREDITO))
            )
            for linha in driver.find_elements(By.CSS_SELECTOR, SEL_LINHAS_CREDITO):
                if "1x" in linha.text:
                    m = PRECO_RE.search(re.sub(r"\s+", " ", linha.text))
                    return m.group(0) if m else None
        except Exception:
            return None
        return None
