#!/usr/bin/env python3
"""Pruebas de la API web con el cliente de pruebas de Flask."""
import io
import json
import sys
from pathlib import Path

import app as webapp

HERE = Path(__file__).parent
SAMPLE = HERE / "out" / "sample.mp4"
import tempfile as _tf
webapp.CAM_FILE = Path(_tf.mkdtemp()) / "data" / "cam_defaults.json"
c = webapp.app.test_client()
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


def upload(data, name="clip.mp4"):
    return c.post("/api/upload", data={"clip": (io.BytesIO(data), name)}, content_type="multipart/form-data")


good = SAMPLE.read_bytes()
r = upload(good)
check("upload valido", r.status_code == 200 and "id" in r.json, r.status_code)
jid = r.json["id"]

check("upload sin archivo", c.post("/api/upload", data={}, content_type="multipart/form-data").status_code == 400)
check("upload extension mala", upload(b"x", "virus.exe").status_code == 400)
check("upload sin extension", upload(b"x", "clip").status_code == 400)
check("upload corrupto", upload(b"esto no es un video", "a.mp4").status_code == 400)
check("upload vacio", upload(b"", "a.mp4").status_code == 400)

check("media id falso", c.get("/media/" + "0" * 32 + "/frame.png").status_code == 404)
check("media id con traversal", c.get("/media/..%2f..%2fetc/frame.png").status_code == 404)
check("media nombre no permitido", c.get(f"/media/{jid}/source.mp4").status_code == 404)
check("media frame ok", c.get(f"/media/{jid}/frame.png").status_code == 200)


def render(**kw):
    body = {"id": jid, "title": "Hola", "account": "wganga", "cam": [0.7, 0.02, 0.28, 0.32], "people": []}
    body.update(kw)
    return c.post("/api/render", json=body)


check("render sin titulo", render(title="   ").status_code == 400)
check("render titulo largo", render(title="a" * 201).status_code == 400)
check("render cuenta mala", render(account="otra").status_code == 400)
check("render id mala", render(id="zzz").status_code == 404)
check("render cam fuera de rango", render(cam=[0.9, 0.9, 0.5, 0.5]).status_code == 400)
check("render cam basura", render(cam="hola").status_code == 400)
check("render cam tamano cero", render(cam=[0.1, 0.1, 0, 0]).status_code == 400)
check("render json invalido", c.post("/api/render", data="no json", content_type="text/plain").status_code == 404)
check("render people basura", render(people=[1, None, "westcol", {"a": 1}]).status_code == 200)

r = render(title="Prueba con tildes ñ ¡¿ y emoji 😂", people=["westcol"])
check("render ok", r.status_code == 200 and r.json["captions"]["people_known"] == ["#westcol"], r.status_code)
out = c.get(r.json["video"])
check("descarga video", out.status_code == 200 and out.data[:4] != b"", out.status_code)
dl = c.get(r.json["download"])
check("descarga con attachment", "attachment" in dl.headers.get("Content-Disposition", ""))

r = render(no_cam=True, cam=None)
check("render sin camara", r.status_code == 200)

check("cam-default invalido", c.post("/api/cam-default", json={"account": "wganga", "cam": [2, 2, 2, 2]}).status_code == 400)
check("cam-default cuenta mala", c.post("/api/cam-default", json={"account": "x", "cam": [0.1, 0.1, 0.2, 0.2]}).status_code == 400)

from unittest import mock

def pub(**kw):
    body = {"id": jid, "title": "Hola", "account": "wganga", "people": ["westcol"], "privacy": "private"}
    body.update(kw)
    return c.post("/api/publish-youtube", json=body)

check("publish privacidad publica bloqueada", pub(privacy="public").status_code == 400)
check("publish sin titulo", pub(title="").status_code == 400)
check("publish cuenta mala", pub(account="x").status_code == 400)
fresh = upload(good).json["id"]
check("publish sin video creado", pub(id=fresh).status_code == 400)
with mock.patch.object(webapp.publish_youtube, "upload", return_value="VID9") as up:
    r = pub()
    check("publish ok (simulado)", r.status_code == 200 and r.json["url"].endswith("/VID9"), r.status_code)
    check("publish usa privado", up.call_args.args[2]["status"]["privacyStatus"] == "private")
with mock.patch.object(webapp.publish_youtube, "upload", side_effect=FileNotFoundError("Falta client_secret.json")):
    r = pub()
    check("publish sin credenciales -> 400 claro", r.status_code == 400 and "client_secret" in r.json["error"])
with mock.patch.object(webapp.publish_youtube, "upload", side_effect=RuntimeError("boom con datos internos")):
    r = pub()
    check("publish error interno no filtra detalles", r.status_code == 502 and "boom" not in r.json["error"])

# ---- variaciones: imagen / segundo video ----
from PIL import Image

def attach(job, kind, data, name="archivo.png"):
    return c.post("/api/attach", data={"id": job, "kind": kind, "file": (io.BytesIO(data), name)},
                  content_type="multipart/form-data")

def img_bytes(fmt="PNG", size=(800, 450), color=(20, 90, 200)):
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, fmt); return b.getvalue()

r = c.get("/api/presets")
ids = [p["id"] for p in r.json]
check("presets lista las 6", r.status_code == 200 and set(ids) == {"cam_game", "game_cam", "clip_image", "image_clip", "clip_clip", "clip_blur"}, ids)
check("presets indican needs/uses_cam", {p["id"]: (p["needs"], p["uses_cam"]) for p in r.json}["clip_image"] == (["image"], False))

job2 = upload(good).json["id"]
def render2(job, **kw):
    body = {"id": job, "title": "Hola", "account": "wganga", "people": []}
    body.update(kw)
    return c.post("/api/render", json=body)

check("render clip_image sin imagen -> 400", render2(job2, preset="clip_image").status_code == 400)
check("render clip_clip sin B -> 400", render2(job2, preset="clip_clip").status_code == 400)
check("render image_clip sin imagen -> 400", render2(job2, preset="image_clip").status_code == 400)
check("render audio b sin B -> 400", render2(job2, audio="b").status_code == 400)
check("render preset inexistente -> 400", render2(job2, preset="x").status_code == 400)
check("render audio invalido -> 400", render2(job2, audio="z").status_code == 400)

r = attach(job2, "image", img_bytes())
check("attach imagen ok", r.status_code == 200 and r.json["width"] == 800, r.status_code)
check("preview de imagen servida", c.get(r.json["preview"]).status_code == 200)
check("render clip_image con imagen", render2(job2, preset="clip_image").status_code == 200)
check("render image_clip con imagen", render2(job2, preset="image_clip").status_code == 200)
check("imagen jpg", attach(job2, "image", img_bytes("JPEG"), "foto.jpg").status_code == 200)
check("imagen webp", attach(job2, "image", img_bytes("WEBP"), "foto.webp").status_code == 200)
check("attach imagen ext mala", attach(job2, "image", b"x", "a.exe").status_code == 400)
check("attach imagen sin extension", attach(job2, "image", b"x", "a").status_code == 400)
check("attach imagen corrupta", attach(job2, "image", b"no soy imagen", "a.png").status_code == 400)
check("attach imagen vacia", attach(job2, "image", b"", "a.png").status_code == 400)
check("tras fallo la imagen buena sigue", render2(job2, preset="clip_image").status_code == 200)
check("attach imagen >40MB", attach(job2, "image", b"0" * (41 * 1024 * 1024), "big.png").status_code == 400)
check("attach kind invalido", attach(job2, "otro", b"x", "a.png").status_code == 400)
check("attach id falso", attach("0" * 32, "image", img_bytes(), "a.png").status_code == 404)
check("attach id basura", attach("../x", "image", img_bytes(), "a.png").status_code == 404)
check("attach sin archivo", c.post("/api/attach", data={"id": job2, "kind": "image"}, content_type="multipart/form-data").status_code == 400)

r = attach(job2, "clip_b", (HERE / "out" / "clip_b.mp4").read_bytes(), "b.mp4")
check("attach clip_b ok", r.status_code == 200 and r.json["duration"] > 0, r.status_code)
check("frame de B servido", c.get(r.json["preview"]).status_code == 200)
check("attach clip_b ext mala", attach(job2, "clip_b", b"x", "b.txt").status_code == 400)
check("attach clip_b corrupto", attach(job2, "clip_b", b"basura total", "b.mp4").status_code == 400)
check("attach clip_b basura con 0x0 no cuelga", attach(job2, "clip_b", b"no soy imagen", "b.png").status_code == 400)
check("render clip_clip con B", render2(job2, preset="clip_clip").status_code == 200)
check("render clip_clip audio b", render2(job2, preset="clip_clip", audio="b").status_code == 200)
check("render clip_clip mute", render2(job2, preset="clip_clip", audio="mute").status_code == 200)
check("reemplazar clip_b", attach(job2, "clip_b", (HERE / "out" / "clip_b.mp4").read_bytes(), "otro.mp4").status_code == 200)
check("render blur ignora cam invalida", render2(job2, preset="clip_blur", cam=[9, 9, 9, 9]).status_code == 200)
check("render game_cam valida cam", render2(job2, preset="game_cam", cam=[9, 9, 9, 9]).status_code == 400)
check("media no expone clip_b ni image.png", c.get(f"/media/{job2}/image.png").status_code == 404
      and c.get(f"/media/{job2}/clip_b.mp4").status_code == 404)

# ---- montaje en segundo plano ----
import time as _time

def start(job, **kw):
    body = {"id": job, "title": "Async", "account": "wganga", "people": ["westcol"], "cam": [0.7, 0.02, 0.28, 0.32]}
    body.update(kw)
    return c.post("/api/render-start", json=body)

def wait_task(tid, timeout=60):
    t0 = _time.time()
    seen = []
    while _time.time() - t0 < timeout:
        st = c.get(f"/api/render-status/{tid}").json
        seen.append(st["progress"])
        if st["state"] != "running":
            return st, seen
        _time.sleep(0.2)
    return {"state": "timeout"}, seen

check("render-start sin titulo -> 400", start(jid, title="").status_code == 400)
check("render-start id falso -> 404", start("0" * 32).status_code == 404)
check("render-start variacion mala -> 400", start(jid, preset="x").status_code == 400)
r = start(jid)
check("render-start ok", r.status_code == 200 and "task" in r.json, r.status_code)
tid = r.json["task"]
r2 = start(jid)
check("segundo montaje simultaneo -> 409", r2.status_code == 409, r2.status_code)
st, seen = wait_task(tid)
check("tarea termina en done", st["state"] == "done", st)
check("progreso sube hasta 1", seen[-1] == 1.0 and seen == sorted(seen), seen[-3:])
check("resultado trae video y captions", "video" in st["result"] and "#westcol" in st["result"]["captions"]["tiktok_caption"])
check("video final se descarga", c.get(st["result"]["video"]).status_code == 200)
check("status id falso -> 404", c.get("/api/render-status/" + "0" * 32).status_code == 404)
check("status id basura -> 404", c.get("/api/render-status/zzz").status_code == 404)
tid2 = start(jid, preset="clip_blur").json["task"]
st2, _ = wait_task(tid2)
check("segunda tarea tras terminar la primera", st2["state"] == "done", st2.get("state"))
with mock.patch.object(webapp.clipmaker, "build", side_effect=RuntimeError("detalle interno secreto")):
    tid3 = start(jid).json["task"]
    st3, _ = wait_task(tid3)
check("error de montaje no filtra detalles", st3["state"] == "error" and "secreto" not in st3["error"], st3)
check("tras un error se puede montar de nuevo", start(jid).status_code == 200)
wait_task(next(reversed(webapp.TASKS)))

# ---- recuadro de camara guardado fuera de las plantillas ----
before = (HERE / "templates" / "wganga.json").read_text()
box = [0.1, 0.2, 0.3, 0.25]
check("cam-default guarda", c.post("/api/cam-default", json={"account": "wganga", "cam": box}).status_code == 200)
check("accounts devuelve el guardado", c.get("/api/accounts").json["wganga"]["cam_crop"] == box)
check("otra cuenta conserva su valor", c.get("/api/accounts").json["gtahispa"]["cam_crop"] != box)
check("no toca templates/*.json", (HERE / "templates" / "wganga.json").read_text() == before)
webapp.CAM_FILE.write_text("{no es json")
check("archivo data corrupto -> usa el de la plantilla",
      c.get("/api/accounts").json["wganga"]["cam_crop"] == json.loads(before)["cam_crop"])
check("cam-default se recupera tras archivo corrupto", c.post("/api/cam-default", json={"account": "gtahispa", "cam": box}).status_code == 200)

# ---- actualizaciones ----
import updater as _upd
_upd.CONFIG_FILES = (Path(_tf.mkdtemp()) / "nada.json",)
r = c.get("/api/update/check")
check("update/check sin config -> deshabilitado", r.status_code == 200 and r.json["enabled"] is False and r.json["current"])
r = c.post("/api/update/apply")
check("update/apply sin config -> 400 claro", r.status_code == 400 and "configuradas" in r.json["error"], r.json)
with mock.patch.object(webapp.updater, "update", return_value={"version": "9.9.9", "from": "1.0.0", "files": 3, "backup": "x"}), \
     mock.patch.object(webapp.threading, "Timer") as timer:
    r = c.post("/api/update/apply")
    check("update/apply ok devuelve version", r.status_code == 200 and r.json["version"] == "9.9.9", r.status_code)
    check("update/apply programa el reinicio (codigo 42)", timer.called and timer.call_args.args[0] == 1.0 and timer.return_value.start.called)
with mock.patch.object(webapp.updater, "update", side_effect=RuntimeError("detalle interno de red")):
    r = c.post("/api/update/apply")
    check("update/apply error no filtra detalles", r.status_code == 500 and "detalle" not in r.json["error"] and "intacta" in r.json["error"])
with mock.patch.object(webapp.updater, "update", side_effect=_upd.UpdateError("Ya tienes la última versión")):
    check("update/apply UpdateError -> 400", c.post("/api/update/apply").status_code == 400)
check("RESTART_CODE es 42 (lo espera run.bat/run.sh)", webapp.RESTART_CODE == 42)

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
