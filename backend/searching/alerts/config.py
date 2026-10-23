"""Configuração global dos alertas (tabela configuracoes) e regra efetiva de cada produto."""
from sqlalchemy.orm import Session

from ..db.models import Configuracao, Produto
from ..db.session import CONFIG_PADRAO
from .regras import BASES_COMPARACAO, BASES_PRECO, Regra

CHAVES_ALERTA = (
    "alertas_ativos",
    "alerta_pct_queda",
    "alerta_degrau_pct",
    "alerta_base_preco",
    "alerta_base_comparacao",
    "alerta_dias_janela",
    "resumo_diario_email",
)


def validar(chave: str, valor) -> str:
    """Normaliza e valida um valor de configuração; lança ValueError com mensagem para o usuário."""
    texto = str(valor).strip().replace(",", ".")
    if chave in ("alertas_ativos", "resumo_diario_email"):
        if texto.lower() in ("1", "true", "sim"):
            return "1"
        if texto.lower() in ("0", "false", "nao", "não"):
            return "0"
        raise ValueError("Valor deve ser ligado ou desligado")
    if chave in ("alerta_pct_queda", "alerta_degrau_pct"):
        numero = float(texto)  # ValueError se não for número
        if not 0 <= numero <= 100 or (chave == "alerta_pct_queda" and numero == 0):
            raise ValueError("O percentual deve estar entre 0 e 100 (a queda mínima não pode ser 0)")
        return f"{numero:g}"
    if chave == "alerta_dias_janela":
        dias = int(float(texto))
        if not 1 <= dias <= 365:
            raise ValueError("A janela deve ter entre 1 e 365 dias")
        return str(dias)
    if chave == "alerta_base_preco":
        if texto not in BASES_PRECO:
            raise ValueError(f"Base de preço deve ser uma de: {', '.join(BASES_PRECO)}")
        return texto
    if chave == "alerta_base_comparacao":
        if texto not in BASES_COMPARACAO:
            raise ValueError(f"Base de comparação deve ser uma de: {', '.join(BASES_COMPARACAO)}")
        return texto
    raise ValueError(f"Configuração desconhecida: {chave}")


def ler_config(s: Session) -> dict[str, str]:
    valores = {k: CONFIG_PADRAO[k] for k in CHAVES_ALERTA}
    for c in s.query(Configuracao).filter(Configuracao.chave.in_(CHAVES_ALERTA)):
        valores[c.chave] = c.valor
    return valores


def salvar_config(s: Session, novos: dict) -> dict[str, str]:
    """Valida tudo antes de gravar: ou salva todas as chaves recebidas ou nenhuma."""
    limpos = {}
    for chave, valor in novos.items():
        if chave not in CHAVES_ALERTA:
            raise ValueError(f"Configuração desconhecida: {chave}")
        try:
            limpos[chave] = validar(chave, valor)
        except ValueError as exc:
            raise ValueError(f"{chave}: {exc}") from None
    for chave, valor in limpos.items():
        s.merge(Configuracao(chave=chave, valor=valor))
    s.flush()
    return ler_config(s)


def regra_do_produto(produto: Produto, cfg: dict[str, str]) -> Regra:
    """Regra do produto; o que ele não definir cai no padrão global (RF-22)."""
    return Regra(
        pct_queda=produto.alerta_pct if produto.alerta_pct is not None else float(cfg["alerta_pct_queda"]),
        base_comparacao=produto.alerta_base or cfg["alerta_base_comparacao"],
        janela_dias=int(cfg["alerta_dias_janela"]),
        degrau_pct=float(cfg["alerta_degrau_pct"]),
        preco_alvo_centavos=produto.alerta_preco_alvo_centavos,
    )
