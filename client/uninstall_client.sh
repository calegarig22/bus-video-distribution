#!/usr/bin/env bash
# Remove o terminal Bus Video. Mantem media/state/config, salvo com --purge.
# Uso: sudo ./uninstall_client.sh [--purge]
set -euo pipefail
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
[[ $EUID -eq 0 ]] || { echo "execute como root: sudo $0" >&2; exit 1; }
BASE=/opt/busvideo-player

echo "==> Parando e desabilitando servicos"
systemctl disable --now busvideo-sync.service busvideo-player.service busvideo-wifi-powersave-off.service 2>/dev/null || true
rm -f /etc/systemd/system/busvideo-sync.service /etc/systemd/system/busvideo-player.service \
      /etc/systemd/system/busvideo-wifi-powersave-off.service /etc/tmpfiles.d/busvideo-player.conf
systemctl daemon-reload
rm -rf /run/busvideo-player

echo "==> Removendo codigo e scripts"
rm -rf "$BASE/app" "$BASE/scripts"

if [[ $PURGE -eq 1 ]]; then
  echo "==> --purge: removendo videos, estado, configuracao e usuario"
  rm -rf "$BASE"
  rm -f /etc/NetworkManager/conf.d/wifi-powersave-off.conf
  userdel busvideo 2>/dev/null || true
  groupdel busvideo 2>/dev/null || true
else
  echo "==> Mantidos: $BASE/media, $BASE/state, $BASE/config (use --purge para apagar)"
fi
echo "Concluido."
