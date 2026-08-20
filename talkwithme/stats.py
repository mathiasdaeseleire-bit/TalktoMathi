"""How much time dictating saved over typing, derived from the history log.

Modelled in words per minute, the way dictation tools conventionally
report it, because it survives missing data: entries logged before the app
recorded durations still have a word count.

    typing time    = words / TYPING_WPM          what it would have cost
    speaking time  = measured, or words / ASSUMED_SPEAKING_WPM when the
                     recording duration wasn't logged
    saved          = typing - speaking, floored at 0 per dictation

The assumptions are stated in the UI rather than hidden, because they are
the whole basis of the number:
  - TYPING_WPM 40 — a competent non-touch-typist on a full keyboard.
    Someone who touch-types at 80 saves roughly half as much.
  - Processing latency counts against the dictation: waiting for the text
    to appear is time not spent working.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import history as history_mod

TYPING_WPM = 40.0             # assumed typing speed
ASSUMED_SPEAKING_WPM = 150.0  # fallback when a duration wasn't recorded


@dataclass
class Period:
    label: str
    dictations: int = 0
    words: int = 0
    typing_s: float = 0.0
    speaking_s: float = 0.0
    measured_words: int = 0     # words whose speaking time was really measured
    measured_s: float = 0.0
    per_day: dict = field(default_factory=lambda: defaultdict(float))
    per_app: dict = field(default_factory=lambda: defaultdict(float))

    @property
    def saved_s(self) -> float:
        return max(0.0, self.typing_s - self.speaking_s)

    @property
    def speaking_wpm(self) -> float:
        """The user's real speaking rate, when there's data for it."""
        if self.measured_s <= 0 or self.measured_words <= 0:
            return ASSUMED_SPEAKING_WPM
        return self.measured_words / (self.measured_s / 60.0)

    @property
    def multiplier(self) -> float:
        if self.speaking_s <= 0:
            return 0.0
        return self.typing_s / self.speaking_s


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _text_of(entry: dict) -> str:
    return entry.get("cleaned") or entry.get("raw") or ""


def summarise(entries: list[dict], since: date | None, label: str,
              typing_wpm: float = TYPING_WPM) -> Period:
    p = Period(label=label)
    for e in entries:
        ts = _parse_ts(e.get("ts", ""))
        if ts is None or (since is not None and ts.date() < since):
            continue
        words = len(_text_of(e).split())
        if not words:
            continue

        typing = words / typing_wpm * 60.0
        record_s = float(e.get("record_s") or 0.0)
        process_s = float(e.get("process_ms") or 0) / 1000.0
        if record_s > 0:
            speaking = record_s + process_s
            p.measured_words += words
            p.measured_s += record_s
        else:
            # Logged before durations were recorded: estimate from words.
            speaking = words / ASSUMED_SPEAKING_WPM * 60.0 + process_s

        p.dictations += 1
        p.words += words
        p.typing_s += typing
        p.speaking_s += speaking
        p.per_day[ts.date()] += max(0.0, typing - speaking)
        p.per_app[e.get("app") or "—"] += max(0.0, typing - speaking)
    return p


def week_and_total(typing_wpm: float = TYPING_WPM) -> tuple[Period, Period]:
    """This week (from Monday) and all time."""
    entries = history_mod.load(limit=100000)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return (
        summarise(entries, monday, "Deze week", typing_wpm),
        summarise(entries, None, "Sinds het begin", typing_wpm),
    )


def format_duration(seconds: float, short: bool = False) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s" if short else f"{seconds} sec"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        if short:
            return f"{minutes}m"
        return f"{minutes} min" if sec < 30 else f"{minutes} min {sec} sec"
    hours, minutes = divmod(minutes, 60)
    if short:
        return f"{hours}u{minutes:02d}" if minutes else f"{hours}u"
    return f"{hours} u {minutes} min" if minutes else f"{hours} u"


def split_duration(seconds: float) -> tuple[str, str]:
    """Value and unit separately, so the UI can typeset them differently."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return str(seconds), "seconden"
    minutes = seconds // 60
    if minutes < 60:
        return str(minutes), "minuten" if minutes != 1 else "minuut"
    hours = minutes / 60.0
    text = f"{hours:.1f}".rstrip("0").rstrip(".")
    return text, "uur"
