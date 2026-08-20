"""The floating listening indicator: a rounded pill in the bottom-right
corner with a live, mirrored waveform.

Two things matter beyond looks:
  - It must never take focus. A borderless window that steals focus makes
    the user's keystrokes vanish into it, which is indistinguishable from
    a broken keyboard. Enforced at the OS level with WS_EX_NOACTIVATE.
  - Levels are smoothed and interpolated, so the bars glide instead of
    strobing at the audio callback rate.

Lives on the Tk main thread; show/hide are called from worker threads and
only flip a flag that the Tk `after` loop reads.
"""
from __future__ import annotations

import ctypes
import logging
import math
import time
import tkinter as tk

from .theme import (ACCENT, ACCENT_DEEP, ACCENT_SOFT, AMBER, BG, BORDER, GREEN,
                     SURFACE, TEXT, TEXT_FAINT, TEXT_MUTED, TRANSPARENT_KEY,
                     mix, round_rect_points)

log = logging.getLogger("talkwithme.indicator")

WIDTH, HEIGHT = 208, 60
MARGIN_X, MARGIN_Y = 22, 66      # clear of the taskbar
RADIUS = 16
BAR_COUNT = 20
BAR_W, BAR_GAP = 3, 4
REFRESH_MS = 33                   # ~30 fps
LOUD_RMS = 2200.0                 # RMS that counts as a full-height bar

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008


def _elapsed_text(seconds: float) -> str:
    minutes, sec = divmod(int(max(0, seconds)), 60)
    if minutes < 60:
        return f"{minutes}:{sec:02d}  ·  klik tray om te stoppen"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}  ·  klik tray om te stoppen"


def _make_unfocusable(win: tk.Toplevel) -> None:
    """Tk has no API for this, so set the extended window styles directly.
    WS_EX_NOACTIVATE stops the window from ever being activated;
    WS_EX_TOOLWINDOW keeps it out of the alt-tab list."""
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        user32.GetWindowLongW.restype = ctypes.c_long
        current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               current | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    except Exception as e:
        log.debug("kon indicator-vensterstijl niet zetten: %s", e)


class Indicator:
    def __init__(self, root: tk.Tk, get_levels, get_meeting_elapsed=None):
        self._root = root
        self._get_levels = get_levels
        self._get_meeting_elapsed = get_meeting_elapsed or (lambda: 0.0)
        self._state = "hidden"          # hidden | listening | processing
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._smoothed = [0.0] * BAR_COUNT
        self._t0 = time.monotonic()
        self._root.after(REFRESH_MS, self._tick)

    # ---- callable from any thread: only flip a flag -----------------

    def show_listening(self) -> None:
        self._state = "listening"

    def show_processing(self) -> None:
        self._state = "processing"

    def show_meeting(self) -> None:
        self._state = "meeting"

    def hide(self) -> None:
        self._state = "hidden"

    # ---- Tk thread only --------------------------------------------

    def _ensure_window(self) -> None:
        if self._win is not None:
            return
        win = tk.Toplevel(self._root)
        # Built hidden and only shown once the extended styles are set.
        # A Toplevel that is visible for even a frame before WS_EX_TOOLWINDOW
        # is applied registers a taskbar button, which flashes up as a
        # blank white icon on every single recording.
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        # Everything painted in the key colour becomes see-through, which is
        # how the pill gets genuinely rounded corners instead of dark stubs.
        win.configure(bg=TRANSPARENT_KEY)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            win.configure(bg=BG)

        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{WIDTH}x{HEIGHT}+{sw - WIDTH - MARGIN_X}+{sh - HEIGHT - MARGIN_Y}")

        canvas = tk.Canvas(win, width=WIDTH, height=HEIGHT, bg=TRANSPARENT_KEY,
                            highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)

        _make_unfocusable(win)
        win.deiconify()
        self._win, self._canvas = win, canvas
        self._smoothed = [0.0] * BAR_COUNT

    def _destroy_window(self) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win, self._canvas = None, None

    def _tick(self) -> None:
        try:
            if self._state == "hidden":
                self._destroy_window()
            else:
                self._ensure_window()
                self._draw()
        except Exception:
            pass
        finally:
            self._root.after(REFRESH_MS, self._tick)

    def _draw(self) -> None:
        c = self._canvas
        if c is None:
            return
        c.delete("all")

        listening = self._state == "listening"
        meeting = self._state == "meeting"
        accent = ACCENT if listening else (GREEN if meeting else AMBER)
        now = time.monotonic() - self._t0

        # White pill on a hairline border, the way a Stripe card sits on the
        # page. Two stacked rounded rects: the outer one is the border.
        c.create_polygon(round_rect_points(1, 1, WIDTH - 1, HEIGHT - 1, RADIUS),
                          smooth=True, fill=mix(BORDER, accent, 0.25), outline="")
        c.create_polygon(round_rect_points(2, 2, WIDTH - 2, HEIGHT - 2, RADIUS - 1),
                          smooth=True, fill=SURFACE, outline="")

        # Breathing status dot.
        pulse = 0.5 + 0.5 * math.sin(now * (5.0 if listening else 2.5))
        cx, cy = 20, HEIGHT / 2
        if listening:
            c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8,
                           fill=mix(SURFACE, accent, 0.10 + 0.16 * pulse), outline="")
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                       fill=mix(accent, ACCENT_SOFT, pulse if listening else 0.0),
                       outline="")

        if meeting:
            title, subtitle = "Vergadering", _elapsed_text(self._get_meeting_elapsed())
        elif listening:
            title, subtitle = "Luistert", "Ctrl+Win loslaten"
        else:
            title, subtitle = "Verwerkt", "Even geduld"
        c.create_text(36, cy - 9, text=title, anchor="w", fill=TEXT,
                       font=("Segoe UI Semibold", 9))
        c.create_text(36, cy + 8, text=subtitle, anchor="w", fill=TEXT_FAINT,
                       font=("Segoe UI", 7))

        self._draw_bars(c, listening, accent, now)

    def _draw_bars(self, c: tk.Canvas, listening: bool, accent: str, now: float) -> None:
        right = WIDTH - 16
        left = right - (BAR_COUNT * (BAR_W + BAR_GAP)) + BAR_GAP
        base_y = HEIGHT / 2 + 9
        max_h = 15.0

        if listening or self._state == "meeting":
            levels = list(self._get_levels() or [])
            recent = levels[-BAR_COUNT:]
            recent = [0.0] * (BAR_COUNT - len(recent)) + recent
            targets = [min(v / LOUD_RMS, 1.0) for v in recent]
        else:
            # Processing: a travelling wave, so it reads as "busy" not "stuck".
            targets = [0.18 + 0.30 * (0.5 + 0.5 * math.sin(now * 6 - i * 0.55))
                        for i in range(BAR_COUNT)]

        for i, target in enumerate(targets):
            # Ease toward the target: rise fast, fall gently.
            cur = self._smoothed[i]
            self._smoothed[i] = cur + (target - cur) * (0.55 if target > cur else 0.22)
            frac = self._smoothed[i]

            h = max(2.0, frac * max_h)
            x = left + i * (BAR_W + BAR_GAP)
            # Louder bars sit deeper in the accent, quiet ones stay pale.
            color = mix(ACCENT_SOFT, ACCENT_DEEP, min(frac * 1.25, 1.0)) if listening else \
                    mix(BORDER, accent, 0.30 + 0.70 * frac)
            c.create_polygon(
                round_rect_points(x, base_y - h, x + BAR_W, base_y + h, BAR_W / 2),
                smooth=True, fill=color, outline="")

        if listening and not any(t > 0.02 for t in targets):
            c.create_text(right, base_y + 1, text="", anchor="e",
                           fill=TEXT_MUTED, font=("Segoe UI", 8))
