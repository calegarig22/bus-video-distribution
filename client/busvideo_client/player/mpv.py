"""mpv controlled through its JSON IPC socket (fullscreen, DRM, hardware decode)."""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .base import Player, PlayerError

log = logging.getLogger("busvideo.player.mpv")


class MpvPlayer(Player):
    name = "mpv"

    def __init__(self, ipc_socket: Path, audio: str = "off", extra_args: str = "", binary: str = "mpv",
                 hwdec: str = "v4l2m2m-copy", vo: str = "gpu", gpu_context: str = "drm"):
        self.ipc_socket = Path(ipc_socket)
        self.audio = audio
        self.extra_args = shlex.split(extra_args) if extra_args else []
        self.binary = binary
        self.hwdec = hwdec
        self.vo = vo
        self.gpu_context = gpu_context
        self.proc: subprocess.Popen | None = None
        self._current: Path | None = None
        self._req_id = 0

    def build_command(self, path: Path) -> list[str]:
        cmd = [self.binary, "--no-config", "--fs", "--loop-file=inf", "--no-osc", "--no-osd-bar",
               "--no-terminal", "--no-input-default-bindings", "--input-vo-keyboard=no",
               "--really-quiet", "--keep-open=no", "--idle=yes", "--force-window=yes",
               f"--input-ipc-server={self.ipc_socket}", "--cache=yes", "--demuxer-max-bytes=64MiB",
               "--ytdl=no", "--load-scripts=no", "--no-input-terminal",   # só o arquivo local; nada de rede/scripts
               "--osd-level=1", "--osd-font-size=46", "--osd-margin-x=40", "--osd-margin-y=40",
               "--osd-border-size=3", "--osd-color=#FFFFFF"]   # mensagens de atualização legíveis nas telas
        if self.vo:
            cmd.append(f"--vo={self.vo}")
        if self.vo == "gpu" and self.gpu_context:
            cmd.append(f"--gpu-context={self.gpu_context}")
        if self.hwdec:
            cmd.append(f"--hwdec={self.hwdec}")
        if self.audio == "off":
            cmd.append("--audio=no")
        elif self.audio != "auto":
            cmd.append(f"--ao={self.audio}")
        cmd += self.extra_args
        cmd.append(str(path))
        return cmd

    def start(self, path: Path) -> None:
        if not shutil.which(self.binary):
            raise PlayerError(f"{self.binary} not installed")
        self.stop()
        self.ipc_socket.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.ipc_socket.unlink()
        except FileNotFoundError:
            pass
        cmd = self.build_command(path)
        log.info("Starting mpv: %s", " ".join(cmd))
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        self._current = Path(path)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise PlayerError(f"mpv exited immediately with code {self.proc.returncode}")
            if self.ipc_socket.exists():
                return
            time.sleep(0.2)
        log.warning("mpv IPC socket did not appear within 15s; continuing without IPC")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self._command(["quit"], timeout=1)
            except Exception:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.proc = None

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _command(self, command: list, timeout: float = 2.0):
        self._req_id += 1
        payload = json.dumps({"command": command, "request_id": self._req_id}) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(self.ipc_socket))
            s.sendall(payload.encode("utf-8"))
            buf = b""
            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data
                for line in buf.split(b"\n"):
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("request_id") == self._req_id:
                        if msg.get("error") not in (None, "success"):
                            raise PlayerError(f"mpv error: {msg.get('error')}")
                        return msg.get("data")
                if len(buf) > 65536:
                    buf = buf[-4096:]
        raise PlayerError("no reply from mpv")

    def get_property(self, name: str):
        try:
            return self._command(["get_property", name])
        except (OSError, PlayerError):
            return None

    def position(self) -> float | None:
        v = self.get_property("time-pos")
        return float(v) if isinstance(v, (int, float)) else None

    def duration(self) -> float | None:
        v = self.get_property("duration")
        return float(v) if isinstance(v, (int, float)) else None

    def load(self, path: Path) -> bool:
        try:
            self._command(["loadfile", str(path), "replace"], timeout=5)
        except (OSError, PlayerError) as exc:
            log.error("mpv loadfile failed: %s", exc)
            return False
        # Give mpv a moment and confirm it is actually playing the new file.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if not self.is_alive():
                return False
            current = self.get_property("path")
            idle = self.get_property("idle-active")
            if current and os.path.realpath(str(current)) == os.path.realpath(str(path)) and not idle:
                self._current = Path(path)
                return True
            if idle:
                log.error("mpv went idle after loadfile (file unplayable?)")
                return False
        log.error("mpv did not confirm playback of %s", path)
        return False
