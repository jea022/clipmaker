#!/usr/bin/env bash
# Mac/Linux: prepara el entorno la primera vez y abre la web local. Se reinicia solo tras una actualización.
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Falta ffmpeg. Mac: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"; exit 1; }
command -v python3 >/dev/null || { echo "Falta Python 3.10 o superior (https://www.python.org/downloads/)"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
PORT="${1:-5000}"
(sleep 2; (command -v open >/dev/null && open "http://127.0.0.1:$PORT") || (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT") || true) &
while true; do
  cmp -s requirements.txt .venv/requirements.installed || { .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/requirements.installed; }
  [ -f templates/wganga.json ] || .venv/bin/python make_template.py
  .venv/bin/python app.py "$PORT" && break
  [ $? -eq 42 ] || break
done
