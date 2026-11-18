#!/usr/bin/env python3
"""Web local para montar clips: sube el clip, escribe el titulo, marca la camara y descarga el video."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

import captions
import clipmaker
import publish_youtube
import updater

HERE = Path(__file__).parent
WORK = HERE / "work"
TEMPLATES = HERE / "templates"
DATA = HERE / "data"
SETTINGS_FILE = DATA / "account_settings.json"
CAM_FILE = DATA / "cam_defaults.json"
ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MEDIA_FILES = {"frame.png", "frame_b.png", "image_preview.png", "out.mp4"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_TITLE = 200
RESTART_CODE = 42

app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")
WORK.mkdir(exist_ok=True)
app.json.sort_keys = False
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


def cleanup_old_jobs(max_age_hours=24):
    cutoff = time.time() - max_age_hours * 3600
    for d in WORK.glob("*"):
        if d.is_dir() and ID_RE.match(d.name) and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def job_dir(job_id):
    if not ID_RE.match(job_id or ""):
        abort(404)
    d = WORK / job_id
    if not d.is_dir():
        abort(404)
    return d


def account_layout_path(account):
    if account not in captions.ACCOUNTS:
        abort(400, description=f"cuenta desconocida: {account}")
    p = TEMPLATES / f"{account}.json"
    if not p.is_file():
        abort(500, description="Faltan las plantillas: ejecuta python make_template.py")
    return p


def _read_json(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


SETTING_KEYS = {
    "cam_crop": ("cam", lambda cfg: cfg["cam_crop"]),
    "game_crop": ("game", lambda cfg: cfg["game_crop"]),
    "title_height": ("title_height", lambda cfg: cfg["title_height"]),
    "font_size": ("font_size", lambda cfg: cfg["title"]["max_size"]),
}


REQUEST_TO_KEY = {kw: key for key, (kw, _) in SETTING_KEYS.items()}


def factory_settings(cfg):
    return {"cam_crop": cfg["cam_crop"], "game_crop": cfg["game_crop"],
            "title_height": cfg["title_zone"][3], "font_size": cfg["title"]["max_size"]}


def account_settings(account, cfg):
    """Valores de la cuenta: los guardados (si son válidos) o los de la plantilla."""
    eff = factory_settings(cfg)
    legacy = clipmaker.valid_box(_read_json(CAM_FILE).get(account) or [])
    if legacy:
        eff["cam_crop"] = legacy
    saved = _read_json(SETTINGS_FILE).get(account)
    if isinstance(saved, dict):
        for key, (kw, getter) in SETTING_KEYS.items():
            if key in saved:
                try:
                    eff[key] = getter(clipmaker.apply_overrides(cfg, **{kw: saved[key]}))
                except ValueError:
                    pass
    return eff


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/accounts")
def api_accounts():
    out = {}
    for name, acc in captions.ACCOUNTS.items():
        cfg = json.loads(account_layout_path(name).read_text())
        out[name] = {"handle": acc["handle"], "people": sorted(acc["people"]), **account_settings(name, cfg),
                     "factory": factory_settings(cfg)}
    return jsonify(out)


@app.get("/api/presets")
def api_presets():
    return jsonify([
        {"id": pid, "label": spec["label"], "needs": spec["needs"], "uses_cam": spec["uses_cam"],
         "diagram": spec["diagram"]}
        for pid, spec in clipmaker.PRESETS.items()
    ])


def extra_file(d, kind):
    pattern = "clip_b.*" if kind == "clip_b" else "image.png"
    return next(iter(sorted(d.glob(pattern))), None)


@app.post("/api/attach")
def api_attach():
    d = job_dir(request.form.get("id"))
    kind = request.form.get("kind")
    f = request.files.get("file")
    if kind not in {"clip_b", "image"}:
        return jsonify(error="kind debe ser clip_b o image"), 400
    if not f or not f.filename:
        return jsonify(error="Falta el archivo"), 400
    ext = Path(f.filename).suffix.lower()
    if kind == "image":
        if ext not in IMAGE_EXT:
            return jsonify(error=f"Imagen no soportada ({ext or 'sin extension'}). Usa {', '.join(sorted(IMAGE_EXT))}"), 400
        raw = d / f"image_upload{ext}"
        f.save(raw)
        try:
            if raw.stat().st_size > MAX_IMAGE_BYTES:
                return jsonify(error="La imagen pesa más de 40 MB"), 400
            new_png = d / "image_new.png"
            clipmaker.normalize_image(raw, new_png)
            from PIL import Image
            prev = Image.open(new_png)
            w, h = prev.size
            prev.thumbnail((640, 640))
            prev.save(d / "image_preview.png")
            new_png.replace(d / "image.png")
        except Exception:
            (d / "image_new.png").unlink(missing_ok=True)
            return jsonify(error="No pude leer esa imagen. ¿Está corrupta?"), 400
        finally:
            raw.unlink(missing_ok=True)
        return jsonify(kind=kind, width=w, height=h, preview=f"/media/{d.name}/image_preview.png")
    if ext not in ALLOWED_EXT:
        return jsonify(error=f"Formato no soportado ({ext or 'sin extension'}). Usa {', '.join(sorted(ALLOWED_EXT))}"), 400
    tmp = d / f"incoming_b{ext}"
    f.save(tmp)
    try:
        w, h = clipmaker.probe_size(tmp)
        dur = clipmaker.probe_duration(tmp)
        clipmaker.extract_frame(tmp, d / "frame_b.png")
    except (subprocess.CalledProcessError, ValueError):
        tmp.unlink(missing_ok=True)
        return jsonify(error="No pude leer ese video. ¿Está corrupto?"), 400
    for old in d.glob("clip_b.*"):
        old.unlink()
    tmp.replace(d / f"clip_b{ext}")
    return jsonify(kind=kind, width=w, height=h, duration=round(dur, 2), preview=f"/media/{d.name}/frame_b.png")


@app.post("/api/upload")
def api_upload():
    f = request.files.get("clip")
    if not f or not f.filename:
        return jsonify(error="Falta el archivo de clip"), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify(error=f"Formato no soportado ({ext or 'sin extension'}). Usa {', '.join(sorted(ALLOWED_EXT))}"), 400
    cleanup_old_jobs()
    job_id = uuid.uuid4().hex
    d = WORK / job_id
    d.mkdir(parents=True)
    src = d / f"source{ext}"
    f.save(src)
    try:
        w, h = clipmaker.probe_size(src)
        dur = clipmaker.probe_duration(src)
        clipmaker.extract_frame(src, d / "frame.png")
    except (subprocess.CalledProcessError, ValueError):
        shutil.rmtree(d, ignore_errors=True)
        return jsonify(error="No pude leer ese video. ¿Está corrupto?"), 400
    return jsonify(id=job_id, width=w, height=h, duration=round(dur, 2), frame=f"/media/{job_id}/frame.png")


@app.get("/media/<job_id>/<name>")
def media(job_id, name):
    if name not in MEDIA_FILES:
        abort(404)
    return send_from_directory(job_dir(job_id), name, as_attachment=(name == "out.mp4" and request.args.get("dl") == "1"),
                               download_name="clip_vertical.mp4")


TASKS = {}
TASKS_LOCK = threading.Lock()


def prepare_render(data):
    """Valida la peticion. Devuelve (params, None) o (None, (respuesta_json, codigo))."""
    d = job_dir(data.get("id"))
    title = " ".join(str(data.get("title", "")).split())
    if not title:
        return None, (jsonify(error="Escribe un título"), 400)
    if len(title) > MAX_TITLE:
        return None, (jsonify(error=f"El título es demasiado largo (máx {MAX_TITLE} caracteres)"), 400)
    account = data.get("account")
    cfg = json.loads(account_layout_path(account).read_text())
    preset = data.get("preset", "cam_game")
    if preset not in clipmaker.PRESETS:
        return None, (jsonify(error=f"Variación desconocida: {preset}"), 400)
    spec = clipmaker.PRESETS[preset]
    audio = data.get("audio", "a")
    if audio not in clipmaker.AUDIO_CHOICES:
        return None, (jsonify(error="Opción de audio inválida"), 400)
    image, clip_b = extra_file(d, "image"), extra_file(d, "clip_b")
    if "image" in spec["needs"] and not image:
        return None, (jsonify(error="Esta variación necesita una imagen: súbela primero"), 400)
    if "clip_b" in spec["needs"] and not clip_b:
        return None, (jsonify(error="Esta variación necesita un segundo video: súbelo primero"), 400)
    if audio == "b" and not clip_b:
        return None, (jsonify(error="Para usar el audio del video B primero súbelo"), 400)
    no_cam = bool(data.get("no_cam")) and spec["uses_cam"]
    eff = account_settings(account, cfg)
    ov = dict(cam=eff["cam_crop"], game=eff["game_crop"], title_height=eff["title_height"], font_size=eff["font_size"])
    if spec["uses_cam"] and not no_cam and data.get("cam") is not None:
        ov["cam"] = data["cam"]
    for key in ("game", "title_height", "font_size"):
        if data.get(key) is not None:
            ov[key] = data[key]
    try:
        cfg = clipmaker.apply_overrides(cfg, **ov)
    except ValueError as e:
        return None, (jsonify(error=str(e)), 400)
    people = [str(p) for p in data.get("people", []) if isinstance(p, str)][:10]
    return dict(d=d, title=title, cfg=cfg, preset=preset, clip_b=clip_b, image=image, audio=audio, no_cam=no_cam,
                src=next(p for p in d.iterdir() if p.stem == "source"), out=d / "out.mp4",
                account=account, people=people), None


def render_result(p):
    return dict(video=f"/media/{p['d'].name}/out.mp4", download=f"/media/{p['d'].name}/out.mp4?dl=1",
                captions=captions.generate(p["account"], p["title"], p["people"]))


def run_build(p, progress_cb=None):
    clipmaker.build(p["src"], p["title"], p["cfg"], p["out"], p["no_cam"], p["preset"], p["clip_b"],
                    p["image"], p["audio"], progress_cb=progress_cb)


@app.post("/api/render")
def api_render():
    p, err = prepare_render(request.get_json(silent=True) or {})
    if err:
        return err
    try:
        run_build(p)
    except subprocess.CalledProcessError:
        return jsonify(error="Falló el montaje del video (ffmpeg)"), 500
    return jsonify(render_result(p))


def cleanup_old_tasks(max_age=3600):
    now = time.time()
    for tid in [t for t, v in TASKS.items() if now - v["created"] > max_age and v["state"] != "running"]:
        TASKS.pop(tid, None)


@app.post("/api/render-start")
def api_render_start():
    p, err = prepare_render(request.get_json(silent=True) or {})
    if err:
        return err
    with TASKS_LOCK:
        cleanup_old_tasks()
        if any(v["state"] == "running" for v in TASKS.values()):
            return jsonify(error="Ya hay un montaje en curso: espera a que termine"), 409
        tid = uuid.uuid4().hex
        task = TASKS[tid] = {"state": "running", "progress": 0.0, "created": time.time()}

    def work():
        try:
            run_build(p, lambda f: task.__setitem__("progress", round(f, 3)))
            task.update(state="done", progress=1.0, result=render_result(p))
        except Exception as e:
            app.logger.exception("fallo montando video")
            msg = "Falló el montaje del video (ffmpeg)" if isinstance(e, subprocess.CalledProcessError) \
                else "Falló el montaje del video"
            task.update(state="error", error=msg)

    threading.Thread(target=work, daemon=True).start()
    return jsonify(task=tid)


@app.get("/api/render-status/<task_id>")
def api_render_status(task_id):
    task = TASKS.get(task_id)
    if not ID_RE.match(task_id) or task is None:
        abort(404)
    out = {"state": task["state"], "progress": task["progress"]}
    if task["state"] == "done":
        out["result"] = task["result"]
    if task["state"] == "error":
        out["error"] = task["error"]
    return jsonify(out)


@app.post("/api/publish-youtube")
def api_publish_youtube():
    data = request.get_json(silent=True) or {}
    d = job_dir(data.get("id"))
    account = data.get("account")
    account_layout_path(account)
    privacy = data.get("privacy", "private")
    if privacy not in {"private", "unlisted"}:
        return jsonify(error="Desde aquí solo se sube como privado o no listado"), 400
    title = " ".join(str(data.get("title", "")).split())
    if not title or len(title) > MAX_TITLE:
        return jsonify(error="Título inválido"), 400
    video = d / "out.mp4"
    if not video.is_file():
        return jsonify(error="Primero crea el video"), 400
    people = [str(p) for p in data.get("people", []) if isinstance(p, str)][:10]
    try:
        publish_youtube.validate_video(video)
        vid = publish_youtube.upload(account, video, publish_youtube.build_body(account, title, people, privacy))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except FileNotFoundError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        app.logger.exception("fallo subiendo a YouTube")
        return jsonify(error=f"YouTube rechazó la subida: {type(e).__name__}"), 502
    return jsonify(url=f"https://youtube.com/shorts/{vid}", privacy=privacy)


@app.get("/api/update/check")
def api_update_check():
    return jsonify(updater.check())


@app.post("/api/update/apply")
def api_update_apply():
    try:
        result = updater.update()
    except updater.UpdateError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        app.logger.exception("fallo actualizando")
        return jsonify(error="No pude actualizar. Tu versión sigue intacta."), 500
    threading.Timer(1.0, lambda: os._exit(RESTART_CODE)).start()
    return jsonify(result)


PREVIEW_LOCK = threading.Lock()


@app.post("/api/preview")
def api_preview():
    data = request.get_json(silent=True) or {}
    if not " ".join(str(data.get("title", "")).split()):
        data = dict(data, title="Tu título aquí")
    p, err = prepare_render(data)
    if err:
        return err
    still = p["d"] / "preview.png"
    with PREVIEW_LOCK:
        try:
            clipmaker.build(p["src"], p["title"], p["cfg"], still, p["no_cam"], p["preset"], p["clip_b"],
                            p["image"], p["audio"], still=True)
        except subprocess.CalledProcessError:
            return jsonify(error="No pude generar la vista previa"), 500
    resp = send_from_directory(p["d"], "preview.png", mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/account-defaults")
def api_account_defaults():
    data = request.get_json(silent=True) or {}
    account = data.get("account")
    cfg = json.loads(account_layout_path(account).read_text())
    saved_all = _read_json(SETTINGS_FILE)
    if data.get("reset"):
        saved_all.pop(account, None)
    else:
        given = {req: data[req] for req in REQUEST_TO_KEY if data.get(req) is not None}
        if not given:
            return jsonify(error="No hay nada que guardar"), 400
        try:
            ov = clipmaker.apply_overrides(cfg, **given)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        entry = saved_all.get(account) if isinstance(saved_all.get(account), dict) else {}
        for req in given:
            key = REQUEST_TO_KEY[req]
            entry[key] = SETTING_KEYS[key][1](ov)
        saved_all[account] = entry
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(saved_all, indent=2))
    tmp.replace(SETTINGS_FILE)
    return jsonify(ok=True, settings=account_settings(account, cfg))


if __name__ == "__main__":
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"No encuentro {tool}. Instala ffmpeg primero.")
    WORK.mkdir(exist_ok=True)
    print(f"Clipmaker v{updater.local_version()}")
    cfg = updater.load_config()
    if cfg and cfg.get("auto"):
        try:
            res = updater.update()
            print(f"Actualizado a v{res['version']}, reiniciando…")
            sys.exit(RESTART_CODE)
        except updater.UpdateError as e:
            print(f"Sin actualizar: {e}")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Abre http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
