#!/usr/bin/env bash
# Mac/Linux: crea el icono "Clipmaker" en el escritorio. Se abre SIN terminal y sigue funcionando aunque
# cierres el navegador; se cierra con el boton "Cerrar Clipmaker" de la pagina.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/run.sh" "$DIR/launcher.py" 2>/dev/null || true
ESC_DIR="$(printf '%s' "$DIR" | sed 's/[&|\\]/\\&/g')"

if [ "$(uname)" = "Darwin" ]; then
  APP="$HOME/Desktop/Clipmaker.app"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Clipmaker</string>
  <key>CFBundleDisplayName</key><string>Clipmaker</string>
  <key>CFBundleIdentifier</key><string>com.clipmaker.app</string>
  <key>CFBundleExecutable</key><string>Clipmaker</string>
  <key>CFBundleIconFile</key><string>Clipmaker</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
  cat > "$APP/Contents/MacOS/Clipmaker.template" <<'SCRIPT'
#!/bin/bash
# Abre Clipmaker en segundo plano (sin Terminal). Las apps abiertas desde Finder no heredan el PATH de Homebrew.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="@DIR@"
cd "$DIR" || { osascript -e 'display dialog "No encuentro la carpeta de Clipmaker. Vuelve a ejecutar crear_acceso_directo.sh" with title "Clipmaker" buttons {"OK"} with icon stop'; exit 1; }
PY=""
if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$(command -v "$c")"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Falta Python 3.9 o superior. Abre Terminal y ejecuta: brew install python@3.12" with title "Clipmaker" buttons {"OK"} with icon stop'
  exit 1
fi
nohup "$PY" "$DIR/launcher.py" >/dev/null 2>&1 &
exit 0
SCRIPT
  sed "s|@DIR@|$ESC_DIR|g" "$APP/Contents/MacOS/Clipmaker.template" > "$APP/Contents/MacOS/Clipmaker"
  rm -f "$APP/Contents/MacOS/Clipmaker.template"
  chmod +x "$APP/Contents/MacOS/Clipmaker"
  [ -f "$DIR/static/clipmaker.icns" ] && cp "$DIR/static/clipmaker.icns" "$APP/Contents/Resources/Clipmaker.icns"
  touch "$APP"
  echo "Listo: $APP"
  echo "Ábrela con doble clic. Si macOS la bloquea: clic derecho > Abrir (solo la primera vez)."
else
  DEST="$( (command -v xdg-user-dir >/dev/null && xdg-user-dir DESKTOP) || true )"
  [ -n "$DEST" ] && [ "$DEST" != "$HOME" ] || DEST="$HOME/Desktop"
  mkdir -p "$DEST"
  FILE="$DEST/Clipmaker.desktop"
  cat > "$FILE.template" <<'DESK'
[Desktop Entry]
Type=Application
Name=Clipmaker
Comment=Clips horizontales a verticales con plantilla
Exec=bash -c 'cd "@DIR@" && PY=.venv/bin/python; [ -x "$PY" ] || PY=python3; exec "$PY" launcher.py'
Icon=@DIR@/static/clipmaker.png
Terminal=false
Categories=AudioVideo;
DESK
  sed "s|@DIR@|$ESC_DIR|g" "$FILE.template" > "$FILE"
  rm -f "$FILE.template"
  chmod +x "$FILE"
  command -v gio >/dev/null && gio set "$FILE" metadata::trusted true 2>/dev/null || true
  echo "Listo: $FILE"
fi
