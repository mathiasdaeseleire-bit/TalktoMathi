"""The app window: one window, three tabs — history, weekly report,
settings.

Opened from the tray, which runs on its own thread, so tray handlers only
enqueue a request that the Tk main loop picks up. Only one window exists
at a time; asking for it again raises the existing one on the right tab.

The tab strip is hand-drawn rather than a ttk.Notebook: the built-in
notebook draws raised, bordered tabs that can't be styled flat, which
looked wrong against a dark surface.
"""
from __future__ import annotations

import logging
import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk

from . import __version__
from . import history as history_mod
from . import paste
from . import prompts
from . import secrets_store
from . import stats as stats_mod
from . import theme
from . import tones as tones_mod

log = logging.getLogger("talkwithme.ui")

TAB_HISTORY, TAB_REPORT, TAB_MEETINGS, TAB_SETTINGS = 0, 1, 2, 3
TAB_NAMES = ("Geschiedenis", "Weekrapport", "Vergaderingen", "Instellingen")


# ----------------------------------------------------------------------
# Small shared building blocks
# ----------------------------------------------------------------------

def card(parent: tk.Misc, **kw) -> tk.Frame:
    """White panel with a hairline border — Tk can't do box-shadows, so the
    border carries the elevation."""
    return tk.Frame(parent, bg=theme.SURFACE, bd=0,
                     highlightthickness=1, highlightbackground=theme.BORDER,
                     highlightcolor=theme.BORDER, **kw)


def label(parent: tk.Misc, text: str, *, font=None, fg=None, bg=None, **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=font or theme.FONT_UI,
                     fg=fg or theme.TEXT, bg=bg or theme.BG,
                     anchor="w", justify="left", **kw)


def caps(parent: tk.Misc, text: str, *, bg=None) -> tk.Label:
    """Small all-caps section label."""
    return label(parent, text.upper(), font=theme.FONT_LABEL,
                  fg=theme.TEXT_MUTED, bg=bg)


class TabBar(tk.Frame):
    """Flat tab strip with an accent underline on the active tab."""

    def __init__(self, parent: tk.Misc, names: tuple[str, ...], on_select):
        super().__init__(parent, bg=theme.BG)
        self._on_select = on_select
        self._active = 0
        self._items: list[tuple[tk.Label, tk.Frame]] = []

        row = tk.Frame(self, bg=theme.BG)
        row.pack(fill="x")
        for i, name in enumerate(names):
            holder = tk.Frame(row, bg=theme.BG)
            holder.pack(side="left")
            lbl = tk.Label(holder, text=name, font=theme.FONT_UI,
                            fg=theme.TEXT_MUTED, bg=theme.BG,
                            padx=2, pady=6, cursor="hand2")
            lbl.pack(padx=(0, 28))
            underline = tk.Frame(holder, height=2, bg=theme.BG)
            underline.pack(fill="x", padx=(0, 28))
            lbl.bind("<Button-1>", lambda e, idx=i: self.select(idx))
            lbl.bind("<Enter>", lambda e, l=lbl, idx=i:
                      l.configure(fg=theme.TEXT if idx != self._active else theme.TEXT))
            lbl.bind("<Leave>", lambda e, l=lbl, idx=i:
                      l.configure(fg=theme.TEXT if idx == self._active else theme.TEXT_MUTED))
            self._items.append((lbl, underline))

        tk.Frame(self, height=1, bg=theme.BORDER).pack(fill="x")
        self._paint()

    def _paint(self) -> None:
        for i, (lbl, underline) in enumerate(self._items):
            active = i == self._active
            lbl.configure(fg=theme.TEXT if active else theme.TEXT_MUTED,
                           font=theme.FONT_SECTION if active else theme.FONT_UI)
            underline.configure(bg=theme.ACCENT if active else theme.BG)

    def select(self, index: int) -> None:
        self._active = index
        self._paint()
        self._on_select(index)


# ----------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------

class MainWindow:
    """Singleton window. Use MainWindow.open(...) rather than constructing."""

    _instance: "MainWindow | None" = None

    @classmethod
    def open(cls, root: tk.Tk, config, on_save, tab: int = TAB_HISTORY,
             controller=None) -> "MainWindow":
        inst = cls._instance
        if inst is not None and inst.win.winfo_exists():
            inst.show(tab)
            return inst
        inst = cls(root, config, on_save, controller)
        cls._instance = inst
        inst.show(tab)
        return inst

    def __init__(self, root: tk.Tk, config, on_save, controller=None):
        self.config = config
        self.controller = controller

        self.win = tk.Toplevel(root)
        self.win.title("TalkWithMe")
        self.win.configure(bg=theme.BG)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        w, h = 900, 680
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self.win.minsize(760, 580)
        theme.apply(self.win)

        head = tk.Frame(self.win, bg=theme.BG)
        head.pack(fill="x", padx=theme.PAD, pady=(theme.PAD, 0))
        label(head, "TalkWithMe", font=theme.FONT_TITLE).pack(anchor="w")
        label(head, "Houd Ctrl + Windows ingedrukt om te dicteren.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w", pady=(3, 0))

        self.tabbar = TabBar(self.win, TAB_NAMES, self._select_tab)
        self.tabbar.pack(fill="x", padx=theme.PAD, pady=(theme.GAP_L, 0))

        self.body = tk.Frame(self.win, bg=theme.BG)
        self.body.pack(fill="both", expand=True, padx=theme.PAD,
                        pady=(theme.GAP, theme.PAD))

        self.tabs = [
            HistoryTab(self.body),
            ReportTab(self.body),
            MeetingsTab(self.body, controller),
            SettingsTab(self.body, config, on_save),
        ]

        self.win.bind("<Escape>", lambda e: self._close())
        self.win.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        MainWindow._instance = None
        self.win.destroy()

    def _select_tab(self, index: int) -> None:
        for i, tab in enumerate(self.tabs):
            if i == index:
                tab.frame.pack(fill="both", expand=True)
                tab.refresh()
            else:
                tab.frame.pack_forget()

    def show(self, tab: int = TAB_HISTORY) -> None:
        self.tabbar.select(tab)
        self.tabs[tab].refresh()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()


# ----------------------------------------------------------------------
# History
# ----------------------------------------------------------------------

class HistoryTab:
    def __init__(self, parent: tk.Misc):
        self.frame = tk.Frame(parent, bg=theme.BG)
        self._entries: list[dict] = []

        top = tk.Frame(self.frame, bg=theme.BG)
        top.pack(fill="x", pady=(0, theme.GAP))
        self.show_raw = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Toon ruwe transcriptie (vóór opschonen)",
                         variable=self.show_raw, command=self._on_toggle).pack(side="left")
        ttk.Button(top, text="Wissen", command=self._clear).pack(side="right")
        ttk.Button(top, text="Vernieuwen", command=self.refresh).pack(side="right", padx=8)

        list_wrap = tk.Frame(self.frame, bg=theme.BG)
        list_wrap.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(list_wrap, columns=("tijd", "app", "toon", "tekst"),
                                  show="headings", selectmode="browse")
        for col, text, width, stretch, anchor in (
            ("tijd", "WANNEER", 118, False, "w"),
            ("app", "APP", 118, False, "w"),
            ("toon", "TOON", 78, False, "w"),
            ("tekst", "TEKST", 480, True, "w"),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, stretch=stretch, anchor=anchor)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail())

        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("odd", background=theme.SURFACE)
        self.tree.tag_configure("even", background=theme.SURFACE_ALT)

        caps(self.frame, "Volledige tekst").pack(anchor="w", pady=(theme.GAP, 6))
        det = tk.Frame(self.frame, bg=theme.BORDER)
        det.pack(fill="x")
        self.detail = tk.Text(det, height=5, wrap="word", font=theme.FONT_BODY,
                               bg=theme.SURFACE, fg=theme.TEXT, relief="flat",
                               padx=14, pady=12, bd=0, selectbackground=theme.ACCENT_DEEP)
        self.detail.pack(fill="x", padx=1, pady=1)
        self.detail.configure(state="disabled")

        actions = tk.Frame(self.frame, bg=theme.BG)
        actions.pack(fill="x", pady=(theme.GAP, 0))
        self.count_label = label(actions, "", font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED)
        self.count_label.pack(side="left")
        ttk.Button(actions, text="Kopieer", style="Accent.TButton",
                    command=self._copy).pack(side="right")

        self.refresh()

    def refresh(self) -> None:
        self._entries = history_mod.load()
        self._populate()

    def _on_toggle(self) -> None:
        self._populate()
        self._show_detail()

    def _body(self, entry: dict) -> str:
        if self.show_raw.get():
            return entry.get("raw") or ""
        return entry.get("cleaned") or entry.get("raw") or ""

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self._entries):
            ts = (e.get("ts") or "").replace("T", "  ")[5:]  # drop the year
            text = " ".join(self._body(e).split())
            if not self.show_raw.get() and not e.get("cleaned_applied"):
                text += "   · niet opgeschoond"
            self.tree.insert("", "end", iid=str(i),
                              values=(ts, e.get("app") or "—", e.get("tone") or "—", text),
                              tags=("even" if i % 2 else "odd",))
        n = len(self._entries)
        self.count_label.configure(
            text="Nog niets gedicteerd." if not n else
                 f"{n} dictaat{'en' if n != 1 else ''}")
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
        else:
            self._set_detail("")

    def _selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self._entries[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _show_detail(self) -> None:
        entry = self._selected()
        self._set_detail(self._body(entry) if entry else "")

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _copy(self) -> None:
        entry = self._selected()
        if not entry:
            return
        if paste.set_clipboard_text(self._body(entry)):
            self.count_label.configure(text="Gekopieerd naar klembord.")
            self.frame.after(1800, self._populate)

    def _clear(self) -> None:
        if messagebox.askyesno("TalkWithMe", "Hele geschiedenis wissen?",
                                parent=self.frame):
            history_mod.clear()
            self.refresh()


# ----------------------------------------------------------------------
# Weekly report
# ----------------------------------------------------------------------

class ReportTab:
    """Scrollable dashboard: headline cubes, where the wait goes, the week,
    and a breakdown per destination.

    The point of the per-channel table is that averages hide the thing you
    can act on. "Two seconds of waiting" is not actionable; "Outlook is
    slow because those dictations are four times longer" is.
    """

    DAY_NAMES = ("ma", "di", "wo", "do", "vr", "za", "zo")
    CUBE_KEYS = ("saved", "dictations", "words", "wpm", "wait", "reliability")

    def __init__(self, parent: tk.Misc):
        self.frame = tk.Frame(parent, bg=theme.BG)
        self.week = self.total = None

        canvas = tk.Canvas(self.frame, bg=theme.BG, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self.frame, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=theme.BG)
        body.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                     lambda e: canvas.itemconfigure(window_id, width=e.width - 16))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                         lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self._body = body

        self._build_cubes(body)
        self._build_compare(body)
        self._build_quota(body)
        self._build_latency(body)
        self._build_week(body)
        self._build_channels(body)
        self._build_footer(body)

        self.refresh()

    # ---- layout ----------------------------------------------------

    def _build_cubes(self, body: tk.Misc) -> None:
        caps(body, "Deze week").pack(anchor="w")
        grid = tk.Frame(body, bg=theme.BG)
        grid.pack(fill="x", pady=(10, 0))
        for col in range(3):
            grid.columnconfigure(col, weight=1, uniform="cube")

        titles = {
            "saved": ("Bespaard", "tegenover typen"),
            "dictations": ("Dictaten", "deze week"),
            "words": ("Woorden", "uitgesproken"),
            "wpm": ("Spreektempo", "gemeten"),
            "wait": ("Wachttijd", "mediaan na loslaten"),
            "reliability": ("Op de cursor", "zonder omweg geplakt"),
        }
        self.cubes = {}
        for i, key in enumerate(self.CUBE_KEYS):
            title, sub = titles[key]
            cube = card(grid)
            cube.grid(row=i // 3, column=i % 3, sticky="nsew",
                       padx=(0 if i % 3 == 0 else 10, 0),
                       pady=(0 if i < 3 else 10, 0))
            inner = tk.Frame(cube, bg=theme.SURFACE)
            inner.pack(fill="both", expand=True, padx=18, pady=16)
            caps(inner, title, bg=theme.SURFACE).pack(anchor="w")
            value = label(inner, "—", font=theme.FONT_STAT, bg=theme.SURFACE)
            value.pack(anchor="w", pady=(7, 0))
            note = label(inner, sub, font=theme.FONT_UI_TINY,
                          fg=theme.TEXT_FAINT, bg=theme.SURFACE)
            note.pack(anchor="w", pady=(3, 0))
            self.cubes[key] = (value, note)

    def _build_quota(self, body: tk.Misc) -> None:
        """Only rendered when the key may read it; a key scoped to
        speech-to-text alone cannot, and an empty row beats an error."""
        self.quota_card = card(body)
        self.quota_inner = tk.Frame(self.quota_card, bg=theme.SURFACE)
        self.quota_inner.pack(fill="x", padx=theme.CARD_PAD, pady=16)

        left = tk.Frame(self.quota_inner, bg=theme.SURFACE)
        left.pack(side="left", fill="x", expand=True)
        caps(left, "Tegoed bij ElevenLabs", bg=theme.SURFACE).pack(anchor="w")
        self.quota_value = label(left, "", font=theme.FONT_SECTION, bg=theme.SURFACE)
        self.quota_value.pack(anchor="w", pady=(6, 0))
        self.quota_note = label(left, "", font=theme.FONT_UI_TINY,
                                 fg=theme.TEXT_FAINT, bg=theme.SURFACE)
        self.quota_note.pack(anchor="w", pady=(3, 0))

        self.quota_bar = tk.Canvas(self.quota_inner, height=8, width=220,
                                    bg=theme.SURFACE, highlightthickness=0, bd=0)
        self.quota_bar.pack(side="right", padx=(20, 0))

    def _refresh_quota(self) -> None:
        from . import quota as quota_mod
        from . import secrets_store

        left = quota_mod.fetch_or_none(secrets_store.get_elevenlabs_api_key())
        if left is None:
            self.quota_card.pack_forget()
            return
        self.quota_card.pack(fill="x", pady=(theme.GAP_L, 0), before=self.compare)

        self.quota_value.configure(
            text=f"{left.summary()}  ·  ongeveer {left.estimated_minutes:.0f} min",
            fg=theme.RED if left.is_low else theme.TEXT)
        bits = [f"tier: {left.tier}"]
        if left.reset_text():
            bits.append(left.reset_text())
        bits.append("minuten zijn een schatting")
        self.quota_note.configure(text="  ·  ".join(bits))

        c = self.quota_bar
        c.delete("all")
        w = int(c.cget("width"))
        c.create_polygon(theme.round_rect_points(0, 1, w, 7, 3), smooth=True,
                          fill=theme.mix(theme.BG, theme.BORDER, 0.6), outline="")
        filled = max(4, w * left.fraction_used)
        c.create_polygon(theme.round_rect_points(0, 1, filled, 7, 3), smooth=True,
                          fill=theme.RED if left.is_low else theme.ACCENT, outline="")

    def _build_compare(self, body: tk.Misc) -> None:
        caps(body, "Typen versus spreken").pack(anchor="w", pady=(theme.GAP_L, 10))
        self.compare = tk.Canvas(body, height=86, bg=theme.BG,
                                  highlightthickness=0, bd=0)
        self.compare.pack(fill="x")
        self.compare.bind("<Configure>", lambda e: self._draw_compare())

    def _build_latency(self, body: tk.Misc) -> None:
        caps(body, "Waar de wachttijd heen gaat").pack(anchor="w", pady=(theme.GAP_L, 4))
        self.latency_note = label(body, "", font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED)
        self.latency_note.pack(anchor="w", pady=(0, 10))
        self.latency = tk.Canvas(body, height=58, bg=theme.BG,
                                  highlightthickness=0, bd=0)
        self.latency.pack(fill="x")
        self.latency.bind("<Configure>", lambda e: self._draw_latency())

    def _build_week(self, body: tk.Misc) -> None:
        caps(body, "Bespaard per dag").pack(anchor="w", pady=(theme.GAP_L, 10))
        self.chart = tk.Canvas(body, height=140, bg=theme.BG,
                                highlightthickness=0, bd=0)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

    def _build_channels(self, body: tk.Misc) -> None:
        head = tk.Frame(body, bg=theme.BG)
        head.pack(fill="x", pady=(theme.GAP_L, 10))
        caps(head, "Per kanaal").pack(side="left")
        self.channel_mode = tk.StringVar(value="app")
        for text, value in (("App", "app"), ("Toon", "tone")):
            ttk.Radiobutton(head, text=text, value=value,
                             variable=self.channel_mode,
                             command=self._fill_channels).pack(side="right", padx=(10, 0))

        self.channels = ttk.Treeview(
            body, columns=("kanaal", "dictaten", "woorden", "lengte",
                            "bespaard", "wacht", "opgeschoond"),
            show="headings", selectmode="none", height=7)
        for col, text, width, anchor in (
            ("kanaal", "KANAAL", 190, "w"),
            ("dictaten", "DICTATEN", 80, "e"),
            ("woorden", "WOORDEN", 90, "e"),
            ("lengte", "GEM. LENGTE", 100, "e"),
            ("bespaard", "BESPAARD", 100, "e"),
            ("wacht", "WACHTTIJD", 100, "e"),
            ("opgeschoond", "OPGESCHOOND", 110, "e"),
        ):
            self.channels.heading(col, text=text, anchor=anchor)
            self.channels.column(col, width=width, anchor=anchor,
                                  stretch=(col == "kanaal"))
        self.channels.pack(fill="x")
        self.channels.tag_configure("odd", background=theme.SURFACE)
        self.channels.tag_configure("even", background=theme.SURFACE_ALT)

        self.insight = label(body, "", font=theme.FONT_UI_SMALL,
                              fg=theme.TEXT_MUTED, wraplength=760)
        self.insight.pack(anchor="w", pady=(12, 0))

    def _build_footer(self, body: tk.Misc) -> None:
        foot = tk.Frame(body, bg=theme.BG)
        foot.pack(fill="x", pady=(theme.GAP_L, 0))
        tk.Frame(foot, height=1, bg=theme.BORDER).pack(fill="x", pady=(0, 10))
        self.total_label = label(foot, "", font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED)
        self.total_label.pack(anchor="w")
        self.assump_label = label(foot, "", font=theme.FONT_UI_TINY,
                                   fg=theme.TEXT_FAINT, wraplength=760)
        self.assump_label.pack(anchor="w", pady=(3, 0))

    # ---- data ------------------------------------------------------

    def refresh(self) -> None:
        self.week, self.total = stats_mod.week_and_total()
        w, t = self.week, self.total

        saved_value, saved_unit = stats_mod.split_duration(w.saved_s)
        self._set_cube("saved", f"{saved_value} {saved_unit}",
                        f"{w.multiplier:.1f}x sneller dan typen" if w.multiplier > 1
                        else "tegenover typen")
        self._set_cube("dictations", str(w.dictations),
                        f"gem. {w.avg_words:.0f} woorden" if w.dictations else "deze week")
        self._set_cube("words", f"{w.words:,}".replace(",", "."), "uitgesproken")
        self._set_cube("wpm", f"{round(w.speaking_wpm)} wpm",
                        "gemeten" if w.measured_words else "geschat, nog niet gemeten")
        self._set_cube("wait", stats_mod.format_ms(w.median_wait_ms),
                        f"95e percentiel {stats_mod.format_ms(w.p95_wait_ms)}"
                        if w.total_ms else "mediaan na loslaten")
        self._set_cube("reliability", stats_mod.format_share(w.paste_share),
                        "zonder omweg geplakt" if w.dictations else "nog geen data")

        self.latency_note.configure(text=self._latency_sentence(w))
        self.total_label.configure(
            text=f"Sinds het begin: {stats_mod.format_duration(t.saved_s)} bespaard "
                 f"over {t.dictations} dictaten en {t.words:,} woorden.".replace(",", "."))
        self.assump_label.configure(
            text=f"Aanname: typen op {stats_mod.TYPING_WPM:.0f} wpm. Spreektijd is gemeten "
                 f"inclusief wachten op de tekst; waar geen opnameduur bekend is, gerekend "
                 f"aan {stats_mod.ASSUMED_SPEAKING_WPM:.0f} wpm. Wachttijden zijn medianen, "
                 f"niet gemiddelden: een enkele netwerkhapering zou een gemiddelde "
                 f"onbruikbaar maken.")

        self._fill_channels()
        self._refresh_quota()
        self._draw_compare()
        self._draw_latency()
        self._draw_chart()

    def _set_cube(self, key: str, value: str, note: str) -> None:
        value_label, note_label = self.cubes[key]
        value_label.configure(text=value)
        note_label.configure(text=note)

    def _latency_sentence(self, w) -> str:
        if not w.total_ms:
            return "Nog geen metingen deze week."
        return (f"Mediaan {stats_mod.format_ms(w.median_wait_ms)} tussen loslaten en tekst. "
                f"Transcriptie {stats_mod.format_ms(w.median_stt_ms)}, "
                f"opschonen {stats_mod.format_ms(w.median_cleanup_ms)}, "
                f"de rest {stats_mod.format_ms(w.median_overhead_ms)}.")

    def _fill_channels(self) -> None:
        if self.week is None:
            return
        bucket = (self.week.per_app if self.channel_mode.get() == "app"
                   else self.week.per_tone)
        rows = sorted(bucket.values(), key=lambda c: c.saved_s, reverse=True)

        self.channels.delete(*self.channels.get_children())
        for i, c in enumerate(rows[:12]):
            self.channels.insert(
                "", "end",
                values=(c.name, c.dictations, f"{c.words:,}".replace(",", "."),
                        f"{c.avg_words:.0f} w",
                        stats_mod.format_duration(c.saved_s, short=True),
                        stats_mod.format_ms(c.median_wait_ms),
                        stats_mod.format_share(c.cleaned_share)),
                tags=("even" if i % 2 else "odd",))
        self.insight.configure(text=self._insight(rows))

    def _insight(self, rows: list) -> str:
        """One concrete thing worth acting on, derived from the data rather
        than from a fixed list of tips."""
        if not rows:
            return "Nog niets gedicteerd deze week."

        w = self.week
        slow = [c for c in rows if c.median_wait_ms and c.dictations >= 3]
        if slow:
            worst = max(slow, key=lambda c: c.median_wait_ms)
            fastest = min(slow, key=lambda c: c.median_wait_ms)
            if worst.median_wait_ms > fastest.median_wait_ms * 1.6:
                return (f"{worst.name} wacht {stats_mod.format_ms(worst.median_wait_ms)} "
                        f"tegen {stats_mod.format_ms(fastest.median_wait_ms)} bij "
                        f"{fastest.name}. Dictaten zijn daar gemiddeld "
                        f"{worst.avg_words:.0f} woorden tegen {fastest.avg_words:.0f}: "
                        f"langere opnames kosten meer transcriptietijd.")

        if w.paste_share < 0.9 and w.dictations >= 3:
            return ("Niet alles belandt op de cursor. Kijk welke app het betreft: "
                    "Microsoft Store-apps weigeren gesimuleerde toetsaanslagen, "
                    "daar komt de tekst op het klembord terecht.")

        if w.cleanup_failure_share > 0.1:
            return (f"{stats_mod.format_share(w.cleanup_failure_share)} van het opschonen "
                    f"mislukte; dan wordt de ruwe transcriptie geplakt. Meestal een "
                    f"rate limit van de gratis tier.")

        if w.avg_words and w.avg_words < 12:
            return (f"Je dictaten zijn kort, gemiddeld {w.avg_words:.0f} woorden. "
                    f"De vaste wachttijd per dictaat weegt dan zwaar; langere stukken "
                    f"in één keer inspreken levert meer op.")

        if w.median_stt_ms > 1500:
            return (f"Transcriptie is met {stats_mod.format_ms(w.median_stt_ms)} het "
                    f"grootste deel van de wachttijd. Die tijd valt pas na het loslaten, "
                    f"omdat de audio nu in zijn geheel verstuurd wordt.")

        return "Geen opvallende knelpunten deze week."

    # ---- drawing ---------------------------------------------------

    def _draw_compare(self) -> None:
        if self.week is None:
            return
        c = self.compare
        c.delete("all")
        w = c.winfo_width() or 700
        track_x0 = 168
        track_x1 = max(track_x0 + 40, w - 92)
        track_w = track_x1 - track_x0
        peak = max(self.week.typing_s, self.week.speaking_s, 1.0)
        track_fill = theme.mix(theme.BG, theme.BORDER, 0.55)

        rows = (
            ("Typen", f"geschat op {stats_mod.TYPING_WPM:.0f} wpm",
             self.week.typing_s, theme.BORDER_STRONG, theme.TEXT_MUTED),
            ("Spreken", "werkelijk", self.week.speaking_s, theme.ACCENT, theme.TEXT),
        )
        for i, (name, note, seconds, color, text_color) in enumerate(rows):
            y = 16 + i * 42
            c.create_text(0, y, text=name, anchor="w", fill=text_color,
                           font=theme.FONT_SECTION)
            c.create_text(0, y + 16, text=note, anchor="w", fill=theme.TEXT_FAINT,
                           font=theme.FONT_UI_TINY)
            c.create_polygon(theme.round_rect_points(track_x0, y - 6, track_x1, y + 6, 6),
                              smooth=True, fill=track_fill, outline="")
            bar_w = max(8.0, (seconds / peak) * track_w)
            c.create_polygon(
                theme.round_rect_points(track_x0, y - 6, track_x0 + bar_w, y + 6, 6),
                smooth=True, fill=color, outline="")
            c.create_text(w, y, text=stats_mod.format_duration(seconds), anchor="e",
                           fill=text_color, font=theme.FONT_UI_SMALL)

    def _draw_latency(self) -> None:
        """One stacked bar: transcription, cleanup, everything else."""
        if self.week is None:
            return
        c = self.latency
        c.delete("all")
        w = c.winfo_width() or 700
        total = self.week.median_wait_ms
        if total <= 0:
            c.create_text(0, 20, text="Nog geen metingen.", anchor="w",
                           fill=theme.TEXT_FAINT, font=theme.FONT_UI_SMALL)
            return

        segments = (
            ("Transcriptie", self.week.median_stt_ms, theme.ACCENT),
            ("Opschonen", self.week.median_cleanup_ms, theme.ACCENT_SOFT),
            ("Overig", self.week.median_overhead_ms, theme.BORDER_STRONG),
        )
        x, y, h = 0.0, 6.0, 18.0
        for _, value, color in segments:
            if value <= 0:
                continue
            seg_w = (value / total) * w
            c.create_rectangle(x, y, x + seg_w, y + h, fill=color, outline="")
            x += seg_w

        legend_x = 0.0
        for name, value, color in segments:
            if value <= 0:
                continue
            c.create_oval(legend_x, 38, legend_x + 8, 46, fill=color, outline="")
            text = f"{name} {stats_mod.format_ms(value)}"
            c.create_text(legend_x + 13, 42, text=text, anchor="w",
                           fill=theme.TEXT_MUTED, font=theme.FONT_UI_TINY)
            legend_x += 13 + len(text) * 5.6 + 22

    def _draw_chart(self) -> None:
        if self.week is None:
            return
        c = self.chart
        c.delete("all")
        w = c.winfo_width() or 700
        h = 140

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        days = [monday + timedelta(days=i) for i in range(7)]
        values = [self.week.per_day.get(d, 0.0) for d in days]
        peak = max(values) if any(values) else 1.0

        slot = w / 7
        bar_w = min(38, slot * 0.42)
        base_y = h - 26
        max_h = base_y - 24

        c.create_line(0, base_y + 0.5, w, base_y + 0.5, fill=theme.BORDER)

        for i, (d, v) in enumerate(zip(days, values)):
            cx = slot * i + slot / 2
            future = d > today
            if v:
                bh = max(4.0, (v / peak) * max_h)
                color = theme.mix(theme.ACCENT_SOFT, theme.ACCENT_DEEP, v / peak)
            else:
                bh, color = 4.0, theme.BORDER
            c.create_polygon(
                theme.round_rect_points(cx - bar_w / 2, base_y - bh,
                                         cx + bar_w / 2, base_y, 5),
                smooth=True, fill=color, outline="")
            if v:
                c.create_text(cx, base_y - bh - 11,
                               text=stats_mod.format_duration(v, short=True),
                               fill=theme.TEXT, font=theme.FONT_UI_TINY)
            c.create_text(cx, base_y + 15, text=self.DAY_NAMES[i],
                           fill=theme.ACCENT if d == today else
                                (theme.TEXT_FAINT if future else theme.TEXT_MUTED),
                           font=theme.FONT_UI_TINY)


class MeetingsTab:
    """Record a meeting, then read back the notes and the transcript.

    The transcript sits beside the notes rather than being thrown away: a
    summary is an interpretation, and the only way to check one is against
    what was actually said.
    """

    def __init__(self, parent: tk.Misc, controller):
        self.frame = tk.Frame(parent, bg=theme.BG)
        self.controller = controller       # the App, for start/stop
        self._meetings: list = []
        self._notes = ""
        self._transcript = ""

        bar = card(self.frame)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=theme.SURFACE)
        inner.pack(fill="x", padx=18, pady=14)

        text_col = tk.Frame(inner, bg=theme.SURFACE)
        text_col.pack(side="left", fill="x", expand=True)
        self.status = label(text_col, "Klaar om op te nemen",
                             font=theme.FONT_SECTION, bg=theme.SURFACE)
        self.status.pack(anchor="w")
        label(text_col,
               "Ook zonder de app: houd Ctrl+Win vast en tik M.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED,
               bg=theme.SURFACE).pack(anchor="w", pady=(3, 0))

        self.record_button = ttk.Button(inner, text="Vergadering opnemen",
                                         style="Accent.TButton",
                                         command=self._toggle_recording)
        self.record_button.pack(side="right")

        split = tk.Frame(self.frame, bg=theme.BG)
        split.pack(fill="both", expand=True, pady=(theme.GAP, 0))

        left = tk.Frame(split, bg=theme.BG, width=230)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        caps(left, "Vergaderingen").pack(anchor="w", pady=(0, 6))
        self.listing = ttk.Treeview(left, columns=("wanneer",), show="headings",
                                     selectmode="browse")
        self.listing.heading("wanneer", text="WANNEER", anchor="w")
        self.listing.column("wanneer", width=210, anchor="w")
        self.listing.pack(fill="both", expand=True)
        self.listing.bind("<<TreeviewSelect>>", lambda e: self._show_selected())
        self.listing.tag_configure("odd", background=theme.SURFACE)
        self.listing.tag_configure("even", background=theme.SURFACE_ALT)

        right = tk.Frame(split, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True, padx=(theme.GAP, 0))

        head = tk.Frame(right, bg=theme.BG)
        head.pack(fill="x", pady=(0, 6))
        self.view_mode = tk.StringVar(value="notes")
        for text, value in (("Notities", "notes"), ("Transcript", "transcript")):
            ttk.Radiobutton(head, text=text, value=value, variable=self.view_mode,
                             command=self._render).pack(side="left", padx=(0, 12))
        ttk.Button(head, text="Verwijderen", command=self._delete).pack(side="right")
        ttk.Button(head, text="Exporteren", command=self._export).pack(side="right", padx=8)

        box = tk.Frame(right, bg=theme.BORDER)
        box.pack(fill="both", expand=True)
        self.view = tk.Text(box, wrap="word", font=theme.FONT_BODY,
                             bg=theme.SURFACE, fg=theme.TEXT, relief="flat",
                             padx=16, pady=14, bd=0,
                             selectbackground=theme.ACCENT_WASH,
                             selectforeground=theme.TEXT)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.view.yview)
        self.view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.view.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.view.tag_configure("h1", font=("Segoe UI Semibold", 13),
                                 spacing1=10, spacing3=6)
        self.view.tag_configure("h2", font=("Segoe UI Semibold", 11),
                                 foreground=theme.ACCENT, spacing1=14, spacing3=5)
        self.view.tag_configure("bullet", lmargin1=18, lmargin2=32, spacing3=3)
        self.view.tag_configure("speaker", foreground=theme.TEXT_FAINT)
        self.view.tag_configure("muted", foreground=theme.TEXT_MUTED)
        self.view.configure(state="disabled")

        note_head = tk.Frame(right, bg=theme.BG)
        note_head.pack(fill="x", pady=(theme.GAP, 4))
        caps(note_head, "Jouw notities tijdens de vergadering").pack(side="left")
        label(note_head, "worden achteraf aangevuld met het transcript",
               font=theme.FONT_UI_TINY, fg=theme.TEXT_FAINT).pack(side="left", padx=(8, 0))

        draft_box = tk.Frame(right, bg=theme.BORDER)
        draft_box.pack(fill="x")
        self.draft = tk.Text(draft_box, wrap="word", height=5, font=theme.FONT_BODY,
                              bg=theme.SURFACE, fg=theme.TEXT, relief="flat",
                              insertbackground=theme.TEXT, padx=16, pady=12, bd=0,
                              selectbackground=theme.ACCENT_WASH,
                              selectforeground=theme.TEXT)
        self.draft.pack(fill="x", padx=1, pady=1)
        self.draft.bind("<KeyRelease>", lambda e: self._sync_draft())

        self.refresh()
        self._tick()

    def _show_live_transcript(self, recorder) -> None:
        """While recording, the pane shows the transcript as it arrives —
        the reason for streaming is that you can watch it happen."""
        streamer = getattr(recorder, "transcriber", None)
        if streamer is None:
            return
        text = streamer.live_text
        if text == getattr(self, "_last_live", None):
            return
        self._last_live = text
        self.view_mode.set("transcript")
        self.view.configure(state="normal")
        self.view.delete("1.0", "end")
        self.view.insert("end", text or "Luistert mee...", "" if text else "muted")
        self.view.see("end")
        self.view.configure(state="disabled")

    def _sync_draft(self) -> None:
        """Keep the controller's copy current: the meeting can also be
        stopped from the tray or the keyboard, with this window closed."""
        try:
            self.controller.meeting_notes_draft = self.draft.get("1.0", "end").strip()
        except Exception:
            pass

    # ---- recording -------------------------------------------------

    def _toggle_recording(self) -> None:
        if not self.controller.meeting_recorder.recording:
            self._sync_draft()
        self.controller.toggle_meeting()
        if not self.controller.meeting_recorder.recording:
            self.draft.delete("1.0", "end")

    def _tick(self) -> None:
        """Keep the button and status in step with the recorder, which can
        also be driven from the tray or the keyboard."""
        try:
            recorder = self.controller.meeting_recorder
            if recorder.recording:
                elapsed = int(recorder.elapsed_s())
                sources = "jij en de anderen" if recorder.system_audio else "alleen je microfoon"
                self.status.configure(
                    text=f"Opname loopt  ·  {elapsed // 60}:{elapsed % 60:02d}  ·  {sources}")
                self.record_button.configure(text="Stoppen en uitwerken")
                self.draft.configure(state="normal")
                self._show_live_transcript(recorder)
            else:
                busy = getattr(self.controller, "meeting_busy", False)
                self.status.configure(text="Bezig met uitwerken..." if busy
                                       else "Klaar om op te nemen")
                self.record_button.configure(text="Vergadering opnemen")
        except Exception:
            pass
        finally:
            self.frame.after(500, self._tick)

    # ---- data ------------------------------------------------------

    def refresh(self) -> None:
        from . import meetings as meetings_mod

        selected = self._selected_stamp()
        self._meetings = meetings_mod.list_meetings()
        self.listing.delete(*self.listing.get_children())
        for i, m in enumerate(self._meetings):
            self.listing.insert("", "end", iid=m.stamp, values=(m.label,),
                                 tags=("even" if i % 2 else "odd",))

        target = selected if selected in {m.stamp for m in self._meetings} else None
        if target is None and self._meetings:
            target = self._meetings[0].stamp
        if target:
            self.listing.selection_set(target)
            self.listing.focus(target)
        else:
            self._notes = self._transcript = ""
            self._render()

    def _selected_stamp(self) -> str | None:
        selection = self.listing.selection()
        return selection[0] if selection else None

    def _selected(self):
        stamp = self._selected_stamp()
        return next((m for m in self._meetings if m.stamp == stamp), None)

    def _show_selected(self) -> None:
        from . import meetings as meetings_mod

        meeting = self._selected()
        if meeting is None:
            self._notes = self._transcript = ""
        else:
            self._notes, self._transcript = meetings_mod.read_meeting(meeting)
        self._render()

    # ---- rendering -------------------------------------------------

    def _render(self) -> None:
        showing_notes = self.view_mode.get() == "notes"
        content = self._notes if showing_notes else self._transcript

        self.view.configure(state="normal")
        self.view.delete("1.0", "end")

        if not content.strip():
            self.view.insert("end",
                              "Nog geen vergaderingen opgenomen."
                              if not self._meetings else
                              "Geen transcript bewaard bij deze vergadering.",
                              "muted")
        elif showing_notes:
            self._render_markdown(content)
        else:
            self._render_transcript(content)
        self.view.configure(state="disabled")

    def _render_markdown(self, text: str) -> None:
        """Just enough markdown for what write_notes produces."""
        for raw in text.split("\n"):
            line = raw.rstrip()
            stripped = line.strip()
            if stripped.startswith("## "):
                self.view.insert("end", stripped[3:] + "\n", "h2")
            elif stripped.startswith("# "):
                self.view.insert("end", stripped[2:] + "\n", "h1")
            elif stripped in ("---", "***"):
                self.view.insert("end", "\n")
            elif stripped.startswith(("- ", "* ")):
                self.view.insert("end", "•  " + _strip_emphasis(stripped[2:]) + "\n",
                                  "bullet")
            else:
                self.view.insert("end", _strip_emphasis(line) + "\n")

    def _render_transcript(self, text: str) -> None:
        for line in text.split("\n"):
            speaker, sep, said = line.partition(": ")
            if sep and len(speaker) < 40:
                self.view.insert("end", speaker + ": ", "speaker")
                self.view.insert("end", said + "\n")
            else:
                self.view.insert("end", line + "\n")

    # ---- actions ---------------------------------------------------

    def _export(self) -> None:
        from tkinter import filedialog

        from . import export as export_mod

        meeting = self._selected()
        if meeting is None or not self._notes.strip():
            messagebox.showinfo("TalkWithMe", "Selecteer eerst een vergadering.",
                                 parent=self.frame)
            return

        path = filedialog.asksaveasfilename(
            parent=self.frame, title="Notities exporteren",
            initialfile=f"vergadering_{meeting.stamp}",
            defaultextension=".pdf",
            filetypes=[(name, f"*{ext}") for name, ext in export_mod.FORMATS])
        if not path:
            return

        markdown = self._notes
        if self.view_mode.get() == "transcript" and self._transcript:
            markdown = f"## Transcript\n\n{self._transcript}"
        try:
            export_mod.export(markdown, path, source_path=meeting.notes_path,
                               title=f"Vergadering {meeting.label}")
        except Exception as e:
            log.exception("exporteren mislukt")
            messagebox.showerror("TalkWithMe", f"Exporteren mislukt:\n{e}",
                                  parent=self.frame)
            return
        import os
        os.startfile(os.path.dirname(path))

    def _delete(self) -> None:
        from . import meetings as meetings_mod

        meeting = self._selected()
        if meeting is None:
            return
        if not messagebox.askyesno(
                "TalkWithMe",
                f"Vergadering van {meeting.label} verwijderen?\n"
                f"De opname en de notities gaan allebei weg.",
                parent=self.frame):
            return
        meetings_mod.delete_meeting(meeting)
        self.refresh()


def _strip_emphasis(text: str) -> str:
    return text.replace("**", "").replace("`", "")


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------

class SettingsTab:
    def __init__(self, parent: tk.Misc, config, on_save):
        self.config = config
        self.on_save = on_save
        self.frame = tk.Frame(parent, bg=theme.BG)

        # Scrollable: this tab is taller than the window on a laptop screen.
        canvas = tk.Canvas(self.frame, bg=theme.BG, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self.frame, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=theme.BG)
        body.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                     lambda e: canvas.itemconfigure(window_id, width=e.width - 18))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                         lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        # --- keys ---------------------------------------------------
        caps(body, "API-keys").pack(anchor="w")
        label(body, "Bewaard in Windows Credential Manager — nooit in een bestand.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 8))

        self.el_var = tk.StringVar(value=secrets_store.get_elevenlabs_api_key() or "")
        self.el_entry = self._field(body, "ElevenLabs  ·  spraak naar tekst", self.el_var)
        self.gm_var = tk.StringVar(value=secrets_store.get_gemini_api_key() or "")
        self.gm_entry = self._field(body, "Gemini  ·  opschonen", self.gm_var)

        self.show_keys = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Keys tonen", variable=self.show_keys,
                         command=self._toggle_key_visibility).pack(anchor="w", pady=(8, 0))

        self._divider(body)

        # --- language --------------------------------------------------
        caps(body, "Taal").pack(anchor="w")
        label(body,
               "Automatisch werkt slecht bij korte zinnen: de transcriptie kiest per"
               "\nfragment een taal en kan er dan naast zitten. Engelse woorden in een"
               "\nNederlandse zin blijven gewoon staan.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 8))
        self._language_codes = ["nl", "en", "fr", "de", "es", "auto"]
        labels = ["Nederlands", "Engels", "Frans", "Duits", "Spaans",
                   "Automatisch (afgeraden)"]
        self.language_combo = ttk.Combobox(body, state="readonly", width=30,
                                            values=labels)
        current = getattr(config, "language", "nl")
        self.language_combo.current(self._language_codes.index(current)
                                     if current in self._language_codes else 0)
        self.language_combo.pack(anchor="w")

        self._divider(body)

        # --- cleanup ------------------------------------------------
        self._divider(body)

        # --- updates ------------------------------------------------
        caps(body, "Updates").pack(anchor="w")
        label(body, "Versie " + __version__ +
               "  ·  nieuwe versies komen van GitHub Releases.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 0))
        self.repo_var = tk.StringVar(value=getattr(config, "update_repo", ""))
        self._field_plain(body, "GitHub-repository  ·  bijvoorbeeld jouwnaam/talkwithme",
                           self.repo_var)
        self.update_check_var = tk.BooleanVar(
            value=getattr(config, "update_check_enabled", True))
        ttk.Checkbutton(body, text="Bij het opstarten controleren op updates",
                         variable=self.update_check_var).pack(anchor="w", pady=(10, 0))

        caps(body, "Opschonen").pack(anchor="w")
        self.cleanup_var = tk.BooleanVar(value=config.cleanup_enabled)
        ttk.Checkbutton(body, text="Mijn spraak opschonen",
                         variable=self.cleanup_var).pack(anchor="w", pady=(8, 2))
        label(body, "Uit = de ruwe transcriptie wordt geplakt.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w")

        self._divider(body)

        # --- tone ---------------------------------------------------
        caps(body, "Toon per app").pack(anchor="w")
        self.tone_var = tk.BooleanVar(value=config.tone_enabled)
        ttk.Checkbutton(body, text="Toon aanpassen aan de app",
                         variable=self.tone_var,
                         command=self._on_tone_toggle).pack(anchor="w", pady=(8, 2))
        label(body,
               "Chat wordt kort en informeel, e-mail netjes, terminal letterlijk.\n"
               "Dit overschrijft bewust de regel over formaliteit behouden.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w")

        tone_row = tk.Frame(body, bg=theme.BG)
        tone_row.pack(fill="x", pady=(theme.GAP, 8))
        label(tone_row, "Bewerk toon:", font=theme.FONT_UI_SMALL,
               fg=theme.TEXT_MUTED).pack(side="left", padx=(0, 10))
        self._tone_keys = list(tones_mod.DEFAULT_TONE_INSTRUCTIONS)
        self.tone_combo = ttk.Combobox(
            tone_row, state="readonly", width=40,
            values=[tones_mod.TONE_LABELS[k] for k in self._tone_keys])
        self.tone_combo.pack(side="left")
        self.tone_combo.current(0)
        self.tone_combo.bind("<<ComboboxSelected>>", lambda e: self._load_tone_text())

        self.tone_text = self._textbox(body, height=6)
        self._tone_edits = dict(config.tone_instructions)
        self._loaded_tone_key = None
        self._load_tone_text()
        self._on_tone_toggle()

        self._divider(body)

        # --- base instructions --------------------------------------
        caps(body, "Instructies aan het model").pack(anchor="w")
        label(body, "Wordt woord-voor-woord meegestuurd.",
               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w", pady=(4, 8))
        self.text = self._textbox(body, height=13)
        self.text.insert("1.0", config.cleanup_instructions)

        btns = tk.Frame(body, bg=theme.BG)
        btns.pack(fill="x", pady=(theme.GAP, 4))
        ttk.Button(btns, text="Herstel standaard",
                    command=self._restore_default).pack(side="left")
        self.status = label(btns, "", font=theme.FONT_UI_SMALL, fg=theme.GREEN)
        self.status.pack(side="left", padx=14)
        ttk.Button(btns, text="Opslaan", style="Accent.TButton",
                    command=self._save).pack(side="right")

    # ---- helpers ---------------------------------------------------

    def _divider(self, parent: tk.Misc) -> None:
        tk.Frame(parent, height=1, bg=theme.BORDER).pack(fill="x", pady=theme.GAP_L)

    def _field(self, parent, text: str, var: tk.StringVar) -> ttk.Entry:
        label(parent, text, font=theme.FONT_UI_SMALL,
               fg=theme.TEXT_MUTED).pack(anchor="w", pady=(10, 4))
        entry = ttk.Entry(parent, textvariable=var, show="•", font=theme.FONT_UI)
        entry.pack(fill="x")
        return entry

    def _field_plain(self, parent, text: str, var: tk.StringVar) -> ttk.Entry:
        label(parent, text, font=theme.FONT_UI_SMALL,
               fg=theme.TEXT_MUTED).pack(anchor="w", pady=(10, 4))
        entry = ttk.Entry(parent, textvariable=var, font=theme.FONT_UI)
        entry.pack(fill="x")
        return entry

    def _textbox(self, parent: tk.Misc, height: int) -> tk.Text:
        box = tk.Frame(parent, bg=theme.BORDER)
        box.pack(fill="x", pady=(0, 0))
        widget = tk.Text(box, height=height, wrap="word", font=theme.FONT_MONO,
                          bg=theme.SURFACE, fg=theme.TEXT, insertbackground=theme.TEXT,
                          relief="flat", padx=14, pady=12, bd=0,
                          selectbackground=theme.ACCENT_DEEP)
        widget.pack(fill="both", expand=True, padx=1, pady=1)
        return widget

    def refresh(self) -> None:
        """Tabs are refreshed on entry; settings hold live edits, so this
        deliberately leaves the fields alone."""
        return

    def _toggle_key_visibility(self) -> None:
        show = "" if self.show_keys.get() else "•"
        self.el_entry.configure(show=show)
        self.gm_entry.configure(show=show)

    def _current_tone_key(self) -> str:
        idx = self.tone_combo.current()
        return self._tone_keys[idx if idx >= 0 else 0]

    def _load_tone_text(self) -> None:
        self._stash_tone_text()
        key = self._current_tone_key()
        was_disabled = str(self.tone_text.cget("state")) == "disabled"
        if was_disabled:
            self.tone_text.configure(state="normal")
        self.tone_text.delete("1.0", "end")
        self.tone_text.insert("1.0", self._tone_edits.get(
            key, tones_mod.DEFAULT_TONE_INSTRUCTIONS.get(key, "")))
        if was_disabled:
            self.tone_text.configure(state="disabled")
        self._loaded_tone_key = key

    def _stash_tone_text(self) -> None:
        """Keep edits to the tone being navigated away from, so switching
        the dropdown doesn't silently discard them."""
        if self._loaded_tone_key:
            self._tone_edits[self._loaded_tone_key] = self.tone_text.get("1.0", "end").strip()

    def _on_tone_toggle(self) -> None:
        enabled = self.tone_var.get()
        self.tone_text.configure(state="normal" if enabled else "disabled",
                                  bg=theme.SURFACE if enabled else theme.BG,
                                  fg=theme.TEXT if enabled else theme.TEXT_FAINT)
        self.tone_combo.configure(state="readonly" if enabled else "disabled")

    def _restore_default(self) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", prompts.DEFAULT_CLEANUP)
        self._tone_edits = dict(tones_mod.DEFAULT_TONE_INSTRUCTIONS)
        self._loaded_tone_key = None
        self._load_tone_text()
        self.status.configure(text="Standaard hersteld — nog niet opgeslagen.",
                               fg=theme.AMBER)

    def _save(self) -> None:
        try:
            el = self.el_var.get().strip()
            gm = self.gm_var.get().strip()
            if el:
                secrets_store.set_elevenlabs_api_key(el)
            if gm:
                secrets_store.set_gemini_api_key(gm)
            instructions = self.text.get("1.0", "end").strip() or prompts.DEFAULT_CLEANUP
            self._stash_tone_text()
            self.config.update_check_enabled = self.update_check_var.get()
            index = self.language_combo.current()
            if index >= 0:
                self.config.language = self._language_codes[index]
            self.on_save(self.cleanup_var.get(), instructions,
                          self.tone_var.get(), dict(self._tone_edits),
                          self.repo_var.get())
            self.status.configure(text="Opgeslagen.", fg=theme.GREEN)
            self.frame.after(2500, lambda: self.status.configure(text=""))
        except Exception as e:
            log.exception("opslaan van instellingen mislukt")
            messagebox.showerror("TalkWithMe", f"Opslaan mislukt: {e}", parent=self.frame)
