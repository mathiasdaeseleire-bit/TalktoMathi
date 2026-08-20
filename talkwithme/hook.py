"""Low-level keyboard hook: hold Ctrl+Win to record.

SAFETY RULES (a dictation tool that eats your keystrokes is worse than no
dictation tool at all):

  1. This hook NEVER suppresses a key. It returns CallNextHookEx for every
     single event, always. Earlier versions swallowed the Win/Alt keyup to
     stop the Start menu; that left Windows believing the modifier was
     still held, which turned every later keystroke into a shortcut. Not
     worth it — a Start-menu flash is survivable, a dead keyboard is not.
  2. Tracked modifier flags are never trusted on their own. Windows can
     eat a keyup (e.g. the Start menu grabs focus), which would strand the
     flag as "still down" and make every later Ctrl press fire a
     recording. GetAsyncKeyState is queried as ground truth on each event.
  3. The callback body is wrapped so that no exception can escape and turn
     into a bogus return value.

The callback stays minimal — set flags, push to a queue. Windows silently
drops hooks whose callback is slow (LowLevelHooksTimeout, ~1s). No
network, no disk, no logging, no print in here.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import queue
import threading

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
LLKHF_INJECTED = 0x10

VK_LCTRL, VK_RCTRL, VK_CTRL = 0xA2, 0xA3, 0x11
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_ESCAPE = 0x1B

# LRESULT/WPARAM/LPARAM are pointer-sized: 64-bit on x64. Declaring
# LRESULT as c_long (32-bit) truncates the value CallNextHookEx returns,
# which is exactly the kind of corruption that makes a hook misbehave.
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]
user32.UnhookWindowsHookEx.restype = w.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", w.DWORD),
        ("scanCode", w.DWORD),
        ("flags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ctypes.POINTER(w.ULONG)),
    ]


START = "START"
STOP = "STOP"
CANCEL = "CANCEL"


def _physically_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def ctrl_down() -> bool:
    return _physically_down(VK_CTRL) or _physically_down(VK_LCTRL) or _physically_down(VK_RCTRL)


def win_down() -> bool:
    return _physically_down(VK_LWIN) or _physically_down(VK_RWIN)


class KeyboardHook:
    def __init__(self, event_queue: "queue.Queue[str]", is_active_cb=None):
        self.queue = event_queue
        self._is_active_cb = is_active_cb or (lambda: False)
        self._hook_id = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._proc = HOOKPROC(self._hook_proc)  # keep reference alive
        self.firing = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return  # never stack hooks: each one adds latency to every keystroke
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="kb-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook_id:
            return
        msg = w.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook_id)
        self._hook_id = None

    def _push(self, event: str) -> None:
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            pass

    def _apply(self, held: bool) -> None:
        if held and not self.firing:
            self.firing = True
            self._push(START)
        elif not held and self.firing:
            self.firing = False
            self._push(STOP)

    def sync_from_physical(self) -> None:
        """Pure physical reconciliation, used by the app's watchdog: if a
        keyup was swallowed by something else, this un-sticks us."""
        self._apply(ctrl_down() and win_down())

    def _sync_from_event(self, vk: int, down: bool) -> None:
        """Inside a low-level hook, GetAsyncKeyState may not yet reflect the
        key currently being processed — the event hasn't been dispatched.
        So take the key in hand from the event itself, and only ask the OS
        about the other one."""
        if vk in (VK_LCTRL, VK_RCTRL, VK_CTRL):
            self._apply(down and win_down())
        else:  # a Win key
            self._apply(down and ctrl_down())

    def _hook_proc(self, nCode, wParam, lParam):
        # Whatever happens below, the key must be passed along untouched.
        try:
            if nCode == 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                # Skip our own synthesized Ctrl+V, else we'd react to ourselves.
                if not (kb.flags & LLKHF_INJECTED):
                    vk = kb.vkCode
                    down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

                    if down and vk == VK_ESCAPE and self._is_active_cb():
                        self.firing = False
                        self._push(CANCEL)
                    elif vk in (VK_LCTRL, VK_RCTRL, VK_CTRL, VK_LWIN, VK_RWIN):
                        self._sync_from_event(vk, down)
        except Exception:
            pass  # never let a bug here block the user's keyboard
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
