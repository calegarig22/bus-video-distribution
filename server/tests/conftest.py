import os
import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:  # pragma: no cover
    pass

from fastapi.testclient import TestClient

from busvideo_server.config import MediaPolicy, Settings
from busvideo_server.main import create_app
from busvideo_server.security import hash_password

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
ADMIN_PW = "senha-teste"
OPERATOR_PW = "senha-operador"
TOKEN = "device-token-test"


def make_video(path: Path, *, seconds=2, size="320x240", fps=25, vcodec="libx264", acodec=None, extra=None):
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}",
           "-t", str(seconds)]
    if acodec:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds), "-c:a", acodec, "-shortest"]
    cmd += ["-c:v", vcodec]
    if vcodec == "libx264":
        cmd += ["-pix_fmt", "yuv420p", "-preset", "ultrafast", "-profile:v", "main"]
    cmd += ["-movflags", "+faststart"] + (extra or []) + [str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def videos(tmp_path_factory):
    if not FFMPEG:
        pytest.skip("ffmpeg not available")
    d = tmp_path_factory.mktemp("videos")
    return {
        "ok": make_video(d / "ok.mp4"),
        "ok_audio": make_video(d / "ok_audio.mp4", acodec="aac"),
        "ok2": make_video(d / "ok2.mp4", seconds=3),
        "fps60": make_video(d / "fps60.mp4", fps=60),
        "mpeg4": make_video(d / "mpeg4.mp4", vcodec="mpeg4"),
        "text": (d / "fake.mp4").write_bytes(b"this is not a video" * 100) and (d / "fake.mp4"),
    }


@pytest.fixture
def settings(tmp_path):
    s = Settings(
        data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
        admin_user="admin", admin_password_hash=hash_password(ADMIN_PW, iterations=1000),
        operator_user="operador", operator_password_hash=hash_password(OPERATOR_PW, iterations=1000),
        secret_key="test-secret", device_token=TOKEN, ffprobe_bin=FFPROBE or "ffprobe",
        media=MediaPolicy(max_size_mb=5, max_fps=30.0),
    )
    return s


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def device_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def _upload(client, path: Path, name=None):
    return client.post("/api/video/upload", content=path.read_bytes(),
                       headers={"X-Filename": name or path.name, "Content-Type": "application/octet-stream"})


@pytest.fixture
def upload():
    return _upload


@pytest.fixture
def admin_password():
    return ADMIN_PW


@pytest.fixture
def operator_password():
    return OPERATOR_PW


@pytest.fixture
def operator(client):
    r = client.post("/api/auth/login", json={"username": "operador", "password": OPERATOR_PW})
    assert r.status_code == 200, r.text
    return client
