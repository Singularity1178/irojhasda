"""Pet mixin: taking cover behind another student (Kneel_* clips)."""
from __future__ import annotations

import random

from .combat_config import (
    COVER_DRIFT, COVER_GAP, COVER_HOLD, COVER_MIN_BEHIND, COVER_SEEK, EXPOSURE_SHOTS,
    MOVE_MAX_TIME, SHOOT_LINES, SHOOT_STANCE_WEIGHT
)
from .combat_data import attack_sets, move_sets
from .mathutil import clamp


class PetCover:
    # ---------------- taking cover behind another student (Kneel_* clips) ----------------
    def shield_spot(self, sh, q):
        """x she kneels at: just behind the shield, on the side away from the opponent q."""
        sx = sh.feet_pos()[0]; tx = q.feet_pos()[0]
        away = 1 if sx >= tx else -1
        lo, hi = self.move_span()
        return clamp(sx + away * COVER_GAP * self.char_h(), lo, hi)

    def shield_ok(self, sh, q, others=()):
        """Can sh serve as her shield against q (her target) right now? She must be a standing student on
        the same floor / window top, on HER side of q (so reaching her never means running past the
        opponent), not hostile, not on the move, and there has to be room to kneel behind her."""
        if sh is None or sh is self or sh is q or sh in others: return False
        if not self.shoot_target_ok(sh) or not sh.grounded or sh.support != self.support: return False
        if sh.state == "flee" or sh.is_running(): return False
        if sh in self.threats(loose=True): return False
        fx, _ = self.feet_pos(); sx = sh.feet_pos()[0]; tx = q.feet_pos()[0]
        if (sx - tx) * (fx - tx) <= 0.0: return False             # the shield is on the opponent's far side
        away = 1 if sx >= tx else -1
        if (self.shield_spot(sh, q) - sx) * away < COVER_MIN_BEHIND * self.char_h(): return False   # wall in the way
        return True

    def pick_shield(self, q, others=()):
        """The nearest student who can be her shield against q, or None."""
        fx, _ = self.feet_pos(); reach = COVER_SEEK * self.char_h()
        best, best_d = None, reach
        for s_ in self.A.pets:
            if not self.shield_ok(s_, q, others): continue
            d = abs(s_.feet_pos()[0] - fx)
            if d <= best_d: best, best_d = s_, d
        return best

    def begin_cover(self, a):
        """A fight is starting (a is her fresh atk dict). If she has Kneel_Attack_* clips, rolls the
        panel's cover chance and finds a student to hide behind, she switches to the kneel stance and runs
        to her. True if she did (the run is already playing), False for an ordinary fight."""
        kc = attack_sets(self.model).get("kneel")
        if kc is None or "ing" not in kc: return False
        if random.random() >= float(self.cfg.get("shoot_cover_chance", 0.55)): return False
        sh = self.pick_shield(a["target"])
        if sh is None: return False
        a["stance"], a["clips"] = "kneel", kc
        self.start_cover_run(a, sh, announce=True)
        return True

    def start_cover_run(self, a, sh, announce=False):
        q = a["target"]; fx, _ = self.feet_pos(); goal = self.shield_spot(sh, q)
        side = 1 if q.feet_pos()[0] >= fx else -1
        a["cover"] = dict(shield=sh, settled=False, t=0.0, hold=random.uniform(*COVER_HOLD))
        sb = a.setdefault("shielded_by", [])
        if sh not in sb: sb.append(sh)                            # her bullets keep passing her old shields too (shoot_fire)
        a["mv"] = dict(kind="shield", goal=goal, side=side, t=MOVE_MAX_TIME["shield"])
        a["run_dir"] = 1 if goal > fx else -1
        a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
        self.atk_phase("run")
        if announce and self.bubble is None: self.say_combat(random.choice(SHOOT_LINES["shield"]), 1.8)

    def cover_settle(self, a):
        """She is behind the shield: Move_End_Kneel if the model has it, else straight to the aim clip."""
        cv = a["cover"]
        if not cv["settled"]: cv["settled"] = True; cv["t"] = 0.0   # (a follow-up run keeps its timer)
        if move_sets(self.model).get("kneel_stop") is not None: self.atk_phase("kneel_in")
        elif "start" in a["clips"]: self.atk_phase("start")
        else: self.combat_next(allow_move=False)

    def in_cover(self):
        """True while she is settled behind a student who is still a valid shield (read by aim_accuracy
        of whoever is shooting at her)."""
        a = self.atk
        if self.state != "shoot" or not a: return False
        cv = a.get("cover")
        if cv is None or not cv["settled"] or a["phase"] in ("run", "end"): return False
        return self.shield_ok(cv["shield"], a["target"], a.get("others", ()))

    def leave_cover(self, a):
        """Stop using the shield. She stands up: back to a standing attack stance if the model has one."""
        a["cover"] = None
        sets = attack_sets(self.model)
        names = [n for n in sets if n != "kneel"]
        if names:
            stance = random.choices(names, [SHOOT_STANCE_WEIGHT.get(n, 1.0) for n in names])[0]
            a["stance"], a["clips"] = stance, sets[stance]

    def cover_upkeep(self, a):
        """Between shots, while she has a shield. Returns True if she starts moving (follows the shield or
        goes to a new one). Gives the cover up when its time is up or the shield is no good any more."""
        cv = a["cover"]; q = a["target"]; ch = self.char_h()
        if cv["settled"] and cv["t"] > cv["hold"]:                # long enough here: stand up and fight
            self.leave_cover(a); return False
        sh = cv["shield"]
        if not self.shield_ok(sh, q, a.get("others", ())):        # the shield is down / hostile / gone
            new = self.pick_shield(q, a.get("others", ()))
            if new is not None:
                self.start_cover_run(a, new); return True
            a["cover"] = None; return False                       # nobody else: she fights from here
        fx, _ = self.feet_pos()
        if abs(self.shield_spot(sh, q) - fx) > COVER_DRIFT * ch:  # the shield wandered off: follow her
            self.start_cover_run(a, sh)
            a["cover"].update(settled=cv["settled"], t=cv["t"], hold=cv["hold"])   # same shield: keep the timer
            return True
        return False
