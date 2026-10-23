"""Gera as imagens e o GIF do README a partir dos dados de demonstração (nada de dados reais).

    cd backend
    venv\\Scripts\\python.exe ..\\scripts\\gerar_docs.py

Sobe o servidor e o frontend com o banco de demonstração, fotografa as telas com o Chrome em modo headless
e grava em docs/. Requer Chrome instalado e `npm install` já feito em frontend/.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

RAIZ = Path(__file__).resolve().parents[1]
BACKEND, FRONTEND, DOCS = RAIZ / "backend", RAIZ / "frontend", RAIZ / "docs"
sys.path.insert(0, str(BACKEND))

from searching.demo import gerar_demo  # noqa: E402

DB = BACKEND / "data" / "demo.db"
PRINTS = BACKEND / "data" / "demo" / "prints"

# (arquivo, rota, altura da janela, ação opcional em JS antes da foto)
TELAS = [
    ("home", "/", 1500, None),
    ("relatorios", "/reports", 900, None),
    ("curvas", "/curves", 900, None),
    ("prints", "/prints", 1100, "const b=[...document.querySelectorAll('.folders button')][0]; b && b.click();"),
    ("revisao", "/review", 1000, None),
    ("alertas", "/alerts", 1700, None),
]
SALVAR_PNG = {"home", "curvas", "revisao"}  # o README mantém só 3 imagens estáticas; o GIF mostra todas


def esperar(url: str, tentativas: int = 60) -> None:
    for _ in range(tentativas):
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{url} não respondeu")


def encerrar(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    gerar_demo(DB, PRINTS)

    env = {
        **os.environ,
        "SEARCHING_DB": str(DB),
        "SEARCHING_PRINTS": str(PRINTS),
        # endereços de exemplo: a tela Alertas não pode mostrar o e-mail real de ninguém
        "SMTP_HOST": "smtp.example.com", "SMTP_USER": "alertas@example.com", "SMTP_PASSWORD": "demo",
        "ALERTA_DESTINATARIOS": "voce@example.com",
    }
    servidor = subprocess.Popen([sys.executable, "server.py"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    vite = subprocess.Popen(["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--strictPort"], cwd=FRONTEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    driver = None
    try:
        esperar("http://127.0.0.1:5000/api/health")
        esperar("http://127.0.0.1:5173/")

        opcoes = Options()
        opcoes.add_argument("--headless=new")
        opcoes.add_argument("--hide-scrollbars")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opcoes)

        quadros = []
        for nome, rota, altura, js in TELAS:
            driver.set_window_size(1280, altura)
            driver.get(f"http://localhost:5173{rota}")
            time.sleep(3)
            if js:
                driver.execute_script(js)
                time.sleep(2)
            destino = DOCS / f"{nome}.png"
            driver.save_screenshot(str(destino))
            quadros.append(Image.open(destino).convert("RGB"))
            print(f"capturada: {nome} ({quadros[-1].size[0]}x{quadros[-1].size[1]})")

        # GIF: largura 880, janela recortada em 880x560 do topo de cada tela, paleta reduzida para ficar leve
        reduzidos = []
        for q in quadros:
            q = q.resize((880, round(q.size[1] * 880 / q.size[0])), Image.LANCZOS).crop((0, 0, 880, 560))
            reduzidos.append(q.quantize(colors=96, method=Image.Quantize.MEDIANCUT))
        reduzidos[0].save(DOCS / "demo.gif", save_all=True, append_images=reduzidos[1:], duration=2200, loop=0, optimize=True)

        for nome, *_ in TELAS:
            if nome not in SALVAR_PNG:
                (DOCS / f"{nome}.png").unlink(missing_ok=True)
        print("docs/ atualizada:", ", ".join(sorted(p.name for p in DOCS.iterdir())))
    finally:
        if driver:
            driver.quit()
        encerrar(servidor)
        encerrar(vite)


if __name__ == "__main__":
    main()
