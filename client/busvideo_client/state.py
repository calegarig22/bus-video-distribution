"""Local device state (state.json). Written atomically, only when it changes."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .fsutil import atomic_write_json, read_json

log = logging.getLogger("busvideo.state")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class DeviceState:
    device_id: str = ""
    current_version: int = 0
    current_filename: str = "current.mp4"
    current_target: str = ""
    sha256: str = ""
    last_update: str = ""
    last_sync: str = ""
    status: str = "ok"
    last_error: str = ""
    app_version: str = ""
    failures: dict = field(default_factory=dict)   # {"<version>": {"count": n, "last": iso}}

    def to_dict(self) -> dict:
        return asdict(self)


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._last_written: dict | None = None

    def load(self, device_id: str, app_version: str) -> DeviceState:
        data = read_json(self.path, None)
        state = DeviceState(device_id=device_id, app_version=app_version)
        if isinstance(data, dict):
            for key in state.to_dict():
                if key in data and key not in ("device_id", "app_version"):
                    setattr(state, key, data[key])
            self._last_written = state.to_dict()
        elif self.path.exists():
            log.error("state.json corrupt; starting with defaults (video on disk is still used)")
        return state

    def save(self, state: DeviceState) -> None:
        data = state.to_dict()
        if data == self._last_written:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, data)
        self._last_written = data
