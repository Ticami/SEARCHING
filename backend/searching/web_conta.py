"""Rotas de contas: login, senha, 2FA, tokens, usuários, atribuições e auditoria (modo hospedado)."""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, select

from . import modo
from .alerts import email as alertas_email
from .auth import guarda, servico
from .auth.guarda import COOKIE
from . import retencao
from .db.models import Atribuicao, Auditoria, Produto, SessaoLogin, TokenApi, Usuario

bp = Blueprint("conta", __name__)


def _fabrica():
    return current_app.config["DB_FABRICA"]


def _json_usuario(u) -> dict:
    return {
        "id": u.id, "email": u.email, "nome": u.nome, "papel": u.papel, "ativo": getattr(u, "ativo", True),
        "totp_ativo": getattr(u, "totp_ativo", False), "deve_trocar_senha": getattr(u, "deve_trocar_senha", False),
        "ultimo_login": u.ultimo_login.isoformat(timespec="seconds") if getattr(u, "ultimo_login", None) else None,
    }


def _json_token(t: TokenApi) -> dict:
    return {
        "id": t.id, "tipo": t.tipo, "nome": t.nome, "prefixo": t.prefixo,
        "criado_em": t.criado_em.isoformat(timespec="seconds"),
        "ultimo_uso": t.ultimo_uso.isoformat(timespec="seconds") if t.ultimo_uso else None,
        "revogado": t.revogado_em is not None,
    }


def _erro(e: servico.ErroAuth):
    return jsonify({"error": str(e), "codigo": e.codigo}), e.status


def _corpo() -> dict:
    d = request.get_json(force=True, silent=True)
    return d if isinstance(d, dict) else {}


@bp.route("/api/modo", methods=["GET"], endpoint="modo")
def modo_atual():
    return jsonify({"modo": modo.modo(), "login": modo.hospedado()})


@bp.route("/api/auth/login", methods=["POST"])
def login():
    d = _corpo()
    ip = guarda.ip_do_cliente()
    with _fabrica()() as s:
        try:
            u = servico.autenticar(s, str(d.get("email", "")), str(d.get("senha", "")), d.get("codigo"), ip)
        except servico.ErroAuth as e:
            servico.auditar(s, "login_falha", ip=ip, email=str(d.get("email", ""))[:200], detalhe={"motivo": e.codigo})
            s.commit()  # guarda a tentativa (limite) e o bloqueio
            return _erro(e)
        valor, csrf = servico.criar_sessao(s, u, ip, request.headers.get("User-Agent", ""))
        servico.auditar(s, "login_ok", u, ip=ip)
        s.commit()
        resposta = jsonify({"usuario": _json_usuario(u), "csrf": csrf})
    resposta.set_cookie(
        COOKIE, valor, max_age=servico.SESSAO_MAXIMA_H * 3600, httponly=True,
        secure=modo.url_publica().startswith("https://"), samesite="Lax", path="/",
    )
    return resposta


@bp.route("/api/auth/logout", methods=["POST"])
def logout():
    if g.sessao is not None:
        with _fabrica()() as s:
            x = s.get(type(g.sessao), g.sessao.id)
            x.revogada = True
            servico.auditar(s, "logout", g.usuario, ip=guarda.ip_do_cliente())
            s.commit()
    resposta = jsonify({"message": "Você saiu."})
    resposta.delete_cookie(COOKIE, path="/")
    return resposta


@bp.route("/api/auth/eu", methods=["GET"])
def eu():
    if not modo.hospedado():
        return jsonify({"modo": "local", "usuario": _json_usuario(g.usuario), "csrf": None, "atribuidos": None})
    if g.usuario is None:
        return jsonify({"error": "Entre para continuar."}), 401
    with _fabrica()() as s:
        atribuidos = list(s.scalars(select(Atribuicao.produto_id).where(Atribuicao.usuario_id == g.usuario.id)))
    return jsonify({
        "modo": "hospedado", "usuario": _json_usuario(g.usuario), "csrf": g.sessao.csrf if g.sessao else None, "atribuidos": atribuidos,
        "precisa_2fa": servico.exige_2fa(g.usuario) and not g.usuario.totp_ativo,
    })


@bp.route("/api/auth/trocar-senha", methods=["POST"])
def trocar_senha():
    d = _corpo()
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        try:
            servico.trocar_senha(s, u, str(d.get("atual", "")), str(d.get("nova", "")), g.sessao.id if g.sessao else None)
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "senha_trocada", u, ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Senha alterada. Outras sessões foram encerradas."})


@bp.route("/api/auth/recuperar", methods=["POST"])
def recuperar():
    """Envia o link de redefinição. A resposta é sempre a mesma, exista ou não a conta."""
    d = _corpo()
    ip = guarda.ip_do_cliente()
    generica = jsonify({"message": "Se este e-mail tem conta, enviamos um link para redefinir a senha."})
    with _fabrica()() as s:
        desde = datetime.now() - timedelta(minutes=servico.JANELA_IP_MIN)
        pedidos = s.scalar(select(func.count()).select_from(Auditoria).where(
            Auditoria.acao == "recuperacao_pedida", Auditoria.ip == ip, Auditoria.em >= desde)) or 0
        if pedidos >= 5:
            return jsonify({"error": "Muitos pedidos. Aguarde alguns minutos."}), 429
        servico.auditar(s, "recuperacao_pedida", ip=ip, email=str(d.get("email", ""))[:200])
        achado = servico.solicitar_redefinicao(s, str(d.get("email", "")))
        s.commit()
        if achado:
            u, puro = achado
            notificador = current_app.config["NOTIFICADOR"]
            try:
                smtp = notificador.carregar_config()
                link = f"{modo.url_publica()}/redefinir?token={puro}"
                texto = (f"Olá, {u.nome or u.email}.\n\nPara criar uma nova senha no SEARCHING, abra o link (vale por "
                         f"{servico.REDEFINICAO_MIN} minutos e só funciona uma vez):\n{link}\n\n"
                         "Se você não pediu isso, ignore este e-mail.")
                msg = alertas_email._mensagem("[SEARCHING] Redefinição de senha", smtp.remetente, [u.email], texto, f"<pre>{alertas_email.escape(texto)}</pre>")
                notificador.enviar(msg, smtp)
            except Exception:
                current_app.logger.exception("e-mail de redefinição não enviado")
    return generica


@bp.route("/api/auth/redefinir", methods=["POST"])
def redefinir():
    d = _corpo()
    with _fabrica()() as s:
        try:
            u = servico.redefinir_com_token(s, str(d.get("token", "")), str(d.get("senha", "")))
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "senha_redefinida", u, ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Senha redefinida. Entre com a nova senha."})


# ---------- 2FA ----------
@bp.route("/api/auth/2fa/iniciar", methods=["POST"])
def iniciar_2fa():
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        try:
            dados = servico.iniciar_2fa(u)
        except servico.ErroAuth as e:
            return _erro(e)
        s.commit()
    return jsonify(dados)


@bp.route("/api/auth/2fa/ativar", methods=["POST"])
def ativar_2fa():
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        try:
            servico.ativar_2fa(u, str(_corpo().get("codigo", "")))
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "2fa_ativado", u, ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Verificação em duas etapas ativada."})


@bp.route("/api/auth/2fa/desativar", methods=["POST"])
def desativar_2fa():
    if servico.exige_2fa(g.usuario):
        return jsonify({"error": "A verificação em duas etapas é obrigatória para administradores."}), 409
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        try:
            servico.desativar_2fa(u, str(_corpo().get("senha", "")))
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "2fa_desativado", u, ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Verificação em duas etapas desativada."})


# ---------- sessões ativas ----------
def _json_sessao(x: SessaoLogin, atual_id=None, usuarios=None) -> dict:
    return {
        "id": x.id, "usuario_id": x.usuario_id, "usuario": (usuarios or {}).get(x.usuario_id),
        "criada_em": x.criada_em.isoformat(timespec="seconds"), "ultimo_uso": x.ultimo_uso.isoformat(timespec="seconds"),
        "ip": x.ip, "navegador": x.user_agent, "atual": x.id == atual_id,
    }


@bp.route("/api/minhas-sessoes", methods=["GET"])
def minhas_sessoes():
    with _fabrica()() as s:
        return jsonify([_json_sessao(x, g.sessao.id if g.sessao else None) for x in servico.sessoes_ativas(s, g.usuario.id)])


@bp.route("/api/minhas-sessoes/<int:sessao_id>", methods=["DELETE"])
def encerrar_minha_sessao(sessao_id):
    with _fabrica()() as s:
        x = s.get(SessaoLogin, sessao_id)
        if x is None or x.usuario_id != g.usuario.id:
            return jsonify({"error": "Sessão não encontrada."}), 404
        x.revogada = True
        servico.auditar(s, "sessao_encerrada", g.usuario, alvo=f"sessão {x.id}", ip=guarda.ip_do_cliente())
        s.commit()
    resposta = jsonify({"message": "Sessão encerrada."})
    if g.sessao is not None and g.sessao.id == sessao_id:
        resposta.delete_cookie(COOKIE, path="/")
    return resposta


@bp.route("/api/minhas-sessoes/encerrar-outras", methods=["POST"])
def encerrar_outras_sessoes():
    with _fabrica()() as s:
        servico.revogar_sessoes_do_usuario(s, g.usuario.id, exceto_id=g.sessao.id if g.sessao else None)
        servico.auditar(s, "sessoes_encerradas", g.usuario, alvo="todas as outras", ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "As outras sessões foram encerradas."})


@bp.route("/api/sessoes", methods=["GET"])
def listar_sessoes():
    with _fabrica()() as s:
        nomes = {u.id: u.email for u in s.scalars(select(Usuario))}
        return jsonify([_json_sessao(x, g.sessao.id if g.sessao else None, nomes) for x in servico.sessoes_ativas(s)])


@bp.route("/api/sessoes/<int:sessao_id>", methods=["DELETE"])
def encerrar_sessao(sessao_id):
    with _fabrica()() as s:
        x = s.get(SessaoLogin, sessao_id)
        if x is None:
            return jsonify({"error": "Sessão não encontrada."}), 404
        x.revogada = True
        servico.auditar(s, "sessao_encerrada_por_admin", g.usuario, alvo=f"sessão {x.id} (usuário {x.usuario_id})", ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Sessão encerrada. A pessoa precisa entrar de novo."})


# ---------- retenção dos prints ----------
@bp.route("/api/retencao", methods=["GET"], endpoint="retencao")
def retencao_atual():
    with _fabrica()() as s:
        return jsonify({"dias": retencao.dias_configurados(s)})


@bp.route("/api/retencao", methods=["PUT"])
def salvar_retencao():
    with _fabrica()() as s:
        try:
            retencao.salvar_dias(s, int(_corpo().get("dias", -1)))
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e) or "Informe o número de dias."}), 400
        servico.auditar(s, "retencao_alterada", g.usuario, detalhe={"dias": _corpo().get("dias")}, ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify({"dias": retencao.dias_configurados(s)})


@bp.route("/api/retencao/aplicar", methods=["POST"])
def aplicar_retencao():
    with _fabrica()() as s:
        resultado = retencao.aplicar(s, simular=bool(_corpo().get("simular")))
        servico.auditar(s, "retencao_aplicada", g.usuario, detalhe=resultado, ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify(resultado)


# ---------- tokens próprios ----------
@bp.route("/api/meus-tokens", methods=["GET"])
def meus_tokens():
    with _fabrica()() as s:
        ts = s.scalars(select(TokenApi).where(TokenApi.usuario_id == g.usuario.id).order_by(TokenApi.id.desc())).all()
        return jsonify([_json_token(t) for t in ts])


@bp.route("/api/meus-tokens", methods=["POST"])
def criar_meu_token():
    d = _corpo()
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        try:
            puro, t = servico.criar_token(s, u, str(d.get("tipo", "")), str(d.get("nome", "")))
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "token_criado", u, alvo=f"{t.tipo}:{t.prefixo}", ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify({"token": puro, "info": _json_token(t), "aviso": "Guarde agora: o token não será mostrado de novo."})


@bp.route("/api/meus-tokens/<int:token_id>", methods=["DELETE"])
def revogar_meu_token(token_id):
    with _fabrica()() as s:
        t = s.get(TokenApi, token_id)
        if t is None or t.usuario_id != g.usuario.id:
            return jsonify({"error": "Token não encontrado."}), 404
        servico.revogar_token(s, t)
        servico.auditar(s, "token_revogado", g.usuario, alvo=f"{t.tipo}:{t.prefixo}", ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Token revogado."})


@bp.route("/api/extensao/parear", methods=["POST"])
def parear_extensao():
    """Cria o token da extensão do usuário logado (substitui o pareamento anterior do mesmo navegador)."""
    with _fabrica()() as s:
        u = s.get(Usuario, g.usuario.id)
        for antigo in s.scalars(select(TokenApi).where(
                TokenApi.usuario_id == u.id, TokenApi.tipo == "extensao", TokenApi.nome == "Pareamento pela tela",
                TokenApi.revogado_em.is_(None))):
            servico.revogar_token(s, antigo)
        try:
            puro, t = servico.criar_token(s, u, "extensao", "Pareamento pela tela")
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "extensao_pareada", u, alvo=t.prefixo, ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify({"token": puro, "servidor": modo.url_publica()})


# ---------- administração ----------
@bp.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    with _fabrica()() as s:
        return jsonify([_json_usuario(u) for u in s.scalars(select(Usuario).order_by(Usuario.id))])


@bp.route("/api/usuarios", methods=["POST"])
def criar_usuario():
    d = _corpo()
    with _fabrica()() as s:
        temporaria = None
        try:
            from .auth import senhas

            temporaria = senhas.senha_temporaria()
            u = servico.criar_usuario(s, str(d.get("email", "")), str(d.get("nome", "")), str(d.get("papel", "leitor")),
                                      temporaria, deve_trocar_senha=True)
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "usuario_criado", g.usuario, alvo=u.email, detalhe={"papel": u.papel}, ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify({"usuario": _json_usuario(u), "senha_temporaria": temporaria,
                        "aviso": "Entregue a senha provisória por um canal seguro: ela não será mostrada de novo."}), 201


@bp.route("/api/usuarios/<int:usuario_id>", methods=["PATCH"])
def alterar_usuario(usuario_id):
    d = _corpo()
    with _fabrica()() as s:
        alvo = s.get(Usuario, usuario_id)
        if alvo is None:
            return jsonify({"error": "Usuário não encontrado."}), 404
        try:
            servico.alterar_usuario(s, alvo, g.usuario, papel=d.get("papel"), ativo=d.get("ativo"), nome=d.get("nome"))
        except servico.ErroAuth as e:
            return _erro(e)
        servico.auditar(s, "usuario_alterado", g.usuario, alvo=alvo.email, detalhe={k: d[k] for k in ("papel", "ativo", "nome") if k in d},
                        ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify(_json_usuario(alvo))


@bp.route("/api/usuarios/<int:usuario_id>/redefinir-senha", methods=["POST"])
def redefinir_senha_usuario(usuario_id):
    with _fabrica()() as s:
        alvo = s.get(Usuario, usuario_id)
        if alvo is None:
            return jsonify({"error": "Usuário não encontrado."}), 404
        temporaria = servico.redefinir_senha_por_admin(s, alvo)
        servico.auditar(s, "senha_redefinida_por_admin", g.usuario, alvo=alvo.email, ip=guarda.ip_do_cliente())
        s.commit()
        return jsonify({"senha_temporaria": temporaria, "aviso": "A pessoa terá de trocá-la ao entrar."})


@bp.route("/api/usuarios/<int:usuario_id>/tokens", methods=["GET"])
def tokens_do_usuario(usuario_id):
    with _fabrica()() as s:
        ts = s.scalars(select(TokenApi).where(TokenApi.usuario_id == usuario_id).order_by(TokenApi.id.desc())).all()
        return jsonify([_json_token(t) for t in ts])


@bp.route("/api/tokens/<int:token_id>", methods=["DELETE"])
def revogar_token(token_id):
    with _fabrica()() as s:
        t = s.get(TokenApi, token_id)
        if t is None:
            return jsonify({"error": "Token não encontrado."}), 404
        servico.revogar_token(s, t)
        servico.auditar(s, "token_revogado_por_admin", g.usuario, alvo=f"usuario {t.usuario_id}: {t.tipo}:{t.prefixo}", ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Token revogado. Ele deixa de funcionar agora."})


@bp.route("/api/auditoria", methods=["GET"])
def auditoria():
    limite = min(request.args.get("limite", 200, type=int), 1000)
    with _fabrica()() as s:
        q = select(Auditoria).order_by(Auditoria.id.desc()).limit(limite)
        if request.args.get("acao"):
            q = q.where(Auditoria.acao == request.args["acao"])
        if request.args.get("usuario_id", type=int):
            q = q.where(Auditoria.usuario_id == request.args.get("usuario_id", type=int))
        return jsonify([
            {"id": a.id, "em": a.em.isoformat(timespec="seconds"), "usuario": a.usuario_email, "acao": a.acao,
             "alvo": a.alvo, "detalhe": a.detalhe, "ip": a.ip} for a in s.scalars(q)
        ])


@bp.route("/api/atribuicoes", methods=["GET"])
def listar_atribuicoes():
    with _fabrica()() as s:
        mapa: dict[int, list[int]] = {}
        for a in s.scalars(select(Atribuicao)):
            mapa.setdefault(a.usuario_id, []).append(a.produto_id)
        return jsonify(mapa)


@bp.route("/api/atribuicoes/<int:usuario_id>", methods=["PUT"])
def salvar_atribuicoes(usuario_id):
    """Substitui a lista de produtos atribuídos ao usuário."""
    ids = {int(i) for i in _corpo().get("produtos", []) if str(i).isdigit()}
    with _fabrica()() as s:
        u = s.get(Usuario, usuario_id)
        if u is None:
            return jsonify({"error": "Usuário não encontrado."}), 404
        validos = set(s.scalars(select(Produto.id).where(Produto.id.in_(ids)))) if ids else set()
        for a in s.scalars(select(Atribuicao).where(Atribuicao.usuario_id == usuario_id)):
            if a.produto_id not in validos:
                s.delete(a)
        atuais = set(s.scalars(select(Atribuicao.produto_id).where(Atribuicao.usuario_id == usuario_id)))
        for pid in validos - atuais:
            s.add(Atribuicao(produto_id=pid, usuario_id=usuario_id))
        servico.auditar(s, "atribuicoes_alteradas", g.usuario, alvo=u.email, detalhe={"produtos": sorted(validos)}, ip=guarda.ip_do_cliente())
        s.commit()
    return jsonify({"message": "Atribuições salvas.", "produtos": sorted(validos)})
