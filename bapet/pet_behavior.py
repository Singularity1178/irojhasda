"""Pet mixin: idle / walk / jump decisions, flying and landing."""
from __future__ import annotations

import math
import random

from .config import WALK_TURN
from .mathutil import clamp


class PetBehavior:
    def try_jump(self):
        fx, fy = self.feet_pos(); s = self.cfg["scale"]; cand = []
        gh = self.A.resolve_screen()
        for (h, l, t, r, b) in self.A.tracker.wins:
            if r < gh.left() or l > gh.right(): continue          # window lives on another monitor
            hg = fy - t
            if h != self.support and hg > 30 and r - l > 140:
                tx = min(max(fx, l + 60), r - 60)
                tx = self.A.clamp_x(tx, self.W)
                if abs(tx - fx) < 520 * s: cand.append((t, h, tx))
        if not cand: return False
        t, h, tx = random.choice(cand); hg = fy - t
        vy = -math.sqrt(2 * self.G * (hg + 70 * s)); tt = (-vy + math.sqrt(vy * vy - 2 * self.G * hg)) / self.G
        self.vx, self.vy = (tx - fx) / tt, vy
        self.walk_dir = 1 if tx >= fx else -1
        self.grounded = False; self.support = None; self.air_kind = "jump"; self.bounces = 0
        self.enter("fall"); self.say(self.line("jump"), 1.6)
        return True

    def behave(self, dt, cur):
        A, cfg = self.A, self.cfg
        fx, fy = self.feet_pos()
        if self.support is not None:
            gh = A.resolve_screen()
            r = A.tracker.rect(self.support)
            if (r is None or not (r[0] + 4 <= fx <= r[2] - 4)
                    or not (gh.left() + 4 <= fx <= gh.right() - 4)):   # window closed / slid to another monitor
                self.support = None; self.grounded = False; self.vx = self.vy = 0.0
                self.air_kind = "jump"; self.bounces = 0; self.say(self.line("lost"), 1.8)
                self.enter("fall"); return
            fy = r[1]
        else:
            fy = A.floor_y(fx)
        self.set_feet(fx, fy)
        self.state_t += dt; st = self.state
        if st == "shoot":
            self.state_t -= dt          # shoot_step counts its own time
            self.shoot_step(dt); return
        if st == "flee":
            self.flee_step(dt); return
        if st == "shot":
            if self.rig.done:
                if self.shot_key == "reload": self.ammo = self.ammo_max      # the reload clip finished: full magazine
                self.enter("idle"); self.plan_next()
            return
        if cfg["follow_cursor"] and st in ("idle", "walk", "alert"):
            dx = cur.x() - fx
            if abs(dx) > 120 * cfg["scale"]:
                self.walk_dir = 1 if dx > 0 else -1
                if st != "walk": self.enter("walk", dur=999.0)
                st = "walk"
            elif st == "walk": self.enter("idle"); st = "idle"
        if st == "idle":
            self.plan_t -= dt
            if self.plan_t <= 0:
                # don't wander off mid-conversation
                if self.busy_chat(): self.plan_t = 1.5
                elif cfg["wander"] and not cfg["follow_cursor"]: self.plan_next_action()
                else: self.plan_t = 3.0
        elif st == "alert":
            if self.state_t > self.state_dur: self.enter("idle"); self.plan_next()
        elif st == "walk":
            self.walk(dt); self.pass_greet(dt)

    def plan_next_action(self):
        # the shooting event: a small chance every time she decides what to do next
        if self.cfg.get("shoot_events", True) and random.random() < float(self.cfg.get("shoot_chance", 0.10)) \
                and self.try_shoot(): return
        if self.cfg.get("look_around", True) and random.random() < float(self.cfg.get("look_around_chance", 0.12)) \
                and self.look_around(): return
        r = random.random(); fx, _ = self.feet_pos()
        if self.cfg["perch"] and self.A.tracker.enabled and r < 0.18 and self.try_jump(): return
        if r < 0.58:
            g = self.A.resolve_screen(); L, R = g.left(), g.right()
            if L + 300 < fx < R - 300: self.pick_walk_heading()          # she walks the way she faces
            else: self.walk_dir = 1 if fx < (L + R) / 2 else -1          # near an edge: back toward the middle
            self.enter("walk", dur=random.uniform(2.5, 6.0))
        elif r < 0.78: self.enter("alert", dur=random.uniform(3, 5.5))
        else: self.plan_t = random.uniform(2.5, 6.0)

    def walk(self, dt):
        A, cfg = self.A, self.cfg
        fx, fy = self.feet_pos()
        spd_px = cfg["walk_speed"] * cfg["scale"]
        # Which way she moves comes from the way she is heading. A window top is a
        # line, so there she only walks along it (side heading, no depth).
        if self.support is not None:
            d = 1 if math.sin(self.heading) >= 0 else -1
            if abs(math.sin(self.heading)) < 0.9: self.set_heading(d * WALK_TURN)
            ux, uz = float(d), 0.0
        else:
            ux, uz = self.travel_vec(self.heading)
            # sideways only: any toward / away part of the heading is dropped
            ux = math.copysign(1.0, ux) if abs(ux) >= 0.2 else float(self.walk_dir)
            uz = 0.0
        fx += ux * spd_px * dt
        gh = A.resolve_screen(); m = self.W * 0.18
        lo, hi = gh.left() + m, max(gh.left() + m, gh.right() - m)
        # Walking normally never reaches the threshold - it is meant for a
        # cfg["walk_speed"] turned up until ambling into a wall really does bowl
        # her over - but the check belongs here, where the edge is, not just in
        # the two places she happens to arrive at it fast today.
        spd = ux * spd_px
        if fx < lo:
            if self.edge_slam(spd): return
            fx = lo; self.face_side(1)
        elif fx > hi:
            if self.edge_slam(spd): return
            fx = hi; self.face_side(-1)
        if self.support is not None:
            r = A.tracker.rect(self.support)
            if r:
                at_edge = (fx < r[0] + 16 and self.walk_dir < 0) or (fx > r[2] - 16 and self.walk_dir > 0)
                if at_edge:
                    if not self.edge_decided: self.edge_decided = True; self.step_off = random.random() < 0.2
                    if not self.step_off: self.face_side(-self.walk_dir)
                else: self.edge_decided = False
        self.set_feet(fx, fy)
        if self.state_t > self.state_dur: self.enter("idle"); self.plan_next()

    # proximity greet: two characters brushing past each other say hello
    def pass_greet(self, dt):
        cfg = self.cfg
        if not cfg["chat"] or not cfg["chat_rate"] or self.dragging: return
        if self.state != "walk" or not self.grounded: return
        if self.busy_chat() or self.meet_target is not None: return
        if random.random() > dt * 0.12 * cfg["chat_rate"]: return
        for q in self.peers(max_dist=self.W * 0.8):
            if q.busy_chat() or q.dragging or not q.isVisible(): continue
            if abs(q.feet_pos()[1] - self.feet_pos()[1]) > self.H * 0.35: continue   # not on the same level
            self.greet(); return

    def air(self, dt):
        A, cfg = self.A, self.cfg
        fx, fy = self.feet_pos()
        self.vy += self.G * dt
        nfx, nfy = fx + self.vx * dt, fy + self.vy * dt
        gh = A.resolve_screen(); m = self.W * 0.15
        lo, hi = gh.left() + m, max(gh.left() + m, gh.right() - m)
        # The ceiling first: these three clamps are tested in that order so a
        # slam never sees a velocity another clamp has already rewritten.
        lim = gh.top() - self.H * 0.4
        if nfy < lim:
            if self.edge_slam(self.vy): return
            nfy = lim; self.vy = abs(self.vy) * 0.4
        if nfx < lo:
            if self.edge_slam(self.vx): return
            nfx = lo; self.vx = abs(self.vx) * 0.55
        elif nfx > hi:
            if self.edge_slam(self.vx): return
            nfx = hi; self.vx = -abs(self.vx) * 0.55
        landed = None
        if self.vy >= 0:
            for top, h in A.surfaces(nfx, cfg["perch"]):
                if (h is None and nfy >= top) or (fy <= top + 4 and nfy >= top): landed = (top, h); break
        if landed: self.land(nfx, landed)
        else: self.set_feet(nfx, nfy)

    def land(self, fx, surf):
        top, h = surf; impact = self.vy
        # The screen floor is its bottom edge, so it knocks her over like the
        # other three. Asked before set_feet, so the ragdoll starts from the
        # frame she was really in and carries the landing speed into it. Only
        # h is None - landing on a window title bar is a perch, not an edge,
        # and the physics world already has real window colliders for that.
        if h is None and self.edge_slam(impact): return
        self.set_feet(fx, top)
        if impact > 1000 and self.bounces < 1:
            self.bounces += 1; self.vy = -impact * 0.28; self.vx *= 0.6; self.sq = min(0.22, impact / 7000); return
        self.bounces = 0; self.grounded = True; self.support = h; self.vx = self.vy = 0.0
        self.sq = min(0.26, impact / 6500)
        s_ = max(0.6, self.cfg["scale"])
        if self.vfx_on():                                    # BA landing: dust rolling out + a floor ring
            self.emit_impact(self.W / 2, self.H * (1 - self.PADB), clamp(impact / (1400.0 * s_), 0.3, 1.8))
        else:
            self.emit("puff", 6, self.W / 2, self.H * (1 - self.PADB), spread=90)
        if self.air_kind == "thrown" and impact > 900:
            self.say(self.line("land")); self.enter("shot", "react")
            self.emote(random.choice(("sweat", "dots", "angry")), 1.6)
        else:
            self.enter("idle"); self.plan_t = 1.5
            if h is not None and random.random() < 0.5: self.say(self.line("perch"), 2.0)
