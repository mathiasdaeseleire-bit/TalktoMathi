"""How much ElevenLabs tegoed is left.

Worth knowing before a meeting: an hour of audio can swallow a free-tier
allowance in one go, and finding that out afterwards means finding out
that the recording was never transcribed.

The quota lives behind the `user_read` permission, which an API key does
not have to carry — a key restricted to speech-to-text works perfectly for
dictating and returns 401 here. That is not an error worth shouting
about, so it is reported as "unknown" and the interface simply omits the
figure.

Credits are ElevenLabs' single unit across products. For Scribe the
conversion is not published as a constant, so minutes are estimated from
what this install has actually spent per second of audio, and labelled as
an estimate rather than presented as fact.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

log = logging.getLogger("talkwithme.quota")

SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
TIMEOUT_S = 8.0
CACHE_S = 120.0            # the figure moves slowly; don't ask on every dictation

# Observed rate for Scribe: roughly this many credits per second of audio.
# Only used to turn credits into a rough "minutes left", never to bill.
CREDITS_PER_SECOND = 6.0


@dataclass
class Quota:
    used: int
    limit: int
    tier: str
    resets_at: datetime | None

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def fraction_used(self) -> float:
        return min(1.0, self.used / self.limit) if self.limit else 0.0

    @property
    def estimated_minutes(self) -> float:
        return self.remaining / CREDITS_PER_SECOND / 60.0

    @property
    def is_low(self) -> bool:
        return self.limit > 0 and self.fraction_used >= 0.85

    def summary(self) -> str:
        return (f"{self.remaining:,} van {self.limit:,} credits over"
                .replace(",", "."))

    def reset_text(self) -> str:
        if self.resets_at is None:
            return ""
        # Calendar days, not timedelta.days: the latter truncates, so a
        # reset 23 hours away would read as "vandaag".
        days = (self.resets_at.date() - datetime.now().date()).days
        if days <= 0:
            return "vernieuwt vandaag"
        if days == 1:
            return "vernieuwt morgen"
        return f"vernieuwt over {days} dagen"


class QuotaUnavailable(Exception):
    """Raised when the key may not read the quota, or the call failed."""


_cache: tuple[float, Quota] | None = None


def fetch(api_key: str, use_cache: bool = True) -> Quota:
    global _cache
    if use_cache and _cache and time.monotonic() - _cache[0] < CACHE_S:
        return _cache[1]
    if not api_key:
        raise QuotaUnavailable("geen API-key")

    try:
        response = httpx.get(SUBSCRIPTION_URL, headers={"xi-api-key": api_key},
                              timeout=TIMEOUT_S)
    except Exception as e:
        raise QuotaUnavailable(f"netwerkfout: {e}") from e

    if response.status_code == 401:
        raise QuotaUnavailable(
            "de API-key mag het verbruik niet lezen (permissie user_read)")
    if response.status_code != 200:
        raise QuotaUnavailable(f"HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as e:
        raise QuotaUnavailable("onleesbaar antwoord") from e

    reset_unix = data.get("next_character_count_reset_unix")
    quota = Quota(
        used=int(data.get("character_count") or 0),
        limit=int(data.get("character_limit") or 0),
        tier=str(data.get("tier") or "onbekend"),
        resets_at=datetime.fromtimestamp(reset_unix) if reset_unix else None,
    )
    _cache = (time.monotonic(), quota)
    return quota


def fetch_or_none(api_key: str) -> Quota | None:
    """For callers that treat an unreadable quota as simply absent."""
    try:
        return fetch(api_key)
    except QuotaUnavailable as e:
        log.debug("tegoed niet op te vragen: %s", e)
        return None
