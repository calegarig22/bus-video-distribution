#!/usr/bin/env bash
# Demonstração local: servidor da garagem + ônibus simulados (player fake) no mesmo computador.
#
#   ./demo/run_demo.sh            # sobe tudo; Ctrl+C encerra
#   ./demo/run_demo.sh --reset    # apaga os dados da demo antes de subir
#
# Interface: https://localhost:8443  (usuários: operador ou admin  senha: demo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
DEMO="$ROOT/demo"
DATA="$DEMO/data"
PORT="${BUSVIDEO_DEMO_PORT:-8443}"          # HTTPS (443 exigiria sudo no notebook)
HTTP_PORT="${BUSVIDEO_DEMO_HTTP_PORT:-8081}" # só redireciona e entrega /ca.crt
TLS="$DATA/server/tls"
ADMIN_PASSWORD="demo"

if [ ! -x "$PY" ]; then
  echo "Ambiente não encontrado. Crie com:" >&2
  echo "  uv venv --python 3.12 .venv && uv pip install -p .venv/bin/python -e 'server[dev]' -e 'client[dev]'" >&2
  exit 1
fi
if [ "${1:-}" = "--reset" ]; then rm -rf "$DATA"; fi
mkdir -p "$DATA"

# ffprobe/ffmpeg do pacote static-ffmpeg (ambiente de desenvolvimento sem Homebrew)
FFBIN="$("$PY" -c 'import static_ffmpeg, shutil, os; static_ffmpeg.add_paths(); print(os.path.dirname(shutil.which("ffprobe")))' 2>/dev/null || true)"
[ -n "$FFBIN" ] && export PATH="$FFBIN:$PATH"

# --- servidor -----------------------------------------------------------------
SERVER_ENV="$DATA/server.env"
if [ -f "$SERVER_ENV" ] && ! grep -q '^OPERATOR_PASSWORD_HASH=' "$SERVER_ENV"; then
  # demo criada antes da conta "operador": semeia a mesma senha da demo
  printf 'OPERATOR_USER=operador\nOPERATOR_PASSWORD_HASH=%s\n' "$("$PY" -m busvideo_server.tools hash-password "$ADMIN_PASSWORD")" >> "$SERVER_ENV"
fi
if [ ! -f "$SERVER_ENV" ]; then
  "$PY" -m busvideo_server.tools gen-env "$ADMIN_PASSWORD" "$ADMIN_PASSWORD" > "$SERVER_ENV"
  cat >> "$SERVER_ENV" <<EOT
BUSVIDEO_HOST=0.0.0.0
BUSVIDEO_PORT=$PORT
BUSVIDEO_TLS_CERT=$TLS/server.crt
BUSVIDEO_TLS_KEY=$TLS/server.key
BUSVIDEO_HTTP_REDIRECT_PORT=$HTTP_PORT
BUSVIDEO_DATA_DIR=$DATA/server
BUSVIDEO_LOG_DIR=$DATA/server/logs
PRODUCT_NAME=Bus Video (demo)
COMPANY_NAME=Empresa Exemplo
OFFLINE_AFTER_S=120
MEDIA_MAX_SIZE_MB=2048
EOT
fi
if ! grep -q '^BUSVIDEO_TLS_CERT=' "$SERVER_ENV"; then   # demo antiga (HTTP 8080): migra para HTTPS
  sed -i '' -e "s/^BUSVIDEO_PORT=.*/BUSVIDEO_PORT=$PORT/" "$SERVER_ENV" 2>/dev/null || sed -i -e "s/^BUSVIDEO_PORT=.*/BUSVIDEO_PORT=$PORT/" "$SERVER_ENV"
  printf 'BUSVIDEO_TLS_CERT=%s\nBUSVIDEO_TLS_KEY=%s\nBUSVIDEO_HTTP_REDIRECT_PORT=%s\n' "$TLS/server.crt" "$TLS/server.key" "$HTTP_PORT" >> "$SERVER_ENV"
fi
# CA da garagem + certificado do servidor (a CA é mantida entre execuções, como na instalação real)
"$PY" -m busvideo_server.tools gen-cert --out "$TLS" --dns localhost --dns "$(hostname)" $(ipconfig getifaddr en0 2>/dev/null | sed 's/^/--ip /') >/dev/null
cp "$TLS/ca.crt" "$DATA/ca.crt"
TOKEN="$(grep '^DEVICE_TOKEN=' "$SERVER_ENV" | cut -d= -f2-)"

pids=()
cleanup() { echo; echo "Encerrando demo..."; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "==> Servidor da garagem em https://localhost:$PORT  (operador ou admin / $ADMIN_PASSWORD)"
BUSVIDEO_SERVER_ENV="$SERVER_ENV" "$PY" -m busvideo_server.main > "$DATA/server.out" 2>&1 &
pids+=($!)
for _ in $(seq 1 50); do
  curl -fs --cacert "$TLS/ca.crt" "https://localhost:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fs --cacert "$TLS/ca.crt" "https://localhost:$PORT/api/health" >/dev/null || { echo "servidor não subiu; veja $DATA/server.out" >&2; exit 1; }

# --- ônibus simulados --------------------------------------------------------------
start_bus() { # id, modo (loop|once)
  local id="$1" mode="$2" base="$DATA/$1"
  mkdir -p "$base"
  cat > "$base/client.env" <<EOT
DEVICE_ID=$id
SERVER_URLS=https://localhost:$PORT
CA_CERT=$TLS/ca.crt
DEVICE_TOKEN=$TOKEN
BASE_DIR=$base
SYNC_INTERVAL=10
PLAYER=fake
SWITCH_MODE=immediate
VALIDATE_FORMAT=auto
DISK_MARGIN_MB=100
LOG_LEVEL=INFO
EOT
  export BUSVIDEO_IPC_SOCKET="$base/mpv.sock"
  if [ "$mode" = "loop" ]; then
    echo "==> Ônibus $id: player + sincronização a cada 10 s (logs em $base/logs/)"
    "$PY" -m busvideo_client.supervisor --config "$base/client.env" 2>&1 | sed -u "s/^/[$id player] /" &
    pids+=($!)
    "$PY" -m busvideo_client.sync --config "$base/client.env" 2>&1 | sed -u "s/^/[$id sync]   /" &
    pids+=($!)
  else
    echo "==> Ônibus $id: sincroniza uma vez e 'sai da garagem' (ficará Offline após 2 min)"
    "$PY" -m busvideo_client.sync --config "$base/client.env" --once 2>&1 | sed -u "s/^/[$id sync]   /" || true
  fi
}

start_bus BUS-001 loop
start_bus BUS-002 once

echo
echo "------------------------------------------------------------------"
echo " Abra https://localhost:$PORT  |  usuário: operador (dia a dia) ou admin (suporte)  |  senha: $ADMIN_PASSWORD"
echo " O navegador avisa sobre o certificado até instalar $DATA/ca.crt (Avançado > Continuar funciona)."
echo " Certificado da garagem: $DATA/ca.crt  (também em http://localhost:$HTTP_PORT/ca.crt)"
echo " Vídeos de teste: ./demo/make_videos.sh  ->  demo/videos/"
echo " Publique um vídeo e acompanhe o BUS-001 baixar e trocar (logs abaixo)."
echo " Ctrl+C encerra a demo."
echo "------------------------------------------------------------------"
wait