"""Battle: one match. Owns the fighters, the floor (props + live desktop windows), the physics
world, projectiles and effects, and runs the clock.

Flow:  intro (students beam in, 3-2-1, BATTLE START)  ->  fight  ->  end (slow motion, winners
celebrate)  ->  the result screen (manager.py). It can be paused / stopped any time from the HUD.

Shooting is resolved with real rays: every bullet gets an aim error (weapon spread x suppression x
target movement x range x AI difficulty) and travels until it meets something - a window, a prop,
sandbags (which catch some shots, especially at whoever crouches right behind them), a student in
the way (body cover: allies block shots aimed past them) or the target. Near misses suppress.
"""
from __future__ import annotations

import math
import random
import time
import traceback

from PySide6 import QtCore
from PySide6.QtCore import QTimer, Qt

from bapet.vfx import weapon_fx
from .ai import DIFF, Brain, CoverMap, Commander
from .effects import Effects
from .fighter import Fighter
from .geometry import Box, NavGrid, point_seg_dist, seg_box, seg_circle
from .obstacles import KINDS, generate, spawn_points
from .physics import ArenaWorld, binding_for
from .topdown import TopDownRenderer

GRAV = 1500.0


class Battle(QtCore.QObject):
    def __init__(self, mgr, teams, settings):
        super().__init__()
        self.mgr = mgr
        self.app = mgr.app
        self.settings = dict(settings)
        self.teams = [list(teams[0]), list(teams[1])]
        S = self.settings
        g = self.app.resolve_screen()
        self.home = g
        self.rect = (float(g.left()), float(g.top()), float(g.right() + 1), float(g.bottom() + 1))
        self.size = float(S["size"])
        self.diff = DIFF.get(S["difficulty"], DIFF["veteran"])
        self.t = 0.0
        self.real_t = 0.0
        self.phase = "intro"
        self.phase_t = 0.0
        self.paused = False
        self.speed = float(S["speed"])
        self.slowmo = 1.0
        self.winner = None
        self.result_shown = False
        self.fx = Effects()
        self.projectiles = []
        self.scheduled = []
        self.banners = []
        self.killfeed = []
        self.thud_t = 0.0
        self.world = ArenaWorld(self.rect)
        try:
            self.world.set_iterations(4)
        except Exception:
            pass
        dpr = 1.0
        try: dpr = float(self.app.qapp.primaryScreen().devicePixelRatio())
        except Exception: pass
        side = int(min(512, max(96, self.size * 2.3 * min(dpr, 1.5))))
        self.tdr = TopDownRenderer(self.app.ctx, side)
        self.nav = NavGrid(self.rect, self.size * 0.2)
        self.covers = CoverMap(self)
        self.win_boxes = {}
        self.boxes = []
        self.props = []
        self.boxes_dirty = True
        self.win_t = 0.0
        self.nav_t = 0.0
        rng = random.Random()
        # ---- students
        self.fighters = []
        keep = []
        for team in (0, 1):
            pts, home = spawn_points(self.rect, len(self.teams[team]), team, S["layout"], self.size, rng)
            keep.append((home[0], home[1], self.size * 1.8))
            for i, (e, (x, y)) in enumerate(zip(self.teams[team], pts)):
                f = Fighter(self, e, team, i, x, y)
                f.brain = Brain(f)
                f.visible_t = 0.25 + i * 0.22 + team * 0.11
                self.fighters.append(f)
                keep.append((x, y, self.size * 0.9))
        # ---- windows first (obstacles avoid them), then props
        self.refresh_windows(force=True)
        if S["obstacles"]:
            blocked = [b.rect for b in self.win_boxes.values()]
            self.props = generate(self.rect, self.size, S["layout"], S["obstacle_amount"], S["barrels"], blocked, keep)
        self.rebuild_boxes()
        for f in self.fighters:
            f.x, f.y = self.nav.nearest_free(f.x, f.y)
            ex = sum(o.x for o in self.fighters if o.team != f.team) / max(1, sum(1 for o in self.fighters if o.team != f.team))
            ey = sum(o.y for o in self.fighters if o.team != f.team) / max(1, sum(1 for o in self.fighters if o.team != f.team))
            f.heading = math.atan2(ey - f.y, ex - f.x)
        self.commanders = [Commander(self, 0), Commander(self, 1)]
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.last = time.perf_counter()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        from .hud import ArenaHUD, ArenaOverlay
        self.overlay = ArenaOverlay(self)
        self.hud = ArenaHUD(self)
        self.overlay.show_on(self.home)
        self.hud.open()
        self.last = time.perf_counter()
        self.timer.start(int(1000 / max(10, int(self.settings["fps"]))))

    def stop(self):
        self.timer.stop()
        for f in self.fighters:
            st = f.rag
            if st and st.get("sk") is not None:
                try: self.world.remove_skeleton(st["sk"])
                except Exception: pass
            try:
                f.rig.limp = False; f.rig.rag_post = []
            except Exception:
                pass
        for w in (getattr(self, "overlay", None), getattr(self, "hud", None)):
            if w is not None:
                try:
                    w.timer.stop() if hasattr(w, "timer") else None
                    w.hide(); w.deleteLater()
                except Exception:
                    pass
        self.overlay = self.hud = None
        if self.tdr is not None:
            self.tdr.release()

    def binding(self, ch):
        return binding_for(ch)

    def set_paused(self, on):
        self.paused = bool(on)

    # ------------------------------------------------------------------ the floor
    def refresh_windows(self, force=False):
        if not self.settings["windows_cover"]:
            if self.win_boxes:
                self.win_boxes = {}; self.boxes_dirty = True
            return
        tr = getattr(self.app, "tracker", None)
        if tr is None or not tr.enabled:
            return
        try:
            dpr = float(self.app.active.dpr) if getattr(self.app, "active", None) else 1.0
            tr.refresh(dpr, self.home.top())
        except Exception:
            traceback.print_exc(); return
        l, t, r, b = self.rect
        area = (r - l) * (b - t)
        seen = set()
        changed = False
        for h, wl, wt, wr, wb in tr.wins:
            cl, ct, cr, cb = max(l, wl), max(t, wt), min(r, wr), min(b, wb)
            if cr - cl < 24 or cb - ct < 24: continue
            if (cr - cl) * (cb - ct) > area * 0.45: continue          # a huge window would leave no floor
            seen.add(h)
            bx = self.win_boxes.get(h)
            if bx is None:
                self.win_boxes[h] = Box(cl, ct, cr, cb, "window", 1e6, "full", None, hwnd=h)
                changed = True
            elif max(abs(bx.l - cl), abs(bx.t - ct), abs(bx.r - cr), abs(bx.b - cb)) > 1.5:
                dt = max(0.05, self.real_t - getattr(bx, "_t", self.real_t - 0.15))
                bx.vx = max(-3000.0, min(3000.0, (cl - bx.l) / dt)); bx.vy = max(-3000.0, min(3000.0, (ct - bx.t) / dt))
                bx.l, bx.t, bx.r, bx.b = cl, ct, cr, cb
                changed = True
            else:
                bx.vx = bx.vy = 0.0
            if bx is not None: bx._t = self.real_t
        for h in list(self.win_boxes):
            if h not in seen:
                self.win_boxes.pop(h); changed = True
        if changed or force:
            self.boxes_dirty = True

    def rebuild_boxes(self):
        self.boxes = [b for b in self.props if b.alive] + list(self.win_boxes.values())
        self.nav.rebuild(self.boxes, self.size * 0.17 + 2.0)
        self.covers.rebuild()
        self.world.set_boxes(self.boxes)
        self.boxes_dirty = False
        for f in self.fighters:                         # paths may cross a new wall now
            if f.alive and f.goal is not None:
                g = f.goal; f.goal = None; f.set_goal(*g)
            if f.alive and f.brain is not None:
                f.brain.think_t = min(f.brain.think_t, 0.1)

    # ------------------------------------------------------------------ queries
    def los(self, x0, y0, x1, y1, ign_r=0.0):
        """Line of sight on the floor: full cover blocks (props next to the viewer don't - she leans out)."""
        for bx in self.boxes:
            if not bx.alive or bx.cover != "full": continue
            if ign_r > 0 and bx.dist(x0, y0) < ign_r: continue
            if bx.kind != "window" and bx.dist(x1, y1) < self.size * 0.3: continue   # her head shows over it
            if seg_box(x0, y0, x1, y1, bx) is not None: return False
        return True

    def cover_value(self, sx, sy, tx, ty, tf=None, at_spot=None):
        """0 = in the open, 0.6 = half cover, 0.85+ = behind solid cover, from a shooter at (sx, sy)."""
        r_ign = self.size * 0.27
        r_adj = self.size * 0.32
        best = 0.0
        for bx in self.boxes:
            if not bx.alive: continue
            if bx.dist(sx, sy) < r_ign: continue
            if seg_box(sx, sy, tx, ty, bx) is None: continue
            adj = bx.dist(tx, ty) < r_adj
            if bx.cover == "full": v = 0.88 if adj else 1.0
            else: v = 0.62 if adj else 0.15
            if v > best:
                best = v
                if best >= 1.0: return 1.0
        if best < 0.65:
            for a in self.fighters:
                if a is tf or a.state not in ("alive", "getup"): continue
                if math.hypot(a.x - sx, a.y - sy) < a.radius * 1.5: continue
                t = seg_circle(sx, sy, tx, ty, a.x, a.y, a.radius * 1.1)
                if t is not None and 0.04 < t < 0.97:
                    best = max(best, 0.65)
                    break
        return best

    # ------------------------------------------------------------------ shooting
    def fire(self, f, tgt):
        st = f.st
        S = self.settings
        mx, my, mh = f.muzzle()
        tx, ty, th = tgt.chest()
        dist = math.hypot(tx - mx, ty - my)
        rng = st.range * self.size
        spread = st.spread * self.diff["spread"] * (1.0 + f.suppression * 0.9)
        if math.hypot(tgt.vx, tgt.vy) > self.size * 0.5: spread *= 1.3
        if dist > rng: spread *= 1.0 + (dist / rng - 1.0) * 1.6
        if self.t < f.buff_until: spread *= 0.8
        base = math.atan2(ty - my, tx - mx)
        look = weapon_fx(st.weapon, getattr(f.ch, "bullet", None)) if weapon_fx else {}
        color = tuple(look.get("color", (255, 210, 120))) if isinstance(look, dict) else (255, 210, 120)
        f.rec["shots"] += 1
        self.fx.muzzle(mx, my, mh, base, (look.get("flash", 1.0) if isinstance(look, dict) else 1.0), color)
        if st.proj:
            self.launch(f, st.proj, tx + random.gauss(0, spread * dist), ty + random.gauss(0, spread * dist),
                        random.uniform(*st.dmg) * S["damage"] * st.dmg_mul * (1.25 if self.t < f.buff_until else 1.0),
                        st.radius * self.size)
            return
        if st.flame:
            self.fx.flame(mx, my, mh, base, rng * 0.5)
        for _ in range(st.pellets):
            ang = base + random.gauss(0.0, spread)
            dmg = random.uniform(*st.dmg) * S["damage"] * st.dmg_mul * (1.25 if self.t < f.buff_until else 1.0)
            if st.pellets > 1:
                dmg *= max(0.35, 1.0 - 0.6 * min(1.0, dist / rng))
            self.trace(f, mx, my, mh, ang, rng * 1.7, dmg, tgt, color, beam=st.beam, pierce=st.pierce,
                       width=look.get("width", 2.6) if isinstance(look, dict) else 2.6, quiet=st.flame)

    def trace(self, f, mx, my, mh, ang, length, dmg, aimed, color, beam=False, pierce=False, width=2.6, quiet=False,
              crit_chance=0.12):
        S = self.settings
        ex, ey = mx + math.cos(ang) * length, my + math.sin(ang) * length
        hits = []
        r_ign = f.radius * 1.6
        for bx in self.boxes:
            if not bx.alive or bx.dist(mx, my) < r_ign: continue
            t = seg_box(mx, my, ex, ey, bx)
            if t is not None: hits.append((t, 0, bx))
        for o in self.fighters:
            if o is f or o.state not in ("alive", "getup"): continue
            t = seg_circle(mx, my, ex, ey, o.x, o.y, o.radius * 1.15)
            if t is not None: hits.append((t, 1, o))
        hits.sort(key=lambda h: h[0])
        end_t = 1.0
        hit_any = False
        for t, kind, obj in hits:
            if kind == 0:
                bx = obj
                near_target = aimed is not None and bx.dist(aimed.x, aimed.y) < self.size * 0.32
                peeking = aimed is not None and aimed.target is not None and aimed.want_fire
                if bx.kind == "window":
                    p_block = 1.0
                elif bx.cover == "full":
                    p_block = (0.6 if peeking else 0.92) if near_target else 1.0
                else:
                    p_block = (0.45 if peeking else 0.7) if near_target else 0.15
                if beam and pierce and bx.kind != "window" and bx.cover == "half":
                    p_block = 0.0
                if random.random() < p_block:
                    end_t = t
                    px, py = mx + (ex - mx) * t, my + (ey - my) * t
                    h = min(mh, bx.height * 0.7)
                    self.fx.sparks(px, py, h, (255, 230, 170), 4)
                    if bx.hp is not None:
                        self.damage_box(bx, dmg * (0.6 if bx.kind == "barrel" else 0.35), f)
                    break
            else:
                o = obj
                px, py = mx + (ex - mx) * t, my + (ey - my) * t
                if o.team == f.team:
                    if not S["friendly_fire"]:
                        end_t = t
                        self.fx.sparks(px, py, mh, (180, 220, 255), 3)
                        if S["damage_numbers"]: self.fx.number(o.x, o.y - o.size * 1.05, "COVER", (170, 210, 255), 12)
                        break
                crit = random.random() < crit_chance
                d, kind_txt = o.take_damage(dmg * (1.6 if crit else 1.0), f, math.cos(ang), math.sin(ang),
                                            explosive=False, crit=crit)
                hit_any = True
                if d > 0:
                    f.rec["dmg"] += d
                    f.rec["hits"] += 1
                    f.ex = min(1.0, f.ex + min(0.03, d / 80000.0))
                    self.fx.hit(px, py, mh, crit)
                    if S["damage_numbers"]:
                        self.fx.number(o.x, o.y - o.size * 1.05, f"{int(d)}", (255, 236, 120) if crit else (255, 255, 255),
                                       16, crit)
                elif kind_txt == "immune" and S["damage_numbers"]:
                    self.fx.number(o.x, o.y - o.size * 1.05, "IMMUNE", (150, 230, 255), 12)
                if not (beam and pierce):
                    end_t = t
                    break
        px, py = mx + (ex - mx) * end_t, my + (ey - my) * end_t
        if not quiet:
            self.fx.tracer(mx, my, mh, px, py, mh * 0.9, color, width, beam=beam)
        # near misses keep heads down
        for o in self.fighters:
            if o.team == f.team or not o.alive: continue
            d, u = point_seg_dist(o.x, o.y, mx, my, px, py)
            if d < self.size * 0.55 and u > 0.05:
                o.suppression = min(1.0, o.suppression + (0.09 if not hit_any else 0.04))
                if o.brain is not None:
                    o.brain.memory[f] = (f.x, f.y, self.t)

    def damage_box(self, bx, dmg, src):
        if bx.hp is None or not bx.alive: return
        bx.hp -= dmg
        if bx.hp <= 0:
            bx.alive = False
            self.boxes_dirty = True
            if KINDS.get(bx.kind, {}).get("explosive"):
                self.explode(bx.cx(), bx.cy(), self.size * 1.45, 2600.0 * self.settings["damage"], src, barrel=True)
            else:
                self.fx.dust(bx.cx(), bx.cy(), 8)
                self.fx.sparks(bx.cx(), bx.cy(), bx.height * 0.5, (220, 180, 120), 10)

    # ------------------------------------------------------------------ projectiles & explosions
    def launch(self, f, kind, tx, ty, dmg, radius, delay=0.0, lob=None):
        mx, my, mh = f.muzzle()
        d = math.hypot(tx - mx, ty - my)
        if lob is None: lob = kind in ("grenade", "mortar", "frag", "shell")
        if lob:
            v = self.size * (4.2 if kind != "mortar" and kind != "shell" else 3.0)
            T = max(0.35, d / v)
            vh = GRAV * T / 2.0 - mh / T
        else:
            v = self.size * 9.0
            T = max(0.05, d / v)
            vh = 0.0
        pr = dict(kind=kind, owner=f, x=mx, y=my, h=mh, vx=(tx - mx) / T, vy=(ty - my) / T, vh=vh, lob=lob,
                  tx=tx, ty=ty, dmg=dmg, radius=radius, t=-delay, T=T, trail=[])
        self.projectiles.append(pr)
        return pr

    def update_projectiles(self, dt):
        keep = []
        for pr in self.projectiles:
            pr["t"] += dt
            if pr["t"] < 0: keep.append(pr); continue
            pr["x"] += pr["vx"] * dt; pr["y"] += pr["vy"] * dt
            if pr["lob"]:
                pr["vh"] -= GRAV * dt; pr["h"] += pr["vh"] * dt
            pr["trail"].append((pr["x"], pr["y"], pr["h"])); pr["trail"] = pr["trail"][-10:]
            boom = False
            if pr["lob"] and pr["h"] <= 0:
                boom = True
            l, t, r, b = self.rect
            if not (l <= pr["x"] <= r and t <= pr["y"] <= b):
                boom = True
            if not boom:
                for bx in self.boxes:
                    if bx.alive and bx.contains(pr["x"], pr["y"]) and pr["h"] < bx.height:
                        boom = True; break
            if not boom and not pr["lob"]:
                for o in self.fighters:
                    if o.team != pr["owner"].team and o.alive and math.hypot(o.x - pr["x"], o.y - pr["y"]) < o.radius * 1.2:
                        boom = True; break
                if pr["t"] > pr["T"] * 1.05: boom = True
            if boom:
                self.explode(pr["x"], pr["y"], pr["radius"], pr["dmg"], pr["owner"])
            else:
                keep.append(pr)
        self.projectiles = keep

    def explode(self, x, y, radius, dmg, src, barrel=False):
        S = self.settings
        self.fx.explosion(x, y, radius)
        self.sound_thud(3.0)
        for o in self.fighters:
            if o.state != "alive": continue
            d = math.hypot(o.x - x, o.y - y)
            if d > radius + o.radius: continue
            k = 1.0 - 0.6 * min(1.0, d / max(1.0, radius))
            if not self.los(x, y, o.x, o.y, 0.0): k *= 0.3
            if src is not None and o.team == src.team and not S["friendly_fire"] and not barrel: continue
            dx, dy = (o.x - x, o.y - y) if d > 1 else (random.uniform(-1, 1), random.uniform(-1, 1))
            got, _k = o.take_damage(dmg * k, src, dx, dy, explosive=True)
            if got > 0:
                if src is not None and src is not o: src.rec["dmg"] += got
                if S["damage_numbers"]:
                    self.fx.number(o.x, o.y - o.size * 1.05, f"{int(got)}", (255, 170, 90), 18, got > 1500)
            o.suppression = 1.0
        for bx in list(self.boxes):
            if bx.alive and bx.hp is not None and bx.dist(x, y) < radius:
                self.damage_box(bx, dmg * 0.8, src)
        self.world.blast(x, y, radius * 1.6, 900.0 * max(0.6, self.size / 120.0))

    # ------------------------------------------------------------------ support
    def heal(self, h, a):
        amt = h.st.heal * (1.25 if self.t < h.buff_until else 1.0)
        got = a.heal_by(amt)
        if got > 0:
            h.rec["heal"] += got
            hx, hy, hh = h.muzzle()
            self.fx.heal_beam(hx, hy, hh, a.x, a.y, a.size * 0.6)
            self.fx.heal(a.x, a.y, a.size * 0.8, got)
            if self.settings["damage_numbers"]:
                self.fx.number(a.x, a.y - a.size * 1.05, f"+{int(got)}", (110, 240, 160), 15)

    def announce_ex(self, f):
        self.banners.append(dict(kind="ex", f=f, t=0.0, life=1.8))

    def schedule(self, delay, fn):
        self.scheduled.append([self.t + delay, fn])

    def do_ex(self, f, pl):
        kind = pl.get("kind")
        S = self.settings
        sz = self.size
        aim = pl.get("aim")
        if kind == "grenade" and aim:
            self.launch(f, "frag", aim[0], aim[1], 2300.0 * S["damage"], sz * 1.35)
        elif kind == "strike" and aim:
            for i in range(5):
                ox, oy = random.uniform(-1, 1) * sz * 1.1, random.uniform(-1, 1) * sz * 0.9
                pr = self.launch(f, "shell", aim[0] + ox, aim[1] + oy, 1700.0 * S["damage"], sz * 1.05, delay=0.25 * i)
                pr["h"] = sz * 6; pr["vh"] = -sz * 2
        elif kind == "pierce" and aim:
            mx, my, mh = f.muzzle()
            ang = math.atan2(aim[1] - my, aim[0] - mx)
            self.trace(f, mx, my, mh, ang, f.st.range * sz * 2.4, sum(f.st.dmg) / 2 * 1.7 * S["damage"], pl.get("target"),
                       (150, 230, 255), beam=True, pierce=True, width=7.0, crit_chance=0.2)
            self.fx.shake += 6
        elif kind == "barrage" and pl.get("target") is not None:
            tgt = pl["target"]
            for i in range(22):
                self.schedule(i * 0.07, lambda tg=tgt: (tg.alive and f.alive) and self._barrage_shot(f, tg))
        elif kind == "charge" and aim:
            mx, my = f.x, f.y
            dx, dy = aim[0] - mx, aim[1] - my
            d = math.hypot(dx, dy) or 1.0
            step = min(d - sz * 0.6, sz * 2.4)
            nx, ny = mx + dx / d * step, my + dy / d * step
            if step > 0 and self.nav.line_free(mx, my, nx, ny):
                for k in range(5):
                    self.fx.dust(mx + (nx - mx) * k / 5, my + (ny - my) * k / 5, 2)
                f.x, f.y = nx, ny
            tgt = pl.get("target")
            if tgt is not None and tgt.alive:
                for _ in range(2):
                    self.fire_raw(f, tgt, mul=1.5)
        elif kind == "shield":
            f.shield_until = self.t + 5.5
            for a in self.fighters:
                if a.team == f.team and a.alive and math.hypot(a.x - f.x, a.y - f.y) < sz * 2.2:
                    a.shield_until = max(a.shield_until, self.t + 3.0)
            self.fx.ring(f.x, f.y, sz * 1.2, (120, 200, 255))
        elif kind == "mass_heal":
            for a in self.fighters:
                if a.team == f.team and a.alive and math.hypot(a.x - f.x, a.y - f.y) < sz * 6.5:
                    got = a.heal_by(a.hp_max * 0.45)
                    f.rec["heal"] += got
                    self.fx.heal(a.x, a.y, a.size * 0.8, got)
                    if got > 0 and S["damage_numbers"]:
                        self.fx.number(a.x, a.y - a.size * 1.05, f"+{int(got)}", (110, 240, 160), 16)
            self.fx.ring(f.x, f.y, sz * 3.0, (110, 240, 160), 0.8)
        elif kind == "buff":
            for a in self.fighters:
                if a.team == f.team and a.alive and math.hypot(a.x - f.x, a.y - f.y) < sz * 6.5:
                    a.buff_until = self.t + 7.0
                    self.fx.ring(a.x, a.y, sz * 0.7, (255, 210, 90))
            tgt = pl.get("target")
            if tgt is not None and tgt.alive:
                tgt.mark_until = self.t + 7.0

    def _barrage_shot(self, f, tgt):
        st = f.st
        mx, my, mh = f.muzzle()
        base = math.atan2(tgt.y - my, tgt.x - mx)
        f.heading = base
        self.fx.muzzle(mx, my, mh, base, 1.1)
        self.trace(f, mx, my, mh, base + random.gauss(0, st.spread * 1.3), st.range * self.size * 1.6,
                   random.uniform(*st.dmg) * self.settings["damage"], tgt, (255, 190, 80))
        for o in self.fighters:
            if o.team != f.team and o.alive and math.hypot(o.x - tgt.x, o.y - tgt.y) < self.size * 2:
                o.suppression = 1.0
        return True

    def fire_raw(self, f, tgt, mul=1.0):
        st = f.st
        mx, my, mh = f.muzzle()
        base = math.atan2(tgt.y - my, tgt.x - mx)
        self.fx.muzzle(mx, my, mh, base, 1.4)
        for _ in range(max(1, st.pellets)):
            self.trace(f, mx, my, mh, base + random.gauss(0, st.spread), st.range * self.size * 1.4,
                       random.uniform(*st.dmg) * self.settings["damage"] * mul, tgt, (255, 210, 120))

    # ------------------------------------------------------------------ events
    def on_knockdown(self, f, killer):
        self.killfeed.append(dict(a=killer, b=f, t=self.real_t, out=f.state == "out"))
        self.killfeed = self.killfeed[-6:]
        self.fx.ring(f.x, f.y, self.size * 0.9, (255, 120, 140) if f.team == 1 else (120, 180, 255))
        if f.cover is not None and not isinstance(f.cover, tuple):
            f.cover.claim = None
        f.cover = None
        if f.state == "out":
            self.banners.append(dict(kind="out", f=f, t=0.0, life=1.6))

    def sound_thud(self, strength):
        if strength < 1.8 or self.real_t - self.thud_t < 0.12: return
        self.thud_t = self.real_t
        play = getattr(self.app, "play_rag_sound", None)
        if play:
            try: play()
            except Exception: pass

    # ------------------------------------------------------------------ the clock
    def tick(self):
        now = time.perf_counter()
        rdt = min(0.1, now - self.last); self.last = now
        self.real_t += rdt
        try:
            self.win_t -= rdt
            if self.win_t <= 0:
                self.win_t = 0.15
                self.refresh_windows()
            self.nav_t -= rdt
            if self.boxes_dirty and self.nav_t <= 0:
                self.nav_t = 0.25
                self.rebuild_boxes()
            dt = 0.0 if (self.paused or self.result_shown) else rdt * self.speed * self.slowmo
            if dt > 0:
                self.step(dt)
            for f in self.fighters:
                if self.real_t >= f.visible_t:
                    f.render(dt if self.phase != "intro" or True else 0.0)
            if self.overlay is not None: self.overlay.update()
            if self.hud is not None: self.hud.update()
        except Exception:
            traceback.print_exc()

    def step(self, dt):
        self.t += dt
        self.phase_t += dt
        self.fx.update(dt)
        for b in self.banners: b["t"] += dt
        self.banners = [b for b in self.banners if b["t"] < b["life"]]
        if self.phase == "intro":
            for f in self.fighters:
                if not getattr(f, "_summoned", False) and self.t >= f.visible_t:
                    f._summoned = True
                    self.fx.summon(f.x, f.y, (30, 161, 255) if f.team == 0 else (255, 76, 104), self.size)
            if self.phase_t >= 3.4:
                self.phase = "fight"; self.phase_t = 0.0
                self.banners.append(dict(kind="start", t=0.0, life=1.4))
            return
        if self.scheduled:
            due = [s for s in self.scheduled if s[0] <= self.t]
            self.scheduled = [s for s in self.scheduled if s[0] > self.t]
            for _t, fn in due:
                try: fn()
                except Exception: traceback.print_exc()
        if self.phase == "fight":
            for c in self.commanders: c.update(dt)
        for f in self.fighters:
            if self.phase == "end" and f.alive:
                f.vx = f.vy = 0
                if f.team == self.winner:
                    f.play("victory", True)
                continue
            f.update(dt)
        self.update_projectiles(dt)
        self.world.set_pillars([(f.x, self.world.CZ - f.y, f.radius, f.size * 0.85)
                                for f in self.fighters if f.state in ("alive", "getup")])
        self.world.step(dt)
        if self.phase == "fight":
            self.check_end()
        elif self.phase == "end":
            if self.phase_t > 1.3: self.slowmo = 1.0
            if self.phase_t > 3.2 and not self.result_shown:
                self.result_shown = True
                self.mgr.show_results(self)

    def check_end(self):
        live = [any(f.in_play for f in self.fighters if f.team == t) for t in (0, 1)]
        winner = None
        if not live[0] and not live[1]: winner = -1
        elif not live[0]: winner = 1
        elif not live[1]: winner = 0
        tl = self.settings["time_limit"]
        if winner is None and tl and self.t >= tl:
            p = [sum(f.power() for f in self.fighters if f.team == t) for t in (0, 1)]
            winner = 0 if p[0] > p[1] + 0.05 else 1 if p[1] > p[0] + 0.05 else -1
        if winner is not None:
            self.winner = winner
            self.phase = "end"; self.phase_t = 0.0
            self.slowmo = 0.35
            self.banners.append(dict(kind="end", t=0.0, life=99.0))
            for f in self.fighters:
                f.want_fire = False; f.path = []

    def time_left(self):
        tl = self.settings["time_limit"]
        return max(0.0, tl - self.t) if tl else None

    def mvp(self):
        best, bs = None, -1
        for f in self.fighters:
            s = f.rec["dmg"] + f.rec["heal"] * 1.2 + f.rec["kills"] * 1500 - f.rec["downs"] * 400
            if self.winner in (0, 1) and f.team == self.winner: s += 2000
            if s > bs: best, bs = f, s
        return best
