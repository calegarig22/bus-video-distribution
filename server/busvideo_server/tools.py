"""Small CLI: python -m busvideo_server.tools hash-password | gen-token | gen-env SENHA_OPERADOR [SENHA_ADMIN]
                                 | set-password USUARIO [SENHA] | gen-cert --out DIR [--ip A] [--dns N]

set-password: redefine no banco a senha de uma conta do painel (operador ou admin). É o caminho de recuperação
quando o próprio administrador esqueceu a senha; roda no PC do servidor com BUSVIDEO_SERVER_ENV apontando para o
server.env (o iniciar.bat / systemd já fazem isso)."""
from __future__ import annotations

import getpass
import secrets
import sys

from .security import hash_password


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "hash-password":
        pw = argv[1] if len(argv) > 1 else getpass.getpass("Senha do administrador: ")
        print(hash_password(pw))
        return 0
    if cmd == "gen-token":
        print(secrets.token_urlsafe(32))
        return 0
    if cmd == "gen-env":
        op_pw = argv[1] if len(argv) > 1 else getpass.getpass("Senha do operador (uso diário): ")
        adm_pw = argv[2] if len(argv) > 2 else getpass.getpass("Senha do administrador (suporte): ")
        print("OPERATOR_USER=operador")
        print(f"OPERATOR_PASSWORD_HASH={hash_password(op_pw)}")
        print("ADMIN_USER=admin")
        print(f"ADMIN_PASSWORD_HASH={hash_password(adm_pw)}")
        print(f"SECRET_KEY={secrets.token_urlsafe(32)}")
        print(f"DEVICE_TOKEN={secrets.token_urlsafe(32)}")
        return 0
    if cmd == "set-password":
        if len(argv) < 2:
            print("uso: set-password USUARIO [SENHA]", file=sys.stderr)
            return 2
        user = argv[1]
        pw = argv[2] if len(argv) > 2 else getpass.getpass(f"Nova senha de {user}: ")
        from .auth import seed_users, set_password
        from .config import load_settings
        from .db import Database
        settings = load_settings()
        db = Database(settings.db_path)
        seed_users(db, settings)
        try:
            set_password(db, user, pw)
        except KeyError:
            print(f"usuário desconhecido: {user} (contas: {settings.operator_user}, {settings.admin_user})", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Senha de {user} redefinida em {settings.db_path}. Vale imediatamente, sem reiniciar o servidor.")
        return 0
    if cmd == "gen-cert":
        import argparse
        from pathlib import Path

        from . import tls
        ap = argparse.ArgumentParser(prog="busvideo_server.tools gen-cert",
                                     description="Cria a CA da garagem (uma vez) e emite o certificado do servidor")
        ap.add_argument("--out", required=True, help="pasta de saída (ex.: /opt/busvideo-server/config/tls)")
        ap.add_argument("--ip", action="append", default=[], help="IP do servidor (repetível; padrão: IPs locais)")
        ap.add_argument("--dns", action="append", default=[], help="nome DNS do servidor (repetível)")
        ap.add_argument("--org", default="Bus Video")
        a = ap.parse_args(argv[1:])
        ips = a.ip or tls.local_ips()
        dns = a.dns or [__import__("socket").gethostname()]
        r = tls.generate(Path(a.out), ips, dns, org=a.org)
        print(f"CA        : {r['ca_crt']} ({'reutilizada' if r['reused_ca'] else 'nova'}; válida até {r['ca_expires']})")
        print(f"Servidor  : {r['server_crt']} (válido até {r['server_expires']})")
        print(f"Chave     : {r['server_key']}")
        print(f"Endereços : {', '.join(r['ips'] + r['dns'])}")
        return 0
    print(f"comando desconhecido: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
