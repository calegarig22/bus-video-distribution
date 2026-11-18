#!/usr/bin/env bash
# Configura o Wi-Fi da garagem com reconexao automatica.
# Uso: sudo wifi-setup.sh SSID PSK [IFACE=wlan0]
set -euo pipefail
[[ $# -ge 2 ]] || { echo "Uso: sudo $0 SSID PSK [IFACE]" >&2; exit 2; }
SSID="$1"; PSK="$2"; IFACE="${3:-wlan0}"
[[ $EUID -eq 0 ]] || { echo "execute como root" >&2; exit 1; }
CON="busvideo-garagem"

if command -v nmcli >/dev/null && systemctl is-active NetworkManager >/dev/null 2>&1; then
  echo "==> NetworkManager: criando conexao '$CON' para SSID '$SSID' em $IFACE"
  nmcli con delete "$CON" >/dev/null 2>&1 || true
  nmcli con add type wifi ifname "$IFACE" con-name "$CON" ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
    connection.autoconnect yes connection.autoconnect-retries 0 \
    connection.autoconnect-priority 10 802-11-wireless.powersave 2 ipv4.method auto >/dev/null
  chmod 600 "/etc/NetworkManager/system-connections/$CON.nmconnection" 2>/dev/null || true
  nmcli con up "$CON" >/dev/null 2>&1 || echo "AVISO: rede fora de alcance agora; conectara automaticamente na garagem"
elif [[ -d /etc/netplan ]]; then
  FILE=/etc/netplan/60-busvideo-wifi.yaml
  echo "==> netplan: escrevendo $FILE"
  cat > "$FILE" <<YAML
network:
  version: 2
  renderer: networkd
  wifis:
    $IFACE:
      optional: true
      dhcp4: true
      access-points:
        "$SSID":
          auth:
            key-management: psk
            password: "$PSK"
YAML
  chmod 600 "$FILE"
  netplan generate
  netplan apply || echo "AVISO: netplan apply falhou; verifique o arquivo"
else
  echo "ERRO: nem NetworkManager nem netplan encontrados" >&2; exit 1
fi
echo "Wi-Fi configurado. Verifique com: iw dev $IFACE link  |  nmcli dev status"
