"""Gera um banco de demonstração com 14 dias de histórico FICTÍCIO (loja, preços e prints sintéticos).

Serve para conhecer a interface sem depender de nenhuma loja real.

    python -m searching.demo            # cria backend/data/demo.db e backend/data/demo/prints
    SEARCHING_DB=... SEARCHING_PRINTS=... python server.py   # ver scripts/iniciar_demo.bat
"""
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .core.precos import formatar_brl
from .db import links
from .db.models import Alerta, Coleta, Execucao, HistoricoLink, Produto, RevisaoLink
from .db.session import BACKEND_DIR, criar_engine, iniciar_banco

LOJA = "Loja Demo"
DIAS = 14
DEST = "voce@example.com"

# (nome comercial, preço-base PIX em centavos)
PRODUTOS = [
    ("Samsung Galaxy S25 256GB", 379900),
    ("Samsung Galaxy S25 Ultra 256GB", 699900),
    ("Samsung Galaxy S25 FE 5G 128GB", 329900),
    ("Samsung Galaxy A17 5G 128GB", 119900),
    ("Samsung Galaxy A17 5G 256GB", 129900),
    ("Samsung Galaxy Z Flip7 FE 128GB", 369300),
    ("Samsung Galaxy Z Fold 7 1TB", 899900),
    ("Samsung Galaxy S24+ 256GB", 316700),
]


def _url(nome: str, codigo: str) -> str:
    slug = "-".join(nome.lower().replace("+", "plus").split())
    return f"https://loja-demo.example/{slug}/p/{codigo}/"


def _imagem_sintetica(destino: Path, produto: str, pix: int | None, cartao: int | None, falha: str | None) -> None:
    from PIL import Image, ImageDraw, ImageFont  # dependência só de desenvolvimento (requirements-dev.txt)

    img = Image.new("RGB", (960, 600), "#f4f6f8")
    d = ImageDraw.Draw(img)
    fonte = lambda n: ImageFont.load_default(size=n)
    d.rectangle([0, 0, 960, 70], fill="#0b6bcb")
    d.text((32, 18), "LOJA DEMO", fill="white", font=fonte(34))
    d.text((32, 110), produto, fill="#1f2933", font=fonte(36))
    if falha:
        d.rectangle([32, 190, 928, 330], fill="#fdecea", outline="#d93025", width=3)
        d.text((60, 225), falha, fill="#b3261e", font=fonte(40))
    else:
        d.text((32, 200), formatar_brl(pix), fill="#0a7d3b", font=fonte(84))
        d.text((32, 300), "no Pix", fill="#52606d", font=fonte(30))
        if cartao is not None:
            d.text((32, 360), f"ou {formatar_brl(cartao)} em 1x no cartao de credito", fill="#52606d", font=fonte(28))
    d.text((32, 540), "Imagem sintetica de demonstracao - nao e uma loja real", fill="#9aa5b1", font=fonte(22))
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, optimize=True)


def gerar_demo(db: Path, prints_dir: Path, hoje: datetime | None = None, semente: int = 7) -> dict:
    """Recria o banco de demonstração (apaga o arquivo anterior) e devolve contagens do que foi criado."""
    rnd = random.Random(semente)
    hoje = (hoje or datetime.now()).replace(hour=12, minute=0, second=0, microsecond=0)
    db, prints_dir = Path(db), Path(prints_dir)
    for alvo in (db, prints_dir):
        if alvo.is_file():
            alvo.unlink()
        elif alvo.is_dir():
            shutil.rmtree(alvo)

    engine = criar_engine(db)
    fabrica = iniciar_banco(engine)
    resumo = {"produtos": 0, "execucoes": 0, "coletas": 0, "prints": 0, "alertas": 0}
    with fabrica() as s:
        produtos: dict[str, Produto] = {}
        for i, (nome, _) in enumerate(PRODUTOS):
            produtos[nome] = links.criar(s, nome, _url(nome, f"d{i + 1:03d}"), LOJA)
        s.commit()
        resumo["produtos"] = len(produtos)

        preco_atual = {nome: base for nome, base in PRODUTOS}
        queda = {"Samsung Galaxy S25 Ultra 256GB": (4, 0.92), "Samsung Galaxy A17 5G 128GB": (2, 0.94)}  # (dias atrás, fator)
        bloqueio_em, suspeito_em, corrigido_em, quebrado_desde = 6, 3, 8, 1

        def registrar(exec_, produto, quando, status, pix, cartao, detalhe=None, mostrar_print=False, falha=None):
            nome = produto.nome_comercial
            caminho = None
            if mostrar_print:
                arq = f"{nome}_{quando:%H-%M-%S}.png"
                _imagem_sintetica(prints_dir / f"{quando:%Y-%m-%d}" / arq, nome, pix, cartao, falha)
                caminho = f"prints/{quando:%Y-%m-%d}/{arq}"
                resumo["prints"] += 1
            c = Coleta(
                execucao_id=exec_.id, produto_id=produto.id, coletado_em=quando, status=status, titulo_lido=f"Celular {nome}",
                vendedor="Loja Demo" if pix else None, preco_pix_centavos=pix, preco_cartao_1x_centavos=cartao,
                texto_bruto={"pix": formatar_brl(pix) if pix else None}, caminho_print=caminho, erro_detalhe=detalhe,
            )
            s.add(c)
            s.flush()
            resumo["coletas"] += 1
            return c

        coleta_do_alerta: dict[str, Coleta] = {}
        for dias_atras in range(DIAS - 1, -1, -1):
            inicio = hoje - timedelta(days=dias_atras)
            ex = Execucao(iniciada_em=inicio, finalizada_em=inicio + timedelta(minutes=7), origem="agendada", total=len(PRODUTOS))
            s.add(ex)
            s.flush()
            resumo["execucoes"] += 1
            finais = []
            for i, (nome, base) in enumerate(PRODUTOS):
                p = produtos[nome]
                quando = inicio + timedelta(seconds=45 * i)
                # variação diária pequena; quedas bruscas nos dias combinados
                novo = preco_atual[nome] * (1 + rnd.uniform(-0.006, 0.006))
                if nome in queda and dias_atras == queda[nome][0]:
                    novo = preco_atual[nome] * queda[nome][1]
                preco_atual[nome] = novo = round(novo / 10) * 10
                cartao = round(novo * 1.095 / 10) * 10
                tem_print = dias_atras <= 2

                if dias_atras == bloqueio_em and nome in ("Samsung Galaxy S25 256GB", "Samsung Galaxy S24+ 256GB"):
                    registrar(ex, p, quando, "BLOQUEIO", None, None, "página de verificação/captcha", tem_print, "Erro 403")
                    finais.append("BLOQUEIO")
                elif nome == "Samsung Galaxy A17 5G 256GB" and dias_atras <= quebrado_desde:
                    registrar(ex, p, quando, "LINK_QUEBRADO", None, None, "página não encontrada", True, "Pagina nao encontrada")
                    finais.append("LINK_QUEBRADO")
                elif nome == "Samsung Galaxy S24+ 256GB" and dias_atras == suspeito_em:
                    registrar(ex, p, quando, "SUSPEITO", round(novo * 0.1), None, "variação acima do limite em relação à última coleta válida", tem_print)
                    finais.append("SUSPEITO")
                elif nome == "Samsung Galaxy Z Flip7 FE 128GB" and dias_atras == corrigido_em:
                    antigo = p.url_atual
                    registrar(ex, p, quando, "LINK_QUEBRADO", None, None, "redirecionou para página que não é de produto")
                    nova = _url(nome, "d106b")
                    links.trocar_url(s, p, nova, "recuperação automática (LINK_QUEBRADO, busca)", "automatico", 0.97)
                    registrar(ex, p, quando + timedelta(seconds=20), "OK", novo, cartao, None, tem_print)
                    ex.links_corrigidos += 1
                    finais.append("OK")
                    assert antigo != nova
                else:
                    c = registrar(ex, p, quando, "OK", novo, cartao, None, tem_print)
                    finais.append("OK")
                    if nome in queda and dias_atras == queda[nome][0]:
                        coleta_do_alerta[nome] = c
            ex.ok = finais.count("OK")
            ex.falhas = len(finais) - ex.ok
            if dias_atras == 0:
                ex.em_revisao = 1

        # fila de revisão: o link do A17 256GB quebrou e a busca achou dois candidatos parecidos demais para decidir sozinha
        quebrado = produtos["Samsung Galaxy A17 5G 256GB"]
        s.add(RevisaoLink(
            produto_id=quebrado.id, motivo="LINK_QUEBRADO", criado_em=hoje - timedelta(days=quebrado_desde),
            candidatos=[
                {"url": _url("Samsung Galaxy A17 5G 256GB Azul", "d205a"), "titulo": "Celular Samsung Galaxy A17 5G com IA, 256GB, 8GB RAM, Azul", "nota": 0.9, "estrategia": "busca", "verificado": False},
                {"url": _url("Samsung Galaxy A17 5G 256GB Preto", "d205b"), "titulo": "Celular Samsung Galaxy A17 5G com IA, 256GB, 8GB RAM, Preto", "nota": 0.9, "estrategia": "busca", "verificado": False},
            ],
        ))

        # alertas: um enviado e um que falhou no envio (mostra o registro e o reenvio)
        for nome, enviado in (("Samsung Galaxy S25 Ultra 256GB", True), ("Samsung Galaxy A17 5G 128GB", False)):
            c = coleta_do_alerta[nome]
            anterior = round(c.preco_pix_centavos / queda[nome][1] / 10) * 10
            s.add(Alerta(
                produto_id=c.produto_id, coleta_id=c.id, preco_anterior_centavos=anterior, preco_atual_centavos=c.preco_pix_centavos,
                queda_pct=round((anterior - c.preco_pix_centavos) / anterior * 100, 2), enviado_em=c.coletado_em + timedelta(minutes=2),
                destinatario=DEST, base_preco="pix", motivos="queda", sucesso=enviado,
                erro=None if enviado else "SMTPAuthenticationError: senha de app inválida",
            ))
            resumo["alertas"] += 1
        s.commit()
    engine.dispose()  # no Windows o arquivo ficaria travado e não poderia ser recriado
    return resumo


if __name__ == "__main__":
    destino_db = BACKEND_DIR / "data" / "demo.db"
    destino_prints = BACKEND_DIR / "data" / "demo" / "prints"
    r = gerar_demo(destino_db, destino_prints)
    print(f"Demonstração criada: {r['produtos']} produtos, {r['execucoes']} execuções, {r['coletas']} coletas, {r['prints']} prints, {r['alertas']} alertas.")
    print(f"Banco: {destino_db}\nPrints: {destino_prints}")
    print("Para abrir a interface com esses dados, use scripts\\iniciar_demo.bat")
