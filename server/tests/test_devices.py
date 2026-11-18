

def hb(client, headers, **kw):
    payload = {"device_id": "BUS-001", "hostname": "bus001", "current_version": 1, "sha256": "abc",
               "app_version": "0.1.0", "free_space_mb": 10000, "uptime_s": 100, "status": "ok"}
    payload.update(kw)
    return client.post("/api/devices/heartbeat", json=payload, headers=headers)


def test_heartbeat_requires_token(client):
    assert client.post("/api/devices/heartbeat", json={"device_id": "BUS-001"}).status_code == 401


def test_heartbeat_and_status(upload, admin, device_headers, videos):
    r = hb(admin, device_headers, current_version=0)
    assert r.status_code == 200 and r.json()["published_version"] is None
    devs = admin.get("/api/devices").json()
    assert len(devs) == 1 and devs[0]["device_id"] == "BUS-001" and devs[0]["status"] == "updated"

    v = upload(admin, videos["ok"]).json()
    admin.post(f"/api/video/{v['id']}/publish")
    devs = admin.get("/api/devices").json()
    assert devs[0]["status"] == "pending"
    hb(admin, device_headers, current_version=1)
    assert admin.get("/api/devices/BUS-001/status").json()["status"] == "updated"

    hb(admin, device_headers, status="downloading")
    assert admin.get("/api/devices/BUS-001").json()["status"] == "downloading"
    hb(admin, device_headers, status="error", last_error="SHA256 mismatch")
    d = admin.get("/api/devices/BUS-001").json()
    assert d["status"] == "error" and d["last_error"] == "SHA256 mismatch"
    assert any("SHA256" in e["message"] for e in d["events"])


def test_invalid_device_id(admin, device_headers):
    assert hb(admin, device_headers, device_id="../x").status_code == 400
    assert hb(admin, device_headers, device_id="").status_code == 400


def test_offline_derivation(admin, device_headers, app):
    hb(admin, device_headers)
    app.state.devices.offline_after_s = -1
    assert admin.get("/api/devices").json()[0]["status"] == "offline"


def test_unknown_device(admin):
    assert admin.get("/api/devices/BUS-999").status_code == 404


def test_admin_can_remove_device_from_list(admin, client, device_headers):
    hb = {"device_id": "BUS-OLD", "current_version": 1, "status": "ok"}
    assert client.post("/api/devices/heartbeat", json=hb, headers=device_headers).status_code == 200
    assert admin.get("/api/devices/BUS-OLD").status_code == 200
    # the bus itself (token only, no session) cannot remove entries
    from fastapi.testclient import TestClient
    anon = TestClient(client.app)
    assert anon.delete("/api/devices/BUS-OLD", headers=device_headers).status_code == 401
    r = admin.delete("/api/devices/BUS-OLD")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert admin.get("/api/devices/BUS-OLD").status_code == 404
    assert admin.delete("/api/devices/BUS-OLD").status_code == 404
    # a live bus comes back on its next heartbeat
    assert client.post("/api/devices/heartbeat", json=hb, headers=device_headers).status_code == 200
    assert admin.get("/api/devices/BUS-OLD").status_code == 200


def test_download_progress_shows_while_downloading(admin, client, device_headers):
    hb = {"device_id": "BUS-DL", "current_version": 1, "status": "downloading", "progress": 45}
    assert client.post("/api/devices/heartbeat", json=hb, headers=device_headers).status_code == 200
    # a published version newer than the bus makes it "downloading" (it reported so)
    d = admin.get("/api/devices/BUS-DL").json()
    assert d["status"] == "downloading" and d["progress"] == 45
    hb.update(status="ok", progress=None)
    client.post("/api/devices/heartbeat", json=hb, headers=device_headers)
    assert admin.get("/api/devices/BUS-DL").json()["progress"] is None
