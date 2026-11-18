"""Client configuration: KEY=VALUE file (client.env) + environment overrides. Stdlib only."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


def load_env_file(path: Path) -> dict:
    values = {}
    if not path or not Path(path).exists():
        return values
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class ClientConfig:
    device_id: str = "BUS-000"
    server_urls: list = field(default_factory=lambda: ["https://192.168.100.10"])
    device_token: str = ""
    ca_cert: str = ""                     # ca.crt da garagem: o ônibus só confia em servidores assinados por ela
    allow_insecure_http: bool = False     # só para demo/bancada: aceitar servidor http:// (sem certificado)
    base_dir: Path = Path("/opt/busvideo-player")
    sync_interval: int = 60
    max_backoff: int = 60                 # espera máxima quando a rede existe mas o servidor não responde
    network_check_interval: int = 5       # sem rede (fora da garagem): checagem local barata a cada N s, para reagir em segundos ao estacionar
    osd_messages: bool = True             # mostrar nas telas do ônibus 'Recebendo vídeo… 45%' e 'Atualizado, pode sair'
    keep_versions: int = 2
    disk_margin_mb: int = 300
    switch_mode: str = "end_of_loop"      # end_of_loop | immediate
    switch_max_wait_s: int = 0            # 0 = one full loop (bounded by duration + 60 s)
    player: str = "mpv"                   # mpv | fake
    audio: str = "off"                    # off | alsa | auto
    mpv_extra_args: str = ""
    download_rate_limit_mbps: float = 0.0
    chunk_size: int = 1024 * 1024
    http_timeout: int = 30
    health_timeout: int = 3
    validate_format: str = "auto"         # auto | ffprobe | mpv | off
    max_failures_per_version: int = 3
    failure_cooldown_s: int = 1800
    set_time_from_server: bool = False
    hostname: str = field(default_factory=socket.gethostname)
    log_level: str = "INFO"

    @property
    def media_dir(self) -> Path:
        return self.base_dir / "media"

    @property
    def versions_dir(self) -> Path:
        return self.media_dir / "versions"

    @property
    def download_dir(self) -> Path:
        return self.media_dir / "download"

    @property
    def current_link(self) -> Path:
        return self.media_dir / "current.mp4"

    @property
    def state_dir(self) -> Path:
        return self.base_dir / "state"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def player_status_file(self) -> Path:
        return self.state_dir / "player_status.json"

    @property
    def log_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def ipc_socket(self) -> Path:
        return Path(os.environ.get("BUSVIDEO_IPC_SOCKET", "/run/busvideo-player/mpv.sock"))

    def ensure_dirs(self) -> None:
        for d in (self.media_dir, self.versions_dir, self.download_dir, self.state_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> ClientConfig:
    env_path = path or os.environ.get("BUSVIDEO_CLIENT_ENV", "/opt/busvideo-player/config/client.env")
    merged = load_env_file(Path(env_path))
    merged.update({k: v for k, v in os.environ.items() if k in _KEYS})
    if overrides:
        merged.update(overrides)
    cfg = ClientConfig()

    def get(key, default):
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

    cfg.device_id = get("DEVICE_ID", cfg.device_id)
    urls = get("SERVER_URLS", None) or get("SERVER_URL", None)
    if urls:
        cfg.server_urls = [u.strip().rstrip("/") for u in urls.split(",") if u.strip()]
    cfg.device_token = get("DEVICE_TOKEN", cfg.device_token)
    cfg.ca_cert = get("CA_CERT", cfg.ca_cert)
    cfg.allow_insecure_http = get("ALLOW_INSECURE_HTTP", cfg.allow_insecure_http)
    cfg.base_dir = Path(get("BASE_DIR", str(cfg.base_dir))).expanduser()
    cfg.sync_interval = get("SYNC_INTERVAL", cfg.sync_interval)
    cfg.max_backoff = get("MAX_BACKOFF", cfg.max_backoff)
    cfg.network_check_interval = max(1, get("NETWORK_CHECK_INTERVAL", cfg.network_check_interval))
    cfg.osd_messages = get("OSD_MESSAGES", cfg.osd_messages)
    cfg.keep_versions = max(1, get("KEEP_VERSIONS", cfg.keep_versions))
    cfg.disk_margin_mb = get("DISK_MARGIN_MB", cfg.disk_margin_mb)
    cfg.switch_mode = get("SWITCH_MODE", cfg.switch_mode)
    cfg.switch_max_wait_s = get("SWITCH_MAX_WAIT_S", cfg.switch_max_wait_s)
    cfg.player = get("PLAYER", cfg.player)
    cfg.audio = get("AUDIO", cfg.audio)
    cfg.mpv_extra_args = get("MPV_EXTRA_ARGS", cfg.mpv_extra_args)
    cfg.download_rate_limit_mbps = get("DOWNLOAD_RATE_LIMIT_MBPS", cfg.download_rate_limit_mbps)
    cfg.chunk_size = get("CHUNK_SIZE", cfg.chunk_size)
    cfg.http_timeout = get("HTTP_TIMEOUT", cfg.http_timeout)
    cfg.health_timeout = get("HEALTH_TIMEOUT", cfg.health_timeout)
    cfg.validate_format = get("VALIDATE_FORMAT", cfg.validate_format)
    cfg.max_failures_per_version = get("MAX_FAILURES_PER_VERSION", cfg.max_failures_per_version)
    cfg.failure_cooldown_s = get("FAILURE_COOLDOWN_S", cfg.failure_cooldown_s)
    cfg.set_time_from_server = get("SET_TIME_FROM_SERVER", cfg.set_time_from_server)
    cfg.hostname = get("HOSTNAME_OVERRIDE", cfg.hostname)
    cfg.log_level = get("LOG_LEVEL", cfg.log_level)
    return cfg


_KEYS = {
    "DEVICE_ID", "SERVER_URLS", "SERVER_URL", "DEVICE_TOKEN", "CA_CERT", "ALLOW_INSECURE_HTTP", "BASE_DIR", "SYNC_INTERVAL", "MAX_BACKOFF",
    "NETWORK_CHECK_INTERVAL", "OSD_MESSAGES",
    "KEEP_VERSIONS", "DISK_MARGIN_MB", "SWITCH_MODE", "SWITCH_MAX_WAIT_S", "PLAYER", "AUDIO",
    "MPV_EXTRA_ARGS", "DOWNLOAD_RATE_LIMIT_MBPS", "CHUNK_SIZE", "HTTP_TIMEOUT", "HEALTH_TIMEOUT",
    "VALIDATE_FORMAT", "MAX_FAILURES_PER_VERSION", "FAILURE_COOLDOWN_S", "SET_TIME_FROM_SERVER",
    "HOSTNAME_OVERRIDE", "LOG_LEVEL",
}
