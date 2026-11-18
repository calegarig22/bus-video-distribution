"""Simulated player for tests and for the demo on a laptop without mpv."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import Player, PlayerError

log = logging.getLogger("busvideo.player.fake")


class FakePlayer(Player):
    name = "fake"

    def __init__(self, loop_seconds: float = 20.0, fail_paths: set | None = None, crash_after: float | None = None):
        self.loop_seconds = loop_seconds
        self.fail_paths = fail_paths or set()
        self.crash_after = crash_after
        self._current: Path | None = None
        self._started: float | None = None
        self._alive = False
        self.loads: list[Path] = []
        self.starts = 0

    def start(self, path: Path) -> None:
        if path.name in self.fail_paths or str(path) in self.fail_paths:
            raise PlayerError(f"cannot open {path}")
        self._current = Path(path)
        self._started = time.monotonic()
        self._alive = True
        self.starts += 1
        log.info("[fake player] NOW PLAYING %s (loop)", path)

    def stop(self) -> None:
        self._alive = False

    def kill(self) -> None:  # test helper: simulate a crash
        self._alive = False

    def is_alive(self) -> bool:
        if self._alive and self.crash_after is not None and self._started is not None:
            if time.monotonic() - self._started > self.crash_after:
                self._alive = False
        return self._alive

    def position(self) -> float | None:
        if not self._alive or self._started is None:
            return None
        return (time.monotonic() - self._started) % self.loop_seconds

    def duration(self) -> float | None:
        return self.loop_seconds

    def load(self, path: Path) -> bool:
        if not self._alive:
            return False
        if path.name in self.fail_paths or str(path) in self.fail_paths:
            log.error("[fake player] failed to load %s", path)
            return False
        self._current = Path(path)
        self._started = time.monotonic()
        self.loads.append(Path(path))
        log.info("[fake player] NOW PLAYING %s (loop)", path)
        return True
