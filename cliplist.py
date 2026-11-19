"""Lista de clips pendientes: marcas de tiempo de un directo/VOD, por streamer.

Se guarda en data/clip_lists.json. Uso:
  python cliplist.py add westcol 02:04:00 "Se le cae todo" --source "https://..."
  python cliplist.py list [westcol]
  python cliplist.py remove westcol 1
"""
import json
import re
import sys
import uuid
from pathlib import Path

FILE = Path(__file__).resolve().parent / "data" / "clip_lists.json"
TS_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")


def parse_time(text):
    """'02:04:00' | '2:04:00' | '4:00' -> 'HH:MM:SS' normalizado. ValueError si no es válida."""
    m = TS_RE.match(str(text).strip())
    if not m:
        raise ValueError("Marca de tiempo inválida (usa HH:MM:SS o MM:SS)")
    h, mi, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if mi > 59 or s > 59:
        raise ValueError("Minutos y segundos deben ser menores de 60")
    return f"{h:02d}:{mi:02d}:{s:02d}"


def _seconds(t):
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


def _norm_streamer(name):
    name = re.sub(r"[^a-z0-9_]", "", str(name).strip().lower().lstrip("@#"))
    if not name:
        raise ValueError("Streamer inválido")
    return name


def _load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(FILE)


def get(streamer=None):
    data = _load()
    if streamer is None:
        return {k: sorted(v, key=lambda c: _seconds(c["time"])) for k, v in data.items()}
    return sorted(data.get(_norm_streamer(streamer), []), key=lambda c: _seconds(c["time"]))


def add(streamer, time, note="", source=""):
    streamer, time = _norm_streamer(streamer), parse_time(time)
    data = _load()
    items = data.setdefault(streamer, [])
    if any(c["time"] == time and c.get("source", "") == str(source).strip() for c in items):
        raise ValueError(f"{time} ya está en la lista de {streamer}")
    clip = {"id": uuid.uuid4().hex[:8], "time": time, "note": str(note).strip()[:200],
            "source": str(source).strip()[:500]}
    items.append(clip)
    _save(data)
    return clip


def remove(streamer, clip_id):
    streamer = _norm_streamer(streamer)
    data = _load()
    items = data.get(streamer, [])
    left = [c for c in items if c["id"] != str(clip_id)]
    if len(left) == len(items):
        raise KeyError("Clip no encontrado")
    data[streamer] = left
    _save(data)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "add" and len(rest) >= 2:
            note = rest[2] if len(rest) > 2 and not rest[2].startswith("--") else ""
            source = rest[rest.index("--source") + 1] if "--source" in rest else ""
            c = add(rest[0], rest[1], note, source)
            print(f"Añadido {c['time']} a la lista de {_norm_streamer(rest[0])} (id {c['id']})")
        elif cmd == "list":
            for who, items in get(rest[0] if rest else None).items() if not rest else {rest[0]: get(rest[0])}.items():
                print(f"{who}:")
                for c in items:
                    print(f"  {c['id']}  {c['time']}  {c['note']}  {c['source']}".rstrip())
        elif cmd == "remove" and len(rest) == 2:
            remove(*rest)
            print("Eliminado")
        else:
            print(__doc__)
            return 1
    except (ValueError, KeyError) as e:
        print(e.args[0])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
