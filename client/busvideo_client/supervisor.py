"""Player supervisor: keeps the player alive, reloads on content change, rolls back on failure."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .config import ClientConfig, load_config
from .fsutil import atomic_write_json
from .logging_setup import setup_logging
from .media import MediaStore
from .player import Player, PlayerError, make_player
from .sdnotify import ready as sd_ready, watchdog as sd_watchdog
from .state import now_iso

log = logging.getLogger("busvideo.player")


class Supervisor:
    def __init__(self, cfg: ClientConfig, player: Player | None = None, tick: float = 1.0):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.store = MediaStore(cfg.media_dir, cfg.keep_versions, cfg.disk_margin_mb)
        self.player = player or make_player(cfg.player, cfg.ipc_socket, cfg.audio, cfg.mpv_extra_args)
        self.tick = tick
        self.playing: Path | None = None
        self.pending: Path | None = None
        self.pending_since: float | None = None
        self.restarts = 0
        self.consecutive_failures = 0
        self._last_pos: float | None = None
        self._last_pos_change = time.monotonic()
        self._last_status: dict | None = None

    # -- status file (for heartbeat / maintenance channel) -----------------------------
    def _write_status(self, state: str) -> None:
        data = {"state": state, "player": self.player.name, "playing": str(self.playing) if self.playing else None,
                "version": self.store.current_version(), "restarts": self.restarts, "updated_at": now_iso()}
        key = {k: v for k, v in data.items() if k != "updated_at"}
        if key != self._last_status:
            self._last_status = key
            try:
                atomic_write_json(self.cfg.player_status_file, data)
            except OSError:
                pass

    # -- start / restart -------------------------------------------------------------------
    def _start(self, path: Path) -> bool:
        try:
            self.player.start(path)
        except PlayerError as exc:
            log.error("Player failed to start with %s: %s", path.name, exc)
            return False
        self.playing = path
        self._last_pos = None
        self._last_pos_change = time.monotonic()
        log.info("Player started: %s", path)
        self._write_status("playing")
        return True

    def ensure_playing(self) -> None:
        target = self.store.current_target()
        if target is None:
            self._write_status("no-content")
            return
        if self.player.is_alive():
            return
        if self.playing is not None:
            self.restarts += 1
            self.consecutive_failures += 1
            log.error("Player not running (restart #%d)", self.restarts)
            if self.consecutive_failures >= 5 and self.store.current_version() is not None:
                # The current file may be the problem: fall back to the previous version.
                rolled = self.store.rollback(exclude_version=self.store.current_version())
                if rolled is not None:
                    log.error("Player kept failing; rolled back to v%d", rolled)
                    self.consecutive_failures = 0
                    target = self.store.current_target()
            delay = min(2 ** min(self.consecutive_failures, 5), 30)
            time.sleep(delay)
        if self._start(target):
            self.consecutive_failures = 0 if self.consecutive_failures < 5 else self.consecutive_failures

    # -- content change detection --------------------------------------------------------
    def check_content_change(self) -> None:
        target = self.store.current_target()
        if target is None or self.playing is None:
            return
        if os.path.realpath(target) == os.path.realpath(self.playing):
            self.pending = None
            return
        if self.pending is None or os.path.realpath(self.pending) != os.path.realpath(target):
            self.pending = target
            self.pending_since = time.monotonic()
            log.info("New content detected: %s (switch mode: %s)", target.name, self.cfg.switch_mode)

    def _should_switch_now(self) -> bool:
        if self.cfg.switch_mode == "immediate":
            return True
        pos = self.player.position()
        if pos is None:
            return True  # no position info: do not wait forever
        duration = self.player.duration() or 30.0
        wrapped = self._last_pos is not None and pos < self._last_pos - 0.01
        near_start = pos < min(1.5, 0.05 * duration)
        max_wait = self.cfg.switch_max_wait_s or (duration + 60)
        timed_out = self.pending_since is not None and (time.monotonic() - self.pending_since) > max_wait
        return wrapped or near_start or timed_out

    def apply_pending(self) -> None:
        if self.pending is None or not self.player.is_alive():
            return
        if not self._should_switch_now():
            return
        new = self.pending
        old = self.playing
        log.info("Switching player to %s", new.name)
        if self.player.load(new):
            self.playing = new
            self.pending = None
            self._last_pos = None
            self._last_pos_change = time.monotonic()
            log.info("Player restarted with new video: %s", new.name)
            self._write_status("playing")
            return
        log.error("Player could not load %s; rolling back", new.name)
        bad_version = self.store.current_version()
        rolled = self.store.rollback(exclude_version=bad_version)
        self.pending = None
        if rolled is None:
            log.error("No previous version to roll back to")
            return
        if old is not None and not self.player.load(old):
            self.player.stop()  # ensure_playing() will restart with the rolled-back file

    # -- stall detection ------------------------------------------------------------------
    def check_stall(self, stall_seconds: float = 15.0) -> None:
        if not self.player.is_alive():
            return
        pos = self.player.position()
        now = time.monotonic()
        if pos is None:
            return
        if self._last_pos is None or abs(pos - self._last_pos) > 0.05:
            self._last_pos_change = now
        elif now - self._last_pos_change > stall_seconds:
            log.error("Player stalled for %.0fs at position %.1f; restarting", now - self._last_pos_change, pos)
            self.player.stop()
            self._last_pos_change = now
        self._last_pos = pos

    def step(self) -> None:
        self.ensure_playing()
        self.check_content_change()
        self.apply_pending()
        self.check_stall()
        sd_watchdog()

    def run_forever(self) -> None:
        log.info("busvideo-player v%s starting: player=%s media=%s", __version__, self.player.name, self.cfg.media_dir)
        sd_ready()
        while True:
            try:
                self.step()
            except Exception:
                log.exception("Unexpected error in supervisor loop")
            time.sleep(self.tick)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BusVideo player supervisor")
    parser.add_argument("--config", help="path to client.env")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    setup_logging(cfg.log_dir, "player", cfg.log_level)
    Supervisor(cfg).run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
