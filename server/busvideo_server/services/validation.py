"""Probes a media file with ffprobe. The file is only ever *read*, never executed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .media_policy import VideoMetadata


class ProbeError(Exception):
    pass


def ffprobe_available(binary: str) -> bool:
    return shutil.which(binary) is not None


def _fraction(text: str) -> float:
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(text)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path, binary: str = "ffprobe", timeout_s: int = 60) -> VideoMetadata:
    if not ffprobe_available(binary):
        raise ProbeError(f"ffprobe não encontrado ({binary}); instale o pacote ffmpeg")
    cmd = [
        binary, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe excedeu o tempo limite") from exc
    if out.returncode != 0:
        raise ProbeError(f"Arquivo não é um vídeo válido: {out.stderr.strip()[:200]}")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("Saída inválida do ffprobe") from exc
    return parse_ffprobe(data, size_bytes=path.stat().st_size)


def parse_ffprobe(data: dict, size_bytes: int = 0) -> VideoMetadata:
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    meta = VideoMetadata(
        container=fmt.get("format_name", ""),
        duration_s=float(fmt.get("duration") or 0.0),
        bitrate_kbps=int(int(fmt.get("bit_rate") or 0) / 1000),
        size_bytes=size_bytes or int(fmt.get("size") or 0),
    )
    if video:
        meta.video_codec = video.get("codec_name", "")
        meta.width = int(video.get("width") or 0)
        meta.height = int(video.get("height") or 0)
        meta.fps = round(_fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0"), 3)
        meta.h264_level = int(video.get("level") or 0)
        meta.profile = video.get("profile", "") or ""
        if not meta.duration_s and video.get("duration"):
            meta.duration_s = float(video["duration"])
    meta.audio_codec = audio.get("codec_name", "unknown") if audio else "none"
    return meta
