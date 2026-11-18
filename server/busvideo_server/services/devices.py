"""Device registry fed by heartbeats. Displayed status is derived, not stored."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..db import Database, utcnow_iso

log = logging.getLogger("busvideo.devices")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def _clean(value, limit: int) -> str:
    """Text from a device: printable characters only (no control chars, no line breaks for the logs)."""
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isprintable())[:limit]


def valid_device_id(device_id: str) -> bool:
    return bool(device_id and DEVICE_ID_RE.match(device_id))


class DeviceManager:
    def __init__(self, db: Database, offline_after_s: int = 900):
        self.db = db
        self.offline_after_s = offline_after_s
        self._progress: dict[str, int] = {}   # download em andamento (%), só em memória

    def heartbeat(self, payload: dict) -> dict:
        device_id = str(payload.get("device_id", "")).strip()
        if not valid_device_id(device_id):
            raise ValueError("device_id inválido")
        now = utcnow_iso()
        fields = {
            "hostname": _clean(payload.get("hostname"), 100),
            "ip": str(payload.get("ip") or "")[:64],
            "current_version": _int_or_none(payload.get("current_version")),
            "sha256": str(payload.get("sha256") or "")[:64],
            "app_version": str(payload.get("app_version") or "")[:32],
            "free_space_mb": _int_or_none(payload.get("free_space_mb")),
            "uptime_s": _int_or_none(payload.get("uptime_s")),
            "status": str(payload.get("status") or "ok")[:32],
            "last_error": (_clean(payload.get("last_error"), 500) or None),
        }
        pct = _int_or_none(payload.get("progress"))
        if fields["status"] == "downloading" and pct is not None:
            self._progress[device_id] = max(0, min(100, pct))
        else:
            self._progress.pop(device_id, None)
        with self.db.tx() as conn:
            existing = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO devices (device_id, hostname, ip, current_version, sha256, app_version,
                       free_space_mb, uptime_s, status, last_error, last_seen, last_update, first_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (device_id, fields["hostname"], fields["ip"], fields["current_version"],
                     fields["sha256"], fields["app_version"], fields["free_space_mb"], fields["uptime_s"],
                     fields["status"], fields["last_error"], now,
                     now if fields["current_version"] is not None else None, now),
                )
                conn.execute("INSERT INTO device_events (device_id, at, level, message) VALUES (?,?,?,?)",
                             (device_id, now, "INFO", "Dispositivo registrado"))
                log.info("Device registered %s ip=%s version=%s", device_id, fields["ip"], fields["current_version"])
            else:
                version_changed = (fields["current_version"] is not None
                                   and fields["current_version"] != existing["current_version"])
                last_update = now if version_changed else existing["last_update"]
                conn.execute(
                    """UPDATE devices SET hostname=?, ip=?, current_version=?, sha256=?, app_version=?,
                       free_space_mb=?, uptime_s=?, status=?, last_error=?, last_seen=?, last_update=?
                       WHERE device_id=?""",
                    (fields["hostname"], fields["ip"], fields["current_version"], fields["sha256"],
                     fields["app_version"], fields["free_space_mb"], fields["uptime_s"], fields["status"],
                     fields["last_error"], now, last_update, device_id),
                )
                if version_changed:
                    conn.execute("INSERT INTO device_events (device_id, at, level, message) VALUES (?,?,?,?)",
                                 (device_id, now, "INFO", f"Atualizado para versão {fields['current_version']}"))
                    log.info("Device %s updated to version %s", device_id, fields["current_version"])
                if fields["last_error"] and fields["last_error"] != existing["last_error"]:
                    conn.execute("INSERT INTO device_events (device_id, at, level, message) VALUES (?,?,?,?)",
                                 (device_id, now, "ERROR", fields["last_error"]))
                    log.warning("Device %s reported error: %s", device_id, fields["last_error"])
        return self.get(device_id)

    def _derive(self, row, published_version: int | None) -> dict:
        d = dict(row)
        seen = _parse(d.get("last_seen"))
        age = (datetime.now(timezone.utc) - seen).total_seconds() if seen else None
        if age is None or age > self.offline_after_s:
            derived = "offline"
        elif d.get("status") == "downloading":
            derived = "downloading"
        elif d.get("status") == "error":
            derived = "error"
        elif published_version is None:
            derived = "updated"
        elif d.get("current_version") == published_version:
            derived = "updated"
        else:
            derived = "pending"
        d["derived_status"] = derived
        d["progress"] = self._progress.get(d["device_id"]) if derived == "downloading" else None
        d["seconds_since_seen"] = int(age) if age is not None else None
        return d

    def list(self, published_version: int | None) -> list[dict]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY device_id").fetchall()
        return [self._derive(r, published_version) for r in rows]

    def get(self, device_id: str, published_version: int | None = None) -> dict | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return self._derive(row, published_version) if row else None

    def delete(self, device_id: str) -> bool:
        """Remove a bus from the panel (decommissioned or a test entry). It re-registers on its next heartbeat."""
        with self.db.tx() as conn:
            conn.execute("DELETE FROM device_events WHERE device_id=?", (device_id,))
            cur = conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
            return cur.rowcount > 0

    def events(self, device_id: str, limit: int = 50) -> list[dict]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM device_events WHERE device_id=? ORDER BY id DESC LIMIT ?", (device_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]


def _int_or_none(value):
    try:
        n = int(value) if value is not None and value != "" else None
    except (TypeError, ValueError, OverflowError):
        return None
    return n if n is None or -(2 ** 62) <= n <= 2 ** 62 else None   # within SQLite INTEGER range


def _parse(text):
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
