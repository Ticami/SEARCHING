"""Gestão de contas pela linha de comando (a senha nunca é aceita como argumento).

Uso (a partir de backend/):
  python -m searching.usuarios criar-admin --email voce@exemplo.com [--nome "Seu Nome"]
  python -m searching.usuarios criar --email x@y.com --papel coletor|leitor|admin
  python -m searching.usuarios listar
  python -m searching.usuarios redefinir-senha --email x@y.com
  python -m searching.usuarios desativar-2fa --email x@y.com
  python -m searching.usuarios desbloquear --email x@y.com
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from .auth import servico
from .db.models import Usuario
from .db.session import criar_engine, iniciar_banco


def _pedir_senha(ler=getpass.getpass) -> str:
    senha = ler("Senha (mínimo 12 caracteres): ")
    if senha != ler("Repita a senha: "):
        raise servico.ErroAuth("As senhas não conferem.")
    return senha


def main(argv: list[str] | None = None, fabrica=None, ler_senha=getpass.getpass, saida=print) -> int:
    ap = argparse.ArgumentParser(prog="searching.usuarios", description="Gestão de contas do SEARCHING.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("criar-admin", "criar"):
        p = sub.add_parser(nome)
        p.add_argument("--email", required=True)
        p.add_argument("--nome", default="")
        if nome == "criar":
            p.add_argument("--papel", choices=servico.PAPEIS, default="leitor")
    for nome in ("redefinir-senha", "desativar-2fa", "desbloquear"):
        sub.add_parser(nome).add_argument("--email", required=True)
    sub.add_parser("listar")
    args = ap.parse_args(argv)

    fabrica = fabrica or iniciar_banco(criar_engine())
    with fabrica() as s:
        try:
            if args.cmd == "listar":
                for u in s.scalars(select(Usuario).order_by(Usuario.id)):
                    saida(f"{u.id}\t{u.email}\t{u.papel}\t{'ativo' if u.ativo else 'inativo'}\t2FA={'sim' if u.totp_ativo else 'não'}")
                return 0
            if args.cmd in ("criar-admin", "criar"):
                papel = "admin" if args.cmd == "criar-admin" else args.papel
                u = servico.criar_usuario(s, args.email, args.nome, papel, _pedir_senha(ler_senha))
                servico.auditar(s, "usuario_criado_cli", alvo=u.email, detalhe={"papel": papel})
                s.commit()
                saida(f"Usuário {u.email} criado como {papel}.")
                return 0
            u = s.scalar(select(Usuario).where(Usuario.email == servico.normalizar_email(args.email)))
            if u is None:
                raise servico.ErroAuth("Usuário não encontrado.", 404)
            if args.cmd == "redefinir-senha":
                from .auth import senhas

                nova = _pedir_senha(ler_senha)
                senhas.validar_politica(nova, u.email)
                u.senha_hash, u.deve_trocar_senha, u.falhas_login, u.bloqueado_ate = senhas.gerar_hash(nova), False, 0, None
                servico.revogar_sessoes_do_usuario(s, u.id)
            elif args.cmd == "desativar-2fa":
                u.totp_ativo, u.totp_segredo = False, None
            else:
                u.falhas_login, u.bloqueado_ate = 0, None
            servico.auditar(s, f"cli_{args.cmd.replace('-', '_')}", alvo=u.email)
            s.commit()
            saida("Feito.")
            return 0
        except (servico.ErroAuth, ValueError) as e:
            saida(f"Erro: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
