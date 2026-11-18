import time

from busvideo_client.player.fake import FakePlayer
from busvideo_client.supervisor import Supervisor


def _install(store, version, content=b"x"):
    (store.download_dir / "video.tmp").write_bytes(content)
    store.install(store.download_dir / "video.tmp", version)


def test_starts_and_restarts_after_crash(cfg):
    player = FakePlayer(loop_seconds=5)
    sup = Supervisor(cfg, player=player)
    sup.step()
    assert sup.playing is None  # no content yet
    _install(sup.store, 1)
    sup.step()
    assert player.is_alive() and sup.playing.name == "video_v1.mp4" and player.starts == 1
    player.kill()
    t0 = time.monotonic()
    sup.step()
    assert player.is_alive() and player.starts == 2 and sup.restarts == 1
    assert time.monotonic() - t0 < 5


def test_switch_immediate_and_end_of_loop(cfg):
    player = FakePlayer(loop_seconds=1.0)
    cfg.switch_mode = "immediate"
    sup = Supervisor(cfg, player=player)
    _install(sup.store, 1)
    sup.step()
    _install(sup.store, 2)
    sup.step()
    assert player.loads and player.loads[-1].name == "video_v2.mp4" and sup.pending is None

    cfg.switch_mode = "end_of_loop"
    _install(sup.store, 3)
    time.sleep(0.3)
    sup.step()
    time.sleep(0.2)
    sup.step()  # position ~0.5s: should still be pending (not near start, not wrapped)
    assert sup.pending is not None and sup.pending.name == "video_v3.mp4"
    time.sleep(0.6)  # crosses the loop boundary
    sup.step()
    assert player.loads[-1].name == "video_v3.mp4" and sup.pending is None


def test_rollback_when_new_file_fails_to_load(cfg):
    player = FakePlayer(loop_seconds=5, fail_paths={"video_v2.mp4"})
    cfg.switch_mode = "immediate"
    sup = Supervisor(cfg, player=player)
    _install(sup.store, 1)
    sup.step()
    _install(sup.store, 2)
    sup.step()
    assert sup.store.current_version() == 1  # rolled back
    assert sup.playing.name == "video_v1.mp4" and player.is_alive()


def test_stall_detection(cfg, monkeypatch):
    player = FakePlayer(loop_seconds=5)
    sup = Supervisor(cfg, player=player)
    _install(sup.store, 1)
    sup.step()
    monkeypatch.setattr(player, "position", lambda: 2.0)
    sup.check_stall(stall_seconds=0.2)
    time.sleep(0.3)
    sup.check_stall(stall_seconds=0.2)
    assert not player.is_alive()
    sup.step()
    assert player.is_alive() and sup.restarts == 1


def test_status_file(cfg):
    player = FakePlayer()
    sup = Supervisor(cfg, player=player)
    _install(sup.store, 4)
    sup.step()
    import json
    data = json.loads(cfg.player_status_file.read_text())
    assert data["state"] == "playing" and data["version"] == 4
