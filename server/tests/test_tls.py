"""TLS certificates, security headers, CSRF origin check and cookie flags."""
import ssl

import pytest
from fastapi.testclient import TestClient

from busvideo_server import tls
from busvideo_server.config import MediaPolicy, Settings
from busvideo_server.main import create_app
from busvideo_server.security import hash_password

ADMIN_PW = "senha-teste"
TOKEN = "device-token-test"


def test_gen_cert_creates_ca_and_server_cert(tmp_path):
    out = tmp_path / "tls"
    r = tls.generate(out, ips=["192.168.100.10"], dns_names=["garagem-busvideo"])
    assert not r["reused_ca"]
    for name in ("ca.crt", "ca.key", "server.crt", "server.key"):
        assert (out / name).exists()
    info = tls.info(out / "server.crt")
    assert set(info["san"]) >= {"192.168.100.10", "127.0.0.1", "garagem-busvideo", "localhost"}
    assert "Garagem CA" in info["issuer"]
    # the chain verifies with the standard library (what the bus client uses)
    ctx = ssl.create_default_context(cafile=str(out / "ca.crt"))
    ctx.load_verify_locations(cafile=str(out / "ca.crt"))
    assert ctx.cert_store_stats()["x509_ca"] == 1


def test_gen_cert_reuses_ca_when_renewing(tmp_path):
    out = tmp_path / "tls"
    first = tls.generate(out, ips=["10.0.0.1"])
    ca_before = (out / "ca.crt").read_bytes()
    second = tls.generate(out, ips=["10.0.0.2"])     # IP changed: new server cert, same CA
    assert second["reused_ca"] and (out / "ca.crt").read_bytes() == ca_before
    assert "10.0.0.2" in tls.info(out / "server.crt")["san"]
    assert first["server_crt"] == second["server_crt"]


def _settings(tmp_path, **kw) -> Settings:
    return Settings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs", admin_user="admin",
                    admin_password_hash=hash_password(ADMIN_PW, iterations=1000), secret_key="s",
                    device_token=TOKEN, media=MediaPolicy(max_size_mb=5), **kw)


def test_tls_settings_and_ca_route(tmp_path):
    out = tmp_path / "tls"
    tls.generate(out, ips=["10.0.0.1"])
    s = _settings(tmp_path, tls_cert=str(out / "server.crt"), tls_key=str(out / "server.key"))
    assert s.tls_enabled and s.ca_cert_path == out / "ca.crt"
    c = TestClient(create_app(s))
    r = c.get("/ca.crt")
    assert r.status_code == 200 and b"BEGIN CERTIFICATE" in r.content
    assert r.headers["strict-transport-security"].startswith("max-age=")
    login = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert login.status_code == 200
    assert "secure" in login.headers["set-cookie"].lower()


def test_no_tls_means_no_hsts_and_no_ca(tmp_path):
    s = _settings(tmp_path)
    assert not s.tls_enabled and s.ca_cert_path is None
    c = TestClient(create_app(s))
    r = c.get("/ca.crt", follow_redirects=False)
    assert r.status_code == 302
    assert "strict-transport-security" not in c.get("/api/health").headers
    login = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert "secure" not in login.headers["set-cookie"].lower()


def test_security_headers(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    h = c.get("/login").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "script-src 'self'" in h["content-security-policy"]
    assert "unsafe-inline" not in h["content-security-policy"]
    assert c.get("/api/health").headers["cache-control"] == "no-store"
    assert "server" not in {k.lower() for k in h.keys()} or h.get("server") != "uvicorn"
    assert c.get("/api/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_csrf_origin_check(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 200
    # same-origin browser request: allowed
    r = c.post("/api/auth/logout", headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 200
    # cross-site browser request carrying the cookie: blocked
    r = c.post("/api/auth/logout", headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/auth/logout", headers={"Referer": "http://evil.example/x"})
    assert r.status_code == 403
    # still logged in (logout was blocked)
    assert c.get("/api/auth/me").status_code == 200
    # device (bearer) requests are not subject to the origin check
    r = c.post("/api/devices/heartbeat", json={"device_id": "BUS-1", "current_version": 0, "status": "pending"},
               headers={"Authorization": f"Bearer {TOKEN}", "Origin": "http://evil.example"})
    assert r.status_code == 200


def test_server_cert_validity_and_auto_renewal(tmp_path):
    out = tmp_path / "tls"
    r = tls.generate(out, ips=["10.0.0.1"])
    assert 700 <= tls.days_left(out / "server.crt") <= 730       # Apple/Chrome accept <= 825 days
    assert not tls.renew_if_needed(r["server_crt"], r["server_key"])   # far from expiry: untouched
    tls.generate(out, ips=["10.0.0.1"], dns_names=["garagem"], server_days=10)   # about to expire
    assert tls.renew_if_needed(r["server_crt"], r["server_key"])
    assert tls.days_left(out / "server.crt") > 700
    assert set(tls.info(out / "server.crt")["san"]) >= {"10.0.0.1", "garagem"}   # same names, same CA


def test_device_text_is_sanitized_and_ip_is_observed(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    hb = {"device_id": "BUS-9", "current_version": 1, "status": "error", "ip": "8.8.8.8",
          "last_error": "<img src=x onerror=alert(1)>\r\nfake log line\x00\x1b[31m", "hostname": "h\nost"}
    r = c.post("/api/devices/heartbeat", json=hb, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    d = c.get("/api/devices/BUS-9").json()
    assert d["ip"] != "8.8.8.8"                       # reported IP is ignored; the connection's IP is stored
    assert "\n" not in d["last_error"] and "\x00" not in d["last_error"] and "\x1b" not in d["last_error"]
    assert d["last_error"].startswith("<img src=x onerror=alert(1)>fake log line")   # kept as text, rendered as text by the panel
    assert d["hostname"] == "host"
    bad = c.post("/api/devices/heartbeat", json={"device_id": "../etc/passwd"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert bad.status_code == 400


def test_device_token_cannot_change_the_video(tmp_path):
    """A bus (or anyone holding the shared device token) can only report; never upload, publish or list."""
    c = TestClient(create_app(_settings(tmp_path)))
    dev = {"Authorization": f"Bearer {TOKEN}"}
    assert c.post("/api/video/upload", content=b"x", headers={**dev, "X-Filename": "a.mp4"}).status_code == 401
    assert c.post("/api/video/1/publish", headers=dev).status_code == 401
    assert c.get("/api/devices", headers=dev).status_code == 401
    assert c.get("/api/video/history", headers=dev).status_code == 401
    assert c.get("/api/video/latest", headers=dev).status_code in (200, 204)   # reading is allowed


def test_logout_revokes_session_server_side(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    token = r.cookies.get("busvideo_session")
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    stolen = TestClient(c.app)
    assert stolen.get("/api/auth/me", headers={"Cookie": f"busvideo_session={token}"}).status_code == 401
    # a fresh login still works
    assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_oversized_json_body_is_rejected_before_reading(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    big = b'{"username":"admin","password":"' + b"A" * (200 * 1024) + b'"}'
    r = c.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    def chunks():
        yield b'{"a":'
        yield b'1}'
    r = c.post("/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"})   # chunked, no length
    assert r.status_code == 411
    # the video upload keeps its own (large) limit: a 200 KB body is not refused by this rule
    c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    r = c.post("/api/video/upload", content=b"x" * (200 * 1024), headers={"X-Filename": "a.mp4"})
    assert r.status_code != 413


def test_huge_integer_in_heartbeat_is_not_a_server_error(tmp_path):
    c = TestClient(create_app(_settings(tmp_path)))
    r = c.post("/api/devices/heartbeat", json={"device_id": "BUS-BIG", "current_version": 10 ** 30, "free_space_mb": -(10 ** 40)},
               headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
