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

TAB_HISTORY, TAB_REPORT, TAB_SETTINGS = 0, 1, 2
TAB_NAMES = ("Geschiedenis", "Weekrapport", "Instellingen")


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
    def open(cls, root: tk.Tk, config, on_save, tab: int = TAB_HISTORY) -> "MainWindow":
        inst = cls._instance
        if inst is not None and inst.win.winfo_exists():
            inst.show(tab)
            return inst
        inst = cls(root, config, on_save)
        cls._instance = inst
        inst.show(tab)
        return inst

    def __init__(self, root: tk.Tk, config, on_save):
        self.config = config

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
    DAY_NAMES = ("ma", "di", "wo", "do", "vr", "za", "zo")

    def __init__(self, parent: tk.Misc):
        self.frame = tk.Frame(parent, bg=theme.BG)
        self.week = self.total = None

        # ---- hero: the one number this screen exists for ------------
        hero = card(self.frame)
        hero.pack(fill="x")
        hero_in = tk.Frame(hero, bg=theme.SURFACE)
        hero_in.pack(fill="x", padx=theme.CARD_PAD, pady=theme.CARD_PAD)

        left = tk.Frame(hero_in, bg=theme.SURFACE)
        left.pack(side="left", anchor="n")
        caps(left, "Deze week bespaard", bg=theme.SURFACE).pack(anchor="w")

        value_row = tk.Frame(left, bg=theme.SURFACE)
        value_row.pack(anchor="w", pady=(6, 0))
        self.hero_value = label(value_row, "—", font=theme.FONT_HERO,
                                 fg=theme.TEXT, bg=theme.SURFACE)
        self.hero_value.pack(side="left")
        self.hero_unit = label(value_row, "", font=theme.FONT_HERO_UNIT,
                                fg=theme.TEXT_MUTED, bg=theme.SURFACE)
        self.hero_unit.pack(side="left", anchor="s", padx=(9, 0), pady=(0, 11))

        self.hero_sub = label(left, "", font=theme.FONT_UI_SMALL,
                               fg=theme.TEXT_MUTED, bg=theme.SURFACE)
        self.hero_sub.pack(anchor="w", pady=(2, 0))

        right = tk.Frame(hero_in, bg=theme.SURFACE)
        right.pack(side="right", anchor="n")
        self.stat_cells = {}
        for key, title in (("dictations", "Dictaten"),
                            ("words", "Woorden"),
                            ("wpm", "Jouw tempo")):
            cell = tk.Frame(right, bg=theme.SURFACE)
            cell.pack(side="left", padx=(30, 0))
            caps(cell, title, bg=theme.SURFACE).pack(anchor="e")
            val = label(cell, "—", font=theme.FONT_STAT, bg=theme.SURFACE)
            val.configure(anchor="e")
            val.pack(anchor="e", pady=(5, 0))
            self.stat_cells[key] = val

        # ---- the comparison that makes the win legible --------------
        caps(self.frame, "Typen versus spreken").pack(anchor="w", pady=(theme.GAP_L, 10))
        self.compare = tk.Canvas(self.frame, height=86, bg=theme.BG,
                                  highlightthickness=0, bd=0)
        self.compare.pack(fill="x")
        self.compare.bind("<Configure>", lambda e: self._draw_compare())

        # ---- per day -------------------------------------------------
        caps(self.frame, "Bespaard per dag").pack(anchor="w", pady=(theme.GAP_L, 10))
        self.chart = tk.Canvas(self.frame, height=140, bg=theme.BG,
                                highlightthickness=0, bd=0)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

        # ---- per app -------------------------------------------------
        caps(self.frame, "Waar").pack(anchor="w", pady=(theme.GAP_L, 8))
        self.apps_frame = tk.Frame(self.frame, bg=theme.BG)
        self.apps_frame.pack(fill="x")

        foot = tk.Frame(self.frame, bg=theme.BG)
        foot.pack(fill="x", side="bottom", pady=(theme.GAP, 0))
        tk.Frame(foot, height=1, bg=theme.BORDER).pack(fill="x", pady=(0, 10))
        self.total_label = label(foot, "", font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED)
        self.total_label.pack(anchor="w")
        self.assump_label = label(foot, "", font=theme.FONT_UI_TINY, fg=theme.TEXT_FAINT)
        self.assump_label.pack(anchor="w", pady=(3, 0))

        self.refresh()

    def refresh(self) -> None:
        self.week, self.total = stats_mod.week_and_total()
        w, t = self.week, self.total

        value, unit = stats_mod.split_duration(w.saved_s)
        self.hero_value.configure(text=value)
        self.hero_unit.configure(text=unit)
        if w.dictations and w.multiplier > 1:
            self.hero_sub.configure(
                text=f"Spreken ging {w.multiplier:.1f}× sneller dan typen.")
        else:
            self.hero_sub.configure(text="Nog geen dictaten deze week.")

        self.stat_cells["dictations"].configure(text=str(w.dictations))
        self.stat_cells["words"].configure(text=f"{w.words:,}".replace(",", "."))
        self.stat_cells["wpm"].configure(text=f"{round(w.speaking_wpm)} wpm")

        self.total_label.configure(
            text=f"Sinds het begin: {stats_mod.format_duration(t.saved_s)} bespaard "
                 f"over {t.dictations} dictaten en {t.words:,} woorden.".replace(",", "."))
        self.assump_label.configure(
            text=f"Aanname: typen op {stats_mod.TYPING_WPM:.0f} wpm. Spreektijd is gemeten "
                 f"(inclusief wachten op de tekst); waar geen opnameduur bekend is, "
                 f"gerekend aan {stats_mod.ASSUMED_SPEAKING_WPM:.0f} wpm.")

        for child in self.apps_frame.winfo_children():
            child.destroy()
        apps = sorted(w.per_app.items(), key=lambda kv: kv[1], reverse=True)[:5]
        if not apps:
            label(self.apps_frame, "Nog niets deze week.",
                   font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED).pack(anchor="w")
        peak = apps[0][1] if apps else 1.0
        for name, saved in apps:
            row = tk.Frame(self.apps_frame, bg=theme.BG)
            row.pack(fill="x", pady=3)
            label(row, name, font=theme.FONT_UI_SMALL, fg=theme.TEXT,
                   width=20).pack(side="left")
            value_lbl = label(row, stats_mod.format_duration(saved),
                               font=theme.FONT_UI_SMALL, fg=theme.TEXT_MUTED, width=12)
            value_lbl.configure(anchor="e")
            value_lbl.pack(side="right")
            bar = tk.Canvas(row, height=8, bg=theme.BG, highlightthickness=0, bd=0)
            bar.pack(side="left", fill="x", expand=True, padx=(8, 12))
            bar.bind("<Configure>",
                      lambda e, b=bar, v=saved, p=peak: self._draw_app_bar(b, v, p))

        self._draw_compare()
        self._draw_chart()

    # ---- drawing ---------------------------------------------------

    def _draw_app_bar(self, bar: tk.Canvas, value: float, peak: float) -> None:
        bar.delete("all")
        w = bar.winfo_width() or 200
        frac = (value / peak) if peak else 0.0
        bar.create_polygon(theme.round_rect_points(0, 1, max(6, w * frac), 7, 3),
                            smooth=True, fill=theme.ACCENT, outline="")

    def _draw_compare(self) -> None:
        """Two bars on a shared scale: what typing would have cost, against
        what speaking actually cost. The gap is the point of the screen."""
        if self.week is None:
            return
        c = self.compare
        c.delete("all")
        w = c.winfo_width() or 700
        label_w, value_w = 168, 92
        track_x0 = label_w
        track_x1 = max(track_x0 + 40, w - value_w)
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
                # Taller bars sit deeper in the blurple, so the week's peak
                # reads instantly without needing to compare labels.
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
                           fill=theme.ACCENT_SOFT if d == today else
                                (theme.TEXT_FAINT if future else theme.TEXT_MUTED),
                           font=theme.FONT_UI_TINY)


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
            self.on_save(self.cleanup_var.get(), instructions,
                          self.tone_var.get(), dict(self._tone_edits),
                          self.repo_var.get())
            self.status.configure(text="Opgeslagen.", fg=theme.GREEN)
            self.frame.after(2500, lambda: self.status.configure(text=""))
        except Exception as e:
            log.exception("opslaan van instellingen mislukt")
            messagebox.showerror("TalkWithMe", f"Opslaan mislukt: {e}", parent=self.frame)
