"""API keys via the Windows Credential Manager (keyring). Never in config or code."""
from __future__ import annotations

import keyring

SERVICE = "talkwithme"
GEMINI_KEY_NAME = "gemini_api_key"
ELEVENLABS_KEY_NAME = "elevenlabs_api_key"


def get_gemini_api_key() -> str | None:
    return keyring.get_password(SERVICE, GEMINI_KEY_NAME)


def set_gemini_api_key(value: str) -> None:
    keyring.set_password(SERVICE, GEMINI_KEY_NAME, value)


def get_elevenlabs_api_key() -> str | None:
    return keyring.get_password(SERVICE, ELEVENLABS_KEY_NAME)


def set_elevenlabs_api_key(value: str) -> None:
    keyring.set_password(SERVICE, ELEVENLABS_KEY_NAME, value)
