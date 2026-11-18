"""Player abstraction. Implementations: mpv (production) and fake (tests/demo)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlayerError(Exception):
    pass


class Player(ABC):
    name = "base"

    @abstractmethod
    def start(self, path: Path) -> None:
        """Start playback of `path` in fullscreen infinite loop."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and release the process."""

    @abstractmethod
    def is_alive(self) -> bool:
        """True while the player process is running."""

    @abstractmethod
    def position(self) -> float | None:
        """Playback position in seconds, or None if unknown."""

    @abstractmethod
    def duration(self) -> float | None:
        """Duration of the loaded file in seconds, or None if unknown."""

    @abstractmethod
    def load(self, path: Path) -> bool:
        """Replace the playing file without restarting the process. Returns success."""

    @property
    def current_path(self) -> Path | None:
        return getattr(self, "_current", None)
