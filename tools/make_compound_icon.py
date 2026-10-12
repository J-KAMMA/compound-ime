"""Draw the CompoundIME icon: a compound bow (cams at the limb tips) with an
arrow pointing up, black lines with a white halo so that one icon reads on both
light and dark taskbars.

  python tools/make_compound_icon.py <out-dir>
Writes compound_ime.ico (16-256 px) and compound_ime-256.png.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BLACK, WHITE = (17, 17, 17, 255), (255, 255, 255, 255)


def cubic(p0, p1, p2, p3, n=200):
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def segment(a, b, n=80):
    for i in range(n + 1):
        t = i / n
        yield (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def ring(c, r, n=120):
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        yield (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def strokes():
    """(points, relative width) in a 24-unit box."""
    yield list(cubic((3.5, 13), (7, 8.5), (17, 8.5), (20.5, 13))), 1.0           # limbs
    yield list(ring((3.6, 13.7), 1.5)), 0.8                                       # cams
    yield list(ring((20.4, 13.7), 1.5)), 0.8
    yield list(segment((4.6, 15.2), (12, 18))) + list(segment((12, 18), (19.4, 15.2))), 0.6  # string
    yield list(segment((12, 21), (12, 3.5))), 1.0                                 # arrow
    yield list(segment((9.6, 6.5), (12, 3.5))) + list(segment((12, 3.5), (14.4, 6.5))), 1.0


def draw(size, scale=8):
    s = size * scale
    unit = s / 24
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    line = (2.3 if size <= 20 else 1.9) * unit
    halo = line + (2.2 if size <= 20 else 2.0) * unit
    for color, width in ((WHITE, halo), (BLACK, line)):
        for points, rel in strokes():
            r = (width if color == WHITE else width * rel) / 2
            if color == WHITE:
                r = (line * rel + (halo - line)) / 2
            for x, y in points:
                x, y = x * unit, y * unit
                d.ellipse((x - r, y - r, x + r, y + r), fill=color)
    return img.resize((size, size), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    images = [draw(size) for size in SIZES]
    images[-1].save(args.out / "compound_ime-256.png")
    images[-1].save(args.out / "compound_ime.ico", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print("icon", args.out / "compound_ime.ico")


if __name__ == "__main__":
    main()
