"""Server v1 → bus v1 → server receives v2 → bus detects, downloads, validates, switches → player plays v2."""
import hashlib
import json

from busvideo_client.config import ClientConfig
from busvideo_client.player.fake import FakePlayer
from busvideo_client.supervisor import Supervisor
from busvideo_client.sync import SyncAgent



def upload_and_publish(admin, path):
    r = admin.post("/api/video/upload", content=path.read_bytes(), headers={"X-Filename": path.name})
    assert r.status_code == 200 and r.json()["compatible"], r.text
    r = admin.post(f"/api/video/{r.json()['id']}/publish")
    assert r.status_code == 200
    return r.json()


def test_end_to_end_update(live, tmp_path, monkeypatch, token, video_maker):
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    admin = live.admin()
    v1 = video_maker(tmp_path / "campanha_v1.mp4", 2, "red")
    v2 = video_maker(tmp_path / "campanha_v2.mp4", 3, "blue")

    # Server publishes version 1
    pub1 = upload_and_publish(admin, v1)
    assert pub1["version"] == 1

    # Bus boots: sync gets v1, player starts playing it
    cfg = ClientConfig(device_id="BUS-001", server_urls=["http://10.255.255.1:9", live.url], device_token=token, allow_insecure_http=True,
                       base_dir=tmp_path / "bus", player="fake", validate_format="auto", disk_margin_mb=0,
                       switch_mode="immediate", health_timeout=2)
    cfg.ensure_dirs()
    agent = SyncAgent(cfg)
    player = FakePlayer(loop_seconds=2)
    sup = Supervisor(cfg, player=player)
    sup.step()
    assert sup.playing is None  # nothing yet
    assert agent.run_once() == "updated"
    sup.step()
    assert sup.playing.name == "video_v1.mp4"
    assert hashlib.sha256(sup.playing.read_bytes()).hexdigest() == pub1["sha256"]

    devices = admin.get("/api/devices").json()
    assert devices[0]["device_id"] == "BUS-001" and devices[0]["status"] == "updated" and devices[0]["current_version"] == 1

    # Operator publishes version 2
    pub2 = upload_and_publish(admin, v2)
    assert pub2["version"] == 2
    assert admin.get("/api/devices").json()[0]["status"] == "pending"

    # Bus enters the garage again: detects, downloads, validates, switches
    assert agent.run_once() == "updated"
    state = json.loads(cfg.state_file.read_text())
    assert state["current_version"] == 2 and state["sha256"] == pub2["sha256"] and state["status"] == "ok"
    sup.step()
    assert sup.playing.name == "video_v2.mp4" and player.loads[-1].name == "video_v2.mp4"
    assert hashlib.sha256(sup.playing.read_bytes()).hexdigest() == pub2["sha256"]
    assert sorted(p.name for p in cfg.versions_dir.iterdir()) == ["video_v1.mp4", "video_v2.mp4"]
    assert not (cfg.download_dir / "video.tmp").exists()

    d = admin.get("/api/devices/BUS-001").json()
    assert d["status"] == "updated" and d["current_version"] == 2
    assert any("versão 2" in e["message"] for e in d["events"])

    # Server goes away: bus keeps playing v2
    live.stop()
    assert agent.run_once() in ("no-server", "no-network")
    sup.step()
    assert player.is_alive() and sup.playing.name == "video_v2.mp4"


def test_end_to_end_interrupted_download(live, tmp_path, monkeypatch, token, video_maker):
    """Wi-Fi drops mid-download: old video keeps playing; download resumes and completes later."""
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    admin = live.admin()
    upload_and_publish(admin, video_maker(tmp_path / "v1.mp4", 2, "green"))
    cfg = ClientConfig(device_id="BUS-002", server_urls=[live.url], device_token=token, base_dir=tmp_path / "bus", allow_insecure_http=True,
                       player="fake", validate_format="auto", disk_margin_mb=0, switch_mode="immediate",
                       chunk_size=256, health_timeout=2)
    cfg.ensure_dirs()
    agent = SyncAgent(cfg)
    player = FakePlayer()
    sup = Supervisor(cfg, player=player)
    assert agent.run_once() == "updated"
    sup.step()
    assert sup.playing.name == "video_v1.mp4"

    upload_and_publish(admin, video_maker(tmp_path / "v2.mp4", 6, "yellow"))
    # Inject a network failure after the first chunks are written.
    from busvideo_client import download as dl
    original_read = None
    calls = {"n": 0}

    class Cutter:
        def __init__(self, resp):
            self.resp = resp
        def __enter__(self):
            return self
        def __exit__(self, *a):
            self.resp.close()
        @property
        def status(self):
            return self.resp.status
        @property
        def headers(self):
            return self.resp.headers
        def read(self, n):
            calls["n"] += 1
            if calls["n"] > 3:
                raise ConnectionResetError("wifi lost")
            return self.resp.read(n)

    real_open = agent.downloader.__class__.download
    from busvideo_client.http import HttpClient
    orig_open_stream = HttpClient.open_stream

    def cut_open_stream(self, path, start=0, etag=None):
        resp = orig_open_stream(self, path, start, etag)
        return Cutter(resp) if calls["n"] == 0 else resp
    monkeypatch.setattr(HttpClient, "open_stream", cut_open_stream)
    assert agent.run_once() == "failed"
    partial = (cfg.download_dir / "video.tmp").stat().st_size
    assert 0 < partial < (tmp_path / "v2.mp4").stat().st_size
    sup.step()
    assert sup.playing.name == "video_v1.mp4"  # untouched

    monkeypatch.setattr(HttpClient, "open_stream", orig_open_stream)
    assert agent.run_once() == "updated"
    sup.step()
    assert sup.playing.name == "video_v2.mp4"
    assert (tmp_path / "v2.mp4").read_bytes() == sup.playing.read_bytes()
