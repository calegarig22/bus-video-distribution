#!/usr/bin/env bash
# Instala/atualiza o terminal embarcado Bus Video (player + sync) em /opt/busvideo-player.
# Uso: sudo ./install_client.sh --device-id BUS-001 --server-url https://192.168.100.10 --token TOKEN --ca-cert ca.crt \
#        [--wifi-ssid SSID --wifi-psk PSK] [--player mpv|fake] [--video /caminho/inicial.mp4] \
#        [--offline-debs DIR] [--skip-apt] [--allow-insecure-http] [--no-firewall]
# Re-executar atualiza o codigo; client.env existente so recebe as chaves passadas na linha de comando.
set -euo pipefail

DEVICE_ID=""; SERVER_URL=""; TOKEN=""; WIFI_SSID=""; WIFI_PSK=""; WIFI_IFACE="wlan0"
PLAYER=""; VIDEO=""; OFFLINE_DEBS=""; SKIP_APT=0; CA_CERT=""; ALLOW_INSECURE_HTTP=0; NO_FIREWALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --device-id) DEVICE_ID="$2"; shift 2 ;;
    --server-url) SERVER_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --ca-cert) CA_CERT="$2"; shift 2 ;;
    --allow-insecure-http) ALLOW_INSECURE_HTTP=1; shift ;;
    --no-firewall) NO_FIREWALL=1; shift ;;
    --wifi-ssid) WIFI_SSID="$2"; shift 2 ;;
    --wifi-psk) WIFI_PSK="$2"; shift 2 ;;
    --wifi-iface) WIFI_IFACE="$2"; shift 2 ;;
    --player) PLAYER="$2"; shift 2 ;;
    --video) VIDEO="$2"; shift 2 ;;
    --offline-debs) OFFLINE_DEBS="$2"; shift 2 ;;
    --skip-apt) SKIP_APT=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Opcao desconhecida: $1" >&2; exit 2 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE=/opt/busvideo-player
APP="$BASE/app"; CONF="$BASE/config/client.env"
SVC_USER=busvideo

info() { echo "==> $*"; }
die()  { echo "ERRO: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "execute como root: sudo $0"
[[ -d "$SRC_DIR/busvideo_client" && -d "$SRC_DIR/systemd" ]] || die "execute a partir da pasta client/ do projeto"
if [[ ! -f "$CONF" ]]; then
  [[ -n "$DEVICE_ID" && -n "$SERVER_URL" && -n "$TOKEN" ]] || \
    die "primeira instalacao exige --device-id, --server-url e --token"
fi
[[ -z "$PLAYER" || "$PLAYER" =~ ^(mpv|fake|mpv-desktop)$ ]] || die "--player deve ser mpv ou fake"
[[ -z "$VIDEO" || -f "$VIDEO" ]] || die "video inicial nao encontrado: $VIDEO"
[[ -z "$CA_CERT" || -f "$CA_CERT" ]] || die "certificado da CA nao encontrado: $CA_CERT"
if [[ "$SERVER_URL" == https://* && -z "$CA_CERT" && ! -f "$BASE/config/ca.crt" ]]; then
  die "servidor HTTPS exige --ca-cert ca.crt (copie de /opt/busvideo-server/ca.crt ou http://IP/ca.crt no servidor)"
fi
if [[ "$SERVER_URL" == http://* && $ALLOW_INSECURE_HTTP -eq 0 ]]; then
  die "servidor http:// nao e aceito num onibus (o token seria entregue a qualquer rede que imite a garagem). Use https:// com --ca-cert, ou --allow-insecure-http SOMENTE em bancada"
fi
[[ -z "$WIFI_SSID" || -n "$WIFI_PSK" ]] || die "--wifi-ssid exige --wifi-psk"

# --- packages -----------------------------------------------------------
if [[ -n "$OFFLINE_DEBS" ]]; then
  info "Instalando pacotes offline de $OFFLINE_DEBS"
  [[ -d "$OFFLINE_DEBS" ]] || die "pasta nao encontrada: $OFFLINE_DEBS"
  dpkg -i "$OFFLINE_DEBS"/*.deb || apt-get install -f -y || true
elif [[ $SKIP_APT -eq 0 ]]; then
  need=()
  command -v python3 >/dev/null || need+=(python3)
  command -v mpv >/dev/null || need+=(mpv)
  command -v ffprobe >/dev/null || need+=(ffmpeg)
  command -v rsync >/dev/null || need+=(rsync)
  if [[ ${#need[@]} -gt 0 ]]; then
    info "Instalando pacotes: ${need[*]}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq "${need[@]}"
  else
    info "Pacotes ja instalados (python3, mpv, ffmpeg)"
  fi
else
  info "--skip-apt: pulando instalacao de pacotes"
fi
command -v python3 >/dev/null || die "python3 nao encontrado"
[[ "${PLAYER:-mpv}" == "fake" ]] || command -v mpv >/dev/null || echo "AVISO: mpv nao encontrado; o player nao vai iniciar"

# --- user / groups -------------------------------------------------------
info "Criando usuario de servico $SVC_USER"
getent group "$SVC_USER" >/dev/null || groupadd --system "$SVC_USER"
getent passwd "$SVC_USER" >/dev/null || useradd --system --gid "$SVC_USER" --home-dir "$BASE" \
  --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
for g in video render input audio; do
  getent group "$g" >/dev/null || groupadd --system "$g"
  usermod -a -G "$g" "$SVC_USER"
done

# --- code / dirs ---------------------------------------------------------
info "Copiando codigo para $APP"
mkdir -p "$APP" "$BASE/config" "$BASE/media/versions" "$BASE/media/download" "$BASE/state" "$BASE/logs"
if command -v rsync >/dev/null; then
  rsync -a --delete --exclude 'tests' --exclude '__pycache__' --exclude '*.pyc' "$SRC_DIR/busvideo_client/" "$APP/busvideo_client/"
else
  rm -rf "$APP/busvideo_client"; cp -r "$SRC_DIR/busvideo_client" "$APP/busvideo_client"
  find "$APP" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
fi
mkdir -p "$BASE/scripts"; cp "$SRC_DIR"/scripts/*.sh "$BASE/scripts/"; chmod 755 "$BASE"/scripts/*.sh
chown -R root:root "$APP" "$BASE/scripts"

# --- config ----------------------------------------------------------------
set_key() {  # set_key KEY VALUE  (append if missing)
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$CONF"; then
    sed -i -E "s|^${key}=.*|${key}=${val}|" "$CONF"
  else
    echo "${key}=${val}" >> "$CONF"
  fi
}
if [[ ! -f "$CONF" ]]; then
  info "Criando $CONF"
  cp "$SRC_DIR/config/client.env.example" "$CONF"
else
  info "Atualizando chaves informadas em $CONF (demais mantidas)"
fi
[[ -n "$DEVICE_ID" ]]  && set_key DEVICE_ID "$DEVICE_ID"
[[ -n "$SERVER_URL" ]] && set_key SERVER_URLS "${SERVER_URL%/}"
if [[ -n "$CA_CERT" ]]; then
  install -m 644 -o root -g "$SVC_USER" "$CA_CERT" "$BASE/config/ca.crt"
  set_key CA_CERT "$BASE/config/ca.crt"
fi
[[ $ALLOW_INSECURE_HTTP -eq 1 ]] && set_key ALLOW_INSECURE_HTTP true
[[ -n "$TOKEN" ]]      && set_key DEVICE_TOKEN "$TOKEN"
[[ -n "$PLAYER" ]]     && set_key PLAYER "$PLAYER"
[[ -n "$WIFI_SSID" ]]  && set_key WIFI_SSID "$WIFI_SSID" && set_key WIFI_PSK "$WIFI_PSK" && set_key WIFI_IFACE "$WIFI_IFACE"
chown root:"$SVC_USER" "$CONF"; chmod 640 "$CONF"
chown -R "$SVC_USER:$SVC_USER" "$BASE/media" "$BASE/state" "$BASE/logs" "$BASE/config"

# --- initial video -----------------------------------------------------------
if [[ -n "$VIDEO" ]]; then
  info "Instalando video inicial como video_v0.mp4"
  install -m 644 -o "$SVC_USER" -g "$SVC_USER" "$VIDEO" "$BASE/media/versions/video_v0.mp4"
  ln -sfn versions/video_v0.mp4 "$BASE/media/current.mp4"
  chown -h "$SVC_USER:$SVC_USER" "$BASE/media/current.mp4"
elif [[ ! -e "$BASE/media/current.mp4" ]]; then
  echo "AVISO: nenhum video inicial (--video); o player aguarda o primeiro download da garagem."
fi

# --- firewall e SSH: o onibus nunca aceita conexao de fora ---------------------
# O terminal so faz conexoes de saida (para a garagem). Nenhuma porta aberta para quem estiver na mesma
# rede (passageiros, outros aparelhos). SSH fica permitido com limite de tentativas, so para manutencao.
if [[ $NO_FIREWALL -eq 0 ]]; then
  if ! command -v ufw >/dev/null && [[ $SKIP_APT -eq 0 ]]; then
    export DEBIAN_FRONTEND=noninteractive; apt-get install -y -qq ufw >/dev/null 2>&1 || true
  fi
  if command -v ufw >/dev/null; then
    info "Firewall: bloqueando toda conexao de entrada (exceto SSH com limite de tentativas)"
    ufw --force reset >/dev/null 2>&1 || true
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw limit 22/tcp >/dev/null
    ufw --force enable >/dev/null
  else
    echo "AVISO: ufw indisponivel; instale-o ou configure o firewall manualmente (deny incoming)."
  fi
fi
if [[ -f /etc/ssh/sshd_config ]]; then
  # Senha por SSH so enquanto nao houver chave instalada para o administrador; com chave, desliga senha.
  if ls /home/*/.ssh/authorized_keys /root/.ssh/authorized_keys >/dev/null 2>&1; then
    install -d /etc/ssh/sshd_config.d
    printf 'PasswordAuthentication no\nPermitRootLogin no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/90-busvideo-hardening.conf
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    info "SSH: login por senha desligado (ha chave autorizada)"
  else
    echo "AVISO: SSH ainda aceita senha. Instale sua chave (ssh-copy-id) e rode o instalador de novo para desligar a senha."
  fi
fi

# --- systemd -------------------------------------------------------------------
info "Instalando servicos systemd busvideo-player e busvideo-sync"
install -m 644 "$SRC_DIR/systemd/busvideo-player.conf" /etc/tmpfiles.d/busvideo-player.conf
install -m 644 "$SRC_DIR/systemd/busvideo-player.service" /etc/systemd/system/busvideo-player.service
install -m 644 "$SRC_DIR/systemd/busvideo-sync.service" /etc/systemd/system/busvideo-sync.service
install -m 644 "$SRC_DIR/systemd/busvideo-provision.service" /etc/systemd/system/busvideo-provision.service
systemd-tmpfiles --create /etc/tmpfiles.d/busvideo-player.conf
systemctl daemon-reload
systemctl enable busvideo-player.service busvideo-sync.service busvideo-provision.service >/dev/null
systemctl restart busvideo-player.service busvideo-sync.service

# --- wi-fi -------------------------------------------------------------------------
if [[ -n "$WIFI_SSID" ]]; then
  info "Configurando Wi-Fi da garagem ($WIFI_SSID)"
  bash "$SRC_DIR/scripts/wifi-setup.sh" "$WIFI_SSID" "$WIFI_PSK" "$WIFI_IFACE" || echo "AVISO: wifi-setup falhou; configure manualmente"
fi
info "Desativando economia de energia do Wi-Fi"
if command -v nmcli >/dev/null && [[ -d /etc/NetworkManager ]]; then
  mkdir -p /etc/NetworkManager/conf.d
  printf '[connection]\nwifi.powersave = 2\n' > /etc/NetworkManager/conf.d/wifi-powersave-off.conf
  systemctl reload NetworkManager 2>/dev/null || true
else
  cat > /etc/systemd/system/busvideo-wifi-powersave-off.service <<UNIT
[Unit]
Description=Disable Wi-Fi power save (BusVideo)
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'command -v iw >/dev/null && iw dev $WIFI_IFACE set power_save off || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload; systemctl enable --now busvideo-wifi-powersave-off.service >/dev/null 2>&1 || true
fi

sleep 2
DID="$(sed -nE 's/^DEVICE_ID=(.*)$/\1/p' "$CONF" | tail -1)"
SRV="$(sed -nE 's/^SERVER_URLS=(.*)$/\1/p' "$CONF" | tail -1)"
cat <<SUMMARY

============================================================
 Terminal Bus Video instalado
------------------------------------------------------------
 Dispositivo   : $DID
 Servidor(es)  : $SRV
 busvideo-player    : $(systemctl is-active busvideo-player.service || true)
 busvideo-sync      : $(systemctl is-active busvideo-sync.service || true)
 Configuracao  : $CONF
 Midia         : $BASE/media   (current.mp4 -> versions/video_vN.mp4)
 Logs          : journalctl -u busvideo-sync -f   |   journalctl -u busvideo-player -f
                 $BASE/logs/sync.log  $BASE/logs/player.log
 Diagnostico   : $BASE/scripts/diagnose.sh
------------------------------------------------------------
 RECOMENDACAO (nao aplicada automaticamente): em /boot/firmware/config.txt
 use hdmi_force_hotplug=1 e modo HDMI fixo (hdmi_group/hdmi_mode) quando
 houver splitter/distribuidor HDMI, para evitar tela preta no boot.
============================================================
SUMMARY
