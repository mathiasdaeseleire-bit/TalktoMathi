"""Speech-to-text via ElevenLabs Scribe v2.

POST https://api.elevenlabs.io/v1/speech-to-text, multipart with model_id
and the audio file; auth via the xi-api-key header. The transcript comes
back in the "text" field.
"""
from __future__ import annotations

import io
import logging
import time
import wave

import httpx
import numpy as np

log = logging.getLogger("talkwithme.stt")

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
DEFAULT_MODEL = "scribe_v2"


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


class SttError(Exception):
    pass


class SttClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, language: str = "auto"):
        self.api_key = api_key
        self.model = model
        self.language = language
        # One shared client: keep-alive means TLS/DNS is already done by the
        # time the user finishes speaking.
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=300),
        )

    def prewarm(self) -> None:
        """Warm TLS/DNS so the first real request isn't paying for it."""
        try:
            self._client.get("https://api.elevenlabs.io/v1/models",
                              headers={"xi-api-key": self.api_key}, timeout=3.0)
        except Exception as e:
            log.debug("stt prewarm faalde (niet fataal): %s", e)

    def transcribe(self, samples: np.ndarray, rate: int) -> tuple[str, int]:
        """Returns (text, provider_ms). Raises SttError on failure."""
        audio = wav_bytes(samples, rate)
        data = {"model_id": self.model}
        if self.language and self.language != "auto":
            data["language_code"] = self.language

        t0 = time.monotonic()
        try:
            resp = self._client.post(
                API_URL,
                headers={"xi-api-key": self.api_key},
                data=data,
                files={"file": ("audio.wav", audio, "audio/wav")},
            )
        except Exception as e:
            raise SttError(f"netwerkfout: {e}") from e
        provider_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            raise SttError(f"HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            payload = resp.json()
        except Exception as e:
            raise SttError(f"ongeldig JSON-antwoord: {e}") from e

        text = payload.get("text")
        if text is None and isinstance(payload.get("transcripts"), list) and payload["transcripts"]:
            text = payload["transcripts"][0].get("text", "")
        return (text or "").strip(), provider_ms

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
