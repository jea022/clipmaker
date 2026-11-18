#!/usr/bin/env python3
"""Pruebas del actualizador con un servidor HTTP local y zips fabricados."""
import http.server
import io
import json
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import updater

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def make_root(version="1.0.0"):
    r = Path(tempfile.mkdtemp())
    for rel, txt in {"app.py": "OLD app", "clipmaker.py": "OLD cm", "static/index.html": "OLD html", "VERSION": version,
                     "data/cam_defaults.json": '{"wganga": [0.1,0.1,0.2,0.2]}', ".venv/marker": "venv",
                     "bin/ffmpeg.exe": "fake-ffmpeg", "secrets/token_x.json": "secreto", "update.json": "{}"}.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    return r


def make_zip(files, prefix="clipmaker-main/", extra_names=()):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, txt in files.items():
            z.writestr(prefix + rel, txt)
        for n in extra_names:
            z.writestr(n, "MALICIOSO")
    return b.getvalue()


GOOD = {"app.py": "NEW app", "clipmaker.py": "NEW cm", "static/index.html": "NEW html", "VERSION": "1.1.0", "extra.py": "nuevo"}
HOSTILE = dict(GOOD, **{".venv/marker": "PWNED", "data/cam_defaults.json": "PWNED", "secrets/token_x.json": "PWNED",
                        "bin/ffmpeg.exe": "PWNED", "update.json": "PWNED", "__pycache__/x.pyc": "PWNED"})

# --- versiones ---
check("1.10.0 > 1.9.0", updater.parse_version("1.10.0") > updater.parse_version("1.9.0"))
for bad in ("", "abc", "1.2.x", "1.0\n<script>", "1..2", "1.2.3.4.5", "-1"):
    try:
        updater.parse_version(bad)
        check(f"version invalida {bad!r}", False)
    except updater.UpdateError:
        check(f"version invalida {bad!r}", True)

# --- aplicar zip ---
root = make_root()
res = updater.apply_zip(make_zip(HOSTILE), root)
check("aplica y reporta version", res["version"] == "1.1.0" and res["files"] == 5, res)
check("codigo actualizado", (root / "app.py").read_text() == "NEW app" and (root / "VERSION").read_text() == "1.1.0")
check("archivo nuevo creado", (root / "extra.py").read_text() == "nuevo")
for rel in (".venv/marker", "data/cam_defaults.json", "bin/ffmpeg.exe", "secrets/token_x.json", "update.json"):
    check(f"no pisa {rel}", (root / rel).read_text() != "PWNED")
check("ignora __pycache__", not (root / "__pycache__").exists())
bk = list((root / "data" / "backups").glob("*/app.py"))
check("copia de seguridad del codigo anterior", len(bk) == 1 and bk[0].read_text() == "OLD app")

# --- zip-slip y rutas peligrosas ---
root = make_root()
before = {p.relative_to(root): p.read_text() for p in root.rglob("*") if p.is_file()}
evil = ["clipmaker-main/../evil.txt", "clipmaker-main/sub/../../evil2.txt", "/abs_evil.txt", "clipmaker-main/C:/evil3.txt",
        "clipmaker-main/..\\evil4.txt"]
outside = root.parent / "evil.txt"
updater.apply_zip(make_zip(GOOD, extra_names=evil), root)
check("zip-slip no escribe fuera", not outside.exists() and not (root.parent / "evil2.txt").exists() and not Path("/abs_evil.txt").exists())
check("rutas raras no crean archivos", not list(root.rglob("evil*")))

# --- zips invalidos: nada cambia ---
def unchanged(root, before):
    return {p.relative_to(root): p.read_text() for p in root.rglob("*") if p.is_file() and "backups" not in p.parts} == before

for name, data in (("basura", b"esto no es un zip"), ("vacio", b""),
                   ("sin app.py", make_zip({k: v for k, v in GOOD.items() if k != "app.py"})),
                   ("sin VERSION", make_zip({k: v for k, v in GOOD.items() if k != "VERSION"})),
                   ("sin index.html", make_zip({k: v for k, v in GOOD.items() if k != "static/index.html"})),
                   ("VERSION malicioso", make_zip(dict(GOOD, VERSION="1.0; rm -rf /"))),
                   ("otro proyecto", make_zip({"main.py": "x", "README": "y"}))):
    root = make_root()
    snap = {p.relative_to(root): p.read_text() for p in root.rglob("*") if p.is_file()}
    try:
        updater.apply_zip(data, root)
        check(f"zip {name} rechazado", False)
    except updater.UpdateError as e:
        check(f"zip {name} rechazado y sin cambios", unchanged(root, snap), str(e)[:50])

big = make_zip(dict(GOOD, **{"huge.bin": "x" * 1000}))
updater.MAX_FILE_BYTES = 500
root = make_root(); snap = {p.relative_to(root): p.read_text() for p in root.rglob("*") if p.is_file()}
try:
    updater.apply_zip(big, root); check("archivo enorme rechazado", False)
except updater.UpdateError:
    check("archivo enorme rechazado y sin cambios", unchanged(root, snap))
updater.MAX_FILE_BYTES = 30 * 1024 * 1024
updater.MAX_FILES = 3
root = make_root()
try:
    updater.apply_zip(make_zip(GOOD), root); check("demasiados archivos rechazado", False)
except updater.UpdateError:
    check("demasiados archivos rechazado", True)
updater.MAX_FILES = 500

# --- raiz del zip distinta (sin carpeta, o anidada) ---
for pref in ("", "repo-main/clipmaker/"):
    root = make_root()
    r = updater.apply_zip(make_zip(GOOD, prefix=pref), root)
    check(f"zip con prefijo {pref!r}", r["version"] == "1.1.0" and (root / "extra.py").exists())

# --- fallo a mitad de escritura: se restaura todo ---
from unittest import mock
root = make_root()
snap = {p.relative_to(root): p.read_text() for p in root.rglob("*") if p.is_file()}
orig_replace, calls = Path.replace, {"n": 0}


def flaky_replace(self, target):
    calls["n"] += 1
    if calls["n"] == 3:
        raise OSError("disco lleno simulado")
    return orig_replace(self, target)


with mock.patch.object(Path, "replace", flaky_replace):
    try:
        updater.apply_zip(make_zip(GOOD), root)
        check("fallo a mitad restaura", False)
    except updater.UpdateError as e:
        check("fallo a mitad avisa y restaura", "restauró" in str(e))
check("tras el fallo el codigo es el anterior", unchanged(root, snap) and not (root / "extra.py").exists()
      and not list(root.rglob("*.new")))

# --- hosts permitidos ---
cfg = {}
for url, ok in (("https://github.com/x/y/archive/main.zip", True), ("https://raw.githubusercontent.com/x/y/main/VERSION", True),
                ("http://github.com/x", False), ("https://evil.com/x.zip", False), ("https://github.com.evil.com/x", False),
                ("ftp://github.com/x", False), ("file:///etc/passwd", False), ("http://127.0.0.1:1/x", False)):
    try:
        updater.check_url(url, cfg); got = True
    except updater.UpdateError:
        got = False
    check(f"host {url}", got == ok)
try:
    updater.check_url("http://127.0.0.1:1/x", {"allowed_hosts": ["127.0.0.1"]}); check("localhost solo si se permite", True)
except updater.UpdateError:
    check("localhost solo si se permite", False)

# --- servidor local: check / update de punta a punta ---
state = {"version": "1.1.0", "zip": make_zip(GOOD)}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/VERSION":
            body = state["version"].encode()
        elif self.path == "/repo.zip":
            body = state["zip"]
        elif self.path == "/redirect":
            self.send_response(302); self.send_header("Location", f"http://localhost:{trap_port}/trampa"); self.end_headers(); return
        elif self.path == "/redirect-ok":
            self.send_response(302); self.send_header("Location", "/VERSION"); self.end_headers(); return
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


trap_hits = []


class Trap(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        trap_hits.append(self.path)
        self.send_response(200); self.send_header("Content-Length", "5"); self.end_headers(); self.wfile.write(b"1.9.9")

    def log_message(self, *a):
        pass


trap = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trap)
threading.Thread(target=trap.serve_forever, daemon=True).start()
trap_port = trap.server_address[1]
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
cfgfile = Path(tempfile.mkdtemp()) / "update.json"
updater.CONFIG_FILES = (cfgfile,)


def set_cfg(**kw):
    c = {"version_url": f"http://127.0.0.1:{port}/VERSION", "zip_url": f"http://127.0.0.1:{port}/repo.zip", "allowed_hosts": ["127.0.0.1"]}
    c.update(kw)
    cfgfile.write_text(json.dumps(c))


root = make_root()
check("sin config -> deshabilitado", updater.check(root) == {"enabled": False, "current": "1.0.0", "available": False})
set_cfg()
r = updater.check(root)
check("detecta version nueva", r["available"] and r["latest"] == "1.1.0" and r["current"] == "1.0.0", r)
state["version"] = "1.0.0"
check("misma version -> no hay", updater.check(root)["available"] is False)
state["version"] = "0.9"
check("version anterior -> no hay", updater.check(root)["available"] is False)
state["version"] = "<html>basura</html>"
r = updater.check(root)
check("VERSION basura -> error controlado", r["available"] is False and "error" in r, r.get("error"))
state["version"] = "1.1.0"
set_cfg(version_url=f"http://127.0.0.1:{port}/nada")
check("404 -> error controlado", "error" in updater.check(root))
set_cfg(version_url=f"http://127.0.0.1:{port}/redirect")
check("redireccion a dominio no permitido -> bloqueada", "error" in updater.check(root))
check("redireccion bloqueada: NUNCA se conecto al destino", trap_hits == [], trap_hits)
set_cfg(version_url=f"http://127.0.0.1:{port}/redirect-ok")
check("redireccion al mismo dominio permitido -> se sigue", updater.check(root).get("latest") == "1.1.0")
set_cfg(version_url="http://127.0.0.1:9/VERSION")
check("servidor caido -> error controlado", "No pude conectar" in updater.check(root).get("error", ""))
set_cfg()
r = updater.update(root)
check("update de punta a punta", r["version"] == "1.1.0" and r["from"] == "1.0.0" and (root / "app.py").read_text() == "NEW app", r)
try:
    updater.update(root); check("segundo update -> ya tienes la ultima", False)
except updater.UpdateError as e:
    check("segundo update -> ya tienes la ultima", "última" in str(e))
state.update(version="1.2.0", zip=b"zip roto")
try:
    updater.update(root); check("zip roto en servidor -> sin cambios", False)
except updater.UpdateError:
    check("zip roto en servidor -> sin cambios", (root / "app.py").read_text() == "NEW app")
srv.shutdown()

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
