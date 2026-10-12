"""Draw the CompoundIME icons: a compound bow with an arrow pointing up.

  python tools/make_compound_icon.py <out-dir>
Writes
  compound_ime.ico          product icon (installer, Apps list, settings tool):
                            black lines with a white halo, cams at the limb tips
  compound_ime_langbar.ico  input-mode icon on the taskbar: a black bow on a
                            white rounded square, so it reads on dark and light
                            taskbars; no cams and bolder lines for 16-24 px
  compound_ime-256.png      preview of the product icon
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
LANGBAR_SIZES = (16, 20, 24, 32, 40, 48, 64)
BLACK, WHITE = (17, 17, 17, 255), (255, 255, 255, 255)
BADGE = (245, 245, 245, 255)


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


def small_strokes():
    """The taskbar shape: limbs low and wide, V string, a clear arrow head."""
    yield list(cubic((2.2, 15.5), (5.5, 9.5), (18.5, 9.5), (21.8, 15.5))), 1.0
    yield list(segment((2.6, 15.6), (12, 19.5))) + list(segment((12, 19.5), (21.4, 15.6))), 0.55
    yield list(segment((12, 22.5), (12, 2.5))), 1.0
    yield list(segment((8.6, 6.2), (12, 2.5))) + list(segment((12, 2.5), (15.4, 6.2))), 1.0


def stamp(d, points, r, unit, color, shrink=1.0, centre=12):
    for x, y in points:
        if shrink != 1.0:
            x, y = centre + (x - centre) * shrink, centre + (y - centre) * shrink
        x, y = x * unit, y * unit
        d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def draw(size, scale=8):
    s = size * scale
    unit = s / 24
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    line = (2.3 if size <= 20 else 1.9) * unit
    halo = line + (2.2 if size <= 20 else 2.0) * unit
    for color in (WHITE, BLACK):
        for points, rel in strokes():
            r = (line * rel + (halo - line)) / 2 if color == WHITE else line * rel / 2
            stamp(d, points, r, unit, color)
    return img.resize((size, size), Image.LANCZOS)


def draw_langbar(size, scale=8):
    s = size * scale
    unit = s / 24
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0.5 * unit, 0.5 * unit, s - 0.5 * unit, s - 0.5 * unit), radius=4.5 * unit, fill=BADGE)
    line = (2.6 if size <= 24 else 2.2) * unit
    for points, rel in small_strokes():
        stamp(d, points, line * rel / 2, unit, BLACK, shrink=0.78)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(images, path):
    images[-1].save(path, sizes=[im.size for im in images], append_images=images[:-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    images = [draw(size) for size in SIZES]
    images[-1].save(args.out / "compound_ime-256.png")
    save_ico(images, args.out / "compound_ime.ico")
    save_ico([draw_langbar(size) for size in LANGBAR_SIZES], args.out / "compound_ime_langbar.ico")
    print("icon", args.out / "compound_ime.ico")


if __name__ == "__main__":
    main()
