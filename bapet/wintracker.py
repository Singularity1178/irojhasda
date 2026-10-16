"""WinTracker: finds the open windows pets can stand on (Windows, ctypes).

Occlusion. EnumWindows walks top-level windows front to back, so every window
seen before another one is drawn ABOVE it. A window that is shown (not
minimised) but hidden behind the ones in front of it is not there as far as a
student is concerned - she must not stand on it, walk along it, or bounce off
it in a ragdoll, i.e. off thin air. So each window is reduced to the part of
it that is actually still visible:

  * windows hidden underneath are dropped outright,
  * windows half hidden are clipped down to the exposed strip,
  * a window whose title bar (the bit a student actually perches on) is
    covered is dropped, because there is no longer a top edge to land on.

Everything that reads the window list - perching, jump targets, both physics
worlds - gets the corrected rects at once, and WinTracker.surface_visible()
re-checks a window a character is standing on every frame so covering her
mid-walk drops her instead of leaving her on nothing.

Occluders are ALL visible windows in front, including ones too small or too
high (a maximised window's top sits above the screen top) to be perches
themselves.
"""
from __future__ import annotations

import ctypes
import os
import sys

# A perch has to be big enough to stand on at all...
MIN_WIN_W = 160.0
MIN_WIN_H = 80.0
# ...and its title bar is the surface, so it has to leave a wide enough strip.
MIN_PERCH_W = 140.0
TITLE_BAND_H = 28.0
# Under this fraction of its area still visible a window stops being a perch,
# no matter how big it is: a 5% sliver of a window is not somewhere to stand.
MIN_VISIBLE_FRAC = 0.25


def _uncovered_area(l, t, r, b, above, clip=None, eps=0.0, max_pieces=256):
    """Exact area of (l, t, r, b) left after subtracting every rect in `above`.

    Plain rectangle subtraction: start with the window (clipped to the
    desktop), cut each window in front out of it, and see what is left.
    """
    if clip is not None:
        l, t = max(l, clip[0]), max(t, clip[1])
        r, b = min(r, clip[2]), min(b, clip[3])
    if r - l <= eps or b - t <= eps:
        return 0.0
    pieces = [(l, t, r, b)]
    for ol, ot, orr, ob in above:
        nxt = []
        for pl, pt, pr, pb in pieces:
            if orr <= pl or ol >= pr or ob <= pt or ot >= pb:
                nxt.append((pl, pt, pr, pb)); continue
            if ot > pt: nxt.append((pl, pt, pr, ot))                  # strip above the occluder
            if ob < pb: nxt.append((pl, ob, pr, pb))                  # strip below it
            mt, mb = (pt if pt > ot else ot), (pb if pb < ob else ob)
            if mb > mt:
                if ol > pl: nxt.append((pl, mt, ol, mb))             # left of it
                if orr < pr: nxt.append((orr, mt, pr, mb))           # right of it
        pieces = nxt
        if not pieces:
            return 0.0
        if len(pieces) > max_pieces:
            return (r - l) * (b - t)        # pathological stack: assume it is still visible
    return sum((pr - pl) * (pb - pt) for pl, pt, pr, pb in pieces)


def _uncovered_top_spans(l, t, r, b, above, clip=None):
    """Horizontal intervals along the window's top title bar that nothing in front covers."""
    if clip is not None:
        l = max(l, clip[0]); r = min(r, clip[2]); t = max(t, clip[1])
    band_b = min(b, t + TITLE_BAND_H)
    spans = [(l, r)]
    for ol, ot, orr, ob in above:
        if ot <= band_b and ob > t + 2.0:        # reaches down over the title bar
            nxt = []
            for s0, s1 in spans:
                if orr <= s0 or ol >= s1:
                    nxt.append((s0, s1))
                else:
                    if ol > s0: nxt.append((s0, ol))
                    if orr < s1: nxt.append((orr, s1))
            spans = nxt
            if not spans:
                return []
    return [s for s in spans if s[1] - s[0] >= MIN_PERCH_W]


# =============================================================================
#  Windows: top-of-window perches (ctypes, no extra deps)
# =============================================================================
class WinTracker:
    SKIP = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
            "XamlExplorerHostIslandWindow", "ApplicationFrameInputSinkWindow", "TopLevelWindowForOverflowXamlIsland"}

    # Slivers thinner than this (px) do not count as visible: the DWM frame
    # bounds of stacked / snapped windows often differ by a pixel or two.
    COVER_EPS = 3.0
    COVER_MAX_PIECES = 256      # give up (= treat as visible) past this; never hit in practice

    def __init__(self):
        self.enabled = sys.platform == "win32"; self.wins = []
        self._occ_before = {}      # hwnd -> the full rects of every window in front of it
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
                self.u32.GetSystemMetrics.argtypes = [ctypes.c_int]
                self.dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
                self.proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                self.pid = os.getpid()
            except Exception:
                self.enabled = False

    def refresh(self, dpr, top_limit):
        """Rebuild self.wins: the still-visible part of every window, Z order front to back.

        A window that is shown but buried under the windows in front of it - a
        terminal behind a maximised browser, say - is invisible on screen, so it
        must not be solid either: before, students could perch on it and limp
        bodies bounced off it, i.e. off thin air. Each candidate is cut down to
        its exposed part here, which covers every user of the list at once
        (perching, jump targets, both physics worlds - they re-sync whenever
        this list changes).
        """
        if not self.enabled: return
        wt, cands = self.wt, []
        cls = ctypes.create_unicode_buffer(256)
        def cb(hwnd, _lp):
            try:
                if not self.u32.IsWindowVisible(hwnd) or self.u32.IsIconic(hwnd): return True
                if self.u32.GetWindowTextLengthW(hwnd) == 0: return True
                pid = wt.DWORD(0); self.u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.pid: return True        # our own pets / panel never hide a window
                self.u32.GetClassNameW(hwnd, cls, 256)
                if cls.value in self.SKIP: return True
                cloaked = ctypes.c_int(0)
                self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
                if cloaked.value: return True
                r = wt.RECT()
                if self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                    self.u32.GetWindowRect(hwnd, ctypes.byref(r))
                l, t, rr, b = r.left / dpr, r.top / dpr, r.right / dpr, r.bottom / dpr
                if rr - l < 1 or b - t < 1: return True
                usable = not (rr - l < MIN_WIN_W or b - t < MIN_WIN_H or t < top_limit + 60.0)
                cands.append((int(hwnd) if hwnd else 0, l, t, rr, b, usable))
            except Exception:
                pass
            return True
        try:
            self.u32.EnumWindows(self.proc(cb), 0)
        except Exception:
            self.enabled = False
            return
        vis = self.virtual_rect(dpr)
        out, above, occ_before = [], [], {}
        for h, l, t, rr, b, usable in cands:
            if usable:
                v = self._visible_rect((l, t, rr, b), above, vis)
                if v is not None:
                    occ_before[h] = list(above)
                    out.append((h, v[0], v[1], v[2], v[3]))
            # Every window occludes whatever is behind it, whether or not it is
            # big enough to be a perch itself, and whether or not it is visible
            # in its own right - it blocks whatever is behind it either way.
            above.append((l, t, rr, b))
        self.wins = out
        self._occ_before = occ_before

    def virtual_rect(self, dpr):
        """The whole desktop (all monitors), logical px - the part of a window off it is not 'visible'."""
        try:
            gm = self.u32.GetSystemMetrics
            x, y, w, h = gm(76), gm(77), gm(78), gm(79)     # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN
            if w > 0 and h > 0:
                return (x / dpr, y / dpr, (x + w) / dpr, (y + h) / dpr)
        except Exception:
            pass
        return None

    @classmethod
    def _visible_rect(cls, rect, above, clip=None):
        """(vl, vt, vr, vb) of the part of `rect` still visible, or None if it is not a perch.

        Three passes, cheapest first: enough area left to be worth anything, a
        title bar you can see (that is the surface a student lands on), then
        the body below it trimmed down to one clean rectangle.
        """
        l, t, r, b = rect
        full_w, full_h = r - l, b - t
        if full_w < MIN_WIN_W or full_h < MIN_WIN_H:
            return None
        area = _uncovered_area(l, t, r, b, above, clip, cls.COVER_EPS, cls.COVER_MAX_PIECES)
        if area < MIN_WIN_W * MIN_WIN_H or area < MIN_VISIBLE_FRAC * full_w * full_h:
            return None                          # buried, or only a sliver of it is left
        spans = _uncovered_top_spans(l, t, r, b, above, clip)
        if not spans:
            return None                          # no visible title bar: no top edge to land on
        vl, vr = max(spans, key=lambda s: s[1] - s[0])
        if vr - vl < MIN_WIN_W:
            return None
        vt, vb = t, b
        if clip is not None:
            vt = max(vt, clip[1]); vb = min(vb, clip[3])
        # The body under the exposed title bar can still be half hidden, and a
        # perch is a rectangle, so keep the biggest clean strip left rather
        # than a shape the collider and the walk edge cannot represent.
        for ol, ot, orr, ob in above:
            if orr <= vl or ol >= vr or ob <= vt or ot >= vb:
                continue
            cur_w, cur_h = vr - vl, vb - vt
            ov_w = min(vr, orr) - max(vl, ol)
            ov_h = min(vb, ob) - max(vt, ot)
            if ov_w <= 0.0 or ov_h <= 0.0:
                continue
            if ot <= vt + TITLE_BAND_H or ov_w >= 0.5 * cur_w or ov_w * ov_h >= 0.35 * cur_w * cur_h:
                cands = []
                if ol - vl >= MIN_WIN_W: cands.append((vl, vt, ol, vb))
                if vr - orr >= MIN_WIN_W: cands.append((orr, vt, vr, vb))
                if ot - vt >= MIN_WIN_H: cands.append((vl, vt, vr, ot))
                if not cands: return None
                vl, vt, vr, vb = max(cands, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
        if vr - vl < MIN_WIN_W or vb - vt < MIN_WIN_H:
            return None
        return (vl, vt, vr, vb)

    def rect(self, hwnd):
        for w in self.wins:
            if w[0] == hwnd: return w[1:]
        return None

    def surfaces(self, fx):
        res = []
        occ_map = getattr(self, "_occ_before", None) or {}
        for i, (h, l, t, r, b) in enumerate(self.wins):
            if l + 6 <= fx <= r - 6:
                # _occ_before holds the FULL rects of the windows in front; the
                # rects in self.wins are clipped, and a window in front may not
                # be a perch at all, so wins[:i] would not be the real occluders.
                front = occ_map.get(h)
                if front is None:
                    front = [w[1:] for w in self.wins[:i]]
                if not any(l2 <= fx <= r2 and t2 <= t + 3 <= b2 for (l2, t2, r2, b2) in front):
                    res.append((t, h))
        return res

    def surface_visible(self, hwnd, fx) -> bool:
        """True if `hwnd` is still an exposed perch at horizontal position `fx`.

        A character standing on a window whose title bar just got covered has
        nothing under her any more, and the window list alone will not say so -
        the window is still in it. PetBehavior.behave asks this every frame and
        drops her off when it goes false.
        """
        r = self.rect(hwnd)
        if r is None or not (r[0] + 4 <= fx <= r[2] - 4):
            return False
        return any(h == hwnd for _t, h in self.surfaces(fx))