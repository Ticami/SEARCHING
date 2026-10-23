from enum import Enum


class StatusColeta(str, Enum):
    OK = "OK"
    LINK_QUEBRADO = "LINK_QUEBRADO"
    PRODUTO_DIVERGENTE = "PRODUTO_DIVERGENTE"
    PRECO_NAO_ENCONTRADO = "PRECO_NAO_ENCONTRADO"
    INDISPONIVEL = "INDISPONIVEL"
    TIMEOUT = "TIMEOUT"
    BLOQUEIO = "BLOQUEIO"
    ERRO_INESPERADO = "ERRO_INESPERADO"
    SUSPEITO = "SUSPEITO"


# Status que disparam a recuperação automática de link (PRD 6.4).
STATUS_RECUPERAVEIS = frozenset(
    {
        StatusColeta.LINK_QUEBRADO,
        StatusColeta.PRODUTO_DIVERGENTE,
        StatusColeta.PRECO_NAO_ENCONTRADO,
    }
)
