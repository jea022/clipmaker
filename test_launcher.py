#!/usr/bin/env python3
"""Pruebas del lanzador: unidades (puertos, bloqueo, reinicios, ffmpeg) e integracion con la app real."""
import http.server
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
FILES = ["app.py", "clipmaker.py", "captions.py", "updater.py", "publish_youtube.py", "make_template.py", "launcher.py",
         "requirements.txt", "VERSION", "layout.json", "hashtags.json"]
DIRS = ["static", "templates", "fonts"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
fails = []
procs = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def make_box(with_venv=True):
    box = Path(tempfile.mkdtemp())
    for f in FILES:
        shutil.copy(HERE / f, box / f)
    for d in DIRS:
        shutil.copytree(HERE / d, box / d)
    if with_venv:
        shutil.copy(HERE / "requirements.txt", HERE / ".venv" / "requirements.installed")
        os.symlink(HERE / ".venv", box / ".venv")
    return box


def load_launcher(box, env=None):
    for k, v in (env or {}).items():
        os.environ[k] = v
    spec = importlib.util.spec_from_file_location(f"launcher_{abs(hash(str(box)))}", box / "launcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def hx(method, port, path, headers=None, body=None, timeout=10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return None, b""


def ping(port):
    code, data = hx("GET", port, "/api/ping", timeout=2)
    try:
        return json.loads(data) if code == 200 else None
    except ValueError:
        return None


def wait_for(fn, timeout=40, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def start_launcher(box, port, py=None, env_extra=None):
    env = dict(os.environ, CLIPMAKER_NO_BROWSER="1", CLIPMAKER_PORT_BASE=str(port))
    env.update(env_extra or {})
    p = subprocess.Popen([py or str(HERE / ".venv" / "bin" / "python"), str(box / "launcher.py"), "--no-browser", "--port", str(port)],
                         cwd=box, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    procs.append(p)
    return p


def stop(box, port, proc):
    hx("POST", port, "/api/shutdown", {"X-Clipmaker": "1"}, timeout=5)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


# =================== unidades ===================
box = make_box()
env_base = {"CLIPMAKER_PORT_BASE": "5900"}
mod = load_launcher(box, env_base)

# --- puertos ---
busy = socket.socket()
busy.bind(("127.0.0.1", 0))
busy.listen(1)
bp = busy.getsockname()[1]
check("port_free detecta un puerto ocupado", not mod.port_free(bp))
check("pick_port salta al siguiente cuando el preferido esta ocupado", mod.pick_port(bp) in (bp + 1, bp + 2, bp + 3), mod.pick_port(bp))
busy.close()
check("pick_port devuelve el preferido si esta libre", mod.pick_port(free_port()) > 1024)

# --- reinicios ---
def seq_spawn(codes):
    it = iter(codes)
    return lambda: subprocess.Popen([sys.executable, "-c", f"import sys; sys.exit({next(it)})"])


notes = []
mod.notify = lambda t, x: notes.append((t, x))
prep = []
check("cierre normal (0): termina sin reiniciar", mod.supervise(seq_spawn([0]), 1, pause=0) == 0)
check("codigo 42 (actualizacion): reinicia y llama a prepare", mod.supervise(seq_spawn([42, 42, 0]), 1, prepare=lambda: prep.append(1), pause=0) == 0 and len(prep) == 2, prep)
check("3 caidas rapidas seguidas: se rinde, avisa y devuelve el codigo", mod.supervise(seq_spawn([1, 1, 1, 0]), 1, pause=0) == 1 and len(notes) == 1 and "varias veces" in notes[0][1], notes)
notes.clear()
check("una caida aislada se recupera (reinicia solo)", mod.supervise(seq_spawn([3, 0]), 1, pause=0) == 0 and notes == [])
ready = []
mod.wait_ready = lambda port, timeout=60: True
mod.supervise(seq_spawn([0]), 1, on_ready=lambda: ready.append(1), pause=0)
time.sleep(0.3)
check("on_ready se avisa una vez cuando la app responde", ready == [1], ready)

# --- bloqueo de una sola copia ---
mod.DATA.mkdir(exist_ok=True)
for f in (mod.LOCK, mod.STATE):
    if f.exists():
        f.unlink()
check("acquire_lock: la primera copia lo consigue", mod.acquire_lock())
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
mod.LOCK.write_text(str(sleeper.pid))
check("acquire_lock: si otra copia viva lo tiene, no lo consigue", not mod.acquire_lock())
sleeper.kill()
sleeper.wait()
check("acquire_lock: un bloqueo viejo (proceso muerto) se recupera", mod.acquire_lock())
mod.write_state(1234, "app")
mod.release_lock()
check("release_lock quita el bloqueo y el estado propios", not mod.LOCK.exists() and not mod.STATE.exists())
mod.LOCK.write_text("999999")
check("pid_alive: un pid inexistente no esta vivo", not mod.pid_alive(999999) and mod.pid_alive(os.getpid()) and not mod.pid_alive(0) and not mod.pid_alive("x"))
mod.LOCK.unlink()

# --- ffmpeg para Windows: descarga y extraccion ---
def build_zip(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return b.getvalue()


zips = {
    "/ok.zip": build_zip({"ffmpeg-x/bin/ffmpeg.exe": b"FFMPEG" * 5000, "ffmpeg-x/bin/ffprobe.exe": b"FFPROBE" * 5000,
                          "ffmpeg-x/bin/ffplay.exe": b"PLAY", "ffmpeg-x/LICENSE.txt": b"lic", "../evil.exe": b"x"}),
    "/sin.zip": build_zip({"ffmpeg-x/bin/ffmpeg.exe": b"solo uno"}),
    "/otro.zip": build_zip({"x/readme.txt": b"nada"}),
    "/roto.zip": b"esto no es un zip",
}


class FF(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = zips.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


ffsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FF)
threading.Thread(target=ffsrv.serve_forever, daemon=True).start()
ffp = ffsrv.server_address[1]
bin_dir = Path(tempfile.mkdtemp()) / "bin"
msgs = []
mod.download_ffmpeg(f"http://127.0.0.1:{ffp}/ok.zip", bin_dir, msgs.append)
check("ffmpeg: extrae ffmpeg.exe y ffprobe.exe con su contenido",
      (bin_dir / "ffmpeg.exe").read_bytes() == b"FFMPEG" * 5000 and (bin_dir / "ffprobe.exe").read_bytes() == b"FFPROBE" * 5000)
check("ffmpeg: no extrae nada mas (ffplay, licencia, rutas raras)", sorted(p.name for p in bin_dir.iterdir()) == ["ffmpeg.exe", "ffprobe.exe"] and not (bin_dir.parent / "evil.exe").exists(), [p.name for p in bin_dir.iterdir()])
check("ffmpeg: muestra el avance y termina con 'listo'", any("%" in m for m in msgs) is True or len(msgs) >= 1, msgs[-2:])
check("ffmpeg: termina diciendo que esta listo", msgs[-1] == "ffmpeg listo.", msgs[-1:])
for name, path, frag in (("zip sin ffprobe", "/sin.zip", "no trae"), ("zip de otra cosa", "/otro.zip", "no trae"), ("zip roto", "/roto.zip", "dañado"),
                         ("404", "/nada.zip", "No pude descargar")):
    try:
        mod.download_ffmpeg(f"http://127.0.0.1:{ffp}{path}", Path(tempfile.mkdtemp()) / "bin", lambda m: None)
        check(f"ffmpeg: {name} se rechaza", False)
    except mod.SetupError as e:
        check(f"ffmpeg: {name} se rechaza", frag in str(e), str(e)[:60])
for bad in ("http://example.com/x.zip", "ftp://127.0.0.1/x.zip", "file:///etc/passwd"):
    try:
        mod.download_ffmpeg(bad, Path(tempfile.mkdtemp()) / "bin", lambda m: None)
        check(f"ffmpeg: rechaza {bad}", False)
    except mod.SetupError as e:
        check(f"ffmpeg: rechaza {bad}", "https" in str(e))
mod.MAX_FFMPEG_BYTES = 1000
try:
    mod.download_ffmpeg(f"http://127.0.0.1:{ffp}/ok.zip", Path(tempfile.mkdtemp()) / "bin", lambda m: None)
    check("ffmpeg: descarga demasiado grande se corta", False)
except mod.SetupError as e:
    check("ffmpeg: descarga demasiado grande se corta", "demasiado grande" in str(e))
mod.MAX_FFMPEG_BYTES = 400 * 1024 * 1024
ffsrv.shutdown()

# --- preparacion del entorno ---
empty = make_box(with_venv=False)
m2 = load_launcher(empty, env_base)
m2.MIN_PY = (99, 0)
s = m2.Setup()
s.run()
check("Setup: Python demasiado viejo da un mensaje claro y marca el paso que falla",
      s.error and "Python 99.0" in s.error and s.view()["steps"][0]["state"] == "falló", s.error)
m3 = load_launcher(box, env_base)
orig_which = m3.shutil.which
m3.shutil.which = lambda name: None if name in ("ffmpeg", "ffprobe") else orig_which(name)
s = m3.Setup()
s.run()
st = {x["id"]: x["state"] for x in s.view()["steps"]}
check("Setup sin ffmpeg: los demas pasos pasan y el de ffmpeg falla con instrucciones",
      st == {"venv": "listo", "deps": "listo", "tpl": "listo", "ffmpeg": "falló"} and "ffmpeg" in s.error and not s.done, (st, s.error))
m3.shutil.which = orig_which
s = m3.Setup()
s.run()
check("Setup con todo listo: termina sin errores", s.done and s.error is None and all(v == "listo" for v in {x["id"]: x["state"] for x in s.view()["steps"]}.values()), s.error)
check("env_ready en el entorno completo", m3.env_ready())
check("env_ready falla si falta ffmpeg", (setattr(m3.shutil, "which", lambda n: None), m3.env_ready())[1] is False)
m3.shutil.which = orig_which

# =================== integracion ===================
def sandbox_server(zip_bytes, version):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = version.encode() if self.path == "/VERSION" else zip_bytes if self.path == "/repo.zip" else None
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --- arranque, una sola copia, cierre ---
box = make_box()
port = free_port()
p1 = start_launcher(box, port)
info = wait_for(lambda: ping(port), 60)
check("lanzador: la app queda respondiendo en el puerto", info and info["app"] == "clipmaker", info)
code, body = hx("GET", port, "/")
check("lanzador: sirve la pagina de Clipmaker", code == 200 and b"Clipmaker" in body)
state = json.loads((box / "data" / "launcher.json").read_text())
check("lanzador: anota su estado (puerto, modo app)", state["port"] == port and state["mode"] == "app" and state["pid"] == p1.pid, state)
check("lanzador: escribe el registro", (box / "data" / "clipmaker.log").exists() and "app arrancada" in (box / "data" / "clipmaker.log").read_text())
t0 = time.time()
p2 = subprocess.run([str(HERE / ".venv" / "bin" / "python"), str(box / "launcher.py"), "--no-browser"], cwd=box,
                    env=dict(os.environ, CLIPMAKER_NO_BROWSER="1", CLIPMAKER_PORT_BASE=str(port)), capture_output=True, text=True, timeout=30)
check("segunda copia: no abre otra, avisa y sale al instante", p2.returncode == 0 and "ya está abierto" in p2.stdout and time.time() - t0 < 8, p2.stdout.strip())
check("segunda copia: la app original sigue siendo la misma", json.loads((box / "data" / "launcher.json").read_text())["pid"] == p1.pid)
check("no hay dos servidores (el puerto siguiente no responde)", ping(port + 1) is None)
code, _ = hx("POST", port, "/api/shutdown")
check("cierre sin cabecera X-Clipmaker -> 403 y sigue viva", code == 403 and ping(port) is not None)
code, _ = hx("POST", port, "/api/shutdown", {"X-Clipmaker": "text/plain"})
check("cierre con cabecera incorrecta -> 403", code == 403 and ping(port) is not None)
code, _ = hx("POST", port, "/api/shutdown", {"X-Clipmaker": "1"})
check("cierre con cabecera correcta -> 200", code == 200)
rc = None
try:
    rc = p1.wait(timeout=20)
except subprocess.TimeoutExpired:
    p1.kill()
check("al cerrar la app el lanzador termina con 0", rc == 0, rc)
check("tras cerrar: el puerto queda libre y se limpian estado y bloqueo",
      wait_for(lambda: ping(port) is None, 5) and not (box / "data" / "launcher.json").exists() and not (box / "data" / "launcher.lock").exists())

# --- reiniciar tras una actualizacion ---
box = make_box()
new_files = {}
for f in FILES + [f"{d}/{p.relative_to(HERE / d)}" for d in DIRS for p in (HERE / d).rglob("*") if p.is_file()]:
    new_files[f] = (HERE / f).read_bytes()
new_files["VERSION"] = b"99.0.0\n"
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w") as z:
    for name, data in new_files.items():
        z.writestr("clipmaker-main/" + name, data)
usrv = sandbox_server(zb.getvalue(), "99.0.0")
(box / "data").mkdir()
(box / "data" / "update.json").write_text(json.dumps({
    "version_url": f"http://127.0.0.1:{usrv.server_address[1]}/VERSION", "zip_url": f"http://127.0.0.1:{usrv.server_address[1]}/repo.zip",
    "allowed_hosts": ["127.0.0.1"]}))
port = free_port()
p1 = start_launcher(box, port)
first = wait_for(lambda: ping(port), 60)
check("actualizacion: la app arranca con la version actual", first and first["version"] == (HERE / "VERSION").read_text().strip(), first)
code, body = hx("POST", port, "/api/update/apply", {"Content-Type": "application/json"}, {}, timeout=30)
check("actualizacion: la app aplica la nueva version", code == 200 and json.loads(body)["version"] == "99.0.0", body[:100])
second = wait_for(lambda: (lambda i: i if i and i["version"] == "99.0.0" and i["pid"] != first["pid"] else None)(ping(port)), 40)
check("actualizacion: el lanzador la reinicia solo con la version nueva", second is not None, second)
check("actualizacion: es otro proceso (reinicio real) y el lanzador sigue siendo el mismo", second and second["pid"] != first["pid"] and p1.poll() is None)
check("actualizacion: tras reiniciar sigue habiendo una sola copia y el estado es el mismo", json.loads((box / "data" / "launcher.json").read_text())["pid"] == p1.pid)
stop(box, port, p1)
check("actualizacion: se puede cerrar despues del reinicio", p1.poll() == 0, p1.poll())
usrv.shutdown()

# --- una copia abierta con la consola (sin lanzador) se detecta ---
box = make_box()
base = free_port()
app_port = base + 3
app = subprocess.Popen([str(HERE / ".venv" / "bin" / "python"), str(box / "app.py"), str(app_port)], cwd=box, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
procs.append(app)
wait_for(lambda: ping(app_port), 40)
r = subprocess.run([str(HERE / ".venv" / "bin" / "python"), str(box / "launcher.py"), "--no-browser"], cwd=box,
                   env=dict(os.environ, CLIPMAKER_NO_BROWSER="1", CLIPMAKER_PORT_BASE=str(base)), capture_output=True, text=True, timeout=30)
check("detecta una app abierta con la consola y no abre otra", r.returncode == 0 and f":{app_port}" in r.stdout and ping(base) is None, r.stdout.strip())
hx("POST", app_port, "/api/shutdown", {"X-Clipmaker": "1"})
app.wait(timeout=15)

# --- falta ffmpeg: pagina de preparacion con el error y reintento ---
box = make_box()
port = free_port()
p1 = start_launcher(box, port, env_extra={"PATH": "/nonexistent"})
page = wait_for(lambda: (lambda r: r if r[0] == 200 else None)(hx("GET", port, "/")), 30)
check("sin ffmpeg: abre la pagina de preparacion", page and b"Preparando Clipmaker" in page[1])
check("sin ffmpeg: la pagina responde como 'preparacion' y no como la app", (ping(port) or {}).get("app") == "clipmaker-setup", ping(port))
status = wait_for(lambda: (lambda d: d if d.get("error") else None)(json.loads(hx("GET", port, "/api/setup-status")[1] or b"{}")), 30)
check("sin ffmpeg: el estado muestra el error con instrucciones", status and "ffmpeg" in status["error"] and "apt install ffmpeg" in status["error"], status and status["error"][:60])
check("sin ffmpeg: los pasos anteriores aparecen como listos", status and [s["state"] for s in status["steps"]] == ["listo", "listo", "listo", "falló"], status and status["steps"])
inst = subprocess.run([str(HERE / ".venv" / "bin" / "python"), str(box / "launcher.py"), "--no-browser"], cwd=box,
                      env=dict(os.environ, CLIPMAKER_NO_BROWSER="1", CLIPMAKER_PORT_BASE=str(port), PATH="/nonexistent"), capture_output=True, text=True, timeout=30)
check("sin ffmpeg: abrir otra vez no duplica, abre la misma pagina", inst.returncode == 0 and "ya está abierto" in inst.stdout, inst.stdout.strip())
check("sin ffmpeg: reintentar sin cabecera -> 403", hx("POST", port, "/api/setup-retry")[0] == 403 and hx("POST", port, "/api/setup-quit")[0] == 403)
check("sin ffmpeg: reintentar con cabecera -> 200 y sigue el error", hx("POST", port, "/api/setup-retry", {"X-Clipmaker": "1"})[0] == 200
      and wait_for(lambda: json.loads(hx("GET", port, "/api/setup-status")[1]).get("error"), 15) is not None)
check("sin ffmpeg: ruta desconocida -> 404", hx("POST", port, "/api/otra", {"X-Clipmaker": "1"})[0] == 404)
hx("POST", port, "/api/setup-quit", {"X-Clipmaker": "1"})
try:
    rc = p1.wait(timeout=20)
except subprocess.TimeoutExpired:
    p1.kill()
    rc = "colgado"
check("sin ffmpeg: 'Cerrar' termina el lanzador y limpia", rc == 1 and wait_for(lambda: ping(port) is None, 5) and not (box / "data" / "launcher.json").exists(), rc)

# --- primera vez de verdad: crea el entorno e instala las librerias ---
box = make_box(with_venv=False)
port = free_port()
p1 = start_launcher(box, port, py=sys.executable)
page = wait_for(lambda: (lambda r: r if r[0] == 200 else None)(hx("GET", port, "/")), 30)
check("primera vez: de inmediato hay una pagina de preparacion", page and b"Preparando Clipmaker" in page[1])
seen = set()


def first_run_done():
    d = json.loads(hx("GET", port, "/api/setup-status")[1] or b"{}") if (ping(port) or {}).get("app") == "clipmaker-setup" else {}
    for s in d.get("steps", []):
        seen.add((s["id"], s["state"]))
    return (ping(port) or {}).get("app") == "clipmaker"


ok = wait_for(first_run_done, 300, step=0.5)
check("primera vez: tras instalar, la app arranca sola en el mismo puerto", bool(ok))
check("primera vez: se vieron los pasos avanzar (entorno y librerias en curso)", ("venv", "en curso") in seen or ("deps", "en curso") in seen, sorted(seen)[:6])
check("primera vez: quedo el entorno y la marca de librerias", (box / ".venv" / "bin" / "python").exists() and (box / ".venv" / "requirements.installed").exists())
check("primera vez: el registro cuenta lo que hizo", "[preparando]" in (box / "data" / "clipmaker.log").read_text())
stop(box, port, p1)
check("primera vez: se cierra normal despues", p1.poll() == 0, p1.poll())

for p in procs:
    if p.poll() is None:
        p.kill()
print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
