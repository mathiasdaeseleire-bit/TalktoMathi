"""One-time migration from the app's former name.

The app was called TalktoMathi before it was published. Renaming moved
the config directory, the credential-store service and the autostart
entry, so without this an existing install would silently come back up
with no API keys, no history and no autostart — looking like a fresh
install that lost everything.

Runs on every start and does nothing once there is no old data left.
"""
from __future__ import annotations

import logging
import os
import shutil
import winreg

from . import config as config_mod

log = logging.getLogger("talkwithme.migrate")

OLD_APP_DIR = os.path.join(os.path.expanduser("~"), ".talktomathi")
OLD_SERVICE = "talktomathi"
OLD_RUN_VALUE = "TalktoMathi"
OLD_INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                                "Programs", "TalktoMathi")
OLD_SHORTCUT = os.path.join(os.environ.get("APPDATA", ""),
                             r"Microsoft\Windows\Start Menu\Programs\TalktoMathi.lnk")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

_KEY_NAMES = ("elevenlabs_api_key", "gemini_api_key")
_FILES = ("config.yaml", "history.jsonl")


def _migrate_app_dir() -> bool:
    if not os.path.isdir(OLD_APP_DIR):
        return False
    config_mod.ensure_app_dir()
    moved = False
    for name in _FILES:
        old = os.path.join(OLD_APP_DIR, name)
        new = os.path.join(config_mod.APP_DIR, name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)
                moved = True
            except OSError as e:
                log.warning("kon %s niet overzetten: %s", name, e)
    return moved


def _migrate_keys() -> bool:
    """Copy rather than move: if anything goes wrong the old credentials
    are still there to fall back on."""
    import keyring

    from . import secrets_store

    moved = False
    for name in _KEY_NAMES:
        try:
            if keyring.get_password(secrets_store.SERVICE, name):
                continue
            old_value = keyring.get_password(OLD_SERVICE, name)
            if old_value:
                keyring.set_password(secrets_store.SERVICE, name, old_value)
                moved = True
        except Exception as e:
            log.warning("kon key %s niet overzetten: %s", name, e)
    return moved


def _migrate_autostart() -> bool:
    """Drop the old Run entry; it points at an exe that no longer exists,
    so leaving it behind means a failed launch at every login."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_ALL_ACCESS) as key:
            try:
                winreg.QueryValueEx(key, OLD_RUN_VALUE)
            except FileNotFoundError:
                return False
            winreg.DeleteValue(key, OLD_RUN_VALUE)
            return True
    except OSError as e:
        log.debug("kon oude autostart niet opruimen: %s", e)
        return False


def _clean_old_install() -> None:
    try:
        if os.path.exists(OLD_SHORTCUT):
            os.remove(OLD_SHORTCUT)
    except OSError as e:
        log.debug("kon oude snelkoppeling niet verwijderen: %s", e)
    try:
        if os.path.isdir(OLD_INSTALL_DIR):
            shutil.rmtree(OLD_INSTALL_DIR, ignore_errors=True)
    except OSError as e:
        log.debug("kon oude installatiemap niet verwijderen: %s", e)


def run() -> None:
    did_anything = False
    try:
        did_anything |= _migrate_app_dir()
        did_anything |= _migrate_keys()
        did_anything |= _migrate_autostart()
        _clean_old_install()
    except Exception:
        log.exception("migratie van de oude naam mislukt")
        return
    if did_anything:
        log.info("instellingen van de vorige naam overgenomen")
