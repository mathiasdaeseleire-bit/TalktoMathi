"""The app mark: a voice waveform whose bars trace an M — speaking, and
Mathi. Drawn at 4x and downsampled, because a tray icon is rendered at
16-32px and unsmoothed edges look cheap at that size.

State is carried by colour (violet idle, coral listening, amber
processing) so the shape stays recognisable while the status changes.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

SS = 4          # supersampling factor
SIZE = 64       # final icon size
BADGE_R = 0.28  # corner radius as a fraction of size

# (top-left, bottom-right) of the badge gradient, per state. Idle runs
# from blurple toward cyan, echoing the Stripe gradient.
GRADIENTS = {
    "idle":       ((0x63, 0x5B, 0xFF), (0x38, 0xBD, 0xF8)),   # blurple -> cyan
    "listening":  ((0xE2, 0x59, 0x50), (0xFF, 0x8A, 0x5B)),   # red -> warm
    "processing": ((0xF5, 0xBE, 0x58), (0xF0, 0x93, 0x2B)),   # amber
}

# Bar heights as a fraction of the usable height. The silhouette rises,
# dips in the middle and rises again: the shape of an M, and the rhythm of
# a voice.
BAR_HEIGHTS = (0.42, 0.86, 0.52, 0.86, 0.42)


def _gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Vertical gradient, nudged diagonally so it doesn't read as flat."""
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (y * 0.78 + x * 0.22) / size
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
    return grad


def make_icon(state: str = "idle", size: int = SIZE) -> Image.Image:
    top, bottom = GRADIENTS.get(state, GRADIENTS["idle"])
    big = size * SS

    # Rounded-square badge, gradient showing through a rounded mask.
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=int(big * BADGE_R), fill=255)

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(_gradient(big, top, bottom).convert("RGBA"), (0, 0), mask)

    # Waveform bars.
    d = ImageDraw.Draw(img)
    n = len(BAR_HEIGHTS)
    bar_w = big * 0.104
    gap = big * 0.062
    total = n * bar_w + (n - 1) * gap
    x = (big - total) / 2
    cy = big / 2
    usable = big * 0.60

    for h_frac in BAR_HEIGHTS:
        h = usable * h_frac
        d.rounded_rectangle(
            (round(x), round(cy - h / 2), round(x + bar_w), round(cy + h / 2)),
            radius=bar_w / 2, fill=(255, 255, 255, 242))
        x += bar_w + gap

    return img.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    """Multi-resolution .ico for the window title bar and the built exe."""
    base = make_icon("idle", 256)
    base.save(path, format="ICO",
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
