#!/usr/bin/env bash
set -euo pipefail

# render_png.sh — Render a single-file HTML+SVG diagram to a crisp PNG via headless Chrome.
# Automatically reads <svg viewBox="0 0 W H"> so the screenshot fits cleanly with zero clipping.
#
# Usage:
#   bash render_png.sh <input.html> [output.png] [--width W] [--height H] [--scale S]

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <input.html> [output.png] [--width W] [--height H] [--scale S]" >&2
  exit 1
fi

INPUT_HTML="$1"
shift

OUT_PNG=""
WIN_W=""
WIN_H=""
SCALE="1.5"

if [[ $# -gt 0 && "$1" != --* ]]; then
  OUT_PNG="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --width)  WIN_W="$2"; shift 2 ;;
    --height) WIN_H="$2"; shift 2 ;;
    --scale)  SCALE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

ABS_HTML="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$INPUT_HTML")"
if [[ ! -f "$ABS_HTML" ]]; then
  echo "Error: file not found: $ABS_HTML" >&2
  exit 1
fi

if [[ -z "$OUT_PNG" ]]; then
  OUT_PNG="${ABS_HTML%.html}.png"
else
  OUT_PNG="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$OUT_PNG")"
fi

# Auto-detect SVG viewBox dimensions if width/height not explicitly passed
if [[ -z "$WIN_W" || -z "$WIN_H" ]]; then
  read -r AUTO_W AUTO_H < <(python3 - "$ABS_HTML" <<'PY'
import re, sys, math
text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
m = re.search(r'viewBox\s*=\s*["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["\']', text)
if m:
    w = math.ceil(float(m.group(1))) + 88
    h = math.ceil(float(m.group(2))) + 96
    print(f"{w} {h}")
else:
    print("1520 1020")
PY
)
  WIN_W="${WIN_W:-$AUTO_W}"
  WIN_H="${WIN_H:-$AUTO_H}"
fi

CHROME_BIN=""
for cand in google-chrome chromium chromium-browser /usr/bin/google-chrome; do
  if command -v "$cand" >/dev/null 2>&1; then
    CHROME_BIN="$(command -v "$cand")"
    break
  fi
done

if [[ -z "$CHROME_BIN" ]]; then
  echo "Error: google-chrome or chromium not found in PATH." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_PNG")"

"$CHROME_BIN" \
  --headless=new \
  --disable-gpu \
  --no-sandbox \
  --hide-scrollbars \
  --force-device-scale-factor="$SCALE" \
  --window-size="${WIN_W},${WIN_H}" \
  --screenshot="$OUT_PNG" \
  "file://${ABS_HTML}" >/dev/null 2>&1

echo "Rendered: $OUT_PNG (window=${WIN_W}x${WIN_H}, scale=${SCALE})"
