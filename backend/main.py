import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
try:
    import pyautogui  # requer display; em ambiente headless pode falhar
except Exception:
    pyautogui = None
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    InvalidSessionIdException,
    TimeoutException,
)
from webdriver_manager.chrome import ChromeDriverManager


# ==============================
# 🗂️ CONFIGURAÇÕES E PASTAS
# ==============================
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
PRINTS_DIR = os.path.join(BASE_DIR, "prints")
LINKS_PATH = os.path.join(BASE_DIR, "links.csv")
HIST_PATH = os.path.join(DATA_DIR, "historico.csv")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PRINTS_DIR, exist_ok=True)


# ==============================
# 💰 REGEX E UTILITÁRIOS
# ==============================
MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}")

def _extract_money(text: str) -> str:
    if not text:
        return "N/A"
    txt = re.sub(r"\s+", " ", str(text))
    match = MONEY_RE.search(txt)
    return match.group(0) if match else txt.strip()

def _money_to_float(value: str) -> float:
    try:
        normalized = re.sub(r"[^0-9,]", "", value).replace(".", "").replace(",", ".")
        return float(normalized)
    except Exception:
        return 0.0

def _domain_label(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().replace("www.", "")
        if "magazineluiza" in host or "magalu" in host:
            return "Magazine Luiza"
        if "amazon" in host:
            return "Amazon"
        if "casasbahia" in host:
            return "Casas Bahia"
        return host or "N/A"
    except Exception:
        return "N/A"


# ==============================
# 🏪 NOVA FUNÇÃO — NOME DO VENDEDOR
# ==============================
def _seller_name(driver: webdriver.Chrome, deadline: float) -> str:
    """
    Retorna o nome do vendedor (Ex: 'Vendido e entregue por Magazine Luiza')
    removendo o prefixo e limpando o texto.
    """
    entregue_por = "N/A"

    selectors = [
        (By.CSS_SELECTOR, "[data-testid='seller-info-name']"),
        (By.CSS_SELECTOR, "[data-testid='seller-name']"),
        (By.XPATH, "//*[contains(text(),'Vendido') and contains(text(),'por')]"),
    ]

    for by, sel in selectors:
        if time.monotonic() >= deadline:
            break
        try:
            el = WebDriverWait(driver, max(2, deadline - time.monotonic()), poll_frequency=0.1).until(
                EC.presence_of_element_located((by, sel))
            )
            txt = el.text
            for key in ["Vendido e entregue por", "Vendido por", "Loja:", "Entregue por"]:
                txt = txt.replace(key, "")
            entregue_por = txt.strip()
            break
        except Exception:
            continue

    return entregue_por


def _simple_model(name: str) -> str:
    if not name:
        return name
    normalized = re.sub(r"\s+", " ", name)
    match = re.search(r"(.{3,}?\b\d{2,4}\s*GB\b)", normalized, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return normalized.split(',')[0].split(' - ')[0].strip()

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# ==============================
# 🌐 DRIVER
# ==============================
def _new_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# ==============================
# 📸 CAPTURA DE TELA
# ==============================
def _capture_screenshot(driver: webdriver.Chrome, pasta: str, nome: str):
    timestamp = datetime.now().strftime("%H-%M-%S")
    filename = f"{_simple_model(nome)}_{timestamp}.png"
    path = os.path.join(pasta, filename)
    if pyautogui is None:
        return None
    try:
        time.sleep(1)
        pyautogui.screenshot(path)
    except Exception:
        return None
    return path


# ==============================
# 💳 ABRIR MODAL MAGALU + CARTÃO
# ==============================
def _open_magalu_modal(driver: webdriver.Chrome, deadline: float) -> bool:
    def _wait_left():
        return max(1.0, deadline - time.monotonic())

    def _robust_click(element):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            time.sleep(0.3)
            ActionChains(driver).move_to_element(element).pause(0.1).click(element).perform()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False

    open_selectors = [
        (By.CSS_SELECTOR, "div[data-testid='rave-payment-card-link'][role='button']"),
        (By.XPATH, "//p[contains(., 'Ver opções de pagamento')]/ancestor::*[@role='button'][1]"),
    ]

    modal_opened = False
    for by, sel in open_selectors:
        try:
            el = WebDriverWait(driver, _wait_left(), poll_frequency=0.15).until(
                EC.presence_of_element_located((by, sel))
            )
            if _robust_click(el):
                WebDriverWait(driver, 8).until(
                    EC.any_of(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "[role='dialog']")),
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-testid='payment-modal']"))
                    )
                )
                modal_opened = True
                break
        except Exception:
            continue

    if not modal_opened:
        return False

    credit_selectors = [
        (By.CSS_SELECTOR, "span[data-testid='tab-header-item-Cartão de crédito']"),
        (By.XPATH, "//span[contains(., 'Cartão de crédito')]"),
    ]

    for by, sel in credit_selectors:
        try:
            el = WebDriverWait(driver, 8).until(EC.presence_of_element_located((by, sel)))
            tab = el.find_element(By.XPATH, "ancestor::div[@role='tab'][1]")
            if _robust_click(tab):
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid*='payment-table']"))
                )
                time.sleep(2)
                return True
        except Exception:
            continue

    return True


# ==============================
# 🛒 COLETA DE PREÇOS MAGALU
# ==============================
def _scrape_magalu(driver: webdriver.Chrome, deadline: float):
    """
    Abre o modal de pagamento da Magalu, clica em 'Cartão de crédito' e coleta:
    - Valor PIX (fora do modal)
    - Valor 1x no Cartão de crédito (PARCELADO)
    """
    pix = parcelado = "N/A"

    # 1️⃣ Captura o valor PIX da página principal
    try:
        el_pix = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='price-value']"))
        )
        pix = _extract_money(el_pix.text)
    except Exception:
        pass

    # 2️⃣ Abre o modal de opções de pagamento
    try:
        open_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div[data-testid='rave-payment-card-link'][role='button']"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", open_btn)
        time.sleep(0.3)
        open_btn.click()
        print("🪟 Modal de pagamento aberto.")
    except Exception:
        print("[⚠️] Não foi possível abrir o modal de pagamento.")
        return pix, parcelado

    # 3️⃣ Clica na aba “Cartão de crédito”
    try:
        tab_credito = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span[data-testid='tab-header-item-Cartão de crédito']"))
        )
        tab_div = tab_credito.find_element(By.XPATH, "ancestor::div[@role='tab'][1]")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tab_div)
        time.sleep(0.3)
        ActionChains(driver).move_to_element(tab_div).pause(0.1).click(tab_div).perform()
        print("💳 Aba 'Cartão de crédito' selecionada.")
    except Exception:
        print("[⚠️] Não foi possível clicar na aba 'Cartão de crédito'.")
        return pix, parcelado

    # 4️⃣ Espera a tabela de parcelamento aparecer
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "tr[data-testid*='payment-table-Cartão de crédito-item']"))
        )
        rows = driver.find_elements(By.CSS_SELECTOR, "tr[data-testid*='payment-table-Cartão de crédito-item']")

        # 5️⃣ Busca o valor da linha “1x”
        for row in rows:
            text = row.text
            if "1x" in text:
                parcelado = _extract_money(text)
                print(f"💰 Valor 1x Cartão de Crédito: {parcelado}")
                break

    except Exception:
        print("[⚠️] Não foi possível localizar o valor do parcelamento.")

    return pix, parcelado

# ==============================
# 🚀 FUNÇÃO PRINCIPAL (COM FILTROS)
# ==============================
def coletar_precos(stores=None, include=None, exclude=None):
    print("🚀 Iniciando coleta...")

    # Mapeamento de aliases de lojas
    store_aliases = {
        "magalu": "magazine luiza",
        "magazineluiza": "magazine luiza",
        "magazine luiza": "magazine luiza",
        "amazon": "amazon",
        "amazon.com.br": "amazon",
        "casasbahia": "casas bahia",
        "casas bahia": "casas bahia",
    }

    # Normaliza filtros
    stores_norm = set(store_aliases.get(_norm(s), _norm(s)) for s in (stores or []))
    include_norm = set(_norm(_simple_model(x)) for x in (include or []) if str(x).strip())
    exclude_norm = set(_norm(_simple_model(x)) for x in (exclude or []) if str(x).strip())

    # Lê CSV de links
    if not os.path.exists(LINKS_PATH):
        raise FileNotFoundError("Arquivo 'links.csv' não encontrado!")

    df_links = pd.read_csv(LINKS_PATH, sep=";", engine="python")
    if df_links.empty:
        raise ValueError("Nenhum link encontrado em links.csv")

    # Cria pasta de prints
    pasta_nome = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pasta_path = os.path.join(PRINTS_DIR, pasta_nome)
    os.makedirs(pasta_path, exist_ok=True)

    driver = _new_driver()
    registros = []

    for _, row in df_links.iterrows():
        nome = str(row.get("NOME COMERCIAL", "")).strip()
        link = str(row.get("LINK", "")).strip()
        if not link:
            continue

        site_label = _domain_label(link)
        site_key = _norm(site_label)
        modelo = _simple_model(nome)
        modelo_key = _norm(modelo)

        # 🧠 Filtros de execução
        if stores_norm and (site_key not in stores_norm):
            continue
        if include_norm and (modelo_key not in include_norm):
            continue
        if exclude_norm and (modelo_key in exclude_norm):
            continue

        print(f"\n➡️ Coletando: {nome} [{site_label}]")
        inicio = time.monotonic()
        deadline = inicio + 10.0

        entregue_por = "N/A"
        pix = parcelado = "N/A"
        status = "OK"

        try:
            # Abre o link
            try:
                driver.get(link)
            except InvalidSessionIdException:
                driver.quit()
                driver = _new_driver()
                driver.get(link)

            # Força versão desktop
            if "//m.magazineluiza.com.br" in driver.current_url:
                driver.get(driver.current_url.replace("//m.magazineluiza.com.br", "//www.magazineluiza.com.br"))

            # Captura o modelo exibido
            try:
                el_model = WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "h1[data-testid='heading-product-title'], h1[itemprop='name'], h1")
                    )
                )
                if el_model and el_model.text.strip():
                    modelo = el_model.text.strip()
            except Exception:
                pass

            # 🏷️ Captura o “entregue por”
            for by, sel in [
                (By.CSS_SELECTOR, "[data-testid='seller-info-name']"),
                (By.CSS_SELECTOR, "[data-testid='seller-name']"),
                (By.XPATH, "//*[contains(text(),'Vendido') and contains(text(),'por')]")
            ]:
                if time.monotonic() >= deadline:
                    break
                try:
                    el_seller = driver.find_element(by, sel)
                    txt = el_seller.text
                    for key in ["Vendido e entregue por", "Vendido por", "Loja:"]:
                        txt = txt.replace(key, "")
                    entregue_por = txt.strip()
                    print(f"🏪 Vendido por: {entregue_por}")
                    break
                except Exception:
                    continue

            # 📸 Captura print ANTES de abrir o modal
            try:
                # aguarda o preço principal aparecer para garantir que a dobra carregou
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='price-value'], p[data-testid='cash-payment-text']"))
                )
            except Exception:
             pass
            _capture_screenshot(driver, pasta_path, nome)

            # 💰 Coleta dos preços (aqui pode abrir o modal)
            if "magazineluiza" in link or "magalu" in link:
                pix, parcelado = _scrape_magalu(driver, time.monotonic() + 8)
            else:
                try:
                    el_pix = driver.find_element(By.CSS_SELECTOR, "p[data-testid='cash-payment-text']")
                    pix = _extract_money(el_pix.text)
                except Exception:
                    pass

        except Exception as err:
            status = f"Erro: {err}"
            print(status)

        # Armazena no registro
        registros.append({
            "DATA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "NOME": nome,
            "MODELO": modelo,
            "SITE": site_label,
            "ENTREGUE_POR": entregue_por,
            "PIX": pix,
            "PARCELADO": parcelado,
            "STATUS": status,
            "LINK": link,
        })

    # Fecha o driver
    try:
        driver.quit()
    except Exception:
        pass

    # Atualiza histórico (;)
    df_novo = pd.DataFrame(registros)
    if os.path.exists(HIST_PATH):
        df_antigo = pd.read_csv(HIST_PATH, sep=";", engine="python")
        df_final = pd.concat([df_antigo, df_novo], ignore_index=True)
    else:
        df_final = df_novo

    df_final.to_csv(HIST_PATH, sep=";", index=False, encoding="utf-8-sig")
    print("\n✅ Coleta finalizada com sucesso.")
    return df_final, pasta_nome
