"""One student in the Battle Arena.

States
    alive    on her feet: the AI (ai.Brain) decides, Fighter.act() carries it out
    down     ragdolled - she lost a life. Lies in the physics world for down_time, then gets up
    getup    blending from however she landed back to standing (invulnerable)
    out      no lives left: her body stays on the floor as a ragdoll

Every ragdoll costs exactly one life (HP hitting zero is what ragdolls her). After getting up she
is invulnerable for a moment (blinking + a shield ring).

Iroha's tank (tank.py): her EX calls mount_tank(). While `self.tank` is set she is invulnerable,
drives with tank kinematics (tank_move), crushes whoever the hull runs over (tank_crush), fires
shells (tank_act -> Battle.fire_shell) and is drawn with the vehicle (render). dismount_tank()
puts her back on foot when the timer runs out.
"""
from __future__ import annotations

import math
import random

import numpy as np

import ragphys3d as R3
from bapet.combat_data import attack_sets, move_sets
from bapet.rig import Rig
from .physics import build_spec, posts_and_root, ragdoll_matrix
from .stats import CombatProfile
from .tank import TANK, crush_dist, find_clip as tank_clip, tank_fit
from .topdown import project, standing_matrix

_QI = (1.0, 0.0, 0.0, 0.0)


def wrap(a):
    return (a + math.pi) % math.tau - math.pi


class Fighter:
    def __init__(self, battle, entry, team, slot, x, y):
        self.B = battle
        self.entry = entry
        self.pet = entry.pet
        self.ch = entry.ch
        self.name = entry.name
        self.team = team
        self.slot = slot
        self.uid = 1000 + team * 100 + slot
        self.st = CombatProfile(self.ch)
        S = battle.settings
        self.size = float(S["size"])
        fit = self.ch.fit
        self.s = self.size / max(float(fit["H"]) * float(getattr(self.ch, "body_frac", 1.0) or 1.0), 1e-6)
        self.radius = self.size * 0.17
        self.base_radius = self.radius
        self.tank = None            # dict while she rides her tank (Iroha), see mount_tank
        self.target_box = None      # a breakable prop she is deliberately shooting (ai 'breach')
        self.rig = Rig(self.ch.model)
        self.binding = battle.binding(self.ch)
        self.x, self.y = float(x), float(y)
        self.vx = self.vy = 0.0
        self.heading = 0.0 if team == 0 else math.pi
        self.hp_max = self.st.hp * float(S["hp"])
        self.hp = self.hp_max
        self.lives = int(S["lives"])
        self.state = "alive"
        self.invuln_until = 0.0
        self.ammo = self.st.mag
        self.reload_t = 0.0
        self.fire_cd = 0.0
        self.burst_left = self.st.burst
        self.aim_t = 0.0
        self.heal_cd = 0.0
        self.atk_phase = None
        self.atk_t = 0.0
        self.anim = None
        self.path = []
        self.goal = None
        self.stuck_t = 0.0
        self.last_prog = (self.x, self.y)
        self.target = None          # who she shoots (or heals)
        self.want_fire = False
        self.face_to = None         # a point to keep facing while idle
        self.stance = "stand"
        self.tactic = "spawn"
        self.cover = None           # the CoverSpot she is using / heading to
        self.suppression = 0.0
        self.ex = random.uniform(0.0, 0.35)
        if self.st.ex == "tank": self.ex = min(self.ex, TANK["ex_start_max"])
        self.ex_cast = None         # (t_left, payload)
        self.want_ex = None
        self.buff_until = self.mark_until = self.shield_until = 0.0
        self.down_t = 0.0
        self.rag = None
        self.flash_t = 0.0
        self.last_hit_by = None
        self.last_hurt = -10.0
        self.rec = dict(dmg=0.0, kills=0, downs=0, heal=0.0, ex=0, shots=0, hits=0)
        self.img = None
        self.img_rect = None
        self.img_sleep = False
        self.last_W = None
        self.last_M = None
        self.spawn_t = 0.0
        self.visible_t = 0.0        # appears with the summon beam
        self.brain = None
        self.play("alert", True, fade=0.0)

    # ------------------------------------------------------------------ queries
    @property
    def alive(self):
        return self.state == "alive"

    @property
    def in_play(self):
        return self.state != "out"

    def hp_frac(self):
        return max(0.0, self.hp) / max(1.0, self.hp_max)

    def invulnerable(self):
        return self.state != "alive" or self.B.t < self.invuln_until or self.tank is not None

    @property
    def riding(self):
        """In her tank and actually driving (not still deploying / stowing)."""
        return self.tank is not None and self.tank["phase"] == "drive"

    def block_radius(self):
        """How wide a body she is to bullets aimed past her (the tank is a wall)."""
        return self.size * TANK["block_r"] if self.tank is not None else self.radius * 1.15

    def power(self):
        """Rough fighting value left in her (for the team commanders and time-outs)."""
        if self.state == "out": return 0.0
        return (self.lives - (0 if self.state == "alive" else 1)) + (self.hp_frac() if self.state == "alive" else 0.5)

    def chest(self):
        return self.x, self.y, self.size * 0.62

    def muzzle(self):
        c, s = math.cos(self.heading), math.sin(self.heading)
        return self.x + c * self.size * 0.3 - s * self.size * 0.06, self.y + s * self.size * 0.3 + c * self.size * 0.06, \
            self.size * 0.55

    def dps_threat(self):
        st = self.st
        if self.tank is not None: return 6.0
        if not st.attacks: return 0.3
        return (sum(st.dmg) / 2.0) * st.pellets * st.burst / max(0.2, st.rof * st.burst + st.gap) / 1000.0

    # ------------------------------------------------------------------ animation
    def clip(self, key):
        c = self.ch.clips
        if self.tank is not None:
            tk = self.tank_clip(key)
            if tk is not None: return tk
        if key == "run":
            rc = move_sets(self.ch.model).get("run")
            return (rc, 1.0) if rc is not None else (c.get("walk"), 1.7)
        if key == "walk": return c.get("walk"), 1.0
        if key == "reload":
            r = c.get("reload")
            return (r, 1.0) if r is not None else (c.get("alert"), 1.0)
        if key == "ex": return c.get("cutin") or c.get("tactical") or c.get("react"), 1.0
        if key == "victory": return c.get("react") or c.get("alert"), 1.0
        if key == "alert": return c.get("alert") or c.get("idle"), 1.0
        if key.startswith("atk_"):
            sets = attack_sets(self.ch.model)
            if not sets: return c.get("alert"), 1.0
            want = "kneel" if self.stance == "kneel" else "stand"
            s = sets.get(want) or sets.get("normal") or sets.get("stand") or next(iter(sets.values()))
            ph = key[4:]
            return s.get(ph) or s.get("ing"), 1.0
        return c.get(key) or c.get("alert"), 1.0

    def tank_clip(self, key):
        """(clip, speed) while riding, or None to fall through to the on-foot lookup."""
        m = {"run": "move", "walk": "move", "alert": "idle", "idle": "idle", "reload": "reload",
             "tank_appear": "appear", "tank_end": "end", "atk_start": "atk_start", "atk_ing": "atk_ing",
             "atk_end": "atk_end", "victory": "idle", "ex": "idle"}
        k = m.get(key)
        if k is None: return None
        c = tank_clip(self.ch, k)
        if c is None and k.startswith("atk_"):
            c = tank_clip(self.ch, "idle")
        return (c, 1.0) if c is not None else None

    def play(self, key, loop, speed=1.0, fade=0.15, restart=False):
        if self.anim == key and not restart:
            self.rig.speed = speed * self.clip(key)[1]
            return
        c, sp = self.clip(key)
        if c is None: return
        self.anim = key
        self.rig.play(c, loop, speed * sp, fade=fade, restart=True)

    # ------------------------------------------------------------------ per tick
    def update(self, dt):
        B = self.B
        self.suppression = max(0.0, self.suppression - dt * 0.35)
        self.flash_t = max(0.0, self.flash_t - dt)
        if self.state == "alive":
            gain = dt / self.st.ex_cost * (1.0 + 0.5 * (self.suppression > 0.3))
            if self.tank is not None: gain = 0.0            # the gauge waits while she rides
            if B.settings["ex_skills"]: self.ex = min(1.0, self.ex + gain)
            if self.tank is not None: self.tank_update(dt)
            if self.brain is not None: self.brain.update(dt)
            self.act(dt)
        elif self.state == "down" or self.state == "out":
            self.down_t += dt
            self.rag_step()
            if self.state == "down" and self.down_t >= B.settings["down_time"]:
                sk = self.rag and self.rag.get("sk")
                resting = sk is None or sk.sleeping or sk.speed() < 60 or self.down_t > B.settings["down_time"] + 2.5
                if resting: self.begin_getup()
        elif self.state == "getup":
            self.getup_step(dt)

    # ------------------------------------------------------------------ acting
    def act(self, dt):
        B = self.B
        if self.tank is not None:
            self.tank_act(dt)
            return
        if self.ex_cast is not None:
            t_left, payload = self.ex_cast
            t_left -= dt
            self.vx *= 0.8; self.vy *= 0.8
            if payload.get("aim"): self.turn_to(payload["aim"][0], payload["aim"][1], dt, 10)
            if t_left <= 0:
                self.ex_cast = None
                B.do_ex(self, payload)
                self.play("alert", True)
            else:
                self.ex_cast = (t_left, payload)
            return
        if self.want_ex is not None and self.ex >= 1.0:
            payload = self.want_ex
            self.want_ex = None
            self.ex = 0.0
            self.rec["ex"] += 1
            self.path = []; self.goal = None
            self.atk_phase = None
            self.play("ex", False, fade=0.1, restart=True)
            self.ex_cast = (0.75, payload)
            B.announce_ex(self)
            return
        moving = self.move(dt)
        if moving:
            self.atk_phase = None
            return
        if self.reload_t > 0:
            self.reload_t -= dt
            self.play("reload", False, speed=max(0.5, self.clip("reload")[0].duration / max(0.4, self.st.reload))
                      if self.clip("reload")[0] is not None else 1.0)
            if self.target is not None: self.turn_to(self.target.x, self.target.y, dt, 3)
            if self.reload_t <= 0:
                self.ammo = self.st.mag
                self.burst_left = self.st.burst
                self.play("alert", True)
            return
        tgt = self.target
        bx = self.target_box
        if bx is not None and (not bx.alive or bx.hp is None):
            self.target_box = bx = None
            if self.brain is not None: self.brain.think_t = 0.0      # it broke: look again at once
        if bx is not None and self.want_fire:
            # deliberately shooting a prop apart (ai 'breach'): aim at the point of it nearest to her
            ax = min(max(self.x, bx.l), bx.r); ay = min(max(self.y, bx.t), bx.b)
            cx, cy = bx.cx(), bx.cy()
            ax, ay = (ax + cx) * 0.5, (ay + cy) * 0.5
            self.turn_to(ax, ay, dt, 9)
            aligned = abs(wrap(math.atan2(ay - self.y, ax - self.x) - self.heading)) < 0.25
            self.atk_t += dt
            if self.atk_phase is None:
                self.atk_phase = "start"; self.aim_t = 0.0; self.atk_t = 0.0
                self.play("atk_start", False, fade=0.1, restart=True)
            elif self.atk_phase == "start":
                if self.rig.done or self.atk_t > 0.4:
                    self.atk_phase = "ing"; self.play("atk_ing", True, fade=0.06, restart=True)
            if self.atk_phase in ("start", "ing"):
                self.aim_t += dt
            if self.atk_phase == "ing" and aligned:
                self.fire_cd -= dt
                if self.fire_cd <= 0 and self.aim_t >= self.st.aim_time:
                    B.fire_box(self, bx, ax, ay)
                    self.ammo -= 1
                    self.burst_left -= 1
                    if self.burst_left > 0:
                        self.fire_cd = self.st.rof
                    else:
                        self.burst_left = self.st.burst
                        self.fire_cd = self.st.rof + self.st.gap * random.uniform(0.8, 1.25)
                    if self.ammo <= 0:
                        self.start_reload()
            return
        if tgt is not None and self.want_fire and (tgt.alive or (self.st.healer and tgt.team == self.team)):
            self.turn_to(tgt.x, tgt.y, dt, 9)
            ang = math.atan2(tgt.y - self.y, tgt.x - self.x)
            aligned = abs(wrap(ang - self.heading)) < 0.22
            self.atk_t += dt
            if self.atk_phase is None:
                self.atk_phase = "start"; self.aim_t = 0.0; self.atk_t = 0.0
                self.play("atk_start", False, fade=0.1, restart=True)
            elif self.atk_phase == "start":
                if self.rig.done or self.atk_t > 0.4:
                    self.atk_phase = "ing"; self.play("atk_ing", True, fade=0.06, restart=True)
            if self.atk_phase in ("start", "ing"):
                self.aim_t += dt
            if self.atk_phase == "ing" and aligned:
                if self.st.healer and tgt.team == self.team:
                    self.heal_cd -= dt
                    if self.heal_cd <= 0:
                        self.heal_cd = self.st.heal_cd
                        B.heal(self, tgt)
                    return
                self.fire_cd -= dt
                if self.fire_cd <= 0 and self.aim_t >= self.st.aim_time:
                    B.fire(self, tgt)
                    self.ammo -= 1
                    self.burst_left -= 1
                    if self.burst_left > 0:
                        self.fire_cd = self.st.rof
                    else:
                        self.burst_left = self.st.burst
                        self.fire_cd = self.st.rof + self.st.gap * random.uniform(0.8, 1.25)
                    if self.ammo <= 0:
                        self.start_reload()
            return
        # nothing to shoot: lower the gun and keep watch
        self.atk_t += dt
        if self.atk_phase in ("start", "ing"):
            self.atk_phase = "end"; self.atk_t = 0.0; self.play("atk_end", False, fade=0.1, restart=True)
        elif self.atk_phase == "end":
            if self.rig.done or self.atk_t > 0.45:
                self.atk_phase = None; self.play("alert", True)
        else:
            self.play("alert", True)
        if self.face_to is not None:
            self.turn_to(self.face_to[0], self.face_to[1], dt, 4)
        if self.ammo < self.st.mag * 0.5 and self.brain is not None and self.brain.safe_to_reload():
            self.start_reload()

    def start_reload(self):
        if self.reload_t > 0 or self.ammo >= self.st.mag: return
        self.reload_t = self.st.reload
        self.atk_phase = None
        self.play("reload", False, restart=True)

    def turn_to(self, x, y, dt, rate):
        want = math.atan2(y - self.y, x - self.x)
        d = wrap(want - self.heading)
        self.heading = wrap(self.heading + max(-rate * dt, min(rate * dt, d)))

    def set_goal(self, x, y):
        nav = self.B.nav
        x, y = nav.nearest_free(x, y, 8)
        if self.goal is not None and math.hypot(self.goal[0] - x, self.goal[1] - y) < self.size * 0.15 and self.path:
            return
        self.goal = (x, y)
        self.path = nav.path(self.x, self.y, x, y)
        self.stuck_t = 0.0
        self.last_prog = (self.x, self.y)
        if not self.path:
            self.goal = None

    def stop(self):
        self.path = []; self.goal = None

    def move(self, dt):
        """Follow the path. True while she is travelling."""
        B = self.B
        if self.tank is not None:
            return self.tank_move(dt)
        speed = self.st.speed * self.size * (0.75 if self.suppression > 0.6 else 1.0)
        if self.path:
            wx, wy = self.path[0]
            dx, dy = wx - self.x, wy - self.y
            d = math.hypot(dx, dy)
            if d < max(4.0, speed * dt * 1.2):
                self.path.pop(0)
                if not self.path:
                    self.goal = None
            if self.path:
                wx, wy = self.path[0]
                dx, dy = wx - self.x, wy - self.y
                d = math.hypot(dx, dy) or 1.0
                tvx, tvy = dx / d * speed, dy / d * speed
            else:
                tvx = tvy = 0.0
        else:
            tvx = tvy = 0.0
        k = 1.0 - math.exp(-dt * 10.0)
        self.vx += (tvx - self.vx) * k
        self.vy += (tvy - self.vy) * k
        # separation from the others on their feet (a tank shoves her the whole way: it does not move)
        for o in B.fighters:
            if o is self or o.state not in ("alive", "getup"): continue
            dx, dy = self.x - o.x, self.y - o.y
            rr = self.radius + (o.size * TANK["push_r"] if o.tank is not None else o.radius)
            d2 = dx * dx + dy * dy
            if d2 < rr * rr:
                d = math.sqrt(d2) or 0.01
                push = (rr - d) * (1.0 if o.tank is not None else 0.5)
                self.x += dx / d * push; self.y += dy / d * push
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.collide()
        sp = math.hypot(self.vx, self.vy)
        if sp > speed * 0.25 and self.path:
            self.heading = wrap(self.heading + max(-12 * dt, min(12 * dt, wrap(math.atan2(self.vy, self.vx) - self.heading))))
            self.play("run", True, speed=max(0.6, min(1.5, sp / max(1.0, speed))))
            self.stuck_t += dt
            if self.stuck_t > 1.0:
                px, py = self.last_prog
                if math.hypot(self.x - px, self.y - py) < self.size * 0.12:
                    g = self.goal
                    self.path = []
                    if g is not None:
                        self.goal = None
                        self.set_goal(g[0] + random.uniform(-0.4, 0.4) * self.size,
                                      g[1] + random.uniform(-0.4, 0.4) * self.size)
                self.stuck_t = 0.0; self.last_prog = (self.x, self.y)
            return True
        return False

    def collide(self, dt=0.0):
        B = self.B
        for bx in B.boxes:
            if not bx.alive: continue
            r = bx.push_circle(self.x, self.y, self.radius)
            if r is not None:
                nx, ny, pen = r
                if self.tank is not None and bx.hp is not None and bx.kind != "window":
                    # the hull grinds crates and barrels flat (barrels blow up - on everyone)
                    B.damage_box(bx, TANK["prop_dps"] * max(dt, 1 / 60) * B.settings["damage"], self)
                    if not bx.alive: continue
                    self.x += nx * pen * 0.5; self.y += ny * pen * 0.5
                    continue
                if pen > self.radius * 2.5 and self.tank is None:   # a window landed on her: hop out
                    self.x, self.y = B.nav.nearest_free(self.x, self.y)
                    self.path = []; self.goal = None
                else:
                    self.x += nx * pen; self.y += ny * pen
        l, t, r_, b = B.rect
        self.x = min(max(self.x, l + self.radius), r_ - self.radius)
        self.y = min(max(self.y, t + self.size * 0.75), b - self.radius)

    # ------------------------------------------------------------------ damage
    def take_damage(self, amount, src, dirx, diry, explosive=False, crit=False):
        """-> (damage dealt, text kind)."""
        B = self.B
        if self.state != "alive":
            return 0.0, "none"
        if self.invulnerable():
            return 0.0, "immune"
        mul = self.st.defense
        if B.t < self.shield_until: mul *= 0.3
        if B.t < self.mark_until: mul *= 1.2
        dmg = amount * mul
        self.hp -= dmg
        self.last_hit_by = src
        self.last_hurt = B.t
        self.flash_t = 0.12
        self.suppression = min(1.0, self.suppression + 0.12)
        self.ex = min(1.0, self.ex + min(0.04, dmg / max(1.0, self.hp_max) * 0.15))
        if self.brain is not None: self.brain.on_hurt(src)
        if self.hp <= 0:
            self.hp = 0.0
            power = (900.0 if explosive else 420.0 + min(600.0, dmg * 0.12)) * max(0.6, self.size / 120.0)
            self.knockdown(dirx, diry, power, src, explosive)
        return dmg, "crit" if crit else "hit"

    def force_down(self, src, dirx, diry, power, explosive=False, credit=0.0):
        """A crush or a tank shell: she goes down no matter what her HP says (unless she is immune).
        -> (damage credited, text kind)."""
        B = self.B
        if self.state != "alive": return 0.0, "none"
        if self.invulnerable(): return 0.0, "immune"
        dealt = max(self.hp, 0.0)
        self.hp = 0.0
        self.last_hit_by = src
        self.last_hurt = B.t
        self.flash_t = 0.15
        if src is not None and src is not self:
            src.rec["dmg"] += max(dealt, credit)
            src.rec["hits"] += 1
        if self.brain is not None: self.brain.on_hurt(src)
        self.knockdown(dirx, diry, power * max(0.6, self.size / 120.0), src, explosive)
        return max(dealt, credit), "crush"

    def heal_by(self, amount):
        if self.state != "alive": return 0.0
        got = min(amount, self.hp_max - self.hp)
        self.hp += got
        return got

    def knockdown(self, dirx, diry, power, killer, explosive=False):
        B = self.B
        self.lives -= 1
        self.rec["downs"] += 1
        self.state = "down" if self.lives > 0 else "out"
        self.down_t = 0.0
        self.path = []; self.goal = None; self.target = None; self.atk_phase = None
        self.ex_cast = None; self.want_ex = None; self.reload_t = 0.0
        self.target_box = None
        self.vx = self.vy = 0.0
        if self.tank is not None: self.dismount_tank(instant=True)
        if killer is not None and killer is not self:
            killer.rec["kills"] += 1
        B.on_knockdown(self, killer)
        d = math.hypot(dirx, diry) or 1.0
        dirx, diry = dirx / d, diry / d
        self.rag = None
        try:
            self.start_ragdoll(dirx, diry, power, explosive)
        except Exception:
            import traceback; traceback.print_exc()
            self.rag = None
        if self.rag is None:                                  # no usable ragdoll bones: tip her over
            self.rag = dict(fake=True, fall=0.0, dirx=dirx, diry=diry)

    def start_ragdoll(self, dirx, diry, power, explosive):
        B = self.B
        if not self.binding.ok or self.last_W is None:
            return
        rig = self.rig
        rig.limp = True; rig.prev = None; rig.fade = 1.0; rig.done = True; rig.rag_post = []
        W = rig.evaluate(0.0, 0.0)
        Wb = rig.world_base
        M0 = self.matrix_standing()
        spec = build_spec(B.world, self.binding, Wb, M0, self.size, self.size / 300.0)
        if spec is None:
            rig.limp = False
            return
        up = power * (0.75 if explosive else 0.18)
        sk = B.world.add_skeleton(self.uid, spec, (dirx * power, -up, 0.0), "shot")
        # the floor-plane push the engine's 'shot' kick has no axis for: screen y -> -Z, graded by height
        ybot = max(sk.Y); ytop = min(sk.Y); span = max(1.0, ybot - ytop)
        for i in range(sk.n):
            g = 0.25 + 0.75 * (ybot - sk.Y[i]) / span
            sk.VZ[i] += -diry * power * g
            if explosive:
                sk.VX[i] += random.uniform(-80, 80); sk.VZ[i] += random.uniform(-80, 80)
        K, pmap = self.binding.rag3_build_map(sk, M0)
        pel = self.binding.rag3_tokens()["pelvis"]
        P0 = (M0 @ np.append(Wb[pel][:3, 3], 1.0))[:3]
        self.rag = dict(sk=sk, K=K, map=pmap, M0=M0, P0=P0, rots=None, Rr=np.eye(3), g=P0.copy(), posts=[])
        self.last_W = W

    def rag_step(self):
        st = self.rag
        if st is None or st.get("fake"):
            if st is not None: st["fall"] = min(1.0, st["fall"] + 0.06)
            return
        sk = st.get("sk")
        if sk is None or sk.detached:
            return
        if sk.explode_guard():
            self.B.world.remove_skeleton(sk); st["sk"] = None; return
        pose = sk.pose()
        X, Y, Z = pose["x"], pose["y"], pose["z"]
        sx, sy, h = self.B.world.to_screen(X, Y, Z)
        st["g"] = np.array([sx, h, sy])
        posts, Rr = posts_and_root(self.binding, sk, st)
        st["posts"] = posts; st["Rr"] = Rr
        self.x, self.y = sx, sy
        for im in self.B.world.pop_impacts(self.uid):
            if im.strength > 0.6:
                self.B.fx.dust(sx, sy, 3)
                self.B.sound_thud(im.strength)

    def begin_getup(self):
        st = self.rag
        self.state = "getup"
        self.down_t = 0.0
        if st is None or st.get("fake") or st.get("sk") is None:
            self.rag = dict(fake_up=True, t=0.0, fall=(st or {}).get("fall", 1.0), dirx=(st or {}).get("dirx", 1.0),
                            diry=(st or {}).get("diry", 0.0))
            return
        sk = st["sk"]
        st["posts0"] = [(node, R3.mat_to_quat(tuple(P.ravel()))) for node, P in st["posts"]]
        st["q_root0"] = R3.mat_to_quat(tuple(np.asarray(st["Rr"]).ravel()))
        st["g0"] = np.array(st["g"])
        self.B.world.remove_skeleton(sk)
        st["sk"] = None
        # where she will stand: the pelvis' floor point, moved to a free spot
        P0 = st["P0"]; M0 = st["M0"]
        anchor0 = M0[:3, 3]
        off_x, off_z = P0[0] - anchor0[0], P0[2] - anchor0[2]
        nx, ny = self.B.nav.nearest_free(st["g0"][0] - off_x, st["g0"][2] - off_z, 20)
        st["stand"] = (nx, ny)
        st["g1"] = np.array([nx + off_x, P0[1], ny + off_z])
        st["t"] = 0.0

    def getup_step(self, dt):
        st = self.rag
        T_UP = 0.9
        st["t"] = st.get("t", 0.0) + dt
        k = min(1.0, st["t"] / T_UP)
        sm = k * k * (3 - 2 * k)
        if st.get("fake_up"):
            st["fall"] = 1.0 - sm
            if k >= 1.0: self.finish_getup(self.x, self.y)
            return
        st["posts"] = [(node, np.asarray(R3.quat_to_mat(R3.slerp_quat(q, _QI, sm))).reshape(3, 3))
                       for node, q in st["posts0"]]
        st["Rr"] = np.asarray(R3.quat_to_mat(R3.slerp_quat(st["q_root0"], _QI, sm))).reshape(3, 3)
        st["g"] = st["g0"] + (st["g1"] - st["g0"]) * sm
        self.x = st["g0"][0] + (st["stand"][0] + 0 - st["g0"][0]) * sm
        self.y = st["g0"][2] + (st["stand"][1] - st["g0"][2]) * sm
        if k >= 1.0:
            # stand exactly where the blend put her: the spawn matrix moved by (g1 - P0)
            M0 = st["M0"]
            self.finish_getup(st["stand"][0], st["stand"][1], heading_from=M0)

    def finish_getup(self, x, y, heading_from=None):
        B = self.B
        self.rag = None
        self.rig.limp = False; self.rig.rag_post = []; self.rig.speed = 1.0; self.rig.done = False
        self.state = "alive"
        self.x, self.y = x, y
        self.hp = self.hp_max
        self.invuln_until = B.t + float(B.settings["invuln"])
        self.suppression = 0.0
        self.ammo = self.st.mag
        self.anim = None
        self.play("alert", True, fade=0.12)
        B.fx.ring(x, y, self.size * 0.6, (111, 224, 255))
        if self.brain is not None: self.brain.on_getup()

    # ------------------------------------------------------------------ Iroha's tank (tank.py)
    def mount_tank(self):
        """Her EX: the tank deploys around her. Until dismount_tank() she is a vehicle."""
        B = self.B
        if self.tank is not None or self.state != "alive": return
        self.tank = dict(phase="deploy", t=0.0, until=B.t + TANK["duration"], fade=0.0,
                         mag=TANK["shell_mag"], reload_t=0.0, fire_cd=TANK["shell_aim"], aim_t=0.0,
                         speed=0.0, atk=None, atk_t=0.0, crushed=0, shells=0)
        self.radius = self.size * TANK["push_r"]
        self.path = []; self.goal = None; self.atk_phase = None; self.target_box = None
        self.reload_t = 0.0; self.suppression = 0.0; self.want_fire = False
        self.anim = None
        self.play("tank_appear", False, fade=0.0, restart=True)
        B.fx.ring(self.x, self.y, self.size * 1.4, (255, 150, 60), 0.7)
        B.fx.dust(self.x, self.y, 14)
        B.fx.shake = getattr(B.fx, "shake", 0) + 8
        for o in B.fighters:                              # whoever stands where it lands is shoved clear
            if o is self or o.state != "alive": continue
            dx, dy = o.x - self.x, o.y - self.y
            d = math.hypot(dx, dy)
            rr = self.radius + o.radius
            if d < rr:
                d = d or 0.01
                o.x, o.y = B.nav.nearest_free(self.x + dx / d * rr * 1.05, self.y + dy / d * rr * 1.05, 10)
        if self.brain is not None: self.brain.on_mount()
        B.on_tank(self, True)

    def dismount_tank(self, instant=False):
        B = self.B
        if self.tank is None: return
        if not instant and self.tank["phase"] != "stow":
            self.tank["phase"] = "stow"; self.tank["t"] = 0.0
            self.path = []; self.goal = None; self.want_fire = False
            self.play("tank_end", False, fade=0.0, restart=True)
            return
        self.tank = None
        self.radius = self.base_radius
        self.anim = None
        self.vx = self.vy = 0.0
        self.ammo = self.st.mag; self.reload_t = 0.0; self.atk_phase = None
        self.x, self.y = B.nav.nearest_free(self.x, self.y, 12)
        if self.state == "alive":
            self.invuln_until = max(self.invuln_until, B.t + 0.8)
            self.play("alert", True, fade=0.0, restart=True)
        B.fx.dust(self.x, self.y, 10)
        if self.brain is not None: self.brain.on_dismount()
        B.on_tank(self, False)

    def tank_update(self, dt):
        tk = self.tank
        tk["t"] += dt
        if tk["phase"] == "deploy":
            tk["fade"] = min(1.0, tk["t"] / max(0.05, TANK["deploy"] * 0.7))
            if tk["t"] >= TANK["deploy"]:
                tk["phase"] = "drive"; tk["t"] = 0.0
                self.play("alert", True, fade=0.0, restart=True)
        elif tk["phase"] == "drive":
            tk["fade"] = 1.0
            if self.B.t >= tk["until"]:
                self.dismount_tank()
        elif tk["phase"] == "stow":
            tk["fade"] = max(0.0, 1.0 - tk["t"] / max(0.05, TANK["stow"]))
            if tk["t"] >= TANK["stow"]:
                self.dismount_tank(instant=True)

    def tank_time_left(self):
        if self.tank is None: return 0.0
        return max(0.0, self.tank["until"] - self.B.t)

    def tank_act(self, dt):
        """Drive, crush, reload, shell. The brain (ai.Brain.think_tank) sets goal / target."""
        B = self.B
        tk = self.tank
        if tk["phase"] != "drive":
            self.vx *= 0.7; self.vy *= 0.7
            return
        moving = self.tank_move(dt)
        self.tank_crush(dt)
        if tk["reload_t"] > 0:
            tk["reload_t"] -= dt
            if not moving: self.play("reload", False)
            if tk["reload_t"] <= 0:
                tk["mag"] = TANK["shell_mag"]
                self.play("alert", True)
            return
        tgt = self.target
        if tgt is not None and self.want_fire and tgt.alive:
            if not moving:
                self.turn_to(tgt.x, tgt.y, dt, TANK["shell_turn"])
            ang = math.atan2(tgt.y - self.y, tgt.x - self.x)
            aligned = abs(wrap(ang - self.heading)) < 0.2
            d = math.hypot(tgt.x - self.x, tgt.y - self.y)
            tk["atk_t"] += dt
            if tk["atk"] is None:
                tk["atk"] = "start"; tk["aim_t"] = 0.0; tk["atk_t"] = 0.0
                if not moving: self.play("atk_start", False, fade=0.1, restart=True)
            elif tk["atk"] == "start" and (self.rig.done or tk["atk_t"] > 0.4):
                tk["atk"] = "ing"
                if not moving: self.play("atk_ing", True, fade=0.06, restart=True)
            tk["aim_t"] += dt if aligned else 0.0
            tk["fire_cd"] -= dt
            r_bl = TANK["shell_radius"] * TANK["splash_pad"] * self.size
            ally_in = TANK["shell_ally_block"] and any(
                a.team == self.team and a is not self and a.alive and math.hypot(a.x - tgt.x, a.y - tgt.y) < r_bl
                for a in B.fighters)
            if (tk["atk"] == "ing" and aligned and tk["fire_cd"] <= 0 and tk["aim_t"] >= TANK["shell_aim"]
                    and d >= TANK["shell_min"] * self.size and not ally_in):
                B.fire_shell(self, tgt)
                tk["mag"] -= 1; tk["shells"] += 1
                tk["fire_cd"] = TANK["shell_rof"]
                tk["aim_t"] = TANK["shell_aim"] * 0.5
                if tk["mag"] <= 0:
                    tk["reload_t"] = TANK["shell_reload"]; tk["atk"] = None
                    if not moving: self.play("reload", False, restart=True)
            return
        if tk["atk"] is not None:
            tk["atk"] = None
        if not moving:
            self.play("alert", True)
            if self.face_to is not None:
                self.turn_to(self.face_to[0], self.face_to[1], dt, TANK["shell_turn"])

    def tank_move(self, dt):
        """Car-like: she turns toward the next waypoint and drives along her heading."""
        B = self.B
        tk = self.tank
        top = TANK["speed"] * self.size
        want = 0.0
        if self.path:
            wx, wy = self.path[0]
            dx, dy = wx - self.x, wy - self.y
            d = math.hypot(dx, dy)
            if d < max(6.0, top * dt * 1.4):
                self.path.pop(0)
                if not self.path: self.goal = None
            if self.path:
                wx, wy = self.path[0]
                a = math.atan2(wy - self.y, wx - self.x)
                diff = wrap(a - self.heading)
                rate = TANK["turn"] * dt
                self.heading = wrap(self.heading + max(-rate, min(rate, diff)))
                want = top * max(0.0, math.cos(diff)) if abs(diff) < 1.5 else 0.0
                if abs(diff) > 2.2: want = -TANK["reverse"] * self.size        # back up and come round
        k = 1.0 - math.exp(-dt * TANK["accel"])
        tk["speed"] += (want - tk["speed"]) * k
        c, s_ = math.cos(self.heading), math.sin(self.heading)
        self.vx, self.vy = c * tk["speed"], s_ * tk["speed"]
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.collide(dt)
        moving = abs(tk["speed"]) > top * 0.12 and bool(self.path)
        if moving:
            self.play("run", True, speed=max(0.6, min(1.4, abs(tk["speed"]) / top)))
            self.stuck_t += dt
            if self.stuck_t > 1.2:
                px, py = self.last_prog
                if math.hypot(self.x - px, self.y - py) < self.size * 0.15:
                    g = self.goal
                    self.path = []; self.goal = None
                    tk["speed"] = -TANK["reverse"] * self.size * 0.5
                    if g is not None:
                        self.set_goal(g[0] + random.uniform(-0.6, 0.6) * self.size,
                                      g[1] + random.uniform(-0.6, 0.6) * self.size)
                self.stuck_t = 0.0; self.last_prog = (self.x, self.y)
        else:
            self.stuck_t = 0.0; self.last_prog = (self.x, self.y)
        return moving

    def tank_crush(self, dt):
        """Anyone on her feet inside the hull capsule while the tank is rolling goes down. Allies too."""
        B = self.B
        tk = self.tank
        top = TANK["speed"] * self.size
        if abs(tk["speed"]) < top * TANK["crush_min_speed"]: return
        r = TANK["crush_r"] * self.size
        c, s_ = math.cos(self.heading), math.sin(self.heading)
        for o in B.fighters:
            if o is self or o.state != "alive": continue
            if crush_dist(self, o.x, o.y) > r + o.radius * 0.6: continue
            dx, dy = o.x - self.x, o.y - self.y
            d = math.hypot(dx, dy) or 1.0
            # flung forward-and-sideways off the hull, in the direction she is driving
            fx, fy = c * 0.75 + dx / d * 0.55, s_ * 0.75 + dy / d * 0.55
            if tk["speed"] < 0: fx, fy = -fx, -fy
            got, kind = o.force_down(self, fx, fy, TANK["crush_knock"], explosive=False,
                                     credit=TANK["crush_dmg"] * B.settings["damage"])
            if kind == "crush":
                tk["crushed"] += 1
                B.fx.dust(o.x, o.y, 10)
                B.fx.sparks(o.x, o.y, self.size * 0.3, (255, 200, 120), 8)
                B.sound_thud(3.0)
                if B.settings["damage_numbers"]:
                    B.fx.number(o.x, o.y - o.size * 1.05, "CRUSHED", (255, 140, 60), 17, True)
            elif kind == "immune" and B.settings["damage_numbers"] and random.random() < 0.1:
                B.fx.number(o.x, o.y - o.size * 1.05, "IMMUNE", (150, 230, 255), 12)

    # ------------------------------------------------------------------ drawing
    def matrix_standing(self):
        return standing_matrix(self.ch, self.x, self.y, self.heading, self.s)

    def render(self, dt):
        """Pose + model matrix -> image (skipped while a finished body lies still)."""
        B = self.B
        st = self.rag
        if self.state in ("alive",):
            self.rig.advance(dt)
        sk = st.get("sk") if st else None
        if self.state in ("down", "out") and st is not None and not st.get("fake"):
            if sk is None or sk.sleeping:
                if self.img is not None and self.img_sleep:
                    return
                self.img_sleep = True
            else:
                self.img_sleep = False
        else:
            self.img_sleep = False
        if st is not None and not st.get("fake") and not st.get("fake_up") and "M0" in st:
            self.rig.rag_post = st.get("posts") or []
            W = self.rig.evaluate(0.0, 0.0)
            M = ragdoll_matrix(st, st["Rr"], st["g"])
        else:
            self.rig.rag_post = []
            W = self.rig.evaluate(0.0, 0.0)
            M = self.matrix_standing()
            if st is not None and ("fake" in st or "fake_up" in st):       # no ragdoll rig: tip over
                from bapet.mathutil import rot_axis
                f = st.get("fall", 1.0)
                ax = np.array([-st.get("diry", 0.0), 0.0, st.get("dirx", 1.0)])
                n = np.linalg.norm(ax)
                if n > 1e-6:
                    R4 = np.eye(4); R4[:3, :3] = rot_axis(ax / n, -f * math.pi / 2)
                    Tp = np.eye(4); Tp[:3, 3] = [self.x, 0, self.y]
                    Tm = np.eye(4); Tm[:3, 3] = [-self.x, 0, -self.y]
                    M = Tp @ R4 @ Tm @ M
        ride = 0.0
        if self.tank is not None and self.state == "alive":
            # the riding pose with the vehicle: framed on the tank, not on her pelvis
            M = standing_matrix(self.ch, self.x, self.y, self.heading, self.s, fit=tank_fit(self.ch))
            ride = self.tank["fade"]
        self.last_W, self.last_M = W, M
        pel = self.binding.rag3_tokens()["pelvis"] if self.binding.ok else self.ch.model.pelvis
        g = M @ np.append(W[pel][:3, 3], 1.0)
        cx, cy = project(g)
        half = self.size * 1.15
        if ride > 0.0:
            cx, cy = project(np.array([self.x, self.size * 0.55, self.y, 1.0]))
            half = self.size * (1.15 + 1.45 * ride)
        img = B.tdr.render(self.ch, W, M, cx, cy, half, B.app.cfg, ride_fade=ride) if B.tdr is not None else None
        self.img = img
        self.img_rect = (cx - half, cy - half, half * 2, half * 2)
