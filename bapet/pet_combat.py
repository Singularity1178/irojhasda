"""Pet mixin: the combat AI (range, nerve, reloading, retaliating, fleeing)."""
from __future__ import annotations

import math
import random
import time

from .combat_config import (
    ACC_FAR, ACC_FAR_MULT, ACC_NEAR, COMBAT_RUN_SPEED, COVER_AIM_MULT, EXPOSURE_SHOTS,
    FLEE_MIN_GAIN, FLEE_REPLAN, FLEE_STAMINA, FLINCH_AIM, MOVE_MAX_TIME, MOVE_MIN,
    NO_FLEE_AFTER_TURN, PROVOKE_COOLDOWN, RELOAD_CHASE_FRAC, RELOAD_COVER_CHANCE,
    RELOAD_COVER_FRAC, RELOAD_TACTICAL_CHANCE, SHOOT_LINES, SHOOT_STANCE_WEIGHT, STRESS_TAU
)
from .combat_data import attack_sets, move_sets, plan_escape, react_odds
from .mathutil import clamp


class PetCombat:
    # ---------------- the combat AI: awareness ----------------
    def run_clip(self):
        """(clip, playback speed) for running: Move_Ing, else the walk clip sped up."""
        c = move_sets(self.model).get("run")
        return (c, 1.0) if c is not None else (self.clips.get("walk"), 1.7)

    def stop_clip(self):
        """Move_End_Normal, or None when the model has none (walk has no end clip)."""
        return move_sets(self.model).get("stop")

    def is_running(self):
        if self.state == "flee": return self.flee is not None and self.flee["phase"] == "run"
        return self.state == "shoot" and self.atk is not None and self.atk["phase"] == "run"

    def stress_now(self):
        """0..1 shakenness: it jumps when she is hit or shot at, and fades on its own."""
        return self.stress * math.exp(-(time.monotonic() - self.stress_t) / STRESS_TAU)

    def add_stress(self, amount):
        self.stress = clamp(self.stress_now() + amount, 0.0, 1.0); self.stress_t = time.monotonic()

    def threats(self, loose=False):
        """Students who are shooting at her right now. loose = also those who count her among the
        students they are fighting (they can turn their gun on her at any moment)."""
        out = []
        for q in self.A.pets:
            if q is self or not q.isVisible() or q.ragdoll or q.dragging: continue
            qa = q.atk
            if q.state != "shoot" or qa is None or qa.get("phase") == "end": continue
            if qa.get("target") is self or (loose and self in qa.get("others", ())): out.append(q)
        return out

    def under_fire(self):
        """True while another student is actively shooting at her."""
        return bool(self.threats())

    def move_span(self):
        """(lo, hi): the x range she can run along on her floor / window top."""
        A = self.A; gh = A.resolve_screen(); m = self.W * 0.18
        lo, hi = gh.left() + m, max(gh.left() + m, gh.right() - m)
        if self.support is not None:
            r = A.tracker.rect(self.support)
            if r: lo = max(lo, r[0] + 16); hi = max(lo, min(hi, r[2] - 16))
        return lo, hi

    def run_to(self, dt, gx):
        """One run step toward gx along her floor / window top. True once she is there. She stops at
        the ends of her floor and never turns back on her own - that is what used to send a runner
        straight back past the student shooting at her."""
        cfg = self.cfg
        fx, fy = self.feet_pos(); lo, hi = self.move_span()
        gx = clamp(gx, lo, hi)
        step = cfg["walk_speed"] * cfg["scale"] * COMBAT_RUN_SPEED * dt
        if abs(gx - fx) <= step:
            self.set_feet(gx, fy); return True
        d = 1 if gx > fx else -1
        self.face_side(d)
        self.set_feet(fx + d * step, fy)
        return False

    def escape_plan(self, extra=()):
        """(goal, gain, threats): where she would run to right now, or None if nobody is shooting at
        her. `extra` = shooters to count even if they are not (yet) aiming at her."""
        ths = self.threats(loose=True)
        for q in extra:
            if q is not self and q not in ths and q.isVisible() and not q.ragdoll: ths.append(q)
        if not ths: return None
        fx, _ = self.feet_pos(); lo, hi = self.move_span()
        goal, gain = plan_escape(fx, lo, hi, [q.feet_pos()[0] for q in ths], self.char_h())
        return goal, gain, ths

    def can_flee(self, plan):
        """Is there anywhere worth running to? (plan comes from escape_plan)"""
        return plan is not None and plan[1] >= FLEE_MIN_GAIN * self.char_h() \
            and time.monotonic() >= self.no_flee_until

    # ---------------- reacting to being shot at: retaliate / run away ----------------
    def provoked(self, shooter):
        """A bullet from another student just reached her (hit or near miss; shot_landed / shot_missed
        call this). If she has a weapon she shoots back, runs, or does nothing: the panel chances are
        the starting odds, bent by react_odds - outnumbered / shaken / nervy students run more, one with
        nowhere to run fights."""
        if self.state in ("shoot", "flee"): return
        if not (self.isVisible() and self.grounded and not self.ragdoll and not self.dragging): return
        now = time.monotonic()                                   # one roll per shooter every few seconds,
        seen = self.__dict__.setdefault("_prov_seen", {})        # so the first shot + the bullet that lands
        if now - seen.get(id(shooter), -99.0) < PROVOKE_COOLDOWN: return   # don't roll twice
        seen[id(shooter)] = now
        if self.state not in ("idle", "alert", "walk", "shot"): return
        if not attack_sets(self.model): return                   # no weapon: nothing
        ret = float(self.cfg.get("shoot_retaliate_chance", 0.8))
        fle = float(self.cfg.get("shoot_flee_chance", 0.15))
        plan = self.escape_plan(extra=(shooter,))
        fight, flee = react_odds(ret, fle, self.can_flee(plan), len(plan[2]) if plan else 1,
                                 self.stress_now(), self.nerve)
        r = random.random()
        if r < fight:
            if self.shoot_target_ok(shooter): self.start_retaliation(shooter)
        elif r < fight + flee:
            self.start_flee(shooter, plan)

    def add_threat(self, q):
        """q is now shooting back at her: while she is attacking she counts q as a target too."""
        a = self.atk
        if self.state != "shoot" or a is None or q is a["target"]: return
        oth = a.setdefault("others", [])
        if q not in oth: oth.append(q)

    def shoot_retarget(self, force=False, drop=None):
        """Choose who to shoot among everyone she is fighting: her current target, the students who
        shot back at her, and anyone else who is shooting at her. Someone shooting at her beats someone
        who is not, nearer beats farther, and a runner is the lowest priority; the current target
        keeps a bonus so she doesn't flip-flop. Returns False if there is nobody left to shoot."""
        a = self.atk
        if a is None: return False
        cur = a["target"]; hostile = self.threats()
        pool = []
        gave_up = a.get("gave_up", ())                           # targets she has written off (see shoot_step)
        for q in [cur] + a.get("others", []) + hostile:
            if q is not drop and q not in gave_up and q not in pool and self.shoot_target_ok(q): pool.append(q)
        if not pool: return False
        fx, _ = self.feet_pos(); span = max(1.0, self.A.resolve_screen().width())
        def score(q):
            return (2.0 if q in hostile else 0.0) + (1.0 - abs(q.feet_pos()[0] - fx) / span) \
                + (0.6 if q is cur else 0.0) - (0.8 if q.state == "flee" else 0.0)
        best = max(pool, key=score)
        if best is not cur and (cur not in pool or cur in gave_up or score(best) > score(cur) + 0.5):
            a["target"] = best; a["chase_t"] = 0.0; a.pop("chase_limit", None); a["planted"] = 0
            a["others"] = [q for q in pool if q is not best]
        return True

    def start_retaliation(self, shooter, why="retaliate"):
        sets = attack_sets(self.model)
        names = list(sets)
        stance = random.choices(names, [SHOOT_STANCE_WEIGHT.get(n, 1.0) for n in names])[0]
        clips = sets[stance]
        self.chat_abort(); self.meet_target = None; self.scan = None
        self.atk = self.make_atk(shooter, stance, clips)
        self.enter("shoot")
        if not self.begin_cover(self.atk): self.atk_phase("start" if "start" in clips else "ing")
        self.say_combat(random.choice(SHOOT_LINES[why]), 2.0, force=True)
        shooter.add_threat(self)                                  # she is a target of the shooter now

    # ---------------- the combat AI: fire and manoeuvre ----------------
    def combat_next(self, allow_move=True):
        """After Start / a shot / a run / a reload: out of ammo -> reload, else decide what to do."""
        a = self.atk
        if a is None: return
        if self.ammo <= 0 or a["want_reload"]: self.atk_phase("reload"); return
        act = self.combat_decide(allow_move)
        if act == "flee": return                                  # combat_decide already switched her over
        if act == "reload": self.atk_phase("reload"); return
        self.atk_phase("run" if act == "move" else "ing")

    def combat_decide(self, allow_move=True):
        """The tactical decision between shots. Returns "shoot", "move", "reload" or "flee".

        1. nerve    shaken enough (and with somewhere to run) she breaks and flees;
        2. lull     the opponent is running (fleeing, or repositioning in the fight) and her magazine is not
                    full -> reload now (always for a runner, sometimes for a tactical move);
        3. ammo     magazine low and she is being shot at, with somewhere to fall back to -> run out of the
                    line of fire, reload there, and come back (once she is out of range she advances again);
        4. range    too far from the target -> advance; opponent on top of her and shooting -> back off;
        5. cover    planted in the open for EXPOSURE_SHOTS while being shot at -> shift to a new spot;
        6. else     stand and shoot.
        Every goal is on her own side of the target, so she never runs through them."""
        a = self.atk; q = a["target"]; ch = self.char_h()
        fx, _ = self.feet_pos(); tx, _ = q.feet_pos()
        dist = abs(tx - fx); lo_r, mid, hi_r = a["rng"]
        side = 1 if tx >= fx else -1                              # which way the opponent is
        shot_at = self.under_fire()
        if shot_at and self.morale_broken():
            plan = self.escape_plan()
            if self.can_flee(plan):
                self.start_flee(plan[2][0], plan, "break"); return "flee"
        if self.chase_reload_ok(q):                               # they are running: nobody is shooting at her
            a["reload_why"] = "chase"; return "reload"
        cv = a.get("cover")
        if cv is not None:                                        # behind a shield: hold, follow, or leave
            if allow_move and self.cover_upkeep(a): return "move"
            if a.get("cover") is not None: return "shoot"         # still covered: no advance / retreat / relocate
            # cover is gone and she found no new one: fall through to the ordinary fight
        if allow_move and shot_at and self.cover_reload_ok():
            plan = self.escape_plan()
            if plan is not None and plan[1] >= FLEE_MIN_GAIN * ch:
                goal = plan[0]
                a["mv"] = dict(kind="cover", goal=goal, side=side, t=MOVE_MAX_TIME["cover"])
                a["run_dir"] = 1 if goal > fx else -1
                a["want_reload"] = True                           # reload as soon as the run is over
                a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
                self.say_combat(random.choice(SHOOT_LINES["cover"]), 1.8)
                return "move"
        if not allow_move: return "shoot"
        kind = goal = None
        if dist > hi_r:                                           # out of effective range: close in
            kind, goal = "advance", tx - side * mid
        elif shot_at and dist < lo_r:                             # on top of her and shooting: back off
            kind, goal = "retreat", tx - side * mid
        elif shot_at and a["planted"] >= a["plant_limit"]:        # standing in the open: relocate
            kind, goal = "shift", tx - side * random.uniform(lo_r, hi_r)
        if kind is not None:
            lo, hi = self.move_span(); goal = clamp(goal, lo, hi)
            gets_closer = abs(goal - tx) < dist
            if abs(goal - fx) < MOVE_MIN * ch or (kind == "advance" and not gets_closer) \
                    or (kind == "retreat" and gets_closer):
                kind = None                                       # pinned against a wall / already there
            else:
                a["mv"] = dict(kind=kind, goal=goal, side=side, t=MOVE_MAX_TIME[kind])
                a["run_dir"] = 1 if goal > fx else -1
                a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
                return "move"
        if a["planted"] >= a["plant_limit"]:                      # wanted to move but could not: stand firm
            a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
        return "shoot"

    def chase_reload_ok(self, q):
        """Her target is running and her magazine is not full: a good moment to reload instead of shooting at
        a moving target (which mostly misses) or chasing it.

        A student fleeing for her life always gives that moment. One who is only repositioning in a fight (a
        tactical run: advance / retreat / shift) gives it RELOAD_TACTICAL_CHANCE of the time; that roll is made
        once per run of theirs, not every frame, so a 'no' stays a no and she shoots or chases as usual."""
        if not (self.ammo < self.ammo_max and self.ammo <= self.ammo_max * RELOAD_CHASE_FRAC): return False
        if not q.is_running(): return False
        if q.state == "flee": return True
        a = self.atk
        if a is None or q.atk is None: return False
        tok = q.atk.get("mv") or q.atk                            # identifies THIS run of theirs
        if a["run_tok"] is not tok:
            a["run_tok"] = tok; a["run_reload"] = random.random() < RELOAD_TACTICAL_CHANCE
        return a["run_reload"]

    def cover_reload_ok(self):
        """Low on ammo (but not empty) while being shot at: worth falling back to reload? Rolled per decision."""
        return 0 < self.ammo <= self.ammo_max * RELOAD_COVER_FRAC and random.random() < RELOAD_COVER_CHANCE

    def combat_move(self, dt):
        """One frame of a tactical run. Returns True when it is over."""
        a = self.atk; mv = a["mv"]; q = a["target"]
        if mv is None: return True
        mv["t"] -= dt
        fx, _ = self.feet_pos(); tx, _ = q.feet_pos()
        mid = a["rng"][1]
        if abs(tx - fx) > 8.0 and (1 if tx >= fx else -1) != mv["side"]: return True   # would be passing them: stop
        if mv["kind"] == "shield":                                # follow the shield, wherever she wanders
            cv = a.get("cover")
            if cv is None or not self.shield_ok(cv["shield"], q, a.get("others", ())): return True
            mv["goal"] = self.shield_spot(cv["shield"], q)
        elif mv["kind"] not in ("shift", "cover"):                # follow an opponent who is moving
            lo, hi = self.move_span(); mv["goal"] = clamp(tx - mv["side"] * mid, lo, hi)
        arrived = self.run_to(dt, mv["goal"])
        return arrived or mv["t"] <= 0.0

    def combat_halt(self):
        """The run is over: the stop clip if she has one, then back to shooting."""
        a = self.atk; mv = a["mv"]; a["mv"] = None
        cv = a.get("cover")
        if mv is not None and mv["kind"] == "shield" and cv is not None:
            if self.shield_ok(cv["shield"], a["target"], a.get("others", ())):
                self.cover_settle(a); return                      # arrived behind the shield: drop into the kneel
            a["cover"] = None                                     # the shield went away on the way: fight from here
        if self.stop_clip() is not None: self.atk_phase("stop")
        else: self.combat_next(allow_move=False)

    def morale_broken(self):
        """Shaken enough to run? More attackers and less nerve break her sooner. Never if the panel's
        'runs away' chance is 0, and not for a while after she has turned to fight."""
        if float(self.cfg.get("shoot_flee_chance", 0.15)) <= 0.0: return False
        if time.monotonic() < self.no_flee_until: return False
        n = len(self.threats())
        return self.stress_now() > 0.65 + 0.30 * self.nerve - 0.12 * max(0, n - 1)

    def aim_accuracy(self, q):
        """Chance a shot at q is on target: the panel's hit chance, less with distance (down to
        ACC_FAR_MULT of it), less while she flinches from a hit, less the more shaken she is."""
        p = float(self.cfg.get("shoot_hit_chance", 0.75))
        if p <= 0.0: return 0.0
        d = abs(q.feet_pos()[0] - self.feet_pos()[0]) / max(1.0, self.char_h())
        rs = self.ch.range_scale          # longer firing range = accuracy holds out further
        p *= 1.0 - (1.0 - ACC_FAR_MULT) * clamp((d - ACC_NEAR * rs) / ((ACC_FAR - ACC_NEAR) * rs), 0.0, 1.0)
        if time.monotonic() < self.flinch_until: p *= FLINCH_AIM
        if q.in_cover(): p *= COVER_AIM_MULT                      # kneeling behind a student: much harder to hit
        p *= 1.0 - 0.3 * self.stress_now()
        return clamp(p, 0.02, 0.98)

    # ---------------- running away ----------------
    def start_flee(self, shooter, plan=None, line="flee"):
        """Run from everyone who is shooting at her, to the goal escape_plan picked. If there is no
        goal worth running to she turns and fights instead."""
        plan = plan or self.escape_plan(extra=(shooter,))
        if plan is None or plan[1] < FLEE_MIN_GAIN * self.char_h():
            if self.shoot_target_ok(shooter) and attack_sets(self.model): self.start_retaliation(shooter, "cornered")
            return
        goal, _gain, ths = plan
        self.chat_abort(); self.meet_target = None; self.scan = None
        fx, _ = self.feet_pos()
        src = min(ths, key=lambda q: abs(q.feet_pos()[0] - fx))
        self.enter("flee")
        self.flee = dict(src=src, goal=goal, t=0.0, phase="run", replan=FLEE_REPLAN,
                         stamina=random.uniform(*FLEE_STAMINA))
        clip, spd = self.run_clip()
        self.rig.play(clip, True, spd, 0.10); self.face_side(1 if goal >= fx else -1)
        self.say_combat(random.choice(SHOOT_LINES[line]), 1.8, force=True)

    def flee_step(self, dt):
        f = self.flee
        if f is None: self.combat_over(); return
        f["t"] += dt
        if f["phase"] != "run":                                   # the stop clip after a run
            if self.rig.done: self.combat_over()
            return
        plan = self.escape_plan()
        if plan is None:                                          # nobody is shooting at her any more
            self.flee_stop(safe=True); return
        goal, gain, ths = plan
        fx, _ = self.feet_pos()
        f["replan"] -= dt
        if f["replan"] <= 0.0:                                    # re-plan as the shooters move
            f["replan"] = FLEE_REPLAN; f["goal"] = goal
            f["src"] = min(ths, key=lambda q: abs(q.feet_pos()[0] - fx))
        if f["t"] > f["stamina"]:                                 # out of breath
            self.flee_turn(ths, "winded"); return
        if self.run_to(dt, f["goal"]):                            # she is there. Is there anywhere further?
            if gain < FLEE_MIN_GAIN * self.char_h():              # no: cornered / boxed in, so she fights
                self.flee_turn(ths, "cornered"); return
            f["replan"] = 0.0                                     # yes (they moved): pick the new goal now

    def flee_turn(self, ths, why):
        """She cannot run any further and they are still shooting: turn and fight the nearest one."""
        fx, _ = self.feet_pos()
        foe = min(ths, key=lambda q: abs(q.feet_pos()[0] - fx))
        self.no_flee_until = time.monotonic() + NO_FLEE_AFTER_TURN
        if attack_sets(self.model) and self.shoot_target_ok(foe): self.start_retaliation(foe, why)
        else: self.flee_stop(safe=False)

    def flee_stop(self, safe):
        f = self.flee
        if safe and random.random() < 0.5: self.say_combat(random.choice(SHOOT_LINES["safe"]), 1.8)
        stop = self.stop_clip()
        if stop is not None and f is not None: f["phase"] = "stop"; self.rig.play(stop, False, 1.0, 0.08)
        else: self.combat_over()
