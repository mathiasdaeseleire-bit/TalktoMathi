"""Unit test for Recorder's capture bookkeeping, calling _cb directly with
synthetic frames (no real audio device needed).

The pre-roll ring buffer this file used to test is gone: a continuously
open WASAPI stream was found to go silent on this machine, so each
recording now opens its own fresh stream. What still needs covering is
that captured chunks concatenate correctly, that levels feed the on-screen
waveform, and that voice activity updates the silence timer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from talkwithme.recorder import Recorder, SILENCE_RMS_THRESHOLD


def _feed(r, n_samples, value):
    chunk = np.full((n_samples, 1), value, dtype=np.int16)
    r._cb(chunk, n_samples, None, None)


def _fresh_recorder() -> Recorder:
    """Recorder() no longer opens a device in __init__ — start() does — so
    it can be constructed in a test without any audio hardware."""
    return Recorder()


def test_chunks_concatenate_in_order():
    r = _fresh_recorder()
    r.chunks = []
    _feed(r, 100, 1)
    _feed(r, 50, 2)
    audio = np.concatenate(r.chunks)
    assert len(audio) == 150, f"verwacht 150 samples, kreeg {len(audio)}"
    assert audio[0] == 1 and audio[-1] == 2, "volgorde van chunks klopt niet"
    print("OK: opgenomen blokken worden in volgorde samengevoegd")


def test_levels_track_signal_for_waveform():
    r = _fresh_recorder()
    r.levels.clear()
    _feed(r, 100, 0)
    _feed(r, 100, 3000)
    assert len(r.levels) == 2, "elk blok hoort één niveau op te leveren"
    assert r.levels[0] < r.levels[1], "luider blok moet hoger niveau geven"
    print("OK: niveaus voeden de waveform-indicator")


def test_loud_audio_updates_voice_timestamp():
    r = _fresh_recorder()
    r.recording = True
    r.last_voice_ts = 0.0
    _feed(r, 100, 0)
    assert r.last_voice_ts == 0.0, "stilte mag de spraak-timer niet bijwerken"
    _feed(r, 100, SILENCE_RMS_THRESHOLD * 4)
    assert r.last_voice_ts > 0.0, "spraak moet de spraak-timer bijwerken"
    print("OK: spraak werkt de stilte-timer bij, stilte niet")


if __name__ == "__main__":
    test_chunks_concatenate_in_order()
    test_levels_track_signal_for_waveform()
    test_loud_audio_updates_voice_timestamp()
    print("\nAlle recorder-tests geslaagd.")
