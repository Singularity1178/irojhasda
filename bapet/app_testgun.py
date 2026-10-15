"""App mixin: the weapon test gun.

Pick a weapon on the Interact tab and Ctrl + left mouse button fires one round of it from
the middle of the pets' screen at the cursor; holding the button keeps firing. It is a
bench for the per-weapon looks in vfx.WEAPON_FX - tracer, muzzle flash, brass, beam,
shotgun pellets, explosion - rather than a new kind of combat: no shooter to answer, no
magazine to empty and no aim roll.

The round is real, though. It stops on the first student it crosses and hits her through
exactly the same path a student's own bullet takes (Pet.shot_landed), so the hit spark, the
damage number, the flinch and the panel's ragdoll chance all behave as they do in a fight.
Students do not shoot back: there is nobody at the other end of it for them to turn on.

A press can reach us two ways, and both are folded into one step() so they cannot fight:

  * the global mouse hook (GlobalMouse), which sees Ctrl + left click anywhere on the
    desktop, over whatever app you are using;
  * the character's own window (Pet.mousePressEvent), which sees it whenever you click on
    a student. This is the important one to keep: the characters are click-through
    overlays, so a click on one is the natural way to aim, and it works with no OS hook at
    all - on a platform that has none, or when Windows refuses to install one.

A press the hook claims never reaches a window at all, so exactly one of the two answers
any given click.

Aiming always reads QCursor.pos() rather than the hook's own coordinates. Those are
physical screen pixels, while the overlay and every character window work in Qt's logical
ones, and the two stop agreeing the moment Windows display scaling is not 100%.
"""
from __future__ import annotations

import math
import time

from PySide6 import QtGui

from . import vfx
from .combat_config import SHOOT_BODY_HALF_W, TEST_GUN_INTERVAL
from .hotkey import GlobalMouse
from .mathutil import clamp


class AppTestGun:
    # Defaults on the class, not set in setup_mouse_hook(): the panel is built before
    # that runs and reads this state while it draws the weapon picker, so it has to
    # exist from the moment the App does rather than from the moment the hook is fitted.
    _gun_t = 0.0                            # s since the last round went out
    _gun_win_at = None                      # a press a character window saw this frame
    _gun_win_held = False                  # ... and whether its button is still down
    _gun_last = None                        # when the last round left, for the panel
    _gun_shots = 0                          # how many have gone out this run
    mouse_hook = None

    # ---- setup ----
    def setup_mouse_hook(self):
        """Ctrl + left click anywhere on the desktop, via a low-level mouse hook.

        A nicety, not a requirement: the character windows can fire the same shot on
        their own (gun_window_press). The hook is installed whatever the setting says,
        but only claims the click while a weapon is picked, so with the gun Off Ctrl +
        click reaches the app underneath exactly as it did before.
        """
        self.mouse_hook = GlobalMouse(self, enabled=lambda: bool(self.test_weapon()))

    def shutdown_mouse_hook(self):
        hk = getattr(self, "mouse_hook", None)
        if hk is not None: hk.remove()

    def test_weapon(self):
        """The weapon picked on the Interact tab, or "" while the test gun is off."""
        return self.cfg.get("test_weapon") or ""

    # ---- the two ways in ----
    def gun_window_press(self):
        """A Ctrl + left click landed on a character window. True when the window must
        treat it as the test gun and not as a poke or a rotate-drag.

        It records the press rather than firing straight away, so both routes go through
        the same step() and cannot double up on one click."""
        if not self.test_weapon(): return False
        self._gun_win_at = QtGui.QCursor.pos()
        self._gun_win_held = True
        return True

    def gun_window_release(self):
        """The button came up over a character window. Safe to call from anywhere: a gun
        press never starts a drag, so this is the only release such a press can have."""
        self._gun_win_held = False

    # ---- the loop side ----
    def test_gun_step(self, dt):
        """One frame of the test gun: fire a press at once, then every
        TEST_GUN_INTERVAL while the button is held, each round aimed at wherever the
        cursor is by then. Does nothing at all unless a weapon is selected."""
        weapon = self.test_weapon()
        at, held = self.gun_press_state()
        if not weapon:
            # Switching the weapon to Off mid-press must let go, or turning it back on
            # with the button still down would start firing again under your finger.
            self._gun_t = 0.0; self._gun_win_held = False; self._gun_win_at = None
            hk = getattr(self, "mouse_hook", None)
            if hk is not None: hk.fired = False; hk.held = False
            return
        if at is not None:                     # a press is a shot even if the button is
            self.test_gun_fire(weapon, at)     # already back up: a fast tap is still a tap
            return
        if not held:
            self._gun_t = 0.0
            return
        self._gun_t += dt
        if self._gun_t >= TEST_GUN_INTERVAL:   # held: keep tracking the cursor
            self._gun_t = 0.0
            self.test_gun_fire(weapon, QtGui.QCursor.pos())

    def gun_press_state(self):
        """((x, y) of a press seen this frame, or None, the button is held).

        A press and its release can both land inside one frame - a fast tap is quicker
        than the 33 ms a 30 fps frame takes - so the press is reported on its own, and
        never conditioned on the button still being down."""
        hk = getattr(self, "mouse_hook", None)
        at = None
        held = self._gun_win_held
        if self._gun_win_at is not None:
            at = self._gun_win_at; self._gun_win_at = None
        if hk is not None:
            hk.sync_button()                  # never let a missed release keep firing
            if hk.fired:
                hk.fired = False
                at = QtGui.QCursor.pos()       # the hook's own point is physical px: see
            held = held or hk.held             # the module docstring, so read the cursor
        return at, held

    def test_gun_fire(self, weapon, at):
        """One round of `weapon` from the middle of the pets' screen to `at` (a Qt global
        point). Muzzle flash and brass at the muzzle, then the round itself; it ends on
        the first student in the way, or on the cursor if the line is clear."""
        tx, ty = float(at.x()), float(at.y())
        look = vfx.weapon_fx(weapon)
        g = self.resolve_screen()
        c = g.center()
        sx, sy = c.x() + 0.5, c.y() + 0.5
        d = math.hypot(tx - sx, ty - sy)
        if d < 1.0: return                     # clicked the muzzle itself: nowhere to go
        ux, uy = (tx - sx) / d, (ty - sy) / d
        fx = self.shotfx
        # The overlay spans the WHOLE virtual desktop, not just the pets' screen. With
        # two monitors the cursor is often on the other one, and an overlay clipped to
        # the pets' screen would swallow most of the tracer - which looks exactly like
        # nothing having happened. Students are still only found on the pets' screen,
        # so a shot aimed at the other monitor simply flies off and sparks there.
        fx.ensure(self.qapp.primaryScreen().virtualGeometry() if self.qapp.primaryScreen()
                  else self.resolve_screen())
        fx.fancy = bool(self.cfg.get("ba_vfx", True))
        ang = math.atan2(uy, ux)
        fsz = float(look.get("flash", 1.0)) * clamp(math.sqrt(max(0.4, self.cfg["scale"])), 0.7, 1.4)
        fx.flash(sx, sy, ang, fsz, look.get("color"))
        if look.get("casing"):                # brass out of the ejection port, backwards
            fx.casing(sx - ux * 40.0, sy - uy * 40.0, 1 if ux >= 0 else -1)
        q, ex, ey = self.first_student_in_line(sx, sy, tx, ty)
        if q is None:
            fx.fire(sx, sy, tx, ty, impact="spark", weapon=weapon)
        else:
            fx.fire(sx, sy, ex, ey, impact="spark", weapon=weapon,
                    cb=lambda q=q, ux=ux, uy=uy, look=look: q.shot_landed(None, ux, uy, None, look=look))
        self._gun_last = time.monotonic(); self._gun_shots += 1

    # ---- who is in the way ----
    def first_student_in_line(self, x0, y0, x1, y1):
        """(student, x, y): the first student the segment (x0, y0)->(x1, y1) crosses,
        and where it crosses her. (None, x1, y1) when the line is clear.

        The body box is the same one a student's own bullets test (SHOOT_BODY_HALF_W), so
        a shot from here and a shot from a gun in her hand agree on what counts as a hit.
        Nearest along the line wins, so a student standing in front of another takes the
        round. Nobody can be skipped and nobody gets an intercept roll: a click is aimed,
        which is the whole point of the test gun.
        """
        dx, dy = x1 - x0, y1 - y0
        found = []
        for q in self.pets:
            if not q.isVisible() or q.ragdoll or q.dragging: continue
            fx, fy = q.feet_pos(); ch = q.char_h(); hw = ch * SHOOT_BODY_HALF_W
            tmin, tmax = 0.0, 1.0               # slab test: the segment vs her body box
            for o, dd, lo, hi in ((x0, dx, fx - hw, fx + hw), (y0, dy, fy - ch, fy)):
                if abs(dd) < 1e-6:
                    if o < lo or o > hi: tmin, tmax = 1.0, 0.0; break
                else:
                    ta, tb = (lo - o) / dd, (hi - o) / dd
                    if ta > tb: ta, tb = tb, ta
                    tmin, tmax = max(tmin, ta), min(tmax, tb)
                    if tmin > tmax: break
            if tmin <= tmax: found.append((tmin, q))
        if not found: return None, x1, y1
        t, q = min(found, key=lambda i: i[0])
        t = min(1.0, t + 0.02)                  # a hair inside her, so the spark lands on her
        return q, x0 + dx * t, y0 + dy * t

    # ---- what the panel shows ----
    def gun_status(self):
        """One line under the picker: what is selected, and whether a round has actually
        gone out. Without it a hook that never fires and a hook that fires but misses are
        indistinguishable from the outside."""
        hk = getattr(self, "mouse_hook", None)
        where = "click anywhere" if (hk is not None and hk.enabled) else "click a student"
        weapon = self.test_weapon()
        if not weapon:
            return f"Off - your Ctrl + click is your Windows' again. ({self._gun_shots} test rounds so far)"
        last = self._gun_last
        ago = "-" if last is None else f"{(time.monotonic() - last):.1f}s ago"
        return (f"{weapon} - Ctrl + left click ({where}); "
                f"last round {ago}; {self._gun_shots} so far")