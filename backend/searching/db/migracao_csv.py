"""Importa links.csv e data/historico.csv para o SQLite. Pode ser executado várias vezes.

Uso (a partir de backend/):  python -m searching.db.migracao_csv
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.atributos import extrair_atributos
from ..core.lojas import loja_do_link
from ..core.precos import parse_preco_centavos
from ..core.status import StatusColeta
from .models import Coleta, Execucao, HistoricoLink, Produto
from .session import BACKEND_DIR, criar_engine, iniciar_banco

# Linhas do histórico com intervalo menor que isso entre si pertencem à mesma execução.
JANELA_EXECUCAO = timedelta(minutes=5)


def _ler_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.exists() or caminho.stat().st_size == 0:
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return [
            {(k or "").strip().upper(): (v or "").strip() for k, v in linha.items()}
            for linha in csv.DictReader(f, delimiter=";")
        ]


def _vazio(valor: str) -> bool:
    return valor.strip().upper() in ("", "N/A", "NAN", "NONE")


def _criar_produto(s: Session, nome: str, loja: str, url: str, ativo: bool) -> Produto:
    attrs = extrair_atributos(nome)
    produto = Produto(
        nome_comercial=nome,
        loja=loja,
        url_atual=url,
        ativo=ativo,
        marca=attrs.marca,
        modelo=attrs.modelo,
        armazenamento=attrs.armazenamento,
        extras=attrs.extras_texto,
    )
    s.add(produto)
    s.flush()
    return produto


def migrar_links(s: Session, linhas: list[dict[str, str]]) -> dict[str, int]:
    resumo = {"criados": 0, "existentes": 0, "duplicados_no_csv": 0}
    vistos: set[tuple[str, str]] = set()
    for linha in linhas:
        nome = linha.get("NOME COMERCIAL") or linha.get("NOME", "")
        url = linha.get("LINK", "")
        loja = linha.get("LOJA", "")
        if not nome or not url:
            continue
        chave = (nome, loja)
        if chave in vistos:
            resumo["duplicados_no_csv"] += 1
            continue
        vistos.add(chave)
        existente = s.scalar(select(Produto).where(Produto.nome_comercial == nome, Produto.loja == loja))
        if existente:
            resumo["existentes"] += 1
            continue
        _criar_produto(s, nome, loja, url, ativo=True)
        resumo["criados"] += 1
    return resumo


def sincronizar_links(s: Session, linhas: list[dict[str, str]]) -> dict[str, int]:
    """Faz o links.csv (editado pela tela Links) valer no banco: cria, atualiza URL e ativa/desativa.

    Provisório até o CRUD de links passar a gravar direto no banco (RF-02).
    """
    resumo = {"criados": 0, "url_alterada": 0, "desativados": 0}
    presentes: set[int] = set()
    for linha in linhas:
        nome = linha.get("NOME COMERCIAL") or linha.get("NOME", "")
        url = linha.get("LINK", "")
        loja = linha.get("LOJA", "") or loja_do_link(url)
        if not nome or not url:
            continue
        produto = s.scalar(select(Produto).where(Produto.nome_comercial == nome, Produto.loja == loja))
        if produto is None:
            produto = _criar_produto(s, nome, loja, url, ativo=True)
            resumo["criados"] += 1
        else:
            if produto.url_atual != url:
                s.add(HistoricoLink(produto_id=produto.id, url_antiga=produto.url_atual, url_nova=url,
                                    motivo="edição manual (links.csv)", origem="manual"))
                produto.url_atual = url
                resumo["url_alterada"] += 1
            produto.ativo = True
        presentes.add(produto.id)

    for produto in s.scalars(select(Produto).where(Produto.ativo.is_(True))):
        if produto.id not in presentes:
            produto.ativo = False
            resumo["desativados"] += 1
    return resumo


def sincronizar_links_csv(fabrica, links_csv: Path | None = None) -> dict[str, int]:
    linhas = _ler_csv(links_csv or BACKEND_DIR / "links.csv")
    if not linhas:
        return {"criados": 0, "url_alterada": 0, "desativados": 0}
    with fabrica() as s:
        resumo = sincronizar_links(s, linhas)
        s.commit()
    return resumo


def _status_legado(status_csv: str, pix: int | None) -> tuple[str, str | None]:
    """Nunca devolve OK sem preço válido (RF-08)."""
    bruto = status_csv.strip().upper()
    if bruto == "OK":
        if pix is None:
            return StatusColeta.PRECO_NAO_ENCONTRADO.value, "Histórico legado: marcado OK, mas sem preço"
        return StatusColeta.OK.value, None
    if bruto in StatusColeta.__members__:
        return bruto, None
    return StatusColeta.ERRO_INESPERADO.value, f"Histórico legado: status '{status_csv}'"


def migrar_historico(s: Session, linhas: list[dict[str, str]]) -> dict[str, int]:
    resumo = {"coletas": 0, "ja_importadas": 0, "execucoes": 0, "produtos_criados": 0}

    parseadas = []
    for linha in linhas:
        try:
            quando = datetime.strptime(linha.get("DATA", ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        parseadas.append((quando, linha))
    parseadas.sort(key=lambda p: p[0])

    # Agrupa em execuções por proximidade de horário.
    grupos: list[list[tuple[datetime, dict[str, str]]]] = []
    for item in parseadas:
        if grupos and item[0] - grupos[-1][-1][0] <= JANELA_EXECUCAO:
            grupos[-1].append(item)
        else:
            grupos.append([item])

    for grupo in grupos:
        inicio, fim = grupo[0][0], grupo[-1][0]
        execucao = s.scalar(
            select(Execucao).where(Execucao.iniciada_em == inicio, Execucao.origem == "legado")
        )
        if execucao is None:
            execucao = Execucao(iniciada_em=inicio, finalizada_em=fim, origem="legado")
            s.add(execucao)
            s.flush()
            resumo["execucoes"] += 1

        novas = []
        for quando, linha in grupo:
            nome, loja = linha.get("NOME", ""), linha.get("SITE", "")
            produto = s.scalar(select(Produto).where(Produto.nome_comercial == nome, Produto.loja == loja))
            if produto is None:
                # Produto que está no histórico mas não no links.csv: preserva o histórico, inativo.
                produto = _criar_produto(s, nome, loja, linha.get("LINK", ""), ativo=False)
                resumo["produtos_criados"] += 1

            if s.scalar(select(Coleta.id).where(Coleta.produto_id == produto.id, Coleta.coletado_em == quando)):
                resumo["ja_importadas"] += 1
                continue

            pix_txt = linha.get("PIX", "")
            cartao_txt = linha.get("CREDITO") or linha.get("PARCELADO", "")
            pix, cartao = parse_preco_centavos(pix_txt), parse_preco_centavos(cartao_txt)
            status, detalhe = _status_legado(linha.get("STATUS", ""), pix)
            vendedor = linha.get("ENTREGUE_POR", "")

            novas.append(
                Coleta(
                    execucao_id=execucao.id,
                    produto_id=produto.id,
                    coletado_em=quando,
                    status=status,
                    titulo_lido=linha.get("MODELO") or None,
                    vendedor=None if _vazio(vendedor) else vendedor,
                    preco_pix_centavos=pix,
                    preco_cartao_1x_centavos=cartao,
                    texto_bruto={"pix": pix_txt, "cartao_1x": cartao_txt},
                    erro_detalhe=detalhe,
                )
            )
            resumo["coletas"] += 1
        s.add_all(novas)
        s.flush()

        total = s.query(Coleta).filter(Coleta.execucao_id == execucao.id).count()
        ok = s.query(Coleta).filter(Coleta.execucao_id == execucao.id, Coleta.status == "OK").count()
        execucao.total, execucao.ok, execucao.falhas = total, ok, total - ok

    return resumo


def migrar(links_csv: Path | None = None, historico_csv: Path | None = None, db: str | Path | None = None) -> dict:
    links_csv = links_csv or BACKEND_DIR / "links.csv"
    historico_csv = historico_csv or BACKEND_DIR / "data" / "historico.csv"
    fabrica = iniciar_banco(criar_engine(db))
    with fabrica() as s:
        resumo = {
            "links": migrar_links(s, _ler_csv(links_csv)),
            "historico": migrar_historico(s, _ler_csv(historico_csv)),
        }
        s.commit()
    return resumo


if __name__ == "__main__":
    import json

    print(json.dumps(migrar(), indent=2, ensure_ascii=False))
