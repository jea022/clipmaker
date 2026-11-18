#!/usr/bin/env python3
"""Genera la plantilla de marca por cuenta: fondo + overlay PNG 1080x1920 y su layout JSON."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
OUT = HERE / "templates"
FONT = str(HERE / "fonts" / "InterDisplay-Bold.otf")
W, H = 1080, 1920

BRANDS = {
    "wganga": {"handle": "@wganga_clips", "accent": "#ff7a00", "bg_top": "#1a0f05", "bg_bottom": "#0b0b14"},
    "gtahispa": {"handle": "@gtaHispaClips", "accent": "#ff2e93", "bg_top": "#1a0518", "bg_bottom": "#0b0b14"},
    "gtaclipsboss": {"handle": "@gtaclipsboss", "accent": "#ffc400", "bg_top": "#1a1405", "bg_bottom": "#0b0b14"},
}


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def make_background(brand):
    top, bottom = hex_rgb(brand["bg_top"]), hex_rgb(brand["bg_bottom"])
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return img.convert("RGBA")


def make_overlay(brand, layout, lines=True):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = hex_rgb(brand["accent"]) + (255,)
    title_y, title_h = layout["title_zone"][1], layout["title_zone"][3]
    for y in ((title_y - 3, title_y + title_h - 3) if lines else ()):
        d.rectangle([0, y, W, y + 6], fill=accent)
    font = ImageFont.truetype(FONT, 38)
    text = brand["handle"]
    tw = d.textlength(text, font=font)
    pad = 18
    x1, y1 = W - tw - 2 * pad - 30, H - 38 - 2 * pad - 30
    d.rounded_rectangle([x1, y1, W - 30, H - 30], radius=18, fill=(0, 0, 0, 170))
    d.text((x1 + pad, y1 + pad - 4), text, font=font, fill=(255, 255, 255, 255))
    return img


def main():
    OUT.mkdir(exist_ok=True)
    base = json.loads((HERE / "layout.json").read_text())
    for name, brand in BRANDS.items():
        bg_path, ov_path = OUT / f"{name}_bg.png", OUT / f"{name}_overlay.png"
        make_background(brand).save(bg_path)
        make_overlay(brand, base).save(ov_path)
        clean_path = OUT / f"{name}_overlay_clean.png"
        make_overlay(brand, base, lines=False).save(clean_path)
        cfg = dict(base)
        cfg["background_png"] = f"templates/{bg_path.name}"
        cfg["overlay_png"] = f"templates/{ov_path.name}"
        cfg["overlay_clean_png"] = f"templates/{clean_path.name}"
        cfg["accent_color"] = brand["accent"]
        cfg["title"] = dict(base["title"])
        (OUT / f"{name}.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        print(f"OK {name}: {bg_path.name}, {ov_path.name}, {name}.json")


if __name__ == "__main__":
    main()
