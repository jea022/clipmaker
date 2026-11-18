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
    # controles: franja, letra y recorte de gameplay
    case("ctl_franja_160_letra_60", args=["--title-height", "160", "--font-size", "60"]),
    case("ctl_franja_560_letra_200", args=["--title-height", "560", "--font-size", "200"]),
    case("ctl_franja_120_letra_30", args=["--title-height", "120", "--font-size", "30"]),
    case("ctl_titulo_largo_franja_120", title="Titulo muy largo que no cabe en una franja tan baja y debe achicarse solo para entrar completo", args=["--title-height", "120"]),
    case("ctl_titulo_largo_letra_200", title="Otro titulo largo con letra enorme que tiene que encoger para caber", args=["--font-size", "200"]),
    case("ctl_game_recortado", args=["--game", "0,0.3,0.7,0.7"]),
    case("ctl_game_recortado_clip_image", args=["--preset", "clip_image", "--image", "{img}", "--game", "0.1,0.1,0.5,0.5"]),
    case("ctl_game_en_blur", args=["--preset", "clip_blur", "--game", "0,0,0.6,1", "--title-height", "420", "--font-size", "120"]),
    case("ctl_game_en_game_cam", args=["--preset", "game_cam", "--game", "0,0,1,0.6", "--cam", "0.6,0.0,0.4,0.4", "--title-height", "200"]),
    case("ctl_todo_junto_clip_clip", args=["--preset", "clip_clip", "--clip-b", "{b_short}", "--title-height", "480", "--font-size", "150", "--game", "0,0,0.8,0.8"]),
    case("ctl_marca_franja", args=["--layout", "templates/wganga.json", "--title-height", "200", "--font-size", "70"]),
    case("ctl_marca_franja_grande", args=["--layout", "templates/gtahispa.json", "--title-height", "520"]),
    # estilos de texto, tipografias, reparto y posicion
    *[case(f"txt_estilo_{s}", args=["--title-style", s, "--font-size", "56" if s.startswith("box") else "84"])
      for s in ("box_white", "box_black", "box_yellow", "outline", "outline_yellow")],
    *[case(f"txt_fuente_{f}", args=["--title-style", "box_white", "--font", f, "--font-size", "60"])
      for f in ("inter", "poppins", "anton", "bebas", "archivo", "bangers", "luckiest")],
    case("txt_fuente_en_franja", args=["--font", "bangers"]),
    case("txt_split_30", args=["--title-style", "box_white", "--split", "30", "--font-size", "56"]),
    case("txt_split_70", args=["--title-style", "box_white", "--split", "70", "--font-size", "56"]),
    case("txt_offset_max", args=["--title-style", "box_black", "--offset", "500", "--font-size", "56"]),
    case("txt_offset_min", args=["--title-style", "box_black", "--offset", "-500", "--font-size", "56"]),
    case("txt_minusculas", title="Me after the first 5 minutes of GTA 6", args=["--title-style", "box_white", "--lowercase", "--font-size", "56"]),
    case("txt_acentos", title="¡Ñandú! ¿Qué pasó? Canción única", args=["--title-style", "box_white", "--font", "luckiest"]),
    case("txt_titulo_largo_caja", title="Este es un titulo larguisimo para comprobar que la caja se parte en varias lineas sin salirse de la pantalla ni tapar todo el video", args=["--title-style", "box_white", "--font-size", "90"]),
    case("txt_palabra_larga_contorno", title="A" * 60, args=["--title-style", "outline", "--font-size", "100"]),
    case("txt_solo_emoji_caja", title="😂😂", args=["--title-style", "box_white"]),
    case("txt_image_clip", args=["--preset", "image_clip", "--image", "{img}", "--title-style", "box_yellow", "--split", "45"]),
    case("txt_clip_clip", args=["--preset", "clip_clip", "--clip-b", "{b_short}", "--title-style", "outline_yellow", "--font", "anton", "--audio", "b"]),
    case("txt_blur_caja", args=["--preset", "clip_blur", "--title-style", "box_white", "--offset", "-100"]),
    case("txt_game_cam", args=["--preset", "game_cam", "--title-style", "box_white", "--cam", "0.6,0.0,0.4,0.4"]),
    case("txt_marca", args=["--layout", "templates/wganga.json", "--title-style", "box_white", "--font", "poppins"]),
    case("txt_marca_blur", args=["--layout", "templates/gtahispa.json", "--preset", "clip_blur", "--title-style", "outline"]),
    case("txt_ignora_altura_franja", args=["--title-style", "box_white", "--title-height", "500"]),
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
    ("err_estilo_malo", ["--title-style", "neon"], "invalid choice"),
    ("err_fuente_mala", ["--font", "comic"], "invalid choice"),
    ("err_split_bajo", ["--split", "10"], "entre 30 y 70"),
    ("err_split_alto", ["--split", "90"], "entre 30 y 70"),
    ("err_split_texto", ["--split", "abc"], "invalid float"),
    ("err_offset_fuera", ["--offset", "9999"], "entre -500 y 500"),
    ("err_franja_baja", ["--title-height", "50"], "entre 120 y 560"),
    ("err_franja_alta", ["--title-height", "9999"], "entre 120 y 560"),
    ("err_franja_texto", ["--title-height", "abc"], "invalid float"),
    ("err_letra_baja", ["--font-size", "5"], "entre 30 y 200"),
    ("err_letra_alta", ["--font-size", "999"], "entre 30 y 200"),
    ("err_game_fuera", ["--game", "2,2,2,2"], "Recuadro de gameplay inválido"),
    ("err_game_basura", ["--game", "x"], "x,y,w,h"),
    ("err_game_tamano_cero", ["--game", "0.1,0.1,0,0"], "Recuadro de gameplay inválido"),
]


def probe(path):
    out = sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration,pix_fmt",
             "-of", "json", path).stdout
    streams = json.loads(out)["streams"]
    return (next(s for s in streams if s["codec_type"] == "video"),
            next((s for s in streams if s["codec_type"] == "audio"), None))


def title_edge_touched(out, layout_path, preset, title_height=None):
    layout = json.loads(Path(layout_path).read_text())
    if title_height:
        layout = clipmaker.apply_overrides(layout, title_height=title_height)
    x, y, w, h = clipmaker.zone_of(layout, preset, "title")
    bg = tuple(int(layout["background_color"][i:i + 2], 16) for i in (1, 3, 5))
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "f.png"
        sh("ffmpeg", "-y", "-v", "error", "-ss", "0.3", "-i", out, "-frames:v", "1", png)
        img = Image.open(png).convert("RGB").crop((x, y, x + w, y + h))
    def texty(px):
        return min(px) >= 215

    for col in list(range(0, 6)) + list(range(w - 6, w)):
        if any(texty(img.getpixel((col, row))) for row in range(h)):
            return True
    for row in list(range(0, 3)) + list(range(h - 3, h)):
        if any(texty(img.getpixel((col, row))) for col in range(w)):
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
            and option(args, "--title-style", "band") == "band" \
            and title_edge_touched(out, layout_path, preset, float(option(args, "--title-height", 0)) or None):
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


def effect_tests(td, assets):
    """Comprueba que los controles cambian de verdad lo que se ve (no solo que no den error)."""
    results = []
    layout = json.loads((HERE / "layout.json").read_text())
    src = td / "effect_src.mp4"
    make_src(src)

    def still(**ov):
        cfg = clipmaker.apply_overrides(layout, **ov) if ov else layout
        out = td / f"still_{abs(hash(json.dumps(ov, sort_keys=True)))}.png"
        clipmaker.build(str(src), "HOLA", cfg, out, still=True)
        return Image.open(out).convert("RGB")

    bg = tuple(int(layout["background_color"][i:i + 2], 16) for i in (1, 3, 5))

    def title_pixels(img, y0, y1):
        return sum(1 for y in range(y0, y1, 2) for x in range(0, 1080, 2) if min(img.getpixel((x, y))) >= 235)

    small, big = still(font_size=40), still(font_size=160)
    a, b = title_pixels(small, 760, 1080), title_pixels(big, 760, 1080)
    results.append(("efecto: letra grande tiene mas pixeles de texto que letra chica", b > a * 3, f"{a} vs {b}"))

    low, tall = still(title_height=160), still(title_height=480)
    zones = lambda T: clipmaker.zone_of(clipmaker.apply_overrides(layout, title_height=T), "cam_game", "title")
    (_, y_low, _, h_low), (_, y_tall, _, h_tall) = zones(160), zones(480)
    near = lambda p, q, tol=12: sum(abs(p[i] - q[i]) for i in range(3)) <= tol
    solid = lambda img, y: near(img.getpixel((5, y)), bg)
    results.append(("efecto: franja alta ocupa mas alto que la baja", h_tall > h_low * 2, f"{h_low} vs {h_tall}"))
    results.append(("efecto: la franja baja deja ver la camara donde la alta ya es franja",
                    not solid(low, y_tall + 10) and solid(tall, y_tall + 10), f"y={y_tall + 10}"))
    results.append(("efecto: franja pegada a camara y gameplay (sin huecos)",
                    solid(tall, y_tall) and not solid(tall, y_tall - 3) and not solid(tall, y_tall + h_tall + 3), ""))
    results.append(("efecto: gameplay recortado cambia la imagen", still(game=[0, 0, 0.5, 0.5]).tobytes() != still().tobytes(), ""))
    results.append(("efecto: cam distinta cambia la imagen", still(cam=[0.0, 0.5, 0.3, 0.3]).tobytes() != still().tobytes(), ""))
    wide = still(font_size=200)
    results.append(("efecto: texto no toca los bordes con letra maxima", not any(min(wide.getpixel((x, y))) >= 235 for x in list(range(0, 4)) + list(range(1076, 1080)) for y in range(760, 1080)), ""))

    # fotograma unico: tamano y velocidad razonables
    import time as _t
    t0 = _t.time()
    im = still(title_height=300)
    results.append(("still devuelve 1080x1920 en menos de 10 s", im.size == (1080, 1920) and _t.time() - t0 < 10, f"{_t.time() - t0:.1f}s"))
    return results


def overlay_tests(td):
    """Mide el modo superpuesto: videos pegados, caja centrada en la union, tipografias distintas."""
    results = []
    flat = td / "flat.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
       "color=c=0x3050a0:s=1920x1080:r=30:d=2,drawbox=x=1344:y=22:w=538:h=345:color=0xff8c00:t=fill",
       "-pix_fmt", "yuv420p", flat)
    layout = json.loads((HERE / "layout.json").read_text())
    bg = tuple(int(layout["background_color"][i:i + 2], 16) for i in (1, 3, 5))
    near = lambda p, q, tol=40: sum(abs(p[i] - q[i]) for i in range(3)) <= tol
    ORANGE, BLUE = (255, 140, 0), (0x30, 0x50, 0xa0)

    def still(title="HOLA", preset="cam_game", **ov):
        cfg = clipmaker.apply_overrides(layout, **ov) if ov else layout
        out = td / f"o_{abs(hash((title, preset, json.dumps(ov, sort_keys=True))))}.png"
        clipmaker.build(str(flat), title, cfg, out, preset=preset, still=True)
        return Image.open(out).convert("RGB")

    def white_bbox(img, y0=0, y1=1920):
        pts = [(x, y) for y in range(y0, y1, 2) for x in range(0, 1080, 2) if min(img.getpixel((x, y))) >= 240]
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    band, over = still(), still(title_style="box_white", font_size=56)
    results.append(("superpuesto: con franja hay fondo en el medio", near(band.getpixel((5, 900)), bg, 30), ""))
    results.append(("superpuesto: sin franja, arriba y abajo pegados en la union",
                    near(over.getpixel((5, 955)), ORANGE) and near(over.getpixel((5, 965)), BLUE), f"{over.getpixel((5, 955))} / {over.getpixel((5, 965))}"))
    bb = white_bbox(over, 700, 1200)
    cx, cy = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) if bb else (0, 0)
    results.append(("superpuesto: caja blanca centrada en horizontal y sobre la union", bb is not None and abs(cx - 540) <= 4 and abs(cy - 960) <= 6, f"centro=({cx:.0f},{cy:.0f})"))

    low = white_bbox(still(title_style="box_white", font_size=56, offset=100), 700, 1400)
    results.append(("superpuesto: offset +100 baja el texto 100 px", low is not None and abs((low[1] + low[3]) / 2 - 1060) <= 6, f"{low}"))
    s30 = white_bbox(still(title_style="box_white", font_size=56, split=30), 300, 1000)
    results.append(("superpuesto: reparto 30% sube la union a y=576", s30 is not None and abs((s30[1] + s30[3]) / 2 - 576) <= 6, f"{s30}"))
    s30img = still(title_style="box_white", font_size=56, split=30)
    results.append(("superpuesto: con reparto 30% el video de arriba termina en y=576",
                    near(s30img.getpixel((5, 570)), ORANGE) and near(s30img.getpixel((5, 582)), BLUE), ""))

    big = white_bbox(still(title="HOLA", title_style="box_white", font_size=180, split=70, offset=500), 1000, 1920)
    results.append(("superpuesto: la caja nunca se sale por abajo (se ajusta)", big is not None and big[3] <= 1919, f"{big}"))
    top = white_bbox(still(title="HOLA", title_style="box_white", font_size=180, split=30, offset=-500), 0, 900)
    results.append(("superpuesto: la caja nunca se sale por arriba (se ajusta)", top is not None and top[1] >= 0, f"{top}"))

    for sid, want in (("box_white", (255, 255, 255)), ("box_black", (17, 17, 17)), ("box_yellow", (255, 212, 0))):
        im = still(title_style=sid, font_size=56)
        # esquina interior izquierda de la caja: lejos del texto
        probe = [im.getpixel((x, 960)) for x in range(0, 540, 1) if near(im.getpixel((x, 960)), want, 24)]
        results.append((f"estilo {sid}: dibuja una caja del color esperado", len(probe) > 20, f"{len(probe)} px"))
    out_im = still(title="HOLA", title_style="outline", font_size=100)
    results.append(("estilo contorno: sin caja (fuera del texto queda el video)", near(out_im.getpixel((300, 960)), BLUE, 30) or near(out_im.getpixel((300, 960)), ORANGE, 30), f"{out_im.getpixel((300, 960))}"))
    yel = still(title="HOLA", title_style="outline_yellow", font_size=100)
    results.append(("estilo contorno amarillo: hay pixeles amarillos de texto",
                    sum(1 for x in range(300, 800, 2) for y in range(880, 1040, 2) if yel.getpixel((x, y))[0] > 220 and yel.getpixel((x, y))[1] > 200 and yel.getpixel((x, y))[2] < 90) > 100, ""))

    renders = {f: still(title="Hola GTA", title_style="box_white", font=f, font_size=60).tobytes() for f in clipmaker.FONTS}
    results.append(("tipografias: las 7 dan resultados distintos", len(set(renders.values())) == len(clipmaker.FONTS), f"{len(set(renders.values()))}/7"))
    results.append(("mayusculas apagadas cambia el texto",
                    still(title="Hola gta", title_style="box_white", uppercase=False).tobytes() != still(title="Hola gta", title_style="box_white").tobytes(), ""))
    results.append(("en franja se ignoran reparto y posicion",
                    still(split=30, offset=200).tobytes() == still().tobytes(), ""))
    results.append(("en franja la tipografia si cambia", still(font="bangers").tobytes() != still().tobytes(), ""))
    long_t = "Titulo larguisimo para ver que la caja crece hacia abajo y se parte en varias lineas sin salirse de los lados del video"
    lb = white_bbox(still(title=long_t, title_style="box_white", font_size=90), 500, 1500)
    results.append(("caja con titulo largo: cabe en ancho (<=92%) y se parte en lineas",
                    lb is not None and lb[0] >= 40 and lb[2] <= 1040 and (lb[3] - lb[1]) > 160, f"{lb}"))
    blur = white_bbox(still(title="HOLA", preset="clip_blur", title_style="box_white", font_size=56), 0, 700)
    results.append(("blur + caja: el texto queda arriba del video, no en el centro", blur is not None and blur[3] < 600, f"{blur}"))
    return results


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
    if not only or "efectos" in only:
        with tempfile.TemporaryDirectory() as td2:
            for name, ok, msg in effect_tests(Path(td2), {}):
                fails += not ok
                print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {msg}")
    if not only or "superpuesto" in only:
        with tempfile.TemporaryDirectory() as td3:
            for name, ok, msg in overlay_tests(Path(td3)):
                fails += not ok
                print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {msg}")
    print(f"\n{fails} fallos")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
