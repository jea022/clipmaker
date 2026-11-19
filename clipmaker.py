#!/usr/bin/env python3
"""Monta un clip horizontal en plantilla vertical con variaciones: camara/gameplay/imagen/segundo video + titulo."""
import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_LOCAL_BIN = Path(__file__).parent / "bin"
if _LOCAL_BIN.is_dir():
    os.environ["PATH"] = str(_LOCAL_BIN) + os.pathsep + os.environ.get("PATH", "")

FFMPEG_ERROR_LOG = Path(__file__).parent / "data" / "ffmpeg_errors.log"

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # subprocess.CREATE_NO_WINDOW


def _quiet_kwargs():
    """En Windows evita que cada llamada a ffmpeg/ffprobe abra su propia ventana de consola."""
    return {"creationflags": NO_WINDOW} if IS_WIN else {}


def _low_priority_kwargs():
    """Como _quiet_kwargs, y ademas el montaje corre a prioridad baja para no robarle CPU al resto del sistema."""
    if IS_WIN:
        return {"creationflags": NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)}
    return {"preexec_fn": lambda: os.nice(10)}


def log_ffmpeg_error(cmd, lines):
    """Guarda el error de ffmpeg en un log aparte; si no se puede escribir, no interrumpe el montaje."""
    try:
        FFMPEG_ERROR_LOG.parent.mkdir(exist_ok=True)
        with FFMPEG_ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {' '.join(cmd)}\n")
            f.write("\n".join(lines[-20:]) + "\n")
    except OSError:
        pass


def resolve(p):
    p = Path(p)
    return p if p.is_absolute() else Path(__file__).parent / p


def probe_size(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        text=True, **_quiet_kwargs(),
    ).strip()
    w, h = (int(v) for v in out.split(",")[:2])
    if w <= 0 or h <= 0:
        raise ValueError(f"El archivo no tiene video válido: {path}")
    return w, h


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        text=True, **_quiet_kwargs(),
    ).strip()
    return float(out)


def clean_title(text):
    keep = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D or unicodedata.category(ch) == "So":
            continue
        keep.append(ch)
    return " ".join("".join(keep).split())


def has_audio(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        text=True, **_quiet_kwargs(),
    ).strip()
    return bool(out)


def crop_box(frac, src_w, src_h):
    x, y, w, h = frac
    cw, ch = int(w * src_w), int(h * src_h)
    cx, cy = int(x * src_w), int(y * src_h)
    return cw - cw % 2, ch - ch % 2, cx, cy


def wrap_lines(draw, text, font, max_w, stroke):
    lines, cur = [], ""
    words = []
    for word in text.split():
        while draw.textlength(word, font=font) + 2 * stroke > max_w and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and draw.textlength(word[:cut], font=font) + 2 * stroke > max_w:
                cut -= 1
            words.append(word[:cut])
            word = word[cut:]
        words.append(word)
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) + 2 * stroke <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def font_path(cfg):
    fid = cfg.get("font")
    return resolve(FONTS[fid][1]) if fid in FONTS else resolve(cfg["title"]["font"])


def render_title(text, zone, cfg, out_png):
    _, _, zw, zh = zone
    t = cfg["title"]
    text = clean_title(text)
    if t.get("uppercase"):
        text = text.upper()
    img = Image.new("RGBA", (zw, zh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_w = zw - 2 * t["padding"]
    max_h = zh - 40
    stroke = t["stroke_width"]
    size = t["max_size"]
    while True:
        font = ImageFont.truetype(str(font_path(cfg)), size)
        lines = wrap_lines(draw, text, font, max_w, stroke)
        line_h = int(size * 1.15)
        fits = len(lines) * line_h <= max_h and all(
            draw.textlength(l, font=font) + 2 * stroke <= max_w for l in lines
        )
        if fits or size <= 20:
            break
        size -= 4
    y = (zh - len(lines) * line_h) // 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((zw - w) / 2, y), line, font=font, fill=t["color"],
                  stroke_width=stroke, stroke_fill=t["stroke_color"])
        y += line_h
    img.save(out_png)


def render_background(cfg, out_png):
    cw, ch = cfg["canvas"]
    if cfg.get("background_png"):
        Image.open(resolve(cfg["background_png"])).convert("RGBA").resize((cw, ch)).save(out_png)
    else:
        Image.new("RGBA", (cw, ch), cfg["background_color"]).save(out_png)


def extract_frame(clip, out_png, t=3.0):
    dur = probe_duration(clip)
    t = min(t, max(dur - 0.1, 0))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                    "-frames:v", "1", str(out_png)], check=True, **_quiet_kwargs())


def preview(clip, cfg, out_png):
    """Dibuja las cajas de recorte sobre un frame del clip para ajustar layout.json."""
    sw, sh = probe_size(clip)
    with tempfile.TemporaryDirectory() as td:
        frame = Path(td) / "f.png"
        extract_frame(clip, frame)
        img = Image.open(frame).convert("RGB")
    d = ImageDraw.Draw(img)
    for key, color in (("cam_crop", "red"), ("game_crop", "lime")):
        x, y, w, h = cfg[key]
        d.rectangle([x * sw, y * sh, (x + w) * sw, (y + h) * sh], outline=color, width=6)
    img.save(out_png)
    print(f"Preview guardado en {out_png} (rojo = camara, verde = gameplay)")


PRESETS = {
    "cam_game": {
        "label": "Cámara arriba + gameplay abajo", "needs": [], "uses_cam": True, "solid_title": True,
        "slots": [("top", "cam"), ("bottom", "clip")],
        "diagram": [("cam", 4), ("title", 1.6), ("clip", 4.4)],
    },
    "game_cam": {
        "label": "Gameplay arriba + cámara abajo", "needs": [], "uses_cam": True, "solid_title": True,
        "slots": [("top", "clip"), ("bottom", "cam")],
        "diagram": [("clip", 4), ("title", 1.6), ("cam", 4.4)],
    },
    "clip_image": {
        "label": "Video arriba + imagen abajo", "needs": ["image"], "uses_cam": False, "solid_title": True,
        "slots": [("top", "clip"), ("bottom", "image")],
        "diagram": [("clip", 4), ("title", 1.6), ("image", 4.4)],
    },
    "image_clip": {
        "label": "Imagen arriba + video abajo", "needs": ["image"], "uses_cam": False, "solid_title": True,
        "slots": [("top", "image"), ("bottom", "clip")],
        "diagram": [("image", 4), ("title", 1.6), ("clip", 4.4)],
    },
    "clip_clip": {
        "label": "Dos videos (A arriba, B abajo)", "needs": ["clip_b"], "uses_cam": False, "solid_title": True,
        "slots": [("top", "clip"), ("bottom", "clip_b")],
        "diagram": [("clip", 4), ("title", 1.6), ("clipb", 4.4)],
    },
    "clip_blur": {
        "label": "Video completo con fondo difuminado", "needs": [], "uses_cam": False, "solid_title": False,
        "clean_overlay": True,
        "zones": {"title": [0, 200, 1080, 340], "main": [0, 656, 1080, 608]},
        "slots": [("full", "blur_bg"), ("main", "clip_contain")],
        "diagram": [("blur", 1.4), ("title", 2.4), ("blur", 1), ("clip", 4.2), ("blur", 5)],
    },
}
AUDIO_CHOICES = ("a", "b", "mute")
FONTS = {
    "inter": ("Inter", "fonts/InterDisplay-Bold.otf"),
    "poppins": ("Poppins", "fonts/Poppins-ExtraBold.ttf"),
    "anton": ("Anton", "fonts/Anton-Regular.ttf"),
    "bebas": ("Bebas Neue", "fonts/BebasNeue-Regular.ttf"),
    "archivo": ("Archivo Black", "fonts/ArchivoBlack-Regular.ttf"),
    "bangers": ("Bangers", "fonts/Bangers-Regular.ttf"),
    "luckiest": ("Luckiest Guy", "fonts/LuckiestGuy-Regular.ttf"),
}
STYLES = {
    "band": {"label": "Franja"},
    "box_white": {"label": "Caja blanca", "text": "#111111", "box": "#ffffff"},
    "box_black": {"label": "Caja negra", "text": "#ffffff", "box": "#111111"},
    "box_yellow": {"label": "Caja amarilla", "text": "#111111", "box": "#ffd400"},
    "outline": {"label": "Contorno blanco", "text": "#ffffff", "box": None},
    "outline_yellow": {"label": "Contorno amarillo", "text": "#ffe600", "box": None},
}
SPLIT_RANGE = (30, 70)
OFFSET_RANGE = (-500, 500)
TITLE_HEIGHT_RANGE = (120, 560)
FONT_SIZE_RANGE = (30, 200)
MIN_BOX = 0.02


def valid_box(box):
    try:
        x, y, w, h = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if not (0 <= x <= 1 and 0 <= y <= 1 and MIN_BOX <= w <= 1 and MIN_BOX <= h <= 1):
        return None
    if x + w > 1.0001 or y + h > 1.0001:
        return None
    return [x, y, w, h]


def _number(value, lo, hi, what):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{what} no es un número")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} no es un número")
    if not lo <= v <= hi:
        raise ValueError(f"{what} debe estar entre {lo} y {hi}")
    return int(round(v))


def apply_overrides(cfg, cam=None, game=None, title_height=None, font_size=None, title_style=None, font=None,
                    split=None, offset=None, uppercase=None):
    """Devuelve una copia de cfg con recortes, alto de franja y tamano de letra personalizados."""
    cfg = copy.deepcopy(cfg)
    if cam is not None:
        box = valid_box(cam)
        if box is None:
            raise ValueError("Recuadro de cámara inválido")
        cfg["cam_crop"] = box
    if game is not None:
        box = valid_box(game)
        if box is None:
            raise ValueError("Recuadro de gameplay inválido")
        cfg["game_crop"] = box
    if title_height is not None:
        cfg["title_height"] = _number(title_height, *TITLE_HEIGHT_RANGE, "El alto de la franja del título")
    if font_size is not None:
        fs = _number(font_size, *FONT_SIZE_RANGE, "El tamaño de letra")
        cfg["title"]["max_size"] = fs
        cfg["title"]["min_size"] = min(cfg["title"].get("min_size", fs), fs)
    if title_style is not None:
        if not isinstance(title_style, str) or title_style not in STYLES:
            raise ValueError("Estilo de texto desconocido")
        cfg["title_style"] = title_style
    if font is not None:
        if not isinstance(font, str) or font not in FONTS:
            raise ValueError("Tipografía desconocida")
        cfg["font"] = font
    if split is not None:
        cfg["title_split"] = _number(split, *SPLIT_RANGE, "El reparto arriba/abajo")
    if offset is not None:
        cfg["title_offset"] = _number(offset, *OFFSET_RANGE, "El desplazamiento del texto")
    if uppercase is not None:
        if not isinstance(uppercase, bool):
            raise ValueError("Mayúsculas debe ser sí o no")
        cfg["title"]["uppercase"] = uppercase
    return cfg


def run_ffmpeg(cmd, duration, progress_cb=None):
    """Ejecuta ffmpeg informando el progreso y matandolo si se cuelga."""
    limit = max(120, duration * 30)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                             **_low_priority_kwargs())
    timer = threading.Timer(limit, proc.kill)
    timer.start()
    errors = []
    try:
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and val.lstrip("-").isdigit() and progress_cb:
                progress_cb(min(max(int(val) / 1_000_000 / duration, 0.0), 1.0))
            elif key not in ("progress", "speed", "bitrate", "total_size", "fps", "stream_0_0_q", "dup_frames",
                             "drop_frames", "frame", "out_time", "out_time_us", "out_time_ms") and line.strip():
                errors.append(line.strip())
        proc.wait()
    finally:
        timer.cancel()
    if proc.returncode != 0:
        if errors:
            print("\n".join(errors[-5:]), file=sys.stderr)
            log_ffmpeg_error(cmd, errors)
        raise subprocess.CalledProcessError(proc.returncode if proc.returncode > 0 else 124, cmd)
    if progress_cb:
        progress_cb(1.0)


def _even(v):
    v = int(v)
    return v - v % 2


def overlay_mode(cfg):
    return cfg.get("title_style", "band") != "band"


def zone_of(cfg, preset, name):
    spec_z = PRESETS[preset].get("zones", {})
    cw, ch = cfg["canvas"]
    th = cfg.get("title_height")
    if overlay_mode(cfg) and "title" not in spec_z and name in ("top", "bottom", "title"):
        split = _even(round(ch * cfg.get("title_split", 50) / 100))
        return {"top": [0, 0, cw, split], "title": [0, split, cw, 0],
                "bottom": [0, split, cw, ch - split]}[name]
    base = {
        "top": cfg.get("top_zone", cfg.get("cam_zone")),
        "bottom": cfg.get("bottom_zone", cfg.get("game_zone")),
        "title": cfg["title_zone"],
        "full": [0, 0, cw, ch],
    }
    if name in spec_z:
        z = list(spec_z[name])
        if name == "title" and th:
            cap = spec_z["main"][1] - z[1] - 16 if "main" in spec_z else TITLE_HEIGHT_RANGE[1]
            z[3] = _even(min(max(th, TITLE_HEIGHT_RANGE[0]), cap))
        return z
    if th and "title" not in spec_z and name in ("top", "bottom", "title"):
        th = _even(min(max(th, TITLE_HEIGHT_RANGE[0]), TITLE_HEIGHT_RANGE[1]))
        t0, b0 = base["top"][3], base["bottom"][3]
        top_h = _even(round((ch - th) * t0 / (t0 + b0)))
        if name == "top":
            return [0, 0, cw, top_h]
        if name == "title":
            return [0, top_h, cw, th]
        return [0, top_h + th, cw, ch - top_h - th]
    return list(base[name])


def render_title_overlay(text, cfg, out_png):
    """Titulo superpuesto: caja redondeada o texto con contorno, del tamano justo. Devuelve (ancho, alto)."""
    st = STYLES[cfg["title_style"]]
    t = cfg["title"]
    text = clean_title(text)
    if t.get("uppercase"):
        text = text.upper()
    if not text:
        Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(out_png)
        return 2, 2
    cw, _ = cfg["canvas"]
    boxed = st.get("box")
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    fpath = str(font_path(cfg))
    size, max_w, max_h = t["max_size"], int(cw * 0.92), 640
    while True:
        font = ImageFont.truetype(fpath, size)
        padx, pady = (round(size * 0.5), round(size * 0.3)) if boxed else (round(size * 0.12), round(size * 0.1))
        stroke = 0 if boxed else max(3, round(size * 0.09))
        lines = wrap_lines(probe, text, font, max_w - 2 * padx - 2 * stroke, stroke)
        lh = int(size * 1.2)
        w = int(max(probe.textlength(l, font=font) for l in lines)) + 2 * padx + 2 * stroke
        h = len(lines) * lh + 2 * pady
        if (w <= max_w and h <= max_h) or size <= 20:
            break
        size -= 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if boxed:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=max(10, round(size * 0.28)), fill=boxed)
    for i, line in enumerate(lines):
        d.text((w / 2, pady + i * lh + lh / 2), line, font=font, fill=st["text"], anchor="mm",
               stroke_width=stroke, stroke_fill="#000000")
    img.save(out_png)
    return w, h


def title_position(cfg, preset, tw, th):
    """Esquina superior izquierda del titulo superpuesto: centrado en la union (o en la franja del titulo)."""
    cw, ch = cfg["canvas"]
    z = zone_of(cfg, preset, "title")
    anchor = z[1] + (z[3] / 2 if "title" in PRESETS[preset].get("zones", {}) else 0)
    y = int(round(anchor + cfg.get("title_offset", 0) - th / 2))
    return (cw - tw) // 2, min(max(y, 0), ch - th)


def render_lines(cfg, title_z, out_png):
    cw, ch = cfg["canvas"]
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = tuple(int(cfg["accent_color"][i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    for y in (title_z[1] - 3, title_z[1] + title_z[3] - 3):
        d.rectangle([0, y, cw, y + 6], fill=color)
    img.save(out_png)


def normalize_image(src, out_png, max_side=4096):
    from PIL import ImageOps
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    img.thumbnail((max_side, max_side))
    img.save(out_png)


def cover(label_in, w, h, label_out):
    return (f"[{label_in}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1[{label_out}]")


def build(clip, title, cfg, out_path, no_cam=False, preset="cam_game", clip_b=None, image=None, audio="a",
          progress_cb=None, still=False):
    if preset not in PRESETS:
        raise ValueError(f"Variación desconocida: {preset} (opciones: {', '.join(PRESETS)})")
    spec = PRESETS[preset]
    if audio not in AUDIO_CHOICES:
        raise ValueError(f"audio debe ser uno de {', '.join(AUDIO_CHOICES)}")
    if "image" in spec["needs"] and not image:
        raise ValueError("Esta variación necesita una imagen (--image)")
    if "clip_b" in spec["needs"] and not clip_b:
        raise ValueError("Esta variación necesita un segundo video (--clip-b)")
    if audio == "b" and not clip_b:
        raise ValueError("audio=b necesita un segundo video (--clip-b)")

    if clip_b:
        try:
            probe_size(clip_b)
        except (subprocess.CalledProcessError, ValueError):
            raise ValueError(f"No pude leer el segundo video: {clip_b}")
    sw, sh = probe_size(clip)
    title_z = zone_of(cfg, preset, "title")
    slots = [(z, k) for z, k in spec["slots"] if not (k == "cam" and no_cam)]
    uses_a = [k for _, k in slots if k in ("cam", "clip", "clip_contain", "blur_bg")]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bg, title_png = td / "bg.png", td / "title.png"
        render_background(cfg, bg)
        if overlay_mode(cfg):
            tw, th = render_title_overlay(title, cfg, title_png)
            title_pos = title_position(cfg, preset, tw, th)
        else:
            render_title(title, title_z, cfg, title_png)
            title_pos = (title_z[0], title_z[1])

        dur_a = probe_duration(clip)
        seek = ["-ss", f"{min(1.0, dur_a * 0.4):.2f}"] if still else []
        inputs, n = [*seek, "-i", str(clip)], 1
        idx = {}
        if "clip_b" in spec["needs"] or audio == "b":
            inputs += ["-stream_loop", "-1", "-i", str(clip_b)]
            idx["clip_b"], n = n, n + 1
        if "image" in spec["needs"]:
            img_png = td / "image.png"
            try:
                normalize_image(image, img_png)
            except Exception:
                raise ValueError(f"No pude leer la imagen: {image}")
            inputs += ["-loop", "1", "-framerate", "30", "-i", str(img_png)]
            idx["image"], n = n, n + 1
        inputs += ["-loop", "1", "-i", str(bg)]
        idx["bg"], n = n, n + 1
        inputs += ["-loop", "1", "-i", str(title_png)]
        idx["title"], n = n, n + 1
        accent, clean = cfg.get("accent_color"), cfg.get("overlay_clean_png")
        dyn_lines = bool(accent and clean and not spec.get("clean_overlay") and not overlay_mode(cfg))
        if dyn_lines:
            lines_png = td / "lines.png"
            render_lines(cfg, title_z, lines_png)
            inputs += ["-loop", "1", "-i", str(lines_png)]
            idx["lines"], n = n, n + 1
        overlay = clean if (spec.get("clean_overlay") or dyn_lines or overlay_mode(cfg)) else None
        overlay = overlay or cfg.get("overlay_png")
        if overlay:
            inputs += ["-loop", "1", "-i", str(resolve(overlay))]
            idx["overlay"], n = n, n + 1

        f = []
        if uses_a:
            outs = "".join(f"[a{i}]" for i in range(len(uses_a)))
            f.append(f"[0:v]split={len(uses_a)}{outs}")
        f.append(f"[{idx['bg']}:v]format=rgba[base]")
        last, a_i = "base", 0
        gw, gh, gx, gy = crop_box(cfg["game_crop"], sw, sh)
        for i, (zname, kind) in enumerate(slots):
            zx, zy, zw, zh = zone_of(cfg, preset, zname)
            lab = f"s{i}"
            if kind == "cam":
                kw, kh, kx, ky = crop_box(cfg["cam_crop"], sw, sh)
                f.append(f"[a{a_i}]crop={kw}:{kh}:{kx}:{ky}[c{i}]")
                f.append(cover(f"c{i}", zw, zh, lab)); a_i += 1
                pos = f"{zx}:{zy}"
            elif kind == "clip":
                f.append(f"[a{a_i}]crop={gw}:{gh}:{gx}:{gy}[c{i}]")
                f.append(cover(f"c{i}", zw, zh, lab)); a_i += 1
                pos = f"{zx}:{zy}"
            elif kind == "clip_contain":
                f.append(f"[a{a_i}]crop={gw}:{gh}:{gx}:{gy},scale={zw}:{zh}:"
                         f"force_original_aspect_ratio=decrease,setsar=1[{lab}]"); a_i += 1
                pos = f"{zx}+({zw}-w)/2:{zy}+({zh}-h)/2"
            elif kind == "blur_bg":
                cw, ch = cfg["canvas"]
                f.append(f"[a{a_i}]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                         f"boxblur=10:2,scale={zw}:{zh},eq=brightness=-0.18,setsar=1[{lab}]"); a_i += 1
                pos = f"{zx}:{zy}"
            elif kind == "clip_b":
                f.append(cover(f"{idx['clip_b']}:v", zw, zh, lab))
                pos = f"{zx}:{zy}"
            elif kind == "image":
                f.append(cover(f"{idx['image']}:v", zw, zh, f"i{i}"))
                f.append(f"[i{i}]format=rgba[{lab}]")
                pos = f"{zx}:{zy}"
            else:
                raise ValueError(f"slot desconocido: {kind}")
            f.append(f"[{last}][{lab}]overlay={pos}[o{i}]")
            last = f"o{i}"
        if "lines" in idx:
            f.append(f"[{last}][{idx['lines']}:v]overlay=0:0[ln]")
            last = "ln"
        f.append(f"[{last}][{idx['title']}:v]overlay={title_pos[0]}:{title_pos[1]}[t]")
        last = "t"
        if "overlay" in idx:
            f.append(f"[{last}][{idx['overlay']}:v]overlay=0:0[ov]")
            last = "ov"
        f.append(f"[{last}]format=yuv420p[out]")

        cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *inputs,
               "-filter_complex", ";".join(f), "-map", "[out]"]
        if still:
            cmd += ["-frames:v", "1", str(out_path)]
            run_ffmpeg(cmd, 1.0, None)
            return
        if audio == "a" and has_audio(clip):
            cmd += ["-map", "0:a"]
        elif audio == "b" and has_audio(clip_b):
            cmd += ["-map", f"{idx['clip_b']}:a"]
        if "-map" in cmd[cmd.index("[out]") + 1:]:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30",
                "-t", f"{dur_a:.3f}", "-movflags", "+faststart", str(out_path)]
        run_ffmpeg(cmd, dur_a, progress_cb)
    print(f"Listo: {out_path}")


def run_batch(folder, cfg, no_cam, **opts):
    exts = {".mp4", ".mov", ".mkv", ".webm"}
    clips = sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)
    if not clips:
        sys.exit(f"No hay videos en {folder}")
    out_dir = folder / "listos"
    out_dir.mkdir(exist_ok=True)
    failed = []
    for clip in clips:
        txt = clip.with_suffix(".txt")
        title = txt.read_text(encoding="utf-8").strip() if txt.is_file() else clip.stem
        try:
            build(clip, title, cfg, out_dir / f"{clip.stem}.mp4", no_cam, **opts)
        except (subprocess.CalledProcessError, ValueError):
            failed.append(clip.name)
    print(f"\n{len(clips) - len(failed)}/{len(clips)} listos en {out_dir}")
    if failed:
        sys.exit(f"Fallaron: {', '.join(failed)}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("clip", nargs="?", help="clip de entrada, o carpeta con --batch")
    p.add_argument("title", nargs="?", default="")
    p.add_argument("--batch", action="store_true",
                   help="procesa todos los videos de la carpeta; el titulo sale de <nombre>.txt")
    p.add_argument("-o", "--output")
    p.add_argument("--layout", default=str(Path(__file__).with_name("layout.json")))
    p.add_argument("--cam", help="override recorte camara: x,y,w,h en fracciones 0-1")
    p.add_argument("--no-cam", action="store_true", help="solo gameplay, sin camara")
    p.add_argument("--preview", action="store_true", help="guarda un frame con las cajas de recorte")
    p.add_argument("--preset", default="cam_game", choices=sorted(PRESETS), help="variación de composición")
    p.add_argument("--clip-b", help="segundo video (variación clip_clip)")
    p.add_argument("--image", help="imagen (variaciones clip_image / image_clip)")
    p.add_argument("--audio", default="a", choices=AUDIO_CHOICES, help="audio: del clip A, del B o sin audio")
    p.add_argument("--game", help="recorte del gameplay: x,y,w,h en fracciones 0-1")
    p.add_argument("--title-height", type=float, help=f"alto de la franja del título en px {TITLE_HEIGHT_RANGE}")
    p.add_argument("--font-size", type=float, help=f"tamaño de letra máximo del título {FONT_SIZE_RANGE}")
    p.add_argument("--title-style", choices=sorted(STYLES), help="estilo del texto: franja, cajas o contorno")
    p.add_argument("--font", choices=sorted(FONTS), help="tipografía del título")
    p.add_argument("--split", type=float, help=f"% de alto de la parte de arriba (modo superpuesto) {SPLIT_RANGE}")
    p.add_argument("--offset", type=float, help=f"subir/bajar el texto superpuesto en px {OFFSET_RANGE}")
    p.add_argument("--lowercase", action="store_true", help="respeta mayúsculas/minúsculas tal como las escribes")
    p.add_argument("--list-presets", action="store_true", help="muestra las variaciones disponibles")
    a = p.parse_args()

    if a.list_presets:
        for pid, spec in PRESETS.items():
            needs = f"  (necesita: {', '.join(spec['needs'])})" if spec["needs"] else ""
            print(f"{pid:12s} {spec['label']}{needs}")
        print("\nEstilos de texto (--title-style):", ", ".join(f"{k} ({v['label']})" for k, v in STYLES.items()))
        print("Tipografías (--font):", ", ".join(f"{k} ({v[0]})" for k, v in FONTS.items()))
        return
    if not a.clip:
        p.error("falta el clip")

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"No encuentro {tool}. Instala ffmpeg y vuelve a intentar.")
    if a.batch:
        if not Path(a.clip).is_dir():
            sys.exit(f"No existe la carpeta: {a.clip}")
    elif not Path(a.clip).is_file():
        sys.exit(f"No existe el clip: {a.clip}")
    if not Path(a.layout).is_file():
        sys.exit(f"No existe el layout: {a.layout}")
    for flag, path in (("--clip-b", a.clip_b), ("--image", a.image)):
        if path and not Path(path).is_file():
            sys.exit(f"No existe el archivo de {flag}: {path}")
    cfg = json.loads(Path(a.layout).read_text())
    def parse_box(text, flag):
        try:
            return [float(v) for v in text.split(",")]
        except ValueError:
            sys.exit(f"{flag} debe ser x,y,w,h entre 0 y 1 (ej. 0.7,0.02,0.28,0.32)")

    try:
        cfg = apply_overrides(cfg, cam=parse_box(a.cam, "--cam") if a.cam else None,
                              game=parse_box(a.game, "--game") if a.game else None,
                              title_height=a.title_height, font_size=a.font_size, title_style=a.title_style,
                              font=a.font, split=a.split, offset=a.offset, uppercase=False if a.lowercase else None)
    except ValueError as e:
        sys.exit(str(e))

    if a.batch:
        run_batch(Path(a.clip), cfg, a.no_cam, preset=a.preset, clip_b=a.clip_b, image=a.image, audio=a.audio)
        return
    clip = Path(a.clip)
    if a.preview:
        preview(clip, cfg, clip.with_suffix(".preview.png"))
        return
    if not a.title:
        sys.exit("Falta el titulo.")
    out = Path(a.output) if a.output else clip.with_name(clip.stem + "_vertical.mp4")
    def show(frac):
        print(f"\r  montando… {int(frac * 100):3d}%", end="" if frac < 1 else "\n", flush=True)

    try:
        build(clip, a.title, cfg, out, a.no_cam, a.preset, a.clip_b, a.image, a.audio, progress_cb=show)
    except ValueError as e:
        sys.exit(str(e))
    except subprocess.CalledProcessError:
        sys.exit("ffmpeg no pudo montar el video (revisa que los archivos sean válidos).")


if __name__ == "__main__":
    main()
