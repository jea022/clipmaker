#!/usr/bin/env python3
"""Pruebas de portabilidad Mac/Linux: puerto por sistema, version de Python, reinicio tras actualizar, puerto ocupado."""
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_sandbox():
    box = Path(tempfile.mkdtemp())
    shutil.copy(HERE / "run.sh", box / "run.sh")
    shutil.copy(HERE / "requirements.txt", box / "requirements.txt")
    (box / "templates").mkdir()
    (box / "templates" / "wganga.json").write_text("{}")
    script(box / ".venv" / "bin" / "pip", "exit 0\n")
    script(box / ".venv" / "bin" / "python",
           'echo "$*" >> "$LOG"\n'
           'n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$COUNT"\n'
           'if [ -n "$FIRST_EXIT" ] && [ "$n" -eq 1 ]; then exit "$FIRST_EXIT"; fi\n'
           'exit "${LAST_EXIT:-0}"\n')
    return box


def run_sh(box, args=(), shim=None, extra_env=None):
    env = dict(os.environ, LOG=str(box / "log.txt"), COUNT=str(box / "count.txt"))
    for k in ("FIRST_EXIT", "LAST_EXIT"):
        env.pop(k, None)
    env.update(extra_env or {})
    if shim:
        env["PATH"] = f"{shim}:{env['PATH']}"
    r = subprocess.run(["bash", str(box / "run.sh"), *args], cwd=box, env=env, capture_output=True, text=True, timeout=60)
    log = (box / "log.txt").read_text().splitlines() if (box / "log.txt").exists() else []
    return r, log


# --- puerto segun el sistema ---
darwin = Path(tempfile.mkdtemp())
script(darwin / "uname", 'echo Darwin\n')

box = make_sandbox()
r, log = run_sh(box)
check("Linux: puerto por defecto 5000", r.returncode == 0 and log == ["app.py 5000"], log)
box = make_sandbox()
r, log = run_sh(box, shim=darwin)
check("Mac (Darwin): puerto por defecto 5055 (el 5000 lo usa AirPlay)", r.returncode == 0 and log == ["app.py 5055"], log)
box = make_sandbox()
r, log = run_sh(box, ["6123"], shim=darwin)
check("Mac: un puerto indicado manda sobre el de por defecto", log == ["app.py 6123"], log)
box = make_sandbox()
r, log = run_sh(box, ["6124"])
check("Linux: un puerto indicado se respeta", log == ["app.py 6124"], log)

# --- reinicio tras actualizar (codigo 42) ---
box = make_sandbox()
r, log = run_sh(box, extra_env={"FIRST_EXIT": "42"})
check("codigo 42 reinicia la app una vez", len(log) == 2 and r.returncode == 0, log)
box = make_sandbox()
r, log = run_sh(box, extra_env={"FIRST_EXIT": "1", "LAST_EXIT": "1"})
check("un fallo normal (codigo 1) no entra en bucle", len(log) == 1, log)

# --- dependencias solo si cambian los requisitos ---
box = make_sandbox()
pip_log = box / "pip.txt"
script(box / ".venv" / "bin" / "pip", f'echo "$*" >> "{pip_log}"\nexit 0\n')
run_sh(box)
first = pip_log.read_text().splitlines() if pip_log.exists() else []
run_sh(box)
second = pip_log.read_text().splitlines() if pip_log.exists() else []
check("instala dependencias la primera vez", len(first) == 1, first)
check("no las reinstala si no cambiaron", len(second) == 1, second)
(box / "requirements.txt").write_text((box / "requirements.txt").read_text() + "\nrequests\n")
run_sh(box)
third = pip_log.read_text().splitlines()
check("las reinstala si cambian los requisitos", len(third) == 2, third)

# --- version de Python ---
old = Path(tempfile.mkdtemp())
for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3"):
    script(old / name, "exit 1\n")
box = make_sandbox()
shutil.rmtree(box / ".venv")
r, log = run_sh(box, shim=old)
check("sin Python 3.9+ avisa y para", r.returncode == 1 and "Python 3.9" in r.stdout and "brew install python@3.12" in r.stdout, r.stdout.strip()[:90])
check("sin Python valido no intenta arrancar la app", log == [])

# --- puerto ocupado: mensaje claro ---
busy = socket.socket()
busy.bind(("127.0.0.1", 0))
busy.listen(1)
port = busy.getsockname()[1]
py = HERE / ".venv" / "bin" / "python"
r = subprocess.run([str(py if py.exists() else sys.executable), str(HERE / "app.py"), str(port)], cwd=HERE,
                   capture_output=True, text=True, timeout=60)
busy.close()
text = r.stdout + r.stderr
check("puerto ocupado: sale con error (no 0 ni 42)", r.returncode not in (0, 42), r.returncode)
check("puerto ocupado: explica el problema y sugiere otro puerto", "No pude abrir el puerto" in text and "AirPlay" in text and "5055" in text, text.strip()[-120:])
check("puerto ocupado: sin traceback", "Traceback" not in text)

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
