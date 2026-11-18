"""Publication counter and 'latest' pointer."""
from __future__ import annotations

import json
import logging

from ..db import Database, utcnow_iso

log = logging.getLogger("busvideo.versions")


class PublishError(Exception):
    pass


def row_to_video(row) -> dict:
    d = dict(row)
    d["reject_reasons"] = json.loads(d.get("reject_reasons") or "[]")
    return d


class VersionManager:
    def __init__(self, db: Database):
        self.db = db

    def get_video(self, video_id: int) -> dict | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return row_to_video(row) if row else None

    def list_videos(self, limit: int = 50) -> list[dict]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [row_to_video(r) for r in rows]

    def publish(self, video_id: int, published_by: str | None = None, note: str | None = None) -> dict:
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if not row:
                raise PublishError("Vídeo não encontrado")
            if row["status"] == "rejected":
                raise PublishError("Vídeo incompatível não pode ser publicado")
            cur = conn.execute(
                "INSERT INTO publications (video_id, published_at, published_by, note) VALUES (?,?,?,?)",
                (video_id, utcnow_iso(), published_by, note),
            )
            version = cur.lastrowid
            conn.execute("UPDATE videos SET status='archived' WHERE status='published' AND id<>?", (video_id,))
            conn.execute("UPDATE videos SET status='published' WHERE id=?", (video_id,))
        log.info("Published version=%s video_id=%s by=%s", version, video_id, published_by)
        return self.latest()

    def latest(self) -> dict | None:
        with self.db.read() as conn:
            row = conn.execute(
                """SELECT p.version, p.published_at, p.published_by, p.note, v.*
                   FROM publications p JOIN videos v ON v.id = p.video_id
                   ORDER BY p.version DESC LIMIT 1"""
            ).fetchone()
        return row_to_video(row) if row else None

    def by_version(self, version: int) -> dict | None:
        with self.db.read() as conn:
            row = conn.execute(
                """SELECT p.version, p.published_at, p.published_by, p.note, v.*
                   FROM publications p JOIN videos v ON v.id = p.video_id WHERE p.version=?""",
                (version,),
            ).fetchone()
        return row_to_video(row) if row else None

    def history(self, limit: int = 100) -> list[dict]:
        with self.db.read() as conn:
            rows = conn.execute(
                """SELECT p.version, p.published_at, p.published_by, p.note, v.id AS video_id,
                          v.original_filename, v.size_bytes, v.sha256, v.duration_s
                   FROM publications p JOIN videos v ON v.id = p.video_id
                   ORDER BY p.version DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
