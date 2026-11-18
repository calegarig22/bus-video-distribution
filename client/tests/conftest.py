import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:  # pragma: no cover
    pass

from busvideo_client.config import ClientConfig

TOKEN = "tok"


class FakeServer:
    """Minimal stand-in for the garage server with failure injection."""

    def __init__(self):
        self.videos: dict[int, Path] = {}
        self.published: int | None = None
        self.heartbeats: list[dict] = []
        self.cut_after_bytes: int | None = None   # close connection mid-stream (first N requests)
        self.cut_requests_left = 0
        self.advertised_sha: str | None = None    # override sha in /latest
        self.ignore_range = False
        self.health_ok = True
        self.requests: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _auth(self):
                return self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                server.requests.append(self.path)
                if not self._auth():
                    return self._json(401, {"detail": "no"})
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/devices/heartbeat":
                    server.heartbeats.append(body)
                    return self._json(200, {"ok": True, "published_version": server.published})
                self._json(404, {})

            def do_GET(self):
                server.requests.append(self.path)
                if self.path == "/api/health":
                    if not server.health_ok:
                        return self._json(503, {"status": "down"})
                    return self._json(200, {"status": "ok", "server_time": "2026-09-09T10:00:00+00:00",
                                            "app_version": "test", "product": "Fake"})
                if not self._auth():
                    return self._json(401, {"detail": "no"})
                if self.path == "/api/video/latest":
                    if server.published is None:
                        self.send_response(204); self.end_headers(); return
                    return self._json(200, server.latest())
                m = re.match(r"^/api/video/download/(\d+)$", self.path)
                if m:
                    return self._download(int(m.group(1)))
                self._json(404, {})

            def _download(self, version):
                path = server.videos.get(version)
                if not path:
                    return self._json(404, {})
                data = path.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                start, end = 0, len(data) - 1
                rng = self.headers.get("Range")
                status = 200
                if rng and not server.ignore_range:
                    m = re.match(r"bytes=(\d+)-(\d*)", rng)
                    start = int(m.group(1))
                    if start >= len(data):
                        self.send_response(416); self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.end_headers(); return
                    status = 206
                self.send_response(status)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("ETag", f'"{sha}"')
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                chunk = data[start:end + 1]
                if server.cut_after_bytes is not None and server.cut_requests_left > 0:
                    server.cut_requests_left -= 1
                    self.wfile.write(chunk[:server.cut_after_bytes])
                    self.wfile.flush()
                    self.connection.close()
                    return
                self.wfile.write(chunk)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def latest(self):
        path = self.videos[self.published]
        data = path.read_bytes()
        return {"version": self.published, "filename": path.name, "size": len(data),
                "sha256": self.advertised_sha or hashlib.sha256(data).hexdigest(),
                "download_url": f"/api/video/download/{self.published}", "published_at": "2026-09-09T10:00:00+00:00"}

    def publish(self, path: Path) -> int:
        version = (self.published or 0) + 1
        self.videos[version] = path
        self.published = version
        return version

    def cut_next(self, n_requests: int, after_bytes: int):
        self.cut_after_bytes = after_bytes
        self.cut_requests_left = n_requests

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.stop()


@pytest.fixture
def cfg(tmp_path, server, monkeypatch):
    monkeypatch.setenv("BUSVIDEO_IPC_SOCKET", str(tmp_path / "mpv.sock"))
    c = ClientConfig(device_id="BUS-001", server_urls=[server.url], device_token=TOKEN, base_dir=tmp_path / "opt",
                     player="fake", validate_format="off", disk_margin_mb=0, chunk_size=1024, health_timeout=2,
                     http_timeout=5, allow_insecure_http=True)   # FakeServer is plain http
    c.ensure_dirs()
    return c


@pytest.fixture
def blob_factory(tmp_path):
    def make(name: str, size: int = 50_000, seed: int = 1) -> Path:
        p = tmp_path / name
        p.write_bytes(bytes((i * seed + 7) % 256 for i in range(size)))
        return p
    return make


FFMPEG = shutil.which("ffmpeg")


@pytest.fixture
def real_video(tmp_path):
    if not FFMPEG:
        pytest.skip("ffmpeg not available")
    p = tmp_path / "real.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(p)], check=True)
    return p
