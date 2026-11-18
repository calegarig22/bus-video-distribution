#!/usr/bin/env bash
# Gera um video de teste H.264 (padrao 1080p30, MP4 faststart) com ffmpeg.
# Uso: make-test-video.sh OUT.mp4 [SECONDS=60] [WIDTHxHEIGHT=1920x1080]
set -euo pipefail
OUT="${1:-}"; SECS="${2:-60}"; SIZE="${3:-1920x1080}"
[[ -n "$OUT" ]] || { echo "Uso: $0 OUT.mp4 [SECONDS] [WIDTHxHEIGHT]" >&2; exit 2; }
command -v ffmpeg >/dev/null || { echo "ffmpeg nao instalado" >&2; exit 1; }

FONT=""
for f in /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf /usr/share/fonts/dejavu/DejaVuSans-Bold.ttf \
         /System/Library/Fonts/Supplemental/Arial\ Bold.ttf /Library/Fonts/Arial\ Bold.ttf; do
  [[ -f "$f" ]] && { FONT="$f"; break; }
done
VF="format=yuv420p"
if [[ -n "$FONT" ]] && ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext; then
  VF="drawtext=fontfile='$FONT':text='BusVideo TESTE %{pts\\:hms}':fontsize=72:fontcolor=white:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h-text_h-60,format=yuv420p"
fi
echo "Gerando $OUT (${SIZE}, 30 fps, ${SECS}s)..."
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "testsrc2=size=${SIZE}:rate=30" -t "$SECS" \
  -vf "$VF" -c:v libx264 -profile:v high -level 4.0 -preset veryfast -b:v 6M -maxrate 8M -bufsize 12M \
  -g 60 -an -movflags +faststart "$OUT"
command -v ffprobe >/dev/null && ffprobe -v error -show_entries stream=codec_name,width,height,avg_frame_rate,level -of default=nw=1 "$OUT"
echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
