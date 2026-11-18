"""Server configuration.

Values come from environment variables, optionally pre-loaded from a KEY=VALUE
file pointed by BUSVIDEO_SERVER_ENV (default: ./config/server.env if present).
No secret is ever hardcoded here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_env_file(path: Path) -> dict:
    """Parse a simple KEY=VALUE file (comments and blank lines ignored)."""
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():  # utf-8-sig: aceita o BOM que o PowerShell grava
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _split_list(value: str) -> list[str]:
    return [v.strip().lower() for v in value.split(",") if v.strip()]


@dataclass
class MediaPolicy:
    """Configurable media rules. Defaults target the Raspberry Pi 3B+ HW decoder."""
    allowed_extensions: list[str] = field(default_factory=lambda: ["mp4", "m4v", "mov"])
    allowed_containers: list[str] = field(default_factory=lambda: ["mov", "mp4", "m4a", "3gp", "3g2", "mj2"])
    allowed_video_codecs: list[str] = field(default_factory=lambda: ["h264"])
    allowed_audio_codecs: list[str] = field(default_factory=lambda: ["aac", "none"])
    max_width: int = 1920
    max_height: int = 1080
    max_fps: float = 30.0
    max_h264_level: int = 41
    max_bitrate_kbps: int = 12000
    max_duration_s: int = 3600
    max_size_mb: int = 2048
    min_duration_s: float = 1.0

    @property
    def max_size_bytes(self) -> int:
        return self.max_size_mb * 1024 * 1024


@dataclass
class Settings:
    data_dir: Path
    log_dir: Path
    host: str = "0.0.0.0"
    port: int = 8080
    product_name: str = "Bus Video"
    company_name: str = "Empresa Exemplo"
    admin_user: str = "admin"                 # administrador (suporte): redefine a senha do operador
    admin_password_hash: str = ""
    operator_user: str = "operador"           # uso diário: publica vídeo e acompanha a frota
    operator_password_hash: str = ""
    secret_key: str = ""
    device_token: str = ""
    session_ttl_s: int = 12 * 3600
    offline_after_s: int = 900
    ffprobe_bin: str = "ffprobe"
    login_max_attempts: int = 5
    login_window_s: int = 60
    tls_cert: str = ""                    # caminho do server.crt (PEM). Com tls_key, liga HTTPS.
    tls_key: str = ""
    http_redirect_port: int = 0           # com HTTPS: porta HTTP que só redireciona e serve /ca.crt (0 = desligado)
    media: MediaPolicy = field(default_factory=MediaPolicy)

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert and self.tls_key)

    @property
    def ca_cert_path(self) -> Path | None:
        """ca.crt next to the server certificate, when it exists (public; buses and operators install it)."""
        if not self.tls_cert:
            return None
        p = Path(self.tls_cert).parent / "ca.crt"
        return p if p.exists() else None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "busvideo.db"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos" / "versions"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "videos" / "incoming"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.log_dir, self.videos_dir, self.incoming_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(env: dict | None = None) -> Settings:
    """Build Settings from (env file) + (process environment). Process env wins."""
    merged: dict = {}
    env_file = os.environ.get("BUSVIDEO_SERVER_ENV", "config/server.env")
    merged.update(load_env_file(Path(env_file)))
    merged.update(os.environ)
    if env:
        merged.update(env)

    def get(key: str, default):
        val = merged.get(key)
        if val is None or val == "":
            return default
        if isinstance(default, bool):
            return str(val).lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        return val

    media = MediaPolicy(
        allowed_extensions=_split_list(get("MEDIA_ALLOWED_EXTENSIONS", "mp4,m4v,mov")),
        allowed_video_codecs=_split_list(get("MEDIA_ALLOWED_VIDEO_CODECS", "h264")),
        allowed_audio_codecs=_split_list(get("MEDIA_ALLOWED_AUDIO_CODECS", "aac,none")),
        max_width=get("MEDIA_MAX_WIDTH", 1920),
        max_height=get("MEDIA_MAX_HEIGHT", 1080),
        max_fps=get("MEDIA_MAX_FPS", 30.0),
        max_h264_level=get("MEDIA_MAX_H264_LEVEL", 41),
        max_bitrate_kbps=get("MEDIA_MAX_BITRATE_KBPS", 12000),
        max_duration_s=get("MEDIA_MAX_DURATION_S", 3600),
        max_size_mb=get("MEDIA_MAX_SIZE_MB", 2048),
    )
    data_dir = Path(get("BUSVIDEO_DATA_DIR", "data")).expanduser()
    log_dir = Path(get("BUSVIDEO_LOG_DIR", str(data_dir / "logs"))).expanduser()
    secret = get("SECRET_KEY", "")
    if not secret:
        # A missing secret would invalidate sessions on restart, but never blocks startup.
        secret = os.urandom(32).hex()
    return Settings(
        data_dir=data_dir,
        log_dir=log_dir,
        host=get("BUSVIDEO_HOST", "0.0.0.0"),
        port=get("BUSVIDEO_PORT", 8080),
        product_name=get("PRODUCT_NAME", "Bus Video"),
        company_name=get("COMPANY_NAME", "Empresa Exemplo"),
        admin_user=get("ADMIN_USER", "admin"),
        admin_password_hash=get("ADMIN_PASSWORD_HASH", ""),
        operator_user=get("OPERATOR_USER", "operador"),
        operator_password_hash=get("OPERATOR_PASSWORD_HASH", ""),
        secret_key=secret,
        device_token=get("DEVICE_TOKEN", ""),
        session_ttl_s=get("SESSION_TTL_S", 12 * 3600),
        offline_after_s=get("OFFLINE_AFTER_S", 900),
        ffprobe_bin=get("FFPROBE_BIN", "ffprobe"),
        login_max_attempts=get("LOGIN_MAX_ATTEMPTS", 5),
        login_window_s=get("LOGIN_WINDOW_S", 60),
        tls_cert=get("BUSVIDEO_TLS_CERT", ""),
        tls_key=get("BUSVIDEO_TLS_KEY", ""),
        http_redirect_port=get("BUSVIDEO_HTTP_REDIRECT_PORT", 0),
        media=media,
    )
