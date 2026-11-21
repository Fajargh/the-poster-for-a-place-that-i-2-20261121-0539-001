#!/usr/bin/env python3
"""VELMARA - The Lagoon of Glass Tides.

A travel poster for a place that does not exist, drawn entirely in code.

The program renders a 1024x1024 travel poster with a pure-Python software
renderer (standard library only - no Pillow, no network, no external files)
and writes it to $MAKEFUN_OUTPUT_DIR/entry.png (or /output/entry.png).

Scene: at golden hour, three glass lighthouses rise from a rocky islet in a
violet lagoon; their warm lamps glow against a rose-and-gold sky while the
tide, famously, never leaves.
"""

import math
import os
import random
import struct
import zlib

W = 1024
H = 1024

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def blend(dst, src, alpha):
    """Alpha-blend src colour over dst colour; alpha 0..1."""
    return tuple(int(round(dst[i] + (src[i] - dst[i]) * alpha)) for i in range(3))


# ---------------------------------------------------------------------------
# Canvas: a flat RGB bytearray with simple drawing primitives
# ---------------------------------------------------------------------------

class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def get(self, x, y):
        i = self._idx(x, y)
        return (self.px[i], self.px[i + 1], self.px[i + 2])

    def set(self, x, y, colour, alpha=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            if alpha >= 1.0:
                self.px[i], self.px[i + 1], self.px[i + 2] = colour
            elif alpha > 0.0:
                r, g, b = self.px[i], self.px[i + 1], self.px[i + 2]
                self.px[i] = int(round(r + (colour[0] - r) * alpha))
                self.px[i + 1] = int(round(g + (colour[1] - g) * alpha))
                self.px[i + 2] = int(round(b + (colour[2] - b) * alpha))

    def fill_row(self, y, colour):
        """Fill one whole row with a solid colour (fast)."""
        if 0 <= y < self.h:
            row = bytes(colour) * self.w
            start = y * self.w * 3
            self.px[start:start + self.w * 3] = row

    def vgradient(self, y0, y1, c0, c1):
        """Vertical gradient between rows y0..y1."""
        span = max(1, y1 - y0)
        for y in range(y0, min(y1 + 1, self.h)):
            t = (y - y0) / span
            self.fill_row(y, lerp(c0, c1, t))

    def hline(self, x0, x1, y, colour, alpha=1.0):
        if x1 < x0:
            x0, x1 = x1, x0
        for x in range(max(0, x0), min(self.w, x1 + 1)):
            self.set(x, y, colour, alpha)

    def vline(self, x, y0, y1, colour, alpha=1.0):
        if y1 < y0:
            y0, y1 = y1, y0
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            self.set(x, y, colour, alpha)

    def line(self, x0, y0, x1, y1, colour, alpha=1.0, width=1):
        """Bresenham line, with a square brush of the given width."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        r = width // 2
        while True:
            for ox in range(-r, r + 1):
                for oy in range(-r, r + 1):
                    self.set(x0 + ox, y0 + oy, colour, alpha)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def fill_polygon(self, points, colour, alpha=1.0):
        """Scanline polygon fill (even-odd)."""
        if not points:
            return
        ys = [p[1] for p in points]
        y_min, y_max = max(0, min(ys)), min(self.h - 1, max(ys))
        n = len(points)
        for y in range(y_min, y_max + 1):
            xs = []
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                self.hline(int(math.ceil(xs[j])), int(math.floor(xs[j + 1])), y, colour, alpha)

    def disc(self, cx, cy, r, colour, alpha=1.0):
        """Filled circle."""
        r2 = r * r
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            dy = y - cy
            half = int(math.sqrt(max(0, r2 - dy * dy)))
            self.hline(cx - half, cx + half, y, colour, alpha)

    def ellipse(self, cx, cy, rx, ry, colour, alpha=1.0):
        for y in range(max(0, cy - ry), min(self.h, cy + ry + 1)):
            dy = (y - cy) / ry
            half = int(rx * math.sqrt(max(0.0, 1.0 - dy * dy)))
            self.hline(cx - half, cx + half, y, colour, alpha)

    def radial_glow(self, cx, cy, r, colour, peak=0.9):
        """Soft radial glow: alpha falls off with distance squared."""
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            for x in range(max(0, cx - r), min(self.w, cx + r + 1)):
                d2 = ((x - cx) ** 2 + (y - cy) ** 2) / (r * r)
                if d2 < 1.0:
                    self.set(x, y, colour, peak * (1.0 - d2) ** 2)


# ---------------------------------------------------------------------------
# Bitmap font (5x7) for the poster's type. Only the glyphs we need.
# ---------------------------------------------------------------------------

GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "01110", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
}


def text_width(text, scale, tracking=1):
    """Width in px of text rendered at the given scale (tracking in px)."""
    return len(text) * (6 * scale) - scale + (len(text) - 1) * tracking


def draw_text(cv, text, cx, y, scale, colour, tracking=1, shadow=None):
    """Draw text centred on cx, top edge at y. Returns the drawn width."""
    width = text_width(text, scale, tracking)
    x = cx - width // 2
    for ch in text:
        glyph = GLYPHS.get(ch.upper(), GLYPHS[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    bx = x + gx * scale
                    by = y + gy * scale
                    if shadow is not None:
                        for sy in range(scale):
                            for sx in range(scale):
                                cv.set(bx + sx + 2, by + sy + 3, shadow, 0.55)
                    for sy in range(scale):
                        for sx in range(scale):
                            cv.set(bx + sx, by + sy, colour)
        x += 6 * scale + tracking
    return width


# ---------------------------------------------------------------------------
# PNG encoder (stdlib only): 8-bit RGB, no filtering, zlib compression.
# ---------------------------------------------------------------------------

def write_png(cv, path):
    raw = bytearray()
    stride = cv.w * 3
    for y in range(cv.h):
        raw.append(0)  # filter: none
        start = y * stride
        raw.extend(cv.px[start:start + stride])

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------------------
# The poster
# ---------------------------------------------------------------------------

# Palette: a golden-hour sky over a violet lagoon.
SKY_TOP = (38, 22, 84)        # deep indigo
SKY_MID = (122, 74, 158)      # violet
SKY_LOW = (232, 138, 160)     # rose
SKY_HORIZON = (255, 196, 107)  # gold
SEA_TOP = (46, 110, 138)      # teal
SEA_BOTTOM = (13, 42, 74)     # deep navy
SUN = (255, 226, 160)
SUN_CORE = (255, 244, 214)
CREAM = (255, 246, 224)
GOLD = (255, 198, 110)
DARK = (24, 16, 58)           # silhouette violet
GLASS = (196, 226, 244)       # pale glass of the lighthouses
LAMP = (255, 190, 90)

HORIZON = 600


def draw_sky(cv):
    cv.vgradient(0, 240, SKY_TOP, SKY_MID)
    cv.vgradient(240, 470, SKY_MID, SKY_LOW)
    cv.vgradient(470, HORIZON, SKY_LOW, SKY_HORIZON)


def draw_sun(cv):
    # Glow, then a solid disc low in the sky, clear of the lighthouses.
    cv.radial_glow(820, 430, 240, SUN, peak=0.6)
    cv.disc(820, 430, 56, SUN_CORE)
    cv.disc(820, 430, 44, (255, 236, 190))


def draw_clouds(cv):
    # Soft, low clouds kept well clear of the title and subtitle.
    rng = random.Random(20261121)
    for _ in range(5):
        cx = rng.randint(80, 944)
        cy = rng.randint(270, 420)
        rx = rng.randint(70, 130)
        ry = rng.randint(10, 16)
        tone = rng.choice([(255, 190, 170), (255, 214, 170), (214, 150, 200)])
        cv.ellipse(cx, cy, rx, ry, tone, alpha=0.22)
        cv.ellipse(cx, cy - 6, int(rx * 0.6), int(ry * 0.7), tone, alpha=0.16)


def draw_birds(cv):
    rng = random.Random(77)
    for _ in range(6):
        x = rng.randint(120, 900)
        y = rng.randint(300, 400)
        s = rng.randint(10, 18)
        cv.line(x - s, y, x, y - 6, DARK, alpha=0.85, width=2)
        cv.line(x, y - 6, x + s, y, DARK, alpha=0.85, width=2)


def draw_headland(cv):
    # A distant violet headland on the left horizon.
    cv.fill_polygon(
        [(0, HORIZON), (0, 520), (90, 500), (180, 545), (260, 560),
         (330, HORIZON)], (94, 58, 130), alpha=0.85)
    cv.fill_polygon(
        [(1024, HORIZON), (1024, 545), (940, 560), (880, 575), (830, HORIZON)],
        (94, 58, 130), alpha=0.7)


def draw_sea(cv):
    cv.vgradient(HORIZON, H, SEA_TOP, SEA_BOTTOM)
    # Sun path: a glittering column under the sun.
    rng = random.Random(4242)
    for _ in range(260):
        x = int(rng.gauss(820, 80))
        y = rng.randint(HORIZON + 6, 900)
        length = rng.randint(4, 26)
        bright = rng.uniform(0.25, 0.85)
        cv.hline(x - length // 2, x + length // 2, y, SUN, alpha=bright * 0.8)
    # Gentle wave lines.
    for i in range(14):
        y = HORIZON + 30 + i * 26
        tone = lerp(SEA_TOP, SEA_BOTTOM, i / 14.0)
        light = lerp(tone, (150, 200, 220), 0.25)
        cv.hline(0, W - 1, y, light, alpha=0.18)


def draw_lighthouse(cv, cx, base_y, height, width, lamp_y):
    """One slender glass lighthouse with a glowing lamp room and spire."""
    top_y = base_y - height
    # Glass tower: a tapered, slightly translucent body.
    body = [(cx - width // 2, base_y), (cx - width // 2 + 6, top_y),
            (cx + width // 2 - 6, top_y), (cx + width // 2, base_y)]
    cv.fill_polygon(body, GLASS, alpha=0.55)
    # Bright edge on the sunlit side.
    cv.line(cx + width // 2 - 6, top_y, cx + width // 2, base_y,
            (255, 255, 255), alpha=0.5, width=2)
    # Ribs up the tower.
    for k in range(1, 4):
        y = top_y + (height * k) // 4
        t = (y - top_y) / height
        half = width // 2 - 6 * t
        cv.hline(int(cx - half), int(cx + half), y, (255, 255, 255), alpha=0.35)
    # Lamp room: warm glowing band with little windows.
    cv.fill_polygon(
        [(cx - width // 2 - 4, lamp_y + 26), (cx - width // 2 + 2, lamp_y),
         (cx + width // 2 - 2, lamp_y), (cx + width // 2 + 4, lamp_y + 26)],
        LAMP, alpha=0.95)
    for wx in range(-2, 3):
        cv.vline(cx + wx * 9, lamp_y + 6, lamp_y + 20, (120, 60, 10), alpha=0.6)
    # Dome and spire with a glowing orb.
    cv.disc(cx, lamp_y - 2, width // 2 + 2, LAMP, alpha=0.9)
    cv.line(cx, lamp_y - width // 2 - 26, cx, lamp_y, DARK, alpha=0.9, width=3)
    cv.radial_glow(cx, lamp_y - width // 2 - 28, 26, LAMP, peak=0.9)
    cv.disc(cx, lamp_y - width // 2 - 28, 7, SUN_CORE)
    # Reflection in the water below the tower.
    rng = random.Random(cx)
    for i in range(8):
        y = base_y + 10 + i * 11
        half = int(width * 0.5 * (1 - i / 12.0))
        jitter = rng.randint(-5, 5)
        cv.hline(cx - half + jitter, cx + half + jitter, y, LAMP,
                 alpha=0.35 * (1 - i / 10.0))


def draw_islet(cv):
    # Dark rocky islet the lighthouses stand on, with a foam line.
    cv.fill_polygon(
        [(330, 660), (380, 612), (470, 596), (560, 592), (640, 600),
         (700, 624), (720, 660), (330, 660)], DARK)
    cv.hline(330, 720, 660, (220, 235, 245), alpha=0.5)
    cv.hline(360, 690, 664, (255, 255, 255), alpha=0.35)


def draw_lanterns(cv):
    # Small floating lanterns drifting on the lagoon.
    rng = random.Random(99)
    for _ in range(26):
        x = rng.randint(60, 964)
        y = rng.randint(HORIZON + 90, 940)
        r = rng.randint(2, 4)
        cv.radial_glow(x, y, 12, LAMP, peak=0.7)
        cv.disc(x, y, r, SUN_CORE)
        cv.vline(x, y + r, y + r + 10, LAMP, alpha=0.3)


def draw_foreground(cv):
    # Dark cliff in the lower-left corner, with a lone wind-bent tree.
    cv.fill_polygon(
        [(0, H), (0, 900), (60, 880), (150, 905), (230, 930), (280, H)],
        DARK)
    cv.line(120, 905, 150, 800, DARK, width=7)
    for dx, dy in [(-38, -28), (-18, -48), (8, -52), (34, -38)]:
        cv.line(150, 800, 150 + dx, 800 + dy, DARK, width=4)
    # A few pale blossoms on the tree, catching the last light.
    for bx, by in [(112, 772), (132, 752), (158, 748), (184, 762), (120, 790)]:
        cv.disc(bx, by, 5, (255, 200, 210), alpha=0.9)


def draw_frame(cv):
    # Thin vintage poster frame, inset from the edge.
    inset = 30
    col = (255, 226, 160)
    cv.hline(inset, W - inset, inset, col, alpha=0.9)
    cv.hline(inset, W - inset, H - inset, col, alpha=0.9)
    cv.vline(inset, inset, H - inset, col, alpha=0.9)
    cv.vline(W - inset, inset, H - inset, col, alpha=0.9)


def draw_type(cv):
    # The name leads the eye: huge at the top, then the subtitle, then the
    # promise of a stay along the bottom.
    draw_text(cv, "VELMARA", W // 2, 78, 14, CREAM,
              tracking=6, shadow=DARK)
    # Gold rule under the name.
    cv.hline(W // 2 - 190, W // 2 + 190, 196, GOLD, alpha=0.95)
    cv.hline(W // 2 - 190, W // 2 + 190, 199, GOLD, alpha=0.6)
    draw_text(cv, "THE LAGOON OF GLASS TIDES", W // 2, 216, 4, CREAM,
              tracking=3, shadow=DARK)
    draw_text(cv, "WHERE THE TIDE NEVER LEAVES", W // 2, 948, 3,
              (255, 226, 160), tracking=2, shadow=DARK)


def render():
    cv = Canvas(W, H)
    draw_sky(cv)
    draw_sun(cv)
    draw_clouds(cv)
    draw_birds(cv)
    draw_headland(cv)
    draw_sea(cv)
    draw_islet(cv)
    # Three glass lighthouses: tall centre, two shorter flanks.
    draw_lighthouse(cv, 512, 606, 300, 64, 330)
    draw_lighthouse(cv, 420, 610, 220, 50, 402)
    draw_lighthouse(cv, 606, 608, 240, 52, 382)
    draw_lanterns(cv)
    draw_foreground(cv)
    draw_type(cv)
    draw_frame(cv)
    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    cv = render()
    size = write_png(cv, path)
    print(f"wrote {path}: {cv.w}x{cv.h}, {size} bytes")
    assert size <= 1_048_576, "entry.png exceeds the 1 MiB cap"
    assert cv.w <= 1024 and cv.h <= 1024, "entry.png exceeds 1024x1024"


if __name__ == "__main__":
    main()
