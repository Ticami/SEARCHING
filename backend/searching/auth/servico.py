"""Contas, sessões, tokens, bloqueio de login, recuperação de senha, 2FA e auditoria (tudo no banco)."""
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Auditoria, RedefinicaoSenha, SessaoLogin, TentativaLogin, TokenApi, Usuario
from . import senhas, totp

PAPEIS = ("leitor", "coletor", "admin")  # do menos para o mais poderoso
TIPOS_TOKEN = ("extensao", "leitura")
FALHAS_PARA_BLOQUEAR = 5
BLOQUEIO_MIN = 15
LIMITE_FALHAS_IP = 20
JANELA_IP_MIN = 15
SESSAO_OCIOSA_H = 8
SESSAO_MAXIMA_H = 24
REDEFINICAO_MIN = 30
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErroAuth(Exception):
    """Erro de autenticação/gestão de contas; `status` é o HTTP sugerido."""

    def __init__(self, mensagem: str, status: int = 400, codigo: str = ""):
        super().__init__(mensagem)
        self.status, self.codigo = status, codigo


def nivel(papel: str) -> int:
    return PAPEIS.index(papel) if papel in PAPEIS else -1


def normalizar_email(email: str | None) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 200:
        raise ErroAuth("E-mail inválido.")
    return e


# ---------- auditoria ----------
def auditar(s: Session, acao: str, usuario: Usuario | None = None, alvo: str = "", detalhe: dict | None = None,
            ip: str = "", email: str = "", agora: datetime | None = None) -> None:
    s.add(Auditoria(
        em=agora or datetime.now(), usuario_id=usuario.id if usuario else None,
        usuario_email=usuario.email if usuario else email, acao=acao, alvo=alvo[:200], detalhe=detalhe, ip=ip[:64],
    ))


# ---------- usuários ----------
def criar_usuario(s: Session, email: str, nome: str, papel: str, senha: str, deve_trocar_senha: bool = False) -> Usuario:
    email = normalizar_email(email)
    if papel not in PAPEIS:
        raise ErroAuth("Papel inválido (use admin, coletor ou leitor).")
    try:
        senhas.validar_politica(senha, email)
    except senhas.SenhaFraca as e:
        raise ErroAuth(str(e)) from None
    if s.scalar(select(Usuario.id).where(Usuario.email == email)):
        raise ErroAuth("Já existe um usuário com este e-mail.", 409)
    u = Usuario(email=email, nome=(nome or "").strip()[:120], papel=papel, senha_hash=senhas.gerar_hash(senha),
                deve_trocar_senha=deve_trocar_senha)
    s.add(u)
    s.flush()
    return u


def _admins_ativos(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(Usuario).where(Usuario.papel == "admin", Usuario.ativo.is_(True))) or 0


def alterar_usuario(s: Session, alvo: Usuario, ator: Usuario | None, papel: str | None = None, ativo: bool | None = None,
                    nome: str | None = None) -> Usuario:
    if papel is not None and papel not in PAPEIS:
        raise ErroAuth("Papel inválido.")
    perde_admin = alvo.papel == "admin" and alvo.ativo and ((papel is not None and papel != "admin") or ativo is False)
    if perde_admin:
        if ator is not None and ator.id == alvo.id:
            raise ErroAuth("Você não pode tirar o próprio acesso de administrador.", 409)
        if _admins_ativos(s) <= 1:
            raise ErroAuth("É preciso manter pelo menos um administrador ativo.", 409)
    if papel is not None:
        alvo.papel = papel
        if nivel(papel) < nivel("coletor"):  # leitor não pode manter token de extensão
            for t in s.scalars(select(TokenApi).where(TokenApi.usuario_id == alvo.id, TokenApi.tipo == "extensao")):
                revogar_token(s, t)
    if nome is not None:
        alvo.nome = nome.strip()[:120]
    if ativo is not None:
        alvo.ativo = ativo
        if not ativo:
            revogar_sessoes_do_usuario(s, alvo.id)
            revogar_tokens_do_usuario(s, alvo.id)
    return alvo


def redefinir_senha_por_admin(s: Session, alvo: Usuario) -> str:
    """Define uma senha temporária (mostrada uma vez ao admin) e obriga a troca no próximo login."""
    temporaria = senhas.senha_temporaria()
    alvo.senha_hash = senhas.gerar_hash(temporaria)
    alvo.deve_trocar_senha = True
    alvo.falhas_login, alvo.bloqueado_ate = 0, None
    revogar_sessoes_do_usuario(s, alvo.id)
    return temporaria


# ---------- login ----------
def _falhas_recentes_ip(s: Session, ip: str, agora: datetime) -> int:
    desde = agora - timedelta(minutes=JANELA_IP_MIN)
    return s.scalar(select(func.count()).select_from(TentativaLogin).where(
        TentativaLogin.ip == ip, TentativaLogin.sucesso.is_(False), TentativaLogin.em >= desde)) or 0


def autenticar(s: Session, email: str, senha: str, codigo: str | None, ip: str, agora: datetime | None = None) -> Usuario:
    """Confere e-mail + senha (+ código 2FA). Mensagem única para e-mail inexistente e senha errada."""
    agora = agora or datetime.now()
    email_n = (email or "").strip().lower()
    generico = ErroAuth("E-mail ou senha incorretos.", 401, "credenciais")
    if _falhas_recentes_ip(s, ip, agora) >= LIMITE_FALHAS_IP:
        raise ErroAuth("Muitas tentativas deste endereço. Aguarde alguns minutos.", 429, "limite_ip")
    u = s.scalar(select(Usuario).where(Usuario.email == email_n))
    if u is None or not u.ativo:
        senhas.conferir(senha or "", senhas.HASH_FALSO)  # gasta o mesmo tempo
        s.add(TentativaLogin(email=email_n[:200], ip=ip, em=agora, sucesso=False))
        raise generico
    if u.bloqueado_ate and u.bloqueado_ate > agora:
        minutos = int((u.bloqueado_ate - agora).total_seconds() // 60) + 1
        raise ErroAuth(f"Conta bloqueada temporariamente por tentativas erradas. Tente de novo em {minutos} min.", 423, "bloqueada")
    ok = senhas.conferir(senha or "", u.senha_hash)
    if ok and u.totp_ativo:
        if not codigo:
            raise ErroAuth("Informe o código do aplicativo autenticador.", 401, "2fa_necessario")
        ok = totp.verificar(u.totp_segredo or "", codigo, agora.timestamp())
    if not ok:
        s.add(TentativaLogin(email=email_n[:200], ip=ip, em=agora, sucesso=False))
        u.falhas_login += 1
        if u.falhas_login >= FALHAS_PARA_BLOQUEAR:
            u.bloqueado_ate = agora + timedelta(minutes=BLOQUEIO_MIN)
            u.falhas_login = 0
            auditar(s, "conta_bloqueada", u, ip=ip, agora=agora)
        raise generico
    u.falhas_login, u.bloqueado_ate, u.ultimo_login = 0, None, agora
    s.add(TentativaLogin(email=email_n[:200], ip=ip, em=agora, sucesso=True))
    if senhas.precisa_novo_hash(u.senha_hash):
        u.senha_hash = senhas.gerar_hash(senha)
    return u


# ---------- sessões ----------
def criar_sessao(s: Session, u: Usuario, ip: str, user_agent: str, agora: datetime | None = None) -> tuple[str, str]:
    agora = agora or datetime.now()
    valor, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    s.add(SessaoLogin(hash=senhas.sha256(valor), usuario_id=u.id, csrf=csrf, criada_em=agora, ultimo_uso=agora,
                      expira_em=agora + timedelta(hours=SESSAO_MAXIMA_H), ip=ip[:64], user_agent=(user_agent or "")[:200]))
    return valor, csrf


def sessao_valida(s: Session, valor: str | None, agora: datetime | None = None) -> tuple[Usuario, SessaoLogin] | None:
    if not valor:
        return None
    agora = agora or datetime.now()
    sessao = s.scalar(select(SessaoLogin).where(SessaoLogin.hash == senhas.sha256(valor)))
    if sessao is None or sessao.revogada or sessao.expira_em <= agora:
        return None
    if agora - sessao.ultimo_uso > timedelta(hours=SESSAO_OCIOSA_H):
        return None
    u = s.get(Usuario, sessao.usuario_id)
    if u is None or not u.ativo:
        return None
    if agora - sessao.ultimo_uso > timedelta(minutes=1):
        sessao.ultimo_uso = agora
    return u, sessao


def revogar_sessoes_do_usuario(s: Session, usuario_id: int, exceto_id: int | None = None) -> None:
    for x in s.scalars(select(SessaoLogin).where(SessaoLogin.usuario_id == usuario_id, SessaoLogin.revogada.is_(False))):
        if x.id != exceto_id:
            x.revogada = True


# ---------- tokens de API ----------
def criar_token(s: Session, u: Usuario, tipo: str, nome: str = "") -> tuple[str, TokenApi]:
    """O token completo só é devolvido agora; no banco fica apenas o hash."""
    if tipo not in TIPOS_TOKEN:
        raise ErroAuth("Tipo de token inválido.")
    if tipo == "extensao" and nivel(u.papel) < nivel("coletor"):
        raise ErroAuth("Só coletores e administradores podem parear a extensão.", 403)
    puro = f"sch_{tipo[0]}_{secrets.token_urlsafe(32)}"
    t = TokenApi(usuario_id=u.id, tipo=tipo, nome=(nome or "").strip()[:80], prefixo=puro[:10], hash=senhas.sha256(puro))
    s.add(t)
    s.flush()
    return puro, t


def token_valido(s: Session, puro: str | None, agora: datetime | None = None) -> tuple[Usuario, TokenApi] | None:
    """Consulta o banco a cada chamada: um token revogado para de funcionar na hora."""
    if not puro or not puro.startswith("sch_"):
        return None
    t = s.scalar(select(TokenApi).where(TokenApi.hash == senhas.sha256(puro)))
    if t is None or t.revogado_em is not None:
        return None
    u = s.get(Usuario, t.usuario_id)
    if u is None or not u.ativo:
        return None
    if t.tipo == "extensao" and nivel(u.papel) < nivel("coletor"):  # rebaixado depois de parear
        return None
    t.ultimo_uso = agora or datetime.now()
    return u, t


def revogar_token(s: Session, t: TokenApi, agora: datetime | None = None) -> None:
    if t.revogado_em is None:
        t.revogado_em = agora or datetime.now()


def revogar_tokens_do_usuario(s: Session, usuario_id: int) -> None:
    for t in s.scalars(select(TokenApi).where(TokenApi.usuario_id == usuario_id, TokenApi.revogado_em.is_(None))):
        revogar_token(s, t)


# ---------- senha ----------
def trocar_senha(s: Session, u: Usuario, atual: str, nova: str, sessao_atual_id: int | None = None) -> None:
    if not senhas.conferir(atual or "", u.senha_hash):
        raise ErroAuth("A senha atual está incorreta.", 403)
    try:
        senhas.validar_politica(nova, u.email)
    except senhas.SenhaFraca as e:
        raise ErroAuth(str(e)) from None
    if senhas.conferir(nova, u.senha_hash):
        raise ErroAuth("A nova senha precisa ser diferente da atual.")
    u.senha_hash, u.deve_trocar_senha = senhas.gerar_hash(nova), False
    revogar_sessoes_do_usuario(s, u.id, exceto_id=sessao_atual_id)


def solicitar_redefinicao(s: Session, email: str, agora: datetime | None = None) -> tuple[Usuario, str] | None:
    """Cria o link de uso único. Devolve None (sem erro) se o e-mail não existe, para não revelar quem tem conta."""
    agora = agora or datetime.now()
    u = s.scalar(select(Usuario).where(Usuario.email == (email or "").strip().lower(), Usuario.ativo.is_(True)))
    if u is None:
        return None
    puro = secrets.token_urlsafe(32)
    s.add(RedefinicaoSenha(usuario_id=u.id, hash=senhas.sha256(puro), expira_em=agora + timedelta(minutes=REDEFINICAO_MIN)))
    return u, puro


def redefinir_com_token(s: Session, puro: str, nova: str, agora: datetime | None = None) -> Usuario:
    agora = agora or datetime.now()
    r = s.scalar(select(RedefinicaoSenha).where(RedefinicaoSenha.hash == senhas.sha256(puro or "")))
    if r is None or r.usado_em is not None or r.expira_em <= agora:
        raise ErroAuth("Link de redefinição inválido ou expirado.", 400)
    u = s.get(Usuario, r.usuario_id)
    try:
        senhas.validar_politica(nova, u.email)
    except senhas.SenhaFraca as e:
        raise ErroAuth(str(e)) from None
    u.senha_hash, u.deve_trocar_senha = senhas.gerar_hash(nova), False
    u.falhas_login, u.bloqueado_ate = 0, None
    r.usado_em = agora
    revogar_sessoes_do_usuario(s, u.id)
    return u


# ---------- sessões ativas ----------
def sessoes_ativas(s: Session, usuario_id: int | None = None, agora: datetime | None = None) -> list[SessaoLogin]:
    agora = agora or datetime.now()
    consulta = select(SessaoLogin).where(
        SessaoLogin.revogada.is_(False), SessaoLogin.expira_em > agora,
        SessaoLogin.ultimo_uso > agora - timedelta(hours=SESSAO_OCIOSA_H),
    ).order_by(SessaoLogin.ultimo_uso.desc())
    if usuario_id is not None:
        consulta = consulta.where(SessaoLogin.usuario_id == usuario_id)
    return list(s.scalars(consulta))


# ---------- 2FA ----------
def exige_2fa(u, env: dict | None = None) -> bool:
    """2FA obrigatório para administradores (SEARCHING_2FA_ADMIN=0 desliga)."""
    import os

    valor = (os.environ if env is None else env).get("SEARCHING_2FA_ADMIN", "1").strip().lower()
    return u.papel == "admin" and valor not in ("0", "false", "nao", "não", "off")



def iniciar_2fa(u: Usuario) -> dict:
    if u.totp_ativo:
        raise ErroAuth("A verificação em duas etapas já está ativa.", 409)
    u.totp_segredo = totp.novo_segredo()
    return {"segredo": u.totp_segredo, "uri": totp.uri(u.totp_segredo, u.email)}


def ativar_2fa(u: Usuario, codigo: str) -> None:
    if not u.totp_segredo or not totp.verificar(u.totp_segredo, codigo):
        raise ErroAuth("Código incorreto.", 400)
    u.totp_ativo = True


def desativar_2fa(u: Usuario, senha: str) -> None:
    if not senhas.conferir(senha or "", u.senha_hash):
        raise ErroAuth("Senha incorreta.", 403)
    u.totp_ativo, u.totp_segredo = False, None
