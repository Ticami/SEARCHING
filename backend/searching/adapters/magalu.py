import re
import time
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..core.precos import PRECO_RE
from ..core.validacao import Leitura
from .base import CandidatoBruto, LojaAdapter

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

SEL_LINKS_BUSCA = "a[href*='/p/']"
SEL_TITULO_CARD = "[data-testid='product-title']"
MAX_RESULTADOS_BUSCA = 20

_PRODUTO_RE = re.compile(r"/p/[^/]+/")
_UMA_PARCELA_RE = re.compile(r"(?<!\d)1x")  # "1x", mas não "11x" nem "12x"
_CODIGO_RE = re.compile(r"/p/([^/]+)/")


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

    def codigo_produto(self, url: str) -> str | None:
        m = _CODIGO_RE.search(urlparse(url or "").path)
        return m.group(1) if m else None

    def urls_base(self, url: str) -> list[str]:
        """Sem parâmetros e sem o trecho de vitrine (/te/...), e depois só /p/<código>/."""
        partes = urlparse(url or "")
        m = re.match(r"^(.*?/p/[^/]+/)", partes.path)
        if not m:
            return []
        base = f"{partes.scheme}://{partes.netloc}"
        candidatas = [base + m.group(1), f"{base}/p/{self.codigo_produto(url)}/"]
        return [u for i, u in enumerate(candidatas) if u != url and u not in candidatas[:i]]

    def url_busca(self, termo: str) -> str | None:
        termo = re.sub(r"\s+", " ", termo or "").strip()
        return f"https://www.magazineluiza.com.br/busca/{quote(termo)}/" if termo else None

    @staticmethod
    def parse_busca(html: str, url_pagina: str) -> list[CandidatoBruto]:
        """Anúncios (links de produto) da página de resultados. Função pura, testável com HTML salvo."""
        soup = BeautifulSoup(html or "", "html.parser")
        vistos: set[str] = set()
        resultados: list[CandidatoBruto] = []
        for a in soup.select(SEL_LINKS_BUSCA):
            href = urljoin(url_pagina, a.get("href", ""))
            partes = urlparse(href)
            m = _CODIGO_RE.search(partes.path)
            if not m or m.group(1) in vistos:
                continue
            el = a.select_one(SEL_TITULO_CARD)
            titulo = (el or a).get_text(" ", strip=True)
            if not titulo:
                continue
            vistos.add(m.group(1))
            resultados.append(CandidatoBruto(url=f"{partes.scheme}://{partes.netloc}{partes.path}", titulo=titulo))
            if len(resultados) >= MAX_RESULTADOS_BUSCA:
                break
        return resultados

    def buscar(self, driver, termo: str, timeout_s: float) -> list[CandidatoBruto]:
        url = self.url_busca(termo)
        if not url:
            return []
        driver.get(url)
        try:
            WebDriverWait(driver, timeout_s, poll_frequency=0.2).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, SEL_LINKS_BUSCA)
            )
        except Exception:
            pass
        return self.parse_busca(driver.page_source, driver.current_url)

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

    @staticmethod
    def parse_cartao_1x(html: str) -> str | None:
        """Preço à vista no cartão de crédito, lido do menu "opções de pagamento" já aberto na página."""
        soup = BeautifulSoup(html or "", "html.parser")
        for linha in soup.select(SEL_LINHAS_CREDITO):
            texto = re.sub(r"\s+", " ", linha.get_text(" ", strip=True))
            if _UMA_PARCELA_RE.search(texto):
                m = PRECO_RE.search(texto)
                return m.group(0) if m else None
        return None

    def ler_html(self, html: str, url_final: str, html_modal: str | None = None) -> Leitura:
        leitura = self.parse_pagina(html, url_final)
        leitura.cartao_texto = self.parse_cartao_1x(html_modal or html)
        return leitura

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
                texto = re.sub(r"\s+", " ", linha.text)
                if _UMA_PARCELA_RE.search(texto):
                    m = PRECO_RE.search(texto)
                    return m.group(0) if m else None
        except Exception:
            return None
        return None
