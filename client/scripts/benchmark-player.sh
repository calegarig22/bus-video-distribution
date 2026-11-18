#!/usr/bin/env bash
# Benchmark do mpv no Raspberry Pi com as flags de producao (busvideo_client/player/mpv.py).
# Uso: benchmark-player.sh VIDEO.mp4 [SECONDS=120] [--vo gpu|drm] [--hwdec v4l2m2m-copy|none] [--audio]
# Veredito OK: frames perdidos < 1% e CPU media do mpv < 60%.
set -uo pipefail
VIDEO=""; SECONDS_TOTAL=120; VO=gpu; HWDEC=v4l2m2m-copy; AUDIO=no
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vo) VO="$2"; shift 2 ;;
    --hwdec) HWDEC="$2"; shift 2 ;;
    --audio) AUDIO=yes; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) if [[ -z "$VIDEO" ]]; then VIDEO="$1"; else SECONDS_TOTAL="$1"; fi; shift ;;
  esac
done
[[ -f "${VIDEO:-}" ]] || { echo "Uso: $0 VIDEO.mp4 [SECONDS] [--vo gpu|drm] [--hwdec v4l2m2m-copy|none]" >&2; exit 2; }
command -v mpv >/dev/null || { echo "mpv nao instalado" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 nao instalado" >&2; exit 1; }

SOCK="/tmp/busvideo-bench-$$.sock"
CMD=(mpv --no-config --fs --loop-file=inf --no-osc --no-osd-bar --no-terminal --no-input-default-bindings
     --input-vo-keyboard=no --really-quiet --keep-open=no --idle=yes --force-window=yes
     "--input-ipc-server=$SOCK" --cache=yes --demuxer-max-bytes=64MiB "--vo=$VO")
[[ "$VO" == "gpu" ]] && CMD+=(--gpu-context=drm)
[[ "$HWDEC" != "none" ]] && CMD+=("--hwdec=$HWDEC")
[[ "$AUDIO" == "no" ]] && CMD+=(--audio=no)
CMD+=("$VIDEO")

FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of csv=p=0 "$VIDEO" 2>/dev/null | awk -F/ '{ if ($2>0) printf "%.2f", $1/$2; else print $1 }')
FPS=${FPS:-30}
echo "Video: $VIDEO  (fps=$FPS)  duracao do teste: ${SECONDS_TOTAL}s"
echo "Comando: ${CMD[*]}"
"${CMD[@]}" & MPV_PID=$!
cleanup() { kill "$MPV_PID" 2>/dev/null; rm -f "$SOCK"; }
trap cleanup EXIT INT TERM

for _ in $(seq 1 50); do [[ -S "$SOCK" ]] && break; kill -0 "$MPV_PID" 2>/dev/null || { echo "mpv encerrou imediatamente (veja: ${CMD[*]} sem --really-quiet)"; exit 1; }; sleep 0.2; done
[[ -S "$SOCK" ]] || echo "AVISO: socket IPC nao apareceu; metricas do mpv indisponiveis"

prop() {  # prop NAME -> value via IPC
  python3 - "$SOCK" "$1" <<'PY' 2>/dev/null
import json, socket, sys
s = socket.socket(socket.AF_UNIX); s.settimeout(2)
try:
    s.connect(sys.argv[1]); s.sendall((json.dumps({"command": ["get_property", sys.argv[2]], "request_id": 1}) + "\n").encode())
    buf = b""
    while b"\n" not in buf: buf += s.recv(4096)
    for line in buf.split(b"\n"):
        if line.strip():
            m = json.loads(line)
            if m.get("request_id") == 1: print(m.get("data", "")); break
except Exception: print("")
PY
}
temp() { command -v vcgencmd >/dev/null && vcgencmd measure_temp 2>/dev/null | tr -dc '0-9.' || echo "-"; }
throttled() { command -v vcgencmd >/dev/null && vcgencmd get_throttled 2>/dev/null | cut -d= -f2 || echo "-"; }
cpu_of() { ps -o %cpu= -p "$1" 2>/dev/null | tr -d ' ' || echo 0; }

printf "\n%-6s %-7s %-7s %-10s %-8s %-8s %-12s %s\n" "t(s)" "cpu%" "temp" "throttled" "drops" "delayed" "time-pos" "hwdec"
sum_cpu=0; n=0; drops=0; delayed=0; hw="-"; elapsed=0
while [[ $elapsed -lt $SECONDS_TOTAL ]]; do
  sleep 5; elapsed=$((elapsed + 5))
  kill -0 "$MPV_PID" 2>/dev/null || { echo "mpv morreu em t=${elapsed}s"; break; }
  c=$(cpu_of "$MPV_PID"); drops=$(prop frame-drop-count); delayed=$(prop vo-delayed-frame-count)
  pos=$(prop time-pos); hw=$(prop hwdec-current)
  printf "%-6s %-7s %-7s %-10s %-8s %-8s %-12s %s\n" "$elapsed" "$c" "$(temp)" "$(throttled)" "${drops:--}" "${delayed:--}" "${pos:--}" "${hw:--}"
  sum_cpu=$(awk -v a="$sum_cpu" -v b="${c:-0}" 'BEGIN{print a+b}'); n=$((n + 1))
done

avg_cpu=$(awk -v s="$sum_cpu" -v n="$n" 'BEGIN{ if (n>0) printf "%.1f", s/n; else print 0 }')
total_frames=$(awk -v f="$FPS" -v t="$elapsed" 'BEGIN{printf "%d", f*t}')
drops=${drops:-0}; [[ "$drops" =~ ^[0-9]+$ ]] || drops=0
drop_pct=$(awk -v d="$drops" -v t="$total_frames" 'BEGIN{ if (t>0) printf "%.2f", 100*d/t; else print 0 }')
echo
echo "================ RESUMO ================"
echo " vo=$VO hwdec=$HWDEC (ativo: ${hw:-?})"
echo " CPU media do mpv : ${avg_cpu}%"
echo " Frames perdidos  : $drops de ~$total_frames (${drop_pct}%)"
echo " Temperatura final: $(temp) C   throttled=$(throttled) (0x0 = ok)"
if awk -v c="$avg_cpu" -v d="$drop_pct" 'BEGIN{exit !(c<60 && d<1)}'; then
  echo " VEREDITO: OK - configuracao adequada para producao"
else
  echo " VEREDITO: REPROVADO - teste: --vo drm | --hwdec none | video em 720p | veja docs/TROUBLESHOOTING.md"
fi
