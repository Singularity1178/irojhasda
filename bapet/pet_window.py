"""Pet mixin: window geometry, flags, scale, click-through, riding a vehicle."""
from __future__ import annotations

import ctypes
import math
import sys

from PySide6.QtCore import Qt

from .config import BASE_H, BASE_W
from .mathutil import clamp
from .ragdoll_config import RAG_WINDOW_SCALE


class PetWindow:
    # ---------------- geometry helpers ----------------
    def feet_pos(self): return self.px + self.W / 2, self.py + self.H * (1 - self.PADB)

    def set_feet(self, fx, fy):
        self.px = fx - self.W / 2; self.py = fy - self.H * (1 - self.PADB)
        self.move(int(round(self.px)), int(round(self.py)))

    def apply_flags(self, show=True):
        f = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.cfg["always_on_top"]: f |= Qt.WindowType.WindowStaysOnTopHint
        vis = self.isVisible()
        self.setWindowFlags(f)
        self._pt = False        # recreating the window resets the ex-style
        if vis or show: self.show()

    def set_passthrough(self, on):
        """A3: on Windows let the window manager do hit-testing per pixel instead
        of an every-3rd-frame mask region, which clipped fast limbs and swallowed
        the heart / star / puff particles."""
        if sys.platform != "win32" or on == self._pt or not self.isVisible(): return
        self._pt = on
        try:
            u = ctypes.windll.user32
            u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]; u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            hwnd = int(self.winId())
            st = u.GetWindowLongW(hwnd, -20)                             # GWL_EXSTYLE
            u.SetWindowLongW(hwnd, -20, (st | 0x80020) if on else (st & ~0x20))
        except Exception: pass

    def apply_scale(self):
        # Her window is the shared --scale one times whatever her own profile
        # asks for (see load_profile). Both numbers move while she is riding, so
        # they are read live off the character rather than cached here.
        # While she is limp the whole window is multiplied once more by rag_win
        # (see rag_window): a tumbling body reaches well outside the standing
        # pose's frame and the window edge clipped it. It is ONLY extra room
        # around her - the camera inside widens by the same factor (Renderer.
        # set_fit), so she is drawn at exactly the same size in exactly the same
        # place, and the physics, which all measures real screen px, does not
        # see a different character at all.
        s = self.cfg["scale"] * self.ch.window_scale; fx, fy = self.feet_pos()
        k = self.rag_win
        self.W, self.H = int(BASE_W * s * self.ch.window_aspect * k), int(BASE_H * s * k)
        scr = self.screen()
        self.dpr = scr.devicePixelRatio() if scr else 1.0
        self.G = 2600.0 * max(0.6, s)           # px/s^2: about her, NOT about her window
        self.bfont.setPointSizeF(max(8.0, 9.5 * math.sqrt(s)))
        self.setFixedSize(self.W, self.H)
        self.ch.renderer.set_size(max(32, int(round(self.W * self.dpr))), max(32, int(round(self.H * self.dpr))))
        self.ch.renderer.set_fit(self.ch.fit, k)
        self.set_feet(fx, fy); self.mask_dirty = True

    # ---------------- the bigger window a limp student gets ----------------
    def rag_window_scale(self):
        """How much bigger her window gets while she is limp. 1.0 = never grows.

        A multiplier rather than a fixed size: the models differ by a factor of a
        few, so what a body needs is room AROUND her, and a ratio scales with
        whatever window she already has (profile scale, --scale, a ride window).
        Physics page / cfg `ragdoll_window_scale`.
        """
        try:
            k = float(self.cfg.get("ragdoll_window_scale", RAG_WINDOW_SCALE))
        except (TypeError, ValueError):
            k = RAG_WINDOW_SCALE
        return clamp(k, 1.0, 4.0)

    def rag_window(self, on):
        """Grow her window while she is limp (or shrink it back). See apply_scale.

        Her feet stay exactly where they were: apply_scale reads feet_pos()
        before it touches W / H and puts them back after, so the extra room all
        goes on the far side of her, where a body that has fallen over needs it.
        """
        k = self.rag_window_scale() if on else 1.0
        if abs(k - self.rag_win) < 1e-3: return
        self.rag_win = k
        self.apply_scale()

    def stand_w(self):
        """Her STANDING window width, window px: W without the limp window.

        Anything sized against her rather than against the frame reads this: W is
        the frame, which is RAG_WINDOW_SCALE times wider than the pose the model
        is measured from while she is down.
        """
        return self.W / max(1e-3, self.rag_win)

    def stand_h(self):
        """Her STANDING window height, window px. See stand_w."""
        return self.H / max(1e-3, self.rag_win)

    # ---------------- riding a vehicle (profile `ride`, e.g. Iroha's tank) ------
    def set_ride(self, on, fade=True):
        """Mount or stow her vehicle. Called from enter() on every state change.

        Three things move together, because they cannot move apart: the clip set
        (her on-foot clips key the tank bone to nothing, so the vehicle only
        exists in a riding pose), the window (it is sized for the vehicle, or she
        is twice as tall as everybody else), and the vehicle's own opacity.

        The pose swap itself is a hard cut and always will be - Rig.play refuses to
        cross-fade two clips that disagree about bone scale, and they do, by three
        orders of magnitude. So the transition is carried by the vehicle instead:
        `ride_t` walks 0 -> 1 over the profile's fade and Renderer draws the tank
        at that opacity, which reads as the tank deploying around her rather than
        appearing between two frames.

        fade=False skips that and stows at once, for the states that are a
        physical change rather than a beat: going limp or picked up, where the
        ragdoll measures itself against the window it finds.
        """
        if self.ch.ride_clips is None: return
        if on:
            if self.ride_on: return
            self.ride_on = True; self.ride_to = 1.0
            if not fade: self.ride_t = 1.0
            self.clips = self.ch.ride_clips
            self._ride_window(self.ch.ride_win)
            # The clip that was playing belongs to the set we just put down, so
            # start its riding twin. Without this she keeps walking on foot inside
            # a tank-sized window until something else picks an animation.
            self.play(self.anim_key, restart=False)
        else:
            self.ride_to = 0.0
            # Dismounting keeps the riding pose and the riding window until the
            # tank has finished fading - advance_ride hands both back after.
            if not fade: self.ride_t = 0.0
            if not self.ride_on or self.ride_t <= 0.0: self._ride_stow()

    def _ride_stow(self):
        """Back on foot: the ordinary clips, the ordinary window, no vehicle."""
        if not self.ride_on: return
        self.ride_on = False
        self.clips = self.ch.clips
        self._ride_window(self.ch.win)
        # The clip that was playing belongs to the set we just put down, so pick
        # its twin again. Restarting it would look like a hiccup mid-reload.
        self.play(self.anim_key, restart=False)

    def advance_ride(self, dt):
        """Walk the vehicle in or out. Every frame, from tick()."""
        if self.ch.ride_clips is None or self.ride_t == self.ride_to: return
        step = dt / max(self.ch.ride_fade, 0.05)
        self.ride_t = clamp(self.ride_t + (step if self.ride_to > 0.0 else -step), 0.0, 1.0)
        if self.ride_to <= 0.0 and self.ride_t <= 0.0: self._ride_stow()

    def _ride_window(self, w):
        """Swap her window (and the camera inside it) to another preset."""
        ch = self.ch
        if ch.window_scale == w["scale"] and ch.window_aspect == w["aspect"] and ch.fit is w["fit"]: return
        ch.window_scale, ch.window_aspect = w["scale"], w["aspect"]
        ch.fit, ch.fit_clip, ch.body_frac = w["fit"], w["clip"], w["body_frac"]
        ch.renderer.set_fit(w["fit"])       # the camera inside the window moves with it
        self.apply_scale()                  # ... and the window itself resizes

    def reset_position(self):
        g = self.A.resolve_screen()
        fx = self.A.clamp_x(g.right() - self.W * 0.9, self.W)
        self.rag_clear()
        self.support = None; self.grounded = True; self.dragging = False; self.vx = self.vy = 0
        self.set_feet(fx, self.A.floor_y(fx)); self.enter("idle")
