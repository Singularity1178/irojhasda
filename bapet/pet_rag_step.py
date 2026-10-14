"""Pet mixin: per-frame ragdoll stepping (rod and pymunk) and its safety nets."""
from __future__ import annotations

import math
import traceback

from .deps import ragphys
from .mathutil import clamp
from .rag_diag import _ragdiag, _ragdiag_on
from .ragdoll_config import (
    RAG_EDGE_SLAM_MAX_T, RAG_FRICTION, RAG_GETUP_TIME, RAG_REST_E, RAG_REST_TIME
)


class PetRagStep:
    # ---------------- ragdoll: body (one rigid rod) ----------------
    def rag_ground(self, x, y_ref):
        """Top-most surface still at or below y_ref (windows are one-way platforms).

        The surface she is already resting on is pinned back in: without that,
        landing on a window title bar leaves the rod's low end below the bar, and
        the one-way test would then drop her straight through it on the next frame.
        """
        if self.rg_top is not None: y_ref = min(y_ref, self.rg_top + 8.0)
        for top, h in self.A.surfaces(x, self.cfg["perch"]):       # sorted top -> bottom
            if top >= y_ref - 6: return top, h
        return self.A.floor_y(x), None

    def ragdoll_step(self, dt):
        dt = min(dt, 1 / 30); s = max(0.6, self.cfg["scale"]); G = self.G
        ch, rad, drop, a = self.rag_geom(); gh = self.A.resolve_screen()
        self.rag_t += dt; self.rag_hit_t += dt
        v0x, v0y, w0 = self.rg_vx, self.rg_vy, self.rg_w
        blend = None
        if self.rag_edge_slam and self.rag_state != "getup" and self.rag_t > RAG_EDGE_SLAM_MAX_T:
            # An edge slam is meant to read as "a few seconds on the floor, then up".
            # rag_getup() defers by itself while she is still flying, so this cannot
            # stand her up in mid-air - it only stops a ragdoll that will never settle
            # (or one left behind by ragdoll_auto_getup=False) from lasting forever.
            blend = self.rag_getup()
        if self.rag_skel is not None:
            self.ragdoll_step_pm(dt); return
        if blend == "pm":
            # She just came off pymunk, so the skeleton is gone and ragdoll_step_pm
            # would no longer be reached. Drive her blend from here instead.
            self.rag_getup_step_pm(dt); return

        if self.rag_state == "getup":
            k = min(1.0, self.rag_t / RAG_GETUP_TIME); sm = k * k * (3 - 2 * k)
            ground, surf = self.rag_ground(self.rg_x, self.rg_y0 + a + rad)
            self.rg_a = self.rg_a0 * (1 - sm)
            self.rg_y = self.rg_y0 + (ground - a - rad - self.rg_y0) * sm
            self.rag_strength = 1 - sm
            self.rg_vx = self.rg_vy = self.rg_w = 0.0
            self.rg_top = ground
            self.set_feet(self.rg_x, self.rg_y + drop)
            if k >= 1.0: self.rag_end(surf)
            self.rag_accel(dt, v0x, v0y, w0); return

        # ---- integrate ----
        self.rg_vy += G * dt
        self.rg_x += self.rg_vx * dt; self.rg_y += self.rg_vy * dt; self.rg_a += self.rg_w * dt
        self.rg_w *= math.exp(-0.15 * dt)
        lo, hi = gh.left() + self.W * 0.15, max(gh.left() + self.W * 0.15, gh.right() - self.W * 0.15)
        if self.rg_x < lo:   self.rg_x = lo; self.rg_vx = abs(self.rg_vx) * 0.5;  self.rg_w *= 0.7
        elif self.rg_x > hi: self.rg_x = hi; self.rg_vx = -abs(self.rg_vx) * 0.5; self.rg_w *= 0.7
        ceil = gh.top() + a
        if self.rg_y < ceil: self.rg_y = ceil; self.rg_vy = abs(self.rg_vy) * 0.4

        # ---- contacts: rod ends (+ thickness) against the ground ----
        # Both ends stay active inside a small speculative margin (about a frame of
        # travel). Correcting penetration on its own drops the other end out of
        # contact every pass, and a rod lying flat then rocks itself forever instead
        # of settling - which would also mean she never lies still long enough to
        # get up. With the margin the sequential impulses actually converge.
        m, I = 1.0, 0.5 * a * a                       # fat rod: spins less than a thin one
        ground, surf = self.rag_ground(self.rg_x, self.rg_prev_low)
        margin = 2.0 * s + abs(self.rg_vy) * dt
        self.rag_contact = False; impact = 0.0
        for _ in range(6):
            for sgn in (1, -1):
                th = self.rg_a
                rx = sgn * a * math.sin(th); ry = -sgn * a * math.cos(th) + rad     # COM -> contact point
                pen = (self.rg_y + ry) - ground
                if pen < -margin: continue                 # nowhere near the surface
                if pen > 0.0:
                    self.rg_y -= pen                      # push her out
                    self.rag_contact = True
                vcx = self.rg_vx - self.rg_w * ry           # velocity of the contact point
                vcy = self.rg_vy + self.rg_w * rx
                if vcy <= 0: continue                       # already separating
                self.rag_contact = True
                e = RAG_REST_E if vcy > 500 * s else 0.0    # only real hits bounce
                j = (1 + e) * vcy / (1 / m + rx * rx / I)
                self.rg_vy -= j / m;  self.rg_w -= j * rx / I
                jt = clamp(-vcx / (1 / m + ry * ry / I), -RAG_FRICTION * j, RAG_FRICTION * j)
                self.rg_vx += jt / m; self.rg_w -= ry * jt / I
                impact = max(impact, vcy)
        th = self.rg_a
        self.rg_top = ground
        # Her rod is a capsule, so its lowest point is the lowest axis end plus the
        # thickness. Using exactly that as the one-way reference is what makes a
        # window title bar behave the way air() already does: she can land on it and
        # stay, and she can still drop through it from above.
        self.rg_prev_low = self.rg_y + rad + a * abs(math.cos(th))

        speed = math.hypot(self.rg_vx, self.rg_vy) + abs(self.rg_w) * a
        if self.rag_contact:
            self.rg_w *= math.exp(-3.0 * dt)                # lying on the floor: bleed spin
            self.rg_vx *= math.exp(-1.2 * dt)
            # Once the normal speed is a nudge rather than a hit, take the last of
            # the rocking out by hand: a pixel or two of solver jitter on a perfectly
            # flat floor would otherwise keep her from ever lying still.
            if abs(self.rg_vy) < 0.4 * 500 * s and abs(self.rg_w) < 1.0:
                self.rg_vy = 0.0
                self.rg_w *= math.exp(-9.0 * dt)
            if abs(math.sin(self.rg_a)) < 0.35:             # standing on her feet = unstable, tip her
                self.rg_w += (1 if math.sin(self.rg_a) >= 0 else -1) * 6 * dt
            # A rod stays balanced on one end only while something keeps disturbing
            # it, and nothing does once she has stopped moving - so ease whatever
            # tilt is left out of "lying flat". Modulo pi: which way she flops is free.
            if speed < 260.0 * s:
                d = (self.rg_a - 0.5 * math.pi) % math.pi
                if d > 0.5 * math.pi: d -= math.pi
                self.rg_a -= d * min(1.0, 4.0 * dt)
        if impact > 700 * s and self.rag_hit_t > 0.25:
            self.rag_hit_t = 0.0
            self.sq = min(0.26, impact / 6500)
            self.emit("puff", 5, self.W / 2, self.H * (1 - self.PADB), spread=90)

        # ---- rest detection -> auto get-up ----
        if self.rag_contact and speed < 40 * s: self.rag_rest += dt
        else: self.rag_rest = 0.0
        if self.rag_want_up and self.rag_rest > 0.2: self.rag_getup()
        elif self.cfg.get("ragdoll_auto_getup", True) and self.rag_rest > RAG_REST_TIME:
            self.rag_getup()

        # ---- sync window + legacy fields (hair/cloth springs read vx/vy) ----
        self.vx, self.vy = self.rg_vx, self.rg_vy
        self.set_feet(self.rg_x, self.rg_y + drop)
        self.rag_accel(dt, v0x, v0y, w0)
        if not all(map(math.isfinite, (self.rg_x, self.rg_y, self.rg_a))):   # failsafe: never get stuck
            self.rag_clear(); self.reset_position()

    # ---------------- ragdoll: the articulated body (pymunk) ----------------
    def ragdoll_step_pm(self, dt):
        """Read the physics pose and drive everything else off it.

        The world was stepped once for the whole app (App.tick), so this only
        reads. Three things come out of it: where her window goes, which bones
        get a post rotation this frame, and whether she is at rest yet.
        """
        sk = self.rag_skel
        if sk is None or sk.detached:
            self.ragdoll = False; return
        s = max(0.6, self.cfg["scale"])
        v0x, v0y, w0 = self.rg_vx, self.rg_vy, self.rg_w
        try:
            self.rag_pm_failsafe(sk)
            if not self.ragdoll:
                return                              # failsafe already cleaned up
            if self.rag_state == "getup":
                self.rag_getup_step_pm(dt)
                return
            pose = sk.pose()
            if not all(map(math.isfinite, (pose["x"], pose["y"], pose["angle"]))):
                self.rag_pm_drop("non-finite pose")
                return
            # --- window placement: her pivot (the pelvis) follows the body ---
            # render_frame rotates the model about the pelvis, so the pelvis has to
            # land exactly where physics says it is, and her feet are a fixed
            # distance below it (measured off the base pose when she went limp).
            self.rg_x, self.rg_y = pose["x"], pose["y"]
            self.rg_vx, self.rg_vy, self.rg_w = pose["vx"], pose["vy"], pose["w"]
            self.rg_a = -pose["phi"][sk.root]        # render_frame does rot_z4(-rg_a)
            self.rag_contact = sk.touching()
            self.set_feet(pose["x"] - self.rag_pel_dx, pose["y"] + sk.drop)
            self.vx, self.vy = pose["vx"], pose["vy"]   # hair / skirt / tie springs
            self.rag_pm_impacts()
            # --- rest detection -> auto get-up ---
            if self.rag_contact and sk.speed() < ragphys.RAGP_REST_SPEED * s:
                self.rag_rest += dt
            else:
                self.rag_rest = 0.0
            # --rag-diag: the get-up decision and the numbers behind it. A
            # character that never gets up is almost always this line, not the
            # physics: she is one px/s over RAGP_REST_SPEED forever, or
            # `rag_contact` is False while she is plainly on the floor.
            if _ragdiag_on():
                self._rag_diag_t = getattr(self, "_rag_diag_t", 0) + 1
                self._rag_diag_peak = max(getattr(self, "_rag_diag_peak", 0.0), sk.speed())
                # Every frame: diag_tick decides for itself whether the line is
                # worth printing, so it can drop the hundreds of identical
                # "still MOVING" lines and keep the ones where rest is counting.
                _ragdiag().diag_tick(
                    self.rag_owner, self._rag_diag_t, sk.speed(),
                    ragphys.RAGP_REST_SPEED * s, self.rag_contact,
                    self.rag_rest, RAG_REST_TIME, bool(self.rag_want_up),
                    bool(self.cfg.get("ragdoll_auto_getup", True)))
            if self.rag_want_up and self.rag_rest > 0.2:
                if _ragdiag_on():
                    _ragdiag().diag_getup(self.rag_owner, "wanted (cursor)", self.rag_rest)
                self.rag_getup()
            elif self.cfg.get("ragdoll_auto_getup", True) and self.rag_rest > RAG_REST_TIME:
                if _ragdiag_on():
                    _ragdiag().diag_getup(self.rag_owner, "auto", self.rag_rest)
                self.rag_getup()
            self.rag_accel(dt, v0x, v0y, w0)
        except Exception:
            traceback.print_exc()
            self.rag_pm_drop("ragdoll_step_pm raised")

    def rag_pm_cursor(self, cur):
        """Point the grab joint at the cursor, once per tick.

        Read here rather than in mouseMoveEvent on purpose. Qt only delivers a
        move event when the cursor actually moves, and delivers them in
        bunches when it moves fast, so the raw event stream is a poor thing to
        hand a constraint: it arrives irregularly and stops dead when the mouse
        stops. Sampling QCursor once per tick gives an evenly spaced target
        every frame, which is what makes her follow smoothly instead of
        juddering toward the mouse in steps.
        """
        sk = self.rag_skel
        if sk is not None and self.dragging and sk.grab_joint is not None:
            sk.move_grab((cur.x(), cur.y()))

    def rag_pm_impacts(self):
        """Turn physics hits into the squash, the dust puff and the sound."""
        W = self.A.rag_world
        if W is None:
            return
        for im in W.pop_impacts(self.rag_owner):
            if im.strength < 0.05:
                continue
            self.sq = min(ragphys.RAGP_SQUASH_MAX, im.strength / ragphys.RAGP_SQUASH_DIV)
            if im.strength > ragphys.RAGP_IMPACT_SOUND:
                play = getattr(self.A, "play_rag_sound", None)
                if play:
                    play()
            if self.rag_hit_t > ragphys.RAGP_IMPACT_COOLDOWN:
                self.rag_hit_t = 0.0
                lx, ly = im.point[0] - self.px, im.point[1] - self.py
                self.emit("puff", 5, lx, ly, spread=90)

    def rag_pm_failsafe(self, sk):
        """Catch the three ways physics can go wrong, and undo all of them."""
        gh = self.A.resolve_screen()
        if sk.explode_guard():
            self.rag_pm_drop("non-finite body")
        elif sk.outside((gh.left(), gh.top(), gh.right(), gh.bottom()),
                        self.char_h()):
            sk.snap_inside((gh.left(), gh.top(), gh.right(), gh.bottom()),
                           self.char_h())

    def rag_pm_drop(self, why):
        """Give up on physics for this pet and put her back on her feet."""
        print(f"[ragdoll] {self.name}: {why}; standing her back up")
        self.rag_clear(); self.reset_position()

    def rag_getup_step_pm(self, dt):
        """Blend the frozen lying pose back to standing, then rag_end."""
        k = min(1.0, self.rag_t / RAG_GETUP_TIME); sm = k * k * (3 - 2 * k)
        ground, surf = self.rag_ground(self.rg_x, self.rg_y0 + self.rag_drop)
        self.rg_strength = 1 - sm
        # every bone unwinds from where she was lying to straight
        self.rag_phi = [p * (1 - sm) for p in self.rag_phi0]
        self.rg_a = self.rag_a0 * (1 - sm)
        self.rg_y = self.rg_y0 + (ground - self.rag_drop - self.rg_y0) * sm
        self.rg_vx = self.rg_vy = self.rg_w = 0.0
        self.rg_top = ground
        self.rag_contact = True
        self.set_feet(self.rg_x - self.rag_pel_dx, self.rg_y + self.rag_drop)
        self.vx = self.vy = 0.0
        if k >= 1.0:
            self.rag_phi = None
            self.rag_end(surf)

    def rag_accel(self, dt, v0x, v0y, w0):
        """Smoothed body accelerations: these are what whip the limbs on impact."""
        inv = 1 / max(dt, 1e-4); G = self.G; k = 1 - math.exp(-dt * 25)
        self.rg_ax    += (clamp((self.rg_vx - v0x) * inv, -8 * G, 8 * G) - self.rg_ax) * k
        self.rg_ay    += (clamp((self.rg_vy - v0y) * inv, -8 * G, 8 * G) - self.rg_ay) * k
        self.rg_alpha += (clamp((self.rg_w - w0) * inv, -250, 250) - self.rg_alpha) * k

    def rag_drag_step(self, dt):
        """User is holding a ragdolled pet: she hangs (existing roll/pitch code),
        limbs still flop because rag_limb_post keeps running off rg_vx/rg_vy."""
        ch, rad, drop, a = self.rag_geom()
        v0x, v0y = self.rg_vx, self.rg_vy
        self.rg_vx = (self.px - self.last_px) / max(dt, 1e-3)
        self.rg_vy = (self.py - self.last_py) / max(dt, 1e-3)
        fx, fy = self.feet_pos(); self.rg_x, self.rg_y = fx, fy - drop
        self.rg_a = self.rg_w = 0.0; self.rag_contact = False; self.rag_top = None
        self.vx, self.vy = self.rg_vx, self.rg_vy
        self.rag_accel(dt, v0x, v0y, 0.0)
