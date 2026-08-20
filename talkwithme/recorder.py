"""Audio capture.

Originally designed around a continuously-running stream with a pre-roll
ring buffer (grab the last ~800ms so the word spoken right at the trigger
isn't lost). That was abandoned: on this machine, a WASAPI stream left
open for more than a few seconds before being read started delivering
near-silent buffers (confirmed by isolated tests with zero app threads
involved — this is a device/driver characteristic, not an app bug), while
a stream opened fresh and used immediately consistently captured cleanly.
start() now opens a brand new stream and stop() closes it; the cost is
~100-300ms of missed audio right at the trigger (more with Bluetooth)
instead of a recording that goes silent after its first fraction of a
second.
"""
from __future__ import annotations

import collections
import logging
import time

import numpy as np
import sounddevice as sd

log = logging.getLogger("talkwithme.recorder")

RATE = 16000
BLOCKSIZE = 4096  # see docstring in _open_stream for why not smaller
SILENCE_RMS_THRESHOLD = 150  # int16 RMS; tune if false silence-stops occur


def _preferred_input_device():
    """MME (sounddevice's usual default) has 90-180ms input latency on this
    machine. WASAPI is picked instead. Falls back to the system default if
    WASAPI isn't available.
    """
    try:
        for hostapi in sd.query_hostapis():
            if hostapi["name"] == "Windows WASAPI" and hostapi["default_input_device"] >= 0:
                return hostapi["default_input_device"]
    except Exception:
        pass
    return None


class Recorder:
    def __init__(self, rate: int = RATE):
        self.rate = rate
        self.recording = False
        self.chunks: list[np.ndarray] = []
        self.last_voice_ts = 0.0
        self.recording_start_ts = 0.0
        self.stream: sd.InputStream | None = None
        # Recent per-block RMS, read by the on-screen waveform indicator.
        self.levels: collections.deque[float] = collections.deque(maxlen=48)

    def _open_stream(self) -> None:
        """WASAPI shared-mode devices generally reject a samplerate that
        doesn't match their mix format, so query the native rate up front
        instead of probing with a doomed OpenStream call. Falls back to the
        system default device/rate if WASAPI querying or opening fails.
        """
        device = _preferred_input_device()
        candidates: list[tuple[int | None, int]] = []
        if device is not None:
            try:
                native = int(sd.query_devices(device)["default_samplerate"])
                candidates.append((device, native))
            except Exception:
                candidates.append((device, self.rate))
        candidates.append((None, RATE))

        last_err: Exception | None = None
        for i, (dev, rate) in enumerate(candidates):
            try:
                stream = sd.InputStream(
                    samplerate=rate, channels=1, dtype="int16",
                    blocksize=BLOCKSIZE, callback=self._cb,
                    device=dev, latency="high",
                )
                self.rate = rate
                self.stream = stream
                self.stream.start()
                log.info("audio-stream geopend: candidate #%d/%d device=%s rate=%d",
                          i + 1, len(candidates), dev, rate)
                return
            except Exception as e:
                log.warning("audio-stream candidate #%d/%d (device=%s rate=%d) faalde: %s",
                             i + 1, len(candidates), dev, rate, e)
                last_err = e
                continue
        raise last_err  # type: ignore[misc]

    def _cb(self, indata, frames, time_info, status):
        mono = indata[:, 0]
        self.chunks.append(mono.copy())
        n = len(mono)
        rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2))) if n else 0.0
        self.levels.append(rms)
        if rms > SILENCE_RMS_THRESHOLD:
            self.last_voice_ts = time.monotonic()

    def start(self) -> None:
        self.chunks = []
        self.levels.clear()
        now = time.monotonic()
        self.recording_start_ts = now
        self.last_voice_ts = now
        self.recording = True
        self._open_stream()

    def stop(self) -> np.ndarray:
        self.recording = False
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        if not self.chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self.chunks)

    def silence_elapsed_s(self) -> float:
        if not self.recording:
            return 0.0
        return time.monotonic() - self.last_voice_ts

    def recording_elapsed_s(self) -> float:
        if not self.recording:
            return 0.0
        return time.monotonic() - self.recording_start_ts

    def reopen_if_needed(self) -> None:
        """No-op: there's no long-lived idle stream to recover anymore —
        each recording opens its own fresh stream in start()."""
        pass

    def close(self) -> None:
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
