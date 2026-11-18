import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:  # pragma: no cover
    pass

from busvideo_server.config import MediaPolicy, Settings
from busvideo_server.main import create_app
from busvideo_server.security import hash_password

ADMIN_PW = "demo"
TOKEN = "integration-token"
FFMPEG = shutil.which("ffmpeg")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, tmp_path: Path):
        self.settings = Settings(
            data_dir=tmp_path / "server" / "data", log_dir=tmp_path / "server" / "logs",
            admin_password_hash=hash_password(ADMIN_PW, iterations=1000), secret_key="s",
            device_token=TOKEN, ffprobe_bin=shutil.which("ffprobe") or "ffprobe",
            media=MediaPolicy(max_size_mb=50), host="127.0.0.1", port=free_port(),
        )
        self.app = create_app(self.settings)
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.settings.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{self.settings.port}"

    def start(self):
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if httpx.get(self.url + "/api/health", timeout=1).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def admin(self) -> httpx.Client:
        c = httpx.Client(base_url=self.url, timeout=30)
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
        assert r.status_code == 200
        return c


@pytest.fixture
def live(tmp_path):
    s = LiveServer(tmp_path).start()
    yield s
    s.stop()


def make_video(path: Path, seconds: int, color: str):
    if not FFMPEG:
        pytest.skip("ffmpeg not available")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:size=320x240:rate=25",
                    "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-movflags", "+faststart", str(path)], check=True)
    return path


@pytest.fixture
def token():
    return TOKEN


@pytest.fixture
def video_maker():
    return make_video
