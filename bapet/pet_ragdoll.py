"""Pet mixin: going limp, shoving, getting up, edge slams."""
from __future__ import annotations

import math
import random
import time

from PySide6 import QtGui

from .deps import ragphys
from .mathutil import clamp
from .rag_diag import _ragdiag, _ragdiag_on
from .ragdoll_config import RAG_COM_PAD, RAG_EDGE_SLAM, RAG_EDGE_SLAM_MAX_V, RAG_REST_TIME


class PetRagdoll:
    def hideEvent(self, e):
        """A hidden pet must not stay in the physics world.

        Nothing ticks a hidden window, so a body left behind would sit there
        colliding with the other pets and the windows forever.
        """
        self.rag_clear()
        super().hideEvent(e)

    def rag_clear(self):
        """Snap out of the ragdoll without moving her. Call before any teleport.

        Always removes her skeleton from the physics world, whichever engine she
        was on: a body left behind in the space would keep colliding with the
        other pets and the windows after she has stood back up.
        """
        if self.rag_skel is not None:
            # Out of whichever world she is in: the pymunk one or the 3D one. Both
            # skeleton types remember their own world.
            wld = getattr(self.rag_skel, "world", None) or self.A.rag_world
            if wld is not None:
                wld.remove_skeleton(self.rag_skel)
        self.rag_skel = None
        self.rag3 = None                   # 3D engine: spawn matrix, post map, get-up blend
        self.ragdoll = False; self.rag_state = "fall"; self.rag_want_up = False
        self.rag_edge_slam = False
        self.rig.dangle_on = True; self.rig.rag_post = []
        # She is standing again, so the rig animates once more. The clip is NOT
        # chosen here: callers that want a specific one (rag_end's "react", a
        # recall's "idle") call enter() right after this, and Rig.play refuses to
        # switch while the rig is still marked limp. Order matters - clear the
        # flag first, then let them pick.
        self.rig.set_limp(False)
        for L in self.rag_bones: L["d"] = L["dd"] = 0.0
        self.rg_contact = False; self.rg_grav = 1.0; self.rag_strength = 1.0
        self.rg_ax = self.rg_ay = self.rg_alpha = 0.0; self.rg_top = None

    # ---------------- ragdoll: start / shove / get up ----------------
    def rag_freeze_pose(self):
        """Hold Formation_Pickup on its last frame: the limp base pose.

        Frozen rather than left playing, for two reasons - the centre of mass
        measured in rag_resolve() comes from exactly this frame, and a limp body
        should not keep animating underneath the physics that is flopping it.

        The rig is put into the full limp state (see Rig.set_limp), not just
        paused, so that nothing can restart the clip: nudging a ragdolled pet
        used to look like it played an animation.
        """
        c = self.clips.get("pickup") or self.clips.get("idle")
        if c is None:
            self.rig.set_limp(True); return
        if not self.rig.limp:
            self.rig.play(c, False, speed=0.0, fade=0.08)
        self.rig.set_limp(True)

    def rag_geom(self):
        """(character height px, body thickness, COM->feet, half-rod length).

        The rod is head end <-> foot end and `rad` thick, so its lowest point
        when upright is exactly COM + a + rad == the feet. Lying flat it rests
        on COM + rad, i.e. she lies ON the surface instead of through it, and
        `self.rag_com` (measured from her pelvis) puts her rotation pivot on it.
        """
        ch = self.rag_h()                           # her body height in window px
        rad = RAG_COM_PAD * self.H * self.ch.body_frac   # body "thickness"
        drop = self.rag_com * ch                     # COM -> feet
        return ch, rad, drop, max(1.0, drop - rad)   # ch, rad, drop, half-rod length a

    def start_ragdoll(self, kick=True, allow_drag=False, impulse=None):
        """Go limp: tumble, bounce, flop, lie there, then get back up.

        With cfg["ragdoll_engine"] == "pymunk" (and pymunk importable) she goes
        into the articulated world instead; the rod below is the fallback, and
        is also what "legacy" selects explicitly.

        `impulse` = (vx, vy, w) in px/s, px/s, rad/s replaces the random kick: she is
        sent off in that direction (used by the shooting event).

        `allow_drag` lets a caller that OWNS her window hand it over mid-drag
        (edge_slam). A normal drag must not do this - she is being carried, so
        going limp under the cursor looks like a glitch, not a knock-down - so
        the flag defaults to off and the drag is refused.
        """
        if self.ragdoll or not self.isVisible() or (self.dragging and not allow_drag): return
        _ragdiag_on() and _ragdiag().diag_start(self, f"start_ragdoll(kick={kick})")
        self.chat_abort(); self.meet_target = None
        # Any vehicle goes NOW, not over the ride fade: everything below measures
        # her against the window it finds (rag_geom, the pymunk skeleton), and
        # rag_freeze_pose picks its pose out of the clip set - both of which are
        # about to change underneath it anyway.
        self.set_ride(False, fade=False)
        engine = self.cfg.get("ragdoll_engine", "pymunk")
        if engine == "3d":
            # The fully 3D ragdoll (ragphys3d.py + pet_rag3d.py). If her rig cannot
            # do it, she falls back to pymunk, then to the rod.
            if self.start_ragdoll_3d(kick, impulse):
                return
        if engine in ("pymunk", "3d"):
            if self.start_ragdoll_pm(kick, impulse):
                return
            # no usable skeleton for this rig: say so once and fall back below
        _ragdiag_on() and _ragdiag().diag_pm_failed(self, "no usable ragdoll skeleton")
        ch, rad, drop, a = self.rag_geom(); s = max(0.6, self.cfg["scale"])
        fx, fy = self.feet_pos()
        self.rg_x, self.rg_y = fx, fy - drop
        self.rg_vx, self.rg_vy = (0.0, 0.0) if self.grounded else (self.vx, self.vy)
        self.rg_a = random.uniform(-0.15, 0.15)       # NEVER exactly 0: a rod balances on its end
        self.rg_w = 0.0
        if kick:
            # Same no-upward-launch rule as ragphys.RAGP_KICK_*: no vy, and only a
            # soft sideways nudge + spin. The random rg_a below is what topples her.
            self.rg_vx += random.choice([-1, 1]) * random.uniform(60, 200) * s
            self.rg_vy -= random.uniform(0, 0) * s
            self.rg_w = random.choice([-1, 1]) * random.uniform(1, 3)
        if impulse is not None:
            self.rg_vx += impulse[0]; self.rg_vy += impulse[1]; self.rg_w = impulse[2]
        self.rg_ax = self.rg_ay = self.rg_alpha = 0.0
        self.rg_prev_low = fy; self.rag_contact = False; self.rag_top = None
        self.rg_grav = 1.0; self.rag_strength = 1.0
        self.rag_state, self.rag_t, self.rag_rest = "fall", 0.0, 0.0
        self.rag_want_up = False
        self.rag_hit_t = 0.0
        for L in self.rag_bones: L["d"] = L["dd"] = 0.0
        self.ragdoll = True; self.rig.dangle_on = False
        self.grounded = False; self.support = None; self.dragging = False
        self.air_kind = "thrown"; self.bounces = 0
        self.roll = self.roll_v = 0.0; self.pitch_hold = self.pitch_hold_v = 0.0
        self.enter("fall"); self.rag_freeze_pose()
        self.say(self.line("launch"), 1.6)

    def start_ragdoll_pm(self, kick=True, impulse=None):
        """Hand her to the pymunk world. True if she went in, False to fall back.

        The skeleton is built from the frame on screen right now, so her current
        pose, scale and facing are what the physics starts from.
        """
        if _ragdiag_on():
            _ragdiag().diag_start(self, f"start_ragdoll_pm(kick={kick})")
        W = self.A.rag_world
        if W is None or self.rag_pm_failed:
            return False
        try:
            # The spec is measured off the frozen limp pose, so freeze first and
            # let last_M catch up: she must go limp from where she is standing.
            self.enter("fall"); self.rag_freeze_pose()
            self.rig.advance(0.0)
            self.render_frame(QtGui.QCursor.pos())
            spec = self.rag_spec()
        except Exception as e:
            print(f"[ragdoll] {self.name}: skeleton build failed ({e}); using the rod ragdoll")
            self.rag_pm_failed = True
            return False
        if spec is None:
            print(f"[ragdoll] {self.name}: rig has no usable ragdoll bones; using the rod ragdoll")
            self.rag_pm_failed = True
            return False
        s = max(0.6, self.cfg["scale"])
        vx, vy = (0.0, 0.0) if self.grounded else (self.vx, self.vy)
        w = 0.0
        if impulse is not None:
            vx += impulse[0]; vy += impulse[1]; w = impulse[2]
        elif kick:
            vx += random.choice([-1, 1]) * random.uniform(*ragphys.RAGP_KICK_VX) * s
            vy -= random.uniform(*ragphys.RAGP_KICK_VY) * s
            w = random.choice([-1, 1]) * random.uniform(*ragphys.RAGP_KICK_W)
        try:
            # BEFORE add_skeleton: ragphys reads RAGP_SELF_COLLIDE while it is
            # building the shapes and filling in the ancestor mute set, so setting
            # it afterwards would leave this ragdoll with the group filter and no
            # self-collision despite the cfg saying otherwise.
            ragphys.RAGP_SELF_COLLIDE = bool(self.cfg.get("ragdoll_self_collide", False))
            self.rag_skel = W.add_skeleton(self.rag_owner, spec, (vx, vy, w))
        except Exception as e:
            print(f"[ragdoll] {self.name}: could not build the physics skeleton ({e}); "
                  "using the rod ragdoll")
            self.rag_pm_failed = True
            return False
        if _ragdiag_on():
            self._rag_diag_t = 0
            self._rag_diag_peak = 0.0
        self.ragdoll = True; self.rig.dangle_on = False
        # --rag-diag: everything about the state she is going down in, then the
        # per-frame dump. diag_pm_ready also lists which overlapping pairs got
        # muted at spawn, which is the difference between "she popped" and
        # "she popped because her thighs were inside each other".
        if _ragdiag_on():
            _ragdiag().diag_pm_ready(self.rag_skel, self)
        # --rag-trace: per-frame physics for the first N frames, which is where
        # an instant launch is actually visible - a big anchor or relative-angle
        # error, or a pelvis nowhere near where the window says it is.
        if getattr(self.A, "rag_trace", 0):
            anch, rel = self.rag_skel.joint_error()
            print(f"[rag-trace] {self.name}: start pelvis="
                  f"({self.rag_skel.bodies[self.rag_skel.root].position[0]:.2f},"
                  f"{self.rag_skel.bodies[self.rag_skel.root].position[1]:.2f}) "
                  f"window={self.px:.0f},{self.py:.0f} drop={self.rag_skel.drop:.2f} "
                  f"bodies={len(self.rag_skel.bodies)} anchor_err={anch:.3f}px "
                  f"rel_err={rel:.4f}rad ignore={len(W._ignore)}")
            W.trace(int(self.A.rag_trace))
        self.grounded = False; self.support = None; self.dragging = False
        self.air_kind = "thrown"; self.bounces = 0
        self.roll = self.roll_v = 0.0; self.pitch_hold = self.pitch_hold_v = 0.0
        self.rag_state, self.rag_t, self.rag_rest = "fall", 0.0, 0.0
        self.rag_want_up = False; self.rag_hit_t = 0.0
        self.rg_ax = self.rg_ay = self.rg_alpha = 0.0
        self.rg_contact = False; self.rg_top = None
        self.rg_grav = 1.0; self.rag_strength = 1.0
        for L in self.rag_bones: L["d"] = L["dd"] = 0.0
        self.say(self.line("launch"), 1.6)
        return True

    # ---------------- ragdoll: knocked over by a screen edge ----------------
    def drag_velocity(self):
        """(vx, vy) of the cursor over the last moment of a drag, px/s.

        Same measurement mouseReleaseEvent uses for a throw, pulled out so the
        edge check and the throw cannot disagree about how fast she was moving.
        0, 0 when there is not enough history yet to divide by anything.
        """
        now = time.time()
        pts = [h for h in self.hist if now - h[0] < 0.14]
        if len(pts) < 2 or pts[-1][0] <= pts[0][0]: return 0.0, 0.0
        dt = pts[-1][0] - pts[0][0]
        return (pts[-1][1] - pts[0][1]) / dt, (pts[-1][2] - pts[0][2]) / dt

    def edge_slam(self, speed=0.0, drag=False):
        """A screen edge stopped her hard enough to knock her over. True if it did.

        Called from every clamp that keeps her inside the home screen - walking,
        flying, landing, and being carried by the cursor - with the speed she
        arrived with, BEFORE the clamp has rewritten it. So she goes down still
        carrying the slam, and the physics walls (or the rod's own bounce) stop
        her, rather than us bouncing her off first and ragdolling the rebound.

        `speed` is ignored when drag is set: a carried character has no velocity
        of her own, so the cursor's is the only thing that hit anything. That is
        also the one case start_ragdoll would refuse, since it is being carried,
        so it has to be let through - hence allow_drag.

        A True return means the window is the ragdoll's now: the caller must
        stop at once, without moving her window, or it would fight the physics
        for a frame.
        """
        if self.ragdoll or not self.isVisible() or not self.cfg.get("ragdoll_edge_slam", True):
            return False
        s = max(0.6, self.cfg["scale"])
        need = self.cfg.get("ragdoll_edge_slam_speed", RAG_EDGE_SLAM) * s
        if drag:
            # Capped, because Qt delivers move events in bunches and two of them
            # a millisecond apart can divide out to a speed no hand produces.
            # Computed into locals first and only committed once it passes:
            # procedural() reads self.vx / self.vy for the hair and skirt
            # springs, so a slow drag must not disturb them by being measured.
            cvx, cvy = self.drag_velocity()
            cap = RAG_EDGE_SLAM_MAX_V
            cvx = clamp(cvx, -cap, cap); cvy = clamp(cvy, -cap, cap)
            v = max(abs(cvx), abs(cvy))
            if v < need: return False
            self.vx, self.vy = cvx, cvy
            self.grounded = False; self.support = None; self.bounces = 0
            self.air_kind = "thrown"
        else:
            v = abs(speed)
            if v < need: return False
        self.rag_edge_slam = True
        # The velocity is left pointing INTO the wall: the ragdoll's own walls
        # stop her dead, which is what "you just hit a wall" should look like.
        self.start_ragdoll(kick=True, allow_drag=drag)
        return True

    # ---------------- Physics page settings ----------------
    def rag_rest_time(self):
        """Seconds lying still before an automatic get-up (Physics page slider)."""
        try:
            return max(0.3, float(self.cfg.get("phys_getup_delay", RAG_REST_TIME)))
        except (TypeError, ValueError):
            return RAG_REST_TIME

    def rag_tick_rest(self, dt, resting):
        """Advance or reset the lying-still timer.

        Being HELD by the cursor always resets it: a body hanging still from the
        cursor (or pressed against a window / edge while carried) reads as
        \"touching and slow\", which used to stand her up in mid-air after a few
        seconds of being held. rag_t is reset too so the edge-slam failsafe
        (RAG_EDGE_SLAM_MAX_T) cannot fire while she is carried either."""
        if self.dragging:
            self.rag_rest = 0.0
            if self.rag_state == "fall":
                self.rag_t = 0.0
            return
        self.rag_rest = self.rag_rest + dt if resting else 0.0

    def rag_may_get_up(self):
        """May she stand up on her own right now?

        Never while held, and never with zero / reversed gravity: lying on the
        ceiling (or floating) and then snapping to a standing pose on the floor
        looks broken. She gets up once gravity points down again (or on demand
        from the Ragdoll / get up action)."""
        if self.dragging:
            return False
        try:
            return float(self.cfg.get("phys_gravity", 1.0)) > 0.05
        except (TypeError, ValueError):
            return True

    def rag_shove(self, power=1.0):
        """Click / Launch on a ragdolled pet = push her away from the cursor."""
        if not self.ragdoll: return
        if self.rag3 is not None and self.rag_skel is None:
            return                          # 3D get-up already running: she is on her way up
        s = max(0.6, self.cfg["scale"]); cur = QtGui.QCursor.pos()
        self.rag_state = "fall"; self.rag_rest = 0.0; self.rag_strength = 1.0
        if self.rag_skel is not None:
            # Into the physics body nearest her, not into her centre of mass: the
            # shove should visibly spin her, not just translate her.
            self.rag_skel.shove((cur.x(), cur.y()), power)
            self.say(self.line("poke"), 1.4)
            return
        self.rg_vx += clamp((self.rg_x - cur.x()) * 6, -1400, 1400) * power
        self.rg_vy -= random.uniform(500, 900) * s * power
        self.rg_w += random.uniform(-8, 8) * power
        self.say(self.line("poke"), 1.4)

    def rag_getup(self):
        """Lie-down -> standing. "pm" / "rod" once a blend has actually started,
        or None if she is not ragdolled, is already getting up, or is still
        flying - in which case rag_want_up is set and she stands up on landing
        instead of being snapped straight down to the floor.

        The caller has to know which: rag_getup_step_pm replays a frozen physics
        pose and the rod blend does not, so picking the wrong one would blend her
        with numbers belonging to the other engine.
        """
        if not self.ragdoll or self.rag_state == "getup": return
        if _ragdiag_on() and not getattr(self.rag_skel, "is3d", False):
            _ragdiag().diag_end(self.rag_owner, self.rag_skel,
                                f"rag_getup after {getattr(self, 'rag_t', 0.0):.2f}s down, "
                                f"peak={getattr(self, '_rag_diag_peak', 0.0):.1f}px/s")
        # Asked to get up while she is still flying: remember it and stand her up
        # the moment she lands, rather than snapping her down to the floor.
        s = max(0.6, self.cfg["scale"])
        if not self.rag_contact and abs(self.rg_vy) > 260.0 * s:
            self.rag_want_up = True
            return
        self.rag_want_up = False
        self.rag_state, self.rag_t = "getup", 0.0
        if self.rag_skel is not None and getattr(self.rag_skel, "is3d", False):
            # 3D engine: freeze every bone's 3D rotation and her depth, leave the
            # world, and let rag3_getup_step blend her upright at z = 0.
            self.rag3_getup_begin()
            return "3d"
        if self.rag_skel is not None:
            # Record the pose she is lying in and take her OUT of the world. The
            # blend below plays it back into the rig; while it runs nothing can
            # hit her, which is acceptable for well under a second.
            pose = self.rag_skel.pose()
            self.rag_phi0 = list(pose["phi"])
            # the skeleton goes away, so keep what the post list needs
            self.rag_pm_bones = dict(bones=list(self.rag_skel.bones),
                                     parents=list(self.rag_skel.parents))
            self.rag_a0 = -pose["phi"][self.rag_skel.root]   # rg_a = +phi_pelvis
            self.rg_x0, self.rg_y0 = pose["x"], pose["y"]
            self.rag_drop = self.rag_skel.drop
            self.A.rag_world.remove_skeleton(self.rag_skel)
            self.rag_skel = None
            self.rag_phi = list(pose["phi"])          # the get-up blend reads this
            return "pm"
        self.rg_a0 = (self.rg_a + math.pi) % math.tau - math.pi    # shortest way back to upright
        self.rg_x0, self.rg_y0 = self.rg_x, self.rg_y
        self.rg_vx = self.rg_vy = self.rg_w = 0.0
        return "rod"

    def rag_end(self, surf):
        self.rag_clear()
        self.grounded = True; self.support = surf; self.vx = self.vy = 0.0; self.bounces = 0
        self.enter("shot", "react"); self.plan_next()
        self.say(self.line("land"), 1.8)
