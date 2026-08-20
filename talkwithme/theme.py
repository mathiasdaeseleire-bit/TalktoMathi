"""Shared visual language for every TalkWithMe window.

Modelled on Stripe's dashboard: a light, airy surface rather than a dark
one, ink-navy text instead of pure black, one blurple accent used
sparingly, hairline borders instead of heavy frames, and a strict spacing
scale so edges line up across every section.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# --- palette ----------------------------------------------------------
BG            = "#F6F9FC"   # page
SURFACE       = "#FFFFFF"   # cards, inputs, rows
SURFACE_ALT   = "#FAFBFC"   # zebra striping
SURFACE_HOVER = "#F0F4F8"
BORDER        = "#E3E8EE"   # hairline
BORDER_STRONG = "#CFD7DF"

TEXT          = "#0A2540"   # ink navy — headings and numbers
TEXT_MUTED    = "#425466"   # body
TEXT_FAINT    = "#8792A2"   # labels, captions

ACCENT        = "#635BFF"   # blurple
ACCENT_SOFT   = "#8F89FF"
ACCENT_DEEP   = "#4F46E5"
ACCENT_WASH   = "#EFEDFF"   # tinted background for accent areas

GREEN         = "#24B47E"
AMBER         = "#F5BE58"
RED           = "#E25950"
CYAN          = "#38BDF8"   # second stop of the Stripe-style gradient

# Colour key used for real rounded corners on the borderless indicator:
# anything painted in it becomes see-through. Deliberately garish so it
# can't collide with real pixels.
TRANSPARENT_KEY = "#FF00FE"

# --- spacing scale ----------------------------------------------------
PAD      = 28   # window gutter
GAP      = 14   # between related blocks
GAP_L    = 30   # between sections
CARD_PAD = 24   # inside a card

# --- type scale -------------------------------------------------------
FONT_UI        = ("Segoe UI", 10)
FONT_UI_SMALL  = ("Segoe UI", 9)
FONT_UI_TINY   = ("Segoe UI", 8)
FONT_TITLE     = ("Segoe UI Semibold", 15)
FONT_SECTION   = ("Segoe UI Semibold", 10)
FONT_BODY      = ("Segoe UI", 10)
FONT_HERO      = ("Segoe UI Light", 48)
FONT_HERO_UNIT = ("Segoe UI", 15)
FONT_STAT      = ("Segoe UI Semibold", 17)
FONT_LABEL     = ("Segoe UI Semibold", 8)   # ALL-CAPS eyebrow labels
FONT_MONO      = ("Cascadia Mono", 9)


def apply(root: tk.Misc) -> ttk.Style:
    """Style ttk widgets to match. 'clam' is the only built-in theme that
    honours custom colours on Windows; the native themes ignore them."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=TEXT,
                     fieldbackground=SURFACE, font=FONT_UI,
                     borderwidth=0, focuscolor=ACCENT)

    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_UI)

    # Inputs: hairline box that picks up the accent on focus.
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                     insertcolor=TEXT, padding=8, borderwidth=1)
    style.map("TEntry",
               bordercolor=[("focus", ACCENT)],
               lightcolor=[("focus", ACCENT)],
               darkcolor=[("focus", ACCENT)])

    style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE,
                     foreground=TEXT, bordercolor=BORDER, arrowcolor=TEXT_MUTED,
                     padding=6, borderwidth=1)
    style.map("TCombobox",
               fieldbackground=[("readonly", SURFACE)],
               bordercolor=[("focus", ACCENT), ("active", BORDER_STRONG)])

    # Secondary button: white, hairline border.
    style.configure("TButton", background=SURFACE, foreground=TEXT_MUTED,
                     bordercolor=BORDER, padding=(15, 8), font=FONT_UI,
                     borderwidth=1, relief="flat")
    style.map("TButton",
               background=[("active", SURFACE_HOVER), ("pressed", SURFACE_HOVER)],
               foreground=[("active", TEXT)],
               bordercolor=[("active", BORDER_STRONG)])

    # Primary button: solid blurple.
    style.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF",
                     bordercolor=ACCENT, padding=(17, 8), font=FONT_SECTION,
                     borderwidth=1, relief="flat")
    style.map("Accent.TButton",
               background=[("active", ACCENT_SOFT), ("pressed", ACCENT_DEEP)],
               bordercolor=[("active", ACCENT_SOFT), ("pressed", ACCENT_DEEP)])

    style.configure("TCheckbutton", background=BG, foreground=TEXT_MUTED,
                     font=FONT_UI, indicatorcolor=SURFACE,
                     indicatorbackground=SURFACE, bordercolor=BORDER_STRONG,
                     focuscolor=BG, padding=2)
    style.map("TCheckbutton",
               background=[("active", BG)],
               foreground=[("active", TEXT)],
               indicatorcolor=[("selected", ACCENT), ("active", SURFACE_HOVER)])

    style.configure("TSeparator", background=BORDER)

    # Table: white rows, hairline header, tinted selection.
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                     foreground=TEXT_MUTED, bordercolor=BORDER, rowheight=30,
                     font=FONT_UI_SMALL, borderwidth=0)
    style.configure("Treeview.Heading", background=BG, foreground=TEXT_FAINT,
                     font=FONT_LABEL, relief="flat", padding=(10, 8),
                     borderwidth=0)
    style.map("Treeview",
               background=[("selected", ACCENT_WASH)],
               foreground=[("selected", TEXT)])
    style.map("Treeview.Heading", background=[("active", BG)])

    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG,
                     bordercolor=BG, arrowcolor=TEXT_FAINT, width=11)
    style.map("Vertical.TScrollbar", background=[("active", BORDER_STRONG)])

    return style


def round_rect_points(x1: float, y1: float, x2: float, y2: float, r: float):
    """Corner points for a rounded rectangle, for Canvas.create_polygon with
    smooth=True. Tk has no rounded-rect primitive."""
    r = min(r, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def mix(color_a: str, color_b: str, t: float) -> str:
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))
