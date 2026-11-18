from __future__ import annotations

from pathlib import Path

from .base import Player, PlayerError


def make_player(kind: str, ipc_socket: Path, audio: str = "off", extra_args: str = "") -> Player:
    if kind == "fake":
        from .fake import FakePlayer
        return FakePlayer()
    if kind == "mpv":
        from .mpv import MpvPlayer
        return MpvPlayer(ipc_socket, audio=audio, extra_args=extra_args)
    if kind == "mpv-desktop":  # laptop demo with a real mpv window
        from .mpv import MpvPlayer
        return MpvPlayer(ipc_socket, audio=audio, extra_args=extra_args, hwdec="auto", vo="", gpu_context="")
    raise PlayerError(f"unknown player: {kind}")


__all__ = ["Player", "PlayerError", "make_player"]
