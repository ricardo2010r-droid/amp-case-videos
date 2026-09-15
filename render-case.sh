#!/usr/bin/env bash
# Render case.html 9:16 to a silent mp4, frames shot in parallel.
#   ./render-case.sh <out.mp4> <seconds> [fps] [jobs]
set -euo pipefail
OUT="${1:?out.mp4}"; SECS="${2:?seconds}"; FPS="${3:-24}"; JOBS="${4:-$(nproc 2>/dev/null || echo 4)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ "$HERE" == /c/* ]]; then   # Git Bash on Windows
  export CHROME="${CHROME_BIN:-/c/Program Files/Google/Chrome/Application/chrome.exe}"
  PAGE="file:///C:/${HERE#/c/}/case.html"
else
  export CHROME="${CHROME_BIN:-google-chrome}"
  PAGE="file://$HERE/case.html"
fi
export PAGE="${PAGE// /%20}" FR="$HERE/.frames-case" FPS
rm -rf "$FR"; mkdir -p "$FR"
TOTAL=$(awk "BEGIN{print int($SECS*$FPS)}")
shoot(){ local T; T=$(awk "BEGIN{printf \"%.4f\", $1/$FPS}")
  "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox --disable-dev-shm-usage \
    --allow-file-access-from-files --force-device-scale-factor=1 --window-size=1080,1920 \
    --virtual-time-budget=1500 --screenshot="$FR/f_$(printf '%04d' "$1").png" "$PAGE?v=1&t=$T" 2>/dev/null || true; }
export -f shoot
echo "Rendering $TOTAL frames with $JOBS jobs..."
seq 0 $((TOTAL-1)) | xargs -P "$JOBS" -I{} bash -c 'shoot {}'
for pass in 1 2 3; do
  BAD=$(python3 "$HERE/checkframes.py" "$FR" 2>/dev/null || python "$HERE/checkframes.py" "$FR"); [ -z "$BAD" ] && break
  echo "  pass $pass: redoing $(echo $BAD | wc -w)"; for i in $BAD; do shoot "$i"; done
done
BAD=$(python3 "$HERE/checkframes.py" "$FR" 2>/dev/null || python "$HERE/checkframes.py" "$FR")
[ -z "$BAD" ] || { echo "ERROR: blank frames remain: $BAD" >&2; exit 1; }
[ "$(ls "$FR" | wc -l)" -eq "$TOTAL" ] || { echo "ERROR: missing frames" >&2; exit 1; }
ffmpeg -v error -y -framerate "$FPS" -i "$FR/f_%04d.png" -c:v libx264 -crf 20 -pix_fmt yuv420p "$OUT"
rm -rf "$FR"; echo "Done -> $OUT"
