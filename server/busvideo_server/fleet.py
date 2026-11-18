"""Instalação e verificação da frota PELA REDE, a partir do PC da garagem, para ônibus que já têm Raspberry.

Em vez de tirar o cartão de cada ônibus, o PC entra em cada Raspberry por SSH (acesso remoto), copia o programa
e o certificado, roda o instalador com o número do ônibus e reinicia. Condições: o Raspberry está na rede da
garagem, aceita SSH e você sabe o usuário e a senha dele (normalmente iguais em todos).

    python -m busvideo_server.fleet descobrir --rede 192.168.100.0/24             # lista os aparelhos com SSH ligado
    python -m busvideo_server.fleet instalar --lista frota.csv --usuario pi         # instala em todos da lista
    python -m busvideo_server.fleet verificar --lista frota.csv --usuario pi        # mostra o estado de cada um
    python -m busvideo_server.fleet instalar --lista frota.csv --usuario pi --so BUS-001 --benchmark   # o primeiro, com teste

frota.csv: uma linha por ônibus, "numero,endereco" (endereco = IP ou nome na rede):
    BUS-001,192.168.100.51
    BUS-002,192.168.100.52

A pasta "pendrive" gerada pelo instalador do servidor (client, ca.crt, garagem.txt) é o que se envia.
No Windows: C:\\BusVideo\\frota.bat instalar --lista C:\\BusVideo\\frota.csv --usuario pi
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import getpass
import io
import ipaddress
import os
import shlex
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REMOTE_DIR = "/tmp/busvideo-pendrive"


@dataclass
class Bus:
    device_id: str
    host: str


@dataclass
class Result:
    bus: Bus
    ok: bool
    message: str
    output: str = ""
    seconds: float = 0.0


@dataclass
class Garage:
    server_url: str = ""
    token: str = ""
    wifi_ssid: str = ""
    wifi_psk: str = ""
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- entrada
def read_fleet(path: Path) -> list[Bus]:
    buses: list[Bus] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().startswith("#"):
                continue
            if len(row) < 2:
                raise ValueError(f"linha inválida em {path}: {row!r} (esperado: NUMERO,ENDERECO)")
            dev, host = row[0].strip(), row[1].strip()
            if not dev or not host:
                raise ValueError(f"linha inválida em {path}: {row!r}")
            buses.append(Bus(dev, host))
    if not buses:
        raise ValueError(f"{path}: nenhum ônibus listado")
    dup = {b.device_id for b in buses if sum(x.device_id == b.device_id for x in buses) > 1}
    if dup:
        raise ValueError(f"{path}: número repetido: {', '.join(sorted(dup))}")
    return buses


def read_garage(pendrive: Path) -> Garage:
    g = Garage()
    info = pendrive / "garagem.txt"
    if info.exists():
        for raw in info.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            if k in ("SERVER_URL", "SERVER_URLS"):
                g.server_url = v
            elif k == "DEVICE_TOKEN":
                g.token = v
            elif k == "WIFI_SSID":
                g.wifi_ssid = v
            elif k == "WIFI_PSK":
                g.wifi_psk = v
    return g


def install_command(bus: Bus, g: Garage, wifi_ssid: str, wifi_psk: str, benchmark: bool, offline_debs: bool) -> str:
    """The exact shell that runs on the Raspberry (stdin carries the sudo password)."""
    args = ["--device-id", bus.device_id, "--server-url", g.server_url, "--token", g.token,
            "--ca-cert", f"{REMOTE_DIR}/ca.crt"]
    if wifi_ssid and wifi_psk:
        args += ["--wifi-ssid", wifi_ssid, "--wifi-psk", wifi_psk]
    if offline_debs:
        args += ["--offline-debs", f"{REMOTE_DIR}/debs"]
    parts = [f"cd {REMOTE_DIR}/client"]
    parts.append("(grep -q '^hdmi_force_hotplug=1' /boot/firmware/config.txt 2>/dev/null || echo hdmi_force_hotplug=1 >> /boot/firmware/config.txt) 2>/dev/null; "
                 "(grep -q '^gpu_mem=' /boot/firmware/config.txt 2>/dev/null || echo gpu_mem=128 >> /boot/firmware/config.txt) 2>/dev/null; true")
    if benchmark:
        parts.append("bash scripts/make-test-video.sh /tmp/teste.mp4 60 1920x1080 && bash scripts/benchmark-player.sh /tmp/teste.mp4 120 || echo 'AVISO: benchmark nao concluiu'")
        args += ["--video", "/tmp/teste.mp4"]
    parts.append("bash ./install_client.sh " + " ".join(shlex.quote(a) for a in args))
    return " && ".join(parts)


# ----------------------------------------------------------------------------- ssh
class Ssh:
    """Thin wrapper over paramiko so the rest of the module can be tested with a fake."""

    def __init__(self, host: str, user: str, password: str | None, key_file: str | None, timeout: int = 15):
        import paramiko
        self.host, self.user, self.password = host, user, password
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())   # rede local da garagem
        self.client.connect(host, username=user, password=password, key_filename=key_file, timeout=timeout,
                            banner_timeout=timeout, auth_timeout=timeout, allow_agent=bool(key_file), look_for_keys=bool(key_file))

    def run(self, command: str, sudo: bool = False, timeout: int = 900) -> tuple[int, str]:
        if sudo:
            command = f"sudo -S -p '' bash -c {shlex.quote(command)}"
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout, get_pty=False)
        if sudo:
            stdin.write((self.password or "") + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")
        return stdout.channel.recv_exit_status(), out

    def upload_dir(self, local: Path, remote: str) -> None:
        sftp = self.client.open_sftp()
        try:
            self._mkdir(sftp, remote)
            for root, dirs, files in os.walk(local):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                rel = os.path.relpath(root, local)
                rdir = remote if rel == "." else f"{remote}/{rel.replace(os.sep, '/')}"
                self._mkdir(sftp, rdir)
                for name in files:
                    if name.endswith(".pyc"):
                        continue
                    data = Path(root, name).read_bytes()
                    if name.endswith((".sh", ".py", ".service", ".conf", ".txt", ".example")):
                        data = data.replace(b"\r\n", b"\n")
                    with sftp.open(f"{rdir}/{name}", "wb") as fh:
                        fh.write(data)
        finally:
            sftp.close()

    @staticmethod
    def _mkdir(sftp, path: str) -> None:
        try:
            sftp.stat(path)
        except OSError:
            sftp.mkdir(path)

    def close(self) -> None:
        self.client.close()


# ----------------------------------------------------------------------------- ações
def deploy_one(bus: Bus, pendrive: Path, g: Garage, user: str, password: str | None, key_file: str | None,
               wifi_ssid: str, wifi_psk: str, benchmark: bool, reboot: bool, ssh_factory=Ssh) -> Result:
    t0 = time.monotonic()
    try:
        ssh = ssh_factory(bus.host, user, password, key_file)
    except Exception as exc:  # noqa: BLE001
        return Result(bus, False, f"não conectou por SSH: {exc}", seconds=time.monotonic() - t0)
    try:
        ssh.run(f"rm -rf {REMOTE_DIR}; mkdir -p {REMOTE_DIR}")
        ssh.upload_dir(pendrive, REMOTE_DIR)
        ssh.run(f"chmod +x {REMOTE_DIR}/client/*.sh {REMOTE_DIR}/client/scripts/*.sh 2>/dev/null; true")
        offline = (pendrive / "debs").is_dir()
        code, out = ssh.run(install_command(bus, g, wifi_ssid, wifi_psk, benchmark, offline), sudo=True)
        if code != 0:
            return Result(bus, False, f"instalador terminou com erro {code}", out, time.monotonic() - t0)
        ssh.run(f"rm -rf {REMOTE_DIR}")
        if reboot:
            ssh.run("nohup sh -c 'sleep 2; reboot' >/dev/null 2>&1 &", sudo=True, timeout=10)
        return Result(bus, True, "instalado" + (" e reiniciando" if reboot else ""), out, time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001
        return Result(bus, False, f"falha: {exc}", seconds=time.monotonic() - t0)
    finally:
        try:
            ssh.close()
        except Exception:  # noqa: BLE001
            pass


def check_one(bus: Bus, user: str, password: str | None, key_file: str | None, ssh_factory=Ssh) -> Result:
    t0 = time.monotonic()
    try:
        ssh = ssh_factory(bus.host, user, password, key_file)
    except Exception as exc:  # noqa: BLE001
        return Result(bus, False, f"não conectou por SSH: {exc}", seconds=time.monotonic() - t0)
    try:
        cmd = ("echo DEVICE_ID=$(sed -nE 's/^DEVICE_ID=(.*)$/\\1/p' /opt/busvideo-player/config/client.env 2>/dev/null); "
               "echo sync=$(systemctl is-active busvideo-sync 2>/dev/null); echo player=$(systemctl is-active busvideo-player 2>/dev/null); "
               "echo version=$(python3 -c \"import json;print(json.load(open('/opt/busvideo-player/state/state.json'))['current_version'])\" 2>/dev/null); "
               "echo os=$(. /etc/os-release && echo $PRETTY_NAME); echo temp=$(vcgencmd measure_temp 2>/dev/null)")
        code, out = ssh.run(cmd)
        info = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        installed = info.get("sync") == "active"
        msg = (f"{info.get('DEVICE_ID') or '(sem instalação)'} · sync {info.get('sync') or '-'} · player {info.get('player') or '-'} "
               f"· versão {info.get('version') or '-'} · {info.get('os') or ''} {info.get('temp') or ''}")
        return Result(bus, installed, msg, out, time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001
        return Result(bus, False, f"falha: {exc}", seconds=time.monotonic() - t0)
    finally:
        ssh.close()


def discover(network: str, port: int = 22, timeout: float = 0.5, workers: int = 64) -> list[tuple[str, str]]:
    """Hosts on the network with the SSH port open, with their names when the router knows them."""
    net = ipaddress.ip_network(network, strict=False)
    hosts = [str(h) for h in net.hosts()]

    def probe(ip: str):
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                pass
        except OSError:
            return None
        try:
            name = socket.gethostbyaddr(ip)[0]
        except OSError:
            name = ""
        return ip, name

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        found = [r for r in pool.map(probe, hosts) if r]
    return found


def print_results(results: list[Result]) -> None:
    ok = sum(1 for r in results if r.ok)
    print()
    print(f"{'ÔNIBUS':<12} {'ENDEREÇO':<18} {'RESULTADO':<8} DETALHE")
    for r in results:
        print(f"{r.bus.device_id:<12} {r.bus.host:<18} {'OK' if r.ok else 'FALHOU':<8} {r.message}  ({r.seconds:.0f}s)")
    print(f"\n{ok} de {len(results)} concluídos.")
    for r in results:
        if not r.ok and r.output:
            print(f"\n--- saída de {r.bus.device_id} ({r.bus.host}) ---")
            print("\n".join(r.output.splitlines()[-25:]))


# ----------------------------------------------------------------------------- CLI
def default_pendrive() -> Path:
    for cand in (Path(r"C:\BusVideo\pendrive"), Path("/opt/busvideo-server/pendrive"), Path("pendrive")):
        if cand.is_dir():
            return cand
    return Path("pendrive")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="busvideo_server.fleet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("descobrir", help="lista aparelhos com SSH ligado na rede")
    d.add_argument("--rede", required=True, help="ex.: 192.168.100.0/24")
    for name in ("instalar", "verificar"):
        s = sub.add_parser(name)
        s.add_argument("--lista", required=True, help="frota.csv: NUMERO,ENDERECO por linha")
        s.add_argument("--usuario", required=True, help="usuário SSH dos Raspberries (ex.: pi, ubuntu)")
        s.add_argument("--senha", default=None, help="senha SSH (se omitida, será perguntada)")
        s.add_argument("--chave", default=None, help="arquivo de chave SSH em vez de senha")
        s.add_argument("--so", default=None, help="agir só neste ônibus (ex.: BUS-001)")
        s.add_argument("--paralelo", type=int, default=4, help="quantos ao mesmo tempo (padrão 4)")
        if name == "instalar":
            s.add_argument("--pendrive", default=None, help="pasta pendrive (padrão: C:\\BusVideo\\pendrive ou /opt/busvideo-server/pendrive)")
            s.add_argument("--wifi-ssid", default=None, help="Wi-Fi da garagem a gravar no ônibus (padrão: o de garagem.txt, se houver)")
            s.add_argument("--wifi-psk", default=None)
            s.add_argument("--benchmark", action="store_true", help="roda o teste de reprodução Full HD antes de instalar (use no primeiro)")
            s.add_argument("--sem-reiniciar", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "descobrir":
        print(f"Procurando aparelhos com SSH em {a.rede} ...")
        found = discover(a.rede)
        if not found:
            print("nenhum aparelho com SSH encontrado (os Raspberries estão na rede? SSH está ligado neles?)")
            return 1
        print(f"\n{'ENDEREÇO':<18} NOME\n" + "\n".join(f"{ip:<18} {name}" for ip, name in found))
        print("\nMonte o frota.csv com uma linha por ônibus: NUMERO,ENDERECO  (ex.: BUS-001,192.168.100.51)")
        return 0

    buses = read_fleet(Path(a.lista))
    if a.so:
        buses = [b for b in buses if b.device_id == a.so]
        if not buses:
            print(f"{a.so} não está em {a.lista}", file=sys.stderr)
            return 2
    password = a.senha
    if not a.chave and password is None:
        password = getpass.getpass(f"Senha SSH do usuário {a.usuario} nos Raspberries: ")

    if a.cmd == "verificar":
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.paralelo) as pool:
            results = list(pool.map(lambda b: check_one(b, a.usuario, password, a.chave), buses))
        print_results(results)
        return 0 if all(r.ok for r in results) else 1

    pendrive = Path(a.pendrive) if a.pendrive else default_pendrive()
    for need in ("client/install_client.sh", "ca.crt"):
        if not (pendrive / need).exists():
            print(f"pasta pendrive incompleta: falta {pendrive / need}. Rode o instalador do servidor de novo.", file=sys.stderr)
            return 2
    g = read_garage(pendrive)
    if not g.server_url or not g.token:
        print(f"{pendrive / 'garagem.txt'} sem SERVER_URL/DEVICE_TOKEN. Rode o instalador do servidor de novo.", file=sys.stderr)
        return 2
    wifi_ssid = a.wifi_ssid if a.wifi_ssid is not None else g.wifi_ssid
    wifi_psk = a.wifi_psk if a.wifi_psk is not None else g.wifi_psk
    if wifi_ssid and not wifi_psk:
        wifi_psk = getpass.getpass(f"Senha do Wi-Fi {wifi_ssid} (Enter para não gravar Wi-Fi): ")
    print(f"Instalando em {len(buses)} ônibus a partir de {pendrive} → {g.server_url}"
          + (f", Wi-Fi {wifi_ssid}" if wifi_ssid and wifi_psk else ", sem alterar o Wi-Fi") + (" (com benchmark)" if a.benchmark else ""))
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.paralelo) as pool:
        results = list(pool.map(lambda b: deploy_one(b, pendrive, g, a.usuario, password, a.chave, wifi_ssid, wifi_psk,
                                                     a.benchmark, not a.sem_reiniciar), buses))
    print_results(results)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
