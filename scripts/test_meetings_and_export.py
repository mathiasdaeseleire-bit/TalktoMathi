"""Meeting transcript assembly, the Ctrl+Win+M shortcut, and note export.

The shortcut tests matter most: it is the one place where the app
deliberately swallows a key, so it needs to be provably narrow.
"""
import ctypes
import os
import queue
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme import export as export_mod
from talkwithme import meetings as meetings_mod
from talkwithme.hook import (KBDLLHOOKSTRUCT, WM_KEYDOWN, WM_KEYUP,
                              KeyboardHook, VK_LCTRL, VK_LWIN, VK_M)

NOTES = """# Vergadering 20-08-2026 14:05

## Samenvatting
De lancering schuift op.

## Besluiten
- Lancering naar 15 september

## Actiepunten
- **Tom** - offerte opvragen - vrijdag

## Aandachtspunten
- Levertermijn is onzeker
"""


def press(hook, vk, down):
    kb = KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0, flags=0, time=0, dwExtraInfo=None)
    return hook._hook_proc(0, WM_KEYDOWN if down else WM_KEYUP, ctypes.addressof(kb))


# ---- the shortcut ----------------------------------------------------

def test_plain_m_is_never_swallowed():
    """Typing the letter m must stay completely ordinary."""
    hook = KeyboardHook(queue.Queue())
    for down in (True, False):
        assert press(hook, VK_M, down) != 1, "losse m mag nooit geblokkeerd worden"
    print("OK: een losse m blijft gewoon typen")


def test_m_without_both_modifiers_is_untouched():
    q = queue.Queue()
    hook = KeyboardHook(q)
    press(hook, VK_LCTRL, True)          # ctrl only, no win
    assert press(hook, VK_M, True) != 1, "Ctrl+M is van de app, niet van ons"
    assert q.empty(), "Ctrl+M mag geen vergadering starten"
    print("OK: Ctrl+M zonder Windows-toets blijft van de app")


# ---- transcript assembly ---------------------------------------------

def test_words_are_grouped_into_speaker_turns():
    payload = {"words": [
        {"text": "hallo", "speaker_id": "speaker_0", "type": "word"},
        {"text": " daar", "speaker_id": "speaker_0", "type": "word"},
        {"text": "hoi", "speaker_id": "speaker_1", "type": "word"},
        {"text": "terug", "speaker_id": "speaker_1", "type": "word"},
    ]}
    out = meetings_mod.format_by_speaker(payload)
    assert out == "speaker_0: hallo daar\nspeaker_1: hoi terug", repr(out)
    print("OK: woorden worden per spreker gebundeld")


def test_audio_events_are_left_out_of_the_transcript():
    payload = {"words": [
        {"text": "(gelach)", "speaker_id": "speaker_0", "type": "audio_event"},
        {"text": "goed", "speaker_id": "speaker_0", "type": "word"},
    ]}
    assert meetings_mod.format_by_speaker(payload) == "speaker_0: goed"
    print("OK: audio-events komen niet in het transcript")


def test_transcript_without_diarisation_still_works():
    """Diarisation can be absent; the plain text field must still carry."""
    payload = {"text": "een gesprek zonder sprekerlabels"}
    assert meetings_mod.format_by_speaker(payload) == "een gesprek zonder sprekerlabels"
    print("OK: transcript zonder sprekerlabels blijft bruikbaar")


# ---- export ----------------------------------------------------------

def test_every_offered_format_produces_a_real_file():
    folder = tempfile.mkdtemp()
    for name, extension in export_mod.FORMATS:
        path = os.path.join(folder, "notities" + extension)
        export_mod.export(NOTES, path, title="Vergadering")
        assert os.path.exists(path), f"{name} leverde geen bestand op"
        assert os.path.getsize(path) > 100, f"{name} leverde een leeg bestand op"
    print("OK: alle aangeboden formaten leveren een echt bestand")


def test_plain_text_keeps_the_content_and_drops_the_markup():
    out = export_mod.to_text(NOTES)
    assert "**" not in out and "##" not in out, "opmaakcodes horen weg te vallen"
    assert "Lancering naar 15 september" in out
    assert "Tom" in out, "namen mogen niet sneuvelen bij het strippen"
    print("OK: platte tekst behoudt de inhoud zonder opmaakcodes")


def test_html_escapes_dangerous_characters():
    out = export_mod.to_html("## Kop\n\nEen <script>alert(1)</script> regel")
    assert "<script>" not in out, "ruwe html uit de notities mag niet doorlekken"
    assert "&lt;script&gt;" in out
    print("OK: html-export ontsnapt gevaarlijke tekens")


def test_unknown_extension_is_refused():
    try:
        export_mod.export(NOTES, os.path.join(tempfile.mkdtemp(), "x.xyz"))
    except ValueError:
        print("OK: onbekend formaat wordt geweigerd")
        return
    raise AssertionError("een onbekende extensie hoort een fout te geven")


if __name__ == "__main__":
    test_plain_m_is_never_swallowed()
    test_m_without_both_modifiers_is_untouched()
    test_words_are_grouped_into_speaker_turns()
    test_audio_events_are_left_out_of_the_transcript()
    test_transcript_without_diarisation_still_works()
    test_every_offered_format_produces_a_real_file()
    test_plain_text_keeps_the_content_and_drops_the_markup()
    test_html_escapes_dangerous_characters()
    test_unknown_extension_is_refused()
    print("\nAlle vergader- en exporttests geslaagd.")
