#!/usr/bin/env python3
"""Genera el icono de la app (static/clipmaker.png y static/clipmaker.ico)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "static"
S = 512


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=110, fill=(14, 14, 22, 255))
    pw, ph = 236, 420
    x0, y0 = (S - pw) // 2, (S - ph) // 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=26, fill=(11, 11, 20, 255), outline=(255, 122, 0, 255), width=10)
    inner = 22
    d.rectangle([x0 + inner, y0 + inner, x0 + pw - inner, y0 + 150], fill=(255, 122, 0, 255))
    d.rectangle([x0 + inner, y0 + 168, x0 + pw - inner, y0 + 214], fill=(255, 255, 255, 255))
    d.rectangle([x0 + inner, y0 + 232, x0 + pw - inner, y0 + ph - inner], fill=(124, 92, 255, 255))
    return img


if __name__ == "__main__":
    img = draw()
    img.save(OUT / "clipmaker.png")
    img.save(OUT / "clipmaker.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("OK static/clipmaker.png y static/clipmaker.ico")
