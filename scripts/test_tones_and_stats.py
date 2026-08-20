"""Tests for tone resolution and the time-saved estimate."""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme import stats as stats_mod
from talkwithme import tones as tones_mod


# ---- tone resolution -------------------------------------------------

def test_exe_maps_to_tone():
    assert tones_mod.resolve("slack.exe", "Slack") == "chat"
    assert tones_mod.resolve("olk.exe", "Postvak IN") == "email"
    assert tones_mod.resolve("windowsterminal.exe", "PowerShell") == "verbatim"
    assert tones_mod.resolve("unknown.exe", "Whatever") == "default"
    print("OK: exe-naam bepaalt de toon")


def test_browser_uses_window_title():
    """A Gmail tab and a WhatsApp tab are the same .exe, so the title has
    to decide."""
    assert tones_mod.resolve("chrome.exe", "Postvak IN - naam@voorbeeld.be - Gmail") == "email"
    assert tones_mod.resolve("chrome.exe", "WhatsApp") == "chat"
    assert tones_mod.resolve("chrome.exe", "Claude") == "prompt"
    assert tones_mod.resolve("chrome.exe", "Een willekeurige nieuwssite") == "default"
    print("OK: in een browser bepaalt de venstertitel de toon")


def test_tone_block_is_appended_after_base():
    base = "BASISREGELS"
    out = tones_mod.build_instructions(base, "chat")
    assert out.startswith(base), "de basisinstructie moet vooraan blijven staan"
    assert "emoji" in out, "chat-toon hoort de emoji-regel te bevatten"
    assert "precedence" in out, "de override-notitie moet meegestuurd worden"
    print("OK: toonblok komt na de basisinstructie, met override-notitie")


def test_without_a_tone_block_only_the_always_rules_are_added():
    """The always-rules are not optional: without them the model may answer
    a dictated question instead of transcribing it, or translate the text."""
    base = "BASISREGELS"
    out = tones_mod.build_instructions(base, "chat", {"chat": ""})
    assert out.startswith(base), "de basisinstructie blijft vooraan staan"
    assert "NEVER answer" in out, "de niet-antwoorden-regel hoort er altijd in"
    assert "Never translate" in out, "de taalregel hoort er altijd in"
    assert "precedence" not in out, "zonder toonblok hoort er geen override-notitie in"
    print("OK: zonder toonblok blijven alleen de altijd-regels over")


def test_always_rules_survive_a_user_edited_base():
    """Users can rewrite the base instruction in Settings; the safety rules
    must not be something they can accidentally delete."""
    out = tones_mod.build_instructions("doe maar iets", "email")
    assert "NEVER answer" in out
    assert "Never translate" in out
    print("OK: veiligheidsregels blijven staan bij een aangepaste basis")


# ---- time saved ------------------------------------------------------

def _entry(text: str, when: datetime, record_s: float, process_ms: int, app="slack.exe"):
    return {"ts": when.isoformat(timespec="seconds"), "raw": text, "cleaned": text,
            "app": app, "cleaned_applied": True, "record_s": record_s,
            "process_ms": process_ms}


def test_saved_time_is_typing_minus_speaking():
    # 40 words at 40 wpm = 60s of typing; spoken in 10s + 2s processing.
    text = " ".join(["woord"] * 40)
    now = datetime.now()
    p = stats_mod.summarise([_entry(text, now, 10.0, 2000)], None, "t")
    assert p.dictations == 1
    assert p.words == 40
    assert abs(p.typing_s - 60.0) < 0.01, p.typing_s
    assert abs(p.speaking_s - 12.0) < 0.01, p.speaking_s
    assert abs(p.saved_s - 48.0) < 0.01, p.saved_s
    print("OK: besparing = typtijd min spreek- en verwerktijd")


def test_slow_dictation_never_counts_as_negative_saving():
    """Rambling for a minute to produce two words is a loss, but it
    shouldn't subtract from earlier real savings."""
    now = datetime.now()
    p = stats_mod.summarise([_entry("hallo daar", now, 60.0, 3000)], None, "t")
    assert p.saved_s == 0.0, p.saved_s
    print("OK: trage dictaten tellen als nul, niet als negatief")


def test_missing_duration_falls_back_to_assumed_speaking_rate():
    """Entries logged before durations were recorded must not look free,
    which would inflate the saving."""
    text = " ".join(["woord"] * 150)   # 1 minute at the assumed 150 wpm
    now = datetime.now()
    p = stats_mod.summarise([_entry(text, now, 0.0, 0)], None, "t")
    assert abs(p.speaking_s - 60.0) < 0.01, p.speaking_s
    assert p.measured_words == 0, "geschatte tijd mag niet als gemeten tellen"
    print("OK: ontbrekende opnameduur valt terug op een aangenomen spreektempo")


def test_speaking_wpm_uses_only_measured_entries():
    now = datetime.now()
    measured = _entry(" ".join(["w"] * 30), now, 12.0, 0)   # 150 wpm
    estimated = _entry(" ".join(["w"] * 500), now, 0.0, 0)  # no duration
    p = stats_mod.summarise([measured, estimated], None, "t")
    assert abs(p.speaking_wpm - 150.0) < 0.01, p.speaking_wpm
    print("OK: spreektempo wordt alleen uit gemeten dictaten berekend")


def test_only_entries_since_the_cutoff_count():
    now = datetime.now()
    old = now - timedelta(days=30)
    text = " ".join(["woord"] * 40)
    entries = [_entry(text, now, 5.0, 0), _entry(text, old, 5.0, 0)]
    week = stats_mod.summarise(entries, date.today(), "week")
    assert week.dictations == 1, "alleen dictaten binnen de periode tellen mee"
    all_time = stats_mod.summarise(entries, None, "alles")
    assert all_time.dictations == 2
    print("OK: periodefilter telt alleen dictaten binnen het venster")


def test_duration_formatting():
    assert stats_mod.format_duration(45) == "45 sec"
    assert stats_mod.format_duration(60) == "1 min"
    assert stats_mod.format_duration(3600) == "1 u"
    assert stats_mod.format_duration(3660) == "1 u 1 min"
    assert stats_mod.format_duration(90, short=True) == "1m"
    assert stats_mod.split_duration(45) == ("45", "seconden")
    assert stats_mod.split_duration(600) == ("10", "minuten")
    assert stats_mod.split_duration(60) == ("1", "minuut")
    print("OK: duur wordt leesbaar geformatteerd")


if __name__ == "__main__":
    test_exe_maps_to_tone()
    test_browser_uses_window_title()
    test_tone_block_is_appended_after_base()
    test_without_a_tone_block_only_the_always_rules_are_added()
    test_always_rules_survive_a_user_edited_base()
    test_saved_time_is_typing_minus_speaking()
    test_slow_dictation_never_counts_as_negative_saving()
    test_missing_duration_falls_back_to_assumed_speaking_rate()
    test_speaking_wpm_uses_only_measured_entries()
    test_only_entries_since_the_cutoff_count()
    test_duration_formatting()
    print("\nAlle toon- en statistiektests geslaagd.")
