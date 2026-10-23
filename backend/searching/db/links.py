"""Operações sobre os links dos produtos. Toda troca de URL passa por aqui para ficar no histórico (RF-04)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.atributos import extrair_atributos
from ..core.lojas import loja_do_link
from .models import HistoricoLink, Produto, RevisaoLink


class LinkInvalido(ValueError):
    pass


def _aplicar_atributos(produto: Produto, nome: str) -> None:
    attrs = extrair_atributos(nome)
    produto.marca, produto.modelo = attrs.marca, attrs.modelo
    produto.armazenamento, produto.extras = attrs.armazenamento, attrs.extras_texto


def listar_ativos(s: Session) -> list[Produto]:
    return list(s.scalars(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.id)))


def criar(s: Session, nome: str, url: str, loja: str = "") -> Produto:
    nome, url = (nome or "").strip(), (url or "").strip()
    if not nome or not url:
        raise LinkInvalido("Campos obrigatórios: nome e link")
    loja = (loja or "").strip() or loja_do_link(url)
    existente = s.scalar(select(Produto).where(Produto.nome_comercial == nome, Produto.loja == loja))
    if existente and existente.ativo:
        raise LinkInvalido("Já existe um produto ativo com esse nome nessa loja")
    if existente:  # produto desativado antes: reaproveita o histórico
        existente.ativo = True
        trocar_url(s, existente, url, "produto reativado", "manual")
        return existente
    produto = Produto(nome_comercial=nome, loja=loja, url_atual=url, ativo=True)
    _aplicar_atributos(produto, nome)
    s.add(produto)
    s.flush()
    return produto


def atualizar(s: Session, produto: Produto, nome: str | None, url: str | None, loja: str | None) -> Produto:
    if nome and nome.strip() != produto.nome_comercial or (loja and loja.strip() != produto.loja):
        novo_nome = (nome or produto.nome_comercial).strip()
        nova_loja = (loja or produto.loja).strip()
        conflito = s.scalar(
            select(Produto).where(Produto.nome_comercial == novo_nome, Produto.loja == nova_loja, Produto.id != produto.id)
        )
        if conflito:
            raise LinkInvalido("Já existe outro produto com esse nome nessa loja")
        produto.nome_comercial, produto.loja = novo_nome, nova_loja
        _aplicar_atributos(produto, novo_nome)
    if url and url.strip() != produto.url_atual:
        trocar_url(s, produto, url.strip(), "edição manual", "manual")
    return produto


def desativar(s: Session, produto: Produto) -> None:
    produto.ativo = False


def trocar_url(s: Session, produto: Produto, url_nova: str, motivo: str, origem: str, nota: float | None = None) -> None:
    """Troca o link do produto e registra no histórico (origem: manual ou automatico)."""
    if url_nova == produto.url_atual:
        return
    s.add(
        HistoricoLink(
            produto_id=produto.id,
            url_antiga=produto.url_atual,
            url_nova=url_nova,
            motivo=motivo,
            origem=origem,
            nota_confianca=nota,
        )
    )
    produto.url_atual = url_nova


def reverter(s: Session, historico: HistoricoLink) -> Produto:
    """Volta o produto para o link anterior a uma troca (a reversão também entra no histórico)."""
    produto = s.get(Produto, historico.produto_id)
    if produto.url_atual != historico.url_nova:
        raise LinkInvalido("O link atual já não é o que essa troca definiu; reverta a troca mais recente primeiro")
    trocar_url(s, produto, historico.url_antiga, f"reversão da troca #{historico.id}", "manual")
    return produto


def resolver_revisao(s: Session, revisao: RevisaoLink, acao: str, url: str | None = None) -> RevisaoLink:
    if revisao.estado != "pendente":
        raise LinkInvalido("Esta revisão já foi resolvida")
    produto = s.get(Produto, revisao.produto_id)
    if acao == "aprovar":
        if not url or not url.strip():
            raise LinkInvalido("Informe o link a aprovar")
        trocar_url(s, produto, url.strip(), f"revisão ({revisao.motivo})", "manual")
        revisao.estado = "aprovado"
    elif acao == "desativar":
        produto.ativo = False
        revisao.estado = "rejeitado"
    else:
        raise LinkInvalido("Ação inválida")
    revisao.resolvido_em = datetime.now()
    return revisao
