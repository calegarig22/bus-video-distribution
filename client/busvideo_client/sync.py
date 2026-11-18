"""Sync agent: network → server → version → download → validate → atomic switch → heartbeat.

Runs forever (systemd) or once (--once). Never touches the player process; it only
updates current.mp4/state.json and, optionally, sends a loadfile hint over IPC.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import ClientConfig, load_config
from .download import Downloader, DownloadError, DownloadInterrupted
from .fsutil import read_json
from .http import HttpClient, HttpError, NetworkError
from .logging_setup import setup_logging
from .media import InsufficientSpace, MediaStore
from .net import discover, has_network, local_ip_towards
from .sdnotify import ready as sd_ready, watchdog as sd_watchdog
from .state import DeviceState, StateStore, now_iso
from .validate import ValidationError, check_format, check_sha256, check_size

log = logging.getLogger("busvideo.sync")


class SyncAgent:
    def __init__(self, cfg: ClientConfig):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.store = MediaStore(cfg.media_dir, cfg.keep_versions, cfg.disk_margin_mb)
        self.state_store = StateStore(cfg.state_file)
        self.state: DeviceState = self.state_store.load(cfg.device_id, __version__)
        self.downloader = Downloader(cfg.download_dir, cfg.chunk_size, cfg.download_rate_limit_mbps,
                                     progress_cb=self._progress)
        self.preferred_url: str | None = None
        self.backoff = cfg.sync_interval
        self._quiet_since: float | None = None
        self._quiet_attempts = 0
        self._last_progress_log = 0.0
        self._osd_pct = -100
        self._hb_pct = -100
        self._progress_pct: int | None = None
        self._http = None
        self.on_message = None            # callable(text, seconds): usado pela tela de demonstração
        self._reconcile_state()

    # -- state helpers -------------------------------------------------------
    def _reconcile_state(self) -> None:
        """Make state.json agree with what is really on disk (e.g. after a crash)."""
        disk_version = self.store.current_version()
        if disk_version is not None and disk_version != self.state.current_version:
            log.warning("state.json says v%s but current.mp4 -> v%s; trusting disk",
                        self.state.current_version, disk_version)
            self.state.current_version = disk_version
            target = self.store.current_target()
            self.state.current_target = os.path.relpath(target, self.cfg.media_dir) if target else ""
            self.state.sha256 = ""  # unknown; will be re-hashed lazily if needed
        self.store.discard_orphans(self.state.current_version)
        self.state_store.save(self.state)

    def _set_error(self, message: str) -> None:
        self.state.status = "error"
        self.state.last_error = message
        self.state_store.save(self.state)

    def _clear_error(self) -> None:
        if self.state.status != "ok" or self.state.last_error:
            self.state.status = "ok"
            self.state.last_error = ""
            self.state_store.save(self.state)

    def _osd(self, text: str, seconds: float = 8.0) -> None:
        """Message on the bus screens (mpv OSD over IPC) so the driver knows what is going on. Best-effort."""
        if self.on_message:
            try:
                self.on_message(text, seconds)
            except Exception:  # noqa: BLE001
                pass
        if not self.cfg.osd_messages:
            return
        sock = self.cfg.ipc_socket
        if not sock.exists():
            return
        try:
            import json
            import socket as _socket
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(sock))
                s.sendall((json.dumps({"command": ["show-text", text, int(seconds * 1000)]}) + "\n").encode())
        except OSError:
            pass

    def _progress(self, done: int, total: int) -> None:
        pct = int(100 * done / total) if total else 0
        if pct >= self._osd_pct + 5 or pct == 100:
            self._osd_pct = pct
            self._osd(f"Recebendo vídeo novo… {pct}%", 30)
        if self._http is not None and pct >= self._hb_pct + 10:
            self._hb_pct = pct
            self._progress_pct = pct
            self._heartbeat(self._http, "downloading", self.preferred_url)
        sd_watchdog()  # long downloads must not trip the systemd watchdog
        now = time.monotonic()
        if now - self._last_progress_log >= 30:
            self._last_progress_log = now
            log.info("Download progress: %.0f%% (%d/%d MB)", 100.0 * done / total,
                     done // (1024 * 1024), total // (1024 * 1024))

    # -- server communication --------------------------------------------------
    def _heartbeat(self, http: HttpClient, status: str | None = None, base_url: str = "") -> None:
        player = read_json(self.cfg.player_status_file, {}) or {}
        host = base_url.split("//", 1)[-1].split("/")[0].split(":")[0] if base_url else ""
        payload = {
            "device_id": self.cfg.device_id,
            "hostname": self.cfg.hostname,
            "ip": local_ip_towards(host) if host else None,
            "current_version": self.state.current_version,
            "sha256": self.state.sha256,
            "app_version": __version__,
            "free_space_mb": int(self.store.free_bytes() / (1024 * 1024)),
            "uptime_s": _uptime_s(),
            "status": status or self.state.status,
            "last_error": self.state.last_error or None,
            "player": player.get("state"),
            "progress": self._progress_pct if status == "downloading" else None,
        }
        try:
            http.post_json("/api/devices/heartbeat", payload, timeout=self.cfg.health_timeout * 3)
        except (HttpError, NetworkError) as exc:
            log.warning("Heartbeat failed: %s", exc)

    def _maybe_set_time(self, health: dict) -> None:
        if not self.cfg.set_time_from_server or not health.get("server_time"):
            return
        try:
            server = datetime.fromisoformat(health["server_time"].replace("Z", "+00:00"))
            drift = abs((datetime.now(timezone.utc) - server).total_seconds())
            if drift > 60:
                subprocess.run(["date", "-u", "-s", server.strftime("%Y-%m-%d %H:%M:%S")],
                               check=False, capture_output=True, timeout=5)
                log.info("Clock adjusted from server (drift was %.0fs)", drift)
        except (ValueError, OSError):
            pass

    # -- failure tracking per version -------------------------------------------
    def _in_cooldown(self, version: int) -> bool:
        info = self.state.failures.get(str(version))
        if not info or info.get("count", 0) < self.cfg.max_failures_per_version:
            return False
        try:
            last = datetime.fromisoformat(info["last"])
        except (KeyError, ValueError):
            return False
        return (datetime.now(timezone.utc) - last).total_seconds() < self.cfg.failure_cooldown_s

    def _record_failure(self, version: int) -> None:
        info = self.state.failures.get(str(version), {"count": 0})
        info["count"] = info.get("count", 0) + 1
        info["last"] = now_iso()
        self.state.failures = {str(version): info}  # keep only the latest version's record

    # -- one sync cycle --------------------------------------------------------------
    def run_once(self) -> str:
        """Returns one of: no-network, no-server, up-to-date, updated, deferred, failed."""
        cfg = self.cfg
        if not has_network(cfg.server_urls):
            self._quiet("no-network", "No network")
            return "no-network"
        base_url, health = discover(cfg.server_urls, cfg.device_token, cfg.health_timeout, self.preferred_url,
                                    cfg.ca_cert, cfg.allow_insecure_http)
        if not base_url:
            self._quiet("no-server", f"Server unavailable ({health})")
            return "no-server"
        self._loud()
        arrived = getattr(self, "_just_arrived", False) or base_url != self.preferred_url
        self._just_arrived = False
        if arrived:
            self._osd("Conectado à garagem. Verificando vídeo…", 6)
        if base_url != self.preferred_url:
            log.info("Server detected at %s (%s v%s)", base_url, health.get("product", ""), health.get("app_version", ""))
            self.preferred_url = base_url
        self._maybe_set_time(health)
        if base_url.lower().startswith("http://") and not getattr(self, "_warned_plain", False):
            log.warning("Servidor sem HTTPS (%s) aceito porque ALLOW_INSECURE_HTTP=true (só demo/bancada): "
                        "token e vídeo trafegam em claro", base_url)
            self._warned_plain = True
        http = HttpClient(base_url, cfg.device_token, cfg.http_timeout, cfg.ca_cert)
        self._http = http
        self.state.last_sync = now_iso()
        self._heartbeat(http, base_url=base_url)

        try:
            latest = http.get_json("/api/video/latest", timeout=cfg.health_timeout * 3)
        except HttpError as exc:
            if exc.status == 401:
                self._set_error("Server rejected device token")
                log.error("Server rejected device token (401); check DEVICE_TOKEN")
                return "failed"
            log.error("Failed to query latest version: %s", exc)
            return "failed"
        except NetworkError as exc:
            log.error("Failed to query latest version: %s", exc)
            return "failed"
        if not latest:
            log.info("Local version: %s | Server has no published video", self.state.current_version)
            self._clear_error()
            self.state_store.save(self.state)
            if arrived:
                self._osd("Nenhum vídeo novo. Pode sair.", 8)
            return "up-to-date"

        server_version = int(latest["version"])
        log.info("Local version: %s | Server version: %s", self.state.current_version, server_version)
        if server_version <= self.state.current_version and self.store.has_playable_video():
            self._clear_error()
            self.state_store.save(self.state)
            if arrived:
                self._osd("Vídeo já atualizado. Pode sair.", 8)
            return "up-to-date"

        # Same content republished under a new version number: no download needed.
        if (latest["sha256"] == self.state.sha256 and self.store.has_playable_video()
                and self.state.current_version and self.store.current_version() == self.state.current_version):
            log.info("Server version %s has the same content as local; updating version number only", server_version)
            self._promote_existing(server_version)
            self._heartbeat(http, "ok", base_url)
            return "updated"

        if self._in_cooldown(server_version):
            log.warning("Version %s failed %d times; waiting cooldown before retrying", server_version,
                        self.state.failures[str(server_version)]["count"])
            return "deferred"

        return self._update(http, latest, base_url)

    def _promote_existing(self, version: int) -> None:
        current = self.store.current_target()
        if current is None:
            return
        target = self.store.version_path(version)
        os.link(current, target) if not target.exists() else None
        from .fsutil import atomic_symlink
        atomic_symlink(os.path.join("versions", target.name), self.store.current_link)
        self.state.current_version = version
        self.state.current_target = os.path.join("versions", target.name)
        self.state.last_update = now_iso()
        self._clear_error()
        self.store.cleanup(version)
        self.state_store.save(self.state)

    def _update(self, http: HttpClient, latest: dict, base_url: str) -> str:
        version = int(latest["version"])
        size = int(latest["size"])
        try:
            self.store.ensure_space(size, protect_version=self.state.current_version)
        except InsufficientSpace as exc:
            log.error("%s", exc)
            self._set_error(str(exc))
            self._heartbeat(http, "error", base_url)
            return "failed"

        self.state.status = "downloading"
        self.state_store.save(self.state)
        self._osd_pct, self._hb_pct, self._progress_pct = -100, 0, 0
        self._osd(f"Recebendo vídeo novo ({size // (1024 * 1024)} MB)… não desligue.", 30)
        self._heartbeat(http, "downloading", base_url)
        try:
            tmp = self.downloader.download(http, latest)
        except DownloadInterrupted as exc:
            log.warning("Download interrupted (%s); will resume on next contact", exc)
            self.state.status = "ok"
            self.state_store.save(self.state)
            self._progress_pct = None
            self._osd("Recebimento interrompido. Continua na próxima parada.", 10)
            return "failed"
        except DownloadError as exc:
            log.error("Download failed: %s", exc)
            self._record_failure(version)
            self._set_error(f"Download failed: {exc}")
            self._progress_pct = None
            self._osd("Falha ao receber o vídeo. Avise a garagem.", 15)
            self._heartbeat(http, "error", base_url)
            return "failed"
        self._progress_pct = None

        self._osd("Conferindo o vídeo…", 20)
        try:
            log.info("Validating download (size, SHA-256, format)")
            check_size(tmp, size)
            check_sha256(tmp, latest["sha256"], tick=lambda _done: sd_watchdog())
            log.info("SHA256 validated")
            tool = check_format(tmp, self.cfg.validate_format)
            log.info("Format validated (%s)", tool)
        except ValidationError as exc:
            log.error("%s", exc)
            self.downloader.discard()
            self._record_failure(version)
            self._set_error(str(exc))
            self._osd("Vídeo recebido com erro. Avise a garagem.", 15)
            self._heartbeat(http, "error", base_url)
            return "failed"

        previous = self.state.current_version
        self.store.install(tmp, version)
        self.downloader.discard()
        self.state.current_version = version
        self.state.current_target = os.path.join("versions", f"video_v{version}.mp4")
        self.state.sha256 = latest["sha256"]
        self.state.last_update = now_iso()
        self.state.status = "ok"
        self.state.last_error = ""
        self.state.failures = {}
        self.state_store.save(self.state)
        log.info("Video updated: v%s -> v%s", previous, version)
        self._notify_player(self.store.version_path(version))
        self.store.cleanup(version)
        self._heartbeat(http, "ok", base_url)
        self._osd(f"Vídeo atualizado (versão {version}). Pode sair.", 15)
        return "updated"

    def _notify_player(self, path: Path) -> None:
        """Best-effort hint over IPC; the supervisor also detects the symlink change by itself."""
        sock = self.cfg.ipc_socket
        if not sock.exists():
            return
        try:
            import json
            import socket as _socket
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(sock))
                s.sendall((json.dumps({"command": ["set_property", "user-data/busvideo-pending", str(path)]}) + "\n").encode())
        except OSError:
            pass

    # -- quiet logging while away from the garage ---------------------------------
    def _quiet(self, kind: str, message: str) -> None:
        now = time.monotonic()
        self._quiet_attempts += 1
        if self._quiet_since is None:
            self._quiet_since = now
            log.info("%s; playback continues with local video (further attempts logged every 10 min)", message)
        elif now - self._quiet_since >= 600:
            log.info("%s for %.0f min (%d attempts)", message, (now - self._quiet_since) / 60, self._quiet_attempts)
            self._quiet_since = now
            self._quiet_attempts = 0
        self.backoff = min(self.backoff * 2, self.cfg.max_backoff)

    def _loud(self) -> None:
        if self._quiet_since is not None:
            log.info("Connectivity restored")
            self._just_arrived = True
        self._quiet_since = None
        self._quiet_attempts = 0
        self.backoff = self.cfg.sync_interval

    # -- main loop ------------------------------------------------------------------
    def delay_for(self, result: str) -> float:
        """Sem rede: checagem local barata a cada poucos segundos (o ônibus pode estar estacionando na vaga).
        Rede sem servidor: espera crescente até MAX_BACKOFF. Servidor ok: SYNC_INTERVAL."""
        if result == "no-network":
            return float(self.cfg.network_check_interval)
        if result == "no-server":
            return float(min(self.backoff, self.cfg.max_backoff))
        return float(self.cfg.sync_interval)

    def run_forever(self) -> None:
        log.info("busvideo-sync v%s starting: device=%s servers=%s local version=%s", __version__,
                 self.cfg.device_id, ",".join(self.cfg.server_urls), self.state.current_version)
        sd_ready()
        while True:
            try:
                result = self.run_once()
            except Exception:  # never die: playback must not depend on this loop
                log.exception("Unexpected error in sync cycle")
                result = "failed"
            sd_watchdog()
            delay = self.delay_for(result)
            slept = 0.0
            while slept < delay:
                time.sleep(min(5.0, delay - slept))
                slept += 5.0
                sd_watchdog()


def _uptime_s() -> int | None:
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BusVideo sync agent")
    parser.add_argument("--config", help="path to client.env")
    parser.add_argument("--once", action="store_true", help="run a single sync cycle and exit")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    setup_logging(cfg.log_dir, "sync", cfg.log_level)
    agent = SyncAgent(cfg)
    if args.once:
        result = agent.run_once()
        log.info("Result: %s", result)
        return 0 if result in ("up-to-date", "updated", "no-network", "no-server", "deferred") else 1
    agent.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
