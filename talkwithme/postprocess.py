"""Deterministic tidy-up applied after the model has spoken.

Mechanics belong in code, not in a prompt. A model follows "don't end a
chat message with a period" most of the time, and the few percent it
doesn't are exactly what makes the app feel untrustworthy. Everything in
here has to hold every single time, so none of it is left to the model.

The rules come from what the target app does with the text, not from
style preference:

  - In WhatsApp, Slack and Teams, Enter SENDS the message. A newline in
    pasted text therefore fires it off half-finished, or splits it into
    several messages. Chat output has to be a single line.
  - Terminals execute on Enter for the same reason, and a trailing full
    stop turns a valid command into a broken one.
  - Mail clients treat blank lines as paragraph breaks, so a greeting or
    sign-off that was actually spoken needs one to render properly.
"""
from __future__ import annotations

import re

# Models occasionally wrap output in a fence despite being told not to.
_FENCE = re.compile(r"\A```[A-Za-z0-9_+-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?```\Z",
                     re.DOTALL)

# "Here is the cleaned text:" and friends, on their own first line.
_PREAMBLE = re.compile(
    r"\A(?:here(?:'s| is)|hier (?:is|staat)|de opgeschoonde tekst|"
    r"cleaned text|output)\b[^\n:]{0,60}:[ \t]*\r?\n+",
    re.IGNORECASE)

_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"))

# A greeting is a short opener ending in a comma: "Hoi Tom," / "Hi Sarah,".
_GREETING = re.compile(
    r"\A(?:hoi|hallo|hey|hi|hello|dag|beste|geachte|goedemorgen|goedemiddag|"
    r"goedenavond|dear)\b[^\n]{0,40},[ \t]*",
    re.IGNORECASE)

_SIGNOFF = re.compile(
    r"\A(?:groeten|groetjes|met vriendelijke groet(?:en)?|mvg|vriendelijke groeten|"
    r"bedankt|dank je|dank u|alvast bedankt|thanks|thank you|best|best regards|"
    r"kind regards|regards|cheers|tot binnenkort|tot snel)\b[^\n]{0,40}\Z",
    re.IGNORECASE)

# Tones whose target app treats Enter as "send" or "execute".
_SINGLE_LINE_TONES = {"chat", "verbatim"}
_NO_TRAILING_PERIOD_TONES = {"chat", "verbatim"}


def strip_fences(text: str) -> str:
    match = _FENCE.match(text.strip())
    return match.group("body") if match else text


def strip_preamble(text: str) -> str:
    return _PREAMBLE.sub("", text, count=1)


def strip_wrapping_quotes(text: str) -> str:
    """Only when the whole text is wrapped, so a real quotation inside the
    sentence survives untouched."""
    stripped = text.strip()
    for opening, closing in _QUOTE_PAIRS:
        if (len(stripped) >= 2 and stripped.startswith(opening)
                and stripped.endswith(closing)
                and closing not in stripped[1:-1]):
            return stripped[1:-1].strip()
    return text


def normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)          # at most one blank line
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def to_single_line(text: str) -> str:
    """Fold paragraphs into one line for apps where Enter sends."""
    parts = [" ".join(block.split()) for block in text.split("\n\n")]
    parts = [p for p in parts if p]
    return " ".join(parts)


def drop_trailing_period(text: str) -> str:
    """A single full stop only. '...' is deliberate, and '!' and '?' carry
    meaning the speaker chose."""
    if text.endswith(".") and not text.endswith(".."):
        return text[:-1]
    return text


def format_email(text: str) -> str:
    """Put a spoken greeting and sign-off on their own lines. Nothing is
    invented here — this only reflows what the speaker actually said."""
    match = _GREETING.match(text)
    if match:
        greeting = match.group(0).strip()
        rest = text[match.end():].lstrip()
        if rest:
            text = f"{greeting}\n\n{rest}"

    lines = text.split("\n")
    if len(lines) > 1:
        last = lines[-1].strip()
        if last and _SIGNOFF.match(last) and lines[-2].strip():
            text = "\n".join(lines[:-1]) + "\n\n" + last
    return text


def finish(text: str, tone: str = "default") -> str:
    """Everything above, in the order that keeps each step meaningful."""
    if not text:
        return ""

    text = strip_fences(text)
    text = strip_preamble(text)
    text = strip_wrapping_quotes(text)
    text = normalise_whitespace(text)

    if tone in _SINGLE_LINE_TONES:
        text = to_single_line(text)
    elif tone == "email":
        text = format_email(text)

    if tone in _NO_TRAILING_PERIOD_TONES:
        text = drop_trailing_period(text)

    return text.strip()
