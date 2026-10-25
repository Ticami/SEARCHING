"""Montagem e envio dos e-mails (alerta, resumo diário e teste). Credenciais só vêm do .env (RF-26)."""
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from pathlib import Path
from string import Template

from dotenv import dotenv_values

from ..core.precos import formatar_brl
from ..db.session import BACKEND_DIR

TEMPLATES = Path(__file__).parent / "templates"
ARQUIVOS_ENV = (BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env")
ROTULO_BASE = {"pix": "PIX", "cartao_1x": "cartão 1x"}
ROTULO_MOTIVO = {"queda": "queda acima do limite", "preco_alvo": "preço-alvo atingido"}


class ConfigEmailIncompleta(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigSMTP:
    host: str
    port: int
    usuario: str
    senha: str
    remetente: str
    destinatarios: tuple[str, ...]


def _valores_env(env: dict | None = None) -> dict:
    if env is not None:
        return env
    valores: dict = {}
    for arquivo in ARQUIVOS_ENV:
        if arquivo.exists():
            valores.update({k: v for k, v in dotenv_values(arquivo).items() if v})
    valores.update({k: v for k, v in os.environ.items() if k.startswith(("SMTP_", "ALERTA_")) and v})
    return valores


def carregar_config_smtp(env: dict | None = None) -> ConfigSMTP:
    """Lê SMTP_* e ALERTA_* do .env (e do ambiente). Lança ConfigEmailIncompleta com o que falta."""
    v = _valores_env(env)
    faltando = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERTA_DESTINATARIOS") if not v.get(k)]
    if faltando:
        raise ConfigEmailIncompleta("E-mail não configurado: faltam " + ", ".join(faltando) + " no arquivo .env")
    try:
        porta = int(v.get("SMTP_PORT", 587))
    except ValueError:
        raise ConfigEmailIncompleta("SMTP_PORT inválida no arquivo .env") from None
    destinatarios = tuple(d.strip() for d in v["ALERTA_DESTINATARIOS"].split(",") if d.strip())
    return ConfigSMTP(
        host=v["SMTP_HOST"],
        port=porta,
        usuario=v["SMTP_USER"],
        senha=v["SMTP_PASSWORD"].replace(" ", ""),  # senhas de app do Gmail vêm com espaços
        remetente=v.get("ALERTA_REMETENTE") or v["SMTP_USER"],
        destinatarios=destinatarios,
    )


def status_config(env: dict | None = None) -> dict:
    """Situação da configuração para a interface (nunca devolve a senha)."""
    try:
        c = carregar_config_smtp(env)
    except ConfigEmailIncompleta as exc:
        return {"configurado": False, "motivo": str(exc), "destinatarios": []}
    return {"configurado": True, "remetente": c.remetente, "destinatarios": list(c.destinatarios), "servidor": f"{c.host}:{c.port}"}


def _template(nome: str, valores: dict) -> str:
    seguros = {k: escape(str(v)) for k, v in valores.items()}
    return Template((TEMPLATES / nome).read_text(encoding="utf-8")).safe_substitute(seguros)


def _mensagem(assunto: str, remetente: str, destinatarios, texto: str, html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    return msg


def construir_alerta(produto, coleta, decisao, base_preco: str, remetente: str, destinatarios) -> EmailMessage:
    """E-mail de queda: produto, loja, preços, percentual, data/hora, link e o print anexado."""
    base = ROTULO_BASE.get(base_preco, base_preco)
    caminho = BACKEND_DIR / coleta.caminho_print if coleta.caminho_print else None
    tem_print = bool(caminho and caminho.is_file())
    dados = {
        "nome": produto.nome_comercial,
        "loja": produto.loja,
        "quando": coleta.coletado_em.strftime("%d/%m/%Y %H:%M"),
        "base_preco": base,
        "preco_anterior": formatar_brl(decisao.preco_anterior_centavos),
        "preco_atual": formatar_brl(decisao.preco_atual_centavos),
        "queda_pct": f"-{decisao.queda_pct:.1f}%".replace(".", ","),
        "motivo": " e ".join(ROTULO_MOTIVO[m] for m in decisao.motivos),
        "link": produto.url_atual,
        "print_aviso": "O print da página no momento da coleta está anexado." if tem_print else "Print indisponível para esta coleta.",
    }
    texto = (
        f"Queda de preço: {dados['nome']} ({dados['loja']})\n"
        f"Preço anterior ({base}): {dados['preco_anterior']}\n"
        f"Preço atual ({base}): {dados['preco_atual']}  ({dados['queda_pct']})\n"
        f"Motivo: {dados['motivo']}\n"
        f"Coletado em: {dados['quando']}\n"
        f"Anúncio: {dados['link']}\n"
        f"{dados['print_aviso']}\n"
    )
    assunto = f"[SEARCHING] {dados['nome']}: {dados['preco_atual']} ({dados['queda_pct']})"
    msg = _mensagem(assunto, remetente, destinatarios, texto, _template("alerta.html", dados))
    if tem_print:
        msg.add_attachment(caminho.read_bytes(), maintype="image", subtype="png", filename=caminho.name)
    return msg


def construir_resumo(resumo: dict, quando, remetente: str, destinatarios) -> EmailMessage:
    por_status = {k: v for k, v in (resumo.get("por_status") or {}).items() if k != "OK"}
    detalhe = "Falhas por motivo: " + ", ".join(f"{k} ({v})" for k, v in sorted(por_status.items())) if por_status else "Nenhuma falha."
    dados = {
        "quando": quando.strftime("%d/%m/%Y %H:%M"),
        "total": resumo.get("total", 0),
        "ok": resumo.get("ok", 0),
        "falhas": resumo.get("falhas", 0),
        "links_corrigidos": resumo.get("links_corrigidos", 0),
        "em_revisao": resumo.get("em_revisao", 0),
        "quedas": resumo.get("alertas", 0),
        "detalhe_falhas": detalhe,
    }
    texto = (
        f"Resumo da coleta de {dados['quando']}\n"
        f"Produtos: {dados['total']} | com sucesso: {dados['ok']} | com falha: {dados['falhas']}\n"
        f"Links corrigidos sozinhos: {dados['links_corrigidos']} | aguardando revisão: {dados['em_revisao']}\n"
        f"Quedas de preço detectadas: {dados['quedas']}\n{detalhe}\n"
    )
    assunto = f"[SEARCHING] Resumo: {dados['ok']}/{dados['total']} coletados, {dados['quedas']} queda(s)"
    return _mensagem(assunto, remetente, destinatarios, texto, _template("resumo.html", dados))


def construir_resumo_semanal(remetente: str, destinatarios, quando, dias: int, linhas: str, excel: bytes) -> EmailMessage:
    texto = (
        f"Resumo dos últimos {dias} dias ({quando:%d/%m/%Y}).\n\n"
        f"Variação do PIX por produto (maiores quedas primeiro):\n{linhas}\n\n"
        "A planilha em anexo traz todas as coletas do período, com o caminho do print.\n"
    )
    html = "<p>" + escape(texto).replace("\n", "<br>") + "</p>"
    msg = _mensagem(f"[SEARCHING] Resumo semanal ({quando:%d/%m/%Y})", remetente, destinatarios, texto, html)
    msg.add_attachment(
        excel, maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"searching_semana_{quando:%Y%m%d}.xlsx",
    )
    return msg


def construir_teste(remetente: str, destinatarios) -> EmailMessage:
    texto = "Este é um e-mail de teste do SEARCHING. Se você o recebeu, os alertas por e-mail estão configurados corretamente."
    html = f"<p>{escape(texto)}</p>"
    return _mensagem("[SEARCHING] E-mail de teste", remetente, destinatarios, texto, html)


def enviar_smtp(msg: EmailMessage, config: ConfigSMTP | None = None) -> None:
    """Envia pela conta do .env. Porta 465 usa SSL direto; as demais, STARTTLS."""
    cfg = config or carregar_config_smtp()
    contexto = ssl.create_default_context()
    if cfg.port == 465:
        servidor = smtplib.SMTP_SSL(cfg.host, cfg.port, context=contexto, timeout=30)
    else:
        servidor = smtplib.SMTP(cfg.host, cfg.port, timeout=30)
    with servidor:
        if cfg.port != 465:
            servidor.starttls(context=contexto)
        servidor.login(cfg.usuario, cfg.senha)
        servidor.send_message(msg)
