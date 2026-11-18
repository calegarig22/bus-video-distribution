"""provision.sh (boot provisioning for cloned SD cards), exercised in dry-run mode with bash."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "provision.sh"
pytestmark = pytest.mark.skipif(sys.platform.startswith("win") or not shutil.which("bash"), reason="needs bash")


def run(tmp_path, provision_text=None, device_id="BUS-MESTRE", pending=True):
    base, boot = tmp_path / "base", tmp_path / "boot"
    for d in ("config", "state", "logs", "scripts"):
        (base / d).mkdir(parents=True, exist_ok=True)
    boot.mkdir(exist_ok=True)
    (base / "config" / "client.env").write_text(f"DEVICE_ID={device_id}\nSERVER_URLS=https://10.0.0.1\nDEVICE_TOKEN=t\nWIFI_IFACE=wlan0\n")
    (base / "state" / "state.json").write_text("{}")
    (base / "scripts" / "wifi-setup.sh").write_text("#!/bin/sh\nexit 0\n")
    if pending:
        (base / "config" / ".provision-pending").touch()
    if provision_text is not None:
        (boot / "busvideo-provision.txt").write_bytes(provision_text.encode())
    env = {**os.environ, "DRY_RUN": "1", "BUSVIDEO_BASE": str(base), "BUSVIDEO_BOOT_DIR": str(boot)}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    conf = dict(l.split("=", 1) for l in (base / "config" / "client.env").read_text().splitlines() if "=" in l)
    return conf, boot, base, r.stdout


def test_provision_file_sets_identity_and_is_consumed(tmp_path):
    conf, boot, base, out = run(tmp_path, "# bus 17\r\nDEVICE_ID = BUS-017\r\nWIFI_SSID=GARAGEM\r\nWIFI_PSK=\"segredo\"\r\nSERVER_URLS=https://192.168.100.10\r\n")
    assert conf["DEVICE_ID"] == "BUS-017" and conf["SERVER_URLS"] == "https://192.168.100.10"
    assert not (boot / "busvideo-provision.txt").exists() and (boot / "busvideo-provision.done").exists()
    assert "segredo" not in (boot / "busvideo-provision.done").read_text()      # Wi-Fi password not left on the boot partition
    assert not (base / "config" / ".provision-pending").exists()
    assert "hostname=bus-017" in out and "wifi-setup.sh GARAGEM segredo" in out


def test_clone_without_file_gets_a_unique_provisional_id(tmp_path):
    conf, _, _, out = run(tmp_path, None)
    assert conf["DEVICE_ID"].startswith("NOVO-") and len(conf["DEVICE_ID"]) == 11
    assert "identidade provisoria" in out


def test_invalid_device_id_is_rejected(tmp_path):
    conf, _, _, out = run(tmp_path, "DEVICE_ID=../etc/passwd\n")
    assert "invalido" in out and conf["DEVICE_ID"] != "../etc/passwd"


def test_named_bus_is_left_alone_when_no_file(tmp_path):
    conf, _, _, _ = run(tmp_path, None, device_id="BUS-042", pending=False)
    assert conf["DEVICE_ID"] == "BUS-042"
