"""Dictation history: every pasted result, raw and cleaned side by side.

Append-only JSON Lines in the app dir, so a corrupt tail can never take
out earlier entries.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

from . import config as config_mod

log = logging.getLogger("talkwithme.history")

HISTORY_PATH = os.path.join(config_mod.APP_DIR, "history.jsonl")
MAX_ENTRIES = 500

_lock = threading.Lock()


def add(raw: str, cleaned: str, app: str, cleaned_applied: bool,
        tone: str | None = None, record_s: float = 0.0,
        process_ms: int = 0) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "raw": raw,
        "cleaned": cleaned,
        "app": app,
        "cleaned_applied": cleaned_applied,
        "tone": tone,
        "record_s": round(record_s, 2),
        "process_ms": process_ms,
    }
    try:
        config_mod.ensure_app_dir()
        with _lock:
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        log.exception("kon history-entry niet wegschrijven")


def load(limit: int = MAX_ENTRIES) -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        return []
    entries: list[dict] = []
    try:
        with _lock:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        log.exception("kon history niet lezen")
        return []
    return entries[-limit:][::-1]  # newest first


def clear() -> None:
    try:
        with _lock:
            if os.path.exists(HISTORY_PATH):
                os.remove(HISTORY_PATH)
    except Exception:
        log.exception("kon history niet wissen")
