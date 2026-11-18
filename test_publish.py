#!/usr/bin/env python3
"""Pruebas del subidor de YouTube sin tocar la red: validacion, dry-run y subida simulada."""
import subprocess
import sys
from pathlib import Path
from unittest import mock

import publish_youtube as py

HERE = Path(__file__).parent
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


vertical = HERE / "out" / "branded.mp4"
horizontal = HERE / "out" / "sample.mp4"
long_vertical = HERE / "out" / "long_vertical.mp4"
if not long_vertical.exists():
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=540x960:r=5:d=200",
                    "-pix_fmt", "yuv420p", str(long_vertical)], check=True)

check("valida vertical", py.validate_video(vertical)["height"] == 1920)
for name, path, frag in (("rechaza horizontal", horizontal, "vertical"),
                         ("rechaza >3min", long_vertical, "180"),
                         ("rechaza inexistente", HERE / "nada.mp4", "No existe")):
    try:
        py.validate_video(path)
        check(name, False, "no lanzo error")
    except ValueError as e:
        check(name, frag in str(e), str(e)[:60])

body = py.build_body("wganga", "x" * 300, ["westcol"], "private")
check("titulo <=100", len(body["snippet"]["title"]) <= 100 and body["snippet"]["title"].endswith("#Shorts"))
check("tags <=15 sin #", len(body["snippet"]["tags"]) <= 15 and not any(t.startswith("#") for t in body["snippet"]["tags"]))
check("privado por defecto", body["status"]["privacyStatus"] == "private")
check("no es para ninos declarado", body["status"]["selfDeclaredMadeForKids"] is False)
try:
    py.build_body("nope", "t", [], "private")
    check("cuenta invalida", False)
except KeyError:
    check("cuenta invalida", True)

r = subprocess.run([sys.executable, str(HERE / "publish_youtube.py"), str(vertical), "Prueba",
                    "--account", "wganga", "--people", "westcol", "--dry-run"], capture_output=True, text=True)
check("dry-run no sube", r.returncode == 0 and "no se subió nada" in r.stdout, r.stderr[-100:])

r = subprocess.run([sys.executable, str(HERE / "publish_youtube.py"), str(vertical), "Prueba",
                    "--account", "wganga"], capture_output=True, text=True, env={"PATH": "/usr/bin:/usr/local/bin", "HOME": "/nonexistent"})
check("sin credenciales error claro", r.returncode != 0 and "client_secret.json" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-120:])

fake_req = mock.Mock()
fake_req.next_chunk.side_effect = [(mock.Mock(progress=lambda: 0.5), None), (None, {"id": "VID123"})]
fake_yt = mock.Mock()
fake_yt.videos.return_value.insert.return_value = fake_req
with mock.patch.object(py, "get_credentials", return_value=object()), \
     mock.patch("googleapiclient.discovery.build", return_value=fake_yt), \
     mock.patch("googleapiclient.http.MediaFileUpload"):
    vid = py.upload("wganga", vertical, body)
check("subida simulada devuelve id", vid == "VID123")
kw = fake_yt.videos.return_value.insert.call_args.kwargs
check("insert con snippet+status", kw["part"] == "snippet,status" and kw["body"] is body)

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
