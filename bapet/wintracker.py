"""WinTracker: finds the open windows pets can stand on (Windows, ctypes)."""
from __future__ import annotations

import ctypes
import os
import sys


# =============================================================================
#  Windows: top-of-window perches (ctypes, no extra deps)
# =============================================================================
class WinTracker:
    SKIP = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
            "XamlExplorerHostIslandWindow", "ApplicationFrameInputSinkWindow", "TopLevelWindowForOverflowXamlIsland"}

    def __init__(self):
        self.enabled = sys.platform == "win32"; self.wins = []
        if self.enabled:
            try:
                from ctypes import wintypes
                self.wt = wintypes
                self.u32 = ctypes.windll.user32; self.dwm = ctypes.windll.dwmapi
                self.u32.IsWindowVisible.argtypes = [wintypes.HWND]
                self.u32.IsIconic.argtypes = [wintypes.HWND]
                self.u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
                self.u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                self.u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                self.u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                self.dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
                self.proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                self.pid = os.getpid()
            except Exception:
                self.enabled = False

    def refresh(self, dpr, top_limit):
        if not self.enabled: return
        wt, out = self.wt, []
        cls = ctypes.create_unicode_buffer(256)
        def cb(hwnd, _lp):
            try:
                if not self.u32.IsWindowVisible(hwnd) or self.u32.IsIconic(hwnd): return True
                if self.u32.GetWindowTextLengthW(hwnd) == 0: return True
                pid = wt.DWORD(0); self.u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.pid: return True
                self.u32.GetClassNameW(hwnd, cls, 256)
                if cls.value in self.SKIP: return True
                cloaked = ctypes.c_int(0)
                self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
                if cloaked.value: return True
                r = wt.RECT()
                if self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                    self.u32.GetWindowRect(hwnd, ctypes.byref(r))
                l, t, rr, b = r.left / dpr, r.top / dpr, r.right / dpr, r.bottom / dpr
                if rr - l < 160 or b - t < 80 or t < top_limit + 60: return True
                out.append((int(hwnd) if hwnd else 0, l, t, rr, b))
            except Exception:
                pass
            return True
        try:
            self.u32.EnumWindows(self.proc(cb), 0)
            self.wins = out
        except Exception:
            self.enabled = False

    def rect(self, hwnd):
        for w in self.wins:
            if w[0] == hwnd: return w[1:]
        return None

    def surfaces(self, fx):
        res = []
        for i, (h, l, t, r, b) in enumerate(self.wins):
            if l + 6 <= fx <= r - 6:
                covered = any(l2 <= fx <= r2 and t2 <= t + 3 <= b2 for (_, l2, t2, r2, b2) in self.wins[:i])
                if not covered: res.append((t, h))
        return res
