#!/usr/bin/env bash
# Provisionamento automatico no boot (busvideo-provision.service).
#
# Permite instalar os onibus por CLONAGEM do cartao SD, sem monitor nem teclado em cada um:
#   1. O primeiro Raspberry e instalado e testado; roda-se prepare-master.sh e grava-se a imagem do cartao.
#   2. Cada cartao novo recebe a imagem e, na particao de boot (visivel em qualquer PC), um arquivo
#      busvideo-provision.txt com o numero do onibus:
#          DEVICE_ID=BUS-017
#          # opcionais: WIFI_SSID=GARAGEM_EXEMPLO  WIFI_PSK=senha  SERVER_URLS=https://192.168.100.10
#   3. No primeiro boot este script aplica o arquivo, renomeia-o para busvideo-provision.done e o onibus se
#      registra na garagem com a identidade certa. Sem arquivo, um clone recebe o nome NOVO-<serial>.
#
# Variaveis para teste (dry-run fora do Pi): BUSVIDEO_BOOT_DIR, BUSVIDEO_BASE, DRY_RUN=1
set -euo pipefail
BASE="${BUSVIDEO_BASE:-/opt/busvideo-player}"
CONF="$BASE/config/client.env"
MARKER="$BASE/config/.provision-pending"
BOOT_DIR="${BUSVIDEO_BOOT_DIR:-}"
DRY="${DRY_RUN:-0}"
log() { echo "busvideo-provision: $*"; }
run() { if [[ "$DRY" == "1" ]]; then log "(dry-run) $*"; else "$@"; fi; }

if [[ -z "$BOOT_DIR" ]]; then
  for d in /boot/firmware /boot; do [[ -d "$d" ]] && { BOOT_DIR="$d"; break; }; done
fi
FILE="$BOOT_DIR/busvideo-provision.txt"
[[ -f "$CONF" ]] || { log "sem $CONF; nada a fazer"; exit 0; }

set_key() {  # set_key KEY VALUE (cria se nao existir)
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$CONF"; then sed -i -E "s|^${key}=.*|${key}=${val}|" "$CONF"; else echo "${key}=${val}" >> "$CONF"; fi
}
get_key() { sed -nE "s/^$1=(.*)$/\1/p" "$CONF" | tail -1; }
valid_id() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; }
serial_suffix() {
  local s; s="$(sed -nE 's/^Serial\s*:\s*0*([0-9a-fA-F]+)$/\1/p' /proc/cpuinfo 2>/dev/null | tail -1)"
  [[ -n "$s" ]] || s="$(cat /etc/machine-id 2>/dev/null || echo "$RANDOM$RANDOM")"
  echo "${s: -6}" | tr '[:lower:]' '[:upper:]'
}

# --- 1. Clone recem-gravado: identidade da maquina e chaves SSH proprias -------------------
if [[ -f "$MARKER" ]]; then
  log "primeiro boot de um clone: regenerando identidade da maquina"
  if [[ "$DRY" != "1" ]]; then
    ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1 || { ssh-keygen -A >/dev/null 2>&1 || true; systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true; }
    [[ -s /etc/machine-id ]] || systemd-machine-id-setup >/dev/null 2>&1 || true
    rm -rf "$BASE/state"/*.json "$BASE/logs"/* "$BASE/media/download"/* 2>/dev/null || true
  fi
  rm -f "$MARKER"
fi

# --- 2. Arquivo de provisionamento na particao de boot -----------------------------------
applied=0
if [[ -f "$FILE" ]]; then
  log "aplicando $FILE"
  DEVICE_ID=""; WIFI_SSID=""; WIFI_PSK=""; SERVER_URLS=""
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    line="${raw%$'\r'}"; line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"; key="${key//[[:space:]]/}"; val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
    val="${val#\"}"; val="${val%\"}"
    case "$key" in
      DEVICE_ID) DEVICE_ID="$val" ;;
      WIFI_SSID) WIFI_SSID="$val" ;;
      WIFI_PSK) WIFI_PSK="$val" ;;
      SERVER_URLS|SERVER_URL) SERVER_URLS="$val" ;;
      *) log "chave ignorada: $key" ;;
    esac
  done < "$FILE"
  if [[ -n "$DEVICE_ID" ]]; then
    if valid_id "$DEVICE_ID"; then
      set_key DEVICE_ID "$DEVICE_ID"; applied=1
      host="$(echo "$DEVICE_ID" | tr '[:upper:]_' '[:lower:]-')"
      run hostnamectl set-hostname "$host" 2>/dev/null || { [[ "$DRY" == "1" ]] || echo "$host" > /etc/hostname; }
      log "DEVICE_ID=$DEVICE_ID hostname=$host"
    else
      log "ERRO: DEVICE_ID invalido em $FILE: '$DEVICE_ID' (use letras, numeros, - e _; ex.: BUS-017)"
    fi
  fi
  if [[ -n "$SERVER_URLS" ]]; then set_key SERVER_URLS "$SERVER_URLS"; applied=1; log "SERVER_URLS=$SERVER_URLS"; fi
  if [[ -n "$WIFI_SSID" && -n "$WIFI_PSK" ]]; then
    run bash "$BASE/scripts/wifi-setup.sh" "$WIFI_SSID" "$WIFI_PSK" "$(get_key WIFI_IFACE || echo wlan0)" || log "AVISO: wifi-setup falhou"
    log "Wi-Fi=$WIFI_SSID"
  fi
  # Nao deixar senha de Wi-Fi na particao de boot depois de aplicada
  sed -E 's/^([[:space:]]*WIFI_PSK[[:space:]]*=).*/\1(aplicada)/' "$FILE" > "$BOOT_DIR/busvideo-provision.done" 2>/dev/null || true
  rm -f "$FILE"
fi

# --- 3. Clone sem arquivo: identidade provisoria distinta, para nao colidir na garagem ----
cur="$(get_key DEVICE_ID || true)"
if [[ -z "$cur" || "$cur" == "BUS-000" || "$cur" == "BUS-MESTRE" ]]; then
  new="NOVO-$(serial_suffix)"
  set_key DEVICE_ID "$new"; applied=1
  log "sem busvideo-provision.txt: identidade provisoria $new (coloque o arquivo na particao de boot e reinicie para nomear)"
fi

if [[ "$applied" == "1" ]]; then
  rm -f "$BASE/state"/*.json 2>/dev/null || true     # a identidade mudou: estado antigo nao vale
  run systemctl try-restart busvideo-sync.service 2>/dev/null || true
fi
exit 0
