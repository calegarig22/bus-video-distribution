#!/usr/bin/env bash
# Gera vídeos de demonstração em demo/videos/ (usa o ffmpeg do ambiente de desenvolvimento).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/demo/videos"
SECONDS_V="${1:-20}"

if command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG="$(command -v ffmpeg)"
elif [ -x "$PY" ]; then
  FFMPEG="$("$PY" -c 'import static_ffmpeg, shutil; static_ffmpeg.add_paths(); print(shutil.which("ffmpeg"))')"
else
  echo "ffmpeg não encontrado. Instale o ffmpeg ou crie o ambiente de desenvolvimento (.venv)." >&2
  exit 1
fi
mkdir -p "$OUT"

gen() { # nome, filtro lavfi, fps, tamanho, extra-args...
  local name="$1" src="$2" fps="$3" size="$4"; shift 4
  local file="$OUT/$name"
  if [ -f "$file" ]; then echo "já existe: $file"; return; fi
  echo "gerando $file ..."
  "$FFMPEG" -y -v error -f lavfi -i "$src=size=$size:rate=$fps" -t "$SECONDS_V" \
    -c:v libx264 -pix_fmt yuv420p -preset veryfast -profile:v high -level 4.0 -b:v 4M -maxrate 6M -bufsize 8M \
    -g "$fps" -movflags +faststart "$@" "$file"
}

gen campanha_v1.mp4 testsrc2 30 1920x1080
gen campanha_v2.mp4 testsrc  30 1920x1080
gen campanha_v3_720p.mp4 smptehdbars 30 1280x720
# Propositalmente incompatível: 60 fps (o servidor deve rejeitar)
gen incompativel_60fps.mp4 testsrc2 60 1280x720

echo
ls -lh "$OUT"
echo
echo "Pronto. Use estes arquivos na interface web (demo/run_demo.sh)."
