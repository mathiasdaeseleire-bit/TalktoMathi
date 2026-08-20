"""Cleanup layer: raw transcript -> cleaned text, via Gemini Flash.

The system instruction is whatever the user has in Settings (defaulting to
prompts.DEFAULT_CLEANUP, sent word-for-word). If this fails for any reason
the caller pastes the raw transcript instead — never lose the user's words.
"""
from __future__ import annotations

import logging
import time

from google import genai
from google.genai import types

log = logging.getLogger("talkwithme.polish")


class PolishClient:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def prewarm(self) -> None:
        try:
            self.client.models.generate_content(
                model=self.model,
                contents=["ping"],
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
        except Exception as e:
            log.debug("cleanup prewarm faalde (niet fataal): %s", e)

    def cleanup(self, transcript: str, instructions: str, timeout_s: float = 10.0) -> tuple[str, int]:
        """Returns (text, provider_ms). Raises on failure."""
        t0 = time.monotonic()
        resp = self.client.models.generate_content(
            model=self.model,
            contents=[transcript],
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                temperature=0.2,
                http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            ),
        )
        provider_ms = int((time.monotonic() - t0) * 1000)
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError("leeg antwoord van cleanup-model")
        return text, provider_ms
