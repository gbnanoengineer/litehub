#!/usr/bin/env python3
"""Draws the Tessera icon (same shapes as packaging/tessera.svg) to assets/icons/<n>x<n>.png."""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
os.makedirs(OUT, exist_ok=True)
S = 8  # supersample
for n in (16, 32, 48, 64, 128, 256, 512):
    big = n * S
    k = big / 128
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = lambda x, y, w, h, r, c: d.rounded_rectangle((x * k, y * k, (x + w) * k, (y + h) * k), r * k, fill=c)
    box(0, 0, 128, 128, 28, "#1e2330")
    box(18, 18, 46, 46, 12, "#25d366")
    box(68, 18, 42, 46, 12, "#26a5e4")
    box(18, 68, 46, 42, 12, "#5865f2")
    box(68, 68, 42, 42, 12, "#ea4335")
    d.ellipse(((64 - 9) * k, (64 - 9) * k, (64 + 9) * k, (64 + 9) * k), fill="#ffffff")
    im.resize((n, n), Image.LANCZOS).save(os.path.join(OUT, "%dx%d.png" % (n, n)))
