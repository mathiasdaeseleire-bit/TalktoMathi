r"""One running copy, and clicking the shortcut opens its window.

The app lives in the tray with no main window, so launching it a second
time looked like nothing happened at all. Now a second launch hands over
to the copy that is already running and exits.

Handover goes through a flag file rather than a socket: a listening socket
can trip the Windows Firewall prompt, and this needs no permissions at
all. The running instance polls for the flag in its monitor loop.
"""
from __future__ import annotations

import ctypes
import logging
import os
import time

from . import config as config_mod

log = logging.getLogger("talkwithme.single_instance")

# Local\\ (per logon session) rather than Global\\: the global
# namespace can require privileges a normal user does not have, and one
# copy per logged-in user is exactly what we want anyway.
MUTEX_NAME = "Local\\TalkWithMe_SingleInstance"
SHOW_FLAG = os.path.join(config_mod.APP_DIR, "show_window.flag")
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None


def acquire() -> bool:
    """True when this process is the first copy. The handle is kept alive
    for the lifetime of the process; Windows releases it on exit.

    use_last_error is essential: plain windll shares one error slot that
    any intervening ctypes call can overwrite, so the ALREADY_EXISTS
    signal would be lost and every launch would look like the first."""
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    err = ctypes.get_last_error()
    if not _mutex_handle:
        log.warning("kon mutex niet maken (%s); tweede exemplaar toegestaan", err)
        return True
    return err != ERROR_ALREADY_EXISTS


def signal_show() -> None:
    """Ask the running copy to bring its window up."""
    try:
        config_mod.ensure_app_dir()
        with open(SHOW_FLAG, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError as e:
        log.warning("kon het draaiende exemplaar niet bereiken: %s", e)


def consume_show_request() -> bool:
    """True once per signal_show(); deletes the flag so it fires once."""
    try:
        if os.path.exists(SHOW_FLAG):
            os.remove(SHOW_FLAG)
            return True
    except OSError:
        pass
    return False


def clear() -> None:
    try:
        if os.path.exists(SHOW_FLAG):
            os.remove(SHOW_FLAG)
    except OSError:
        pass
