"""Política de acesso de cada rota (deny by default).

Toda rota do Flask precisa aparecer em POLITICAS; uma rota sem política responde 403 e o teste
`test_toda_rota_tem_politica` falha. A matriz documentada em docs/DESENHO_MULTIUSUARIO.md é este arquivo.
"""
from dataclasses import dataclass

PUBLICA = "publica"      # sem login (login, saúde, arquivos do site)
LOGADO = "logado"        # qualquer usuário autenticado
LEITOR = "leitor"
COLETOR = "coletor"
ADMIN = "admin"
EXTENSAO = "extensao"    # só com o token da extensão (por usuário no modo hospedado; arquivo global no local)


@dataclass(frozen=True)
class Politica:
    acesso: str
    so_local: bool = False       # só existe no modo local (ex.: coleta automática, token global)
    dono: bool = False           # coletor só age em produto atribuído a ele (admin: qualquer um); conferido na rota
    escrita_leitura: bool = False  # POST que não altera nada (ex.: exportar Excel): leitor pode


def _p(acesso, **kw):
    return Politica(acesso, **kw)


POLITICAS: dict[str, Politica] = {
    # ----- públicas -----
    "api_health": _p(PUBLICA),
    "conta.modo": _p(PUBLICA),
    "conta.login": _p(PUBLICA),
    "conta.recuperar": _p(PUBLICA),
    "conta.redefinir": _p(PUBLICA),
    "arquivos_do_site": _p(PUBLICA),
    "arquivos_do_site_raiz": _p(PUBLICA),
    # ----- qualquer usuário logado (conta própria) -----
    "conta.eu": _p(LOGADO),
    "conta.logout": _p(LOGADO),
    "conta.trocar_senha": _p(LOGADO),
    "conta.iniciar_2fa": _p(LOGADO),
    "conta.ativar_2fa": _p(LOGADO),
    "conta.desativar_2fa": _p(LOGADO),
    "conta.meus_tokens": _p(LOGADO),
    "conta.criar_meu_token": _p(LOGADO),
    "conta.revogar_meu_token": _p(LOGADO),
    "conta.minhas_assinaturas": _p(LOGADO),
    "conta.minhas_sessoes": _p(LOGADO),
    "conta.encerrar_minha_sessao": _p(LOGADO),
    "conta.encerrar_outras_sessoes": _p(LOGADO),
    # ----- leitor: só ver -----
    "listar_links": _p(LEITOR),
    "historico_de_links": _p(LEITOR),
    "listar_revisoes": _p(LEITOR),
    "get_print": _p(LEITOR),
    "listar_historico": _p(LEITOR),
    "exportar_historico": _p(LEITOR, escrita_leitura=True),
    "galeria_de_prints": _p(LEITOR),
    "painel_de_saude": _p(LEITOR),
    "listar_alertas": _p(LEITOR),
    "listar_regras_alerta": _p(LEITOR),
    "assistida_em_coleta": _p(LEITOR),
    # ----- coletor (do que lhe foi atribuído) -----
    "editar_link": _p(COLETOR, dono=True),
    "salvar_regra_alerta": _p(COLETOR, dono=True),
    "conta.salvar_minhas_assinaturas": _p(COLETOR),
    "resolver_revisao": _p(COLETOR, dono=True),
    "assistida_sessao": _p(COLETOR),
    "assistida_iniciar": _p(COLETOR),
    "assistida_link_quebrado": _p(COLETOR),
    "assistida_pular": _p(COLETOR),
    "assistida_encerrar": _p(COLETOR),
    "conta.parear_extensao": _p(COLETOR),
    # ----- extensão (token) -----
    "assistida_captura": _p(EXTENSAO),
    "assistida_autorizar": _p(EXTENSAO),
    # ----- admin -----
    "adicionar_link": _p(ADMIN),
    "deletar_link": _p(ADMIN),
    "reverter_troca_de_link": _p(ADMIN),
    "salvar_config_alertas": _p(ADMIN),
    "salvar_destinatarios": _p(ADMIN),
    "conta.listar_assinaturas": _p(ADMIN),
    "conta.salvar_assinaturas_do_usuario": _p(ADMIN),
    "enviar_email_de_teste": _p(ADMIN),
    "coletar_manual": _p(ADMIN, so_local=True),
    "assistida_token": _p(COLETOR, so_local=True),
    "conta.listar_usuarios": _p(ADMIN),
    "conta.criar_usuario": _p(ADMIN),
    "conta.alterar_usuario": _p(ADMIN),
    "conta.redefinir_senha_usuario": _p(ADMIN),
    "conta.tokens_do_usuario": _p(ADMIN),
    "conta.revogar_token": _p(ADMIN),
    "conta.auditoria": _p(ADMIN),
    "conta.listar_sessoes": _p(ADMIN),
    "conta.encerrar_sessao": _p(ADMIN),
    "conta.retencao": _p(ADMIN),
    "conta.salvar_retencao": _p(ADMIN),
    "conta.aplicar_retencao": _p(ADMIN),
    "conta.listar_atribuicoes": _p(ADMIN),
    "conta.salvar_atribuicoes": _p(ADMIN),
}
