"""FastAPI application factory and uvicorn entrypoint."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import auth_routes, devices, health, video
from .auth import LoginRateLimiter, list_users, seed_users
from .config import Settings, load_settings
from .db import Database
from . import hardening
from .logging_setup import setup_logging
from .services.devices import DeviceManager
from .services.storage import VideoStorage
from .services.versions import VersionManager
from .web import routes as web_routes

log = logging.getLogger("busvideo.server")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    setup_logging(settings.log_dir)
    app = FastAPI(title=settings.product_name, version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    db = Database(settings.db_path)
    seed_users(db, settings)
    app.state.settings = settings
    app.state.db = db
    app.state.storage = VideoStorage(settings, db)
    app.state.versions = VersionManager(db)
    app.state.devices = DeviceManager(db, settings.offline_after_s)
    app.state.login_limiter = LoginRateLimiter(settings.login_max_attempts, settings.login_window_s)
    hardening.install(app, settings)
    app.include_router(health.router)
    app.include_router(auth_routes.router)
    app.include_router(video.router)
    app.include_router(devices.router)
    app.include_router(web_routes.router)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "web" / "static")), name="static")

    @app.on_event("startup")
    def _startup():
        removed = app.state.storage.cleanup_incoming()
        if removed:
            log.info("Removed %d stale incoming upload(s)", removed)
        accounts = list_users(db)
        if not any(u["has_password"] for u in accounts):
            log.error("Nenhuma conta do painel tem senha (ADMIN_PASSWORD_HASH / OPERATOR_PASSWORD_HASH vazios): "
                      "login desabilitado. Rode: python -m busvideo_server.tools set-password admin")
        for u in accounts:
            if not u["has_password"]:
                log.warning("Conta %r (%s) sem senha: o administrador define no painel (Senha) ou "
                            "`tools set-password %s`", u["user"], u["role"], u["user"])
        if not settings.device_token:
            log.error("DEVICE_TOKEN is not set: devices cannot authenticate.")
        if not settings.tls_enabled:
            log.warning("HTTPS desligado (BUSVIDEO_TLS_CERT/BUSVIDEO_TLS_KEY vazios): senha e token trafegam em claro. "
                        "Gere os certificados com: python -m busvideo_server.tools gen-cert --out config/tls")
        log.info("%s v%s started on %s:%s (%s) data=%s", settings.product_name, __version__,
                 settings.host, settings.port, "https" if settings.tls_enabled else "http", settings.data_dir)

    return app


def _ensure_ffprobe(settings: Settings) -> None:
    """On Windows/dev boxes without a system ffmpeg, use the ffprobe bundled by the static-ffmpeg package."""
    import shutil
    if shutil.which(settings.ffprobe_bin):
        return
    try:
        import static_ffmpeg  # optional dependency (server[windows] / server[dev])
        static_ffmpeg.add_paths()
    except Exception:  # noqa: BLE001 - absence is reported at upload time by validation.probe()
        return


def _renew_certificate(settings: Settings) -> None:
    """Renew the server certificate before it expires (buses verify the expiry). Checked at start and daily."""
    import threading
    from . import tls
    try:
        if tls.renew_if_needed(settings.tls_cert, settings.tls_key):
            log.warning("Certificado HTTPS renovado (mesma CA); usando o novo certificado")
        log.info("Certificado HTTPS válido por mais %d dias", tls.days_left(Path(settings.tls_cert)))
    except Exception as exc:  # noqa: BLE001
        log.error("Não foi possível verificar/renovar o certificado HTTPS: %s", exc)

    def daily():
        import os
        import time
        while True:
            time.sleep(24 * 3600)
            try:
                if tls.renew_if_needed(settings.tls_cert, settings.tls_key):
                    log.warning("Certificado HTTPS renovado; reiniciando para carregá-lo (o serviço volta sozinho)")
                    os._exit(3)
            except Exception as exc:  # noqa: BLE001
                log.error("Renovação do certificado falhou: %s", exc)
    threading.Thread(target=daily, name="tls-renew", daemon=True).start()


def main() -> None:
    import uvicorn
    settings = load_settings()
    _ensure_ffprobe(settings)
    app = create_app(settings)
    kwargs: dict = {"host": settings.host, "port": settings.port, "log_level": "info", "server_header": False}
    if settings.tls_enabled:
        _renew_certificate(settings)
        kwargs.update(ssl_certfile=settings.tls_cert, ssl_keyfile=settings.tls_key,
                      ssl_ciphers="ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!MD5:!DSS")   # TLS 1.2+ (default), PFS only
        if settings.http_redirect_port:
            hardening.start_http_redirect(settings.host, settings.http_redirect_port, settings.port,
                                          settings.ca_cert_path)
    uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()
