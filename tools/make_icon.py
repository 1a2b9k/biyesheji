"""
Generate assets/app.ico -- the icon used by the Desktop shortcut.

Why a generated icon instead of a checked-in binary: the palette has to stay in
step with the frontend (``frontend/src/utils/chart.js`` uses the same hex
values), and a PNG->ICO conversion is three lines of Pillow. Keeping the source
in the repo means the icon can be rebuilt after a palette change instead of
being an opaque blob nobody dares touch.

The design is deliberately plain -- three sentiment bars on the ink background.
At 16x16 (the size Windows actually shows in the taskbar and title bar) any
finer detail turns to mud, so the shape is nothing but three rounded rectangles
with a wide margin.

Usage:
    .python\\python.exe tools/make_icon.py
    .python\\python.exe tools/make_icon.py --out assets/app.ico

Output sizes: 16, 24, 32, 48, 64, 128, 256 -- Windows picks per context.
"""

from __future__ import annotations

import argparse
import os
import sys

# Same hex values as frontend/src/utils/chart.js. Duplicated on purpose: this
# script must run without a Node toolchain, and a test asserts they agree.
INK = '#191713'
SURFACE = '#f7f4ee'
POS = '#c8443a'    # 涨 / 正面
NEG = '#2e7d5b'    # 跌 / 负面
NEU = '#8a857d'    # 中性

SIZES = (16, 24, 32, 48, 64, 128, 256)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_OUT = os.path.join(_REPO_ROOT, 'assets', 'app.ico')


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def render(size: int):
    """Draw one square icon at ``size`` pixels and return a PIL image."""
    from PIL import Image, ImageDraw

    # Supersample 4x then downscale: PIL has no anti-aliased rounded rectangle,
    # and drawing directly at 16px produces visibly ragged corners.
    scale = 4
    big = size * scale
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = round(big * 0.06)
    radius = round(big * 0.22)
    draw.rounded_rectangle(
        [margin, margin, big - margin - 1, big - margin - 1],
        radius=radius, fill=_hex_to_rgb(INK))

    # Three bars: leftmost shortest (negative), middle longest (neutral, it is
    # the majority class in this project's data), right medium (positive).
    bar_w = round(big * 0.16)
    gap = round(big * 0.075)
    total = bar_w * 3 + gap * 2
    x0 = (big - total) // 2
    base_y = big - margin - round(big * 0.20)
    heights = (0.26, 0.52, 0.38)
    colors = (NEG, NEU, POS)
    for i, (h, color) in enumerate(zip(heights, colors)):
        x = x0 + i * (bar_w + gap)
        top = base_y - round(big * h)
        draw.rounded_rectangle(
            [x, top, x + bar_w - 1, base_y],
            radius=max(1, round(bar_w * 0.35)),
            fill=_hex_to_rgb(color))

    return img.resize((size, size), Image.LANCZOS)


def build(out_path: str) -> str:
    """Write the multi-size .ico and return its path."""
    from PIL import Image

    frames = [render(s) for s in SIZES]
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # Pillow writes every supplied size into one .ico; ``sizes`` alone would
    # re-render from the single largest image and lose the per-size tuning.
    frames[-1].save(out_path, format='ICO',
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Generate assets/app.ico')
    parser.add_argument('--out', default=_DEFAULT_OUT, help='output .ico path')
    args = parser.parse_args(argv)

    path = build(args.out)
    print('[icon] wrote %s (%d bytes)' % (path, os.path.getsize(path)))
    print('[icon] sizes: %s' % ', '.join(str(s) for s in SIZES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
