from __future__ import annotations

from fastapi import APIRouter, Request

from .. import __version__
from ..db import utcnow_iso

router = APIRouter()


@router.get("/api/health")
def health(request: Request):
    return {"status": "ok", "server_time": utcnow_iso(), "app_version": __version__,
            "product": request.app.state.settings.product_name}
