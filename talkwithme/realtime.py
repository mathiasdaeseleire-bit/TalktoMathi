"""Streaming transcription over a WebSocket (ElevenLabs Scribe v2 Realtime).

Why this exists: the batch endpoint only sees the audio once you stop
talking, so every second of transcription is a second of waiting. Median
wait was around 2.7s. Streaming sends the audio while it is still being
spoken, so by the time you release the keys most of the work is done and
only the tail remains.

For a meeting the difference is larger still. Uploading an hour of audio
and waiting for it to be transcribed is minutes; here the transcript is
already there when the meeting ends, and it can be shown live while it
runs.

The connection is deliberately treated as unreliable. Every caller keeps
the audio it captured, so a dropped socket falls back to the batch
endpoint rather than losing the recording.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time

import numpy as np
import websocket

log = logging.getLogger("talkwithme.realtime")

WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
MODEL = "scribe_v2_realtime"
TARGET_RATE = 16000          # audio_format pcm_16000
CONNECT_TIMEOUT_S = 6.0
FINISH_TIMEOUT_S = 4.0


def resample_to_16k(audio: np.ndarray, source_rate: int) -> np.ndarray:
    """Linear resampling. Speech at 16 kHz is what the model wants, and
    the artefacts of a simple interpolation sit far above the band that
    carries intelligibility."""
    if source_rate == TARGET_RATE or len(audio) == 0:
        return audio
    target_len = int(len(audio) / source_rate * TARGET_RATE)
    if target_len <= 0:
        return np.zeros(0, dtype=np.int16)
    positions = np.linspace(0, len(audio) - 1, target_len)
    return np.interp(positions, np.arange(len(audio)),
                      audio.astype(np.float64)).astype(np.int16)


class RealtimeError(Exception):
    pass


class RealtimeSession:
    """One transcription session. Not reusable: open, stream, finish."""

    def __init__(self, api_key: str, language: str = "auto",
                 commit_strategy: str = "vad", on_update=None):
        self.api_key = api_key
        self.language = language
        self.commit_strategy = commit_strategy
        self._on_update = on_update

        self._ws: websocket.WebSocket | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._committed: list[str] = []
        self._partial = ""
        self._closed = threading.Event()
        self._last_commit_ts = 0.0
        self.failed: Exception | None = None

    # ---- text ------------------------------------------------------

    @property
    def committed_text(self) -> str:
        with self._lock:
            return " ".join(part for part in self._committed if part).strip()

    @property
    def live_text(self) -> str:
        """Committed text plus whatever is still being revised, for display."""
        with self._lock:
            parts = [part for part in self._committed if part]
            if self._partial:
                parts.append(self._partial)
        return " ".join(parts).strip()

    # ---- lifecycle -------------------------------------------------

    def connect(self) -> None:
        params = [
            f"model_id={MODEL}",
            "audio_format=pcm_16000",
            f"commit_strategy={self.commit_strategy}",
        ]
        if self.language and self.language != "auto":
            params.append(f"language_code={self.language}")
        url = f"{WS_URL}?{'&'.join(params)}"

        try:
            self._ws = websocket.create_connection(
                url, header={"xi-api-key": self.api_key},
                timeout=CONNECT_TIMEOUT_S)
            self._ws.settimeout(1.0)
        except Exception as e:
            raise RealtimeError(f"kon geen verbinding maken: {e}") from e

        self._reader = threading.Thread(target=self._read_loop,
                                         name="realtime-reader", daemon=True)
        self._reader.start()
        log.info("realtime-sessie geopend (commit=%s)", self.commit_strategy)

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                if not self._closed.is_set():
                    self.failed = e
                    log.warning("realtime-verbinding verbroken: %s", e)
                return
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            self._handle(message)

    def _handle(self, message: dict) -> None:
        kind = message.get("message_type")
        text = (message.get("text") or "").strip()

        if kind == "partial_transcript":
            with self._lock:
                self._partial = text
        elif kind in ("committed_transcript", "committed_transcript_with_timestamps"):
            with self._lock:
                if text:
                    self._committed.append(text)
                self._partial = ""
                self._last_commit_ts = time.monotonic()
        elif kind == "session_started":
            return
        else:
            return

        if self._on_update:
            try:
                self._on_update(self.live_text)
            except Exception:
                pass

    def send(self, audio: np.ndarray, source_rate: int, commit: bool = False) -> None:
        if self._ws is None or self._closed.is_set():
            return
        chunk = resample_to_16k(audio, source_rate)
        if len(chunk) == 0 and not commit:
            return
        payload = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(chunk.tobytes()).decode("ascii"),
            "sample_rate": TARGET_RATE,
        }
        if commit:
            payload["commit"] = True
        try:
            self._ws.send(json.dumps(payload))
        except Exception as e:
            self.failed = e
            log.warning("versturen van audio mislukt: %s", e)

    def finish(self, timeout_s: float = FINISH_TIMEOUT_S) -> str:
        """Flush, then give the tail of the audio a moment to come back."""
        if self._ws is None:
            return self.committed_text

        self.send(np.zeros(0, dtype=np.int16), TARGET_RATE, commit=True)

        started = time.monotonic()
        deadline = started + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                partial, committed = self._partial, list(self._committed)
            if committed and not partial and time.monotonic() - self._last_commit_ts > 0.25:
                break
            # Nothing at all after a moment means there was no speech in the
            # audio; waiting out the full timeout would just stall the paste.
            if not committed and not partial and time.monotonic() - started > 1.2:
                break
            if self.failed:
                break
            time.sleep(0.05)

        text = self.live_text          # include a trailing partial if that is all we got
        self.close()
        return text

    def close(self) -> None:
        self._closed.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None


def is_available() -> bool:
    return websocket is not None


class StreamingTranscriber:
    """A RealtimeSession that is safe to feed from an audio callback.

    The callback runs on PortAudio's thread; anything slow there costs
    audio. So `feed` only appends to a queue, and a sender thread does the
    resampling, encoding and network write.
    """

    QUEUE_LIMIT = 400          # ~ tens of seconds of audio; drops rather than grows

    def __init__(self, api_key: str, language: str = "auto",
                 commit_strategy: str = "vad", on_update=None):
        import queue as queue_mod

        self.session = RealtimeSession(api_key, language, commit_strategy, on_update)
        self._queue: "queue_mod.Queue" = queue_mod.Queue(maxsize=self.QUEUE_LIMIT)
        self._queue_empty = queue_mod.Empty
        self._sender: threading.Thread | None = None
        self._stop = threading.Event()
        self.started = False

    def start(self) -> None:
        self.session.connect()
        self._sender = threading.Thread(target=self._send_loop,
                                         name="realtime-sender", daemon=True)
        self._sender.start()
        self.started = True

    def feed(self, audio: np.ndarray, rate: int) -> None:
        if not self.started:
            return
        try:
            self._queue.put_nowait((audio.copy(), rate))
        except Exception:
            pass       # a full queue means the network is behind; drop, never block

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                audio, rate = self._queue.get(timeout=0.2)
            except self._queue_empty:
                continue
            self.session.send(audio, rate)

    @property
    def live_text(self) -> str:
        return self.session.live_text

    @property
    def failed(self):
        return self.session.failed

    def finish(self, timeout_s: float = FINISH_TIMEOUT_S) -> str:
        """Drain what is queued, then close the session and return the text."""
        deadline = time.monotonic() + 2.0
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.03)
        self._stop.set()
        if self._sender is not None:
            self._sender.join(timeout=1.0)
        return self.session.finish(timeout_s)

    def close(self) -> None:
        self._stop.set()
        self.session.close()
