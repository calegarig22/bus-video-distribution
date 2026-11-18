"""Applies the configurable media policy to probed metadata."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ..config import MediaPolicy


@dataclass
class VideoMetadata:
    container: str = ""
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = "none"
    fps: float = 0.0
    bitrate_kbps: int = 0
    h264_level: int = 0
    profile: str = ""
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PolicyResult:
    compatible: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(meta: VideoMetadata, policy: MediaPolicy) -> PolicyResult:
    reasons: list[str] = []
    container_ok = any(c in policy.allowed_containers for c in meta.container.split(","))
    if meta.container and not container_ok:
        reasons.append(f"Container não suportado: {meta.container} (esperado MP4)")
    if not meta.video_codec:
        reasons.append("Nenhuma trilha de vídeo encontrada")
    elif meta.video_codec.lower() not in policy.allowed_video_codecs:
        reasons.append(
            f"Codec de vídeo não suportado: {meta.video_codec.upper()} "
            f"(permitido: {', '.join(c.upper() for c in policy.allowed_video_codecs)})"
        )
    if meta.audio_codec.lower() not in policy.allowed_audio_codecs:
        reasons.append(
            f"Codec de áudio não suportado: {meta.audio_codec.upper()} "
            f"(permitido: {', '.join(c.upper() for c in policy.allowed_audio_codecs)})"
        )
    if meta.width > policy.max_width or meta.height > policy.max_height:
        reasons.append(
            f"Resolução {meta.width}x{meta.height} acima do limite "
            f"{policy.max_width}x{policy.max_height}"
        )
    if meta.fps > policy.max_fps + 0.01:
        reasons.append(f"FPS {meta.fps:g} acima do limite {policy.max_fps:g}")
    if meta.video_codec.lower() == "h264" and meta.h264_level and meta.h264_level > policy.max_h264_level:
        reasons.append(
            f"H.264 level {meta.h264_level / 10:.1f} acima do limite "
            f"{policy.max_h264_level / 10:.1f} (decodificador do Raspberry Pi)"
        )
    if meta.bitrate_kbps > policy.max_bitrate_kbps:
        reasons.append(
            f"Bitrate {meta.bitrate_kbps / 1000:.1f} Mbps acima do limite "
            f"{policy.max_bitrate_kbps / 1000:.1f} Mbps"
        )
    if meta.duration_s > policy.max_duration_s:
        reasons.append(
            f"Duração {meta.duration_s / 60:.1f} min acima do limite {policy.max_duration_s / 60:.0f} min"
        )
    if meta.duration_s and meta.duration_s < policy.min_duration_s:
        reasons.append("Duração menor que o mínimo permitido")
    if meta.size_bytes > policy.max_size_bytes:
        reasons.append(
            f"Tamanho {meta.size_bytes / (1024 * 1024):.0f} MB acima do limite {policy.max_size_mb} MB"
        )
    return PolicyResult(compatible=not reasons, reasons=reasons)


def check_extension(filename: str, policy: MediaPolicy) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in policy.allowed_extensions:
        return f"Extensão .{ext or '?'} não permitida (permitido: {', '.join(policy.allowed_extensions)})"
    return None
