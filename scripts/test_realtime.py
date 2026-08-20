"""Streaming transcription: resampling, message handling, and the rules
that keep a flaky socket from costing the user their words.

No network here — the session is driven with the messages the API would
send, so the logic can be checked without a key.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from talkwithme import realtime


def _session():
    return realtime.RealtimeSession("test-key", commit_strategy="vad")


def test_resampling_hits_the_target_length():
    audio = np.zeros(48000, dtype=np.int16)
    assert len(realtime.resample_to_16k(audio, 48000)) == 16000
    assert len(realtime.resample_to_16k(audio, 16000)) == 48000, "16k blijft ongemoeid"
    assert len(realtime.resample_to_16k(np.zeros(0, dtype=np.int16), 48000)) == 0
    print("OK: herbemonstering levert de juiste lengte")


def test_resampling_preserves_the_signal_shape():
    """A constant tone must survive; silence must stay silent."""
    audio = np.full(48000, 5000, dtype=np.int16)
    out = realtime.resample_to_16k(audio, 48000)
    assert abs(int(out.mean()) - 5000) < 5, out.mean()
    print("OK: herbemonstering behoudt het signaal")


def test_committed_pieces_join_into_one_transcript():
    s = _session()
    s._handle({"message_type": "committed_transcript", "text": "ik denk"})
    s._handle({"message_type": "committed_transcript", "text": "dat het werkt"})
    assert s.committed_text == "ik denk dat het werkt", s.committed_text
    print("OK: bevestigde stukken vormen samen het transcript")


def test_partial_shows_live_but_never_lands_in_the_final_text():
    s = _session()
    s._handle({"message_type": "committed_transcript", "text": "hallo"})
    s._handle({"message_type": "partial_transcript", "text": "daar"})
    assert s.live_text == "hallo daar", "de live weergave toont het voorlopige stuk"
    assert s.committed_text == "hallo", "voorlopige tekst is nog niet bevestigd"
    print("OK: voorlopige tekst is zichtbaar maar niet bevestigd")


def test_a_commit_replaces_the_partial_it_finished():
    s = _session()
    s._handle({"message_type": "partial_transcript", "text": "hall"})
    s._handle({"message_type": "committed_transcript", "text": "hallo"})
    assert s.live_text == "hallo", s.live_text
    print("OK: een bevestiging vervangt het voorlopige stuk")


def test_timestamped_commits_count_too():
    s = _session()
    s._handle({"message_type": "committed_transcript_with_timestamps",
                "text": "met tijdcodes", "words": []})
    assert s.committed_text == "met tijdcodes"
    print("OK: bevestigingen met tijdcodes tellen mee")


def test_unknown_messages_are_ignored():
    s = _session()
    s._handle({"message_type": "session_started", "session_id": "x"})
    s._handle({"message_type": "iets_nieuws", "text": "negeer mij"})
    assert s.committed_text == "", "onbekende berichten horen genegeerd te worden"
    print("OK: onbekende berichten worden genegeerd")


def test_finish_without_a_connection_returns_what_it_has():
    """A socket that never opened must not raise on the way out."""
    s = _session()
    s._handle({"message_type": "committed_transcript", "text": "toch iets"})
    assert s.finish(timeout_s=0.2) == "toch iets"
    print("OK: afronden zonder verbinding geeft terug wat er is")


def test_updates_are_pushed_to_the_listener():
    seen = []
    s = realtime.RealtimeSession("test-key", on_update=seen.append)
    s._handle({"message_type": "partial_transcript", "text": "loopt"})
    assert seen == ["loopt"], seen
    print("OK: de weergave krijgt elke wijziging door")


def test_feeding_before_start_is_harmless():
    """The audio callback may fire before the socket is up."""
    t = realtime.StreamingTranscriber("test-key")
    t.feed(np.zeros(160, dtype=np.int16), 16000)
    assert t.live_text == ""
    print("OK: audio voeden voor de start doet niets")


if __name__ == "__main__":
    test_resampling_hits_the_target_length()
    test_resampling_preserves_the_signal_shape()
    test_committed_pieces_join_into_one_transcript()
    test_partial_shows_live_but_never_lands_in_the_final_text()
    test_a_commit_replaces_the_partial_it_finished()
    test_timestamped_commits_count_too()
    test_unknown_messages_are_ignored()
    test_finish_without_a_connection_returns_what_it_has()
    test_updates_are_pushed_to_the_listener()
    test_feeding_before_start_is_harmless()
    print("\nAlle streamingtests geslaagd.")
