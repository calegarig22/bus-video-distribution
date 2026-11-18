"""Tela de ônibus para demonstração: um ônibus simulado com a "tela" num navegador.

Roda o mesmo agente de sincronização do Raspberry (player fake) e abre uma página em tela cheia que toca o
vídeo atual em loop, mostra o número do ônibus e a versão, e troca para a versão nova no fim do ciclo,
exatamente como o player de bordo faz. Serve para ver, no notebook, o ônibus "pegar" o vídeo publicado.

Uso:
    .venv/bin/python demo/bus_screen.py                                   # contra a demo local (https://localhost:8443)
    .venv/bin/python demo/bus_screen.py --server https://192.168.100.8 --token TOKEN --ca-cert ca.crt --device-id CASA-TELA
    .venv/bin/python demo/bus_screen.py --port 8092 --device-id CASA-TELA-2   # segunda tela na mesma máquina

A página abre sozinha em http://localhost:<porta>. Tecle F (ou o botão) para tela cheia. Ctrl+C encerra.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "client"))

from busvideo_client.config import ClientConfig, load_env_file  # noqa: E402
from busvideo_client.sync import SyncAgent  # noqa: E402

_demo_ca = ROOT / "demo" / "data" / "server" / "tls" / "ca.crt"
DEFAULT_CA = str(_demo_ca) if _demo_ca.exists() else ""

PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{device_id}</title>
<style>
  [hidden]{{display:none!important}}
  html,body{{margin:0;height:100%;background:#000;color:#fff;font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow:hidden}}
  video{{position:fixed;inset:0;width:100%;height:100%;object-fit:contain;background:#000}}
  .hud{{position:fixed;left:18px;bottom:18px;background:rgba(0,0,0,.62);border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:12px 16px;min-width:340px;backdrop-filter:blur(6px)}}
  .hud b{{font-size:22px;letter-spacing:.02em}} .hud .v{{font-size:40px;font-weight:800;line-height:1;margin:6px 0}}
  .hud small{{color:#bcd;font-size:13px;display:block;margin-top:4px}}
  .badge{{display:inline-block;margin-top:8px;padding:6px 10px;border-radius:999px;font-weight:700;font-size:14px;background:#1f9d55}}
  .badge.pend{{background:#c77700}} .badge.err{{background:#b3261e}}
  .wait{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font-size:28px;color:#9ab;text-align:center;padding:40px}}
  button{{margin-top:8px;margin-right:6px;background:#0b6bcb;color:#fff;border:0;border-radius:8px;padding:8px 12px;font-weight:700;cursor:pointer}}
  .tag{{position:fixed;top:14px;right:16px;background:rgba(0,0,0,.55);padding:6px 12px;border-radius:8px;font-size:13px;color:#cde}}
  .osd{{position:fixed;top:40px;left:40px;max-width:70%;background:rgba(0,0,0,.7);color:#fff;font-size:42px;font-weight:700;padding:14px 22px;border-radius:12px;text-shadow:0 2px 6px #000;border:2px solid rgba(255,255,255,.35)}}
</style></head><body>
<video id="v" autoplay muted playsinline hidden></video>
<div id="wait" class="wait">Aguardando o primeiro vídeo da garagem…</div>
<div class="tag">tela do ônibus · demonstração · servidor {server}</div>
<div id="osd" class="osd" hidden></div>
<div class="hud">
  <b>🚌 {device_id}</b>
  <div class="v">versão <span id="ver">–</span></div>
  <span id="badge" class="badge">exibindo</span>
  <small id="sync">consultando a garagem…</small>
  <div><button onclick="switchNow()" id="btn" hidden>Trocar agora</button><button onclick="fs()">Tela cheia (F)</button></div>
</div>
<script>
const osd=document.getElementById('osd'); let osdUntil=0;
const v=document.getElementById('v'), wait=document.getElementById('wait'), ver=document.getElementById('ver'),
      badge=document.getElementById('badge'), sync=document.getElementById('sync'), btn=document.getElementById('btn');
let playing=0, pending=0;
function fs(){{ (document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen()); }}
document.addEventListener('keydown',e=>{{ if(e.key==='f'||e.key==='F') fs(); }});
function load(n){{ playing=n; pending=0; v.src='/video?v='+n+'&t='+Date.now(); v.hidden=false; wait.hidden=true; v.play().catch(()=>{{}});
  ver.textContent=n; badge.textContent='exibindo'; badge.className='badge'; btn.hidden=true; }}
function switchNow(){{ if(pending) load(pending); }}
v.addEventListener('ended',()=>{{ if(pending) load(pending); else {{ v.currentTime=0; v.play(); }} }});
async function poll(){{
  try{{
    const s=await (await fetch('/state')).json();
    sync.textContent='última consulta '+s.last_sync_local+' · '+s.last_result+(s.last_error?' · '+s.last_error:'');
    if(s.message && s.message_until>Date.now()/1000){{ osd.textContent=s.message; osd.hidden=false; }} else {{ osd.hidden=true; }}
    if(s.version>0 && playing===0) load(s.version);
    else if(s.version>0 && s.version!==playing && pending!==s.version){{
      pending=s.version; badge.textContent='versão '+s.version+' recebida e conferida · troca ao fim do vídeo'; badge.className='badge pend'; btn.hidden=false; }}
    if(s.last_error){{ badge.className='badge err'; }}
  }}catch(e){{ sync.textContent='sem resposta do agente'; }}
}}
setInterval(poll,2000); poll();
</script></body></html>"""


class Screen:
    def __init__(self, agent: SyncAgent, interval: int):
        self.agent, self.interval = agent, interval
        self.last_result, self.last_sync = "", ""
        self.message, self.message_until = "", 0.0
        self.lock = threading.Lock()
        agent.on_message = self._on_message

    def _on_message(self, text: str, seconds: float) -> None:
        with self.lock:
            self.message, self.message_until = text, time.time() + seconds

    def loop(self):
        while True:
            try:
                r = self.agent.run_once()
            except Exception as exc:  # noqa: BLE001
                r = f"erro: {exc}"
            with self.lock:
                self.last_result, self.last_sync = r, time.strftime("%H:%M:%S")
            time.sleep(self.interval)

    def state(self) -> dict:
        with self.lock:
            return {"device_id": self.agent.cfg.device_id, "version": self.agent.state.current_version,
                    "last_result": self.last_result, "last_sync_local": self.last_sync,
                    "last_error": self.agent.state.last_error or "",
                    "message": self.message, "message_until": self.message_until}

    def video_path(self) -> Path | None:
        t = self.agent.store.current_target()
        return t if t and t.exists() else None


def make_handler(screen: Screen, server_label: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencia o log de acesso
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                body = PAGE.format(device_id=screen.agent.cfg.device_id, server=server_label).encode()
                self._send(200, "text/html; charset=utf-8", body)
            elif path == "/state":
                self._send(200, "application/json", json.dumps(screen.state()).encode())
            elif path == "/video":
                self._video()
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _video(self):
            p = screen.video_path()
            if not p:
                return self._send(404, "text/plain", b"sem video")
            size = p.stat().st_size
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if (a and b) else size - 1
                end = min(end, size - 1)
            length = end - start + 1
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(p, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)
    return H


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="https://localhost:8443")
    ap.add_argument("--token", default=None, help="DEVICE_TOKEN (padrão: lido de demo/data/server.env)")
    ap.add_argument("--ca-cert", default=DEFAULT_CA, help="ca.crt da garagem (obrigatório com servidor https://; padrão: o da demo)")
    ap.add_argument("--allow-insecure-http", action="store_true", help="aceitar servidor http:// (só demo/bancada)")
    ap.add_argument("--device-id", default="BUS-TELA")
    ap.add_argument("--interval", type=int, default=15, help="segundos entre consultas à garagem")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    token = args.token or load_env_file(ROOT / "demo" / "data" / "server.env").get("DEVICE_TOKEN", "")
    if not token:
        print("DEVICE_TOKEN não encontrado; passe --token ou rode ./demo/run_demo.sh antes", file=sys.stderr)
        return 1
    base = ROOT / "demo" / "data" / "screen" / args.device_id
    os.environ["BUSVIDEO_IPC_SOCKET"] = str(base / "no-ipc.sock")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = ClientConfig(device_id=args.device_id, server_urls=[args.server], device_token=token, base_dir=base,
                       player="fake", validate_format="auto", disk_margin_mb=0, keep_versions=2,
                       health_timeout=10, http_timeout=120, hostname=args.device_id.lower(), ca_cert=args.ca_cert,
                       allow_insecure_http=args.allow_insecure_http)
    cfg.ensure_dirs()
    screen = Screen(SyncAgent(cfg), args.interval)
    threading.Thread(target=screen.loop, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(screen, args.server))
    url = f"http://localhost:{args.port}"
    print(f"Tela do ônibus {args.device_id}: {url}  (garagem: {args.server}; consulta a cada {args.interval}s)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
