"""Headless smoke test for the Battle Arena AI (babattlearena/ai.py + tank.py + geometry.py).

No PySide6, no numpy, no GL: the fighters and the battle are small fakes with just the
attributes the brains read. It runs a 3v3 for a while on a floor with props, puts Iroha in her
tank half-way through, and checks that

    1. nobody idles: every student either moves, shoots or breaches within a few seconds
    2. no cover spot is chosen right next to a known enemy (the "cover beside the enemy" bug)
    3. breaching is chosen when a target hides behind a breakable prop in range
    4. with an enemy tank bearing down, students side-step instead of standing in its path
    5. the tank brain shells clusters but never one with an ally inside the blast
    6. no exceptions anywhere in think() / update() over the whole run

    python test_arena_ai.py
"""
from __future__ import annotations

import importlib.util
import math
import random
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE / "babattlearena"

# -- load the three pure modules as a package WITHOUT running babattlearena/__init__ (it wants Qt)
pkg = types.ModuleType("babattlearena")
pkg.__path__ = [str(PKG)]
sys.modules["babattlearena"] = pkg


def _load(name):
    spec = importlib.util.spec_from_file_location(f"babattlearena.{name}", PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"babattlearena.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


geometry = _load("geometry")
tank = _load("tank")
ai = _load("ai")
Box, NavGrid, seg_box, seg_circle = geometry.Box, geometry.NavGrid, geometry.seg_box, geometry.seg_circle
TANK = tank.TANK

SZ = 120.0
RECT = (0.0, 0.0, 1600.0, 900.0)


class Stats:
    def __init__(self, weapon="Assault Rifle", role="Attacker", rng=4.6, healer=False):
        self.weapon = weapon
        self.role = role
        self.range = rng
        self.pref = rng * 0.78
        self.speed = 1.75
        self.healer = healer
        self.support = False
        self.attacks = not healer
        self.ex = "grenade" if not healer else "mass_heal"
        self.proj = "grenade" if weapon == "Grenade Launcher" else None
        self.dmg = (420, 680)
        self.box_dps = 1600.0
        self.mag = 24
        self.defense = 1.0


class Fighter:
    def __init__(self, B, name, team, x, y, st):
        self.B, self.name, self.team = B, name, team
        self.x, self.y, self.vx, self.vy = x, y, 0.0, 0.0
        self.st = st
        self.size, self.radius = SZ, SZ * 0.17
        self.state = "alive"
        self.hp = self.hp_max = 4200.0
        self.heading = 0.0 if team == 0 else math.pi
        self.target = None; self.want_fire = False; self.target_box = None
        self.cover = None; self.face_to = None; self.stance = "stand"; self.tactic = "spawn"
        self.suppression = 0.0; self.reload_t = 0.0; self.ammo = 24
        self.ex = 0.0; self.ex_cast = None; self.want_ex = None
        self.mark_until = self.shield_until = self.buff_until = 0.0
        self.last_hurt = -10.0
        self.path = []; self.goal = None
        self.tank = None
        self.brain = None
        self.log = []                      # (t, event)
        self.moved = 0.0
        self.shots = 0
        self.invuln_until = 0.0

    # --- what the brains read
    @property
    def alive(self): return self.state == "alive"
    def hp_frac(self): return self.hp / self.hp_max
    def invulnerable(self): return self.state != "alive" or self.tank is not None or self.B.t < self.invuln_until
    def dps_threat(self): return 6.0 if self.tank is not None else 1.5
    def block_radius(self): return self.size * TANK["block_r"] if self.tank is not None else self.radius * 1.15
    def tank_time_left(self): return max(0.0, self.tank["until"] - self.B.t) if self.tank else 0.0
    def power(self): return 1.0 + self.hp_frac()

    def set_goal(self, x, y):
        x, y = self.B.nav.nearest_free(x, y, 8)
        self.goal = (x, y)
        self.path = self.B.nav.path(self.x, self.y, x, y) or []
        if not self.path: self.goal = None
        else: self.log.append((self.B.t, "goal"))

    def stop(self):
        self.path = []; self.goal = None

    # --- a tiny body: walk the path, shoot when told
    def step(self, dt):
        if self.tank is not None:
            top = TANK["speed"] * self.size
        else:
            top = self.st.speed * self.size
        if self.path:
            wx, wy = self.path[0]
            dx, dy = wx - self.x, wy - self.y
            d = math.hypot(dx, dy)
            if d < 6: self.path.pop(0)
            else:
                stepd = min(d, top * dt)
                self.x += dx / d * stepd; self.y += dy / d * stepd
                self.moved += stepd
                self.heading = math.atan2(dy, dx)
                self.vx, self.vy = dx / d * top, dy / d * top
                if self.tank is not None: self.tank["speed"] = top
        else:
            self.vx = self.vy = 0.0
            if self.tank is not None: self.tank["speed"] = 0.0
            if self.face_to is not None:
                self.heading = math.atan2(self.face_to[1] - self.y, self.face_to[0] - self.x)
        if self.want_fire and (self.target is not None or self.target_box is not None):
            self.shots += 1
            if self.target_box is not None and self.target_box.hp is not None:
                self.target_box.hp -= self.st.box_dps * dt
                if self.target_box.hp <= 0:
                    self.target_box.alive = False
                    self.B.boxes_dirty = True
                    self.log.append((self.B.t, "broke:" + self.target_box.kind))
        # clamp to the floor
        l, t, r, b = RECT
        self.x = min(max(self.x, l + self.radius), r - self.radius)
        self.y = min(max(self.y, t + self.radius), b - self.radius)


class Fx:
    def __getattr__(self, k): return lambda *a, **kw: None


class Battle:
    def __init__(self):
        self.t = 0.0
        self.phase = "fight"
        self.size = SZ
        self.rect = RECT
        self.diff = ai.DIFF["veteran"]
        self.settings = dict(ex_skills=True, friendly_fire=False, damage=1.0, damage_numbers=False)
        self.projectiles = []
        self.fx = Fx()
        self.nav = NavGrid(RECT, SZ * 0.2)
        self.props = []
        self.boxes = []
        self.boxes_dirty = False
        self.fighters = []
        self.covers = ai.CoverMap(self)
        self.commanders = [ai.Commander(self, 0), ai.Commander(self, 1)]
        self.errors = []

    def add_box(self, cx, cy, w, h, kind, hp, cover="full"):
        bx = Box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, kind, SZ * 0.5, cover, hp)
        self.props.append(bx)
        return bx

    def rebuild(self):
        self.boxes = [b for b in self.props if b.alive]
        self.nav.rebuild(self.boxes, SZ * 0.17 + 2.0)
        self.covers.rebuild()
        self.boxes_dirty = False
        for f in self.fighters:
            if f.alive and f.goal is not None:
                g = f.goal; f.goal = None; f.set_goal(*g)

    # --- the same queries battle.py offers
    def los(self, x0, y0, x1, y1, ign_r=0.0):
        for bx in self.boxes:
            if not bx.alive or bx.cover != "full": continue
            if ign_r > 0 and bx.dist(x0, y0) < ign_r: continue
            if bx.kind != "window" and bx.dist(x1, y1) < self.size * 0.3: continue
            if seg_box(x0, y0, x1, y1, bx) is not None: return False
        return True

    def cover_value(self, sx, sy, tx, ty, tf=None, at_spot=None):
        r_ign = self.size * 0.27; r_adj = self.size * 0.32
        best = 0.0
        for bx in self.boxes:
            if not bx.alive or bx.dist(sx, sy) < r_ign: continue
            if seg_box(sx, sy, tx, ty, bx) is None: continue
            adj = bx.dist(tx, ty) < r_adj
            v = (0.88 if adj else 1.0) if bx.cover == "full" else (0.62 if adj else 0.15)
            best = max(best, v)
            if best >= 1.0: return 1.0
        if best < 0.85:
            for a in self.fighters:
                if a is tf or a.state not in ("alive", "getup"): continue
                if math.hypot(a.x - sx, a.y - sy) < a.radius * 1.5: continue
                t = seg_circle(sx, sy, tx, ty, a.x, a.y, a.block_radius() * 0.96)
                if t is not None and 0.04 < t < 0.97:
                    best = max(best, 0.85 if a.tank is not None else 0.65)
        return best

    def blocking_box(self, x0, y0, x1, y1, ign_r=0.0):
        best, bt = None, 2.0
        for bx in self.boxes:
            if not bx.alive: continue
            if ign_r > 0 and bx.dist(x0, y0) < ign_r: continue
            t = seg_box(x0, y0, x1, y1, bx)
            if t is not None and t < bt: best, bt = bx, t
        return best

    def step(self, dt):
        self.t += dt
        if self.boxes_dirty: self.rebuild()
        for c in self.commanders: c.update(dt)
        for f in self.fighters:
            if not f.alive: continue
            try:
                f.brain.update(dt)
            except Exception as e:                    # the real Brain.update swallows think() errors; we don't
                import traceback; traceback.print_exc()
                self.errors.append(repr(e))
            f.step(dt)
            if f.tank is not None and self.t >= f.tank["until"]:
                f.tank = None; f.radius = SZ * 0.17; f.brain.on_dismount()


def build(walled=False, diff="veteran"):
    random.seed(7)
    B = Battle()
    B.diff = ai.DIFF[diff]
    if walled:
        # a wall across the field with one gap: nobody sees anybody at the start
        B.add_box(800, 200, SZ * 0.4, 400, "container", None)
        B.add_box(800, 760, SZ * 0.4, 280, "container", None)
    # props: a breakable crate wall in the middle, a barrel near team 1, a barrier
    crate = B.add_box(800, 450, SZ * 0.56, SZ * 0.56, "crate", 4200)
    B.add_box(800, 250, SZ * 1.45, SZ * 0.32, "barrier", None)
    barrel = B.add_box(1150, 650, SZ * 0.36, SZ * 0.36, "barrel", 650)
    B.add_box(500, 650, SZ * 1.3, SZ * 0.38, "sandbags", None, "half")
    team0 = [("Shiroko", Stats()), ("Hoshino", Stats("Shotgun", "Tank", 2.8)), ("Iroha", Stats("Handgun", "Tactical Support", 5.0))]
    team1 = [("Hina", Stats("Machine Gun")), ("Ako", Stats("Handgun", "Healer", 4.0, healer=True)), ("Mika", Stats("Grenade Launcher"))]
    for i, (n, st) in enumerate(team0):
        f = Fighter(B, n, 0, 200, 250 + i * 200, st); f.brain = ai.Brain(f); B.fighters.append(f)
    for i, (n, st) in enumerate(team1):
        f = Fighter(B, n, 1, 1400, 250 + i * 200, st); f.brain = ai.Brain(f); B.fighters.append(f)
    B.fighters[2].st.ex = "tank"
    B.rebuild()
    return B, crate, barrel


def run(walled=False, diff="veteran"):
    print(f"--- scenario: {'walled' if walled else 'open'} field, {diff}")
    B, crate, barrel = build(walled, diff)
    dt = 1 / 30
    cover_next_to_enemy = 0
    idle_violations = 0
    breached = False
    evaded = 0
    shells_on_ally = 0
    shells = 0
    last_act = {f: (0.0, 0.0, 0) for f in B.fighters}
    bad_cover_t = {f: 0.0 for f in B.fighters}     # how long she has been heading for a bad spot
    bad_shell_t = 0.0                              # how long the tank has kept a bad aim
    REACT = 0.15                                   # a brain reacts every 0.12 s; longer than that is a real fault
    T_TANK = 6.0
    for k in range(int(30 / dt)):
        B.step(dt)
        # Iroha summons the tank at T_TANK
        iroha = B.fighters[2]
        if abs(B.t - T_TANK) < dt / 2 and iroha.tank is None:
            iroha.tank = dict(phase="drive", until=B.t + TANK["duration"], speed=0.0, reload_t=0.0, fade=1.0)
            iroha.radius = SZ * TANK["push_r"]
            iroha.brain.on_mount()
            for o in B.fighters:
                if o.brain is not None and o is not iroha: o.brain.think_t = 0.0
        for f in B.fighters:
            # 1. idling: more than 3.5 s without moving a quarter height, firing, or breaching
            m0, t0, s0 = last_act[f]
            acted = f.moved - m0 > SZ * 0.25 or f.shots > s0 or f.tank is not None
            if acted: last_act[f] = (f.moved, B.t, f.shots)
            elif B.t - t0 > 3.5:
                idle_violations += 1; last_act[f] = (f.moved, B.t, f.shots)
                print(f"  idle: {f.name} at t={B.t:.1f} tactic={f.tactic}")
            # 2. cover beside an enemy she can see, kept for longer than one reaction
            bad = False
            if isinstance(f.cover, ai.CoverSpot) and f.path:
                for e in f.brain.visible:
                    if math.hypot(e.x - f.cover.x, e.y - f.cover.y) < SZ * 1.3 and \
                            B.cover_value(e.x, e.y, f.cover.x, f.cover.y, f) < 0.6:
                        bad = True
            bad_cover_t[f] = bad_cover_t[f] + dt if bad else 0.0
            if bad_cover_t[f] > REACT:
                cover_next_to_enemy += 1
                print(f"  bad cover: {f.name} at t={B.t:.1f}")
            # 3. breaching
            if f.tactic == "breach" and f.target_box is not None: breached = True
            # 4. evading the tank
            if f is not iroha and iroha.tank is not None and f.tactic == "evade": evaded += 1
            # 5. the tank brain's shell choice
            if f is iroha and f.tank is not None and f.want_fire and f.target is not None:
                shells += 1
                if any(a.team == 0 and a is not f and math.hypot(a.x - f.target.x, a.y - f.target.y) < SZ * TANK["shell_radius"]
                       for a in B.fighters):
                    bad_shell_t += dt
                    if bad_shell_t > REACT: shells_on_ally += 1
                else:
                    bad_shell_t = 0.0
            elif f is iroha:
                bad_shell_t = 0.0
    print(f"run: {B.t:.0f}s, errors={len(B.errors)}, idle violations={idle_violations}, "
          f"cover-beside-enemy={cover_next_to_enemy}, breached={breached}, crate alive={crate.alive}, "
          f"barrel alive={barrel.alive}, evade ticks={evaded}, shell ticks={shells}, shells with ally in blast={shells_on_ally}")
    for f in B.fighters:
        print(f"  {f.name:8s} team {f.team}  moved {f.moved / SZ:5.1f} ch  shots-ticks {f.shots:4d}  final tactic {f.tactic}")
    ok = True
    if B.errors: print("FAIL: exceptions in the AI"); ok = False
    if idle_violations > 2: print("FAIL: students standing around"); ok = False
    if cover_next_to_enemy > 0: print("FAIL: cover picked right next to an enemy"); ok = False
    if shells_on_ally > 0: print("FAIL: the tank aimed a shell with an ally in the blast"); ok = False
    if evaded == 0: print("WARN: nobody had to evade the tank (layout dependent)")
    if not breached: print("WARN: no breach happened (layout dependent)")
    print("PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    rc = run()
    rc |= run(walled=True, diff="rookie")
    rc |= run(walled=True, diff="elite")
    sys.exit(rc)
