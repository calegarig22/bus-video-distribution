"""Admin session auth (cookie) and device bearer-token auth."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from .db import utcnow_iso
from .security import constant_time_equals, hash_password, verify_password, verify_session

log = logging.getLogger("busvideo.auth")
SESSION_COOKIE = "busvideo_session"
ROLE_ADMIN = "admin"          # responsável técnico: tudo que o operador faz + redefinir senhas
ROLE_OPERATOR = "operator"    # uso diário do painel
PANEL_ROLES = (ROLE_ADMIN, ROLE_OPERATOR)
MIN_PASSWORD_LEN = 8
_DUMMY_HASH = hash_password("timing-uniform")   # verificado quando o usuário não existe, para não vazar isso pelo tempo


class LoginRateLimiter:
    def __init__(self, max_attempts: int, window_s: int):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._attempts: dict[str, deque] = defaultdict(deque)

    def allowed(self, key: str) -> bool:
        now = time.monotonic()
        q = self._attempts[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        return len(q) < self.max_attempts

    def record_failure(self, key: str) -> None:
        if len(self._attempts) > 10000 and key not in self._attempts:   # bounded memory under IP-spoofed floods
            now = time.monotonic()
            for k in [k for k, q in self._attempts.items() if not q or now - q[-1] > self.window_s]:
                self._attempts.pop(k, None)
        self._attempts[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


def get_settings(request: Request):
    return request.app.state.settings


def _session_sig(token: str) -> str:
    return token.rsplit(".", 1)[-1][:128]


def revoke_session(db, token: str, exp: int) -> None:
    """Logout: the signed token stays cryptographically valid, so remember it as revoked until it expires."""
    now = int(time.time())
    with db.tx() as conn:
        conn.execute("DELETE FROM revoked_sessions WHERE exp < ?", (now,))
        conn.execute("INSERT OR REPLACE INTO revoked_sessions (sig, exp) VALUES (?, ?)", (_session_sig(token), int(exp)))


def is_revoked(db, token: str) -> bool:
    with db.tx() as conn:
        return conn.execute("SELECT 1 FROM revoked_sessions WHERE sig=?", (_session_sig(token),)).fetchone() is not None


def current_admin(request: Request) -> dict | None:
    """Payload da sessão de qualquer usuário do painel (operador ou administrador), ou None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = verify_session(token, request.app.state.settings.secret_key)
    if payload and payload.get("role") in PANEL_ROLES and not is_revoked(request.app.state.db, token):
        return payload
    return None


def require_admin(request: Request) -> dict:
    """Exige login no painel (operador ou administrador)."""
    admin = current_admin(request)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login necessário")
    return admin


def require_role_admin(request: Request) -> dict:
    """Exige o administrador (suporte)."""
    user = require_admin(request)
    if user.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Só o administrador pode fazer isso")
    return user


def device_token_valid(request: Request) -> bool:
    settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    presented = header[7:].strip()
    if not settings.device_token:
        # No token configured: deny by default (never open without configuration).
        return False
    return constant_time_equals(presented, settings.device_token)


def require_device(request: Request) -> dict:
    if device_token_valid(request):
        return {"role": "device"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de dispositivo inválido")


def require_device_or_admin(request: Request) -> dict:
    if device_token_valid(request):
        return {"role": "device"}
    admin = current_admin(request)
    if admin:
        return admin
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autorizado")


def seed_users(db, settings) -> None:
    """Garante as duas contas do painel no banco. O server.env só semeia: depois que a senha foi trocada pelo
    painel (ou por `tools set-password`), o banco prevalece. Um hash vazio deixa a conta sem login."""
    with db.tx() as conn:
        for username, role, env_hash in ((settings.admin_user, ROLE_ADMIN, settings.admin_password_hash),
                                         (settings.operator_user, ROLE_OPERATOR, settings.operator_password_hash)):
            if not username:
                continue
            row = conn.execute("SELECT password_hash FROM users WHERE username=?", (username,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO users (username, role, password_hash, updated_at) VALUES (?,?,?,?)",
                             (username, role, env_hash or "", utcnow_iso()))
            elif not row["password_hash"] and env_hash:
                conn.execute("UPDATE users SET password_hash=?, role=?, updated_at=? WHERE username=?",
                             (env_hash, role, utcnow_iso(), username))


def list_users(db) -> list[dict]:
    with db.read() as conn:
        rows = conn.execute("SELECT username, role, password_hash, updated_at FROM users ORDER BY role, username").fetchall()
    return [{"user": r["username"], "role": r["role"], "has_password": bool(r["password_hash"]),
             "updated_at": r["updated_at"]} for r in rows]


def get_user(db, username: str) -> dict | None:
    with db.read() as conn:
        r = conn.execute("SELECT username, role, password_hash FROM users WHERE username=?", (username,)).fetchone()
    return dict(r) if r else None


def check_login(db, username: str, password: str) -> dict | None:
    """Retorna {"user", "role"} se usuário e senha conferem; senão None. Tempo uniforme para usuário inexistente."""
    row = get_user(db, username)
    if not row or not row["password_hash"]:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {"user": row["username"], "role": row["role"]}


def verify_user_password(db, username: str, password: str) -> bool:
    return check_login(db, username, password) is not None


def set_password(db, username: str, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD_LEN} caracteres")
    if get_user(db, username) is None:
        raise KeyError(username)
    with db.tx() as conn:
        conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE username=?",
                     (hash_password(new_password), utcnow_iso(), username))
