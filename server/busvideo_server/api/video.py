from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import require_admin, require_device_or_admin
from ..services.storage import UploadError
from ..services.versions import PublishError

log = logging.getLogger("busvideo.api.video")
router = APIRouter()
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 1024 * 1024


def _latest_payload(pub: dict) -> dict:
    return {
        "version": pub["version"],
        "filename": pub["original_filename"],
        "size": pub["size_bytes"],
        "sha256": pub["sha256"],
        "duration": pub["duration_s"],
        "width": pub["width"],
        "height": pub["height"],
        "video_codec": pub["video_codec"],
        "published_at": pub["published_at"],
        "download_url": f"/api/video/download/{pub['version']}",
    }


@router.get("/api/video/latest")
def latest(request: Request, _=Depends(require_device_or_admin)):
    pub = request.app.state.versions.latest()
    if not pub:
        return Response(status_code=204)
    return _latest_payload(pub)


def _file_iter(path: Path, start: int, end: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _serve_file(request: Request, path: Path, sha256: str, download_name: str):
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Arquivo do vídeo não está mais disponível")
    size = path.stat().st_size
    etag = f'"{sha256}"'
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Content-Type": "video/mp4",
        "Content-Disposition": f'inline; filename="{download_name}"',
        "Cache-Control": "no-cache",
    }
    if_range = request.headers.get("if-range")
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200
    if range_header and (not if_range or if_range == etag):
        m = RANGE_RE.match(range_header.strip())
        if not m:
            raise HTTPException(status_code=416, detail="Range inválido")
        s, e = m.group(1), m.group(2)
        if s == "" and e == "":
            raise HTTPException(status_code=416, detail="Range inválido")
        if s == "":
            start = max(size - int(e), 0)
        else:
            start = int(s)
            if e:
                end = min(int(e), size - 1)
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)
    return StreamingResponse(_file_iter(path, start, end), status_code=status_code, headers=headers)


@router.api_route("/api/video/download", methods=["GET", "HEAD"])
def download_latest(request: Request, _=Depends(require_device_or_admin)):
    pub = request.app.state.versions.latest()
    if not pub:
        raise HTTPException(status_code=404, detail="Nenhum vídeo publicado")
    path = request.app.state.storage.path_for(pub["stored_filename"])
    return _serve_file(request, path, pub["sha256"], f"video_v{pub['version']}.mp4")


@router.api_route("/api/video/download/{version}", methods=["GET", "HEAD"])
def download_version(version: int, request: Request, _=Depends(require_device_or_admin)):
    pub = request.app.state.versions.by_version(version)
    if not pub:
        raise HTTPException(status_code=404, detail="Versão não encontrada")
    path = request.app.state.storage.path_for(pub["stored_filename"])
    return _serve_file(request, path, pub["sha256"], f"video_v{version}.mp4")


def _video_payload(v: dict) -> dict:
    return {
        "id": v["id"], "filename": v["original_filename"], "size": v["size_bytes"],
        "sha256": v["sha256"], "duration": v["duration_s"], "width": v["width"], "height": v["height"],
        "video_codec": v["video_codec"], "audio_codec": v["audio_codec"], "fps": v["fps"],
        "bitrate_kbps": v["bitrate_kbps"], "h264_level": v["h264_level"], "status": v["status"],
        "compatible": v["status"] != "rejected", "reasons": v["reject_reasons"],
        "uploaded_at": v["uploaded_at"], "uploaded_by": v["uploaded_by"],
    }


@router.post("/api/video/upload")
async def upload(request: Request, admin=Depends(require_admin)):
    """Raw-body streaming upload. Filename in X-Filename header (or ?filename=)."""
    filename = request.headers.get("x-filename") or request.query_params.get("filename") or ""
    declared = request.headers.get("content-length")
    declared_size = int(declared) if declared and declared.isdigit() else None
    try:
        stored = await request.app.state.storage.receive_upload(
            request.stream(), filename, uploaded_by=admin.get("user"), declared_size=declared_size,
        )
    except UploadError as exc:
        log.warning("Upload rejected (%s): %s", filename, exc)
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "compatible": False})
    video = request.app.state.versions.get_video(stored.id)
    return _video_payload(video)


@router.post("/api/video/{video_id}/publish")
def publish(video_id: int, request: Request, admin=Depends(require_admin)):
    try:
        pub = request.app.state.versions.publish(video_id, published_by=admin.get("user"))
    except PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _latest_payload(pub)


@router.get("/api/video/history")
def history(request: Request, _=Depends(require_admin)):
    return request.app.state.versions.history()


@router.get("/api/video/list")
def list_videos(request: Request, _=Depends(require_admin)):
    return [_video_payload(v) for v in request.app.state.versions.list_videos()]


@router.get("/api/video/{video_id}")
def get_video(video_id: int, request: Request, _=Depends(require_admin)):
    v = request.app.state.versions.get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    return _video_payload(v)
