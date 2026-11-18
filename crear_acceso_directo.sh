#!/usr/bin/env bash
# Mac/Linux: crea el acceso directo "Clipmaker" en el escritorio.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/run.sh"
if [ "$(uname)" = "Darwin" ]; then
  DEST="$HOME/Desktop"
  mkdir -p "$DEST"
  FILE="$DEST/Clipmaker.command"
  printf '#!/usr/bin/env bash\ncd "%s" && exec ./run.sh\n' "$DIR" > "$FILE"
  chmod +x "$FILE"
else
  DEST="$( (command -v xdg-user-dir >/dev/null && xdg-user-dir DESKTOP) || true )"
  [ -n "$DEST" ] && [ "$DEST" != "$HOME" ] || DEST="$HOME/Desktop"
  mkdir -p "$DEST"
  FILE="$DEST/Clipmaker.desktop"
  cat > "$FILE" <<DESK
[Desktop Entry]
Type=Application
Name=Clipmaker
Comment=Clips horizontales a verticales con plantilla
Exec=bash -c 'cd "$DIR" && ./run.sh'
Icon=$DIR/static/clipmaker.png
Terminal=true
Categories=AudioVideo;
DESK
  chmod +x "$FILE"
  command -v gio >/dev/null && gio set "$FILE" metadata::trusted true 2>/dev/null || true
fi
echo "Acceso directo creado: $FILE"
