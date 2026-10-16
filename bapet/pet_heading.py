"""Pet mixin: 3D heading, hand rotation, look-around, heights."""
from __future__ import annotations

import math
import random
import time

from .config import DEPTH_WALK_PX, WALK_TURN, WALK_Z_DEAD
from .mathutil import clamp, wrap_pi
from .renderer import Renderer


class PetHeading:
    # ---------------- 3D heading ----------------
    # heading = the world yaw she is walking along. walk_dir (-1 / +1) is kept as the
    # screen side of that heading, so anything that just orders "walk left / right"
    # (wander, follow-cursor, a jump, the conversation code) still works: it turns her
    # to that side. See the WALK_* constants for the conventions.
    @property
    def walk_dir(self):
        return self._walk_dir

    @walk_dir.setter
    def walk_dir(self, v):
        v = 1 if v >= 0 else -1
        self._walk_dir = v
        h = getattr(self, "heading", None)
        # already heading to that side (maybe diagonally, in 3D): leave it alone
        if h is None or abs(math.sin(h)) < 0.2 or (math.sin(h) > 0) != (v > 0):
            self.heading = v * WALK_TURN

    def set_heading(self, h):
        self.heading = wrap_pi(h)
        s = math.sin(self.heading)
        if abs(s) > 1e-3: self._walk_dir = 1 if s > 0 else -1

    def face_side(self, d):
        """Turn her path to screen side d (+1 right / -1 left), keeping any depth part."""
        s = math.sin(self.heading)
        if abs(s) < 0.2: self.set_heading(d * WALK_TURN)
        elif (s > 0) != (d > 0): self.set_heading(-self.heading)       # mirror about the depth axis
        else: self._walk_dir = d

    def travel_vec(self, h):
        """Unit ground vector (x right, z toward the camera) she moves along for heading h.
        A three-quarter turn counts as a sideways walk, so the usual walking pose
        never drifts in depth."""
        sx, cz = math.sin(h), math.cos(h)
        zc = math.copysign(max(0.0, abs(cz) - WALK_Z_DEAD) / (1.0 - WALK_Z_DEAD), cz)
        n = math.hypot(sx, zc)
        return (sx / n, zc / n) if n > 1e-6 else (float(self._walk_dir), 0.0)

    def pick_walk_heading(self):
        """Where a wander walk starts. If she has been turned to face somewhere
        (rotation slider / drag), she walks that way, now and then turning round.
        Facing you or away has no heading of its own, so she picks a side as before -
        and sometimes a diagonal toward / away from you (depth_roam)."""
        cfg = self.cfg; yo = self.yaw_base()
        if abs(math.sin(yo)) >= 0.35:
            h = yo if random.random() > 0.2 else -yo
            self.set_heading(h); return
        d = random.choice([-1, 1])
        if False:           # depth walking removed: she only ever walks sideways
            a = math.radians(random.uniform(30, 70))                    # angle off the screen axis
            toward = 1 if self.depth < -0.4 else (-1 if self.depth > 0.4 else random.choice([-1, 1]))
            self.set_heading(math.atan2(d * math.cos(a), toward * math.sin(a)))
        else:
            self.set_heading(d * WALK_TURN)

    def depth_scale(self):
        return 1.0          # no walking toward / away from the screen, so no size change

    # ---------------- per-character rotation + look-around ----------------
    def yaw_base(self):
        """Rest facing (radians): this character's temporary hand rotation
        (Ctrl/Shift+wheel, rotate-drag). It eases back to 0 on its own."""
        return math.radians(self.yaw_user)

    def nudge_rotation(self, yaw=None, pitch=None, tilt=None):
        """Set this character's hand rotation (degrees). Only HER, never the others."""
        if yaw is not None: self.yaw_user = ((yaw + 180.0) % 360.0) - 180.0
        if pitch is not None: self.pitch_user = clamp(pitch, -90.0, 90.0)
        if tilt is not None: self.tilt_user = clamp(tilt, -40.0, 40.0)
        self.rot_touch = time.time()

    def rot_return(self, dt):
        """Ease a hand-rotated character back to facing the desktop on her own."""
        if not self.cfg.get("rotation_return", True) or self.rotating: return
        if not (self.yaw_user or self.pitch_user or self.tilt_user): return
        if time.time() - self.rot_touch < float(self.cfg.get("rotation_return_delay", 2.0)): return
        k = math.exp(-dt * 2.6)
        old = self.yaw_user
        self.yaw_user *= k; self.pitch_user *= k; self.tilt_user *= k
        if abs(self.yaw_user) < 0.3: self.yaw_user = 0.0
        if abs(self.pitch_user) < 0.3: self.pitch_user = 0.0
        if abs(self.tilt_user) < 0.3: self.tilt_user = 0.0
        # the walking-path logic must not read this return as a user turn
        self._yo_seen += math.radians(self.yaw_user - old)

    def look_around(self):
        """Turn to look left / right, then come back to facing the desktop."""
        if self.scan is not None or self.ragdoll or self.dragging or not self.grounded: return False
        if self.state not in ("idle", "alert"): return False
        a = math.radians(random.uniform(40, 75)); s = random.choice([-1, 1])
        seq = [(s * a, random.uniform(0.7, 1.5))]
        if random.random() < 0.7: seq.append((-s * a * random.uniform(0.6, 1.0), random.uniform(0.7, 1.5)))
        seq.append((0.0, 0.6))
        self.scan = dict(seq=seq, i=0, t=seq[0][1])
        self.plan_t = max(self.plan_t, sum(h for _t, h in seq) + 1.5)
        return True

    def scan_step(self, dt):
        sc = self.scan
        if sc is not None:
            if self.state not in ("idle", "alert") or not self.grounded or self.ragdoll or self.dragging:
                self.scan = sc = None                        # interrupted: ease back to front
            else:
                sc["t"] -= dt
                if sc["t"] <= 0:
                    sc["i"] += 1
                    if sc["i"] >= len(sc["seq"]): self.scan = sc = None
                    else: sc["t"] = sc["seq"][sc["i"]][1]
        tgt = sc["seq"][sc["i"]][0] if sc is not None else 0.0
        self.scan_yaw += (tgt - self.scan_yaw) * (1 - math.exp(-dt * 4.5))
        if sc is None and abs(self.scan_yaw) < 1e-3: self.scan_yaw = 0.0

    def char_h(self):
        """Her height in window px, including the depth size change.

        This is the framed height, not her body: for a character whose window
        had to make room for a vehicle (Iroha's tank) it is mostly tank. That
        is what the callers want - combat spacing and the speech bubble all
        measure from the floor to the top of what she is standing on. Use
        rag_h() for anything sized against her actual body.

        stand_h(), not H: while she is limp her window is RAG_WINDOW_SCALE
        times the one her model was measured in, and that extra frame is not
        her - she is drawn at the same size as ever, so every size read off H
        has to come from the standing window instead.
        """
        return self.stand_h() * Renderer.FRAC * self.depth_scale()

    def rag_h(self):
        """Her own body's height in window px - what the ragdoll is sized against.

        Same as char_h() for every ordinary model; less for one that filled
        its window with a vehicle, so her capsule radii stay limb-sized.
        """
        return self.stand_h() * Renderer.FRAC * self.ch.body_frac * self.depth_scale()

    def walk_depth(self, uz, dt):
        """Move toward / away from the camera. Reaching either end turns her round,
        like a screen edge does."""
        self.depth += uz * self.cfg["walk_speed"] * dt / DEPTH_WALK_PX
        if self.depth > 1.0 or self.depth < -1.0:
            self.depth = clamp(self.depth, -1.0, 1.0)
            self.set_heading(math.pi - self.heading)                    # flip the depth part
