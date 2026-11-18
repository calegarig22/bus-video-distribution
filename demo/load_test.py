"""Teste de carga: simula N ônibus sincronizando com o servidor da demo.

Uso (com ./demo/run_demo.sh rodando em outro terminal; servidor e CA da demo são o padrão):
    .venv/bin/python demo/load_test.py --buses 600 --concurrency 50          # uma rodada
    .venv/bin/python demo/load_test.py --buses 600 --loop 30                 # rodadas a cada 30 s (Ctrl+C encerra)
    .venv/bin/python demo/load_test.py --reset                               # apaga os dados dos ônibus simulados
    .venv/bin/python demo/load_test.py --buses 3 --prefix GAR --loop 15      # 3 ônibus "parados na garagem", consultando a cada 15 s

Cada ônibus é um SyncAgent real (mesmo código do Raspberry) com pasta própria em demo/data/load/BUS-NNN.
O player não é executado (só o agente), e a validação por ffprobe fica desligada para não dominar a CPU do notebook.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "client"))

from busvideo_client.config import ClientConfig, load_env_file  # noqa: E402
from busvideo_client.sync import SyncAgent  # noqa: E402

_demo_ca = ROOT / "demo" / "data" / "server" / "tls" / "ca.crt"
DEFAULT_CA = str(_demo_ca) if _demo_ca.exists() else ""


def make_agent(base: Path, i: int, server: str, token: str, prefix: str = "BUS", ca_cert: str = "",
               allow_insecure_http: bool = False) -> SyncAgent:
    device_id = f"{prefix}-{i:03d}"
    cfg = ClientConfig(device_id=device_id, server_urls=[server], device_token=token, base_dir=base / device_id,
                       player="fake", validate_format="off", disk_margin_mb=0, keep_versions=1,
                       health_timeout=10, http_timeout=60, hostname=device_id.lower(), ca_cert=ca_cert,
                       allow_insecure_http=allow_insecure_http)
    cfg.ensure_dirs()
    return SyncAgent(cfg)


def run_round(agents: list[SyncAgent], concurrency: int) -> tuple[Counter, float, int]:
    t0 = time.monotonic()
    downloaded = [0]

    def one(agent: SyncAgent):
        before = agent.state.current_version
        result = agent.run_once()
        if result == "updated" and agent.state.current_version != before:
            downloaded[0] += agent.store.current_target().stat().st_size if agent.store.current_target() else 0
        return result

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = Counter(pool.map(one, agents))
    return results, time.monotonic() - t0, downloaded[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--buses", type=int, default=600)
    ap.add_argument("--concurrency", type=int, default=50, help="ônibus sincronizando ao mesmo tempo (simula chegada em ondas)")
    ap.add_argument("--server", default="https://localhost:8443")
    ap.add_argument("--token", default=None, help="DEVICE_TOKEN (padrão: lido de demo/data/server.env)")
    ap.add_argument("--ca-cert", default=DEFAULT_CA, help="ca.crt da garagem (obrigatório com servidor https://; padrão: o da demo)")
    ap.add_argument("--allow-insecure-http", action="store_true", help="aceitar servidor http:// (só demo/bancada)")
    ap.add_argument("--loop", type=int, default=0, metavar="SEG", help="repetir rodadas a cada SEG segundos (ônibus 'parados na garagem')")
    ap.add_argument("--prefix", default="BUS", help="prefixo dos identificadores (padrão BUS; use outro para não misturar com os ônibus do run_demo.sh)")
    ap.add_argument("--reset", action="store_true", help="apagar demo/data/load antes de começar")
    args = ap.parse_args()

    base = ROOT / "demo" / "data" / "load"
    if args.reset:
        shutil.rmtree(base, ignore_errors=True)
        print(f"apagado: {base}")
        if args.buses <= 0:
            return 0
    token = args.token or load_env_file(ROOT / "demo" / "data" / "server.env").get("DEVICE_TOKEN", "")
    if not token:
        print("DEVICE_TOKEN não encontrado; rode ./demo/run_demo.sh primeiro ou passe --token", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
    os.environ["BUSVIDEO_IPC_SOCKET"] = str(base / "no-ipc.sock")

    print(f"Preparando {args.buses} ônibus simulados em {base} ...")
    t0 = time.monotonic()
    agents = [make_agent(base, i, args.server, token, args.prefix, args.ca_cert, args.allow_insecure_http) for i in range(1, args.buses + 1)]
    print(f"  pronto em {time.monotonic() - t0:.1f}s")

    round_no = 0
    while True:
        round_no += 1
        results, elapsed, downloaded = run_round(agents, args.concurrency)
        versions = Counter(a.state.current_version for a in agents)
        errors = [(a.cfg.device_id, a.state.last_error) for a in agents if a.state.last_error]
        mb = downloaded / (1024 * 1024)
        print(f"\nRodada {round_no}: {args.buses} ônibus em {elapsed:.1f}s "
              f"({args.buses / max(elapsed, 1e-6):.0f} ônibus/s, concorrência {args.concurrency})")
        print(f"  resultados : {dict(results)}")
        print(f"  versões    : {dict(sorted(versions.items()))}")
        if mb:
            print(f"  baixado    : {mb:.0f} MB ({mb / max(elapsed, 1e-6):.1f} MB/s agregados)")
        if errors:
            print(f"  erros      : {len(errors)} (ex.: {errors[0]})")
        if not args.loop:
            break
        print(f"  próxima rodada em {args.loop}s (publique um vídeo novo na página e observe) ...")
        try:
            time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\nencerrado")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
