#!/usr/bin/env bash
# Assistente de instalacao do primeiro onibus (Raspberry Pi com Ubuntu), em portugues, com perguntas.
#
# Roda a partir do pendrive preparado pelo instalador do servidor (pasta "pendrive" em C:\BusVideo ou
# /opt/busvideo-server). O pendrive traz: este assistente, a pasta client, o certificado ca.crt e o garagem.txt
# (endereco do servidor e token). Assim, no Raspberry so se responde: numero do onibus e senha do Wi-Fi.
#
#   sudo mount /dev/sda1 /mnt
#   sudo bash /mnt/instalar-onibus.sh
#
# Teste fora do Pi: DRY_RUN=1 bash instalar-onibus.sh (so mostra o que faria)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY="${DRY_RUN:-0}"
say() { echo; echo "==> $*"; }
run() { if [[ "$DRY" == "1" ]]; then echo "(simulacao) $*"; else "$@"; fi; }
ask() { local prompt="$1" default="${2:-}" reply; if [[ -n "$default" ]]; then read -r -p "$prompt [$default]: " reply; echo "${reply:-$default}"; else read -r -p "$prompt: " reply; echo "$reply"; fi; }

echo "=================================================================="
echo "  Bus Video - assistente do primeiro onibus"
echo "=================================================================="
if [[ "$DRY" != "1" && $EUID -ne 0 ]]; then echo "Rode com sudo: sudo bash $0"; exit 1; fi

# --- 1. O que veio no pendrive --------------------------------------------------
[[ -d "$HERE/client" ]] || { echo "ERRO: pasta 'client' nao encontrada ao lado deste assistente ($HERE). Copie a pasta 'pendrive' inteira."; exit 1; }
CA="$HERE/ca.crt"; INFO="$HERE/garagem.txt"
[[ -f "$CA" ]] || { echo "ERRO: ca.crt nao encontrado em $HERE (o certificado da garagem)."; exit 1; }
SERVER_URL=""; TOKEN=""; WIFI_SSID=""; WIFI_PSK=""
if [[ -f "$INFO" ]]; then
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    line="${raw%$'\r'}"; [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    k="${line%%=*}"; v="${line#*=}"; k="${k//[[:space:]]/}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
    case "$k" in SERVER_URL|SERVER_URLS) SERVER_URL="$v";; DEVICE_TOKEN) TOKEN="$v";; WIFI_SSID) WIFI_SSID="$v";; WIFI_PSK) WIFI_PSK="$v";; esac
  done < "$INFO"
  say "Dados da garagem lidos de garagem.txt"
else
  say "garagem.txt nao encontrado; vou perguntar o endereco e o token"
fi

# --- 2. Perguntas ----------------------------------------------------------------
echo
DEVICE_ID="$(ask "Numero deste onibus (letras, numeros e traco; ex.: BUS-001)" "BUS-001")"
while ! [[ "$DEVICE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; do echo "  Use so letras, numeros, - e _ (ex.: BUS-001)"; DEVICE_ID="$(ask "Numero deste onibus")"; done
[[ -n "$SERVER_URL" ]] || SERVER_URL="$(ask "Endereco do servidor da garagem (ex.: https://192.168.100.10)")"
[[ "$SERVER_URL" == https://* ]] || { echo "ERRO: o endereco precisa comecar com https:// (ex.: https://192.168.100.10)"; exit 1; }
[[ -n "$TOKEN" ]] || TOKEN="$(ask "DEVICE_TOKEN (impresso pelo instalador do servidor)")"
[[ -n "$WIFI_SSID" ]] || WIFI_SSID="$(ask "Nome do Wi-Fi da garagem" "GARAGEM_EXEMPLO")"
if [[ -z "$WIFI_PSK" ]]; then read -r -s -p "Senha do Wi-Fi $WIFI_SSID (nao aparece ao digitar): " WIFI_PSK; echo; fi
VIDEO=""
for cand in "$HERE"/video-inicial.mp4 "$HERE"/*.mp4; do [[ -f "$cand" ]] && { VIDEO="$cand"; break; }; done
BENCH="$(ask "Fazer o teste de reproducao Full HD antes de instalar? (s/n, leva 3 minutos)" "s")"

echo
echo "------------------------------------------------------------------"
echo "  Onibus      : $DEVICE_ID"
echo "  Servidor    : $SERVER_URL"
echo "  Wi-Fi       : $WIFI_SSID"
echo "  Certificado : $CA"
echo "  Video inicial: ${VIDEO:-nenhum (o onibus busca o primeiro video na garagem)}"
echo "------------------------------------------------------------------"
OK="$(ask "Confirmar e instalar? (s/n)" "s")"; [[ "$OK" =~ ^[sSyY] ]] || { echo "Cancelado."; exit 0; }

# --- 3. Copia para o cartao e ajuste do HDMI ------------------------------------
say "Copiando o programa para o cartao do Raspberry"
DEST="/root/busvideo-client"
run rm -rf "$DEST"; run cp -r "$HERE/client" "$DEST"
CFG=/boot/firmware/config.txt; [[ -f "$CFG" ]] || CFG=/boot/config.txt
if [[ "$DRY" != "1" && -f "$CFG" ]]; then
  grep -q '^hdmi_force_hotplug=1' "$CFG" || echo 'hdmi_force_hotplug=1' >> "$CFG"
  grep -q '^gpu_mem=' "$CFG" || echo 'gpu_mem=128' >> "$CFG"
  say "Saida HDMI ajustada em $CFG (telas ligadas depois do Raspberry nao ficam pretas)"
else
  echo "(simulacao) ajustar $CFG: hdmi_force_hotplug=1, gpu_mem=128"
fi

# --- 4. Teste de reproducao (opcional, so no primeiro) ---------------------------
if [[ "$BENCH" =~ ^[sSyY] ]]; then
  say "Teste de reproducao: gerando um video Full HD de 60 s e tocando por 2 minutos. Olhe o monitor."
  if [[ "$DRY" == "1" ]]; then echo "(simulacao) make-test-video.sh + benchmark-player.sh"; else
    bash "$DEST/scripts/make-test-video.sh" /tmp/teste.mp4 60 1920x1080 || echo "AVISO: nao gerou o video de teste (ffmpeg ausente?); o instalador instala o ffmpeg e o teste pode ser repetido depois."
    [[ -f /tmp/teste.mp4 ]] && { bash "$DEST/scripts/benchmark-player.sh" /tmp/teste.mp4 120 || echo "AVISO: benchmark nao concluiu; veja a mensagem acima."; }
    [[ -z "$VIDEO" && -f /tmp/teste.mp4 ]] && VIDEO=/tmp/teste.mp4
  fi
fi

# --- 5. Instalacao propriamente dita ----------------------------------------------
say "Instalando o programa de bordo (precisa de internet nesta etapa, salvo se o pendrive tiver a pasta debs)"
args=(--device-id "$DEVICE_ID" --server-url "$SERVER_URL" --token "$TOKEN" --ca-cert "$CA" --wifi-ssid "$WIFI_SSID" --wifi-psk "$WIFI_PSK")
[[ -n "$VIDEO" ]] && args+=(--video "$VIDEO")
if [[ -d "$HERE/debs" ]] && ls "$HERE"/debs/*.deb >/dev/null 2>&1; then say "Pasta debs encontrada no pendrive: instalando os pacotes sem internet"; args+=(--offline-debs "$HERE/debs"); fi
if [[ "$DRY" == "1" ]]; then echo "(simulacao) bash $DEST/install_client.sh ${args[*]//$WIFI_PSK/******}"; else
  ( cd "$DEST" && bash ./install_client.sh "${args[@]}" )
fi

echo
echo "=================================================================="
echo "  PRONTO. Este Raspberry e o onibus $DEVICE_ID."
echo "  Proximo passo: desligue (sudo poweroff), retire o pendrive e ligue de novo."
echo "  O video deve aparecer em ate 30 s. Na garagem, ele aparece no painel."
echo "  Para virar a imagem-mestre dos outros onibus: sudo /opt/busvideo-player/scripts/prepare-master.sh"
echo "=================================================================="
