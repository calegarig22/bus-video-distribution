from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_admin, require_device

log = logging.getLogger("busvideo.api.devices")
router = APIRouter()


def _public(d: dict) -> dict:
    return {
        "device_id": d["device_id"], "hostname": d["hostname"], "ip": d["ip"],
        "current_version": d["current_version"], "sha256": d["sha256"], "app_version": d["app_version"],
        "free_space_mb": d["free_space_mb"], "uptime_s": d["uptime_s"], "reported_status": d["status"],
        "status": d["derived_status"], "progress": d.get("progress"), "last_error": d["last_error"], "last_seen": d["last_seen"],
        "last_update": d["last_update"], "first_seen": d["first_seen"],
        "seconds_since_seen": d["seconds_since_seen"],
    }


def _published_version(request: Request):
    pub = request.app.state.versions.latest()
    return pub["version"] if pub else None


@router.post("/api/devices/heartbeat")
async def heartbeat(request: Request, _=Depends(require_device)):
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido")
    if request.client:
        payload["ip"] = request.client.host   # sempre o IP observado, nunca o informado pelo dispositivo
    try:
        request.app.state.devices.heartbeat(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pub = request.app.state.versions.latest()
    return {"ok": True, "published_version": pub["version"] if pub else None}


@router.post("/api/devices/register")
async def register(request: Request, auth=Depends(require_device)):
    return await heartbeat(request, auth)


@router.get("/api/devices")
def list_devices(request: Request, _=Depends(require_admin)):
    return [_public(d) for d in request.app.state.devices.list(_published_version(request))]


@router.get("/api/devices/{device_id}")
def get_device(device_id: str, request: Request, _=Depends(require_admin)):
    d = request.app.state.devices.get(device_id, _published_version(request))
    if not d:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    out = _public(d)
    out["events"] = request.app.state.devices.events(device_id)
    return out


@router.delete("/api/devices/{device_id}")
def delete_device(device_id: str, request: Request, admin=Depends(require_admin)):
    """Remove the bus from the list. Only the operator can do it; a live bus simply reappears on its next heartbeat."""
    if not request.app.state.devices.delete(device_id):
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    log.info("Device %s removed from the list by %s", device_id, admin.get("user"))
    return {"ok": True}


@router.get("/api/devices/{device_id}/status")
def device_status(device_id: str, request: Request, _=Depends(require_admin)):
    d = request.app.state.devices.get(device_id, _published_version(request))
    if not d:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    return {"device_id": device_id, "status": d["derived_status"], "current_version": d["current_version"],
            "last_seen": d["last_seen"], "last_error": d["last_error"]}
