"""SQLite access layer (stdlib sqlite3, WAL mode). One connection per request."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stored_filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    duration_s REAL,
    width INTEGER,
    height INTEGER,
    video_codec TEXT,
    audio_codec TEXT,
    fps REAL,
    bitrate_kbps INTEGER,
    h264_level INTEGER,
    container TEXT,
    status TEXT NOT NULL DEFAULT 'uploaded',
    reject_reasons TEXT NOT NULL DEFAULT '[]',
    uploaded_at TEXT NOT NULL,
    uploaded_by TEXT
);
CREATE TABLE IF NOT EXISTS publications (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    published_at TEXT NOT NULL,
    published_by TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip TEXT,
    current_version INTEGER,
    sha256 TEXT,
    app_version TEXT,
    free_space_mb INTEGER,
    uptime_s INTEGER,
    status TEXT,
    last_error TEXT,
    last_seen TEXT,
    last_update TEXT,
    first_seen TEXT
);
CREATE TABLE IF NOT EXISTS device_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_events_device ON device_events(device_id, at);
CREATE TABLE IF NOT EXISTS revoked_sessions (
    sig TEXT PRIMARY KEY,
    exp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()
