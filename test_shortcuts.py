#!/usr/bin/env python3
"""Pruebas de los accesos directos: app de Mac, lanzador de Linux, iconos y revision de los archivos de Windows."""
import json
import os
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
FILES = ["app.py", "clipmaker.py", "captions.py", "updater.py", "publish_youtube.py", "make_template.py", "launcher.py",
         "requirements.txt", "VERSION", "layout.json", "hashtags.json", "crear_acceso_directo.sh", "run.sh"]
DIRS = ["static", "templates", "fonts"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
fails = []
launchers = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def make_box(name="Mi Carpeta & prueba|x", with_venv=True):
    root = Path(tempfile.mkdtemp())
    box = root / name
    box.mkdir()
    for f in FILES:
        shutil.copy(HERE / f, box / f)
    for d in DIRS:
        shutil.copytree(HERE / d, box / d)
    if with_venv:
        os.symlink(HERE / ".venv", box / ".venv")
        shutil.copy(HERE / "requirements.txt", HERE / ".venv" / "requirements.installed")
    return box


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def api(port, method="GET", path="/api/ping", headers=None):
    try:
        with OPENER.open(urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {}, data=b"" if method == "POST" else None), timeout=2) as r:
            return r.status, json.loads(r.read() or b"{}")
    except Exception:
        return None, None


def wait_for(fn, timeout=40, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def shutdown(port):
    api(port, "POST", "/api/shutdown", {"X-Clipmaker": "1"})
    return wait_for(lambda: api(port)[0] is None, 20)


def env_for(port, home, extra=None):
    env = dict(os.environ, HOME=str(home), CLIPMAKER_NO_BROWSER="1", CLIPMAKER_PORT_BASE=str(port))
    env.update(extra or {})
    return env


# ---------------- Mac: Clipmaker.app ----------------
darwin = Path(tempfile.mkdtemp())
(darwin / "uname").write_text("#!/bin/sh\necho Darwin\n")
(darwin / "uname").chmod(0o755)
box = make_box()
home = Path(tempfile.mkdtemp())
r = subprocess.run(["bash", str(box / "crear_acceso_directo.sh")], cwd=box, capture_output=True, text=True,
                   env=dict(os.environ, HOME=str(home), PATH=f"{darwin}:{os.environ['PATH']}"), timeout=30)
app = home / "Desktop" / "Clipmaker.app"
exe = app / "Contents" / "MacOS" / "Clipmaker"
check("Mac: crea Clipmaker.app en el escritorio", r.returncode == 0 and app.is_dir(), r.stderr.strip()[:80])
check("Mac: estructura de la app (Info.plist, ejecutable, icono)", (app / "Contents" / "Info.plist").is_file() and exe.is_file() and (app / "Contents" / "Resources" / "Clipmaker.icns").is_file())
plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
check("Mac: Info.plist valido con ejecutable, icono, tipo APPL y sin icono de Dock",
      plist["CFBundleExecutable"] == "Clipmaker" and plist["CFBundleIconFile"] == "Clipmaker" and plist["CFBundlePackageType"] == "APPL" and plist["LSUIElement"] is True, plist.get("CFBundleIdentifier"))
check("Mac: el ejecutable tiene permiso de ejecucion", bool(exe.stat().st_mode & stat.S_IXUSR))
src = exe.read_text()
check("Mac: no quedan marcas sin sustituir y la ruta (con espacios y simbolos) es exacta",
      "@DIR@" not in src and f'DIR="{box}"' in src and not (app / "Contents" / "MacOS" / "Clipmaker.template").exists(), [l for l in src.splitlines() if l.startswith("DIR=")])
check("Mac: el script no tiene errores de sintaxis", subprocess.run(["bash", "-n", str(exe)], capture_output=True).returncode == 0)
check("Mac: añade Homebrew al PATH y abre sin Terminal (nohup en segundo plano)", "/opt/homebrew/bin" in src and "nohup" in src and "launcher.py" in src)
r2 = subprocess.run(["bash", str(box / "crear_acceso_directo.sh")], cwd=box, capture_output=True, text=True,
                    env=dict(os.environ, HOME=str(home), PATH=f"{darwin}:{os.environ['PATH']}"), timeout=30)
check("Mac: repetir el instalador no falla y deja lo mismo", r2.returncode == 0 and exe.read_text() == src)
port = free_port()
t0 = time.time()
run = subprocess.run([str(exe)], capture_output=True, text=True, env=env_for(port, home), timeout=30)
check("Mac: al abrir la app el ejecutable termina enseguida (queda en segundo plano)", run.returncode == 0 and time.time() - t0 < 6, f"{time.time() - t0:.1f}s")
info = wait_for(lambda: (lambda s: s[1] if s[0] == 200 else None)(api(port)), 60)
check("Mac: la app de Clipmaker queda funcionando tras abrir el .app", info and info["app"] == "clipmaker", info)
state = json.loads((box / "data" / "launcher.json").read_text()) if (box / "data" / "launcher.json").exists() else {}
if state.get("pid"):
    launchers.append(state["pid"])
check("Mac: sobrevive despues de que el ejecutable terminó (no depende de el)", state.get("pid") and subprocess.run(["kill", "-0", str(state["pid"])]).returncode == 0)
again = subprocess.run([str(exe)], capture_output=True, text=True, env=env_for(port, home), timeout=30)
time.sleep(1.5)
check("Mac: abrir el .app otra vez no crea una segunda copia", again.returncode == 0 and json.loads((box / "data" / "launcher.json").read_text())["pid"] == state["pid"] and api(port + 1)[0] is None)
check("Mac: se cierra con el boton (cierre limpio)", shutdown(port))

nopy = Path(tempfile.mkdtemp())
for n in ("python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3"):
    (nopy / n).write_text("#!/bin/sh\nexit 1\n")
    (nopy / n).chmod(0o755)
box2 = make_box("sin venv", with_venv=False)
home2 = Path(tempfile.mkdtemp())
subprocess.run(["bash", str(box2 / "crear_acceso_directo.sh")], cwd=box2, capture_output=True, text=True,
               env=dict(os.environ, HOME=str(home2), PATH=f"{darwin}:{os.environ['PATH']}"), timeout=30)
exe2 = home2 / "Desktop" / "Clipmaker.app" / "Contents" / "MacOS" / "Clipmaker"
# Se quita la linea que antepone las rutas de Homebrew: aqui /usr/local/bin si trae un Python de verdad
no_brew = exe2.with_name("sin_brew")
no_brew.write_text("\n".join(l for l in exe2.read_text().splitlines() if not l.startswith("export PATH=")) + "\n")
no_brew.chmod(0o755)
rr = subprocess.run([str(no_brew)], capture_output=True, text=True, env=env_for(free_port(), home2, {"PATH": f"{nopy}:{os.environ['PATH']}"}), timeout=30)
check("Mac: sin Python 3.9+ sale con error y no deja nada a medias", rr.returncode == 1 and not (box2 / "data" / "launcher.json").exists(), rr.returncode)

# ---------------- Linux: Clipmaker.desktop ----------------
box = make_box()
home = Path(tempfile.mkdtemp())
r = subprocess.run(["bash", str(box / "crear_acceso_directo.sh")], cwd=box, capture_output=True, text=True,
                   env=dict(os.environ, HOME=str(home)), timeout=30)
desk = home / "Desktop" / "Clipmaker.desktop"
check("Linux: crea Clipmaker.desktop ejecutable", r.returncode == 0 and desk.is_file() and bool(desk.stat().st_mode & stat.S_IXUSR), r.stderr.strip()[:80])
text = desk.read_text()
fields = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
check("Linux: sin terminal, con nombre e icono existente", fields["Terminal"] == "false" and fields["Name"] == "Clipmaker" and Path(fields["Icon"]).is_file(), fields.get("Icon"))
check("Linux: sin marcas sin sustituir y con la ruta exacta", "@DIR@" not in text and str(box) in fields["Exec"])
port = free_port()
proc = subprocess.Popen(fields["Exec"], shell=True, env=env_for(port, home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
info = wait_for(lambda: (lambda s: s[1] if s[0] == 200 else None)(api(port)), 60)
check("Linux: el comando del acceso directo arranca la app (aunque la ruta tenga espacios y simbolos)", info and info["app"] == "clipmaker", info)
check("Linux: se cierra con el boton y el lanzador termina con 0", shutdown(port) and proc.wait(timeout=20) == 0)

# ---------------- iconos ----------------
ico, icns = Image.open(HERE / "static" / "clipmaker.ico"), Image.open(HERE / "static" / "clipmaker.icns")
check("iconos: .ico para Windows con varios tamaños", ico.format == "ICO" and (256, 256) in ico.info["sizes"] and (16, 16) in ico.info["sizes"])
check("iconos: .icns para Mac con tamaños normales y retina", icns.format == "ICNS" and (512, 512, 2) in icns.info["sizes"]
      and ((16, 16, 1) in icns.info["sizes"] or (16, 16, 2) in icns.info["sizes"]), sorted(icns.info["sizes"])[:3])

# ---------------- Windows (solo se puede revisar el texto: aqui no hay Windows) ----------------
vbs = (HERE / "Clipmaker.vbs").read_text(encoding="utf-8")
code = [l for l in vbs.splitlines() if l.strip() and not l.strip().startswith("'")]
check("Windows .vbs: comillas balanceadas en cada linea", all(l.count('"') % 2 == 0 for l in code if not l.rstrip().endswith("_")), [l for l in code if l.count('"') % 2][:2])
opens = sum(1 for l in code if re.match(r"\s*If .* Then\s*$", l))
check("Windows .vbs: If/End If y Function/End Function balanceados",
      opens == sum(1 for l in code if re.match(r"\s*End If", l)) and sum(1 for l in code if l.strip().startswith("Function ")) == sum(1 for l in code if l.strip() == "End Function"), (opens,))
check("Windows .vbs: abre sin ventana (estilo 0) y usa pythonw/pyw", 'launcher, 0, False' in vbs and "pythonw.exe" in vbs and "pyw -3" in vbs and "launcher.py" in vbs)
check("Windows .vbs: avisa con un mensaje si no hay Python", "MsgBox" in vbs and "winget install Python.Python.3.12" in vbs)
bat = (HERE / "crear_acceso_directo.bat").read_text(encoding="utf-8")
check("Windows .bat: el acceso directo apunta a wscript.exe + Clipmaker.vbs (sin consola)", "wscript.exe" in bat and "Clipmaker.vbs" in bat and "clipmaker.ico" in bat and "run.bat" not in bat.replace("crear_acceso_directo", ""))
check("Windows .bat: parentesis balanceados en el bloque de PowerShell", bat.count("(") == bat.count(")"), (bat.count("("), bat.count(")")))

# limpieza de procesos que pudieran quedar
for pid in launchers:
    try:
        os.kill(pid, 9)
    except OSError:
        pass
print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
