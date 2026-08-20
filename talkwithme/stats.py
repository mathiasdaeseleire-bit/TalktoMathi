"""What the report needs to answer: how much time did dictating save, and
where is the remaining time going.

Time saved is modelled in words per minute, the way dictation tools
conventionally report it, because it survives missing data: entries logged
before the app recorded durations still have a word count.

    typing time    = words / TYPING_WPM          what it would have cost
    speaking time  = measured, or words / ASSUMED_SPEAKING_WPM when the
                     recording duration wasn't logged
    saved          = typing - speaking, floored at 0 per dictation

The assumptions are stated in the UI rather than hidden, because they are
the whole basis of the number:
  - TYPING_WPM 40 — a competent non-touch-typist on a full keyboard.
    Someone who touch-types at 80 saves roughly half as much.
  - Waiting counts against the dictation: the seconds between releasing
    the keys and seeing text are time not spent working.

Latency is reported as a median and a 95th percentile rather than a mean.
One 30-second network stall would drag a mean somewhere that describes no
actual dictation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import history as history_mod

TYPING_WPM = 40.0             # assumed typing speed
ASSUMED_SPEAKING_WPM = 150.0  # fallback when a duration wasn't recorded


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class Channel:
    """One destination — an app, or a tone."""
    name: str
    dictations: int = 0
    words: int = 0
    saved_s: float = 0.0
    waits_ms: list = field(default_factory=list)
    cleaned: int = 0
    pasted: int = 0

    @property
    def median_wait_ms(self) -> float:
        return percentile(self.waits_ms, 0.5)

    @property
    def avg_words(self) -> float:
        return self.words / self.dictations if self.dictations else 0.0

    @property
    def cleaned_share(self) -> float:
        return self.cleaned / self.dictations if self.dictations else 0.0

    @property
    def paste_share(self) -> float:
        return self.pasted / self.dictations if self.dictations else 0.0


@dataclass
class Period:
    label: str
    dictations: int = 0
    words: int = 0
    typing_s: float = 0.0
    speaking_s: float = 0.0
    measured_words: int = 0     # words whose speaking time was really measured
    measured_s: float = 0.0
    cleaned: int = 0
    cleanup_failed: int = 0
    pasted: int = 0
    stt_ms: list = field(default_factory=list)
    cleanup_ms: list = field(default_factory=list)
    total_ms: list = field(default_factory=list)
    per_day: dict = field(default_factory=lambda: defaultdict(float))
    per_hour: dict = field(default_factory=lambda: defaultdict(int))
    per_app: dict = field(default_factory=dict)
    per_tone: dict = field(default_factory=dict)

    # ---- headline ---------------------------------------------------

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

    # ---- where the wait goes ----------------------------------------

    @property
    def median_wait_ms(self) -> float:
        return percentile(self.total_ms, 0.5)

    @property
    def p95_wait_ms(self) -> float:
        return percentile(self.total_ms, 0.95)

    @property
    def median_stt_ms(self) -> float:
        return percentile(self.stt_ms, 0.5)

    @property
    def median_cleanup_ms(self) -> float:
        return percentile(self.cleanup_ms, 0.5)

    @property
    def median_overhead_ms(self) -> float:
        """Everything that is neither transcription nor cleanup: encoding
        the audio, the clipboard, the paste."""
        return max(0.0, self.median_wait_ms - self.median_stt_ms - self.median_cleanup_ms)

    # ---- reliability -------------------------------------------------

    @property
    def paste_share(self) -> float:
        return self.pasted / self.dictations if self.dictations else 0.0

    @property
    def cleanup_failure_share(self) -> float:
        attempted = self.cleaned + self.cleanup_failed
        return self.cleanup_failed / attempted if attempted else 0.0

    @property
    def avg_words(self) -> float:
        return self.words / self.dictations if self.dictations else 0.0

    @property
    def busiest_hour(self) -> int | None:
        return max(self.per_hour, key=self.per_hour.get) if self.per_hour else None


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _text_of(entry: dict) -> str:
    return entry.get("cleaned") or entry.get("raw") or ""


def _bump(bucket: dict, name: str, words: int, saved: float,
          wait_ms: int, cleaned: bool, pasted: bool) -> None:
    channel = bucket.get(name)
    if channel is None:
        channel = bucket[name] = Channel(name=name)
    channel.dictations += 1
    channel.words += words
    channel.saved_s += saved
    if wait_ms:
        channel.waits_ms.append(wait_ms)
    channel.cleaned += int(cleaned)
    channel.pasted += int(pasted)


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

        saved = max(0.0, typing - speaking)
        cleaned = bool(e.get("cleaned_applied"))
        delivery = e.get("delivery")
        # Entries from before delivery was tracked shouldn't count as
        # failures; treat an absent field as a normal paste.
        pasted = delivery in (None, "pasted")
        total_ms = int(e.get("process_ms") or 0)

        p.dictations += 1
        p.words += words
        p.typing_s += typing
        p.speaking_s += speaking
        p.cleaned += int(cleaned)
        if e.get("cleanup_error"):
            p.cleanup_failed += 1
        p.pasted += int(pasted)

        if total_ms:
            p.total_ms.append(total_ms)
        if e.get("stt_ms"):
            p.stt_ms.append(int(e["stt_ms"]))
        if e.get("cleanup_ms"):
            p.cleanup_ms.append(int(e["cleanup_ms"]))

        p.per_day[ts.date()] += saved
        p.per_hour[ts.hour] += 1
        _bump(p.per_app, e.get("app") or "—", words, saved, total_ms, cleaned, pasted)
        _bump(p.per_tone, e.get("tone") or "—", words, saved, total_ms, cleaned, pasted)
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


# ---- formatting ------------------------------------------------------

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


def format_ms(ms: float) -> str:
    if ms <= 0:
        return "—"
    if ms < 1000:
        return f"{int(round(ms))} ms"
    return f"{ms / 1000:.1f} s".replace(".", ",")


def format_share(fraction: float) -> str:
    return f"{round(fraction * 100)}%"
