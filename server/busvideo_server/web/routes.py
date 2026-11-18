from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import current_admin

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ctx(request: Request, **extra) -> dict:
    s = request.app.state.settings
    ctx = {"request": request, "product_name": s.product_name, "company_name": s.company_name,
           "policy": s.media}
    ctx.update(extra)
    return ctx


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    admin = current_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=302)
    return TEMPLATES.TemplateResponse(request, "index.html", _ctx(request, user=admin.get("user"), role=admin.get("role")))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_admin(request):
        return RedirectResponse("/", status_code=302)
    return TEMPLATES.TemplateResponse(request, "login.html", _ctx(request))


@router.get("/ca.crt")
def ca_cert(request: Request):
    """Public CA certificate of the garage (install it on operator PCs/phones and on each bus)."""
    ca = request.app.state.settings.ca_cert_path
    if not ca:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(str(ca), media_type="application/x-x509-ca-cert", filename="ca.crt")
