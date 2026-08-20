r"""Autostart via HKCU\...\Run — no admin rights needed."""
from __future__ import annotations

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TalkWithMe"


def _target_command() -> str:
    r"""Prefer the installed copy: dist\ gets overwritten on every rebuild,
    so pointing Run at it leaves a stale or missing target."""
    # Imported lazily: install.py imports this module.
    from .install import INSTALLED_EXE

    if os.path.exists(INSTALLED_EXE):
        return f'"{INSTALLED_EXE}"'
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m talkwithme'


def enable() -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _target_command())


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def current_target() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except FileNotFoundError:
        return None


def is_enabled() -> bool:
    return current_target() is not None
