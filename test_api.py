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
import captions as _captions
_captions.USER_FILE = _tmpdata / "hashtags.json"
_captions.CURSOR_FILE = _tmpdata / "hashtag_cursor.json"
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

# ---- estilos de texto y tipografias ----
opts = c.get("/api/text-options").json
check("text-options: 6 estilos y 7 fuentes", len(opts["styles"]) == 6 and len(opts["fonts"]) == 7, (len(opts["styles"]), len(opts["fonts"])))
check("text-options: incluye caja blanca y Anton", any(s["id"] == "box_white" and s["box"] == "#ffffff" for s in opts["styles"])
      and any(f["id"] == "anton" and f["label"] == "Anton" for f in opts["fonts"]))
for f in opts["fonts"]:
    rr = c.get(f["url"])
    check(f"fuente servida {f['id']}", rr.status_code == 200 and len(rr.data) > 10000 and "max-age" in rr.headers.get("Cache-Control", ""))
for bad in ("../app.py", "..%2fapp.py", "licenses", "licenses/OFL-anton.txt", "OFL-anton.txt", "README.txt", "nada.ttf", "%2e%2e%2fapp.py"):
    check(f"fuentes: no sirve {bad}", c.get("/fonts/" + bad).status_code == 404)
a0 = c.get("/api/accounts").json["wganga"]
check("factory trae estilo/fuente/reparto/offset/mayusculas", a0["factory"]["title_style"] == "band" and a0["factory"]["font"] == "inter"
      and a0["factory"]["title_split"] == 50 and a0["factory"]["title_offset"] == 0 and a0["factory"]["uppercase"] is True, a0["factory"])

r = defaults(title_style="box_white", font="anton", split=40, offset=120, uppercase=False, font_size=56)
st = r.json["settings"] if r.status_code == 200 else {}
check("account-defaults guarda estilo, fuente, reparto, offset, mayusculas",
      st.get("title_style") == "box_white" and st.get("font") == "anton" and st.get("title_split") == 40
      and st.get("title_offset") == 120 and st.get("uppercase") is False, st)
a1 = c.get("/api/accounts").json
check("accounts devuelve los ajustes de texto guardados", a1["wganga"]["font"] == "anton" and a1["wganga"]["title_style"] == "box_white")
check("otra cuenta no hereda el estilo", a1["gtahispa"]["title_style"] == "band" and a1["gtahispa"]["font"] == "inter")
for name, kw in (("estilo raro", dict(title_style="neon")), ("estilo vacio", dict(title_style="")), ("estilo numero", dict(title_style=5)),
                 ("estilo lista", dict(title_style=["box_white"])), ("fuente rara", dict(font="comic")), ("fuente numero", dict(font=7)),
                 ("split bajo", dict(split=10)), ("split alto", dict(split=90)), ("split texto", dict(split="x")), ("split bool", dict(split=True)),
                 ("offset fuera", dict(offset=9999)), ("offset menos", dict(offset=-9999)), ("offset texto", dict(offset="x")),
                 ("mayusculas texto", dict(uppercase="si")), ("mayusculas numero", dict(uppercase=1)), ("mayusculas lista", dict(uppercase=[True]))):
    check(f"account-defaults rechaza {name}", defaults(**kw).status_code == 400)
check("tras rechazos lo guardado sigue intacto", c.get("/api/accounts").json["wganga"]["font"] == "anton")
webapp.SETTINGS_FILE.write_text(json.dumps({"wganga": {"title_style": "neon", "font": "anton", "title_split": 5, "title_offset": 40, "uppercase": "no"}}))
a2 = c.get("/api/accounts").json["wganga"]
check("ajustes de texto invalidos guardados caen a fabrica uno a uno",
      a2["title_style"] == "band" and a2["font"] == "anton" and a2["title_split"] == 50 and a2["title_offset"] == 40 and a2["uppercase"] is True, a2)
check("reset devuelve todo a fabrica", defaults(reset=True).json["settings"]["font"] == "inter")

r, cfg_used = captured()
check("render sin ajustes de texto usa franja e Inter", cfg_used["title_style"] == "band" and cfg_used.get("font") == "inter")
defaults(title_style="box_black", font="bebas", split=35, offset=-80, uppercase=False)
r, cfg_used = captured()
check("render usa el estilo y la fuente guardados", cfg_used["title_style"] == "box_black" and cfg_used["font"] == "bebas"
      and cfg_used["title_split"] == 35 and cfg_used["title_offset"] == -80 and cfg_used["title"]["uppercase"] is False)
r, cfg_used = captured(title_style="outline", font="bangers", split=60, offset=10, uppercase=True)
check("la peticion pisa el estilo guardado", cfg_used["title_style"] == "outline" and cfg_used["font"] == "bangers"
      and cfg_used["title_split"] == 60 and cfg_used["title_offset"] == 10 and cfg_used["title"]["uppercase"] is True)
for name, kw in (("estilo", dict(title_style="x")), ("fuente", dict(font="x")), ("split", dict(split=99)), ("offset", dict(offset=-600)),
                 ("mayusculas", dict(uppercase="x"))):
    check(f"render rechaza {name} invalido", captured(**kw)[0].status_code == 400)
defaults(reset=True)

check("preview con caja blanca difiere de la franja", preview(title_style="box_white", font_size=56).data != preview().data)
check("preview con otra fuente difiere", preview(title_style="box_white", font="anton").data != preview(title_style="box_white", font="bangers").data)
check("preview reparto distinto difiere", preview(title_style="box_white", split=30).data != preview(title_style="box_white", split=70).data)
check("preview offset distinto difiere", preview(title_style="box_white", offset=-200).data != preview(title_style="box_white", offset=200).data)
check("preview estilo invalido -> 400", preview(title_style="x").status_code == 400)
for sid in ("box_white", "box_black", "outline", "outline_yellow"):
    check(f"preview con titulo solo de emojis y {sid} no rompe", preview(title="😂😂", title_style=sid).status_code == 200)
check("montaje sincrono con titulo solo de emojis y caja", c.post("/api/render", json={"id": jid, "title": "😂", "account": "wganga",
      "title_style": "box_white"}).status_code == 200)
for pid in ("game_cam", "clip_blur", "clip_image"):
    check(f"preview {pid} con caja", preview(id=job2 if pid == "clip_image" else jid, preset=pid, title_style="box_yellow").status_code == 200)
tid = start(jid, title_style="outline_yellow", font="anton").json["task"]
stt, _ = wait_task(tid)
check("montaje en segundo plano con estilo superpuesto", stt["state"] == "done", stt.get("error"))
check("montaje en segundo plano con estilo invalido -> 400", start(jid, title_style="x").status_code == 400)

# ---- hashtags: lista editable y reparto ----
hv = c.get("/api/hashtags").json
check("hashtags: devuelve las dos cuentas con config, recomendados y estado",
      set(hv) == {"wganga", "gtahispa", "gtaclipsboss"} and all({"config", "defaults", "customized"} <= set(v) for v in hv.values()) and not hv["wganga"]["customized"])
check("hashtags: los recomendados traen GTA6/GTAVI y personas", hv["wganga"]["config"]["always"] == ["#GTA6", "#GTAVI"] and "westcol" in hv["wganga"]["config"]["people"])
check("accounts: las personas salen de la lista de hashtags", "lonche" in c.get("/api/accounts").json["wganga"]["people"])


def save_ht(account="wganga", **cfg):
    return c.post("/api/hashtags", json={"account": account, "config": cfg})


r = save_ht(always=["#GTA6"], niche="#aaa1 #bbb1, ccc1", broad=["#fyp"], people={"Ana López": ["#ana1", "ana2"]}, count_tiktok=6)
v = r.json if r.status_code == 200 else {}
check("hashtags: guardar normaliza y marca la cuenta como personalizada",
      r.status_code == 200 and v["config"]["niche"] == ["#aaa1", "#bbb1", "#ccc1"] and v["config"]["people"] == {"analopez": ["#ana1", "#ana2"]} and v["customized"] is True, r.status_code)
check("hashtags: lo guardado aparece en /api/accounts como persona", "analopez" in c.get("/api/accounts").json["wganga"]["people"])
check("hashtags: la otra cuenta no cambia", not c.get("/api/hashtags").json["gtahispa"]["customized"])
for name, body in (("cuenta rara", {"account": "x", "config": {}}), ("cuenta lista", {"account": ["wganga"], "config": {}}),
                   ("sin config", {"account": "wganga"}), ("config no dict", {"account": "wganga", "config": ["x"]}),
                   ("hashtag con espacio", {"account": "wganga", "config": {"niche": [["#dos palabras"]]}}),
                   ("hashtag con simbolo", {"account": "wganga", "config": {"niche": ["#ho!la"]}}),
                   ("cantidad fuera de rango", {"account": "wganga", "config": {"count_tiktok": 99}}),
                   ("demasiados fijos", {"account": "wganga", "config": {"always": [f"#t{i}x" for i in range(6)]}}),
                   ("persona sin hashtags", {"account": "wganga", "config": {"people": {"ab": []}}})):
    check(f"hashtags: rechaza {name}", c.post("/api/hashtags", json=body).status_code == 400)
check("hashtags: tras rechazos lo guardado sigue intacto", c.get("/api/hashtags").json["wganga"]["config"]["count_tiktok"] == 6)
r = c.post("/api/hashtags", json={"account": "wganga", "reset": True})
check("hashtags: restablecer vuelve a los recomendados", r.status_code == 200 and r.json["customized"] is False and r.json["config"] == r.json["defaults"])
check("hashtags: restablecer una cuenta inexistente -> 400", c.post("/api/hashtags", json={"account": "x", "reset": True}).status_code == 400)


def ht_preview(**kw):
    body = {"account": "wganga", "title": "Prueba", "people": ["westcol"], "n": 6}
    body.update(kw)
    return c.post("/api/hashtags/preview", json=body)


r = ht_preview()
check("hashtags/preview: devuelve 6 captions con clips distintos", r.status_code == 200 and len(r.json["samples"]) == 6
      and len({tuple(s["hashtags"]) for s in r.json["samples"]}) == 6, r.status_code)
check("hashtags/preview: cada caption lleva 5 hashtags y los fijos", all(len(s["hashtags"]) == 5 and s["hashtags"][:2] == ["#GTA6", "#GTAVI"] for s in r.json["samples"]))
check("hashtags/preview: YouTube lleva #Shorts al final", all(s["yt_hashtags"][-1] == "#Shorts" and len(s["yt_hashtags"]) == 4 for s in r.json["samples"]))
check("hashtags/preview: uso por hashtag en 30 clips", r.json["usage"][0]["clips"] == 30 and all(set(u) == {"tag", "clips"} for u in r.json["usage"]))
r2 = ht_preview(config={"always": ["#solo1"], "niche": ["#nn1", "#nn2", "#nn3"], "count_tiktok": 4}, people=[])
check("hashtags/preview: usa la config sin guardar", r2.status_code == 200 and r2.json["samples"][0]["hashtags"][0] == "#solo1"
      and not c.get("/api/hashtags").json["wganga"]["customized"])
rp = ht_preview(clip_game="gta5rp", people=[])
check("hashtags/preview: clip RP no lleva #GTA6 y si los de RP",
      rp.status_code == 200 and all("#GTA6" not in s["hashtags"] and s["hashtags"][0] == "#gtaroleplay" for s in rp.json["samples"]))
check("hashtags/preview: clip GTA VI no lleva hashtags de RP",
      not any(t in ("#gtaroleplay", "#colombiarp") for s in r.json["samples"] for t in s["hashtags"]))
for name, kw in (("juego raro", dict(clip_game="minecraft")), ("juego lista", dict(clip_game=["gta6"])), ("cuenta rara", dict(account="x")),
                 ("config invalida", dict(config={"niche": ["#mal uno"]}))):
    check(f"hashtags/preview rechaza {name}", ht_preview(**kw).status_code == 400)
check("hashtags/preview: n fuera de rango usa 6", len(ht_preview(n=999).json["samples"]) == 6 and len(ht_preview(n="x").json["samples"]) == 6)
check("hashtags/preview: titulo vacio usa uno de ejemplo", ht_preview(title="").status_code == 200)

# el numero de clip avanza con cada montaje y el juego se aplica
c0 = c.post("/api/render", json={"id": jid, "title": "Uno", "account": "wganga", "people": ["westcol"]})
c1 = c.post("/api/render", json={"id": jid, "title": "Uno", "account": "wganga", "people": ["westcol"]})
cap0, cap1 = c0.json["captions"], c1.json["captions"]
check("render: el numero de clip avanza (0, 1...)", cap1["cursor"] == cap0["cursor"] + 1, (cap0["cursor"], cap1["cursor"]))
check("render: dos clips seguidos llevan hashtags distintos", cap0["hashtags"] != cap1["hashtags"])
check("render: la cuenta gtahispa lleva su propio contador", c.post("/api/render", json={"id": jid, "title": "Uno", "account": "gtahispa"}).json["captions"]["cursor"] == 0)
rp_r = c.post("/api/render", json={"id": jid, "title": "RP", "account": "wganga", "clip_game": "gta5rp"})
check("render: juego RP cambia los hashtags fijos", rp_r.status_code == 200 and "#GTA6" not in rp_r.json["captions"]["hashtags"] and rp_r.json["captions"]["game"] == "gta5rp")
check("render: juego invalido -> 400", c.post("/api/render", json={"id": jid, "title": "x", "account": "wganga", "clip_game": "otro"}).status_code == 400)
check("render: juego lista -> 400", c.post("/api/render", json={"id": jid, "title": "x", "account": "wganga", "clip_game": ["gta6"]}).status_code == 400)
tidg = start(jid, clip_game="gta5rp").json["task"]
stg, _ = wait_task(tidg)
check("montaje en segundo plano con juego RP", stg["state"] == "done" and stg["result"]["captions"]["game"] == "gta5rp", stg.get("error"))
check("montaje en segundo plano con juego invalido -> 400", start(jid, clip_game="otro").status_code == 400)
ht_custom = save_ht(always=["#propio1"], niche=["#extra1", "#extra2"], people={"ana": ["#ana1"]}, count_tiktok=3)
cust = c.post("/api/render", json={"id": jid, "title": "x", "account": "wganga", "people": ["ana"]}).json["captions"]
check("render: usa la lista personalizada", cust["hashtags"][:2] == ["#propio1", "#ana1"] and len(cust["hashtags"]) == 3, cust["hashtags"])
c.post("/api/hashtags", json={"account": "wganga", "reset": True})

# YouTube usa el mismo reparto que se vio en pantalla
with mock.patch.object(webapp.publish_youtube, "upload", return_value="VIDH") as up_mock:
    pr = c.post("/api/publish-youtube", json={"id": jid, "title": "Hola", "account": "wganga", "people": ["westcol"], "cursor": 4, "clip_game": "gta6"})
    sent = up_mock.call_args.args[2] if up_mock.called else {}
    want = _captions.generate("wganga", "Hola", ["westcol"], 4, "gta6")
    check("publicar: YouTube usa el mismo reparto (mismo clip) que el caption", pr.status_code == 200 and sent["snippet"]["tags"] == [t.lstrip("#") for t in want["yt_hashtags"]], sent.get("snippet", {}).get("tags"))
    check("publicar: la descripcion lleva los mismos hashtags", all(t in sent["snippet"]["description"] for t in want["yt_hashtags"]))
    check("publicar: juego invalido -> 400", c.post("/api/publish-youtube", json={"id": jid, "title": "Hola", "account": "wganga", "clip_game": "x"}).status_code == 400)
    pr2 = c.post("/api/publish-youtube", json={"id": jid, "title": "Hola", "account": "wganga", "cursor": "x"})
    check("publicar: cursor basura se trata como 0", pr2.status_code == 200)

# ---- ping y cierre (los usa el lanzador) ----
import os as _os
pg = c.get("/api/ping").json
check("ping: identifica la app, su version y su proceso", pg["app"] == "clipmaker" and pg["version"] == (HERE / "VERSION").read_text().strip() and pg["pid"] == _os.getpid(), pg)
check("shutdown sin cabecera -> 403", c.post("/api/shutdown").status_code == 403)
check("shutdown con cabecera incorrecta -> 403", c.post("/api/shutdown", headers={"X-Clipmaker": "0"}).status_code == 403
      and c.post("/api/shutdown", headers={"X-Clipmaker": "true"}).status_code == 403)
check("shutdown con JSON de otra pagina (sin cabecera propia) -> 403", c.post("/api/shutdown", json={"x": 1}, headers={"Origin": "https://evil.example"}).status_code == 403)
with mock.patch.object(webapp.threading, "Timer") as tm:
    rs = c.post("/api/shutdown", headers={"X-Clipmaker": "1"})
    check("shutdown con cabecera correcta -> 200 y programa el cierre", rs.status_code == 200 and rs.json["ok"] is True and tm.called
          and tm.call_args.args[0] == 0.5 and tm.return_value.start.called)
check("shutdown: GET no esta permitido", c.get("/api/shutdown").status_code == 405)

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

# --- cuenta @gtaclipsboss ---
accs = c.get("/api/accounts").json
check("cuentas: aparece @gtaclipsboss", accs.get("gtaclipsboss", {}).get("handle") == "@gtaclipsboss", list(accs))
check("cuentas: @gtaclipsboss tiene su propia plantilla de marca", accs["gtaclipsboss"]["factory"] is not None and Path("templates/gtaclipsboss_bg.png").is_file())
hh = c.get("/api/hashtags").json
check("hashtags: @gtaclipsboss usa los mismos que @gtaHispaClips", hh["gtaclipsboss"]["defaults"] == hh["gtahispa"]["defaults"])
check("hashtags: @gtaclipsboss tiene sus propios contadores", c.post("/api/render", json={"id": jid, "title": "Uno", "account": "gtaclipsboss"}).status_code == 200)

print(f"\n{len(fails)} fallos")
sys.exit(1 if fails else 0)
