"""Video storage: streamed upload → hash → probe → policy → versioned file.

Files are always written under system-generated names; the original filename is
kept only for display. Nothing here ever executes an uploaded file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from ..config import Settings
from ..db import Database, utcnow_iso
from . import validation
from .media_policy import VideoMetadata, check_extension, evaluate

log = logging.getLogger("busvideo.storage")

CHUNK = 1024 * 1024
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ \-()]+")


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class StoredVideo:
    id: int
    stored_filename: str
    original_filename: str
    size_bytes: int
    sha256: str
    metadata: VideoMetadata
    compatible: bool
    reasons: list[str]
    status: str


def sanitize_display_name(name: str) -> str:
    name = os.path.basename(name or "").strip()
    name = SAFE_NAME.sub("_", name)
    return name[:120] or "video.mp4"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class VideoStorage:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        settings.ensure_dirs()

    async def receive_upload(
        self, stream: AsyncIterator[bytes], original_filename: str,
        uploaded_by: str | None = None, declared_size: int | None = None,
    ) -> StoredVideo:
        policy = self.settings.media
        display_name = sanitize_display_name(original_filename)
        ext_error = check_extension(display_name, policy)
        if ext_error:
            raise UploadError(ext_error)
        if declared_size is not None and declared_size > policy.max_size_bytes:
            raise UploadError(f"Arquivo maior que o limite de {policy.max_size_mb} MB", 413)

        tmp_path = self.settings.incoming_dir / f"upload_{uuid.uuid4().hex}.tmp"
        hasher = hashlib.sha256()
        size = 0
        try:
            with open(tmp_path, "wb") as out:
                async for chunk in stream:
                    size += len(chunk)
                    if size > policy.max_size_bytes:
                        raise UploadError(f"Arquivo maior que o limite de {policy.max_size_mb} MB", 413)
                    hasher.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0:
                raise UploadError("Arquivo vazio")
            if declared_size is not None and declared_size != size:
                raise UploadError("Upload incompleto: tamanho recebido difere do declarado")
            sha256 = hasher.hexdigest()
            try:
                meta = validation.probe(tmp_path, self.settings.ffprobe_bin)
            except validation.ProbeError as exc:
                raise UploadError(str(exc)) from exc
            meta.size_bytes = size
            result = evaluate(meta, policy)
            return self._register(tmp_path, display_name, size, sha256, meta, result.compatible,
                                  result.reasons, uploaded_by)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _register(self, tmp_path: Path, display_name: str, size: int, sha256: str,
                  meta: VideoMetadata, compatible: bool, reasons: list[str],
                  uploaded_by: str | None) -> StoredVideo:
        status = "uploaded" if compatible else "rejected"
        with self.db.tx() as conn:
            cur = conn.execute(
                """INSERT INTO videos (stored_filename, original_filename, size_bytes, sha256,
                   duration_s, width, height, video_codec, audio_codec, fps, bitrate_kbps,
                   h264_level, container, status, reject_reasons, uploaded_at, uploaded_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("pending", display_name, size, sha256, meta.duration_s, meta.width, meta.height,
                 meta.video_codec, meta.audio_codec, meta.fps, meta.bitrate_kbps, meta.h264_level,
                 meta.container, status, json.dumps(reasons, ensure_ascii=False), utcnow_iso(),
                 uploaded_by),
            )
            video_id = cur.lastrowid
            stored = f"video_{video_id}.mp4"
            final_path = self.settings.videos_dir / stored
            os.replace(tmp_path, final_path)
            os.chmod(final_path, 0o640)
            conn.execute("UPDATE videos SET stored_filename=? WHERE id=?", (stored, video_id))
        log.info("Upload registered id=%s name=%s size=%s sha256=%s status=%s reasons=%s",
                 video_id, display_name, size, sha256[:12], status, reasons)
        return StoredVideo(video_id, stored, display_name, size, sha256, meta, compatible, reasons, status)

    def path_for(self, stored_filename: str) -> Path:
        # stored_filename always comes from the DB, never from a request.
        return self.settings.videos_dir / os.path.basename(stored_filename)

    def cleanup_incoming(self) -> int:
        removed = 0
        for p in self.settings.incoming_dir.glob("upload_*.tmp"):
            p.unlink(missing_ok=True)
            removed += 1
        return removed
