#!/usr/bin/env bash
# Instala/atualiza o servidor da garagem (Bus Video) em /opt/busvideo-server.
# Uso: sudo ./install_server.sh [--port 443] [--operator-password SENHA] [--admin-password SENHA] [--no-ufw]
# HTTPS: gera a CA da garagem e o certificado do servidor em config/tls (ca.crt vai para cada onibus).
# Re-executar atualiza o codigo sem tocar em config/server.env nem em data/.
set -euo pipefail

PORT=443
HTTP_PORT=80
ADMIN_PASSWORD=""; OPERATOR_PASSWORD=""
USE_UFW=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="$2"; shift 2 ;;
    --operator-password) OPERATOR_PASSWORD="$2"; shift 2 ;;
    --no-ufw) USE_UFW=0; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Opcao desconhecida: $1" >&2; exit 2 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE=/opt/busvideo-server
APP="$BASE/app"; VENV="$BASE/venv"; CONF="$BASE/config/server.env"
SVC_USER=busvideo-server

info() { echo "==> $*"; }
die()  { echo "ERRO: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "execute como root: sudo $0"
[[ -z "$ADMIN_PASSWORD" || ${#ADMIN_PASSWORD} -ge 8 ]] || die "--admin-password precisa de pelo menos 8 caracteres"
[[ -z "$OPERATOR_PASSWORD" || ${#OPERATOR_PASSWORD} -ge 8 ]] || die "--operator-password precisa de pelo menos 8 caracteres"
[[ -f /etc/os-release ]] && . /etc/os-release
case "${ID:-}${ID_LIKE:-}" in *ubuntu*|*debian*) ;; *) die "sistema nao suportado (esperado Ubuntu/Debian)";; esac
[[ -f "$SRC_DIR/pyproject.toml" && -d "$SRC_DIR/busvideo_server" ]] || die "execute a partir da pasta server/ do projeto"

info "Instalando dependencias do sistema (python3, venv, ffmpeg)"
need=()
command -v python3 >/dev/null || need+=(python3)
python3 -c 'import venv' 2>/dev/null || need+=(python3-venv)
command -v ffprobe >/dev/null || need+=(ffmpeg)
command -v rsync >/dev/null || need+=(rsync)
if [[ ${#need[@]} -gt 0 ]]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq "${need[@]}"
fi

info "Criando usuario de servico $SVC_USER"
getent group "$SVC_USER" >/dev/null || groupadd --system "$SVC_USER"
getent passwd "$SVC_USER" >/dev/null || useradd --system --gid "$SVC_USER" --home-dir "$BASE" \
  --no-create-home --shell /usr/sbin/nologin "$SVC_USER"

info "Copiando codigo para $APP"
mkdir -p "$APP" "$BASE/config" "$BASE/data/videos/versions" "$BASE/data/videos/incoming" "$BASE/logs"
rsync -a --delete --exclude 'tests' --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' \
  --exclude 'data' "$SRC_DIR/" "$APP/"

info "Criando ambiente virtual e instalando pacote"
[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip >/dev/null
"$VENV/bin/pip" install --quiet --upgrade "$APP"

if [[ ! -f "$CONF" ]]; then
  info "Gerando configuracao inicial em $CONF"
  ask_pw() { # $1 = rotulo, $2 = nome da variavel
    local pw confirm
    while :; do
      read -r -s -p "$1: " pw; echo
      read -r -s -p "Confirme a senha: " confirm; echo
      [[ ${#pw} -ge 8 && "$pw" == "$confirm" ]] && break
      echo "Senhas diferentes ou com menos de 8 caracteres; tente novamente."
    done
    printf -v "$2" '%s' "$pw"
  }
  [[ -n "$OPERATOR_PASSWORD" ]] || ask_pw "Senha do OPERADOR (usuario 'operador', uso diario do painel)" OPERATOR_PASSWORD
  [[ -n "$ADMIN_PASSWORD" ]] || ask_pw "Senha do ADMINISTRADOR (usuario 'admin', suporte; redefine a senha do operador)" ADMIN_PASSWORD
  {
    echo "# Gerado por install_server.sh em $(date '+%Y-%m-%d %H:%M:%S')"
    "$VENV/bin/python" -m busvideo_server.tools gen-env "$OPERATOR_PASSWORD" "$ADMIN_PASSWORD"
    # Remaining keys with defaults, skipping the ones gen-env already produced.
    grep -E '^(#|[A-Z_]+=)' "$SRC_DIR/server.env.example" \
      | grep -vE '^(OPERATOR_USER|OPERATOR_PASSWORD_HASH|ADMIN_USER|ADMIN_PASSWORD_HASH|SECRET_KEY|DEVICE_TOKEN)=' \
      | sed -E "s/^BUSVIDEO_PORT=.*/BUSVIDEO_PORT=$PORT/; s#^BUSVIDEO_TLS_CERT=.*#BUSVIDEO_TLS_CERT=$BASE/config/tls/server.crt#; s#^BUSVIDEO_TLS_KEY=.*#BUSVIDEO_TLS_KEY=$BASE/config/tls/server.key#; s/^BUSVIDEO_HTTP_REDIRECT_PORT=.*/BUSVIDEO_HTTP_REDIRECT_PORT=$HTTP_PORT/"
  } > "$CONF"
else
  info "Mantendo configuracao existente em $CONF"
  [[ -n "$ADMIN_PASSWORD$OPERATOR_PASSWORD" ]] && echo "AVISO: senhas ignoradas (config ja existe; troque pelo painel ou com: $VENV/bin/python -m busvideo_server.tools set-password operador|admin)"
  if ! grep -q '^BUSVIDEO_TLS_CERT=' "$CONF"; then
    info "Migrando configuracao existente para HTTPS na porta $PORT"
    sed -i -E "s/^BUSVIDEO_PORT=.*/BUSVIDEO_PORT=$PORT/" "$CONF"
    printf '\nBUSVIDEO_TLS_CERT=%s\nBUSVIDEO_TLS_KEY=%s\nBUSVIDEO_HTTP_REDIRECT_PORT=%s\n' "$BASE/config/tls/server.crt" "$BASE/config/tls/server.key" "$HTTP_PORT" >> "$CONF"
  fi
  grep -q '^BUSVIDEO_PORT=' "$CONF" && PORT="$(sed -nE 's/^BUSVIDEO_PORT=(.*)$/\1/p' "$CONF" | tail -1)"
fi
info "Gerando/renovando os certificados HTTPS em $BASE/config/tls (a CA e mantida entre execucoes)"
"$VENV/bin/python" -m busvideo_server.tools gen-cert --out "$BASE/config/tls" --dns "$(hostname)" $(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9.]+$' | sed 's/^/--ip /' | tr '\n' ' ')
chmod 700 "$BASE/config/tls"; chmod 600 "$BASE"/config/tls/*.key; chmod 644 "$BASE"/config/tls/*.crt
install -m 644 "$BASE/config/tls/ca.crt" "$BASE/ca.crt"
# Pasta "pendrive": tudo que o primeiro Raspberry precisa (assistente, programa, certificado, dados da garagem)
CLIENT_SRC="$(cd "$SRC_DIR/.." && pwd)/client"
if [[ -f "$CLIENT_SRC/install_client.sh" ]]; then
  PEN="$BASE/pendrive"; rm -rf "$PEN/client"; mkdir -p "$PEN"
  cp -r "$CLIENT_SRC" "$PEN/client"; find "$PEN/client" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  cp "$CLIENT_SRC/instalar-onibus.sh" "$PEN/"; cp "$BASE/config/tls/ca.crt" "$PEN/ca.crt"
  IP_NOW="$(hostname -I 2>/dev/null | awk '{print $1}')"
  printf '# Dados da garagem lidos pelo assistente instalar-onibus.sh\nSERVER_URL=https://%s\nDEVICE_TOKEN=%s\nWIFI_SSID=\nWIFI_PSK=\n' "${IP_NOW:-IP_DO_SERVIDOR}" "$(sed -nE 's/^DEVICE_TOKEN=(.*)$/\1/p' "$CONF" | tail -1)" > "$PEN/garagem.txt"
  chmod -R a+rX "$PEN"; chmod 600 "$PEN/garagem.txt"
  printf '#!/usr/bin/env bash\n# Frota pela rede: descobrir | instalar | verificar (ver: %s/venv/bin/python -m busvideo_server.fleet --help)\nexec "%s/venv/bin/python" -m busvideo_server.fleet "$@"\n' "$BASE" "$BASE" > "$BASE/frota.sh"; chmod 755 "$BASE/frota.sh"
  [[ -f "$BASE/frota.csv" ]] || printf '# Um onibus por linha: NUMERO,ENDERECO (IP ou nome na rede)\n# BUS-001,192.168.100.51\n' > "$BASE/frota.csv"
fi
chmod 600 "$CONF"
chown -R "$SVC_USER:$SVC_USER" "$BASE/config" "$BASE/data" "$BASE/logs"
chown -R root:root "$APP" "$VENV"

info "Instalando servico systemd busvideo-server"
install -m 644 "$SRC_DIR/systemd/busvideo-server.service" /etc/systemd/system/busvideo-server.service
systemctl daemon-reload
systemctl enable --now busvideo-server.service >/dev/null
systemctl restart busvideo-server.service

if [[ $USE_UFW -eq 1 ]] && command -v ufw >/dev/null; then
  info "Liberando portas $PORT/tcp (HTTPS) e $HTTP_PORT/tcp (redirecionamento) no ufw"
  ufw allow "$PORT/tcp" >/dev/null || true
  ufw allow "$HTTP_PORT/tcp" >/dev/null || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
TOKEN="$(sed -nE 's/^DEVICE_TOKEN=(.*)$/\1/p' "$CONF" | tail -1)"
ADMIN="$(sed -nE 's/^ADMIN_USER=(.*)$/\1/p' "$CONF" | tail -1)"
OPER="$(sed -nE 's/^OPERATOR_USER=(.*)$/\1/p' "$CONF" | tail -1)"
sleep 2
STATUS="$(systemctl is-active busvideo-server.service || true)"
cat <<SUMMARY

============================================================
 Servidor Bus Video instalado  (status: $STATUS)
------------------------------------------------------------
 Interface do operador : https://${IP:-IP_DO_SERVIDOR}/   (porta $PORT)
 Pendrive              : copie $BASE/pendrive para um pendrive e leve ao primeiro Raspberry (assistente instalar-onibus.sh)
 Pela rede             : $BASE/frota.sh descobrir|instalar|verificar  (onibus que ja tem Raspberry na rede)
 Certificado da CA     : $BASE/ca.crt   (instale nos PCs/celulares dos operadores)
                         tambem em http://${IP:-IP_DO_SERVIDOR}/ca.crt
 Usuario operador      : ${OPER:-operador}   (uso diario)
 Usuario administrador : ${ADMIN:-admin}   (suporte; redefine a senha do operador no painel, botao Senha)
 Esqueceu a do admin?  : sudo BUSVIDEO_SERVER_ENV=$CONF $VENV/bin/python -m busvideo_server.tools set-password admin
 Configuracao          : $CONF
 Dados / videos        : $BASE/data
 Logs                  : journalctl -u busvideo-server -f   |   $BASE/logs/server.log

 DEVICE_TOKEN (copie para o install_client.sh de CADA onibus):
   $TOKEN
============================================================
SUMMARY
