"""Real server over HTTPS (garage CA) + real bus client: pinned CA works, anything else is refused."""
import shutil
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from busvideo_client.config import ClientConfig
from busvideo_client.sync import SyncAgent
from busvideo_server import tls
from busvideo_server.config import MediaPolicy, Settings
from busvideo_server.main import create_app
from busvideo_server.security import hash_password

ADMIN_PW = "demo"
TOKEN = "integration-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TlsServer:
    def __init__(self, tmp_path):
        self.certs = tls.generate(tmp_path / "tls", ips=["127.0.0.1"], dns_names=["localhost"])
        self.settings = Settings(
            data_dir=tmp_path / "srv" / "data", log_dir=tmp_path / "srv" / "logs",
            admin_password_hash=hash_password(ADMIN_PW, iterations=1000), secret_key="s", device_token=TOKEN,
            ffprobe_bin=shutil.which("ffprobe") or "ffprobe", media=MediaPolicy(max_size_mb=50),
            host="127.0.0.1", port=_free_port(),
            tls_cert=self.certs["server_crt"], tls_key=self.certs["server_key"],
        )
        config = uvicorn.Config(create_app(self.settings), host="127.0.0.1", port=self.settings.port,
                                log_level="warning", ssl_certfile=self.settings.tls_cert,
                                ssl_keyfile=self.settings.tls_key)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"https://127.0.0.1:{self.settings.port}"

    def start(self):
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if httpx.get(self.url + "/api/health", timeout=1, verify=self.certs["ca_crt"]).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("tls server did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def tls_live(tmp_path):
    s = TlsServer(tmp_path).start()
    yield s
    s.stop()


def _agent(tmp_path, url, token, ca_cert, name):
    cfg = ClientConfig(device_id=name, server_urls=[url], device_token=token, base_dir=tmp_path / name,
                       player="fake", validate_format="off", disk_margin_mb=0, health_timeout=3, ca_cert=ca_cert)
    cfg.ensure_dirs()
    return SyncAgent(cfg)


def test_bus_with_pinned_ca_syncs_over_https(tls_live, tmp_path, monkeypatch, video_maker):
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    admin = httpx.Client(base_url=tls_live.url, verify=tls_live.certs["ca_crt"], timeout=30)
    r = admin.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()
    v1 = video_maker(tmp_path / "v1.mp4", 2, "green")
    r = admin.post("/api/video/upload", content=v1.read_bytes(), headers={"X-Filename": "v1.mp4"})
    assert r.status_code == 200, r.text
    assert admin.post(f"/api/video/{r.json()['id']}/publish").status_code == 200

    agent = _agent(tmp_path, tls_live.url, TOKEN, tls_live.certs["ca_crt"], "BUS-TLS")
    assert agent.run_once() == "updated"
    assert agent.state.current_version == 1
    assert admin.get("/api/devices").json()[0]["device_id"] == "BUS-TLS"
    # the public CA download works over HTTPS too
    assert b"BEGIN CERTIFICATE" in admin.get("/ca.crt").content


def test_bus_without_ca_refuses_server(tls_live, tmp_path, monkeypatch):
    """No CA_CERT: the system trust store does not know the garage CA, so the bus must not talk to it."""
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    agent = _agent(tmp_path, tls_live.url, TOKEN, "", "BUS-NOCA")
    assert agent.run_once() == "no-server"
    assert "CERTIFICATE_VERIFY_FAILED" in (agent.state.last_error or "") or agent.state.current_version == 0


def test_bus_with_wrong_ca_refuses_server(tls_live, tmp_path, monkeypatch):
    """A different CA (an attacker's) is not accepted either."""
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    other = tls.generate(tmp_path / "other-ca", ips=["127.0.0.1"])
    agent = _agent(tmp_path, tls_live.url, TOKEN, other["ca_crt"], "BUS-WRONGCA")
    assert agent.run_once() == "no-server"
    assert agent.state.current_version == 0
