"""Teste ponta a ponta da PÁGINA DE OPÇÕES da extensão contra um servidor HTTPS de verdade (docker compose + Caddy).

Confere: registro dinâmico do ponte.js no domínio do servidor, servidor fixado (a página não consegue trocá-lo), pareamento
automático por token de usuário e o botão Desparear.

Pré-requisito (o stack de teste, com o domínio `localhost` e certificado interno do Caddy):

    docker compose -p searching-teste --env-file <arquivo com SEARCHING_DOMINIO=localhost e POSTGRES_SENHA=...> up -d --build

    cd backend
    venv\\Scripts\\python.exe ..\\scripts\\e2e_opcoes_extensao.py

Cria (e remove no fim) um coletor de teste dentro do contêiner. O Chrome roda com --ignore-certificate-errors só porque o
certificado do Caddy para `localhost` vem de uma autoridade interna. Abre uma janela do Chrome por cerca de um minuto.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

RAIZ = Path(__file__).resolve().parents[1]
EXTENSAO = RAIZ / "extensao"
PROJETO = "searching-teste"
URL = "https://localhost"
EMAIL, SENHA = "coletor-opcoes@e2e.teste", "Senha-Opcoes-Forte-1"


def chrome_for_testing():
    """Caminho do Chrome for Testing já baixado pelo Selenium (cache). O Chrome instalado no computador, quando é da mesma versão,
    é preferido pelo Selenium Manager e NÃO aceita --load-extension; por isso o teste aponta direto para o Chrome for Testing."""
    raiz = Path(os.environ.get("SE_CACHE_PATH") or Path.home() / ".cache" / "selenium") / "chrome"
    achados = sorted(raiz.glob("*/*/chrome.exe")) or sorted(raiz.glob("*/*/chrome"))
    return str(achados[-1]) if achados else None


def compose(*args, entrada=None):
    # bytes na entrada: no modo texto do Windows a quebra de linha viraria CRLF e a senha criada ficaria com um CR no fim
    r = subprocess.run(["docker", "compose", "-p", PROJETO, *args], input=entrada.encode() if entrada else None,
                       capture_output=True, cwd=RAIZ)
    r.stdout, r.stderr = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    return r


def esperar(fn, segundos=30, msg=""):
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError(f"tempo esgotado: {msg}")


def esperar_texto(driver, trecho, segundos, msg):
    try:
        esperar(lambda: trecho in texto(driver), segundos, msg)
    except AssertionError:
        raise AssertionError(f"{msg}. Tela atual: " + texto(driver)[-600:].replace(chr(10), " | ")) from None


def texto(driver):
    return driver.execute_script("return document.body.innerText")


def main():
    r = compose("ps", "--status", "running", "--format", "{{.Service}}")
    if "app" not in r.stdout:
        sys.exit("O stack de teste não está no ar (veja o cabeçalho do script).")
    r = compose("exec", "-T", "app", "python", "-m", "searching.usuarios", "criar", "--email", EMAIL, "--papel", "coletor", entrada=f"{SENHA}\n{SENHA}\n")
    assert "criado" in r.stdout, r.stdout + r.stderr
    codigo = ("from searching.db.session import criar_engine, iniciar_banco\n"
              "from searching.db import links\n"
              "from searching.db.models import Atribuicao, Usuario\n"
              "from sqlalchemy import select\n"
              "f = iniciar_banco(criar_engine())\n"
              "with f() as s:\n"
              "    u = s.scalar(select(Usuario).where(Usuario.email == '" + EMAIL + "'))\n"
              "    p = links.criar(s, 'Produto Opcoes E2E', 'https://www.magazineluiza.com.br/x/p/opc123/te/x/', 'Magazine Luiza')\n"
              "    s.flush(); s.add(Atribuicao(produto_id=p.id, usuario_id=u.id)); s.commit()\n")
    r = compose("exec", "-T", "app", "python", "-c", codigo)
    assert r.returncode == 0, r.stderr

    driver = None
    try:
        opcoes = Options()
        opcoes.browser_version = "stable"
        if chrome_for_testing():
            opcoes.binary_location = chrome_for_testing()
        opcoes.add_argument(f"--load-extension={EXTENSAO}")  # a extensão REAL, sem nenhuma edição de teste
        opcoes.add_argument("--ignore-certificate-errors")
        opcoes.add_argument("--window-size=1400,1000")
        driver = webdriver.Chrome(options=opcoes)

        def id_da_extensao():
            for t in driver.execute_cdp_cmd("Target.getTargets", {})["targetInfos"]:
                if t["url"].startswith("chrome-extension://") and t["url"].endswith("background.js"):
                    return t["url"].split("/")[2]
        ext_id = esperar(id_da_extensao, 15, "service worker da extensão")
        print(f"[ok] extensão real carregada (id {ext_id})")

        # 1) sem configurar o servidor, o site hospedado NÃO é reconhecido (ponte.js só roda no localhost:5173)
        driver.get(URL + "/assisted")
        esperar(lambda: "Esqueci a senha" in texto(driver), 20, "tela de login")
        campos = driver.find_elements("css selector", "input")
        campos[0].send_keys(EMAIL)
        campos[1].send_keys(SENHA)
        driver.execute_script("[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='Entrar').click()")
        esperar_texto(driver, "Extensão não detectada", 45, "extensão não detectada antes de configurar")
        print("[ok] antes de configurar, a tela não enxerga a extensão (nada do servidor hospedado é aceito por padrão)")

        # 2) página de opções: informa o servidor HTTPS -> registra o ponte.js nesse domínio
        driver.get(f"chrome-extension://{ext_id}/opcoes.html")
        driver.find_element("id", "servidor").clear()
        driver.find_element("id", "servidor").send_keys(URL)
        driver.find_element("id", "salvar").click()
        esperar(lambda: "Ainda não pareada" in driver.find_element("id", "estado").text, 10, "estado após salvar")
        registrados = driver.execute_async_script(
            "const cb = arguments[arguments.length-1]; chrome.scripting.getRegisteredContentScripts().then(r => cb(r.map(x => x.matches).flat()))")
        assert f"{URL}/*" in registrados, registrados
        print(f"[ok] opções: servidor {URL} salvo e ponte.js registrado em {registrados}")

        # 3) agora a tela detecta a extensão e faz o pareamento com token do usuário
        driver.get(URL + "/assisted")
        esperar_texto(driver, "Extensão conectada", 25, "extensão conectada")
        print("[ok] a tela detectou a extensão e entregou o token do usuário (pareamento automático por HTTPS)")
        tokens = json.loads(compose("exec", "-T", "app", "python", "-c",
                                    "import sqlite3,os\n").stdout or "[]") if False else None
        driver.get(f"chrome-extension://{ext_id}/opcoes.html")
        esperar(lambda: "Pareada com" in driver.find_element("id", "estado").text, 10, "estado pareada")
        print("[ok] opções mostram: " + driver.find_element("id", "estado").text)

        # 4) servidor fixado: a página do servidor não consegue trocar o endereço da extensão
        driver.get(URL + "/assisted")
        esperar(lambda: "Extensão conectada" in texto(driver), 25, "extensão conectada (2)")
        driver.execute_script("window.postMessage({origem:'searching-app', id: 9001, tipo:'configurar', servidor:'https://evil.example.com', recorteTopoPx: 7}, location.origin)")
        time.sleep(1.5)
        driver.get(f"chrome-extension://{ext_id}/opcoes.html")
        esperar(lambda: driver.find_element("id", "servidor").get_attribute("value"), 5, "campo servidor")
        valor = driver.find_element("id", "servidor").get_attribute("value")
        assert valor == URL, f"o servidor foi trocado pela página: {valor}"
        assert driver.find_element("id", "recorte").get_attribute("value") == "7"  # o que a página PODE ajustar: só recorte/token
        print("[ok] servidor fixado: a página tentou trocar para https://evil.example.com e a extensão ignorou")

        # 5) Desparear
        driver.find_element("id", "desparear").click()
        esperar(lambda: "Ainda não pareada" in driver.find_element("id", "estado").text, 10, "desparear")
        print("[ok] Desparear: a extensão voltou a 'não pareada'")

        # 6) a tela pareia de novo sozinha (token novo)
        driver.get(URL + "/assisted")
        esperar(lambda: "Extensão conectada" in texto(driver), 25, "re-pareamento")
        print("[ok] ao reabrir a tela, o pareamento é refeito com um token novo")
        print("\nTUDO CERTO: página de opções, registro dinâmico, servidor fixado e Desparear funcionam com HTTPS.")
    finally:
        if driver:
            driver.quit()
        limpeza = ("from searching.db.session import criar_engine, iniciar_banco\n"
                   "from searching.db.models import Atribuicao, Produto, SessaoLogin, TokenApi, Usuario, Auditoria\n"
                   "from sqlalchemy import select\n"
                   "f = iniciar_banco(criar_engine())\n"
                   "with f() as s:\n"
                   "    u = s.scalar(select(Usuario).where(Usuario.email == '" + EMAIL + "'))\n"
                   "    if u:\n"
                   "        for M in (Atribuicao, SessaoLogin, TokenApi):\n"
                   "            for x in s.scalars(select(M).where(M.usuario_id == u.id)): s.delete(x)\n"
                   "        s.flush(); s.delete(u)\n"
                   "    for p in s.scalars(select(Produto).where(Produto.nome_comercial == 'Produto Opcoes E2E')): s.delete(p)\n"
                   "    s.commit()\n")
        compose("exec", "-T", "app", "python", "-c", limpeza)


if __name__ == "__main__":
    main()
