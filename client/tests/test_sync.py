import hashlib
import json
import os

from busvideo_client.sync import SyncAgent


def test_no_server_keeps_local_state(cfg, server):
    server.stop()
    agent = SyncAgent(cfg)
    assert agent.run_once() == "no-server"
    assert agent.state.current_version == 0 and agent.state.status == "ok"


def test_server_without_publication(cfg, server):
    agent = SyncAgent(cfg)
    assert agent.run_once() == "up-to-date"
    assert server.heartbeats and server.heartbeats[0]["device_id"] == "BUS-001"


def test_full_update_then_up_to_date(cfg, server, blob_factory):
    v1 = server.publish(blob_factory("a.mp4"))
    agent = SyncAgent(cfg)
    assert agent.run_once() == "updated"
    assert agent.state.current_version == v1
    assert agent.store.current_target().read_bytes() == blob_factory("a.mp4").read_bytes()
    assert not (cfg.download_dir / "video.tmp").exists() and not (cfg.download_dir / "video.part.json").exists()
    state = json.loads(cfg.state_file.read_text())
    assert state["current_version"] == 1 and state["sha256"] == hashlib.sha256(blob_factory("a.mp4").read_bytes()).hexdigest()
    assert agent.run_once() == "up-to-date"
    assert server.heartbeats[-1]["current_version"] == 1 and server.heartbeats[-1]["status"] == "ok"

    v2 = server.publish(blob_factory("b.mp4", seed=3))
    assert agent.run_once() == "updated"
    assert agent.store.current_version() == v2 and agent.store.installed_versions() == [1, 2]


def test_interrupted_download_resumes(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4", size=40_000))
    server.cut_next(1, after_bytes=10_000)
    agent = SyncAgent(cfg)
    assert agent.run_once() == "failed"
    assert (cfg.download_dir / "video.tmp").stat().st_size == 10_000
    assert agent.store.current_target() is None  # nothing installed yet
    assert agent.run_once() == "updated"
    assert any("Range" not in p for p in server.requests)
    assert agent.store.current_target().read_bytes() == blob_factory("a.mp4", size=40_000).read_bytes()


def test_interrupted_download_keeps_old_video(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4"))
    agent = SyncAgent(cfg)
    assert agent.run_once() == "updated"
    server.publish(blob_factory("b.mp4", seed=5))
    server.cut_next(3, after_bytes=2_000)
    for _ in range(3):
        assert agent.run_once() == "failed"
        assert agent.store.current_version() == 1
    assert agent.run_once() == "updated" and agent.store.current_version() == 2


def test_sha_mismatch_discards_and_keeps_old(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4"))
    agent = SyncAgent(cfg)
    agent.run_once()
    server.publish(blob_factory("b.mp4", seed=5))
    server.advertised_sha = "0" * 64
    assert agent.run_once() == "failed"
    assert agent.store.current_version() == 1
    assert not (cfg.download_dir / "video.tmp").exists()
    assert "SHA256" in agent.state.last_error and agent.state.status == "error"
    assert server.heartbeats[-1]["status"] == "error"
    # cooldown after max failures
    cfg.max_failures_per_version = 2
    assert agent.run_once() == "failed"
    assert agent.run_once() == "deferred"
    server.advertised_sha = None
    cfg.max_failures_per_version = 99
    assert agent.run_once() == "updated" and agent.state.status == "ok" and agent.state.failures == {}


def test_server_ignores_range(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4", size=30_000))
    server.ignore_range = True
    server.cut_next(1, after_bytes=5_000)
    agent = SyncAgent(cfg)
    assert agent.run_once() == "failed"
    assert agent.run_once() == "updated"


def test_insufficient_space(cfg, server, blob_factory, monkeypatch):
    server.publish(blob_factory("a.mp4"))
    agent = SyncAgent(cfg)
    monkeypatch.setattr(type(agent.store), "free_bytes", lambda self: 10)
    assert agent.run_once() == "failed"
    assert "disk space" in agent.state.last_error and server.heartbeats[-1]["status"] == "error"


def test_republish_same_content_no_download(cfg, server, blob_factory):
    a = blob_factory("a.mp4")
    server.publish(a)
    agent = SyncAgent(cfg)
    agent.run_once()
    server.publish(blob_factory("b.mp4", seed=9))
    agent.run_once()
    server.publish(a)  # rollback on server: version 3 == content of version 1
    downloads_before = len([p for p in server.requests if "/download/" in p])
    assert agent.run_once() == "updated"
    assert len([p for p in server.requests if "/download/" in p]) == downloads_before + 1  # v1 was cleaned, so re-download
    assert agent.store.current_version() == 3


def test_state_reconciles_with_disk(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4"))
    agent = SyncAgent(cfg)
    agent.run_once()
    cfg.state_file.write_text(json.dumps({"current_version": 0}))
    agent2 = SyncAgent(cfg)
    assert agent2.state.current_version == 1


def test_bad_token(cfg, server, blob_factory):
    server.publish(blob_factory("a.mp4"))
    cfg.device_token = "wrong"
    agent = SyncAgent(cfg)
    assert agent.run_once() == "failed"
    assert "token" in agent.state.last_error


def test_format_validation_with_ffprobe(cfg, server, real_video, blob_factory):
    cfg.validate_format = "auto"
    server.publish(real_video)
    agent = SyncAgent(cfg)
    assert agent.run_once() == "updated"
    server.publish(blob_factory("junk.mp4"))
    assert agent.run_once() == "failed"
    assert agent.store.current_version() == 1 and "ffprobe" in agent.state.last_error


def test_plain_http_server_is_refused_by_default(cfg, server, blob_factory):
    """On a real bus the token must never go to a server that did not prove it is the garage (https + CA)."""
    from busvideo_client.sync import SyncAgent
    cfg.allow_insecure_http = False
    agent = SyncAgent(cfg)
    assert agent.run_once() == "no-server"
    assert server.heartbeats == [] and agent.state.current_version == 0
    cfg.allow_insecure_http = True            # demo/bench only
    assert SyncAgent(cfg).run_once() in ("no-publication", "updated", "up-to-date")


def test_update_spot_messages_and_fast_network_recheck(cfg, server, blob_factory):
    """Driver-facing messages on the screens: arrival, progress, done. And a cheap re-check every few seconds without network."""
    from busvideo_client.sync import SyncAgent
    cfg.allow_insecure_http = True
    server.publish(blob_factory("vaga.mp4", size=2 * 1024 * 1024))
    agent = SyncAgent(cfg)
    shown = []
    agent.on_message = lambda text, seconds: shown.append(text)
    assert agent.delay_for("no-network") == cfg.network_check_interval and agent.delay_for("no-network") <= 5
    assert agent.delay_for("up-to-date") == cfg.sync_interval
    assert agent.run_once() == "updated"
    joined = " | ".join(shown)
    assert "Recebendo vídeo novo" in joined and "100%" in joined and "Conferindo" in joined
    assert shown[-1].startswith("Vídeo atualizado") and "Pode sair" in shown[-1]
    # progress went to the garage while downloading
    assert any(h.get("status") == "downloading" and h.get("progress") is not None for h in server.heartbeats)
    # next stop with nothing new: a short "pode sair" only when it (re)connects
    shown.clear()
    agent._just_arrived = True
    assert agent.run_once() == "up-to-date"
    assert any("Pode sair" in t for t in shown)
    shown.clear()
    assert agent.run_once() == "up-to-date" and shown == []      # steady state: quiet
