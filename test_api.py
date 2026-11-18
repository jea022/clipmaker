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
_tmpdata = Path(_tf.mkdtemp()) / "data"
webapp.CAM_FILE = _tmpdata / "cam_defaults.json"
webapp.SETTINGS_FILE = _tmpdata / "account_settings.json"
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

# ---- ajustes por cuenta: camara, gameplay, franja y letra ----
from unittest import mock as _m
before = (HERE / "templates" / "wganga.json").read_text()
tpl = json.loads(before)
box, gbox = [0.1, 0.2, 0.3, 0.25], [0.0, 0.3, 0.7, 0.7]


def defaults(**kw):
    body = {"account": "wganga"}
    body.update(kw)
    return c.post("/api/account-defaults", json=body)


r = defaults(cam=box, game=gbox, title_height=400, font_size=80)
check("account-defaults guarda todo", r.status_code == 200 and r.json["settings"]["title_height"] == 400, r.status_code)
acc = c.get("/api/accounts").json
check("accounts devuelve lo guardado", (acc["wganga"]["cam_crop"], acc["wganga"]["game_crop"], acc["wganga"]["title_height"],
                                         acc["wganga"]["font_size"]) == (box, gbox, 400, 80), acc["wganga"])
check("accounts incluye valores de fabrica", acc["wganga"]["factory"]["title_height"] == 320 and acc["wganga"]["factory"]["font_size"] == 96)
check("otra cuenta conserva los suyos", acc["gtahispa"]["title_height"] == 320 and acc["gtahispa"]["cam_crop"] != box)
check("no toca templates/*.json", (HERE / "templates" / "wganga.json").read_text() == before)
check("guardado parcial mantiene el resto", defaults(font_size=60).status_code == 200
      and c.get("/api/accounts").json["wganga"]["cam_crop"] == box and c.get("/api/accounts").json["wganga"]["font_size"] == 60)
for name, kw in (("alto bajo", dict(title_height=50)), ("alto alto", dict(title_height=9999)), ("letra baja", dict(font_size=5)),
                 ("letra alta", dict(font_size=999)), ("alto texto", dict(title_height="abc")), ("alto bool", dict(title_height=True)),
                 ("cam fuera", dict(cam=[2, 2, 2, 2])), ("game fuera", dict(game=[0.9, 0.9, 0.5, 0.5])), ("game basura", dict(game="x")),
                 ("nada que guardar", dict())):
    check(f"account-defaults rechaza {name}", defaults(**kw).status_code == 400)
check("account-defaults cuenta mala", c.post("/api/account-defaults", json={"account": "x", "cam": box}).status_code == 400)
check("account-defaults reset -> fabrica", defaults(reset=True).json["settings"]["title_height"] == 320
      and c.get("/api/accounts").json["wganga"]["cam_crop"] == tpl["cam_crop"])
webapp.SETTINGS_FILE.write_text("{no es json")
check("archivo corrupto -> usa la plantilla", c.get("/api/accounts").json["wganga"]["title_height"] == 320)
webapp.SETTINGS_FILE.write_text(json.dumps({"wganga": {"title_height": 9999, "font_size": 70, "cam_crop": "x"}}))
a2 = c.get("/api/accounts").json["wganga"]
check("valores guardados invalidos caen a fabrica uno a uno", a2["title_height"] == 320 and a2["font_size"] == 70 and a2["cam_crop"] == tpl["cam_crop"], a2)
webapp.SETTINGS_FILE.unlink()
webapp.CAM_FILE.write_text(json.dumps({"wganga": box}))
check("formato antiguo (cam_defaults.json) se respeta", c.get("/api/accounts").json["wganga"]["cam_crop"] == box)
webapp.CAM_FILE.unlink()
defaults(title_height=440, font_size=64, game=gbox)

# se aplican al montar: guardados por defecto y sobrescritos por la peticion
def captured(**kw):
    body = {"id": jid, "title": "Hola", "account": "wganga", "preset": "cam_game"}
    body.update(kw)
    with _m.patch.object(webapp.clipmaker, "build") as b:
        r = c.post("/api/render", json=body)
    return r, (b.call_args.args[2] if b.called else None)

r, cfg_used = captured()
check("render usa los ajustes guardados", r.status_code == 200 and cfg_used["title_height"] == 440 and cfg_used["title"]["max_size"] == 64
      and cfg_used["game_crop"] == gbox, cfg_used and cfg_used.get("title_height"))
r, cfg_used = captured(title_height=200, font_size=120, game=[0, 0, 1, 1])
check("la peticion pisa lo guardado", cfg_used["title_height"] == 200 and cfg_used["title"]["max_size"] == 120 and cfg_used["game_crop"] == [0, 0, 1, 1])
check("render alto fuera de rango -> 400", captured(title_height=50)[0].status_code == 400)
check("render letra rara -> 400", captured(font_size="grande")[0].status_code == 400)
check("render game invalido -> 400", captured(game=[1, 1, 1, 1])[0].status_code == 400)
check("render title_height bool -> 400", captured(title_height=True)[0].status_code == 400)
defaults(reset=True)

# ---- vista previa ----
import io as _io

def preview(**kw):
    body = {"id": jid, "title": "Vista previa", "account": "wganga", "preset": "cam_game"}
    body.update(kw)
    return c.post("/api/preview", json=body)

r = preview()
img = Image.open(_io.BytesIO(r.data)) if r.status_code == 200 else None
check("preview devuelve png 1080x1920", r.status_code == 200 and r.mimetype == "image/png" and img.size == (1080, 1920), r.status_code)
check("preview sin cache", "no-store" in r.headers.get("Cache-Control", ""))
check("preview con titulo vacio usa uno de ejemplo", preview(title="  ").status_code == 200)
a1, a2_ = preview(title_height=120).data, preview(title_height=560).data
check("preview cambia con el alto de la franja", a1 != a2_)
check("preview con otra letra cambia", preview(font_size=40).data != preview(font_size=160).data)
check("preview game recortado cambia", preview(game=[0, 0, 0.5, 0.5]).data != preview().data)
check("preview variacion que pide imagen sin imagen -> 400", preview(id=fresh, preset="clip_image").status_code == 400)
check("preview id falso -> 404", preview(id="0" * 32).status_code == 404)
check("preview alto invalido -> 400", preview(title_height=1).status_code == 400)
check("preview cuenta mala -> 400", preview(account="x").status_code == 400)
for pid in ("game_cam", "clip_blur"):
    check(f"preview {pid}", preview(preset=pid).status_code == 200)
check("preview clip_image con imagen", preview(id=job2, preset="clip_image", title_height=300).status_code == 200)

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
