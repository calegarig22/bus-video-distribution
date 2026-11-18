"""Post-download validation: size, SHA-256 and (when a tool exists) media format."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("busvideo.validate")


class ValidationError(Exception):
    pass


def sha256_of(path: Path, chunk: int = 1024 * 1024, tick=None) -> str:
    """Hash a file; `tick(bytes_done)` is called per chunk (used to feed the systemd watchdog)."""
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
            done += len(block)
            if tick:
                tick(done)
    return h.hexdigest()


def check_size(path: Path, expected: int) -> None:
    actual = path.stat().st_size
    if actual != expected:
        raise ValidationError(f"Size mismatch: expected {expected}, got {actual}")


def check_sha256(path: Path, expected: str, tick=None) -> str:
    actual = sha256_of(path, tick=tick)
    if actual.lower() != expected.lower():
        raise ValidationError(f"SHA256 mismatch: expected {expected[:12]}…, got {actual[:12]}…")
    return actual


def check_format(path: Path, mode: str = "auto", ffprobe_bin: str = "ffprobe", mpv_bin: str = "mpv") -> str:
    """Returns the tool used ('ffprobe', 'mpv' or 'skipped'). Raises ValidationError if invalid."""
    if mode == "off":
        return "skipped"
    if mode in ("auto", "ffprobe") and shutil.which(ffprobe_bin):
        return _probe_ffprobe(path, ffprobe_bin)
    if mode in ("auto", "mpv") and shutil.which(mpv_bin):
        return _probe_mpv(path, mpv_bin)
    if mode == "auto":
        log.warning("No ffprobe/mpv available for format validation; relying on SHA-256 only")
        return "skipped"
    raise ValidationError(f"Format validation tool for mode {mode!r} not available")


def _probe_ffprobe(path: Path, binary: str) -> str:
    cmd = [binary, "-v", "error", "-print_format", "json", "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("ffprobe timed out") from exc
    if out.returncode != 0:
        raise ValidationError(f"ffprobe rejected file: {out.stderr.strip()[:200]}")
    try:
        streams = json.loads(out.stdout).get("streams", [])
    except ValueError as exc:
        raise ValidationError("ffprobe output unreadable") from exc
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not video:
        raise ValidationError("No video stream in file")
    codec = video[0].get("codec_name", "")
    if codec != "h264":
        raise ValidationError(f"Unsupported video codec on device: {codec}")
    return "ffprobe"


def _probe_mpv(path: Path, binary: str) -> str:
    cmd = [binary, "--no-config", "--vo=null", "--ao=null", "--frames=1", "--really-quiet", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("mpv probe timed out") from exc
    if out.returncode != 0:
        raise ValidationError("mpv could not decode the file")
    return "mpv"
