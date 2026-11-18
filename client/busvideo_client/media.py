"""Media store: versioned files, atomic current.mp4 symlink, disk space, cleanup, rollback."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from .fsutil import atomic_symlink, fsync_dir, fsync_file

log = logging.getLogger("busvideo.media")
VERSION_RE = re.compile(r"^video_v(\d+)\.mp4$")


class InsufficientSpace(Exception):
    pass


class MediaStore:
    def __init__(self, media_dir: Path, keep_versions: int = 2, disk_margin_mb: int = 300):
        self.media_dir = Path(media_dir)
        self.versions_dir = self.media_dir / "versions"
        self.download_dir = self.media_dir / "download"
        self.current_link = self.media_dir / "current.mp4"
        self.keep_versions = max(1, keep_versions)
        self.disk_margin_bytes = disk_margin_mb * 1024 * 1024
        for d in (self.media_dir, self.versions_dir, self.download_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- queries -------------------------------------------------------------
    def version_path(self, version: int) -> Path:
        return self.versions_dir / f"video_v{version}.mp4"

    def installed_versions(self) -> list[int]:
        out = []
        for p in self.versions_dir.iterdir():
            m = VERSION_RE.match(p.name)
            if m and p.is_file():
                out.append(int(m.group(1)))
        return sorted(out)

    def current_target(self) -> Path | None:
        """Resolved path of current.mp4, or None if missing/broken."""
        try:
            if not self.current_link.is_symlink():
                return self.current_link if self.current_link.is_file() else None
            target = Path(os.readlink(self.current_link))
            if not target.is_absolute():
                target = self.current_link.parent / target
            return target if target.is_file() else None
        except OSError:
            return None

    def current_version(self) -> int | None:
        t = self.current_target()
        if not t:
            return None
        m = VERSION_RE.match(t.name)
        return int(m.group(1)) if m else None

    def has_playable_video(self) -> bool:
        return self.current_target() is not None

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.media_dir).free

    # -- space management ----------------------------------------------------
    def ensure_space(self, needed: int, protect_version: int | None = None) -> None:
        """Make room for `needed` bytes (+margin). Deletes rollback copies if required."""
        already = 0
        tmp = self.download_dir / "video.tmp"
        if tmp.exists():
            already = tmp.stat().st_size
        required = needed - already + self.disk_margin_bytes
        if self.free_bytes() >= required:
            return
        for v in sorted(self.installed_versions()):
            if v == protect_version:
                continue
            log.warning("Insufficient disk space; removing rollback copy video_v%d.mp4", v)
            self.version_path(v).unlink(missing_ok=True)
            if self.free_bytes() >= required:
                return
        free_mb = self.free_bytes() / (1024 * 1024)
        raise InsufficientSpace(f"Insufficient disk space: need {required / (1024 * 1024):.0f} MB, free {free_mb:.0f} MB")

    # -- install / rollback ----------------------------------------------------
    def install(self, tmp_path: Path, version: int) -> Path:
        """Move a *validated* file into place and atomically repoint current.mp4."""
        target = self.version_path(version)
        fsync_file(tmp_path)
        os.replace(tmp_path, target)
        try:
            os.chmod(target, 0o644)
        except OSError:
            pass
        fsync_dir(self.versions_dir)
        atomic_symlink(os.path.join("versions", target.name), self.current_link)
        log.info("Video updated: current.mp4 -> %s", target.name)
        return target

    def rollback(self, exclude_version: int | None = None) -> int | None:
        """Repoint current.mp4 at the newest other installed version. Returns that version."""
        candidates = [v for v in self.installed_versions() if v != exclude_version]
        if not candidates:
            return None
        v = candidates[-1]
        atomic_symlink(os.path.join("versions", self.version_path(v).name), self.current_link)
        log.warning("Rolled back current.mp4 -> video_v%d.mp4", v)
        return v

    def cleanup(self, current: int | None = None) -> list[int]:
        """Keep the newest `keep_versions` files (always keeping `current`)."""
        versions = self.installed_versions()
        keep = set(versions[-self.keep_versions:])
        if current is not None:
            keep.add(current)
        removed = []
        for v in versions:
            if v not in keep:
                self.version_path(v).unlink(missing_ok=True)
                removed.append(v)
        if removed:
            log.info("Removed old version(s): %s", ", ".join(f"v{v}" for v in removed))
        return removed

    def discard_orphans(self, active_version: int | None = None) -> None:
        part = self.download_dir / "video.part.json"
        tmp = self.download_dir / "video.tmp"
        if tmp.exists() and not part.exists():
            log.info("Removing orphan temporary download")
            tmp.unlink(missing_ok=True)
        for p in self.download_dir.iterdir():
            if p.name not in ("video.tmp", "video.part.json"):
                p.unlink(missing_ok=True)
