"""Varredura de segurança básica do servidor Bus Video (as falhas simples e óbvias que um atacante testa primeiro).

Roda contra um servidor no ar e imprime PASS/FAIL por item. Não altera vídeos publicados: só faz login, envia
heartbeats de teste e tenta acessos que devem ser negados. Use na demo, no PC da garagem ou na bancada.

    .venv/bin/python demo/security_scan.py                                    # demo local (https://localhost:8443)
    .venv/bin/python demo/security_scan.py --server https://192.168.100.8 --ca-cert ca.crt --password SENHA --token TOKEN
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "client"))
from busvideo_client.config import load_env_file  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Http:
    def __init__(self, base: str, ca_cert: str):
        self.base = base.rstrip("/")
        self.ctx = None
        if self.base.startswith("https://"):
            self.ctx = ssl.create_default_context(cafile=ca_cert) if ca_cert else ssl.create_default_context()
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj),
                                                  urllib.request.HTTPSHandler(context=self.ctx))
        self.opener.addheaders = []

    def req(self, method: str, path: str, body=None, headers=None, raw=False):
        data = body if raw or body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/octet-stream" if raw else "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def tls_checks(base: str, ca_cert: str) -> None:
    u = urlsplit(base)
    if u.scheme != "https":
        check("HTTPS ligado", False, "servidor em HTTP: senha e token trafegam em claro")
        return
    host, port = u.hostname, u.port or 443
    # certificado verificado pela CA da garagem
    try:
        ctx = ssl.create_default_context(cafile=ca_cert) if ca_cert else ssl.create_default_context()
        with socket.create_connection((host, port), timeout=5) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            check("HTTPS: certificado válido para a CA informada", True, f"{t.version()} {t.cipher()[0]}")
            check("HTTPS: só TLS 1.2 ou superior negociado", t.version() in ("TLSv1.2", "TLSv1.3"), t.version())
    except Exception as exc:  # noqa: BLE001
        check("HTTPS: certificado válido para a CA informada", False, str(exc)[:80])
    # sem CA (confiança do sistema) deve falhar: prova que é a CA da garagem, não um certificado público qualquer
    try:
        with socket.create_connection((host, port), timeout=5) as s, ssl.create_default_context().wrap_socket(s, server_hostname=host):
            check("HTTPS: recusado sem a CA da garagem (sem confiança implícita)", False, "aceito pelo sistema")
    except ssl.SSLError:
        check("HTTPS: recusado sem a CA da garagem (sem confiança implícita)", True)
    except Exception as exc:  # noqa: BLE001
        check("HTTPS: recusado sem a CA da garagem (sem confiança implícita)", False, str(exc)[:60])
    # TLS 1.0/1.1 recusados
    import warnings
    for ver in (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1):
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ver; ctx.maximum_version = ver
            ctx.set_ciphers("ALL:@SECLEVEL=0")
            with socket.create_connection((host, port), timeout=5) as s, ctx.wrap_socket(s, server_hostname=host):
                check(f"TLS antigo recusado ({ver.name})", False, "aceito")
        except (ssl.SSLError, OSError, ValueError):
            check(f"TLS antigo recusado ({ver.name})", True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="https://localhost:8443")
    ap.add_argument("--ca-cert", default=str(ROOT / "demo/data/server/tls/ca.crt"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="demo")
    ap.add_argument("--token", default=None, help="DEVICE_TOKEN (padrão: demo/data/server.env)")
    a = ap.parse_args()
    if not Path(a.ca_cert).exists():
        a.ca_cert = ""
    token = a.token or load_env_file(ROOT / "demo/data/server.env").get("DEVICE_TOKEN", "")
    origin = f"{urlsplit(a.server).scheme}://{urlsplit(a.server).netloc}"
    print(f"Varredura em {a.server}\n")

    print("Transporte")
    tls_checks(a.server, a.ca_cert)

    print("\nAcesso sem credenciais")
    h = Http(a.server, a.ca_cert)
    for path in ("/api/devices", "/api/video/latest", "/api/video/download", "/api/auth/me"):
        st, _, _ = h.req("GET", path)
        check(f"GET {path} exige login/token", st == 401, f"HTTP {st}")
    st, _, _ = h.req("POST", "/api/video/upload", b"x", raw=True, headers={"X-Filename": "a.mp4"})
    check("upload sem login negado", st == 401, f"HTTP {st}")
    st, _, _ = h.req("POST", "/api/video/1/publish", {})
    check("publicar sem login negado", st == 401, f"HTTP {st}")
    st, _, _ = h.req("POST", "/api/devices/heartbeat", {"device_id": "X"}, headers={"Authorization": "Bearer errado"})
    check("heartbeat com token errado negado", st == 401, f"HTTP {st}")
    st, _, _ = h.req("GET", "/api/docs")
    check("Swagger/OpenAPI não exposto", st == 404, f"HTTP {st}")
    st, _, _ = h.req("GET", "/static/../config/server.env")
    check("path traversal em /static bloqueado", st in (400, 404), f"HTTP {st}")
    st, _, _ = h.req("GET", "/static/")
    check("listagem de /static bloqueada", st in (403, 404), f"HTTP {st}")
    st, hdr, _ = h.req("GET", "/login")
    check("cabeçalho Server não revela o software", "uvicorn" not in hdr.get("server", "").lower(), hdr.get("server", "ausente"))
    check("Content-Security-Policy presente sem inline", "unsafe-inline" not in hdr.get("content-security-policy", "") and "script-src 'self'" in hdr.get("content-security-policy", ""))
    check("X-Frame-Options DENY", hdr.get("x-frame-options") == "DENY")
    check("X-Content-Type-Options nosniff", hdr.get("x-content-type-options") == "nosniff")
    if a.server.startswith("https://"):
        check("HSTS presente", "strict-transport-security" in hdr)

    print("\nLogin")
    st, _, _ = h.req("POST", "/api/auth/login", {"username": a.user, "password": "senha-errada-xyz"})
    check("senha errada negada", st == 401, f"HTTP {st}")
    st, _, _ = h.req("POST", "/api/auth/login", b"{not json", raw=True, headers={"Content-Type": "application/json"})
    check("JSON inválido tratado (sem erro 500)", st == 400, f"HTTP {st}")

    print("\nSessão do operador")
    h2 = Http(a.server, a.ca_cert)
    st, hdr, _ = h2.req("POST", "/api/auth/login", {"username": a.user, "password": a.password})
    if st != 200:
        check("login com a senha informada", False, f"HTTP {st}; use --password")
        return finish()
    cookie = hdr.get("set-cookie", "").lower()
    check("cookie de sessão HttpOnly", "httponly" in cookie)
    check("cookie de sessão SameSite", "samesite" in cookie)
    if a.server.startswith("https://"):
        check("cookie de sessão Secure", "secure" in cookie)
    st, _, _ = h2.req("POST", "/api/auth/logout", headers={"Origin": "https://site-malicioso.example", "Sec-Fetch-Site": "cross-site"})
    check("CSRF: POST de outro site com o cookie é bloqueado", st == 403, f"HTTP {st}")
    st, _, _ = h2.req("GET", "/api/auth/me")
    check("sessão continua válida após o bloqueio", st == 200, f"HTTP {st}")
    # cookie forjado
    h3 = Http(a.server, a.ca_cert)
    st, _, _ = h3.req("GET", "/api/devices", headers={"Cookie": "busvideo_session=eyJ1c2VyIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJleHAiOjk5OTk5OTk5OTl9.AAAA"})
    check("cookie forjado (assinatura inválida) rejeitado", st == 401, f"HTTP {st}")

    print("\nDispositivos")
    if token:
        hb = {"device_id": "SCAN-XSS", "current_version": 0, "status": "error", "ip": "8.8.8.8",
              "last_error": "<img src=x onerror=alert('xss')>\r\nlinha falsa", "hostname": "scan"}
        st, _, _ = h2.req("POST", "/api/devices/heartbeat", hb, headers={"Authorization": f"Bearer {token}"})
        st2, _, body = h2.req("GET", "/api/devices/SCAN-XSS")
        d = json.loads(body) if st2 == 200 else {}
        check("IP informado pelo dispositivo é ignorado (usa o observado)", d.get("ip") not in (None, "8.8.8.8"), str(d.get("ip")))
        check("texto do dispositivo sem quebras de linha/controle", "\n" not in d.get("last_error", "") and "\r" not in d.get("last_error", ""))
        st, _, _ = h2.req("POST", "/api/devices/heartbeat", {"device_id": "../../x"}, headers={"Authorization": f"Bearer {token}"})
        check("device_id inválido rejeitado", st == 400, f"HTTP {st}")
        st, _, _ = h2.req("POST", "/api/devices/heartbeat", {"device_id": "SCAN-1", "current_version": "abc"}, headers={"Authorization": f"Bearer {token}"})
        check("tipos inválidos no heartbeat não derrubam o servidor", st in (200, 400), f"HTTP {st}")
    else:
        print("  (sem DEVICE_TOKEN: testes de dispositivo pulados; passe --token)")

    print("\nDownload")
    st, _, _ = h2.req("GET", "/api/video/download", headers={"Range": "bytes=abc"})
    check("Range malformado tratado", st in (404, 416, 200, 206), f"HTTP {st}")
    st, _, _ = h2.req("GET", "/api/video/download", headers={"Range": "bytes=99999999999-"})
    check("Range fora do arquivo tratado", st in (404, 416), f"HTTP {st}")

    if token:
        for dev_id in ("SCAN-XSS", "SCAN-1"):
            h2.req("DELETE", f"/api/devices/{dev_id}")
        st, _, _ = h2.req("GET", "/api/devices/SCAN-XSS")
        check("dispositivos de teste removidos da lista", st == 404, f"HTTP {st}")

    print("\nForça bruta  (por último: bloqueia este IP por 1 minuto)")
    codes = [h.req("POST", "/api/auth/login", {"username": a.user, "password": "errada"})[0] for _ in range(6)]
    check("limite de tentativas de login (429 após 5 erros)", 429 in codes, str(codes))
    return finish()


def finish() -> int:
    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(fails)} de {len(RESULTS)} verificações passaram.")
    if fails:
        print("Falhas: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
