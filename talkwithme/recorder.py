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
SILENCE_RMS_THRESHOLD = 150
OPEN_ATTEMPTS = 4
OPEN_RETRY_S = 0.12  # int16 RMS; tune if false silence-stops occur


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
        self.using_fallback_device = False
        # Optional live consumer (streaming transcription). Called from the
        # audio callback, so it must only queue work, never block.
        self.on_audio = None
        # Recent per-block RMS, read by the on-screen waveform indicator.
        self.levels: collections.deque[float] = collections.deque(maxlen=48)

    def _open_stream(self) -> None:
        """Open the real microphone, retrying before giving up on it.

        The preferred WASAPI device intermittently refuses to start with a
        WDM-KS ioctl error, usually because something else let go of it a
        moment ago. Falling straight through to the system default looks
        like success and then records pure silence, which is worse than an
        error: you only find out after speaking. So the preferred device
        gets several short retries, and the fallback is marked as suspect
        so the caller can warn if nothing was captured.
        """
        device = _preferred_input_device()
        rate = RATE
        if device is not None:
            try:
                rate = int(sd.query_devices(device)["default_samplerate"])
            except Exception:
                pass

        last_err: Exception | None = None
        if device is not None:
            for attempt in range(1, OPEN_ATTEMPTS + 1):
                try:
                    self._start(device, rate)
                    self.using_fallback_device = False
                    if attempt > 1:
                        log.info("microfoon geopend na poging %d", attempt)
                    return
                except Exception as e:
                    last_err = e
                    log.warning("microfoon openen mislukt (poging %d/%d): %s",
                                 attempt, OPEN_ATTEMPTS, e)
                    time.sleep(OPEN_RETRY_S)

        try:
            self._start(None, RATE)
            self.using_fallback_device = True
            log.warning("teruggevallen op het standaardapparaat; dat levert op "
                         "sommige machines stilte op")
            return
        except Exception as e:
            last_err = e
        raise last_err  # type: ignore[misc]

    def _start(self, device, rate: int) -> None:
        stream = sd.InputStream(
            samplerate=rate, channels=1, dtype="int16",
            blocksize=BLOCKSIZE, callback=self._cb,
            device=device, latency="high",
        )
        stream.start()
        self.rate = rate
        self.stream = stream
        log.info("audio-stream geopend: device=%s rate=%d", device, rate)

    def _cb(self, indata, frames, time_info, status):
        mono = indata[:, 0]
        self.chunks.append(mono.copy())
        consumer = self.on_audio
        if consumer is not None:
            try:
                consumer(mono, self.rate)
            except Exception:
                pass
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
