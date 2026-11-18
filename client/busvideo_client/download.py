"""Resumable, rate-limited download into media/download/video.tmp."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .fsutil import atomic_write_json, fsync_file, read_json
from .http import HttpClient, HttpError, NetworkError

log = logging.getLogger("busvideo.download")


class DownloadError(Exception):
    pass


class DownloadInterrupted(DownloadError):
    """Network dropped mid-transfer; partial file kept for resume."""


class Downloader:
    def __init__(self, download_dir: Path, chunk_size: int = 1024 * 1024, rate_limit_mbps: float = 0.0,
                 progress_cb=None):
        self.download_dir = Path(download_dir)
        self.tmp_path = self.download_dir / "video.tmp"
        self.part_path = self.download_dir / "video.part.json"
        self.chunk_size = chunk_size
        self.rate_limit_bps = rate_limit_mbps * 1_000_000 / 8 if rate_limit_mbps > 0 else 0
        self.progress_cb = progress_cb

    # -- partial state -------------------------------------------------------
    def partial_matches(self, info: dict) -> bool:
        part = read_json(self.part_path, None)
        if not isinstance(part, dict) or not self.tmp_path.exists():
            return False
        return (part.get("version") == info["version"] and part.get("sha256") == info["sha256"]
                and part.get("size") == info["size"])

    def discard(self) -> None:
        for p in (self.tmp_path, self.part_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def bytes_done(self) -> int:
        try:
            return self.tmp_path.stat().st_size
        except FileNotFoundError:
            return 0

    # -- transfer ------------------------------------------------------------
    def download(self, http: HttpClient, info: dict) -> Path:
        """Download info['download_url'] to video.tmp, resuming when possible."""
        self.download_dir.mkdir(parents=True, exist_ok=True)
        expected = int(info["size"])
        if self.partial_matches(info):
            start = self.bytes_done()
            if start > expected:
                log.warning("Partial file larger than expected; discarding")
                self.discard()
                start = 0
        else:
            self.discard()
            start = 0
        if start == 0:
            atomic_write_json(self.part_path, {"version": info["version"], "sha256": info["sha256"],
                                               "size": expected, "started_at": time.time()})
        if start == expected:
            log.info("Download already complete (%d bytes)", expected)
            return self.tmp_path
        if start:
            log.info("Resuming download from byte %d of %d (%.1f%%)", start, expected, 100.0 * start / expected)
        else:
            log.info("Download started: version %s, %d bytes", info["version"], expected)

        etag = f'"{info["sha256"]}"'
        try:
            resp = http.open_stream(info["download_url"], start=start, etag=etag)
        except HttpError as exc:
            if exc.status == 416:
                self.discard()
            raise DownloadError(str(exc)) from exc
        except NetworkError as exc:
            raise DownloadInterrupted(str(exc)) from exc

        with resp:
            status = resp.status
            if start and status == 200:
                log.warning("Server ignored Range; restarting download from zero")
                start = 0
            elif start and status != 206:
                raise DownloadError(f"Unexpected status {status} on resume")
            content_range = resp.headers.get("Content-Range", "")
            if status == 206 and not content_range.startswith(f"bytes {start}-"):
                raise DownloadError(f"Unexpected Content-Range {content_range!r}")
            mode = "r+b" if start else "wb"
            t0 = time.monotonic()
            received = 0
            with open(self.tmp_path, mode) as out:
                if start:
                    out.seek(start)
                while True:
                    try:
                        chunk = resp.read(self.chunk_size)
                    except (OSError, ConnectionError) as exc:
                        out.flush()
                        raise DownloadInterrupted(f"connection lost: {exc}") from exc
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)
                    if self.progress_cb:
                        self.progress_cb(start + received, expected)
                    if start + received > expected:
                        raise DownloadError("Server sent more bytes than announced")
                    if self.rate_limit_bps:
                        ideal = received / self.rate_limit_bps
                        elapsed = time.monotonic() - t0
                        if ideal > elapsed:
                            time.sleep(ideal - elapsed)
                out.flush()
                os.fsync(out.fileno())
            elapsed = max(time.monotonic() - t0, 1e-6)
            log.info("Download finished: %d bytes in %.1fs (%.1f Mbps)", received, elapsed,
                     received * 8 / elapsed / 1e6)
        total = self.bytes_done()
        if total < expected:
            raise DownloadInterrupted(f"incomplete: {total} of {expected} bytes")
        fsync_file(self.tmp_path)
        return self.tmp_path
