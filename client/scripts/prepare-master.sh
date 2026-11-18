#!/usr/bin/env bash
# Prepara este Raspberry (ja instalado e TESTADO) para virar a IMAGEM-MESTRE dos outros onibus.
#
#   sudo /opt/busvideo-player/scripts/prepare-master.sh            # limpa identidade e desliga
#   sudo /opt/busvideo-player/scripts/prepare-master.sh --no-off   # so limpa, nao desliga
#
# Depois: retire o cartao, grave a imagem (dd / Win32DiskImager) e escreva-a nos outros cartoes.
# Cada cartao novo recebe um busvideo-provision.txt na particao de boot com o DEVICE_ID do onibus.
# O que fica na imagem: programa, configuracao (servidor, token, CA, Wi-Fi), video inicial.
# O que sai: identidade do onibus, estado, logs, chaves SSH do host, machine-id.
set -euo pipefail
BASE=/opt/busvideo-player; CONF="$BASE/config/client.env"
[[ $EUID -eq 0 ]] || { echo "execute como root: sudo $0" >&2; exit 1; }
[[ -f "$CONF" ]] || { echo "cliente nao instalado ($CONF ausente)" >&2; exit 1; }
OFF=1; [[ "${1:-}" == "--no-off" ]] && OFF=0

echo "==> Parando servicos"
systemctl stop busvideo-sync.service busvideo-player.service 2>/dev/null || true
echo "==> Limpando identidade e estado"
sed -i -E 's/^DEVICE_ID=.*/DEVICE_ID=BUS-MESTRE/' "$CONF"
rm -rf "$BASE/state"/*.json "$BASE/logs"/* "$BASE/media/download"/* 2>/dev/null || true
touch "$BASE/config/.provision-pending"
rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
: > /etc/machine-id; rm -f /var/lib/dbus/machine-id
hostnamectl set-hostname busvideo-onibus 2>/dev/null || echo busvideo-onibus > /etc/hostname
rm -f /boot/firmware/busvideo-provision.txt /boot/firmware/busvideo-provision.done 2>/dev/null || true
journalctl --rotate >/dev/null 2>&1 || true; journalctl --vacuum-time=1s >/dev/null 2>&1 || true
echo "==> Pronto para gerar a imagem. Video inicial mantido: $(readlink "$BASE/media/current.mp4" 2>/dev/null || echo nenhum)"
sync
if [[ $OFF -eq 1 ]]; then echo "==> Desligando em 5 s; depois retire o cartao."; sleep 5; poweroff; fi
