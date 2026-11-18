import os
from pathlib import Path

import pytest

from busvideo_client.media import InsufficientSpace, MediaStore
from busvideo_client.state import DeviceState, StateStore


def test_state_roundtrip_and_corruption(tmp_path):
    store = StateStore(tmp_path / "s" / "state.json")
    st = store.load("BUS-001", "0.1.0")
    assert st.current_version == 0
    st.current_version = 5; st.sha256 = "abc"
    store.save(st)
    assert (tmp_path / "s" / "state.json").exists() and not (tmp_path / "s" / "state.json.tmp").exists()
    st2 = StateStore(tmp_path / "s" / "state.json").load("BUS-001", "0.1.0")
    assert st2.current_version == 5 and st2.sha256 == "abc"
    (tmp_path / "s" / "state.json").write_text("{corrupt")
    st3 = StateStore(tmp_path / "s" / "state.json").load("BUS-001", "0.1.0")
    assert st3.current_version == 0


def test_install_symlink_and_cleanup(tmp_path):
    store = MediaStore(tmp_path / "media", keep_versions=2)
    assert store.current_target() is None and not store.has_playable_video()
    for v in (1, 2, 3):
        tmp = store.download_dir / "video.tmp"
        tmp.write_bytes(b"v%d" % v)
        store.install(tmp, v)
        assert store.current_target().read_bytes() == b"v%d" % v
        assert store.current_link.is_symlink() and os.readlink(store.current_link) == f"versions/video_v{v}.mp4"
        assert not tmp.exists()
    assert store.installed_versions() == [1, 2, 3]
    assert store.cleanup(current=3) == [1]
    assert store.installed_versions() == [2, 3] and store.current_version() == 3


def test_rollback(tmp_path):
    store = MediaStore(tmp_path / "media", keep_versions=2)
    for v in (1, 2):
        (store.download_dir / "video.tmp").write_bytes(b"x")
        store.install(store.download_dir / "video.tmp", v)
    assert store.rollback(exclude_version=2) == 1
    assert store.current_version() == 1
    assert store.rollback(exclude_version=1) == 2
    store.version_path(1).unlink()
    assert store.rollback(exclude_version=2) is None


def test_ensure_space_removes_rollback_copies(tmp_path, monkeypatch):
    store = MediaStore(tmp_path / "media", keep_versions=2, disk_margin_mb=0)
    for v in (1, 2):
        (store.download_dir / "video.tmp").write_bytes(b"x" * 1000)
        store.install(store.download_dir / "video.tmp", v)
    free = {"v": 500}

    def fake_free(self):
        return free["v"] + sum(0 if p.exists() else 1000 for p in (store.version_path(1),))
    monkeypatch.setattr(MediaStore, "free_bytes", fake_free)
    store.ensure_space(1200, protect_version=2)  # needs removal of v1 (frees 1000)
    assert not store.version_path(1).exists() and store.version_path(2).exists()
    with pytest.raises(InsufficientSpace):
        store.ensure_space(5000, protect_version=2)
    assert store.version_path(2).exists()  # current is never deleted


def test_orphan_tmp_removed(tmp_path):
    store = MediaStore(tmp_path / "media")
    (store.download_dir / "video.tmp").write_bytes(b"junk")
    store.discard_orphans()
    assert not (store.download_dir / "video.tmp").exists()
