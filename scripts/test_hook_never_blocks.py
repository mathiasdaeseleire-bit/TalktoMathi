"""Guarantee test: the hook must NEVER suppress a keystroke, and must
never get stranded in a 'held' state.

Calls _hook_proc directly with synthetic events. A low-level keyboard hook
suppresses a key by returning 1; anything else passes it through. Every
case here asserts the return is not 1, including deliberately hostile ones
(exception inside the callback, unknown keys, injected input).
"""
import ctypes
import os
import queue
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from talkwithme.hook import (
    KeyboardHook, KBDLLHOOKSTRUCT, WM_KEYDOWN, WM_KEYUP,
    VK_LCTRL, VK_LWIN, VK_ESCAPE, LLKHF_INJECTED,
)

VK_A, VK_V = 0x41, 0x56


def press(hook, vk, down, injected=False):
    kb = KBDLLHOOKSTRUCT(vkCode=vk, scanCode=0,
                          flags=LLKHF_INJECTED if injected else 0,
                          time=0, dwExtraInfo=None)
    wparam = WM_KEYDOWN if down else WM_KEYUP
    return hook._hook_proc(0, wparam, ctypes.addressof(kb))


def test_ordinary_typing_never_blocked():
    hook = KeyboardHook(queue.Queue())
    for vk in (VK_A, VK_V, VK_LCTRL, VK_LWIN, VK_ESCAPE):
        for down in (True, False):
            ret = press(hook, vk, down)
            assert ret != 1, f"vk={vk:#x} down={down} werd geblokkeerd (ret={ret})"
    print("OK: gewone toetsen worden nooit geblokkeerd")


def test_escape_while_recording_not_blocked():
    q = queue.Queue()
    hook = KeyboardHook(q, is_active_cb=lambda: True)
    ret = press(hook, VK_ESCAPE, True)
    assert ret != 1, "ESC moet doorgelaten worden, ook tijdens opname"
    assert q.get_nowait() == "CANCEL"
    print("OK: ESC annuleert maar wordt doorgelaten")


def test_ctrl_v_does_not_fire_recording():
    """The bug that made pasting an API key impossible: a stranded Win flag
    turned Ctrl+V into a recording trigger."""
    q = queue.Queue()
    hook = KeyboardHook(q)
    hook.firing = False
    press(hook, VK_LCTRL, True)
    ret = press(hook, VK_V, True)
    assert ret != 1, "Ctrl+V mag nooit geblokkeerd worden"
    assert q.empty(), f"Ctrl+V mag geen opname starten, kreeg {list(q.queue)}"
    print("OK: Ctrl+V plakt gewoon, start geen opname")


def test_injected_input_ignored():
    q = queue.Queue()
    hook = KeyboardHook(q)
    ret = press(hook, VK_V, True, injected=True)
    assert ret != 1
    assert q.empty()
    print("OK: eigen gesimuleerde toetsen worden genegeerd")


def test_exception_in_callback_still_passes_key():
    class Exploding(KeyboardHook):
        def _sync_from_event(self, vk, down):
            raise RuntimeError("boom")

    hook = Exploding(queue.Queue())
    ret = press(hook, VK_LCTRL, True)
    assert ret != 1, "een fout in de callback mag de toets nooit tegenhouden"
    print("OK: fout in callback blokkeert de toets niet")


def test_watchdog_unsticks_state():
    q = queue.Queue()
    hook = KeyboardHook(q)
    hook.firing = True          # pretend a keyup was swallowed
    hook.sync_from_physical()   # keys aren't really down
    assert hook.firing is False, "watchdog moet vastgelopen staat herstellen"
    assert q.get_nowait() == "STOP"
    print("OK: watchdog herstelt vastgelopen toetsstatus")


if __name__ == "__main__":
    test_ordinary_typing_never_blocked()
    test_escape_while_recording_not_blocked()
    test_ctrl_v_does_not_fire_recording()
    test_injected_input_ignored()
    test_exception_in_callback_still_passes_key()
    test_watchdog_unsticks_state()
    print("\nAlle veiligheidstests geslaagd.")
