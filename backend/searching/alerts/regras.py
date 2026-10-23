"""Regras puras de alerta de queda de preço (sem banco, e-mail ou navegador): fáceis de testar."""
from dataclasses import dataclass
from datetime import datetime, timedelta

BASES_COMPARACAO = ("ultimo", "minimo_n_dias", "media_n_dias")
BASES_PRECO = ("pix", "cartao_1x")


@dataclass(frozen=True)
class Regra:
    pct_queda: float  # queda mínima, em %, para alertar
    base_comparacao: str  # ultimo | minimo_n_dias | media_n_dias
    janela_dias: int  # N das bases "n_dias"
    degrau_pct: float  # queda adicional exigida para um novo alerta do mesmo produto
    preco_alvo_centavos: int | None = None


@dataclass(frozen=True)
class UltimoAlerta:
    preco_centavos: int
    em: datetime


@dataclass(frozen=True)
class Decisao:
    preco_anterior_centavos: int
    preco_atual_centavos: int
    queda_pct: float
    motivos: tuple[str, ...]  # "queda" e/ou "preco_alvo"


def preco_referencia(base: str, anteriores: list[tuple[datetime, int]], agora: datetime, janela_dias: int) -> int | None:
    """Preço com o qual o atual é comparado. `anteriores` são coletas válidas anteriores à atual."""
    if not anteriores:
        return None
    if base == "ultimo":
        return max(anteriores, key=lambda p: p[0])[1]
    inicio = agora - timedelta(days=janela_dias)
    janela = [preco for quando, preco in anteriores if quando >= inicio]
    if not janela:
        return None
    if base == "minimo_n_dias":
        return min(janela)
    if base == "media_n_dias":
        return round(sum(janela) / len(janela))
    raise ValueError(f"base de comparação desconhecida: {base}")


def _subiu_desde(ultimo: UltimoAlerta, anteriores: list[tuple[datetime, int]]) -> bool:
    return any(quando > ultimo.em and preco > ultimo.preco_centavos for quando, preco in anteriores)


def avaliar(
    regra: Regra,
    atual_centavos: int,
    agora: datetime,
    anteriores: list[tuple[datetime, int]],
    ultimo_alerta: UltimoAlerta | None,
) -> Decisao | None:
    """Decide se esta coleta (válida) merece alerta. Devolve None quando não."""
    referencia = preco_referencia(regra.base_comparacao, anteriores, agora, regra.janela_dias)

    motivos = []
    queda = 0.0
    if referencia:
        queda = (referencia - atual_centavos) / referencia * 100
        if queda >= regra.pct_queda:
            motivos.append("queda")
    if regra.preco_alvo_centavos is not None and atual_centavos <= regra.preco_alvo_centavos:
        motivos.append("preco_alvo")
    if not motivos:
        return None

    # Anti-duplicidade (RF-24): mesmo preço não reenvia. Novo alerta só se cair mais um degrau
    # ou se o preço subiu e voltou a cair desde o último alerta.
    if ultimo_alerta is not None:
        desceu_degrau = atual_centavos <= ultimo_alerta.preco_centavos * (1 - regra.degrau_pct / 100)
        if not (desceu_degrau or _subiu_desde(ultimo_alerta, anteriores)):
            return None

    return Decisao(
        preco_anterior_centavos=referencia if referencia else atual_centavos,
        preco_atual_centavos=atual_centavos,
        queda_pct=round(max(queda, 0.0), 2),
        motivos=tuple(motivos),
    )
