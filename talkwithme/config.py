"""Config for TalkWithMe. YAML at %USERPROFILE%\\.talkwithme\\config.yaml.

API keys are NOT here — those live in the Windows Credential Manager.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

from . import prompts
from . import tones as tones_mod

APP_DIR = os.path.join(os.path.expanduser("~"), ".talkwithme")
CONFIG_PATH = os.path.join(APP_DIR, "config.yaml")
LOG_PATH = os.path.join(APP_DIR, "talkwithme.log")

DEFAULTS = {
    "max_duration_s": 300,
    "language": "auto",
    "stt_model": "scribe_v2",
    "cleanup_model": "gemini-flash-lite-latest",
    "cleanup_enabled": True,
    "update_repo": "mathiasdaeseleire-bit/TalkwithMe",          # bv. "mathias/talkwithme"; leeg = niet controleren
    "update_check_enabled": True,
    "cleanup_instructions": prompts.DEFAULT_CLEANUP,
    # Adapt tone to the app being typed into (chat vs email vs terminal).
    "tone_enabled": True,
    "tone_instructions": dict(tones_mod.DEFAULT_TONE_INSTRUCTIONS),
    "exe_tones": dict(tones_mod.DEFAULT_EXE_TONES),
    "title_tones": dict(tones_mod.DEFAULT_TITLE_TONES),
    "paste_keys": {
        "windowsterminal.exe": "ctrl+shift+v",
    },
}


@dataclass
class Config:
    max_duration_s: int = DEFAULTS["max_duration_s"]
    language: str = DEFAULTS["language"]
    stt_model: str = DEFAULTS["stt_model"]
    cleanup_model: str = DEFAULTS["cleanup_model"]
    cleanup_enabled: bool = DEFAULTS["cleanup_enabled"]
    update_repo: str = DEFAULTS["update_repo"]
    update_check_enabled: bool = DEFAULTS["update_check_enabled"]
    cleanup_instructions: str = DEFAULTS["cleanup_instructions"]
    tone_enabled: bool = DEFAULTS["tone_enabled"]
    tone_instructions: dict = None  # type: ignore[assignment]
    exe_tones: dict = None  # type: ignore[assignment]
    title_tones: dict = None  # type: ignore[assignment]
    paste_keys: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.paste_keys is None:
            self.paste_keys = dict(DEFAULTS["paste_keys"])
        if self.tone_instructions is None:
            self.tone_instructions = dict(DEFAULTS["tone_instructions"])
        if self.exe_tones is None:
            self.exe_tones = dict(DEFAULTS["exe_tones"])
        if self.title_tones is None:
            self.title_tones = dict(DEFAULTS["title_tones"])

    def save(self) -> None:
        ensure_app_dir()
        data = {
            "max_duration_s": self.max_duration_s,
            "language": self.language,
            "stt_model": self.stt_model,
            "cleanup_model": self.cleanup_model,
            "cleanup_enabled": self.cleanup_enabled,
            "update_repo": self.update_repo,
            "update_check_enabled": self.update_check_enabled,
            "cleanup_instructions": self.cleanup_instructions,
            "tone_enabled": self.tone_enabled,
            "tone_instructions": self.tone_instructions,
            "exe_tones": self.exe_tones,
            "title_tones": self.title_tones,
            "paste_keys": self.paste_keys,
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def ensure_app_dir() -> None:
    os.makedirs(APP_DIR, exist_ok=True)


def load_config() -> Config:
    ensure_app_dir()
    raw = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            raw = {}  # corrupt config: fall back to defaults rather than crash
    merged = {**DEFAULTS, **raw}
    # Migration: before the ElevenLabs switch, stt_model held a Gemini model
    # name. Anything that isn't a Scribe model is stale — reset it, otherwise
    # the STT call would send a nonsense model_id.
    if not str(merged.get("stt_model", "")).startswith("scribe"):
        merged["stt_model"] = DEFAULTS["stt_model"]
    # Same for the old polish_model key, and for tone-era instructions.
    if "polish_model" in raw and "cleanup_model" not in raw:
        merged["cleanup_model"] = DEFAULTS["cleanup_model"]
    cfg = Config(
        max_duration_s=int(merged["max_duration_s"]),
        language=merged["language"],
        stt_model=merged["stt_model"],
        cleanup_model=merged["cleanup_model"],
        cleanup_enabled=bool(merged["cleanup_enabled"]),
        update_repo=str(merged.get("update_repo") or "").strip(),
        update_check_enabled=bool(merged.get("update_check_enabled", True)),
        cleanup_instructions=merged["cleanup_instructions"] or prompts.DEFAULT_CLEANUP,
        tone_enabled=bool(merged["tone_enabled"]),
        # Merge onto the defaults so tones added in a later version show up
        # for users whose config file predates them.
        tone_instructions={**DEFAULTS["tone_instructions"],
                            **(merged.get("tone_instructions") or {})},
        exe_tones={**DEFAULTS["exe_tones"],
                    **{k.lower(): v for k, v in (merged.get("exe_tones") or {}).items()}},
        title_tones={**DEFAULTS["title_tones"],
                      **(merged.get("title_tones") or {})},
        paste_keys={k.lower(): v for k, v in (merged.get("paste_keys") or {}).items()},
    )
    if not os.path.exists(CONFIG_PATH):
        cfg.save()
    return cfg
