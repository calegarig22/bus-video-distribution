"""Network presence and server discovery (cascade of configured URLs)."""
from __future__ import annotations

import logging
import socket
from urllib.parse import urlparse

from .http import HttpClient, HttpError, NetworkError

log = logging.getLogger("busvideo.net")


def local_ip_towards(host: str, port: int = 80) -> str | None:
    """Local IP that would be used to reach host (no packet is sent for UDP connect)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            s.connect((host, port))
            return s.getsockname()[0]
    except OSError:
        return None


def has_network(urls: list[str]) -> bool:
    for url in urls:
        p = urlparse(url)
        if p.hostname and local_ip_towards(p.hostname, p.port or 80):
            return True
    return False


def discover(urls: list[str], token: str, timeout: int = 3, preferred: str | None = None, ca_cert: str = "",
             allow_insecure_http: bool = False):
    """Return (base_url, health_json) for the first server answering /api/health.

    Plain http:// servers are ignored unless allow_insecure_http: on a real bus the token must never be sent
    to a server that did not prove, with the garage CA, that it is the garage.
    """
    order = [u for u in urls if allow_insecure_http or u.lower().startswith("https://")]
    if not order:
        return None, "nenhum servidor https:// configurado (ALLOW_INSECURE_HTTP=false)"
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    last_error = None
    for url in order:
        client = HttpClient(url, token, timeout, ca_cert)
        try:
            health = client.get_json("/api/health", timeout=timeout)
            if isinstance(health, dict) and health.get("status") == "ok":
                return url, health
            last_error = f"{url}: resposta inesperada"
        except HttpError as exc:
            last_error = f"{url}: {exc}"
        except NetworkError as exc:
            last_error = f"{url}: {exc}"
    return None, last_error
