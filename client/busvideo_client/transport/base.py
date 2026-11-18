"""Maintenance transport abstraction (future Bluetooth / local diagnostics).

The MVP ships only this interface plus a local provider that reads state.json.
A future BLE GATT service or RFCOMM console implements MaintenanceTransport and
consumes StatusProvider without touching the sync agent or the player.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..fsutil import read_json


class StatusProvider:
    """Read-only view of the device for any maintenance channel."""

    def __init__(self, state_file: Path, player_status_file: Path, device_id: str, app_version: str):
        self.state_file = Path(state_file)
        self.player_status_file = Path(player_status_file)
        self.device_id = device_id
        self.app_version = app_version

    def identity(self) -> dict:
        return {"device_id": self.device_id, "app_version": self.app_version}

    def status(self) -> dict:
        state = read_json(self.state_file, {}) or {}
        player = read_json(self.player_status_file, {}) or {}
        return {"identity": self.identity(), "state": state, "player": player}


class MaintenanceTransport(ABC):
    """Contract for a local maintenance channel (Bluetooth, serial, ...)."""

    @abstractmethod
    def start(self, provider: StatusProvider) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
