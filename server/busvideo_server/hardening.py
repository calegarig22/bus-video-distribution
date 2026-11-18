"""HTTP-level hardening: security headers, CSRF origin check and the HTTP→HTTPS redirect listener."""
from __future__ import annotations

import http.server
import logging
import threading
from pathlib import Path
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("busvideo.hardening")

# Only what the panel needs: own scripts/styles/images/media, no inline scripts, no third parties.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_JSON_BODY = 64 * 1024            # every route except the streaming video upload (which has its own limit)
STREAMING_PATHS = ("/api/video/upload",)


def _same_site(request: Request) -> bool:
    """CSRF defence for cookie sessions: a browser cross-site request always carries Origin/Sec-Fetch-Site."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True   # non-browser client (curl, scripts): the cookie itself is the credential
    host = request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() == host.lower()


def install(app, settings) -> None:
    @app.middleware("http")
    async def _hardening(request: Request, call_next):
        # 0. Body size: nothing but the video upload may send a large body (memory exhaustion by an unauthenticated
        #    client). A body without Content-Length (chunked) is refused too, since its size is unknown up front.
        if request.method in UNSAFE_METHODS and not request.url.path.startswith(STREAMING_PATHS):
            length = request.headers.get("content-length")
            if length is None and request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "Content-Length obrigatório"}, status_code=411)
            if length is not None and (not length.isdigit() or int(length) > MAX_JSON_BODY):
                return JSONResponse({"detail": "Corpo da requisição grande demais"}, status_code=413)
        # 1. CSRF: state-changing request authenticated by the session cookie must come from our own page.
        if (request.method in UNSAFE_METHODS and "busvideo_session" in request.cookies
                and not request.headers.get("authorization", "").lower().startswith("bearer ")
                and not _same_site(request)):
            log.warning("Blocked cross-site %s %s from origin=%r", request.method, request.url.path,
                        request.headers.get("origin"))
            return JSONResponse({"detail": "Origem não permitida"}, status_code=403)
        response = await call_next(request)
        # 2. Security headers on every response.
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if settings.tls_enabled:
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    https_port = 443
    ca_cert: Path | None = None
    server_version = "busvideo-redirect"
    sys_version = ""

    def log_message(self, *args):  # keep the console quiet
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/ca.crt" and self.ca_cert and self.ca_cert.exists():
            body = self.ca_cert.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="ca.crt"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        host = (self.headers.get("Host") or "localhost").split(":")[0]
        if not host or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for ch in host):
            host = "localhost"
        port = "" if self.https_port == 443 else f":{self.https_port}"
        self.send_response(301)
        self.send_header("Location", f"https://{host}{port}{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_HEAD = do_GET
    do_POST = do_GET


def start_http_redirect(host: str, http_port: int, https_port: int, ca_cert: Path | None) -> None:
    """Plain-HTTP helper listener: redirects to HTTPS and serves the public ca.crt. Never serves the app."""
    handler = type("RedirectHandler", (_RedirectHandler,), {"https_port": https_port, "ca_cert": ca_cert})
    try:
        srv = http.server.ThreadingHTTPServer((host, http_port), handler)
    except OSError as exc:
        log.warning("HTTP redirect listener not started on port %s: %s", http_port, exc)
        return
    threading.Thread(target=srv.serve_forever, name="http-redirect", daemon=True).start()
    log.info("HTTP redirect listener on %s:%s -> https (serves /ca.crt)", host, http_port)
