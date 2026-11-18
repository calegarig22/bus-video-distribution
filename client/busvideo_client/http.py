"""Tiny HTTP client over urllib with timeouts, bearer auth and Range support."""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request

from . import __version__


class HttpError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"HTTP {status} {message}".strip())
        self.status = status


class NetworkError(Exception):
    pass


def make_ssl_context(ca_cert: str = "") -> ssl.SSLContext:
    """TLS context that verifies the server. With ca_cert, ONLY the garage CA is trusted (pinning)."""
    if ca_cert:
        ctx = ssl.create_default_context(cafile=ca_cert)
    else:
        ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class HttpClient:
    def __init__(self, base_url: str, token: str = "", timeout: int = 30, ca_cert: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.ca_cert = ca_cert
        self.ssl_context = make_ssl_context(ca_cert) if self.base_url.lower().startswith("https://") else None

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": f"busvideo-client/{__version__}", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def _open(self, req: urllib.request.Request, timeout: int | None = None):
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout, context=self.ssl_context)
        except urllib.error.HTTPError as exc:
            raise HttpError(exc.code, exc.reason) from exc
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            raise NetworkError(str(getattr(exc, "reason", exc))) from exc

    def get_json(self, path: str, timeout: int | None = None):
        req = urllib.request.Request(self.base_url + path, headers=self._headers())
        with self._open(req, timeout) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict, timeout: int | None = None):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=body, method="POST",
                                     headers=self._headers({"Content-Type": "application/json"}))
        with self._open(req, timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else None

    def open_stream(self, path: str, start: int = 0, etag: str | None = None):
        """Open a streaming GET; returns the raw response (caller must close)."""
        extra = {"Accept": "*/*"}
        if start > 0:
            extra["Range"] = f"bytes={start}-"
            if etag:
                extra["If-Range"] = etag
        req = urllib.request.Request(self.base_url + path, headers=self._headers(extra))
        return self._open(req)
