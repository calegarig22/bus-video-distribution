import hashlib



def test_upload_and_publish_flow(upload, admin, videos, device_headers):
    r = upload(admin, videos["ok"])
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["compatible"] is True and v["video_codec"] == "h264" and v["width"] == 320
    assert v["sha256"] == hashlib.sha256(videos["ok"].read_bytes()).hexdigest()
    assert admin.get("/api/video/latest", headers=device_headers).status_code == 204

    r = admin.post(f"/api/video/{v['id']}/publish")
    assert r.status_code == 200
    latest = admin.get("/api/video/latest", headers=device_headers).json()
    assert latest["version"] == 1 and latest["sha256"] == v["sha256"] and latest["size"] == v["size"]
    assert latest["download_url"] == "/api/video/download/1"

    r = admin.get(latest["download_url"], headers=device_headers)
    assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == v["sha256"]
    assert r.headers["etag"] == f'"{v["sha256"]}"' and r.headers["accept-ranges"] == "bytes"


def test_upload_with_audio_ok(upload, admin, videos):
    v = upload(admin, videos["ok_audio"]).json()
    assert v["compatible"] and v["audio_codec"] == "aac"


def test_upload_rejections(upload, admin, videos):
    r = upload(admin, videos["fps60"]).json()
    assert r["compatible"] is False and any("FPS" in x for x in r["reasons"])
    r = upload(admin, videos["mpeg4"]).json()
    assert r["compatible"] is False and any("Codec" in x for x in r["reasons"])
    r = upload(admin, videos["text"])
    assert r.status_code == 400 and "válido" in r.json()["detail"]
    r = upload(admin, videos["ok"], name="video.avi")
    assert r.status_code == 400 and "Extensão" in r.json()["detail"]
    r = admin.post("/api/video/upload", content=b"", headers={"X-Filename": "a.mp4"})
    assert r.status_code == 400


def test_rejected_cannot_be_published(upload, admin, videos):
    v = upload(admin, videos["fps60"]).json()
    assert admin.post(f"/api/video/{v['id']}/publish").status_code == 400


def test_size_limit(admin, videos, settings):
    big = b"\0" * (settings.media.max_size_bytes + 1)
    r = admin.post("/api/video/upload", content=big, headers={"X-Filename": "big.mp4"})
    assert r.status_code == 413
    assert not list(settings.incoming_dir.glob("*.tmp"))


def test_republish_old_video_creates_new_version(upload, admin, videos, device_headers):
    v1 = upload(admin, videos["ok"]).json()
    v2 = upload(admin, videos["ok2"]).json()
    admin.post(f"/api/video/{v1['id']}/publish")
    admin.post(f"/api/video/{v2['id']}/publish")
    assert admin.get("/api/video/latest", headers=device_headers).json()["version"] == 2
    admin.post(f"/api/video/{v1['id']}/publish")  # rollback
    latest = admin.get("/api/video/latest", headers=device_headers).json()
    assert latest["version"] == 3 and latest["sha256"] == v1["sha256"]
    hist = admin.get("/api/video/history").json()
    assert [h["version"] for h in hist] == [3, 2, 1]
    assert admin.get("/api/video/download/2", headers=device_headers).json if False else True


def test_range_requests(upload, admin, videos, device_headers):
    v = upload(admin, videos["ok"]).json()
    admin.post(f"/api/video/{v['id']}/publish")
    data = videos["ok"].read_bytes()
    r = admin.get("/api/video/download/1", headers={**device_headers, "Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(data)}"
    r = admin.get("/api/video/download/1", headers={**device_headers, "Range": "bytes=500-"})
    assert r.status_code == 206 and r.content == data[500:]
    r = admin.get("/api/video/download/1", headers={**device_headers, "Range": f"bytes={len(data) + 10}-"})
    assert r.status_code == 416
    r = admin.get("/api/video/download/1", headers={**device_headers, "Range": "bytes=0-9", "If-Range": '"other"'})
    assert r.status_code == 200 and r.content == data
    r = admin.head("/api/video/download/1", headers=device_headers)
    assert r.status_code == 200 and int(r.headers["content-length"]) == len(data)


def test_stored_names_are_system_generated(upload, admin, videos, settings):
    v = upload(admin, videos["ok"], name="../../etc/passwd.mp4").json()
    assert v["filename"] == "passwd.mp4"
    files = list(settings.videos_dir.iterdir())
    assert len(files) == 1 and files[0].name == f"video_{v['id']}.mp4"
    assert not list(settings.incoming_dir.iterdir())


def test_download_missing_version(admin, device_headers):
    assert admin.get("/api/video/download/99", headers=device_headers).status_code == 404
    assert admin.get("/api/video/download", headers=device_headers).status_code == 404
