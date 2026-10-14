"""GlobalHotkey: system-wide Ctrl+1 via a low-level keyboard hook (Windows)."""
from __future__ import annotations

import ctypes
import sys

from PySide6 import QtCore


# =============================================================================
#  Global hotkey (system-wide, Windows)
# =============================================================================
# Ctrl+1 anywhere in Windows flops whatever character is under the cursor, so it
# works while you are typing in something else - which is the whole point, since
# the pets are click-through overlays that rarely hold keyboard focus.
#
# A WH_KEYBOARD_LL hook rather than RegisterHotKey: Ctrl+1 belongs to a browser or
# editor half the time, and RegisterHotKey can lose that race. The low-level hook
# sees the key before anything else does. It also swallows Ctrl+1 so the app under
# the cursor does not also act on it (browser zoom reset and friends).
#
# The callback does nothing but raise a flag. Windows silently unhooks a low-level
# hook that takes longer than LowLevelHooksTimeout to answer, so the real work
# happens in App.tick() one frame later.
HOTKEY_VK_ONE = (0x31, 0x61)                  # '1' on the top row, and the numpad 1

HOTKEY_VK_CTRL = (0x11, 0xA2, 0xA3)              # generic / left / right control
HOTKEY_VK_SHIFT = (0x10, 0xA0, 0xA1)
HOTKEY_VK_ALT = (0x12, 0xA4, 0xA5)
HOTKEY_VK_WIN = (0x5B, 0x5C)
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WH_KEYBOARD_LL = 13


class _KbdEvent(ctypes.Structure):
    """KBDLLHOOKSTRUCT. dwExtraInfo is ULONG_PTR, so this is 24 bytes on x64."""
    _fields_ = [("vkCode", ctypes.c_uint32), ("scanCode", ctypes.c_uint32),
                ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("extra", ctypes.c_size_t)]

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


class GlobalHotkey(QtCore.QObject):
    """System-wide Ctrl+1. Raises `fired`; nothing else happens inside the hook."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fired = False
        self._proc = None; self._h = None
        self._down = set()                     # modifier keys currently held
        self.enabled = self.install()

    def _match(self, vk, wp):
        pressed = wp in (WM_KEYDOWN, WM_SYSKEYDOWN)
        mods = HOTKEY_VK_CTRL + HOTKEY_VK_SHIFT + HOTKEY_VK_ALT + HOTKEY_VK_WIN
        if vk in mods:
            self._down.add(vk) if pressed else self._down.discard(vk)
            return False
        # Ctrl + a top-row (or numpad) 1, with nothing else held so we do not
        # steal Ctrl+Shift+1, Alt+Ctrl+1 or Win+Ctrl+1 from whatever needs them.
        want_ctrl = any(v in self._down for v in HOTKEY_VK_CTRL)
        others = any(v in self._down for v in HOTKEY_VK_SHIFT + HOTKEY_VK_ALT + HOTKEY_VK_WIN)
        return want_ctrl and not others and vk in HOTKEY_VK_ONE

    def install(self):
        if sys.platform != "win32":
            return False
        try:
            u32 = ctypes.windll.user32
            u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32]
            u32.SetWindowsHookExW.restype = ctypes.c_void_p
            u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            u32.UnhookWindowsHookEx.restype = ctypes.c_bool
            u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
            u32.CallNextHookEx.restype = ctypes.c_ssize_t

            def cb(code, wparam, lparam):
                # Nothing in here may raise: ctypes would print a traceback per
                # keystroke and answer 0, which both spams the console and lets the
                # key through to the app underneath.
                try:
                    if code >= 0:
                        # lparam arrives as a plain int, so wrap it before casting.
                        vk = int(ctypes.cast(ctypes.c_void_p(lparam),
                                              ctypes.POINTER(_KbdEvent)).contents.vkCode)
                        if self._match(vk, wparam) and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            self.fired = True
                            return 1                   # ours now: don't pass it on
                except Exception:
                    pass
                return u32.CallNextHookEx(None, code, wparam, lparam)

            self._proc = HOOKPROC(cb)                   # must stay referenced
            # hMod NULL is correct here: the procedure lives in this process and the
            # hook covers the whole desktop, not one thread.
            self._h = u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            if not self._h:
                self._proc = None
                print("[warn] global Ctrl+1 hook refused by Windows; using the in-app shortcut only")
                return False
            print("[info] global hotkey ready: Ctrl+1 (any app, any time)")
            return True
        except Exception as e:
            print(f"[warn] global Ctrl+1 hook failed: {e}")
            return False

    def remove(self):
        if self._h:
            try: ctypes.windll.user32.UnhookWindowsHookEx(self._h)
            except Exception: pass
            self._h = None
        self._proc = None
