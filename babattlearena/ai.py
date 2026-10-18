"""Tactical AI for the Battle Arena.

Two layers:

Commander (one per team, every ~0.6 s)
    * weighs both teams' remaining strength (lives + HP) and picks a POSTURE:
      push (winning: advance cover to cover), hold, or fall_back (losing: give ground, regroup)
    * picks a FOCUS target: the most killable enemy someone on the team can see (low HP,
      out of cover, marked by a support, close to the team) - focus fire
    * sends FLANKERS (veteran: 1, elite: 2) - mobile attackers who work around the side of an
      enemy dug in behind cover
    * a tank's EX taunts: while her shield is up the enemy focus switches to her

Brain (one per student, thinks every 0.25-0.7 s depending on difficulty; reacts every frame)
    perception  line of sight through windows / props, a short memory of where enemies were,
                incoming grenades and how exposed she is from each threat
    utility     scores ENGAGE, TAKE COVER, ADVANCE, FLANK, RETREAT, REGROUP, HEAL and picks the
                best (with a little hysteresis so nobody dithers)
    cover       every prop and real window edge offers cover spots. Spots are scored for
                protection from the current threats, whether she can still shoot from it (peek),
                her preferred range (weapon / row), travel time and danger on the way, crowding
                (no two students in one spot - spread out against grenades), and the posture.
                Standing allies count as cover too: squishies hide behind tanks.
    behaviour   reload behind cover, retreat toward the healer when hurt, suppressed students keep
                their heads down, grenades are dodged, EX skills are used when they pay off
                (grenades into clusters or behind cover, shields when the team is under fire,
                mass heals when several allies are hurt ...)
"""
from __future__ import annotations

import math
import random

from .geometry import point_seg_dist, seg_box, seg_circle

DIFF = {
    #           think s, react s, aim spread x, flank n, cover weight, use posture
    "rookie":  dict(think=0.7, react=0.55, spread=1.45, flank=0, cover=0.6, posture=False, dodge=0.3),
    "veteran": dict(think=0.42, react=0.3, spread=1.0, flank=1, cover=1.0, posture=True, dodge=0.75),
    "elite":   dict(think=0.26, react=0.16, spread=0.78, flank=2, cover=1.25, posture=True, dodge=1.0),
}


class CoverSpot:
    __slots__ = ("x", "y", "box", "nx", "ny", "claim")

    def __init__(self, x, y, box, nx, ny):
        self.x, self.y, self.box, self.nx, self.ny = x, y, box, nx, ny
        self.claim = None


class CoverMap:
    def __init__(self, battle):
        self.B = battle
        self.spots = []

    def rebuild(self):
        B = self.B
        r = B.size * 0.17 + 4.0
        step = B.size * 0.5
        out = []
        for bx in B.boxes:
            if not bx.alive: continue
            w, h = bx.r - bx.l, bx.b - bx.t
            for side in range(4):
                if side in (0, 1):                     # top / bottom edges
                    n = max(1, int(w / step))
                    y = bx.t - r if side == 0 else bx.b + r
                    ny = -1.0 if side == 0 else 1.0
                    for k in range(n + 1):
                        x = bx.l + w * (k / n if n else 0.5)
                        out.append(CoverSpot(x, y, bx, 0.0, ny))
                else:
                    n = max(1, int(h / step))
                    x = bx.l - r if side == 2 else bx.r + r
                    nx = -1.0 if side == 2 else 1.0
                    for k in range(n + 1):
                        y = bx.t + h * (k / n if n else 0.5)
                        out.append(CoverSpot(x, y, bx, nx, 0.0))
        nav = B.nav
        self.spots = [s for s in out if nav.free(s.x, s.y)]


class Commander:
    def __init__(self, battle, team):
        self.B = battle
        self.team = team
        self.posture = "hold"
        self.focus = None
        self.flankers = set()
        self.t = random.uniform(0, 0.3)
        self.centroid = None
        self.enemy_centroid = None
        self.flank_t = 0.0

    def update(self, dt):
        self.t -= dt
        if self.t > 0: return
        self.t = 0.6
        B = self.B
        D = B.diff
        mine = [f for f in B.fighters if f.team == self.team and f.alive]
        theirs = [f for f in B.fighters if f.team != self.team and f.alive]
        my_p = sum(f.power() for f in B.fighters if f.team == self.team)
        en_p = sum(f.power() for f in B.fighters if f.team != self.team)
        ratio = my_p / max(0.1, en_p)
        if not D["posture"]:
            self.posture = "hold"
        elif ratio > 1.3 or (len(theirs) <= 1 and len(mine) >= 2):
            self.posture = "push"
        elif ratio < 0.72:
            self.posture = "fall_back"
        else:
            self.posture = "hold"
        if mine:
            self.centroid = (sum(f.x for f in mine) / len(mine), sum(f.y for f in mine) / len(mine))
        if theirs:
            self.enemy_centroid = (sum(f.x for f in theirs) / len(theirs), sum(f.y for f in theirs) / len(theirs))
        # focus fire
        best, bs = None, -1e9
        taunt = [e for e in theirs if B.t < e.shield_until and e.st.role == "Tank"]
        for e in (taunt or theirs):
            seen = any(f.brain is not None and e in f.brain.visible for f in mine)
            if not seen: continue
            ehp = e.hp / max(0.3, e.st.defense)
            s = -ehp / 1000.0
            if B.t < e.mark_until: s += 1.5
            if self.centroid:
                s -= math.hypot(e.x - self.centroid[0], e.y - self.centroid[1]) / (B.size * 6.0)
            if e.invulnerable(): s -= 5
            if taunt: s += 4
            if s > bs: best, bs = e, s
        self.focus = best
        # flankers
        self.flank_t -= 0.6
        if self.flank_t <= 0:
            self.flank_t = random.uniform(7, 11)
            self.flankers = set()
            n = D["flank"] if (len(mine) >= 3 and self.posture != "fall_back") else 0
            cands = [f for f in mine if f.st.role not in ("Tank", "Healer") and f.st.attacks
                     and f.st.weapon in ("Submachine Gun", "Assault Rifle", "Shotgun", "Handgun")]
            cands.sort(key=lambda f: -f.st.speed)
            for f in cands[:n]:
                self.flankers.add(f)


class Brain:
    def __init__(self, f):
        self.f = f
        self.B = f.B
        self.think_t = random.uniform(0.0, 0.4)
        self.react_t = 0.0
        self.visible = set()
        self.memory = {}                      # enemy -> (x, y, time)
        self.tactic = "advance"
        self.tactic_t = 0.0
        self.threats = []
        self.dodge_cd = 0.0
        self.hurt_t = -10.0
        self.cover_val = 0.0

    # ------------------------------------------------------------------ hooks
    def on_hurt(self, src):
        self.hurt_t = self.B.t
        if src is not None and src.team != self.f.team:
            self.memory[src] = (src.x, src.y, self.B.t)
        if self.tactic in ("engage", "advance") and self.f.hp_frac() < 0.5:
            self.think_t = min(self.think_t, self.B.diff["react"])

    def on_getup(self):
        self.think_t = 0.0
        self.tactic = "cover"
        if isinstance(self.f.cover, CoverSpot):
            self.f.cover.claim = None
        self.f.cover = None

    def safe_to_reload(self):
        return self.cover_val > 0.5 or not self.visible

    # ------------------------------------------------------------------ main
    def update(self, dt):
        f, B = self.f, self.B
        self.tactic_t += dt
        self.dodge_cd -= dt
        if self.dodge_cd <= 0 and self.dodge():
            return
        self.react_t -= dt
        if self.react_t <= 0:
            self.react_t = 0.12
            self.react()
        self.think_t -= dt
        if self.think_t <= 0:
            self.think_t = B.diff["think"] * random.uniform(0.8, 1.25)
            try:
                self.think()
            except Exception:
                import traceback; traceback.print_exc()

    # ------------------------------------------------------------------ perception
    def perceive(self):
        f, B = self.f, self.B
        self.visible = set()
        cx, cy = f.x, f.y
        sight = max(f.st.range * 2.2, 9.0) * f.size
        for e in B.fighters:
            if e.team == f.team or not e.alive: continue
            d = math.hypot(e.x - cx, e.y - cy)
            if d > sight: continue
            if B.los(cx, cy, e.x, e.y, f.radius * 1.5):
                self.visible.add(e)
                self.memory[e] = (e.x, e.y, B.t)
        for e in list(self.memory):
            if not e.alive or B.t - self.memory[e][2] > 5.0:
                self.memory.pop(e, None)
        th = []
        for e in self.visible:
            d = math.hypot(e.x - cx, e.y - cy)
            if d < e.st.range * f.size * 1.6:
                th.append((e.dps_threat() / (0.5 + d / (f.size * 4.0)), e))
        th.sort(key=lambda t: -t[0])
        self.threats = [e for _s, e in th[:3]]
        if self.threats:
            self.cover_val = sum(B.cover_value(e.x, e.y, f.x, f.y, f) for e in self.threats) / len(self.threats)
        else:
            self.cover_val = 1.0

    def pick_target(self):
        f, B = self.f, self.B
        C = B.commanders[f.team]
        rng = f.st.range * f.size * 1.12
        best, bs = None, -1e9
        for e in self.visible:
            d = math.hypot(e.x - f.x, e.y - f.y)
            if d > rng: continue
            s = -d / (f.size * 3.0)
            s += (1.0 - e.hp_frac()) * 1.5
            if e is C.focus: s += 1.6
            if B.t < e.mark_until: s += 0.6
            if e.invulnerable(): s -= 4.0
            s -= B.cover_value(f.x, f.y, e.x, e.y, e) * 1.4
            if e is f.target: s += 0.5                 # stick with her
            if e.st.role == "Healer": s += 0.4
            if s > bs: best, bs = e, s
        return best

    # ------------------------------------------------------------------ fast reactions
    def react(self):
        """Every ~0.1 s: keep shooting at something valid, stop shooting at nothing."""
        f, B = self.f, self.B
        t = f.target
        if f.st.healer and t is not None and t.team == f.team:
            if not t.alive or t.hp_frac() > 0.97 or not B.los(f.x, f.y, t.x, t.y, f.radius * 1.5):
                f.target = None; f.want_fire = False
            return
        if t is not None and (not t.alive or math.hypot(t.x - f.x, t.y - f.y) > f.st.range * f.size * 1.25
                              or not B.los(f.x, f.y, t.x, t.y, f.radius * 1.5)):
            f.target = None
            f.want_fire = False

    def dodge(self):
        """A grenade / shell landing on her: get out of the blast."""
        f, B = self.f, self.B
        for pr in B.projectiles:
            if pr["owner"].team == f.team or not pr.get("lob"): continue
            r = pr["radius"] * 1.1
            dx, dy = f.x - pr["tx"], f.y - pr["ty"]
            d = math.hypot(dx, dy)
            if d < r and random.random() < B.diff["dodge"]:
                if d < 1e-3: dx, dy, d = random.uniform(-1, 1), random.uniform(-1, 1), 1.0
                gx, gy = f.x + dx / d * (r - d + f.size * 0.6), f.y + dy / d * (r - d + f.size * 0.6)
                f.set_goal(gx, gy)
                f.want_fire = False
                self.set_tactic("evade")
                self.dodge_cd = 1.2
                self.think_t = 0.9
                return True
        self.dodge_cd = 0.2
        return False

    def set_tactic(self, name):
        if name != self.tactic:
            self.tactic = name
            self.tactic_t = 0.0
        self.f.tactic = name

    # ------------------------------------------------------------------ deliberation
    def think(self):
        f, B = self.f, self.B
        if B.phase != "fight": return
        self.perceive()
        C = B.commanders[f.team]
        D = B.diff
        hpf = f.hp_frac()
        target = self.pick_target()
        allies = [a for a in B.fighters if a.team == f.team and a.alive and a is not f]
        exposed = 1.0 - self.cover_val
        cpos = (f.cover.x, f.cover.y) if isinstance(f.cover, CoverSpot) else (f.cover[2], f.cover[3]) if isinstance(f.cover, tuple) else None
        near_cover = cpos is not None and math.hypot(cpos[0] - f.x, cpos[1] - f.y) < f.size * 0.35
        self.consider_ex(target, allies)
        # ---- healers first look after the team
        if f.st.healer:
            hurt = [a for a in allies + [f] if a.hp_frac() < 0.8]
            hurt.sort(key=lambda a: a.hp_frac())
            for a in hurt:
                d = math.hypot(a.x - f.x, a.y - f.y)
                if d <= f.st.range * f.size and (a is f or B.los(f.x, f.y, a.x, a.y, f.radius * 1.5)):
                    if a is f:
                        continue
                    f.target = a; f.want_fire = True
                    self.set_tactic("heal")
                    if exposed > 0.6 and self.threats:
                        self.move_to_cover("cover", target, max_dist=2.5)
                    else:
                        f.stop()
                    return
            if hurt and hurt[0] is not f:
                a = hurt[0]
                self.set_tactic("heal")
                self.goto_near(a.x, a.y, f.st.range * 0.6)
                return
        scores = {}
        has_shot = target is not None
        outnum = sum(1 for e in self.visible if math.hypot(e.x - f.x, e.y - f.y) < f.size * 5)
        outnum -= sum(1 for a in allies if math.hypot(a.x - f.x, a.y - f.y) < f.size * 4)
        scores["retreat"] = (max(0.0, 0.45 - hpf) * 3.2 + (f.suppression * 0.5 if hpf < 0.6 else 0.0)
                             + (0.25 * max(0, outnum) if hpf < 0.7 else 0.0)) * (1.0 if self.threats else 0.2)
        if C.posture == "fall_back": scores["retreat"] += 0.25
        scores["cover"] = ((0.5 + f.suppression * 0.6 + (1.0 - hpf) * 0.35) * D["cover"] * exposed
                           if self.threats else 0.0)
        if f.reload_t > 0 or f.ammo <= 0: scores["cover"] += 0.6 * exposed
        scores["engage"] = (0.75 + self.cover_val * 0.45 - f.suppression * 0.3) if has_shot else 0.0
        if f.st.support and has_shot: scores["engage"] += 0.1
        adv = 0.0 if has_shot else 0.62
        if C.posture == "push": adv += 0.3
        if C.posture == "fall_back": adv *= 0.45
        if hpf < 0.4: adv *= 0.4
        scores["advance"] = adv
        if f in C.flankers and target is not None and B.cover_value(f.x, f.y, target.x, target.y, target) > 0.5:
            scores["flank"] = 0.95
        elif f in C.flankers and not has_shot:
            scores["flank"] = 0.7
        if C.centroid is not None and allies:
            dc = math.hypot(C.centroid[0] - f.x, C.centroid[1] - f.y) / f.size
            if dc > 7.0 and C.posture != "push" and not has_shot:
                scores["regroup"] = 0.55 + (dc - 7.0) * 0.05
        if self.tactic in scores and self.tactic_t < 6.0:
            scores[self.tactic] += 0.15
        tactic = max(scores, key=scores.get)
        self.set_tactic(tactic)
        f.target = target
        f.want_fire = False
        if tactic == "engage":
            f.want_fire = True
            f.stance = "kneel" if self.cover_val > 0.55 else "stand"
            if exposed > 0.6 and not near_cover and D["cover"] >= 1.0:
                # duck behind something close by first, if it still lets her shoot
                if self.move_to_cover("cover", target, max_dist=1.6, need_fire=True):
                    f.want_fire = False
                    return
            f.stop()
        elif tactic == "cover":
            if not self.move_to_cover("cover", target, max_dist=5.5):
                f.want_fire = has_shot; f.stop()
            f.stance = "kneel"
        elif tactic == "retreat":
            if not self.move_to_cover("retreat", target, max_dist=9.0):
                away = self.away_point(4.0)
                f.set_goal(*away)
            f.stance = "kneel"
        elif tactic == "advance":
            goal_e = self.enemy_goal()
            if goal_e is None:
                f.stop(); return
            if not self.move_to_cover("advance", target, max_dist=7.0, toward=goal_e):
                self.goto_near(goal_e[0], goal_e[1], f.st.pref)
            f.stance = "stand"
        elif tactic == "flank":
            tgt = target or (min(self.memory, key=lambda e: math.hypot(e.x - f.x, e.y - f.y)) if self.memory else None)
            if tgt is None:
                f.stop(); return
            if not self.move_to_cover("flank", tgt, max_dist=9.0):
                self.goto_near(tgt.x, tgt.y, f.st.pref * 0.8, side=True)
            f.stance = "stand"
        elif tactic == "regroup":
            if not self.move_to_cover("regroup", target, max_dist=9.0, toward=C.centroid):
                self.goto_near(C.centroid[0], C.centroid[1], 2.0)
        if f.target is None and self.memory:
            e = min(self.memory, key=lambda q: math.hypot(q.x - f.x, q.y - f.y))
            mx, my, _t = self.memory[e]
            f.face_to = (mx, my)
        elif C.enemy_centroid is not None:
            f.face_to = C.enemy_centroid

    # ------------------------------------------------------------------ EX
    def consider_ex(self, target, allies):
        f, B = self.f, self.B
        if f.ex < 1.0 or not B.settings["ex_skills"] or f.want_ex is not None or f.ex_cast is not None:
            return
        kind = f.st.ex
        enemies = [e for e in (self.visible | set(self.memory)) if e.alive]
        if kind in ("grenade", "strike"):
            best, bs = None, 0.0
            reach = f.st.range * f.size * (1.1 if kind == "grenade" else 3.0)
            for e in enemies:
                ex, ey = (e.x, e.y) if e in self.visible else self.memory[e][:2]
                if math.hypot(ex - f.x, ey - f.y) > reach: continue
                n = sum(1 for o in enemies if math.hypot(o.x - ex, o.y - ey) < f.size * 1.4)
                s = n + B.cover_value(f.x, f.y, ex, ey, e) * 0.8 + (1.0 - e.hp_frac()) * 0.5
                if s > bs: best, bs = (ex, ey), s
            if best is not None and bs >= 1.3:
                f.want_ex = dict(kind=kind, aim=best)
        elif kind in ("pierce", "barrage"):
            if target is not None:
                f.want_ex = dict(kind=kind, aim=(target.x, target.y), target=target)
        elif kind == "charge":
            if target is not None and math.hypot(target.x - f.x, target.y - f.y) < f.size * 4.0:
                f.want_ex = dict(kind=kind, aim=(target.x, target.y), target=target)
        elif kind == "shield":
            under_fire = sum(1 for a in allies + [f] if B.t - a.last_hurt < 2.0)
            if (f.hp_frac() < 0.75 and self.threats) or under_fire >= 2:
                f.want_ex = dict(kind=kind)
        elif kind == "mass_heal":
            hurt = [a for a in allies + [f] if a.hp_frac() < 0.7]
            if len(hurt) >= 2 or any(a.hp_frac() < 0.35 for a in hurt):
                f.want_ex = dict(kind=kind)
        elif kind == "buff":
            fighting = sum(1 for a in allies if a.target is not None)
            if fighting >= 2 or (fighting >= 1 and len(allies) <= 2):
                f.want_ex = dict(kind=kind, aim=(target.x, target.y) if target else None, target=target)

    # ------------------------------------------------------------------ movement helpers
    def enemy_goal(self):
        f, B = self.f, self.B
        if self.memory:
            e = min(self.memory, key=lambda q: math.hypot(q.x - f.x, q.y - f.y))
            return self.memory[e][:2]
        C = B.commanders[f.team]
        return C.enemy_centroid

    def away_point(self, dist):
        f = self.f
        if not self.threats:
            return f.x, f.y
        ax = sum(e.x for e in self.threats) / len(self.threats)
        ay = sum(e.y for e in self.threats) / len(self.threats)
        dx, dy = f.x - ax, f.y - ay
        d = math.hypot(dx, dy) or 1.0
        return f.x + dx / d * dist * f.size, f.y + dy / d * dist * f.size

    def goto_near(self, x, y, keep, side=False):
        f = self.f
        dx, dy = f.x - x, f.y - y
        d = math.hypot(dx, dy) or 1.0
        if side:
            dx, dy = dx * 0.4 - dy * 0.9, dy * 0.4 + dx * 0.9
            d = math.hypot(dx, dy) or 1.0
        k = keep * f.size
        if math.hypot(f.x - x, f.y - y) < k * 1.05 and not side:
            f.stop(); return
        f.set_goal(x + dx / d * k, y + dy / d * k)

    def move_to_cover(self, mode, target, max_dist=6.0, need_fire=False, toward=None):
        """Score cover spots (props, windows, standing allies) and head for the best one."""
        f, B = self.f, self.B
        D = B.diff
        C = B.commanders[f.team]
        sz = f.size
        R = max_dist * sz
        threats = self.threats or ([target] if target is not None else [])
        if not threats and self.memory:
            threats = [e for e in self.memory if e.alive][:2]
        cands = []
        for sp in B.covers.spots:
            d = math.hypot(sp.x - f.x, sp.y - f.y)
            if d > R: continue
            if sp.claim is not None and sp.claim is not f and sp.claim.alive: continue
            cands.append((d, sp.x, sp.y, sp))
        # living shields: the spot right behind a standing ally (tanks first), away from the threats
        if threats:
            ax = sum(e.x for e in threats) / len(threats); ay = sum(e.y for e in threats) / len(threats)
            for a in B.fighters:
                if a.team != f.team or a is f or not a.alive: continue
                dx, dy = a.x - ax, a.y - ay
                dd = math.hypot(dx, dy) or 1.0
                px, py = a.x + dx / dd * (a.radius + f.radius + 4), a.y + dy / dd * (a.radius + f.radius + 4)
                d = math.hypot(px - f.x, py - f.y)
                if d <= R and B.nav.free(px, py):
                    cands.append((d, px, py, ("ally", a, px, py)))
        if not cands:
            return False
        cands.sort(key=lambda c: c[0])
        cands = cands[:24]
        if toward is None and C.enemy_centroid is not None:
            toward = C.enemy_centroid
        pref = f.st.pref * sz
        rng = f.st.range * sz
        best, bs = None, -1e9
        for d, x, y, sp in cands:
            prot = 0.0
            for e in threats:
                prot += B.cover_value(e.x, e.y, x, y, f, at_spot=sp)
            prot = prot / len(threats) if threats else 0.5
            if isinstance(sp, tuple) and sp[1].st.role == "Tank": prot += 0.1
            fire = 0.0
            if target is not None:
                dt_ = math.hypot(target.x - x, target.y - y)
                if dt_ <= rng * 1.05 and B.los(x, y, target.x, target.y, f.radius * 1.6):
                    fire = 1.0
                dist_pen = abs(dt_ - pref) / max(pref, 1.0)
            else:
                dist_pen = 0.0
            crowd = 0.0
            for a in B.fighters:
                if a is f or a.team != f.team or not a.alive: continue
                da = math.hypot(a.x - x, a.y - y)
                if da < sz * 1.1: crowd += 0.6 * (1.0 - da / (sz * 1.1))
            danger = 0.0
            mx, my = (f.x + x) / 2, (f.y + y) / 2
            for e in threats[:2]:
                if B.los(e.x, e.y, mx, my, 0.0): danger += 0.25
            travel = d / max(1.0, f.st.speed * sz)
            s = 2.1 * prot * D["cover"] - 0.28 * travel - danger - crowd
            if mode in ("cover", "engage"):
                s += 1.1 * fire - 0.5 * dist_pen
                if need_fire and fire < 1.0: continue
            elif mode == "advance":
                s += 0.7 * fire - 0.35 * dist_pen
                if toward is not None:
                    gain = math.hypot(f.x - toward[0], f.y - toward[1]) - math.hypot(x - toward[0], y - toward[1])
                    s += 1.2 * gain / sz / max(1.0, max_dist) * 2.0
                    if gain < sz * 0.6: s -= 0.8
            elif mode == "flank":
                if target is not None:
                    tc = B.cover_value(x, y, target.x, target.y, target)
                    s += 1.6 * (1.0 - tc) + 0.6 * fire - 0.4 * dist_pen
                    # an angle: away from the line her teammates already shoot along
                    if C.centroid is not None:
                        a1 = math.atan2(C.centroid[1] - target.y, C.centroid[0] - target.x)
                        a2 = math.atan2(y - target.y, x - target.x)
                        s += 0.6 * abs(math.sin((a2 - a1) / 2.0))
            elif mode == "retreat":
                dmin = min((math.hypot(x - e.x, y - e.y) for e in threats), default=0.0)
                s += 0.9 * dmin / sz / 4.0 + 0.6 * prot
                healer = next((a for a in B.fighters if a.team == f.team and a.alive and a.st.healer and a is not f), None)
                if healer is not None:
                    s -= 0.25 * math.hypot(x - healer.x, y - healer.y) / sz / 3.0
                s += 0.3 * fire
            elif mode == "regroup":
                if toward is not None:
                    s -= 0.5 * math.hypot(x - toward[0], y - toward[1]) / sz / 3.0
                s += 0.4 * fire
            if C.posture == "push" and toward is not None and mode != "retreat":
                s -= 0.08 * math.hypot(x - toward[0], y - toward[1]) / sz
            if C.posture == "fall_back" and toward is not None:
                s += 0.06 * math.hypot(x - toward[0], y - toward[1]) / sz
            if sp is f.cover: s += 0.25                 # do not hop between equal spots
            if s > bs: best, bs = (x, y, sp), s
        if best is None:
            return False
        x, y, sp = best
        if f.cover is not None and f.cover is not sp and not isinstance(f.cover, tuple):
            f.cover.claim = None
        f.cover = sp
        if isinstance(sp, CoverSpot):
            sp.claim = f
        if math.hypot(x - f.x, y - f.y) < sz * 0.12:
            f.stop()
        else:
            f.set_goal(x, y)
        return True
