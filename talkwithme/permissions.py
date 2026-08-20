"""Microphone privacy check.

Windows exposes the per-user microphone consent under
HKCU\\...\\CapabilityAccessManager\\ConsentStore\\microphone. Desktop
(non-packaged) apps like this one fall under the NonPackaged subkey.
"""
from __future__ import annotations

import logging
import winreg

log = logging.getLogger("talkwithme.permissions")

_BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

SETTINGS_URI = "ms-settings:privacy-microphone"

MESSAGE = (
    "TalkWithMe heeft geen toegang tot je microfoon.\n\n"
    "Zet dit aan in Windows-instellingen:\n"
    "  Privacy en beveiliging  >  Microfoon\n"
    "    1. 'Microfoontoegang' -> Aan\n"
    "    2. 'Apps toegang geven tot je microfoon' -> Aan\n"
    "    3. 'Bureaubladapps toegang geven tot je microfoon' -> Aan\n\n"
    "Start TalkWithMe daarna opnieuw."
)


def _read_value(path: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, "Value")
            return value
    except FileNotFoundError:
        return None
    except OSError as e:
        log.debug("kon microfoon-consent niet lezen (%s): %s", path, e)
        return None


def microphone_allowed() -> bool:
    """False only when Windows explicitly says Deny — an absent key means
    the user has never touched the setting, which is not a denial."""
    for path in (_BASE, _BASE + r"\NonPackaged"):
        if _read_value(path) == "Deny":
            return False
    return True


def open_privacy_settings() -> None:
    import os
    try:
        os.startfile(SETTINGS_URI)
    except Exception as e:
        log.warning("kon privacy-instellingen niet openen: %s", e)
