"""Getting text onto the cursor: fill the clipboard and simulate the paste
keys via SendInput. Works everywhere, including Electron apps where direct
text injection fails.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time

import pywintypes
import win32clipboard as cb
import win32con

log = logging.getLogger("talkwithme.paste")

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_V = 0x56

# Marks injected input so our own hook can ignore it (LLKHF_INJECTED).
EXTRA_INFO_INJECTED = 0xFEED0001


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUnion(ctypes.Union):
    # Must mirror the real Win32 union (mi/ki/hi) even though we only ever
    # populate ki: SendInput validates cbSize against its own sizeof(INPUT)
    # and silently sends zero events if it doesn't match. A union with only
    # ki is 8 bytes smaller than the real struct on x64 (32 vs 40) because
    # MOUSEINPUT, the actual largest member, is missing.
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("union", _INPUTUnion)]


_extra = ctypes.c_ulong(EXTRA_INFO_INJECTED)


def _make_key_input(vk: int, up: bool, unicode: bool = False) -> INPUT:
    flags = 0
    wvk = vk
    wscan = 0
    if unicode:
        flags |= KEYEVENTF_UNICODE
        wvk = 0
        wscan = vk  # char code goes in wScan for unicode events
    if up:
        flags |= KEYEVENTF_KEYUP
    ki = KEYBDINPUT(wVk=wvk, wScan=wscan, dwFlags=flags, time=0,
                     dwExtraInfo=ctypes.pointer(_extra))
    inp = INPUT(type=INPUT_KEYBOARD, union=_INPUTUnion(ki=ki))
    return inp


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def send_key_combo(keys: tuple[str, ...]) -> None:
    vk_map = {"ctrl": VK_CONTROL, "shift": VK_SHIFT, "v": VK_V}
    vks = [vk_map[k] for k in keys]
    down = [_make_key_input(vk, up=False) for vk in vks]
    up = [_make_key_input(vk, up=True) for vk in reversed(vks)]
    _send(down + up)


def type_unicode(text: str, chunk_size: int = 20, delay_s: float = 0.005) -> None:
    """Fallback when paste is blocked (password fields, RDP, some games)."""
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        inputs = []
        for ch in chunk:
            inputs.append(_make_key_input(ord(ch), up=False, unicode=True))
            inputs.append(_make_key_input(ord(ch), up=True, unicode=True))
        _send(inputs)
        time.sleep(delay_s)


# ---- clipboard save/restore -------------------------------------------

def _open_clipboard(retries: int = 5, delay_s: float = 0.02) -> bool:
    for _ in range(retries):
        try:
            cb.OpenClipboard()
            return True
        except Exception:
            time.sleep(delay_s)
    return False


def save_clipboard() -> dict[int, object]:
    saved: dict[int, object] = {}
    if not _open_clipboard():
        return saved
    try:
        fmt = 0
        while True:
            fmt = cb.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            if fmt in (win32con.CF_UNICODETEXT, win32con.CF_TEXT, win32con.CF_HTML if hasattr(win32con, "CF_HTML") else -1):
                try:
                    saved[fmt] = cb.GetClipboardData(fmt)
                except Exception:
                    pass
    finally:
        cb.CloseClipboard()
    return saved


def restore_clipboard(saved: dict[int, object]) -> None:
    if not saved:
        return
    if not _open_clipboard():
        return
    try:
        cb.EmptyClipboard()
        for fmt, data in saved.items():
            try:
                cb.SetClipboardData(fmt, data)
            except Exception:
                pass
    finally:
        cb.CloseClipboard()


def set_clipboard_text(text: str, retries: int = 3, delay_s: float = 0.05) -> bool:
    """SetClipboardData occasionally fails with a transient 'invalid
    handle' error under Windows clipboard contention — retry the whole
    open/empty/set cycle rather than treating it as a hard failure."""
    for attempt in range(retries):
        if not _open_clipboard():
            time.sleep(delay_s)
            continue
        try:
            cb.EmptyClipboard()
            cb.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return True
        except pywintypes.error as e:
            log.warning("SetClipboardData mislukt (poging %d/%d): %s", attempt + 1, retries, e)
        finally:
            try:
                cb.CloseClipboard()
            except pywintypes.error:
                pass
        time.sleep(delay_s)
    return False


def insert_text(text: str, exe: str, paste_keys: dict[str, str], notify_cb=None) -> bool:
    """Returns True if the paste keystroke was sent (best effort — we can't
    confirm the target app actually accepted it)."""
    saved = save_clipboard()

    if not set_clipboard_text(text):
        if notify_cb:
            notify_cb("TalkWithMe", "Klembord niet beschikbaar — tekst niet geplakt.")
        return False

    keys_str = paste_keys.get(exe, "ctrl+v")
    keys = tuple(keys_str.split("+"))
    try:
        send_key_combo(keys)
    except Exception as e:
        log.warning("plakken mislukt: %s", e)
        if notify_cb:
            notify_cb("TalkWithMe", "Plakken mislukt — tekst staat op je klembord.")
        return False

    def restore():
        time.sleep(0.15)
        restore_clipboard(saved)

    threading.Thread(target=restore, daemon=True).start()
    return True
