from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from ..modo import exigir_local


class Navegador:
    """Dono do ChromeDriver; recria a sessão se ela cair no meio da coleta.

    Não esconde que o Chrome é controlado por programa: se a loja bloquear, registramos BLOQUEIO e seguimos.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None

    def _criar(self):
        exigir_local("O navegador do coletor automático")  # servidor hospedado nunca abre lojas
        opcoes = Options()
        if self.headless:
            opcoes.add_argument("--headless=new")
            opcoes.add_argument("--window-size=1366,900")
        else:
            opcoes.add_argument("--start-maximized")
        opcoes.add_argument("--disable-extensions")
        opcoes.add_argument("--disable-dev-shm-usage")
        opcoes.page_load_strategy = "eager"
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
