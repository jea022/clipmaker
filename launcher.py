#!/usr/bin/env python3
"""Lanzador de Clipmaker: arranca la app en segundo plano (sin ventana de consola), prepara el entorno la
primera vez mostrando el progreso en el navegador, evita abrir dos copias y la reinicia tras actualizar.
Solo usa la libreria estandar, asi funciona igual en Windows, Mac y Linux."""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
LOG = DATA / "clipmaker.log"
STATE = DATA / "launcher.json"
LOCK = DATA / "launcher.lock"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
NO_WINDOW = 0x08000000 if IS_WIN else 0
RESTART_CODE = 42
MIN_PY = (3, 9)
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
PORT_BASE = int(os.environ.get("CLIPMAKER_PORT_BASE") or (5055 if IS_MAC else 5000))
MAX_FFMPEG_BYTES = 400 * 1024 * 1024
FFMPEG_ENTRY = re.compile(r"/bin/(ffmpeg|ffprobe)\.exe$")
LOCAL_HOSTS = ("127.0.0.1", "localhost")


class SetupError(Exception):
    pass


# ---------- utilidades ----------
def log(msg):
    try:
        DATA.mkdir(exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.replace(LOG.with_suffix(".log.1"))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def extend_path():
    """Las apps lanzadas desde Finder/Explorador no heredan el PATH de la terminal (p. ej. Homebrew)."""
    extra = [str(HERE / "bin")]
    if IS_MAC:
        extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WIN:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reuse_option():
    """En Windows SO_REUSEADDR deja abrir un puerto que YA esta en uso (da un falso 'libre'); alli se usa la
    opcion exclusiva. En Mac/Linux SO_REUSEADDR si falla correctamente con un puerto ocupado."""
    if IS_WIN and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        return socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE
    return socket.SOL_SOCKET, socket.SO_REUSEADDR


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(*reuse_option(), 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(preferred):
    for port in range(preferred, preferred + 25):
        if port_free(port):
            return port
    raise SetupError(f"No encuentro un puerto libre entre el {preferred} y el {preferred + 24}.")


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ping(port, timeout=1.5):
    try:
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            data = json.loads(r.read(2000).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def notify(title, text):
    log(f"AVISO: {title}: {text}")
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", f"display dialog {json.dumps(text, ensure_ascii=False)} with title "
                            f"{json.dumps(title, ensure_ascii=False)} buttons {{\"OK\"}} with icon stop"], timeout=300)
        else:
            print(f"{title}: {text}", file=sys.stderr)
    except Exception:
        pass


def find_browser():
    """Un navegador basado en Chromium (Edge, Chrome, Brave...) para abrir Clipmaker como ventana de aplicación."""
    forced = os.environ.get("CLIPMAKER_BROWSER")
    if forced:
        return forced if (Path(forced).is_file() or shutil.which(forced)) else None
    cands = []
    if IS_WIN:
        roots = [Path(r) for r in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                                   os.environ.get("LocalAppData")) if r]
        for sub in (("Microsoft", "Edge", "Application", "msedge.exe"), ("Google", "Chrome", "Application", "chrome.exe"),
                    ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")):
            cands += [root.joinpath(*sub) for root in roots]
    elif IS_MAC:
        for name in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            for base in (Path("/Applications"), Path.home() / "Applications"):
                cands.append(base / f"{name}.app" / "Contents" / "MacOS" / name)
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                     "microsoft-edge-stable", "brave-browser"):
            found = shutil.which(name)
            if found:
                cands.append(Path(found))
    for c in cands:
        if c.is_file():
            return str(c)
    return None


class Window:
    """Abre Clipmaker como ventana de aplicación (sin pestañas ni barra de direcciones). Con un perfil propio, el
    navegador es un proceso aparte: cuando cierras la ventana ese proceso termina y se puede cerrar Clipmaker."""

    def __init__(self, tab=False, enabled=True):
        self.tab, self.enabled = tab, enabled
        self.proc, self.opened_at, self.on_close = None, 0.0, None

    def open(self, port):
        if not self.enabled or os.environ.get("CLIPMAKER_NO_BROWSER"):
            return
        url = f"http://127.0.0.1:{port}"
        browser = None if (self.tab or os.environ.get("CLIPMAKER_TAB")) else find_browser()
        if not browser:
            webbrowser.open(url)
            return
        profile = DATA / "window-profile"
        profile.mkdir(parents=True, exist_ok=True)
        cmd = [browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
               "--window-size=1320,920"]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"no pude abrir la ventana con {browser} ({e}); abro el navegador normal")
            webbrowser.open(url)
            return
        self.opened_at = time.time()
        log(f"ventana abierta con {browser}")
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        proc = self.proc
        proc.wait()
        # Si termina casi al instante, el navegador le pasó la ventana a una copia ya abierta: no es un cierre.
        if time.time() - self.opened_at >= 3 and self.on_close:
            log("se cerró la ventana de Clipmaker")
            self.on_close()


def open_browser(port, enabled=True, tab=False):
    """Abre otra ventana de Clipmaker sin vigilarla (cuando ya hay una copia en marcha)."""
    Window(tab, enabled).open(port)


def shutdown_app(port):
    try:
        _NO_PROXY.open(urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", method="POST", data=b"",
                                              headers={"X-Clipmaker": "1"}), timeout=3).read()
    except Exception:
        pass


# ---------- una sola copia a la vez ----------
def read_state():
    try:
        data = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(port, mode):
    DATA.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"pid": os.getpid(), "port": port, "mode": mode, "started": time.time()}))


def probe_legacy(port, timeout=0.6):
    """Una copia ANTERIOR de Clipmaker (sin /api/ping): se reconoce por su lista de variaciones."""
    try:
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/presets", timeout=timeout) as r:
            data = json.loads(r.read(20000).decode("utf-8"))
    except Exception:
        return False
    return isinstance(data, list) and any(isinstance(x, dict) and x.get("id") == "cam_game" for x in data)


def existing_instance():
    """Una copia ya abierta: la que anota el lanzador o, si se abrió con la consola (run.bat/run.sh) o es de una
    version anterior, la que responda en los puertos habituales."""
    st = read_state()
    if st and isinstance(st.get("port"), int):
        info = ping(st["port"])
        if info and info.get("app") in ("clipmaker", "clipmaker-setup"):
            return st
    for port in range(PORT_BASE, PORT_BASE + 25):
        info = ping(port, timeout=0.4)
        if info and info.get("app") == "clipmaker":
            return {"port": port, "mode": "app"}
        if probe_legacy(port):
            return {"port": port, "mode": "legacy"}
    return None


def acquire_lock():
    DATA.mkdir(exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(LOCK.read_text().strip())
            except (OSError, ValueError):
                pid = 0
            if pid_alive(pid) and pid != os.getpid():
                return False
            try:
                LOCK.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def release_lock():
    try:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass
    try:
        st = read_state()
        if st and st.get("pid") == os.getpid():
            STATE.unlink()
    except OSError:
        pass


# ---------- entorno ----------
def venv_python(gui=False):
    base = HERE / ".venv"
    if IS_WIN:
        w = base / "Scripts" / "pythonw.exe"
        return w if gui and w.exists() else base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def requirements_ok():
    marker, req = HERE / ".venv" / "requirements.installed", HERE / "requirements.txt"
    try:
        return marker.read_bytes() == req.read_bytes()
    except OSError:
        return False


def have_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def env_ready():
    return venv_python().exists() and requirements_ok() and have_ffmpeg() and (HERE / "templates" / "wganga.json").exists()


def run_cmd(cmd, note, cwd=HERE):
    """Ejecuta un comando mostrando su salida linea a linea; devuelve las ultimas lineas si falla."""
    kwargs = {"creationflags": NO_WINDOW} if IS_WIN else {}
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, errors="replace", **kwargs)
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            note(line[:200])
    proc.wait()
    return proc.returncode, tail[-6:]


def download_ffmpeg(url, bin_dir, note=print):
    """Descarga el zip de ffmpeg para Windows y extrae solo ffmpeg.exe y ffprobe.exe en bin_dir."""
    u = urlparse(url)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in LOCAL_HOSTS)):
        raise SetupError("La descarga de ffmpeg debe ser por https.")
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    opener = _NO_PROXY if u.hostname in LOCAL_HOSTS else urllib.request.build_opener()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "clipmaker-launcher"}), timeout=30) as r:
                total = int(r.headers.get("Content-Length") or 0)
                done, next_mark = 0, 10
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > MAX_FFMPEG_BYTES:
                        raise SetupError("La descarga de ffmpeg es demasiado grande.")
                    tmp.write(chunk)
                    if total and done * 100 // total >= next_mark:
                        note(f"Descargando ffmpeg… {done * 100 // total}%")
                        next_mark += 10
        except SetupError:
            raise
        except Exception as e:
            raise SetupError(f"No pude descargar ffmpeg ({type(e).__name__}). Revisa tu conexión y pulsa Reintentar.")
    try:
        found = set()
        with zipfile.ZipFile(tmp_path) as z:
            for info in z.infolist():
                m = FFMPEG_ENTRY.search(info.filename)
                if m and not info.is_dir():
                    name = m.group(1) + ".exe"
                    with z.open(info) as src, open(bin_dir / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.add(name)
        if found != {"ffmpeg.exe", "ffprobe.exe"}:
            raise SetupError("El archivo descargado no trae ffmpeg.exe y ffprobe.exe.")
    except zipfile.BadZipFile:
        raise SetupError("El archivo de ffmpeg descargado está dañado. Pulsa Reintentar.")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    note("ffmpeg listo.")


class Setup:
    """Prepara el entorno la primera vez y deja el progreso para mostrarlo en el navegador."""
    STEPS = [("venv", "Crear el entorno de Python"), ("deps", "Instalar las librerías"),
             ("tpl", "Preparar las plantillas"), ("ffmpeg", "Preparar ffmpeg (para montar los videos)")]

    def __init__(self):
        self.state = {k: "pendiente" for k, _ in self.STEPS}
        self.lines, self.error, self.done = [], None, False
        self.retry = threading.Event()
        self.quit = False

    def note(self, text):
        self.lines = (self.lines + [text])[-80:]
        log(f"[preparando] {text}")

    def view(self):
        return {"steps": [{"id": k, "label": label, "state": self.state[k]} for k, label in self.STEPS],
                "lines": self.lines[-14:], "error": self.error, "done": self.done}

    def run(self):
        self.error, self.done = None, False
        self.state = {k: "pendiente" for k, _ in self.STEPS}
        steps = {"venv": self.step_venv, "deps": self.step_deps, "tpl": self.step_tpl, "ffmpeg": self.step_ffmpeg}
        try:
            for key, _ in self.STEPS:
                if self.quit:
                    raise SetupError("Preparación cancelada.")
                self.state[key] = "en curso"
                steps[key]()
                self.state[key] = "listo"
            self.done = True
        except SetupError as e:
            self.error = str(e)
            for k, v in self.state.items():
                if v == "en curso":
                    self.state[k] = "falló"
            log(f"[preparando] ERROR: {e}")

    def step_venv(self):
        if venv_python().exists():
            return
        if sys.version_info < MIN_PY:
            raise SetupError(f"Necesitas Python {MIN_PY[0]}.{MIN_PY[1]} o superior (tienes {sys.version_info[0]}."
                             f"{sys.version_info[1]}). Windows: winget install Python.Python.3.12 · Mac: brew install python@3.12")
        self.note("Creando el entorno de Python…")
        code, tail = run_cmd([sys.executable, "-m", "venv", str(HERE / ".venv")], self.note)
        if code != 0 or not venv_python().exists():
            raise SetupError("No pude crear el entorno de Python. " + (" ".join(tail[-2:]) or "")
                             + (" En Ubuntu: sudo apt install python3-venv" if sys.platform.startswith("linux") else ""))

    def step_deps(self):
        if requirements_ok():
            return
        self.note("Instalando las librerías (puede tardar un par de minutos)…")
        code, tail = run_cmd([str(venv_python()), "-m", "pip", "install", "-q", "-r", "requirements.txt"], self.note)
        if code != 0:
            raise SetupError("No pude instalar las librerías: " + " ".join(tail[-3:]) + " Revisa tu conexión y pulsa Reintentar.")
        shutil.copyfile(HERE / "requirements.txt", HERE / ".venv" / "requirements.installed")

    def step_tpl(self):
        if (HERE / "templates" / "wganga.json").exists():
            return
        self.note("Preparando las plantillas…")
        code, tail = run_cmd([str(venv_python()), "make_template.py"], self.note)
        if code != 0:
            raise SetupError("No pude preparar las plantillas: " + " ".join(tail[-2:]))

    def step_ffmpeg(self):
        if have_ffmpeg():
            return
        if IS_WIN:
            self.note("Descargando ffmpeg (unos 200 MB, solo esta vez)…")
            download_ffmpeg(os.environ.get("CLIPMAKER_FFMPEG_URL") or FFMPEG_URL, HERE / "bin", self.note)
            extend_path()
            if not have_ffmpeg():
                raise SetupError("No encuentro ffmpeg después de descargarlo.")
        elif IS_MAC:
            raise SetupError("Falta ffmpeg. Abre la app Terminal y ejecuta: brew install ffmpeg "
                             "(si no tienes Homebrew, mira https://brew.sh). Luego pulsa Reintentar.")
        else:
            raise SetupError("Falta ffmpeg. En Ubuntu/Debian: sudo apt install ffmpeg. Luego pulsa Reintentar.")


SETUP_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Preparando Clipmaker</title><style>
body{margin:0;background:#0e0e16;color:#f2f2f7;font:16px/1.5 system-ui,sans-serif}main{max-width:620px;margin:8vh auto;padding:0 20px}
h1{font-size:22px;margin:0 0 4px}p{color:#9a9ab0;margin:0 0 18px}li{list-style:none;margin:6px 0;padding:8px 12px;border:1px solid #2a2a3d;border-radius:8px;background:#171724}
ul{padding:0;margin:0 0 16px}.s{float:right;font-size:13px;color:#9a9ab0}.listo .s{color:#3ddc84}.falló .s{color:#ff5c5c}.en.curso .s{color:#ff7a00}
pre{background:#171724;border:1px solid #2a2a3d;border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap;color:#9a9ab0;min-height:2em}
.err{background:#2a1417;border:1px solid #ff5c5c;border-radius:8px;padding:12px;margin:12px 0;display:none}
button{background:#ff7a00;color:#111;border:0;padding:10px 16px;border-radius:8px;font:inherit;font-weight:700;cursor:pointer;margin-right:8px}
button.g{background:transparent;color:#f2f2f7;border:1px solid #2a2a3d;font-weight:600}</style></head><body><main>
<h1>Preparando Clipmaker</h1><p>Solo pasa la primera vez. Cuando termine, esta página se abre sola.</p>
<ul id="steps"></ul><pre id="log"></pre><div class="err" id="err"></div>
<div id="btns" style="display:none"><button id="retry">Reintentar</button><button class="g" id="quit">Cerrar</button></div></main>
<script>
const $=id=>document.getElementById(id);
async function tick(){
  try{
    const a=await fetch('/api/ping',{cache:'no-store'}).then(r=>r.json());
    if(a.app==='clipmaker'){location.reload();return;}
    const s=await fetch('/api/setup-status',{cache:'no-store'}).then(r=>r.json());
    $('steps').innerHTML=s.steps.map(x=>`<li class="${x.state}">${x.label}<span class="s">${x.state}</span></li>`).join('');
    $('log').textContent=s.lines.join('\\n');
    $('err').style.display=s.error?'block':'none';$('err').textContent=s.error||'';
    $('btns').style.display=s.error?'block':'none';
  }catch(e){}
  setTimeout(tick,1000);
}
$('retry').onclick=()=>fetch('/api/setup-retry',{method:'POST',headers:{'X-Clipmaker':'1'}});
$('quit').onclick=()=>{fetch('/api/setup-quit',{method:'POST',headers:{'X-Clipmaker':'1'}});document.body.innerHTML='<main><h1>Clipmaker se cerró</h1><p>Puedes cerrar esta pestaña.</p></main>';};
tick();
</script></body></html>"""


def start_setup_server(port, setup):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/ping":
                self._send(200, json.dumps({"app": "clipmaker-setup"}))
            elif self.path == "/api/setup-status":
                self._send(200, json.dumps(setup.view(), ensure_ascii=False))
            else:
                self._send(200, SETUP_PAGE, "text/html")

        def do_POST(self):
            if self.headers.get("X-Clipmaker") != "1":
                self._send(403, json.dumps({"error": "no permitido"}))
            elif self.path == "/api/setup-retry":
                setup.retry.set()
                self._send(200, json.dumps({"ok": True}))
            elif self.path == "/api/setup-quit":
                setup.quit = True
                setup.retry.set()
                self._send(200, json.dumps({"ok": True}))
            else:
                self._send(404, json.dumps({"error": "no existe"}))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------- la app ----------
def spawn_app(port):
    DATA.mkdir(exist_ok=True)
    logf = open(LOG, "ab")
    kwargs = {"creationflags": NO_WINDOW} if IS_WIN else {}
    return subprocess.Popen([str(venv_python(gui=True)), str(HERE / "app.py"), str(port)], cwd=HERE, stdout=logf,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)


def wait_ready(port, timeout=60, proc=None):
    end = time.time() + timeout
    while time.time() < end:
        info = ping(port)
        if info and info.get("app") == "clipmaker":
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.4)
    return False


def watch_ready(port, proc, on_ready, timeout=60):
    """Espera a que la app responda; si no lo hace, avisa en vez de esperar en silencio."""
    if wait_ready(port, timeout, proc):
        on_ready()
    elif proc.poll() is None:
        log(f"la app no respondió en el puerto {port} tras {timeout}s (respuesta de /api/ping: {ping(port)})")
        notify("Clipmaker", f"La app no respondió en el puerto {port}. Puede que otra copia de Clipmaker u otro "
                            f"programa lo esté usando. Cierra las ventanas negras de Clipmaker y vuelve a abrirlo. "
                            f"Más detalles en {LOG}")


def supervise(spawn, port, on_ready=None, prepare=None, max_fast_crashes=3, pause=1.0):
    """Mantiene la app viva: la reinicia tras una actualizacion (codigo 42) o una caida; termina al cerrarla."""
    fast = 0
    while True:
        started = time.time()
        proc = spawn()
        log(f"app arrancada (pid {proc.pid}) en el puerto {port}")
        if on_ready:
            threading.Thread(target=watch_ready, args=(port, proc, on_ready), daemon=True).start()
            on_ready = None
        code = proc.wait()
        log(f"la app terminó con código {code}")
        if code == RESTART_CODE:
            fast = 0
            if prepare:
                prepare()
            continue
        if code == 0:
            return 0
        fast = fast + 1 if time.time() - started < 10 else 0
        if fast >= max_fast_crashes:
            notify("Clipmaker no pudo arrancar", f"La app se cerró varias veces seguidas (código {code}). "
                   f"Mira el registro en {LOG}")
            return code
        time.sleep(pause)


def quiet_prepare():
    """Tras actualizar: instala librerias nuevas si cambiaron, sin mostrar nada."""
    setup = Setup()
    setup.run()
    if setup.error:
        notify("Clipmaker", f"No pude preparar la actualización: {setup.error}")


def run(port, no_browser=False, tab=False):
    opened = False
    current = {"setup": None}
    win = Window(tab, not no_browser)

    def close_request():
        s = current["setup"]
        if s is not None:
            s.quit = True
            s.retry.set()
        shutdown_app(port)

    win.on_close = close_request
    if not env_ready():
        setup = Setup()
        current["setup"] = setup
        server = start_setup_server(port, setup)
        write_state(port, "setup")
        win.open(port)
        opened = True
        while True:
            setup.run()
            if setup.quit:
                server.shutdown()
                server.server_close()
                return 1
            if not setup.error:
                break
            setup.retry.clear()
            setup.retry.wait()
            if setup.quit:
                server.shutdown()
                server.server_close()
                return 1
        server.shutdown()
        server.server_close()
    write_state(port, "app")

    def ready():
        nonlocal opened
        if not opened:
            opened = True
            win.open(port)

    return supervise(lambda: spawn_app(port), port, on_ready=ready, prepare=quiet_prepare)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, help="puerto (por defecto 5000, o 5055 en Mac)")
    ap.add_argument("--no-browser", action="store_true", help="no abrir ninguna ventana")
    ap.add_argument("--tab", action="store_true", help="abrir en una pestaña del navegador en vez de una ventana propia")
    ap.add_argument("--status", action="store_true", help="muestra el estado y sale")
    a = ap.parse_args(argv)
    os.chdir(HERE)
    extend_path()
    if a.status:
        inst = existing_instance()
        print(json.dumps({"ready": env_ready(), "running": inst, "version": (HERE / "VERSION").read_text().strip()}))
        return 0
    inst = existing_instance()
    if inst:
        print(f"Clipmaker ya está abierto en http://127.0.0.1:{inst['port']}")
        if inst.get("mode") == "legacy":
            notify("Clipmaker", f"Ya hay una copia anterior de Clipmaker abierta (puerto {inst['port']}, la ventana negra "
                                f"de run.bat). Se abre esa. Para pasar al lanzador nuevo: pulsa «Actualizar ahora» en esa "
                                f"página, luego «Cerrar Clipmaker», cierra la ventana negra y abre Clipmaker otra vez.")
        open_browser(inst["port"], not a.no_browser, a.tab)
        return 0
    if not acquire_lock():
        end = time.time() + 30
        while time.time() < end:
            inst = existing_instance()
            if inst:
                open_browser(inst["port"], not a.no_browser, a.tab)
                return 0
            time.sleep(0.5)
        print("Otro lanzador está arrancando Clipmaker.", file=sys.stderr)
        return 1
    try:
        try:
            port = a.port or pick_port(PORT_BASE)
        except SetupError as e:
            notify("Clipmaker", str(e))
            return 1
        log(f"lanzador iniciado (pid {os.getpid()}, puerto {port})")
        return run(port, a.no_browser, a.tab)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
