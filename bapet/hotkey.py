"""GlobalHotkey: system-wide Ctrl+1 via a low-level keyboard hook (Windows).

GlobalMouse, at the bottom, is the same idea for Ctrl + left mouse button.
"""
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


# =============================================================================
#  Global mouse hook (system-wide, Windows)
# =============================================================================
# Ctrl + left mouse button anywhere fires the weapon picked on the Interact tab
# from the middle of the pets' screen at the cursor. A WH_MOUSE_LL hook for the same
# reason as the keyboard one: the characters are click-through overlays that hardly
# ever see a press, and the point of a test gun is to be able to shoot at them while
# doing something else.
#
# The hook only records the press and answers. The work happens in App.tick() one
# frame later, and `enabled()` is asked on every press: while the weapon is Off the
# hook answers "not mine" and Ctrl + click reaches whatever is under the cursor
# exactly as it did before, so the feature costs nothing when it is not in use.
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
WM_LBUTTON_DN = (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK)
WH_MOUSE_LL = 14
VK_LBUTTON = 0x01
VK_CONTROL = (0x11, 0xA2, 0xA3)              # generic / left / right control


class _MouseEvent(ctypes.Structure):
    """MSLLHOOKSTRUCT. dwExtraInfo is ULONG_PTR, so this is 32 bytes on x64."""
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long),
                ("mouseData", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("extra", ctypes.c_size_t)]


def _down(vk):
    try: return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception: return False


class GlobalMouse(QtCore.QObject):
    """System-wide Ctrl + left click. Raises `fired` and remembers where; every button
    release clears `held`. Nothing else happens inside the hook.

    enabled  called on every press to ask whether a weapon is selected right now.
    """

    def __init__(self, parent=None, enabled=None):
        super().__init__(parent)
        self.fired = False                       # a press waiting to be acted on
        self.pos = None                          # where it happened, in global px
        self.held = False                        # the button is down and the press was ours
        self._ours = False                       # ... and it is still down
        self._proc = None; self._h = None
        self._armed = enabled or (lambda: False)
        self.enabled = self.install()

    def sync_button(self):
        """Safety net for a release the hook never saw (a hook installed or removed while
        the button was already down, a swallowed press eaten by another hook): without it
        `held` could stay True and the gun would keep firing on its own."""
        if self._ours and not _down(VK_LBUTTON):
            self._ours = False; self.held = False

    def _handle(self, wparam, x, y):
        """(swallow?) for one mouse message. Never raises."""
        try:
            if wparam in WM_LBUTTON_DN:
                if not (self._armed() and any(_down(vk) for vk in VK_CONTROL)):
                    return False
                self.fired = True; self.pos = (int(x), int(y))
                self.held = True; self._ours = True
                return True
            if wparam == WM_LBUTTONUP and self._ours:
                self._ours = False; self.held = False
                return True                       # ours: the matching press was swallowed too
        except Exception:
            self._ours = False; self.held = False
        return False

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
            k32 = ctypes.windll.kernel32
            # Without this the handle comes back as a 32-bit int and the top half of a
            # 64-bit module handle is thrown away, which Windows reports as a bad hook.
            k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            k32.GetModuleHandleW.restype = ctypes.c_void_p

            def cb(code, wparam, lparam):
                # Nothing in here may raise: ctypes would print a traceback per click
                # and answer 0, which both spams the console and lets the click through.
                try:
                    if code >= 0 and (wparam in WM_LBUTTON_DN or wparam == WM_LBUTTONUP):
                        ev = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(_MouseEvent)).contents
                        if self._handle(wparam, ev.x, ev.y):
                            return 1               # ours now: don't pass it on
                except Exception:
                    pass
                return u32.CallNextHookEx(None, code, wparam, lparam)

            self._proc = HOOKPROC(cb)                   # must stay referenced
            # A real module handle rather than NULL. NULL is documented as fine for a
            # low-level hook whose procedure lives in this process, but only alongside a
            # dwThreadId that names one of our threads; with dwThreadId 0 (the whole
            # desktop) Windows is free to refuse it, and a refused WH_MOUSE_LL hook fails
            # silently - it just never fires. GetModuleHandleW(None) is our own module,
            # which is exactly what the hook procedure is in, and is accepted either way.
            hmod = k32.GetModuleHandleW(None)
            self._h = u32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, hmod, 0)
            if not self._h:
                self._proc = None
                print("[warn] global mouse hook refused by Windows; the weapon test gun "
                      "will only work on clicks that land on a character")
                return False
            print("[info] global mouse hook ready: Ctrl + left click (while a weapon is picked)")
            return True
        except Exception as e:
            print(f"[warn] global mouse hook failed: {e} - the weapon test gun will only "
                  f"work on clicks that land on a character")
            return False

    def remove(self):
        self.held = False; self._ours = False; self.fired = False
        if self._h:
            try: ctypes.windll.user32.UnhookWindowsHookEx(self._h)
            except Exception: pass
            self._h = None
        self._proc = None
