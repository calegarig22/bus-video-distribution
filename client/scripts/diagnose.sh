#!/usr/bin/env bash
# Diagnostico READ-ONLY do Raspberry Pi para o projeto Bus Video.
# Uso: sudo diagnose.sh   (sem sudo funciona, com menos informacao)
# Saida: tela + /tmp/busvideo-diagnose-<data>.txt  (envie este arquivo para a equipe tecnica)
set -uo pipefail
OUT="/tmp/busvideo-diagnose-$(date +%Y%m%d-%H%M%S).txt"
exec > >(tee "$OUT") 2>&1

section() { echo; echo "################ $* ################"; }
run() { echo "\$ $*"; "$@" 2>&1 || echo "(indisponivel / erro $?)"; }
has() { command -v "$1" >/dev/null 2>&1; }

section "SISTEMA"
run lsb_release -a
run uname -mr
run cat /proc/device-tree/model
run systemctl get-default
run uptime
run free -m
run nproc

section "FIRMWARE / config.txt"
for f in /boot/firmware/config.txt /boot/config.txt; do
  [[ -f $f ]] && { echo "--- $f"; grep -E '^\s*(dtoverlay|gpu_mem|hdmi_|dtparam=audio|arm_64bit|max_framebuffers|disable_overscan)' "$f"; }
done
for f in /boot/firmware/cmdline.txt /boot/cmdline.txt; do [[ -f $f ]] && { echo "--- $f"; cat "$f"; }; done

section "GPU / VIDEO (DRM, V4L2, decodificador HW)"
run ls -l /dev/dri /dev/video* 
has v4l2-ctl && run v4l2-ctl --list-devices
has ffmpeg && { echo "\$ ffmpeg decoders v4l2m2m"; ffmpeg -hide_banner -decoders 2>/dev/null | grep -i v4l2m2m || echo "(nenhum decoder v4l2m2m)"; }
has mpv && { run bash -c "mpv --version | head -3"; echo "\$ mpv --vo=help"; mpv --vo=help 2>/dev/null; echo "\$ mpv --hwdec=help"; mpv --hwdec=help 2>/dev/null; }
has gst-inspect-1.0 && { echo "\$ gstreamer v4l2/kms"; gst-inspect-1.0 2>/dev/null | grep -Ei 'v4l2h264dec|kmssink' || echo "(sem plugins)"; }
has vcgencmd && { run vcgencmd get_throttled; run vcgencmd measure_temp; run vcgencmd get_mem gpu; run vcgencmd get_mem arm; }
echo "kmsprint: $(has kmsprint && echo sim || echo nao)   modetest: $(has modetest && echo sim || echo nao)"
for c in /sys/class/drm/card*-*; do
  [[ -d $c ]] && echo "$(basename "$c"): status=$(cat "$c/status" 2>/dev/null) enabled=$(cat "$c/enabled" 2>/dev/null) edid=$(stat -c %s "$c/edid" 2>/dev/null) bytes modes=$(head -3 "$c/modes" 2>/dev/null | tr '\n' ' ')"
done
has kmsprint && run kmsprint
has tvservice && run tvservice -s

section "REDE"
run ls -l /etc/netplan
for f in /etc/netplan/*.yaml; do [[ -f $f ]] && { echo "--- $f"; sed -E 's/(password:).*/\1 ****/' "$f"; }; done
run systemctl is-active NetworkManager systemd-networkd wpa_supplicant
has nmcli && { run nmcli dev status; run nmcli -t -f NAME,TYPE,AUTOCONNECT con show; }
has iw && { run iw dev; for i in $(iw dev 2>/dev/null | awk '/Interface/{print $2}'); do run iw dev "$i" get power_save; run iw dev "$i" link; done; }
run ip -br addr
run cat /etc/hostname
run bash -c "getent hosts busvideo-server busvideo-server.local || echo '(busvideo-server nao resolve)'"
run systemctl is-active avahi-daemon

section "ARMAZENAMENTO"
run df -h / /opt /boot/firmware
run mount | grep -E ' / |/opt'
for k in name oemid manfid serial date; do [[ -f /sys/block/mmcblk0/device/$k ]] && echo "sdcard $k: $(cat /sys/block/mmcblk0/device/$k)"; done
run ls -la /opt/busvideo-player/media /opt/busvideo-player/media/versions
[[ -f /opt/busvideo-player/state/state.json ]] && run cat /opt/busvideo-player/state/state.json

section "SERVICOS E PROCESSOS EXISTENTES"
run systemctl list-units --type=service --state=running --no-pager
run bash -c "crontab -l 2>/dev/null; ls /etc/cron.d 2>/dev/null"
run bash -c "ls -la /etc/xdg/autostart ~/.config/autostart /home/*/.config/autostart 2>/dev/null"
run bash -c "ps aux | grep -Ei 'mpv|vlc|omxplayer|gst|chromium|X|wayland|kodi' | grep -v grep"
has fuser && run bash -c "fuser -v /dev/dri/* /dev/video* /dev/fb0 2>&1"
has aplay && run aplay -l

section "USUARIOS / ACESSO"
run id
run bash -c "getent group sudo video render input audio"
run systemctl is-active ssh sshd
run bash -c "grep -E '^(PasswordAuthentication|PermitRootLogin)' /etc/ssh/sshd_config 2>/dev/null"

section "BusVideo (se instalado)"
for u in busvideo-player busvideo-sync; do
  if systemctl cat "$u" >/dev/null 2>&1; then
    run systemctl status "$u" --no-pager -l
    run journalctl -u "$u" -n 30 --no-pager
  else
    echo "$u: nao instalado"
  fi
done
[[ -f /opt/busvideo-player/config/client.env ]] && { echo "--- client.env (segredos ocultos)"; sed -E 's/^(DEVICE_TOKEN|WIFI_PSK)=.*/\1=****/' /opt/busvideo-player/config/client.env; }

echo; echo "Relatorio salvo em: $OUT"
