"""Fleet deployment over the network: input parsing, the remote command, and the deploy/check flows with a fake SSH."""
import socket
import threading
from pathlib import Path

import pytest

from busvideo_server import fleet


def test_read_fleet_and_validation(tmp_path):
    f = tmp_path / "frota.csv"
    f.write_text("# numero,endereco\nBUS-001,192.168.100.51\n BUS-002 , bus002.local \n")
    buses = fleet.read_fleet(f)
    assert [(b.device_id, b.host) for b in buses] == [("BUS-001", "192.168.100.51"), ("BUS-002", "bus002.local")]
    f.write_text("BUS-001,10.0.0.1\nBUS-001,10.0.0.2\n")
    with pytest.raises(ValueError, match="repetido"):
        fleet.read_fleet(f)
    f.write_text("BUS-003\n")
    with pytest.raises(ValueError, match="inválida"):
        fleet.read_fleet(f)


def _pendrive(tmp_path) -> Path:
    pen = tmp_path / "pendrive"
    (pen / "client" / "scripts").mkdir(parents=True)
    (pen / "client" / "install_client.sh").write_text("#!/bin/bash\necho fake\n")
    (pen / "ca.crt").write_text("cert")
    (pen / "garagem.txt").write_bytes(b"\xef\xbb\xbfSERVER_URL=https://192.168.100.10\r\nDEVICE_TOKEN=tok123\r\nWIFI_SSID=GARAGEM\r\nWIFI_PSK=\r\n")
    return pen


def test_read_garage_and_install_command(tmp_path):
    g = fleet.read_garage(_pendrive(tmp_path))
    assert g.server_url == "https://192.168.100.10" and g.token == "tok123" and g.wifi_ssid == "GARAGEM"
    cmd = fleet.install_command(fleet.Bus("BUS-017", "10.0.0.17"), g, "GARAGEM", "s3nha d'agua", benchmark=True, offline_debs=False)
    assert "--device-id BUS-017" in cmd and "--server-url https://192.168.100.10" in cmd and "--token tok123" in cmd
    assert "--ca-cert /tmp/busvideo-pendrive/ca.crt" in cmd and "--wifi-psk 's3nha d'\"'\"'agua'" in cmd
    assert "benchmark-player.sh" in cmd and "--video /tmp/teste.mp4" in cmd and "hdmi_force_hotplug" in cmd
    cmd2 = fleet.install_command(fleet.Bus("BUS-018", "h"), g, "", "", benchmark=False, offline_debs=True)
    assert "--wifi" not in cmd2 and "--offline-debs /tmp/busvideo-pendrive/debs" in cmd2 and "benchmark" not in cmd2


class FakeSsh:
    """Records what would be sent to a Raspberry."""
    instances: list = []
    fail_connect: set = set()
    install_exit = 0

    def __init__(self, host, user, password, key_file, timeout=15):
        if host in FakeSsh.fail_connect:
            raise OSError("timed out")
        self.host, self.user, self.password = host, user, password
        self.commands: list[tuple[str, bool]] = []
        self.uploaded = None
        FakeSsh.instances.append(self)

    def run(self, command, sudo=False, timeout=900):
        self.commands.append((command, sudo))
        if "install_client.sh" in command:
            return FakeSsh.install_exit, "==> instalado\n"
        if "systemctl is-active busvideo-sync" in command:
            return 0, "DEVICE_ID=BUS-001\nsync=active\nplayer=active\nversion=3\nos=Ubuntu 24.04\ntemp=temp=51.0'C\n"
        return 0, ""

    def upload_dir(self, local, remote):
        self.uploaded = (Path(local), remote)

    def close(self):
        pass


def test_deploy_one_uploads_and_runs_installer_with_sudo(tmp_path):
    FakeSsh.instances.clear(); FakeSsh.fail_connect = set(); FakeSsh.install_exit = 0
    pen = _pendrive(tmp_path)
    g = fleet.read_garage(pen)
    r = fleet.deploy_one(fleet.Bus("BUS-001", "10.0.0.1"), pen, g, "pi", "raspberry", None, "GARAGEM", "psk",
                         benchmark=False, reboot=True, ssh_factory=FakeSsh)
    assert r.ok and "instalado" in r.message and "reiniciando" in r.message
    s = FakeSsh.instances[-1]
    assert s.uploaded == (pen, fleet.REMOTE_DIR)
    sudo_cmds = [c for c, sudo in s.commands if sudo]
    assert any("install_client.sh" in c and "--device-id BUS-001" in c for c in sudo_cmds)
    assert any("reboot" in c for c in sudo_cmds)
    assert s.password == "raspberry"


def test_deploy_reports_connection_and_installer_failures(tmp_path):
    FakeSsh.instances.clear(); FakeSsh.fail_connect = {"10.0.0.9"}; FakeSsh.install_exit = 0
    pen = _pendrive(tmp_path); g = fleet.read_garage(pen)
    r = fleet.deploy_one(fleet.Bus("BUS-009", "10.0.0.9"), pen, g, "pi", "x", None, "", "", False, True, ssh_factory=FakeSsh)
    assert not r.ok and "não conectou" in r.message
    FakeSsh.fail_connect = set(); FakeSsh.install_exit = 3
    r = fleet.deploy_one(fleet.Bus("BUS-010", "10.0.0.10"), pen, g, "pi", "x", None, "", "", False, True, ssh_factory=FakeSsh)
    assert not r.ok and "erro 3" in r.message and "instalado" in r.output
    assert not any("reboot" in c for c, _ in FakeSsh.instances[-1].commands)   # never reboots after a failed install


def test_check_one_parses_state():
    FakeSsh.instances.clear(); FakeSsh.fail_connect = set()
    r = fleet.check_one(fleet.Bus("BUS-001", "10.0.0.1"), "pi", "x", None, ssh_factory=FakeSsh)
    assert r.ok and "BUS-001" in r.message and "sync active" in r.message and "versão 3" in r.message


def test_discover_finds_open_ssh_port_on_localhost():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
    port = srv.getsockname()[1]
    def serve():
        try:
            while True:
                srv.accept()[0].close()
        except OSError:
            pass
    t = threading.Thread(target=serve, daemon=True); t.start()
    try:
        found = fleet.discover("127.0.0.1/32", port=port, timeout=1)
        assert [ip for ip, _ in found] == ["127.0.0.1"]
        assert fleet.discover("127.0.0.1/32", port=1, timeout=0.3) == []
    finally:
        srv.close()
