from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..auth import (ROLE_ADMIN, SESSION_COOKIE, check_login, current_admin, list_users, require_admin,
                    require_role_admin, revoke_session, set_password, verify_user_password)
from ..security import sign_session, verify_session

log = logging.getLogger("busvideo.api.auth")
router = APIRouter()


@router.post("/api/auth/login")
async def login(request: Request):
    settings = request.app.state.settings
    limiter = request.app.state.login_limiter
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.allowed(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    username = str(body.get("username", ""))[:64]
    password = str(body.get("password", ""))[:256]
    account = check_login(request.app.state.db, username, password)
    if not account:
        limiter.record_failure(client_ip)
        log.warning("Login failed for user=%r from %s", username, client_ip)
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    limiter.reset(client_ip)
    token = sign_session({"user": account["user"], "role": account["role"]}, settings.secret_key, settings.session_ttl_s)
    resp = JSONResponse({"ok": True, "user": account["user"], "role": account["role"]})
    resp.set_cookie(SESSION_COOKIE, token, max_age=settings.session_ttl_s, httponly=True,
                    samesite="lax", path="/", secure=settings.tls_enabled)
    log.info("Login ok user=%s from %s", username, client_ip)
    return resp


@router.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        payload = verify_session(token, request.app.state.settings.secret_key)
        if payload:
            revoke_session(request.app.state.db, token, payload.get("exp", 0))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/api/auth/me")
def me(request: Request):
    admin = current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Login necessário")
    return {"user": admin.get("user"), "role": admin.get("role")}


@router.get("/api/auth/users")
def users(request: Request):
    """Contas do painel (só o administrador). Nunca devolve hashes."""
    require_role_admin(request)
    return list_users(request.app.state.db)


@router.post("/api/auth/password")
async def change_password(request: Request):
    """Troca de senha. Qualquer usuário troca a própria informando a atual; o administrador redefine a de
    qualquer conta (é assim que se recupera a senha esquecida do operador)."""
    me_ = require_admin(request)
    db = request.app.state.db
    limiter = request.app.state.login_limiter
    client_ip = request.client.host if request.client else "unknown"
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    target = str(body.get("username") or me_["user"])[:64]
    new_password = str(body.get("new_password", ""))[:256]
    current = str(body.get("current_password", ""))[:256]
    own = target == me_["user"]
    if not own and me_.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Só o administrador altera a senha de outro usuário")
    if own:
        key = f"pw:{client_ip}"
        if not limiter.allowed(key):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
        if not verify_user_password(db, target, current):
            limiter.record_failure(key)
            raise HTTPException(status_code=403, detail="Senha atual incorreta")
        limiter.reset(key)
    try:
        set_password(db, target, new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="Usuário não existe")
    log.warning("Senha de %r alterada por %r (%s) de %s", target, me_["user"], me_.get("role"), client_ip)
    return {"ok": True, "user": target}
