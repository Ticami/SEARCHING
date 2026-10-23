from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class Navegador:
    """Dono do ChromeDriver; recria a sessão se ela cair no meio da coleta."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None

    def _criar(self):
        opcoes = Options()
        if self.headless:
            opcoes.add_argument("--headless=new")
            opcoes.add_argument("--window-size=1366,900")
        else:
            opcoes.add_argument("--start-maximized")
        opcoes.add_argument("--disable-blink-features=AutomationControlled")
        opcoes.add_argument("--disable-infobars")
        opcoes.add_argument("--disable-extensions")
        opcoes.add_argument("--disable-dev-shm-usage")
        opcoes.page_load_strategy = "eager"
        opcoes.add_experimental_option("excludeSwitches", ["enable-automation"])
        opcoes.add_experimental_option("useAutomationExtension", False)
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opcoes)

    def obter(self):
        if self.driver is None:
            self.driver = self._criar()
        return self.driver

    def reiniciar(self):
        self.fechar()
        return self.obter()

    def fechar(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
