#!/usr/bin/env python3
"""Pruebas de humo: genera fuentes sinteticas variadas y valida la salida de clipmaker."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
CM = HERE / "clipmaker.py"
sys.path.insert(0, str(HERE))
import clipmaker  # noqa: E402


def sh(*cmd, check=True):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=check)


def make_src(path, size="1920x1080", fps=30, dur=3, audio=True, vcodec="libx264", pix="yuv420p", freq=440):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}"]
    cmd += ["-c:v", vcodec, "-pix_fmt", pix]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    sh(*cmd, path)


def make_assets(td):
    a = {}
    Image.new("RGB", (1600, 900), (30, 120, 60)).save(td / "img.jpg")
    png = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(png).ellipse([50, 50, 850, 850], fill=(255, 200, 0, 255))
    png.save(td / "alpha.png")
    Image.new("RGB", (500, 1200), (120, 30, 90)).save(td / "tall.png")
    Image.new("RGB", (10, 10), (200, 0, 0)).save(td / "tiny.png")
    Image.new("RGB", (6000, 4000), (0, 90, 160)).save(td / "huge.jpg")
    rot = Image.new("RGB", (800, 400), (10, 150, 150))
    ex = rot.getexif()
    ex[274] = 6  # orientacion EXIF: girar 90
    rot.save(td / "exif.jpg", exif=ex)
    Image.new("RGB", (400, 300), (90, 90, 200)).save(td / "anim.gif")
    make_src(td / "b_short.mp4", size="1280x720", fps=24, dur=1, freq=880)
    make_src(td / "b_long.mp4", size="1280x720", fps=24, dur=6, freq=880)
    make_src(td / "b_noaudio.mp4", size="1280x720", fps=24, dur=2, audio=False)
    make_src(td / "b_vertical.mp4", size="720x1280", fps=30, dur=2, freq=660)
    for k in ("img.jpg", "alpha.png", "tall.png", "tiny.png", "huge.jpg", "exif.jpg", "anim.gif",
              "b_short.mp4", "b_long.mp4", "b_noaudio.mp4", "b_vertical.mp4"):
        a[k.split(".")[0]] = str(td / k)
    return a


def case(name, src=None, title="Titulo de prueba", args=(), audio=True):
    return dict(name=name, src=src or {}, title=title, args=list(args), audio=audio)


CASES = [
    case("base_16x9"),
    case("sin_audio", dict(audio=False), audio=False),
    case("vertical_src", dict(size="1080x1920")),
    case("cuadrado", dict(size="1000x1000")),
    case("4k", dict(size="3840x2160")),
    case("res_impar", dict(size="1366x768")),
    case("fps60", dict(fps=60)),
    case("fps_raro", dict(fps=23)),
    case("muy_corto", dict(dur=1)),
    case("hevc", dict(vcodec="libx265")),
    case("titulo_largo", title="Esto es un titulo absurdamente largo que sigue y sigue para ver si el texto se achica y se parte en varias lineas sin salirse de la zona"),
    case("titulo_palabra_larga", title="A" * 56),
    case("titulo_caracteres", title="¡Ñandú! ¿Qué pasó? \"comillas\" 'simples' & ampersand %50 :) 😂"),
    case("titulo_solo_emoji", title="😂😂😂"),
    case("titulo_con_barra", title="A/B \\ C; D, E: F"),
    case("no_cam", args=["--no-cam"]),
    case("cam_override", args=["--cam", "0.0,0.65,0.3,0.33"]),
    # variaciones
    case("v_game_cam", args=["--preset", "game_cam"]),
    case("v_clip_image_jpg", args=["--preset", "clip_image", "--image", "{img}"]),
    case("v_clip_image_alpha", args=["--preset", "clip_image", "--image", "{alpha}"]),
    case("v_clip_image_tall", args=["--preset", "clip_image", "--image", "{tall}"]),
    case("v_clip_image_tiny", args=["--preset", "clip_image", "--image", "{tiny}"]),
    case("v_clip_image_huge", args=["--preset", "clip_image", "--image", "{huge}"]),
    case("v_clip_image_exif", args=["--preset", "clip_image", "--image", "{exif}"]),
    case("v_clip_image_gif", args=["--preset", "clip_image", "--image", "{anim}"]),
    case("v_image_clip", args=["--preset", "image_clip", "--image", "{img}"]),
    case("v_image_clip_sin_audio", dict(audio=False), args=["--preset", "image_clip", "--image", "{img}"], audio=False),
    case("v_clip_clip_b_corto", args=["--preset", "clip_clip", "--clip-b", "{b_short}"]),
    case("v_clip_clip_b_largo", args=["--preset", "clip_clip", "--clip-b", "{b_long}"]),
    case("v_clip_clip_b_vertical", args=["--preset", "clip_clip", "--clip-b", "{b_vertical}"]),
    case("v_clip_clip_audio_b", dict(audio=False), args=["--preset", "clip_clip", "--clip-b", "{b_short}", "--audio", "b"], audio=True),
    case("v_clip_clip_audio_b_sin_audio_b", args=["--preset", "clip_clip", "--clip-b", "{b_noaudio}", "--audio", "b"], audio=False),
    case("v_clip_clip_mute", args=["--preset", "clip_clip", "--clip-b", "{b_short}", "--audio", "mute"], audio=False),
    case("v_blur", args=["--preset", "clip_blur"]),
    case("v_blur_vertical", dict(size="1080x1920"), args=["--preset", "clip_blur"]),
    case("v_blur_sin_audio", dict(audio=False), args=["--preset", "clip_blur"], audio=False),
    case("v_blur_titulo_largo", title="Titulo larguisimo para ver como se comporta la variacion con fondo difuminado cuando hay mucho texto que partir", args=["--preset", "clip_blur"]),
    case("v_marca_wganga", args=["--layout", "templates/wganga.json", "--preset", "clip_image", "--image", "{img}"]),
    case("v_marca_blur", args=["--layout", "templates/gtahispa.json", "--preset", "clip_blur"]),
]

ERROR_CASES = [
    ("err_falta_imagen", ["--preset", "clip_image"], "imagen"),
    ("err_falta_clip_b", ["--preset", "clip_clip"], "segundo video"),
    ("err_audio_b_sin_b", ["--audio", "b"], "segundo video"),
    ("err_imagen_inexistente", ["--preset", "clip_image", "--image", "/no/existe.png"], "No existe"),
    ("err_imagen_basura", ["--preset", "clip_image", "--image", "{garbage}"], "No pude leer la imagen"),
    ("err_clip_b_basura", ["--preset", "clip_clip", "--clip-b", "{garbage}"], "No pude leer el segundo video"),
    ("err_preset_malo", ["--preset", "no_existe"], "invalid choice"),
]


def probe(path):
    out = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration,pix_fmt",
             "-of", "json", path).stdout
    streams = json.loads(out)["streams"]
    return (next(s for s in streams if s["codec_type"] == "video"),
            next((s for s in streams if s["codec_type"] == "audio"), None))


def title_edge_touched(out, layout_path, preset):
    layout = json.loads(Path(layout_path).read_text())
    x, y, w, h = clipmaker.zone_of(layout, preset, "title")
    bg = tuple(int(layout["background_color"][i:i + 2], 16) for i in (1, 3, 5))
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "f.png"
        sh("ffmpeg", "-y", "-v", "error", "-ss", "0.3", "-i", out, "-frames:v", "1", png)
        img = Image.open(png).convert("RGB").crop((x, y, x + w, y + h))
    for col in list(range(0, 6)) + list(range(w - 6, w)):
        for row in range(h):
            p = img.getpixel((col, row))
            if sum(abs(p[i] - bg[i]) for i in range(3)) > 40:
                return True
    return False


def option(args, flag, default):
    return args[args.index(flag) + 1] if flag in args else default


def run_case(c, td, assets):
    name, src_kwargs = c["name"], c["src"]
    src, out = td / f"{name}.mp4", td / f"{name}_v.mp4"
    make_src(src, **src_kwargs)
    args = [a.format(**assets) if "{" in a else a for a in c["args"]]
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, str(CM), str(src), c["title"], "-o", str(out), *args],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT 120s (colgado)"
    dt = time.time() - t0
    if r.returncode != 0 or not out.exists():
        tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.stdout[-200:]
        return False, f"fallo ({r.returncode}): {tail}"
    v, a = probe(out)
    problems = []
    if (v["width"], v["height"]) != (1080, 1920):
        problems.append(f"tamano {v['width']}x{v['height']}")
    if v["pix_fmt"] != "yuv420p":
        problems.append(f"pix_fmt {v['pix_fmt']}")
    if c["audio"] and a is None:
        problems.append("perdio audio")
    if not c["audio"] and a is not None:
        problems.append("audio inesperado")
    layout_path = option(args, "--layout", str(HERE / "layout.json"))
    preset = option(args, "--preset", "cam_game")
    if clipmaker.PRESETS[preset]["solid_title"] and "templates" not in layout_path \
            and title_edge_touched(out, layout_path, preset):
        problems.append("titulo se sale de los bordes")
    exp = src_kwargs.get("dur", 3)
    got = float(v.get("duration", 0))
    if abs(got - exp) > 0.4:
        problems.append(f"duracion {got:.2f}s vs {exp}s")
    return (not problems), (", ".join(problems) or f"ok {dt:.1f}s")


def run_error_case(name, args, expect, td, assets):
    src = td / "err_src.mp4"
    if not src.exists():
        make_src(src)
    args = [a.format(**assets) if "{" in a else a for a in args]
    try:
        r = subprocess.run([sys.executable, str(CM), str(src), "x", "-o", str(td / "err_out.mp4"), *args],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT 60s (colgado)"
    text = r.stdout + r.stderr
    if r.returncode == 0:
        return False, "debia fallar y salio bien"
    if "Traceback" in text:
        return False, "error sin manejar (traceback)"
    return (expect in text), (f"mensaje esperado '{expect}' no aparece: {text.strip()[-100:]}" if expect not in text else "ok")


def main():
    only = sys.argv[1:]
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        assets = make_assets(td)
        (td / "garbage.bin").write_text("esto no es un archivo multimedia")
        assets["garbage"] = str(td / "garbage.bin")
        for c in CASES:
            if only and c["name"] not in only:
                continue
            ok, msg = run_case(c, td, assets)
            fails += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {c['name']:34s} {msg}")
        for name, args, expect in ERROR_CASES:
            if only and name not in only:
                continue
            ok, msg = run_error_case(name, args, expect, td, assets)
            fails += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {msg}")
    print(f"\n{fails} fallos")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
