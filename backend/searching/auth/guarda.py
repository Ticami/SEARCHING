"""Guarda central de autorização: roda antes de toda rota e aplica a política declarada em politicas.py."""
import hmac
from types import SimpleNamespace

from flask import current_app, g, jsonify, request

from .. import assistida, modo, seguranca
from . import politicas as pol
from . import limite, servico

COOKIE = "searching_sessao"
METODOS_SEGUROS = ("GET", "HEAD", "OPTIONS")
ROTAS_DA_TROCA_DE_SENHA = ("conta.trocar_senha", "conta.eu", "conta.logout")
ROTAS_DO_2FA = ROTAS_DA_TROCA_DE_SENHA + ("conta.iniciar_2fa", "conta.ativar_2fa")

# No modo local não há login: quem acessa o 127.0.0.1 é o administrador (como sempre foi).
USUARIO_LOCAL = SimpleNamespace(id=None, email="local", nome="Uso local", papel="admin", local=True, deve_trocar_senha=False)


def ip_do_cliente() -> str:
    return request.remote_addr or ""


def token_da_requisicao() -> str | None:
    t = request.headers.get("X-Searching-Token")
    if t:
        return t
    cab = request.headers.get("Authorization", "")
    return cab[7:].strip() if cab.lower().startswith("bearer ") else None


def _erro(mensagem: str, status: int):
    return jsonify({"error": mensagem}), status


def _origem_ok(origens) -> bool:
    origem = request.headers.get("Origin")
    return bool(origem) and origem.rstrip("/") in origens


def exigir_dono(produto_id: int):
    """Coletor só mexe em produto atribuído a ele; admin em qualquer um. Devolve (resposta, status) se negar, senão None."""
    u = g.usuario
    if u is None or u.papel == "admin":
        return None
    from sqlalchemy import select

    from ..db.models import Atribuicao

    with current_app.config["DB_FABRICA"]() as s:
        if s.scalar(select(Atribuicao.produto_id).where(Atribuicao.usuario_id == u.id, Atribuicao.produto_id == produto_id)):
            return None
    return _erro("Este produto não está atribuído a você.", 403)


def _limitar():
    """Limite de requisições por minuto (por usuário; sem login, por IP). Devolve a resposta 429 ou None."""
    if request.method == "OPTIONS" or request.path == "/api/health":
        return None
    lim = limite.limites()
    if request.endpoint == "exportar_historico":
        categoria = "exportar"
    elif request.method not in METODOS_SEGUROS:
        categoria = "escrita"
    else:
        categoria = "leitura"
    dono = ("u", g.usuario.id) if getattr(g, "usuario", None) is not None else ("ip", ip_do_cliente())
    espera = current_app.config["LIMITADOR"].permitir((categoria, *dono), lim[categoria])
    if espera is None:
        return None
    resposta = jsonify({"error": "Muitas requisições. Aguarde um pouco e tente de novo.", "aguardar_s": round(espera, 1)})
    resposta.status_code = 429
    resposta.headers["Retry-After"] = str(int(espera) + 1)
    return resposta


def instalar(app) -> None:
    app.config["LIMITADOR"] = limite.Limitador()

    @app.before_request
    def aplicar_politica():
        resposta = _aplicar_politica()
        if modo.hospedado():  # modo local: uma pessoa só, sem limite
            return _limitar() or resposta
        return resposta

    def _aplicar_politica():
        g.usuario, g.sessao, g.token = None, None, None
        if request.method == "OPTIONS" or request.endpoint is None:
            return None
        politica = pol.POLITICAS.get(request.endpoint)
        if politica is None:  # deny by default
            return _erro("Rota sem política de acesso.", 403)
        hospedado = modo.hospedado()
        if hospedado and politica.so_local:
            return _erro("Indisponível no modo hospedado: a coleta acontece pela extensão, no computador de cada pessoa.", 404)
        if politica.acesso == pol.EXTENSAO and not seguranca.extensao_autorizada(request.headers.get("Origin")):
            return _erro("Esta extensão não está autorizada neste servidor (SEARCHING_EXTENSAO_IDS).", 403)
        if not hospedado:
            g.usuario = USUARIO_LOCAL
            if request.endpoint.startswith("conta.") and request.endpoint not in ("conta.modo", "conta.eu"):
                return _erro("Não há login no modo local.", 404)
            if politica.acesso == pol.EXTENSAO and not assistida.token_valido(request.headers.get("X-Searching-Token")):
                return _erro("Token da extensão ausente ou inválido. Abra a tela Coleta assistida para parear.", 401)
            return None

        token = token_da_requisicao()
        insegura = request.method not in METODOS_SEGUROS
        origens = current_app.config["ORIGENS"]
        # Origin só protege credenciais "ambientes" (cookie); com token no cabeçalho o navegador de outro site não consegue enviar.
        if insegura and not token and not _origem_ok(origens):
            return _erro("Origem não permitida.", 403)
        if politica.acesso == pol.PUBLICA:
            return None

        with current_app.config["DB_FABRICA"]() as s:
            if politica.acesso == pol.EXTENSAO:
                achado = servico.token_valido(s, token)
                if not achado or achado[1].tipo != "extensao":
                    return _erro("Token da extensão ausente, inválido ou revogado. Pareie a extensão de novo.", 401)
                s.commit()
                g.usuario, g.token = _destacar(s, achado[0]), achado[1]
                return None
            cookie = request.cookies.get(COOKIE)
            if cookie:
                achado = servico.sessao_valida(s, cookie)
                if not achado:
                    return _erro("Sessão expirada. Entre de novo.", 401)
                u, sessao = achado
                if insegura and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), sessao.csrf):
                    return _erro("Token CSRF ausente ou inválido.", 403)
                s.commit()
                g.usuario, g.sessao = _destacar(s, u), sessao
                if u.deve_trocar_senha and request.endpoint not in ROTAS_DA_TROCA_DE_SENHA:
                    return _erro("Troque a senha provisória antes de continuar.", 403)
                if servico.exige_2fa(u) and not u.totp_ativo and request.endpoint not in ROTAS_DO_2FA:
                    resposta = jsonify({"error": "Administradores precisam ativar a verificação em duas etapas (Minha conta).", "codigo": "2fa_obrigatorio"})
                    resposta.status_code = 403
                    return resposta
                if politica.acesso == pol.LOGADO:
                    return None
                if servico.nivel(u.papel) < servico.nivel(politica.acesso):
                    return _negado(u, politica)
                return None
            if token:  # token de API somente leitura (planilhas, BI)
                achado = servico.token_valido(s, token)
                if not achado or achado[1].tipo != "leitura":
                    return _erro("Token inválido ou revogado.", 401)
                s.commit()
                g.usuario, g.token = _destacar(s, achado[0]), achado[1]
                if politica.acesso != pol.LEITOR or insegura:
                    return _negado(achado[0], politica)
                return None
        return _erro("Entre para continuar.", 401)

    def _destacar(s, u):
        s.expunge(u)
        return u

    def _negado(u, politica):
        return _erro("Seu perfil não tem permissão para isso.", 403)

    @app.after_request
    def auditar_e_proteger(resposta):
        if modo.hospedado():
            resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
            resposta.headers.setdefault("X-Frame-Options", "DENY")
            resposta.headers.setdefault("Referrer-Policy", "same-origin")
            resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            resposta.headers.setdefault(
                "Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
            )
            if request.path.startswith("/api/"):
                resposta.headers["Cache-Control"] = "no-store"
            u = getattr(g, "usuario", None)
            registrar = u is not None and request.endpoint in pol.POLITICAS and (
                (request.method not in METODOS_SEGUROS and resposta.status_code < 400) or resposta.status_code == 403
            )
            if registrar and request.endpoint != "conta.login":
                try:
                    with current_app.config["DB_FABRICA"]() as s:
                        acao = "acesso_negado" if resposta.status_code == 403 else "escrita"
                        servico.auditar(
                            s, acao, u, alvo=f"{request.method} {request.path}"[:200],
                            detalhe={"status": resposta.status_code}, ip=ip_do_cliente(),
                        )
                        s.commit()
                except Exception:  # auditar nunca derruba a resposta
                    current_app.logger.exception("falha ao gravar auditoria")
        return resposta
