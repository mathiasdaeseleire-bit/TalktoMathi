"""Reading the remaining ElevenLabs allowance.

The important behaviour is what happens when it cannot be read: a key
scoped to speech-to-text alone works fine for dictating but is refused
here, and that must stay silent rather than surface as a failure.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme import quota as quota_mod


def _quota(used=200_000, limit=1_000_000, days=5):
    return quota_mod.Quota(used=used, limit=limit, tier="free",
                            resets_at=datetime.now() + timedelta(days=days))


def test_remaining_and_share():
    q = _quota(used=250_000, limit=1_000_000)
    assert q.remaining == 750_000
    assert abs(q.fraction_used - 0.25) < 0.001
    print("OK: resterend tegoed en verbruikt aandeel kloppen")


def test_overspending_never_goes_negative():
    """Usage can exceed the limit on a paid plan; a negative 'left' would
    read as nonsense."""
    q = _quota(used=1_200_000, limit=1_000_000)
    assert q.remaining == 0
    assert q.fraction_used == 1.0
    print("OK: over de limiet blijft het resterende tegoed nul")


def test_low_only_near_the_end():
    assert not _quota(used=500_000).is_low, "de helft is niet bijna op"
    assert _quota(used=900_000).is_low, "90 procent hoort te waarschuwen"
    print("OK: waarschuwing pas als het tegoed echt bijna op is")


def test_missing_limit_does_not_divide_by_zero():
    q = quota_mod.Quota(used=0, limit=0, tier="onbekend", resets_at=None)
    assert q.fraction_used == 0.0
    assert not q.is_low
    assert q.reset_text() == ""
    print("OK: ontbrekende limiet veroorzaakt geen deling door nul")


def test_reset_wording():
    assert _quota(days=0).reset_text() == "vernieuwt vandaag"
    assert _quota(days=1).reset_text() == "vernieuwt morgen"
    assert "12 dagen" in _quota(days=12).reset_text()
    print("OK: vernieuwingsdatum wordt leesbaar verwoord")


def test_minutes_are_derived_from_remaining_credits():
    q = _quota(used=0, limit=int(quota_mod.CREDITS_PER_SECOND * 600))
    assert abs(q.estimated_minutes - 10.0) < 0.01, q.estimated_minutes
    print("OK: resterende minuten volgen uit het resterende tegoed")


def test_unreadable_quota_is_absent_not_an_error():
    """A speech-to-text-only key returns 401; callers must get None."""
    assert quota_mod.fetch_or_none("") is None
    print("OK: onleesbaar tegoed levert None op, geen fout")


if __name__ == "__main__":
    test_remaining_and_share()
    test_overspending_never_goes_negative()
    test_low_only_near_the_end()
    test_missing_limit_does_not_divide_by_zero()
    test_reset_wording()
    test_minutes_are_derived_from_remaining_credits()
    test_unreadable_quota_is_absent_not_an_error()
    print("\nAlle tegoed-tests geslaagd.")
