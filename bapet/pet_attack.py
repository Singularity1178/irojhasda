"""Pet mixin: the shooting event (clips, ammo, tracers, hits)."""
from __future__ import annotations

import math
import random
import time

from PySide6 import QtWidgets

from .combat_config import (
    BURST_SPAN, CHASE_GIVE_UP, COMBAT_DISTANCE_SCALE, ENGAGE_BAND, ENGAGE_RANGE, EXPOSURE_SHOTS,
    FLINCH_TIME, MIN_ENGAGE, RELOAD_TIME, SHOOT_BODY_HALF_W, SHOOT_FIRE_FRAC, SHOOT_KNOCK_LIFT,
    SHOOT_KNOCK_SPEED, SHOOT_KNOCK_SPIN, SHOOT_LINES, SHOOT_MAX_TIME, SHOOT_MOCK_PERIOD,
    SHOOT_RUN_DODGE, SHOOT_STANCE_WEIGHT, STRESS_HIT, STRESS_NEAR
)
from . import vfx
from .combat_data import attack_sets, move_sets, weapon_for
from .mathutil import clamp


class PetAttack:
    # ---------------- shooting event ----------------
    def shoot_targets(self):
        """Other students she could shoot right now: visible, standing, not mid-drag."""
        # Unlimited range: every other visible student on this screen is fair game, however
        # far away and whatever window she is standing on (peers() would cap it at ~1.6 widths
        # and the same level).
        home = getattr(self.A, "home", None)
        out = []
        for q in self.A.pets:
            if q is self or not q.isVisible(): continue
            if not (q.grounded and not q.ragdoll and not q.dragging): continue
            if home is not None:
                qx, _qy = q.feet_pos()
                if qx + q.W * 0.5 < home.left() or qx - q.W * 0.5 > home.right(): continue
            out.append(q)
        out.sort(key=lambda q: abs(q.feet_pos()[0] - self.feet_pos()[0]))
        return out

    def try_shoot(self, force=False):
        """Start a shooting event against another student. True if it started.

        She picks one student and keeps shooting at that student until she ragdolls.
        force  the menu / panel path: skips the "must be idle" check and drops any chat.
        """
        if not self.isVisible() or not self.grounded or self.dragging or self.ragdoll: return False
        if not force and (self.state not in ("idle", "alert", "walk") or self.busy_chat()): return False
        if not attack_sets(self.model):                      # no shooting animation = no weapon
            if force and self.bubble is None: self.say("I don't have my weapon.", 2.0)
            return False
        studs = self.shoot_targets()
        if not studs:
            if force: self.say("Nobody to shoot at...", 1.6)
            return False
        target = random.choice(studs)
        sets = attack_sets(self.model)
        stance, clips = None, {}
        if sets:
            names = list(sets)
            stance = random.choices(names, [SHOOT_STANCE_WEIGHT.get(n, 1.0) for n in names])[0]
            clips = sets[stance]
        if force: self.chat_abort()
        self.meet_target = None
        self.atk = self.make_atk(target, stance, clips)
        self.enter("shoot")
        if self.begin_cover(self.atk): pass                   # kneel-behind-a-student tactic: she is running to it
        else: self.atk_phase("start" if "start" in clips else ("ing" if clips else "mock"))
        self.say_combat(random.choice(SHOOT_LINES["student"]), 2.0, force=True)
        return True

    def make_atk(self, target, stance, clips):
        """Fresh combat state for one fight. rng = (near, middle, far): the band of distances she is
        content to fight at, in px, drawn once per fight so each one plays a little differently."""
        ch = self.char_h(); gh = self.A.resolve_screen()
        rs = self.ch.range_scale          # her firing range (combat_index.json) vs the default
        mid = min(random.uniform(*ENGAGE_RANGE) * ch * rs, gh.width() * min(0.4 * COMBAT_DISTANCE_SCALE, 0.9))
        half = ENGAGE_BAND * ch * rs
        return dict(target=target, stance=stance, clips=clips, phase=None, fired=False, mock_t=0.0,
                    run_dir=1, mv=None, rng=(max(MIN_ENGAGE * ch * min(1.0, rs), mid - half), mid, mid + half),
                    planted=0, plant_limit=random.randint(*EXPOSURE_SHOTS),
                    reload_t=0.0, reload_anim=False, want_reload=False, reload_why="reload", run_tok=None, run_reload=False, burst_n=0, burst_i=0, burst_fr=[],
                    cover=None)

    def atk_phase(self, phase):
        """Switch to one phase of the attack: Start / Ing / End, a run, the stop after it, a reload,
        or the cafe-only 'mock' pose. (There is no Delay phase: Ing follows Ing directly so she can
        keep firing.)"""
        if phase == "ing" and self.ammo <= 0: phase = "reload"       # nothing left to fire
        a = self.atk; a["phase"] = phase; a["fired"] = False
        if phase == "run":
            clip, spd = self.run_clip()
            self.rig.play(clip, True, spd, 0.10); self.face_side(a["run_dir"]); return
        if phase == "stop":
            self.rig.play(self.stop_clip(), False, 1.0, 0.08); return
        if phase == "kneel_in":                                  # Move_End_Kneel: the run ends in a kneel
            self.rig.play(move_sets(self.model)["kneel_stop"], False, 1.0, 0.08); return
        if phase == "reload":
            rc = self.reload_clip()                              # Normal_Reload, else stand about in Formation_Idle
            a["reload_anim"] = rc is not None
            a["reload_t"] = (rc.duration + 1.0) if rc is not None else random.uniform(*RELOAD_TIME)
            a["reload_total"] = a["reload_t"]                       # for the BA reload gauge (pet_render)
            self.rig.play(rc if rc is not None else self.clips.get("alert"), rc is None, 1.0, 0.16)
            a["want_reload"] = False
            self.say_combat(random.choice(SHOOT_LINES[a["reload_why"]]), 1.6); a["reload_why"] = "reload"; return
        if phase == "mock":
            a["mock_t"] = 0.0
            self.rig.play(self.clips.get("alert"), True, 1.0, 0.16)
            return
        if phase == "ing": self.plan_burst()
        self.rig.play(a["clips"][phase], False, 1.0, 0.12 if phase == "start" else 0.06)

    def plan_burst(self):
        """One attack animation fires ammo_per_attack bullets (fewer if the magazine has fewer left), spread
        evenly across the clip. A single bullet leaves at SHOOT_FIRE_FRAC like it always did."""
        a = self.atk
        n = max(1, min(self.shots_per_attack, self.ammo))
        lo, hi = BURST_SPAN
        a["burst_n"], a["burst_i"] = n, 0
        a["burst_fr"] = [SHOOT_FIRE_FRAC] if n == 1 else [lo + (hi - lo) * i / (n - 1) for i in range(n)]

    def reload_clip(self):
        """The Normal_Reload clip, or None when the model has none."""
        return self.clips.get("reload")

    def begin_reload(self, force=False):
        """Play Normal_Reload, then refill the magazine (behave does the refill when the clip ends).
        True if the animation started. Without a reload clip she just refills at once and this is False.
        Not for a ragdolled / carried / airborne student, and not when nothing has been spent."""
        if self.ragdoll or self.dragging or not self.grounded or not self.isVisible(): return False
        if self.ammo >= self.ammo_max and not force: return False
        if self.reload_clip() is None:
            self.ammo = self.ammo_max; return False
        self.chat_abort(); self.meet_target = None; self.scan = None
        self.enter("shot", "reload")
        if self.bubble is None: self.say_combat(random.choice(SHOOT_LINES["rearm"]), 1.6)
        return True

    def combat_over(self):
        """Her fight (or her run from one) is finished: if she is on her feet and has spent rounds she
        plays Normal_Reload and reloads, otherwise she just goes back to idle."""
        if not self.begin_reload(): self.enter("idle")
        self.plan_next()

    # ---------------- Blue Archive VFX helpers ----------------
    def weapon_type(self):
        """Her weapon_type from combat_index.json (cached), or None."""
        w = getattr(self, "_weapon_type", False)
        if w is False:
            try: w = weapon_for(self.ch.path)
            except Exception: w = None
            self._weapon_type = w
        return w

    def weapon_look(self):
        """The merged look of her shots: weapon defaults + her profile bullet (Iroha's shell)."""
        return vfx.weapon_fx(self.weapon_type(), self.ch.bullet)

    def shielding_for(self, shooter):
        """True when she is the student someone else is kneeling behind, and this bullet was
        meant for that student: the BA 'BLOCK'."""
        sa = getattr(shooter, "atk", None) if shooter is not None else None
        tgt = sa.get("target") if sa else None
        if tgt is None or tgt is self: return False
        ta = getattr(tgt, "atk", None)
        cv = ta.get("cover") if ta else None
        return cv is not None and cv.get("shield") is self

    def shoot_target_ok(self, q):
        return q is not None and q.isVisible() and not q.ragdoll and not q.dragging

    def shoot_stand_down(self):
        """The target is down (or gone): wind the attack up with the End clip, else stop at once."""
        a = self.atk
        if a["phase"] != "mock" and "end" in a["clips"]: self.atk_phase("end")
        else: self.shoot_end()

    def shoot_step(self, dt):
        """Per-frame driver of the attack state machine (called from behave).

        Phases: start -> [decide] -> ing (one shot per clip) -> [decide] -> ing ... with a run (+ the
        stop clip) or a reload wherever the tactical decision (combat_decide) asks for one. She keeps
        fighting until her target ragdolls (or is dragged away / hidden), then plays End and stops.
        """
        a = self.atk; self.state_t += dt
        if a is None or self.state_t > SHOOT_MAX_TIME:
            self.shoot_end(); return
        ph, clips = a["phase"], a["clips"]
        if ph != "end" and not self.shoot_target_ok(a["target"]):
            if not self.shoot_retarget(force=True):              # target ragdolled / gone, nobody else to shoot
                self.shoot_stand_down(); return
        if ph != "end":                                          # a target that shrugs shots off: give up quickly
            gu = a["target"].ch.shot_give_up
            if gu is not None and id(a["target"]) in a.get("hit_on", ()):   # only once a bullet has really hit her
                if a.get("gu_ref") is not a["target"]:
                    a["gu_ref"] = a["target"]; a["gu_t"] = 0.0; a["gu_limit"] = random.uniform(*gu)
                a["gu_t"] += dt
                if a["gu_t"] > a["gu_limit"]:
                    foe = a["target"]
                    a.setdefault("gave_up", []).append(foe); a["gu_ref"] = None
                    lines = foe.ch.give_up_lines or SHOOT_LINES["give_up"]
                    self.say_combat(random.choice(lines), 2.0, force=True)
                    if not self.shoot_retarget(force=True, drop=foe):
                        self.shoot_stand_down(); return
                    ph = a["phase"]
        if ph != "end" and a["target"].state == "flee":          # target is running away: give up after a while
            a["chase_t"] = a.get("chase_t", 0.0) + dt
            if a["chase_t"] > a.setdefault("chase_limit", random.uniform(*CHASE_GIVE_UP)):
                if not self.shoot_retarget(force=True, drop=a["target"]):
                    self.shoot_stand_down(); return
        cv = a.get("cover")
        if cv is not None and cv["settled"]: cv["t"] += dt        # how long she has been behind this shield
        if ph == "mock":                                           # no attack clips: aim from Formation_Idle
            a["mock_t"] += dt
            if a["mock_t"] >= SHOOT_MOCK_PERIOD:
                a["mock_t"] = 0.0; self.shoot_fire()
        elif ph == "start":
            if self.rig.done: self.combat_next()
        elif ph == "ing":
            c = self.rig.clip
            if c is not None and c.duration > 0:                 # each bullet leaves at its own point in the clip
                while self.atk is not None and a["burst_i"] < a["burst_n"] and \
                        (self.rig.done or self.rig.t >= c.duration * a["burst_fr"][a["burst_i"]]):
                    a["burst_i"] += 1; self.shoot_fire()
            if self.rig.done and self.atk is not None:
                self.shoot_retarget()                            # shoot whoever matters most now
                self.combat_next()                               # then decide: shoot / move / reload / break
        elif ph == "run":
            mv = a["mv"]
            if mv is not None and mv["kind"] == "advance" and self.chase_reload_ok(a["target"]):
                a["want_reload"] = True; a["reload_why"] = "chase"; self.combat_halt()   # they are running: reload instead
            elif self.combat_move(dt): self.combat_halt()
        elif ph == "stop":
            if self.rig.done: self.combat_next(allow_move=False)
        elif ph == "kneel_in":                                     # settled behind the shield: now aim from the kneel
            if self.rig.done:
                if "start" in clips: self.atk_phase("start")
                else: self.combat_next(allow_move=False)
        elif ph == "reload":
            a["reload_t"] -= dt
            if (a["reload_anim"] and self.rig.done) or a["reload_t"] <= 0.0:
                self.ammo = self.ammo_max; self.combat_next()
        elif ph == "end":
            if self.rig.done: self.shoot_end()

    def shoot_end(self):
        self.atk = None
        self.combat_over()                                        # reload if she is on her feet and spent rounds

    def shoot_body_pt(self, q):
        """Chest of another pet in screen px."""
        return (q.px + q.W * 0.5, q.py + q.H * (1 - q.PADB) - q.char_h() * 0.55)

    def atk_aim_point(self):
        """Where she is aiming (screen px) while the shoot state runs, else None."""
        a = self.atk
        if self.state == "flee" and self.flee is not None and self.shoot_target_ok(self.flee["src"]):
            return self.shoot_body_pt(self.flee["src"])      # glance back at who is shooting
        if self.state != "shoot" or not a or a["target"] is None: return None
        return self.shoot_body_pt(a["target"])

    def muzzle_pt(self):
        """Screen px the bullet leaves from: her right hand, else her chest."""
        if self._muzzle_node is False:                  # looked up once
            node = None
            frag = ((self.ch.bullet or {}).get("muzzle_bone") or "muzzle").lower()
            for i, n in enumerate(self.model.names):
                if frag in n.lower(): node = i; break
            if node is None: node = self.rag_bone("r hand")
            self._muzzle_node = node
        if self._muzzle_node is not None:
            try:
                x, y = self.rag_project(self._muzzle_node)
                return self.px + x, self.py + y
            except Exception:
                pass
        return self.px + self.W * 0.5, self.py + self.H * (1 - self.PADB) - self.char_h() * 0.6

    def shot_blocker(self, x0, y0, x1, y1, skip):
        """The first student whose body the bullet path (x0,y0)->(x1,y1) crosses, and
        where it crosses. Each student in the way only takes the bullet with probability
        cfg shoot_intercept_chance, so now and then a bullet passes someone and carries on.
        `skip` = pets that can never be the blocker (the shooter, and the target)."""
        dx, dy = x1 - x0, y1 - y0
        found = []
        for q in self.A.pets:
            if q is self or q in skip or not self.shoot_target_ok(q): continue
            fx, fy = q.feet_pos(); ch = q.char_h(); hw = ch * SHOOT_BODY_HALF_W
            tmin, tmax = 0.0, 1.0                       # slab test: segment vs the body box
            for o, d, lo, hi in ((x0, dx, fx - hw, fx + hw), (y0, dy, fy - ch, fy)):
                if abs(d) < 1e-6:
                    if o < lo or o > hi: tmin, tmax = 1.0, 0.0; break
                else:
                    ta, tb = (lo - o) / d, (hi - o) / d
                    if ta > tb: ta, tb = tb, ta
                    tmin, tmax = max(tmin, ta), min(tmax, tb)
                    if tmin > tmax: break
            if tmin <= tmax: found.append((tmin, q))
        found.sort(key=lambda t: t[0])
        chance = float(self.cfg.get("shoot_intercept_chance", 0.55))
        for t, q in found:
            if random.random() < chance:
                t = min(1.0, t + 0.02)                  # a hair inside the body, so the spark lands on her
                return q, x0 + dx * t, y0 + dy * t
        return None, x1, y1

    def shoot_fire(self):
        """One shot: tracer from her hand at the target. It hits whichever student it reaches
        first, which is usually the target but sometimes someone standing in the way."""
        a = self.atk; aim = self.atk_aim_point()
        if a is None or aim is None: return
        fx = self.A.shotfx
        scr = self.screen().geometry() if self.screen() else QtWidgets.QApplication.primaryScreen().geometry()
        fx.ensure(scr)
        mx, my = self.muzzle_pt(); tx, ty = aim
        d = math.hypot(tx - mx, ty - my) or 1.0
        ux, uy = (tx - mx) / d, (ty - my) / d
        mx += ux * self.H * 0.06; my += uy * self.H * 0.06       # out to the end of the barrel
        fx.fancy = bool(self.cfg.get("ba_vfx", True))
        wpn = self.weapon_type(); look = self.weapon_look(); ang = math.atan2(uy, ux)
        fsz = float(look.get("flash", 1.0)) * clamp(math.sqrt(max(0.4, self.cfg["scale"])), 0.7, 1.4)
        fx.flash(mx, my, ang, fsz, look.get("color"))           # BA muzzle flash, along the barrel
        if look.get("casing") and not self.ch.bullet:            # brass flicks out of the ejection port, backwards
            fx.casing(mx - ux * self.H * 0.05, my - uy * self.H * 0.05, 1 if ux >= 0 else -1)
        sc = max(0.6, self.cfg["scale"])
        q = a["target"]
        cv = a.get("cover"); shield = cv["shield"] if cv is not None else None   # her own shield is never in her line of fire
        friends = ()                                             # ... nor is anyone she has hidden behind in this fight (she may have
        if shield is not None or a.get("shielded_by"):           #     stood up or moved on, but still be standing right behind her)
            hostile = self.threats(loose=True)                   # unless that student has turned on her
            friends = tuple(s_ for s_ in dict.fromkeys(([shield] if shield is not None else []) + a.get("shielded_by", []))
                            if s_ is not None and s_ not in hostile)
        bl = self.ch.bullet                                      # None = an ordinary bullet (see iroha.py)
        if bl and bl.get("muzzle_flash", 1.0) > 1.0:             # a cannon flash is bigger
            for _ in range(int(bl["muzzle_flash"])): fx.flash(mx, my, ang, fsz * 1.5, (255, 150, 60))
        hit = random.random() < self.aim_accuracy(q)
        self.ammo = max(0, self.ammo - 1); a["planted"] += 1  # one round gone; one more from this spot
        if hit:
            ex, ey = tx, ty                                      # aimed straight at her chest
            skip = (q,) + friends
        else:                                                    # flies wide, keeps going past her
            side = random.choice([-1, 1]) * random.uniform(0.7, 1.4) * q.W * 0.5
            ex = tx - uy * side + ux * 500 * sc; ey = ty + ux * side + uy * 500 * sc
            ex, ey = self.shot_to_edge(mx, my, ex, ey)           # unlimited range: it flies on to the screen edge
            skip = (q,) + friends                                # she was missed, someone behind her may not be
        other, bx, by = self.shot_blocker(mx, my, ex, ey, skip)
        if other is not None:                                    # somebody else got in the way
            bd = math.hypot(bx - mx, by - my) or 1.0
            bux, buy = (bx - mx) / bd, (by - my) / bd
            fx.fire(mx, my, bx, by, impact="spark", style=bl, weapon=wpn,
                    cb=lambda o=other, ux=bux, uy=buy: o.shot_landed(self, ux, uy, bl))
        elif hit:
            fx.fire(mx, my, ex, ey, impact="spark", style=bl, weapon=wpn,
                    cb=lambda q=q, ux=ux, uy=uy: q.shot_landed(self, ux, uy, bl))
        else:
            fx.fire(mx, my, ex, ey, impact="spark", style=bl, weapon=wpn, cb=lambda q=q, sh=self: q.shot_missed(sh))

    def shot_to_edge(self, x0, y0, x1, y1):
        """Extend the line (x0,y0)->(x1,y1) until it leaves this pet's screen."""
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-6: return x1, y1
        scr = self.screen().geometry() if self.screen() else QtWidgets.QApplication.primaryScreen().geometry()
        ts = []
        if abs(dx) > 1e-6: ts.append(((scr.right() if dx > 0 else scr.left()) - x0) / dx)
        if abs(dy) > 1e-6: ts.append(((scr.bottom() if dy > 0 else scr.top()) - y0) / dy)
        t = max(1.0, min(ts)) if ts else 1.0
        return x0 + dx * t, y0 + dy * t

    def shot_landed(self, shooter, ux, uy, bullet=None, look=None):
        """A bullet has reached her. (ux, uy) is the unit direction it was travelling in.
        `bullet` is the shooter's profile bullet (Iroha's tank shell), or None for an ordinary one.
        `look` is the merged weapon look the damage number is rolled from, when the shooter is
        not a character with a weapon of her own - the panel's test gun passes the weapon the
        player picked there, and None (with shooter None) falls back to the plain bullet look."""
        if not self.isVisible() or self.ragdoll or self.dragging: return
        if self.is_running() and random.random() < SHOOT_RUN_DODGE:
            self.shot_missed(shooter); return                    # dodged while running
        fighting = self.state in ("shoot", "flee")               # keeps fighting / running when hit
        sa = shooter.atk if shooter is not None else None        # the shooter's fight records that this bullet landed
        if sa is not None: sa.setdefault("hit_on", set()).add(id(self))
        self.emit("star", 6)
        # BA combat text: damage number, CRITICAL, or BLOCK when she is shielding someone
        look = look or (shooter.weapon_look() if shooter is not None and hasattr(shooter, "weapon_look")
                        else vfx.weapon_fx(None, bullet))
        shell = bool(bullet) and float(bullet.get("impact_size", 1.0)) >= 2.0
        blocked = self.shielding_for(shooter)
        dmg, crit = vfx.roll_damage(look, 0.0 if blocked else (0.35 if shell else 0.15), 0.35 if blocked else 1.0)
        self.combat_popup(dmg, "block" if blocked else ("crit" if crit else "normal"), 1.25 if shell else 1.0)
        self.add_stress(STRESS_HIT); self.flinch_until = time.monotonic() + FLINCH_TIME   # shaken, aim spoiled
        rag_p = float(self.cfg.get("shoot_ragdoll_chance", 0.5))
        if self.ch.shot_ragdoll_chance is not None and self.ride_on: rag_p = self.ch.shot_ragdoll_chance   # profile override, only while riding (Iroha: 0 in her tank)
        knock = 1.0
        if bullet and bullet.get("ragdoll_chance") is not None:  # a special bullet sets its own odds, panel slider ignored
            rag_p = clamp(float(bullet["ragdoll_chance"]), 0.0, 1.0); knock = float(bullet.get("knock", 1.0))
        if rag_p > 0.0 and random.random() < rag_p:
            s = max(0.6, self.cfg["scale"]); spd = random.uniform(*SHOOT_KNOCK_SPEED) * s * knock
            spin = math.copysign(random.uniform(*SHOOT_KNOCK_SPIN), ux if abs(ux) > 1e-3 else 1.0)
            imp = (ux * spd, uy * spd * 0.5 - random.uniform(*SHOOT_KNOCK_LIFT) * s, spin)
            self.rag_edge_slam = False
            self.atk = None; self.flee = None
            if self.vfx_on():                                    # knocked down: oversized BA hit burst on her
                try:
                    bx_, by_ = self.shoot_body_pt(self)
                    self.A.shotfx.burst(bx_, by_, 1.4 * knock, tuple(look.get("tint", (255, 236, 170))))
                except Exception: pass
                self.emit_shards(8, spread=self.W * 0.3)
            self.start_ragdoll(kick=False, impulse=imp)
            if self.ragdoll: self.say_combat(random.choice(SHOOT_LINES["knocked"]), 2.2, force=True)
            return
        if fighting:
            self.sq_v += 1.2
        else:
            self.chat_abort()
            if self.grounded:
                self.enter("shot", "react"); self.sq_v += 1.2
            self.emote(random.choice(("exclaim", "surprise", "angry")), 1.4)   # caught off guard
        self.say_combat(random.choice(self.ch.hit_lines or SHOOT_LINES["hit"]), 1.8)
        if shooter is not None and shooter is not self:
            self.provoked(shooter)                               # a stray bullet counts too: retaliate / run / nothing

    def shot_missed(self, shooter=None):
        """A bullet went past her. It still counts as being shot at: it rattles her a little, and she
        may shoot back or run just as if it had hit."""
        if not self.isVisible() or self.ragdoll: return
        who = shooter if (shooter is not None and shooter is not self) else None
        if who is not None: self.combat_popup("MISS", "miss")     # BA: an evaded / wide shot reads MISS
        if who is not None and self.state not in ("shoot", "flee") and random.random() < 0.5:
            self.emote("sweat", 1.3)
        if who is not None: self.add_stress(STRESS_NEAR)
        if not self.bubble and random.random() < 0.6:
            self.say_combat(random.choice(SHOOT_LINES["miss"]), 1.6)
        if who is not None: self.provoked(who)
