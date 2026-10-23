from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Preços são guardados em centavos (inteiros) para permitir cálculo exato de variação.


class Base(DeclarativeBase):
    pass


class Produto(Base):
    __tablename__ = "produtos"
    __table_args__ = (UniqueConstraint("nome_comercial", "loja", name="uq_produto_nome_loja"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_comercial: Mapped[str] = mapped_column(String(200))
    loja: Mapped[str] = mapped_column(String(80))
    url_atual: Mapped[str] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Atributos usados na validação de título e na nota de confiança dos links.
    marca: Mapped[str] = mapped_column(String(60), default="")
    modelo: Mapped[str] = mapped_column(String(120), default="")
    armazenamento: Mapped[str] = mapped_column(String(20), default="")
    extras: Mapped[str] = mapped_column(String(120), default="")  # "5G,FE"

    # None = usa o padrão global (tabela configuracoes).
    alerta_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    alerta_base: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ultimo | minimo_n_dias | media_n_dias
    alerta_preco_alvo_centavos: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    coletas: Mapped[list["Coleta"]] = relationship(back_populates="produto")


class Execucao(Base):
    __tablename__ = "execucoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    iniciada_em: Mapped[datetime] = mapped_column(DateTime)
    finalizada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    origem: Mapped[str] = mapped_column(String(20))  # manual | agendada | assistida | legado
    total: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    falhas: Mapped[int] = mapped_column(Integer, default=0)
    links_corrigidos: Mapped[int] = mapped_column(Integer, default=0)
    em_revisao: Mapped[int] = mapped_column(Integer, default=0)

    coletas: Mapped[list["Coleta"]] = relationship(back_populates="execucao")


class Coleta(Base):
    __tablename__ = "coletas"
    __table_args__ = (
        UniqueConstraint("produto_id", "coletado_em", name="uq_coleta_produto_momento"),
        Index("ix_coletas_produto_data", "produto_id", "coletado_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    execucao_id: Mapped[int | None] = mapped_column(ForeignKey("execucoes.id"), nullable=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    coletado_em: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30))
    titulo_lido: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendedor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    moeda: Mapped[str] = mapped_column(String(3), default="BRL")
    preco_pix_centavos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preco_cartao_1x_centavos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    texto_bruto: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # texto lido da página, para auditoria
    caminho_print: Mapped[str | None] = mapped_column(Text, nullable=True)
    erro_detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)

    produto: Mapped[Produto] = relationship(back_populates="coletas")
    execucao: Mapped[Execucao | None] = relationship(back_populates="coletas")


class HistoricoLink(Base):
    __tablename__ = "historico_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    url_antiga: Mapped[str] = mapped_column(Text)
    url_nova: Mapped[str] = mapped_column(Text)
    motivo: Mapped[str] = mapped_column(String(200), default="")
    origem: Mapped[str] = mapped_column(String(20))  # manual | automatico
    nota_confianca: Mapped[float | None] = mapped_column(Float, nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RevisaoLink(Base):
    __tablename__ = "revisao_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    execucao_id: Mapped[int | None] = mapped_column(ForeignKey("execucoes.id"), nullable=True)
    motivo: Mapped[str] = mapped_column(String(40))
    candidatos: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{url, titulo, nota}]
    estado: Mapped[str] = mapped_column(String(20), default="pendente")  # pendente | aprovado | rejeitado
    criado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.now)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TentativaRecuperacao(Base):
    """Uma tentativa de recuperar o link de um produto (limite diário por produto, RF-21)."""

    __tablename__ = "tentativas_recuperacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    execucao_id: Mapped[int | None] = mapped_column(ForeignKey("execucoes.id"), nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    estrategia: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resultado: Mapped[str] = mapped_column(String(30))  # corrigido | revisao | sem_candidato


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    coleta_id: Mapped[int | None] = mapped_column(ForeignKey("coletas.id"), nullable=True)
    preco_anterior_centavos: Mapped[int] = mapped_column(Integer)
    preco_atual_centavos: Mapped[int] = mapped_column(Integer)
    queda_pct: Mapped[float] = mapped_column(Float)
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    destinatario: Mapped[str] = mapped_column(String(200), default="")
    base_preco: Mapped[str] = mapped_column(String(20), default="pix")  # pix | cartao_1x
    motivos: Mapped[str] = mapped_column(String(60), default="queda")  # "queda", "preco_alvo" ou os dois, separados por vírgula
    sucesso: Mapped[bool] = mapped_column(Boolean, default=False)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)


class Configuracao(Base):
    __tablename__ = "configuracoes"

    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)
