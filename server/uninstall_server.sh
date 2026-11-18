#!/usr/bin/env bash
# Remove o servidor Bus Video. Mantem /opt/busvideo-server/data e config, salvo com --purge.
# Uso: sudo ./uninstall_server.sh [--purge]
set -euo pipefail
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
[[ $EUID -eq 0 ]] || { echo "execute como root: sudo $0" >&2; exit 1; }
BASE=/opt/busvideo-server

echo "==> Parando e desabilitando busvideo-server"
systemctl disable --now busvideo-server.service 2>/dev/null || true
rm -f /etc/systemd/system/busvideo-server.service
systemctl daemon-reload

echo "==> Removendo codigo e ambiente virtual"
rm -rf "$BASE/app" "$BASE/venv"

if [[ $PURGE -eq 1 ]]; then
  echo "==> --purge: removendo dados, videos, configuracao e usuario"
  rm -rf "$BASE"
  userdel busvideo-server 2>/dev/null || true
  groupdel busvideo-server 2>/dev/null || true
else
  echo "==> Mantidos: $BASE/data (videos/banco) e $BASE/config (use --purge para apagar)"
fi
echo "Concluido."
