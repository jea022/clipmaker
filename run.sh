#!/usr/bin/env bash
# Mac/Linux: prepara el entorno la primera vez y abre la web local. Se reinicia solo tras una actualización.
set -e
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Falta ffmpeg. Mac: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
  exit 1
fi
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Falta Python 3.9 o superior. Mac: brew install python@3.12 (o https://www.python.org/downloads/)"
  exit 1
fi
if [ ! -d .venv ]; then
  "$PY" -m venv .venv || { echo "No pude crear el entorno de Python. En Ubuntu: sudo apt install python3-venv"; exit 1; }
fi
# En macOS el puerto 5000 suele estar ocupado por AirPlay Receiver
if [ "$(uname)" = "Darwin" ]; then DEFAULT_PORT=5055; else DEFAULT_PORT=5000; fi
PORT="${1:-$DEFAULT_PORT}"
(sleep 2; (command -v open >/dev/null && open "http://127.0.0.1:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") || true) &
while true; do
  cmp -s requirements.txt .venv/requirements.installed || { .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/requirements.installed; }
  [ -f templates/wganga.json ] || .venv/bin/python make_template.py
  .venv/bin/python app.py "$PORT" && break
  [ $? -eq 42 ] || break
done
