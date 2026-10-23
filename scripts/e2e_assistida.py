"""Teste ponta a ponta da coleta assistida, com Chrome de verdade e uma "Magalu" simulada localmente.

Sobe: loja simulada (porta 5999) + servidor Flask + frontend (Vite) + Chrome com a extensão carregada.
Faz o que o usuário faz: abre a tela, começa, aperta Próximo e confere o que a extensão leu e enviou.
Nada é enviado a nenhuma loja real e os seus dados reais não são tocados (banco, prints e token temporários).

    cd backend
    venv\\Scripts\\python.exe ..\\scripts\\e2e_assistida.py

Abre janelas do Chrome na sua tela por cerca de um minuto.

Observação: o Chrome oficial (a partir da versão 137) não carrega extensões por linha de comando. Por isso o teste usa o
"Chrome for Testing", o build de testes do Google, que o Selenium baixa sozinho na primeira vez (cerca de 460 MB, no cache
do Selenium; a variável SE_CACHE_PATH muda o local). O Chrome instalado no seu computador não é alterado.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

RAIZ = Path(__file__).resolve().parents[1]
BACKEND, FRONTEND, EXTENSAO = RAIZ / "backend", RAIZ / "frontend", RAIZ / "extensao"
PORTA_LOJA = 5999
PORTA_API, PORTA_APP = 5100, 5273  # portas próprias: não esbarram no programa que você já tenha aberto (5000 e 5173)
HOST_LOJA = f"www.magazineluiza.localhost:{PORTA_LOJA}"  # *.localhost resolve para 127.0.0.1 no Chrome

PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{titulo}</title>
<style>body{{font-family:Arial;margin:0}}header{{background:#0086ff;color:#fff;padding:18px 32px;font-size:26px}}main{{padding:32px}}
h1{{font-size:28px}}.preco{{font-size:44px;color:#0a7d3b;font-weight:bold}}[role=button]{{display:inline-block;margin-top:18px;padding:12px 20px;background:#eef;border-radius:8px;cursor:pointer}}
[role=dialog]{{position:fixed;top:120px;right:60px;width:420px;background:#fff;border:2px solid #0086ff;padding:20px;box-shadow:0 4px 30px #0005}}[role=tab]{{cursor:pointer;font-weight:bold}}</style></head>
<body><header>Magalu (simulada para teste)</header><main>
<h1 data-testid="heading-product-title">{titulo}</h1>
<p data-testid="seller-info-name">Vendido e entregue por Samsung</p>
<div class="preco"><span data-testid="price-value">{preco}</span> <small>no Pix</small></div>
<div data-testid="rave-payment-card-link" role="button" onclick="abrir()"><p>Ver opções de pagamento</p></div>
</main>
<script>
function abrir(){{
  const d=document.createElement('div'); d.setAttribute('role','dialog');
  d.innerHTML='<div role="tab" id="aba"><span data-testid="tab-header-item-Cartão de crédito">Cartão de crédito</span></div><div id="conteudo"></div>';
  document.body.appendChild(d);
  document.getElementById('aba').addEventListener('click',function(){{
    setTimeout(function(){{document.getElementById('conteudo').innerHTML='<table><tr data-testid="payment-table-Cartão de crédito-item-0"><td>1x</td><td>{cartao}</td></tr><tr data-testid="payment-table-Cartão de crédito-item-10"><td>11x</td><td>R$ 363,54</td></tr></table>'}},300);
  }});
}}
document.addEventListener('keydown',function(e){{if(e.key==='Escape'){{var d=document.querySelector('[role=dialog]'); if(d) d.remove();}}}});
</script></body></html>"""

BLOQUEIO = """<!doctype html><html><head><meta charset="utf-8"><title>Magazine Luiza | Não é possível acessar a página</title></head>
<body style="font-family:Arial;text-align:center;padding-top:120px"><h1>Não é possível acessar a página</h1><p>(Erro 403)</p><p>Por favor, tente novamente em 1 minuto.</p></body></html>"""

PAGINAS = {
    "/celular-samsung-galaxy-s25/p/abc123/te/gs25/": ("Celular Samsung Galaxy S25 5G, 256GB, 12GB RAM", "R$ 3.799,00", "R$ 3.998,95"),
    "/celular-samsung-galaxy-a17/p/def456/te/ga14/": ("Celular Samsung Galaxy A17 5G com IA, 128GB, 4GB RAM", "R$ 1.199,00", "R$ 1.332,22"),
}
BLOQUEIA_UMA_VEZ = "/bloqueado/p/zzz999/"
PAGINAS[BLOQUEIA_UMA_VEZ] = ("Celular Samsung Galaxy S24+, 256GB, 12GB de RAM", "R$ 3.167,12", "R$ 3.599,00")
PRODUTOS = [
    ("Samsung Galaxy S25 256GB", "/celular-samsung-galaxy-s25/p/abc123/te/gs25/"),
    ("Samsung Galaxy A17 5G 128GB", "/celular-samsung-galaxy-a17/p/def456/te/ga14/"),
    ("Samsung Galaxy S24+ 256GB", "/bloqueado/p/zzz999/"),
]
ACESSOS = []


class Loja(BaseHTTPRequestHandler):
    def do_GET(self):
        ACESSOS.append((time.time(), self.path))
        primeira_visita = sum(1 for _, c in ACESSOS if c == self.path) == 1
        if self.path in PAGINAS and not (self.path == BLOQUEIA_UMA_VEZ and primeira_visita):
            titulo, preco, cartao = PAGINAS[self.path]
            corpo, codigo = PAGINA.format(titulo=titulo, preco=preco, cartao=cartao).encode(), 200
        else:
            corpo, codigo = BLOQUEIO.encode(), 403
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def http(url, corpo=None, metodo=None):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode() if corpo is not None else None, method=metodo or ("POST" if corpo is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _porta_ocupada(porta):
    import socket

    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def esperar(url, tentativas=60):
    for _ in range(tentativas):
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{url} não respondeu")


def encerrar(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def esperar_texto(driver, trecho, segundos=40):
    fim = time.time() + segundos
    while time.time() < fim:
        texto = driver.execute_script("return document.body.innerText")
        if trecho.lower() in texto.lower():  # a tela usa maiúsculas em alguns títulos
            return texto
        time.sleep(0.4)
    raise AssertionError(f"Não apareceu na tela em {segundos}s: {trecho!r}\n--- tela ---\n{texto[-900:]}")


def clicar(driver, texto):
    ok = driver.execute_script(
        "const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim().startsWith(arguments[0])&&!x.disabled); if(b){b.click();return true} return false", texto)
    assert ok, f"botão não encontrado ou desabilitado: {texto!r}"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="searching_e2e_"))
    ext = tmp / "extensao"
    shutil.copytree(EXTENSAO, ext)
    # a cópia de teste também enxerga a loja simulada (a extensão de verdade só conhece as lojas reais)
    man = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    man["host_permissions"] += [f"http://*.magazineluiza.localhost:{PORTA_LOJA}/*", f"http://127.0.0.1:{PORTA_API}/*"]
    man["content_scripts"][0]["matches"] += [f"http://localhost:{PORTA_APP}/*", f"http://127.0.0.1:{PORTA_APP}/*"]
    (ext / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    bg = (ext / "background.js").read_text(encoding="utf-8")
    assert 'const HOSTS_PERMITIDOS = ["magazineluiza.com.br", "magazinevoce.com.br"]' in bg
    (ext / "background.js").write_text(bg.replace('"magazinevoce.com.br"]', '"magazinevoce.com.br", "magazineluiza.localhost"]'), encoding="utf-8")

    ocupadas = [p for p in (PORTA_LOJA, PORTA_API, PORTA_APP) if _porta_ocupada(p)]
    if ocupadas:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(f"Portas {ocupadas} ocupadas: feche o que estiver usando e rode de novo (nada foi tocado).")
    loja = ThreadingHTTPServer(("127.0.0.1", PORTA_LOJA), Loja)
    threading.Thread(target=loja.serve_forever, daemon=True).start()

    env = {**os.environ, "SEARCHING_PORT": str(PORTA_API), "SEARCHING_API": f"http://127.0.0.1:{PORTA_API}",
           "SEARCHING_ORIGENS": f"http://localhost:{PORTA_APP},http://127.0.0.1:{PORTA_APP}", "SEARCHING_DB": str(tmp / "e2e.db"), "SEARCHING_PRINTS": str(tmp / "prints"), "SEARCHING_TOKEN": str(tmp / "token"),
           # e-mail inexistente: o teste nunca envia mensagem de verdade
           "SMTP_HOST": "smtp.invalid", "SMTP_USER": "teste@example.com", "SMTP_PASSWORD": "x", "ALERTA_DESTINATARIOS": "teste@example.com"}
    servidor = subprocess.Popen([sys.executable, "server.py"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    vite = subprocess.Popen(["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(PORTA_APP), "--strictPort"], cwd=FRONTEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    driver = None
    try:
        esperar(f"http://127.0.0.1:{PORTA_API}/api/health")
        esperar(f"http://127.0.0.1:{PORTA_APP}/")
        for nome, caminho in PRODUTOS:
            http(f"http://127.0.0.1:{PORTA_API}/api/links", {"nome": nome, "link": f"http://{HOST_LOJA}{caminho}", "loja": "Magazine Luiza"})
        print(f"[ok] servidor, frontend e loja simulada no ar; {len(PRODUTOS)} produtos cadastrados")

        opcoes = Options()
        opcoes.browser_version = "stable"  # Chrome for Testing (o Chrome oficial não aceita --load-extension)
        opcoes.add_argument(f"--load-extension={ext}")
        opcoes.add_argument("--window-size=1500,1150")
        driver = webdriver.Chrome(options=opcoes)
        driver.get(f"http://localhost:{PORTA_APP}/assisted")
        # guarda os eventos que a extensão manda à tela (andamento e avisos), para diagnosticar e conferir
        driver.execute_script("window.__ev=[]; window.addEventListener('message', e => { if (e.data && e.data.origem==='searching-ext' && e.data.tipo==='evento') window.__ev.push(e.data); })")

        esperar_texto(driver, "Extensão conectada")
        print("[ok] a tela detectou a extensão e fez o pareamento (token entregue)")

        clicar(driver, "Começar coleta assistida")
        tela = esperar_texto(driver, "R$ 3.799,00", 60)
        assert "R$ 3.998,95" in tela, "cartão 1x não apareceu"
        assert "Samsung" in tela and "OK" in tela
        print("[ok] 1º produto: PIX R$ 3.799,00 e cartão 1x R$ 3.998,95 preenchidos sozinhos")
        saida = os.environ.get("E2E_SAIDA")  # opcional: pasta onde guardar uma foto da tela e um print, para conferir a olho
        if saida:
            Path(saida).mkdir(parents=True, exist_ok=True)
            time.sleep(1)
            driver.save_screenshot(str(Path(saida) / "tela_assistida.png"))
        print(f"     janelas do Chrome: {len(driver.window_handles)} (a extensão abriu a janela da Magalu)")

        # Próximo: um clique (aqui pela tecla de atalho, como o usuário faria)
        time.sleep(3.2)
        driver.find_element("tag name", "body").send_keys(Keys.SPACE)
        esperar_texto(driver, "R$ 1.199,00", 60)
        print("[ok] 2º produto aberto com a tecla de espaço: PIX R$ 1.199,00")

        time.sleep(3.2)
        clicar(driver, "Próximo")
        tela = esperar_texto(driver, "BLOQUEIO", 60)
        assert "Nada foi forçado" in tela
        print("[ok] 3º produto: a loja simulada bloqueou (403) e a tela mostrou BLOQUEIO, sem insistir")

        sessao = http(f"http://127.0.0.1:{PORTA_API}/api/assistida/sessao")
        status = [i["coleta"]["status"] for i in sessao["itens"]]
        assert status == ["OK", "OK", "BLOQUEIO"], status
        eventos = driver.execute_script("return window.__ev")
        avisos = [e.get("detalhe") for e in eventos if e.get("etapa") == "aviso"]
        print(f"     avisos da extensão: {avisos or 'nenhum'}")
        prints = list((tmp / "prints").rglob("*.png"))
        if saida and prints:
            shutil.copy(sorted(prints)[0], Path(saida) / "print_da_extensao.png")
        assert len(prints) == 3 and all(p.stat().st_size > 5000 for p in prints), prints
        print(f"[ok] servidor registrou {status} e guardou {len(prints)} prints reais (PNG de {min(p.stat().st_size for p in prints)//1024} KB ou mais)")

        # intervalo mínimo: nunca mais de uma página a cada 3 s
        pedidos = [t for t, c in ACESSOS if c != "/favicon.ico"]
        folgas = [round(b - a, 1) for a, b in zip(pedidos, pedidos[1:])]
        assert all(f >= 3.0 for f in folgas), folgas
        print(f"[ok] intervalo entre páginas da loja: {folgas} s (mínimo 3 s)")

        # aviso amarelo: fixo no topo, com a contagem, o motivo e um Refazer por produto
        esperar_texto(driver, "1 produto(s) com erro", 10)
        driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight)")
        time.sleep(0.4)
        topo = driver.execute_script("return document.querySelector('[role=alert]').getBoundingClientRect().top")
        assert -1 <= topo <= 2, f"o aviso não ficou fixo no topo ao rolar a página (top={topo})"
        driver.execute_script("window.scrollTo(0, 0)")
        driver.execute_script("document.querySelector('[data-testid=alternar-erros]').click()")
        lista = esperar_texto(driver, "S24+", 10)
        assert "BLOQUEIO" in lista
        if saida:
            driver.save_screenshot(str(Path(saida) / "tela_aviso_erros.png"))
        print("[ok] aviso amarelo: '1 produto(s) com erro', fixo no topo ao rolar, com o motivo (BLOQUEIO) e o botão Refazer")

        # Refazer pelo aviso: uma página por clique; quando dá certo o aviso some
        time.sleep(3.2)
        driver.execute_script("document.querySelector('[data-testid=refazer-erro]').click()")
        esperar_texto(driver, "R$ 3.167,12", 60)
        fim = time.time() + 15
        while time.time() < fim and driver.execute_script("return document.querySelector('[role=alert]') !== null"):
            time.sleep(0.3)
        assert driver.execute_script("return document.querySelector('[role=alert]') === null"), "o aviso deveria sumir quando não há mais erros"
        print("[ok] Refazer pelo aviso: PIX R$ 3.167,12 lido e o aviso sumiu")
        sessao = http(f"http://127.0.0.1:{PORTA_API}/api/assistida/sessao")
        assert [i["coleta"]["status"] for i in sessao["itens"]] == ["OK", "OK", "OK"]
        assert len(list((tmp / "prints").rglob("*.png"))) == 4  # a falha e a coleta refeita guardam um print cada
        pedidos = [t for t, c in ACESSOS if c != "/favicon.ico"]
        folgas = [round(b - a, 1) for a, b in zip(pedidos, pedidos[1:])]
        assert all(f >= 3.0 for f in folgas), folgas

        clicar(driver, "Encerrar")
        tela = esperar_texto(driver, "Execução encerrada", 20)
        assert "3 de 3 com sucesso" in tela, tela[-500:]
        hist = http(f"http://127.0.0.1:{PORTA_API}/api/historico")
        assert [h["PIX_CENTAVOS"] for h in hist] == [379900, 119900, None, 316712], hist
        print("[ok] execução encerrada: 3 de 3 com sucesso; a falha anterior continua no histórico")
        print("\nTUDO CERTO: o fluxo assistido funciona de ponta a ponta.")
    finally:
        if driver:
            driver.quit()
        encerrar(servidor)
        encerrar(vite)
        loja.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
