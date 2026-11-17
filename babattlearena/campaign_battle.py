"""One campaign room: a Battle with an uneven fight, run modifiers, loot and a student you can drive.

    CampaignBattle    Battle + the run's modifiers (permanent upgrades x supports), enemy tiers (grunt / elite /
                      boss, all of them the students' own .glb models), Credits dropped by retired enemies,
                      supplies (consumables) and the hand-over to the campaign when the room ends.
    CampaignFighter   a Fighter with a tier, a modifier table, stuns and regeneration.
    PlayerFighter     every squad member is one. While `manual` is set (the student you control) the keyboard
                      and mouse replace her tactical brain; the rest of her body (animation, bursts, reloads,
                      EX casting, ragdolls) is the ordinary Fighter. Switch it off and her brain takes over again.
    ControlPad        an (almost) invisible full-screen window that takes the keyboard and mouse while you are
                      in control. The battlefield overlay itself stays click-through.
    CampaignOverlay / CampaignHUD   the arena overlay and top bar with the campaign extras drawn on top.

Controls (while MANUAL is on)
    WASD / arrows  move            LMB (hold)  fire at the cursor (snaps to an enemy under it; healers heal allies)
    Space / Shift  dash (brief invulnerability)        RMB / Q / E  EX skill at the cursor
    R  reload      1-4  supplies   Tab  control the next squad member      T  manual / auto      Esc  pause
"""
from __future__ import annotations

import math
import random

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRect, QRectF, Qt

from .battle import Battle
from .campaign_data import AREAS, BASE, ITEM_BY_ID, ROOMS_PER_AREA
from .fighter import Fighter, wrap
from .hud import ArenaHUD, ArenaOverlay
from .obstacles import OBLIQUE
from .tank import TANK
from .theme import (AF, BLUE, BLUE_D, CYAN, GREEN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PURPLE, RED, RED_T, SKY, WHITE,
                    YELLOW, YELLOW_D, W_BLACK, W_BOLD, clamp, col, ease_out, glyph_icon, para, text)

GOLD = (255, 214, 80)
HELP = ("WASD move  \u00b7  LMB fire  \u00b7  RMB / Q EX skill  \u00b7  SPACE dash  \u00b7  R reload  \u00b7  1-4 supplies"
        "  \u00b7  TAB swap student  \u00b7  T manual / auto  \u00b7  ESC pause")


def _k(key):
    return int(getattr(key, "value", key))


# ============================================================================== input
class PlayerInput:
    """What the player is holding right now, plus the keys pressed since the last step."""

    MOVE = {_k(Qt.Key.Key_W): (0, -1), _k(Qt.Key.Key_Up): (0, -1), _k(Qt.Key.Key_S): (0, 1), _k(Qt.Key.Key_Down): (0, 1),
            _k(Qt.Key.Key_A): (-1, 0), _k(Qt.Key.Key_Left): (-1, 0), _k(Qt.Key.Key_D): (1, 0), _k(Qt.Key.Key_Right): (1, 0)}
    ACTIONS = {_k(Qt.Key.Key_Space): "dash", _k(Qt.Key.Key_Shift): "dash", _k(Qt.Key.Key_R): "reload",
               _k(Qt.Key.Key_Q): "ex", _k(Qt.Key.Key_E): "ex", _k(Qt.Key.Key_Tab): "swap", _k(Qt.Key.Key_T): "auto",
               _k(Qt.Key.Key_1): "item0", _k(Qt.Key.Key_2): "item1", _k(Qt.Key.Key_3): "item2", _k(Qt.Key.Key_4): "item3"}

    def __init__(self):
        self.keys = set()
        self.lmb = False
        self.presses = []

    def clear(self):
        self.keys.clear(); self.lmb = False; self.presses.clear()

    def axis(self):
        x = y = 0
        for k in self.keys:
            d = self.MOVE.get(k)
            if d: x += d[0]; y += d[1]
        x = max(-1, min(1, x)); y = max(-1, min(1, y))
        n = math.hypot(x, y)
        return (x / n, y / n) if n > 0 else (0.0, 0.0)

    def press(self, name):
        if len(self.presses) < 16: self.presses.append(name)

    def take(self, name):
        if name in self.presses:
            self.presses.remove(name)
            return True
        return False


class ControlPad(QtWidgets.QWidget):
    """Takes the keyboard and mouse for the student you control. It is painted with an alpha of 1/255: invisible,
    but enough for the window system to hand it the clicks instead of the desktop underneath."""

    def __init__(self, battle):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.B = battle
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setWindowTitle("Campaign Controls")

    def show_on(self, g, hole=None):
        self.setGeometry(g)
        if hole is not None:                                   # the HUD bar keeps its own clicks
            local = QRect(hole.left() - g.left(), hole.top() - g.top(), hole.width(), hole.height())
            self.setMask(QtGui.QRegion(self.rect()).subtracted(QtGui.QRegion(local)))
        self.show(); self.raise_(); self.grab_focus()

    def grab_focus(self):
        self.activateWindow(); self.setFocus()

    def focusNextPrevChild(self, _next):                       # Tab is a game key here, not focus navigation
        return False

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 1))
        p.end()

    def keyPressEvent(self, ev):
        if ev.isAutoRepeat(): return
        k = _k(ev.key())
        if k == _k(Qt.Key.Key_Escape):
            self.B.mgr.pause_menu()
            return
        ctl = self.B.ctl
        ctl.keys.add(k)
        name = ctl.ACTIONS.get(k)
        if name: ctl.press(name)

    def keyReleaseEvent(self, ev):
        if ev.isAutoRepeat(): return
        self.B.ctl.keys.discard(_k(ev.key()))

    def mousePressEvent(self, ev):
        ctl = self.B.ctl
        if ev.button() == Qt.MouseButton.LeftButton: ctl.lmb = True
        elif ev.button() == Qt.MouseButton.RightButton: ctl.press("ex")
        elif ev.button() == Qt.MouseButton.MiddleButton: ctl.press("dash")
        if not self.isActiveWindow(): self.grab_focus()

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton: self.B.ctl.lmb = False

    def focusOutEvent(self, ev):
        self.B.ctl.clear()
        super().focusOutEvent(ev)

    def hideEvent(self, ev):
        self.B.ctl.clear()
        super().hideEvent(ev)

    def closeEvent(self, ev):
        ev.ignore()


class AimPoint:
    """A spot on the floor the player is shooting at: enough of a Fighter for Battle.fire / trace."""
    alive = True
    state = "alive"
    tank = None
    target = None
    want_fire = False
    vx = vy = 0.0
    mark_until = shield_until = 0.0

    def __init__(self, owner):
        self.team = 1 - owner.team
        self.size = owner.size
        self.radius = owner.radius
        self.x, self.y = owner.x, owner.y
        self.name = "aim"

    def chest(self): return self.x, self.y, self.size * 0.62
    def invulnerable(self): return False
    def hp_frac(self): return 1.0
    def block_radius(self): return self.radius


# ============================================================================== fighters
class CampaignFighter(Fighter):
    tier = "grunt"
    manual = False

    def __init__(self, battle, entry, team, slot, x, y):
        super().__init__(battle, entry, team, slot, x, y)
        self.mods = {}
        self.stun_until = 0.0
        self.revive_frac = 0.0

    def setup(self, tier, mods, hp_frac=1.0, lives=1, scale=1.0):
        """Fold a modifier table into her own combat profile (every Fighter has a private CombatProfile)."""
        self.tier, self.mods = tier, mods
        g = mods.get
        st = self.st
        st.dmg_mul *= g("dmg", 1.0); st.box_dps *= g("dmg", 1.0)
        st.defense *= g("taken", 1.0)
        k = max(0.2, g("rof", 1.0))
        st.rof /= k; st.gap /= k
        st.reload *= g("reload", 1.0)
        st.mag = max(1, int(round(st.mag * g("mag", 1.0))))
        self.ammo = st.mag
        st.speed *= g("speed", 1.0)
        st.ex_cost /= max(0.2, g("ex", 1.0))
        self.hp_max *= g("hp", 1.0)
        self.hp = self.hp_max * clamp(hp_frac, 0.05, 1.0)
        self.lives = max(1, int(lives))
        if scale != 1.0:
            self.size *= scale; self.s *= scale
            self.radius = self.base_radius = self.size * 0.17
        if tier == "boss": self.ex = max(self.ex, 0.5)

    def take_damage(self, amount, src, dirx, diry, explosive=False, crit=False):
        m = getattr(src, "mods", None)
        if m:
            if self.tier in ("elite", "boss"): amount *= m.get("vs_elite", 1.0)
            if explosive: amount *= m.get("expl", 1.0)
        return super().take_damage(amount, src, dirx, diry, explosive, crit)

    def finish_getup(self, x, y, heading_from=None):
        super().finish_getup(x, y, heading_from)
        if self.revive_frac:
            self.hp = self.hp_max * self.revive_frac
            self.revive_frac = 0.0

    def update(self, dt):
        B = self.B
        if self.state == "alive":
            rg = self.mods.get("regen", 0.0)
            if rg > 0 and self.hp < self.hp_max:
                self.hp = min(self.hp_max, self.hp + self.hp_max * rg * dt)
            if B.t < self.stun_until and self.tank is None:
                self.flash_t = max(0.0, self.flash_t - dt)
                self.suppression = 1.0
                self.vx = self.vy = 0.0
                self.want_fire = False; self.atk_phase = None
                self.path = []; self.goal = None
                self.play("alert", True)
                return
        self.drive(dt)

    def drive(self, dt):
        Fighter.update(self, dt)


class PlayerFighter(CampaignFighter):
    tier = "ally"

    def __init__(self, battle, entry, team, slot, x, y):
        super().__init__(battle, entry, team, slot, x, y)
        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.dash_dir = (1.0, 0.0)
        self.sense_t = 0.0
        self.aim = AimPoint(self)

    # ------------------------------------------------------------------ who is driving
    def manual_now(self):
        B = self.B
        return (self.manual and self.state == "alive" and self.tank is None and B.phase == "fight"
                and getattr(B, "ctl", None) is not None)

    def set_manual(self, on):
        on = bool(on)
        if on == self.manual: return
        self.manual = on
        self.path = []; self.goal = None; self.face_to = None
        self.target = None; self.want_fire = False; self.target_box = None
        br = self.brain
        if br is not None:
            br.drop_cover()
            br.think_t = 0.0; br.idle_t = 0.0; br.restless = 0.0

    def dash_cooldown(self):
        return max(0.4, BASE["dash_cd"] * self.mods.get("dash_cd", 1.0))

    # ------------------------------------------------------------------ per tick
    def drive(self, dt):
        if not self.manual_now():
            if isinstance(self.target, AimPoint):              # the brain must never be handed the crosshair
                self.target = None; self.want_fire = False
            self.dash_cd = max(0.0, self.dash_cd - dt)
            return Fighter.update(self, dt)
        B = self.B
        ctl = B.ctl
        self.suppression = max(0.0, self.suppression - dt * 0.35)
        self.flash_t = max(0.0, self.flash_t - dt)
        if B.settings["ex_skills"]:
            self.ex = min(1.0, self.ex + dt / self.st.ex_cost * (1.0 + 0.5 * (self.suppression > 0.3)))
        self.dash_cd = max(0.0, self.dash_cd - dt)
        br = self.brain
        self.sense_t -= dt
        if br is not None and self.sense_t <= 0:               # her eyes still feed the team commander
            self.sense_t = 0.2
            try: br.perceive()
            except Exception: pass
        self.path = []; self.goal = None; self.face_to = None; self.target_box = None
        ax, ay = B.cursor()
        tgt = self.pick_aim(ax, ay) if (ctl.lmb and self.ex_cast is None) else None
        self.target = tgt
        self.want_fire = tgt is not None
        if tgt is not None and self.reload_t <= 0:
            self.turn_to(tgt.x, tgt.y, dt, 10)
        if ctl.take("reload"): self.start_reload()
        if ctl.take("ex"): self.request_ex(ax, ay)
        if ctl.take("dash"): self.start_dash(ctl)
        if tgt is not None and self.atk_phase == "end":         # trigger pulled again while the gun was coming down:
            self.atk_phase = None                              # Fighter.act only starts an attack from None
        if self.atk_phase == "start" and self.atk_t > 0.12:    # a player's trigger answers faster than the wind-up clip
            self.atk_phase = "ing"
            self.play("atk_ing", True, fade=0.06, restart=True)
        self.act(dt)

    def pick_aim(self, ax, ay):
        """What a click at (ax, ay) means: an ally to heal (healers), the enemy under the cursor, or the floor."""
        B = self.B
        best, bd = None, self.size * 0.7
        for o in B.fighters:
            if o is self or not o.alive: continue
            if o.team == self.team and not (self.st.healer and o.hp_frac() < 0.995): continue
            d = min(math.hypot(o.x - ax, o.y - ay), math.hypot(o.x - ax, o.y - o.size * 0.5 - ay))
            if o.team == self.team: d *= 0.8                       # healing wins a tie
            if d < bd: best, bd = o, d
        if best is not None: return best
        a = self.aim
        a.x, a.y = ax, ay
        if math.hypot(ax - self.x, ay - self.y) < self.size * 0.35:     # clicking on herself: shoot where she faces
            a.x = self.x + math.cos(self.heading) * self.size; a.y = self.y + math.sin(self.heading) * self.size
        return a

    def request_ex(self, ax, ay):
        B = self.B
        if self.ex < 1.0 or self.want_ex is not None or self.ex_cast is not None or not B.settings["ex_skills"]:
            if self.ex < 1.0: B.toast("EX not ready")
            return
        kind = self.st.ex
        near = B.enemy_near(ax, ay, self.size * 2.5)
        if kind in ("grenade", "strike"):
            reach = self.st.range * self.size * (1.3 if kind == "grenade" else 3.0)
            dx, dy = ax - self.x, ay - self.y
            d = math.hypot(dx, dy)
            if d > reach: ax, ay = self.x + dx / d * reach, self.y + dy / d * reach
            pl = dict(kind=kind, aim=(ax, ay))
        elif kind == "barrage":
            tgt = near or B.enemy_near(self.x, self.y, self.size * 12.0)
            if tgt is None:
                B.toast("No target"); return
            pl = dict(kind=kind, aim=(tgt.x, tgt.y), target=tgt)
        elif kind in ("pierce", "charge"):
            pl = dict(kind=kind, aim=(ax, ay), target=near)
        elif kind == "buff":
            pl = dict(kind=kind, aim=None, target=near)
        else:
            pl = dict(kind=kind)
        self.want_ex = pl

    def start_dash(self, ctl):
        B = self.B
        if self.dash_cd > 0 or self.dash_t > 0 or self.ex_cast is not None: return
        ix, iy = ctl.axis()
        if not (ix or iy): ix, iy = math.cos(self.heading), math.sin(self.heading)
        self.dash_dir = (ix, iy)
        self.dash_t = 0.17
        self.dash_cd = self.dash_cooldown()
        self.invuln_until = max(self.invuln_until, B.t + 0.30)
        B.fx.dust(self.x, self.y, 6)
        B.fx.ring(self.x, self.y, self.size * 0.5, (255, 255, 255), 0.25)
        blast = self.mods.get("dash_blast", 0.0)
        if blast > 0:
            B.explode(self.x, self.y, self.size * 1.25, blast * B.settings["damage"], self)

    def move(self, dt):
        if not self.manual_now():
            return Fighter.move(self, dt)
        B = self.B
        ix, iy = B.ctl.axis()
        speed = self.st.speed * self.size * (0.75 if self.suppression > 0.6 else 1.0)
        busy = self.want_fire or self.reload_t > 0
        dashing = self.dash_t > 0
        if dashing:
            self.dash_t -= dt
            v = self.size * 7.5
            self.vx, self.vy = self.dash_dir[0] * v, self.dash_dir[1] * v
            if random.random() < 0.5: B.fx.dust(self.x, self.y, 1)
        else:
            ks = 0.62 if self.want_fire else (0.85 if self.reload_t > 0 else 1.0)
            k = 1.0 - math.exp(-dt * 14.0)
            self.vx += (ix * speed * ks - self.vx) * k
            self.vy += (iy * speed * ks - self.vy) * k
        for o in B.fighters:                                   # the same shoulder room everyone else keeps
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
        going = sp > speed * 0.2 and (ix != 0 or iy != 0 or dashing)
        if going and not busy:
            want = math.atan2(self.vy, self.vx)
            self.heading = wrap(self.heading + max(-14 * dt, min(14 * dt, wrap(want - self.heading))))
            self.play("run", True, speed=max(0.6, min(1.5, sp / max(1.0, speed))))
            return True
        return False


# ============================================================================== the battle
class CampaignBattle(Battle):
    def __init__(self, mgr, run, door, by_name, settings, manual=True):
        mods = run.mods()
        squad = [m for m in run.living() if m["name"] in by_name]
        foes = [e for e in door["enemies"] if e["name"] in by_name]
        S = dict(settings)
        S.update(lives=max([int(m["lives"]) for m in squad] + [int(e.get("lives", 1)) for e in foes] + [1]),
                 time_limit=0, layout=door.get("layout", "left_right"), speed=1.0, damage=1.0, hp=1.0,
                 friendly_fire=False, ex_skills=True, difficulty=door.get("diff", "veteran"), obstacles=True,
                 down_time=2.0, invuln=1.5)
        ctx = dict(run=run, door=door, mods=mods, specs=[squad, foes])
        super().__init__(mgr, [[by_name[m["name"]] for m in squad], [by_name[e["name"]] for e in foes]], S, campaign=ctx)
        self.run, self.door, self.mods = run, door, mods
        self.ctl = PlayerInput()
        self.pad = None
        self.manual_on = bool(manual)
        self.player = None
        self.kills = 0
        self.loot = 0.0
        self.item_cd = 0.0
        self.toasts = []
        self.started = False
        self.finished = False
        lead = next((f for f in self.fighters if f.team == 0 and f.name == run.leader), None)
        self.set_player(lead or next((f for f in self.fighters if f.team == 0), None))

    # ------------------------------------------------------------------ construction hooks (see Battle)
    def make_fighter(self, entry, team, slot, x, y):
        ctx = self.campaign
        spec = ctx["specs"][team][slot]
        if team == 0:
            f = PlayerFighter(self, entry, team, slot, x, y)
            f.setup("ally", ctx["mods"], hp_frac=spec["hp"], lives=spec["lives"])
        else:
            f = CampaignFighter(self, entry, team, slot, x, y)
            f.setup(spec.get("tier", "grunt"), dict(hp=spec.get("hp", 1.0), dmg=spec.get("dmg", 1.0), ex=spec.get("ex", 1.0)),
                    lives=spec.get("lives", 1), scale=spec.get("scale", 1.0))
        return f

    def make_overlay(self):
        return CampaignOverlay(self)

    def make_hud(self):
        return CampaignHUD(self)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        super().start()
        try:
            self.pad = ControlPad(self)
        except Exception:
            import traceback; traceback.print_exc()
            self.pad = None
        self.sync_pad()

    def stop(self):
        pad, self.pad = self.pad, None
        if pad is not None:
            try:
                pad.hide(); pad.deleteLater()
            except Exception:
                pass
        super().stop()

    def tick(self):
        super().tick()
        self.sync_pad()

    def sync_pad(self):
        """The pad is up exactly while somebody can be driven: manual on, not paused, the fight not over."""
        pad = self.pad
        if pad is None: return
        want = (self.manual_on and not self.paused and not self.result_shown and self.phase in ("intro", "fight")
                and getattr(self, "overlay", None) is not None)
        if want and not pad.isVisible():
            hud = getattr(self, "hud", None)
            pad.show_on(self.home, hud.frameGeometry() if hud is not None else None)
            if hud is not None: hud.raise_()
        elif not want and pad.isVisible():
            pad.hide()

    def focus_pad(self):
        if self.pad is not None and self.pad.isVisible():
            self.pad.grab_focus()

    def step(self, dt):
        if self.phase == "intro": dt *= 1.6                    # rooms come thick and fast: a shorter stand-by
        elif self.phase == "end" and self.phase_t > 1.0: dt *= 2.0
        super().step(dt)
        if self.phase == "fight":
            self.campaign_step(dt)
        for t in self.toasts: t["t"] += dt
        self.toasts = [t for t in self.toasts if t["t"] < t["life"]]

    def campaign_step(self, dt):
        self.item_cd = max(0.0, self.item_cd - dt)
        if not self.started:
            self.started = True
            sh = self.mods.get("start_shield", 0.0)
            if sh > 0:
                for f in self.fighters:
                    if f.team == 0: f.shield_until = max(f.shield_until, self.t + sh)
            d = self.door
            kind = "AREA BOSS" if d["kind"] == "boss" else ("ELITE GUARD" if d.get("elite") else "ENCOUNTER")
            self.banners.append(dict(kind="c_note", text=f"{AREAS[d['area']]['name'].upper()}  \u00b7  {kind}", t=0.0,
                                     life=2.2, color=AREAS[d["area"]]["color"]))
        ctl = self.ctl
        if ctl.take("auto"): self.toggle_manual()
        if ctl.take("swap"): self.swap_player()
        for i in range(4):
            if ctl.take(f"item{i}"): self.use_item(i)
        p = self.player
        if p is None or p.state == "out":
            self.swap_player(silent=True)
        ctl.presses.clear()

    # ------------------------------------------------------------------ rules on top of Battle
    def trace(self, f, *a, **kw):
        bonus = getattr(f, "mods", {}).get("crit", 0.0)
        if bonus: kw["crit_chance"] = kw.get("crit_chance", 0.12) + bonus
        return super().trace(f, *a, **kw)

    def do_ex(self, f, pl):
        S = self.settings
        old = S["damage"]
        S["damage"] = old * getattr(f, "mods", {}).get("dmg", 1.0)      # EX skills ignore the gun's multiplier
        try:
            super().do_ex(f, pl)
        finally:
            S["damage"] = old

    def on_knockdown(self, f, killer):
        super().on_knockdown(f, killer)
        if f.team != 1: return
        if f.state == "out":
            self.kills += 1
            v = self.run.kill_value(getattr(f, "tier", "grunt"))
            self.loot += v
            self.fx.number(f.x, f.y - f.size * 1.3, f"+{int(round(v))} CR", GOLD, 15)
            ls = self.mods.get("lifesteal", 0.0)
            if ls > 0:
                for a in self.fighters:
                    if a.team == 0 and a.alive:
                        got = a.heal_by(a.hp_max * ls)
                        if got > 0: self.fx.heal(a.x, a.y, a.size * 0.8, got)
        elif getattr(f, "tier", "") == "boss":
            self.banners.append(dict(kind="c_note", text=f"{f.name.upper()}  \u00b7  PHASE BREAK", t=0.0, life=1.8,
                                     color=(255, 226, 63)))

    def check_end(self):
        super().check_end()
        if self.phase == "end":
            for b in self.banners:
                if b.get("kind") == "end": b["kind"] = "c_end"
            self.ctl.clear()

    def report(self):
        """What the campaign needs to know about this room once it is over."""
        squad = []
        for f in self.fighters:
            if f.team != 0: continue
            out = f.state == "out"
            hp = f.hp_frac() if f.state == "alive" else (0.0 if out else 0.6)
            squad.append(dict(name=f.name, hp=hp, lives=max(0, f.lives), out=out))
        return dict(win=self.winner == 0, kills=self.kills, credits=self.loot, squad=squad)

    # ------------------------------------------------------------------ the player
    def cursor(self):
        p = QtGui.QCursor.pos()
        l, t, r, b = self.rect
        return min(max(float(p.x()), l), r), min(max(float(p.y()), t), b)

    def toast(self, msg, life=1.6):
        self.toasts = [t for t in self.toasts if t["text"] != msg][-3:]
        self.toasts.append(dict(text=msg, t=0.0, life=life))

    def enemy_near(self, x, y, radius):
        best, bd = None, radius
        for o in self.fighters:
            if o.team != 1 or not o.alive: continue
            d = math.hypot(o.x - x, o.y - y)
            if d < bd: best, bd = o, d
        return best

    def set_player(self, f):
        for o in self.fighters:
            if isinstance(o, PlayerFighter): o.set_manual(False)
        self.player = f
        if f is not None and self.manual_on: f.set_manual(True)

    def toggle_manual(self):
        self.manual_on = not self.manual_on
        self.set_player(self.player)
        self.toast("MANUAL CONTROL" if self.manual_on else "AUTO: her own tactics")
        try:
            self.run.save.d["manual"] = self.manual_on
            self.run.save.save()
        except Exception:
            pass
        self.sync_pad()

    def swap_player(self, silent=False):
        mine = [f for f in self.fighters if f.team == 0 and f.state != "out"]
        if not mine: return
        cur = self.player
        i = mine.index(cur) if cur in mine else -1
        nxt = mine[(i + 1) % len(mine)]
        if nxt is cur: return
        self.set_player(nxt)
        self.fx.ring(nxt.x, nxt.y, nxt.size * 0.8, (255, 226, 63), 0.5)
        if not silent: self.toast(f"Now controlling {nxt.name}")

    # ------------------------------------------------------------------ supplies
    def use_item(self, i):
        lo = self.run.loadout()
        if self.phase != "fight" or self.paused or not (0 <= i < len(lo)) or self.item_cd > 0: return False
        iid = lo[i]
        save = self.run.save
        if save.count(iid) <= 0:
            self.toast(f"{ITEM_BY_ID[iid]['name']}: none left"); return False
        try:
            ok = self.apply_item(iid)
        except Exception:
            import traceback; traceback.print_exc()
            ok = False
        if ok:
            save.use_item(iid)
            self.item_cd = 0.5
            self.toast(f"Used {ITEM_BY_ID[iid]['name']}  ({save.count(iid)} left)")
        return ok

    def _user(self):
        p = self.player
        if p is not None and p.alive: return p
        return next((f for f in self.fighters if f.team == 0 and f.alive), None)

    def _item_aim(self, u):
        if self.manual_on and self.pad is not None and self.pad.isVisible():
            return self.cursor()
        e = self.enemy_near(u.x, u.y, 1e9)
        return (e.x, e.y) if e is not None else None

    def apply_item(self, iid):
        S = self.settings
        sz = self.size
        mine = [f for f in self.fighters if f.team == 0 and f.alive]
        u = self._user()
        if iid == "revive":
            f = next((x for x in self.fighters if x.team == 0 and x.state == "out"), None)
            if f is None:
                self.toast("Nobody to revive"); return False
            f.lives = 1
            f.state = "down"
            f.down_t = float(S["down_time"])
            f.revive_frac = 0.5
            self.fx.ring(f.x, f.y, sz * 1.0, (255, 226, 63), 0.8)
            self.fx.number(f.x, f.y - sz * 1.1, "REVIVE", (255, 226, 63), 17, True)
            return True
        if u is None:
            self.toast("Nobody standing"); return False
        if iid == "medkit":
            t = u if u.hp_frac() < 0.98 else min(mine, key=lambda f: f.hp_frac())
            if t.hp_frac() >= 0.98:
                self.toast("HP already full"); return False
            got = t.heal_by(t.hp_max * 0.5)
            self.fx.heal(t.x, t.y, t.size * 0.8, got)
            self.fx.number(t.x, t.y - t.size * 1.05, f"+{int(got)}", (110, 240, 160), 16)
            return True
        if iid == "rations":
            if all(f.hp_frac() >= 0.98 for f in mine):
                self.toast("HP already full"); return False
            for f in mine:
                got = f.heal_by(f.hp_max * 0.25)
                if got > 0:
                    self.fx.heal(f.x, f.y, f.size * 0.8, got)
                    self.fx.number(f.x, f.y - f.size * 1.05, f"+{int(got)}", (110, 240, 160), 15)
            return True
        if iid == "drink":
            if u.ex >= 1.0:
                self.toast("EX already full"); return False
            u.ex = 1.0
            self.fx.ring(u.x, u.y, sz * 0.8, (255, 226, 63), 0.5)
            return True
        if iid == "barrier":
            for f in mine:
                f.shield_until = max(f.shield_until, self.t + 6.0)
                self.fx.ring(f.x, f.y, sz * 0.9, (120, 200, 255), 0.6)
            return True
        aim = self._item_aim(u)
        if aim is None:
            self.toast("No target"); return False
        ax, ay = aim
        if iid == "frag":
            self.launch(u, "frag", ax, ay, 2600.0 * S["damage"], sz * 1.4)
            return True
        if iid == "flash":
            n = 0
            for e in self.fighters:
                if e.team == 1 and e.alive and math.hypot(e.x - ax, e.y - ay) < sz * 3.6:
                    e.stun_until = self.t + (1.0 if getattr(e, "tier", "") == "boss" else 2.5)
                    e.suppression = 1.0
                    self.fx.number(e.x, e.y - e.size * 1.05, "STUN", (255, 255, 200), 14)
                    n += 1
            self.fx.ring(ax, ay, sz * 3.6, (255, 255, 220), 0.45)
            self.fx.ring(ax, ay, sz * 1.8, (255, 255, 255), 0.3)
            self.fx.shake = getattr(self.fx, "shake", 0) + 4
            return True
        if iid == "beacon":
            for k in range(6):
                ox, oy = random.uniform(-1, 1) * sz * 1.2, random.uniform(-1, 1) * sz * 1.0
                pr = self.launch(u, "shell", ax + ox, ay + oy, 1900.0 * S["damage"], sz * 1.05, delay=0.22 * k)
                pr["h"] = sz * 6; pr["vh"] = -sz * 2
            self.fx.ring(ax, ay, sz * 1.6, (255, 120, 60), 0.9)
            return True
        return False


# ============================================================================== drawing
class CampaignOverlay(ArenaOverlay):
    TIER_COL = {"elite": PURPLE, "boss": YELLOW}

    def paint_field(self, p, now):
        B = self.B
        pl = B.player
        if pl is not None and pl.state in ("alive", "getup") and B.real_t >= pl.visible_t:
            pulse = 0.5 + 0.5 * math.sin(now * 5)
            pen = QtGui.QPen(col(YELLOW, 150 + 90 * pulse), 3.0)
            if not B.manual_on: pen.setDashPattern([3, 3])
            p.setPen(pen); p.setBrush(col(YELLOW, 26))
            p.drawEllipse(QPointF(pl.x, pl.y), pl.radius * 2.0, pl.radius * 1.0)
            if B.manual_on and B.phase == "fight" and pl.alive:
                ax, ay = B.cursor()
                d = math.hypot(ax - pl.x, ay - pl.y)
                if d > pl.size * 0.4:
                    rng = pl.st.range * pl.size
                    k = min(1.0, rng / d)
                    pen = QtGui.QPen(col(YELLOW, 70), 1.6); pen.setDashPattern([4, 5]); pen.setDashOffset(-now * 30)
                    p.setPen(pen)
                    p.drawLine(QPointF(pl.x, pl.y), QPointF(pl.x + (ax - pl.x) * k, pl.y + (ay - pl.y) * k))
        for f in B.fighters:
            c = self.TIER_COL.get(getattr(f, "tier", ""))
            if c is None or f.state not in ("alive", "getup") or B.real_t < f.visible_t: continue
            pen = QtGui.QPen(col(c, 190), 2.4); pen.setDashPattern([2, 3]); pen.setDashOffset(now * 18)
            p.setPen(pen); p.setBrush(col(c, 22))
            p.drawEllipse(QPointF(f.x, f.y), f.radius * 2.2, f.radius * 1.1)
        super().paint_field(p, now)

    def paint_ui(self, p, now):
        super().paint_ui(p, now)
        B = self.B
        g = QRectF(B.home)
        cx = g.center().x()
        for f in B.fighters:
            if f.state != "alive" or B.real_t < f.visible_t: continue
            top = f.y - f.size * OBLIQUE * 1.02 - 26
            tier = getattr(f, "tier", "")
            if tier in ("elite", "boss"):
                r = QRectF(f.x - 28, top - 4, 56, 13)
                p.setPen(NOPEN); p.setBrush(col(self.TIER_COL[tier], 235)); p.drawPolygon(para(r, 4))
                text(p, r, tier.upper(), 8, NAVY_D if tier == "boss" else WHITE, W_BLACK, True, AF.AlignCenter, 0.8)
            if B.t < getattr(f, "stun_until", 0.0):
                text(p, QRectF(f.x - 40, top - 20, 80, 14), "\u2736 STUNNED \u2736", 9, col(YELLOW, 240), W_BLACK, True)
            if f is B.player:
                r = QRectF(f.x - 20, top - 4, 40, 13)
                p.setPen(NOPEN); p.setBrush(col(YELLOW, 240)); p.drawPolygon(para(r, 4))
                text(p, r, "YOU" if B.manual_on else "AUTO", 8, NAVY_D, W_BLACK, True, AF.AlignCenter, 0.8)
                if B.manual_on:                                # dash: a small arc that refills
                    k = 1.0 - clamp(f.dash_cd / max(0.1, f.dash_cooldown()), 0.0, 1.0)
                    cr = QRectF(f.x + 26, top - 6, 16, 16)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QtGui.QPen(col(NAVY_D, 150), 3)); p.drawEllipse(cr)
                    p.setPen(QtGui.QPen(CYAN if k >= 1.0 else col(WHITE, 220), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawArc(cr, 90 * 16, int(-360 * 16 * k))
        self.paint_boss(p, g, now)
        for bn in B.banners:
            k = bn.get("kind")
            if k == "c_end":
                if B.winner == 0:
                    self.strip_banner(p, g, bn["t"], 99, "ROOM CLEAR", "\u5236\u5727\u5b8c\u4e86  \u00b7  the way is open", YELLOW, hold=True)
                else:
                    self.strip_banner(p, g, bn["t"], 99, "SQUAD DOWN", "\u4f5c\u6226\u5931\u6557  \u00b7  the run ends here", RED_T, hold=True)
            elif k == "c_note":
                t = bn["t"]
                a = clamp(min(t * 5, (bn["life"] - t) * 3), 0, 1)
                r = QRectF(cx - 280, g.top() + 128, 560, 36)
                p.save(); p.setOpacity(a)
                p.setPen(NOPEN); p.setBrush(col(NAVY_D, 225)); p.drawPolygon(para(r, 12))
                c = QtGui.QColor(*bn.get("color", (255, 226, 63)))
                p.setBrush(c); p.drawPolygon(para(QRectF(r.left() + 4, r.top(), 10, r.height()), 5))
                text(p, r, bn["text"], 15, WHITE, W_BLACK, True, AF.AlignCenter, 2.0)
                p.restore()
        self.paint_hotbar(p, g, now)
        y = g.bottom() - 150
        for tst in reversed(B.toasts):
            a = clamp(min(tst["t"] * 6, (tst["life"] - tst["t"]) * 3), 0, 1)
            r = QRectF(cx - 190, y, 380, 28)
            p.save(); p.setOpacity(a)
            p.setPen(NOPEN); p.setBrush(col(NAVY_D, 215)); p.drawRoundedRect(r, 14, 14)
            text(p, r, tst["text"], 12, WHITE, W_BLACK, True)
            p.restore()
            y -= 32

    def paint_boss(self, p, g, now):
        B = self.B
        boss = next((f for f in B.fighters if getattr(f, "tier", "") == "boss" and f.in_play), None)
        if boss is None or B.phase == "intro": return
        w = min(560.0, g.width() * 0.4)
        r = QRectF(g.center().x() - w / 2, g.top() + 104, w, 14)
        text(p, QRectF(r.left(), r.top() - 20, w, 18), f"{boss.name}  \u00b7  AREA BOSS", 12, WHITE, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 1.5)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 200)); p.drawPolygon(para(r.adjusted(-3, -3, 3, 3), 5))
        k = boss.hp_frac() if boss.state == "alive" else 0.0
        p.setBrush(col(RED_T, 240)); p.drawPolygon(para(QRectF(r.left(), r.top(), max(1.0, w * k), r.height()), 4))
        for i in range(max(0, boss.lives)):
            cxp = r.right() - 8 - i * 14
            d = QtGui.QPolygonF([QPointF(cxp, r.top() - 16), QPointF(cxp + 5, r.top() - 10), QPointF(cxp, r.top() - 4),
                                 QPointF(cxp - 5, r.top() - 10)])
            p.setPen(QtGui.QPen(WHITE, 1)); p.setBrush(YELLOW); p.drawPolygon(d)

    def paint_hotbar(self, p, g, now):
        B = self.B
        lo = B.run.loadout()
        save = B.run.save
        n = len(lo)
        sw, sh, gap = 62.0, 48.0, 8.0
        pl = B.player
        total = n * sw + max(0, n - 1) * gap + 170
        x = g.center().x() - total / 2
        y = g.bottom() - 96
        # EX + credits block
        r = QRectF(x, y, 160, sh)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 200)); p.drawPolygon(para(r, 10))
        if pl is not None:
            text(p, QRectF(r.left() + 16, r.top() + 3, 130, 16), pl.name, 11, WHITE, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, elide=True)
            bar = QRectF(r.left() + 16, r.top() + 22, 124, 7)
            p.setBrush(col(WHITE, 50)); p.drawRoundedRect(bar, 3, 3)
            p.setBrush(YELLOW if pl.ex >= 1.0 else col(SKY, 230))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * clamp(pl.ex, 0, 1), bar.height()), 3, 3)
            en = pl.st.ex_name[0]
            text(p, QRectF(r.left() + 16, r.top() + 30, 130, 14), ("EX READY: " if pl.ex >= 1.0 else "EX: ") + en, 8,
                 YELLOW if pl.ex >= 1.0 else col(WHITE, 200), W_BOLD, False, AF.AlignLeft | AF.AlignVCenter, elide=True)
        x += 170
        for i, iid in enumerate(lo):
            c = ITEM_BY_ID[iid]
            cnt = save.count(iid)
            r = QRectF(x + i * (sw + gap), y, sw, sh)
            p.setPen(QtGui.QPen(col(WHITE, 200 if cnt else 80), 1.2)); p.setBrush(col(NAVY_D, 205 if cnt else 120))
            p.drawRoundedRect(r, 8, 8)
            hue = QtGui.QColor.fromHsv(int(c["hue"]) % 360, 150, 255)
            text(p, QRectF(r.left(), r.top() + 6, sw, 20), c["tag"], 13, hue if cnt else col(GREY, 200), W_BLACK, True)
            text(p, QRectF(r.left(), r.top() + 26, sw, 16), f"x{cnt}", 11, WHITE if cnt else col(GREY, 200), W_BLACK, True)
            kr = QRectF(r.left() - 4, r.top() - 6, 18, 16)
            p.setPen(NOPEN); p.setBrush(YELLOW); p.drawRoundedRect(kr, 4, 4)
            text(p, kr, str(i + 1), 10, NAVY_D, W_BLACK, False)
        if B.manual_on and B.phase in ("intro", "fight") and B.t < 14.0:
            a = clamp((14.0 - B.t) / 2.0, 0, 1)
            p.save(); p.setOpacity(a)
            hr = QRectF(g.center().x() - 470, g.bottom() - 40, 940, 24)
            p.setPen(NOPEN); p.setBrush(col(NAVY_D, 190)); p.drawRoundedRect(hr, 12, 12)
            text(p, hr, HELP, 10, WHITE, W_BOLD, False)
            p.restore()


class CampaignHUD(ArenaHUD):
    def __init__(self, battle):
        super().__init__(battle)
        self.base_w = 980
        self.setWindowTitle("Campaign HUD")

    def paint_content(self, p, R, now):
        B = self.B
        d = B.door
        area = AREAS[d["area"]]
        ac = QtGui.QColor(*area["color"])
        r = QRectF(R.left() + 10, R.top() + 10, 230, R.height() - 20)
        p.setPen(NOPEN); p.setBrush(ac); p.drawPolygon(para(r, 12))
        step = d["room"] % ROOMS_PER_AREA + 1
        text(p, r.adjusted(16, 2, -12, -r.height() * 0.45), f"AREA {d['area'] + 1}  \u00b7  ROOM {step}/{ROOMS_PER_AREA}", 13,
             WHITE, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.2)
        kind = "BOSS" if d["kind"] == "boss" else ("ELITE  \u00b7  " if d.get("elite") else "") + d.get("title", "")
        text(p, r.adjusted(16, r.height() * 0.45, -12, -2), kind, 11, col(WHITE, 235), W_BOLD, False,
             AF.AlignLeft | AF.AlignVCenter, elide=True)
        mine = sum(1 for f in B.fighters if f.team == 0 and f.in_play)
        foes = sum(1 for f in B.fighters if f.team == 1 and f.in_play)
        tr = QRectF(r.right() + 8, R.top() + 6, 164, R.height() - 12)
        mm, ss = int(B.t // 60), int(B.t % 60)
        text(p, QRectF(tr.left(), tr.top(), tr.width(), tr.height() * 0.58), f"{mm:02d}:{ss:02d}", 24, NAVY, W_BLACK, True)
        ph = {"intro": "STAND BY", "fight": "PAUSED" if B.paused else f"SQUAD {mine}  \u00b7  HOSTILES {foes}",
              "end": "ROOM OVER"}[B.phase]
        text(p, QRectF(tr.left(), tr.top() + tr.height() * 0.56, tr.width(), tr.height() * 0.4), ph, 10, BLUE_D, W_BLACK,
             True, AF.AlignCenter, 1.6)
        cr = QRectF(tr.right() + 6, R.center().y() - 19, 96, 38)
        p.setPen(QtGui.QPen(col(YELLOW_D, 160), 1.2)); p.setBrush(col(WHITE, 250)); p.drawRoundedRect(cr, 9, 9)
        text(p, QRectF(cr.left(), cr.top() + 2, cr.width(), 18), f"+{int(B.loot)}", 14, NAVY, W_BLACK, True)
        text(p, QRectF(cr.left(), cr.top() + 20, cr.width(), 14), "CREDITS", 8, YELLOW_D, W_BLACK, True, AF.AlignCenter, 1.2)
        # supplies (clickable; the number keys do the same while you are in control)
        x = cr.right() + 10
        save = B.run.save
        for i, iid in enumerate(B.run.loadout()[:4]):
            c = ITEM_BY_ID[iid]
            cnt = save.count(iid)
            br = QRectF(x + i * 50, R.center().y() - 19, 44, 38)
            key = ("item", i)
            hov = self.hover == key and cnt > 0
            p.setPen(QtGui.QPen(col(BLUE, 160 if hov else 90), 1.4)); p.setBrush(col(SKY, 255) if hov else col(WHITE, 250 if cnt else 150))
            p.drawRoundedRect(br, 9, 9)
            text(p, QRectF(br.left(), br.top() + 3, br.width(), 18), c["tag"], 10, NAVY if cnt else GREY, W_BLACK, True)
            text(p, QRectF(br.left(), br.top() + 20, br.width(), 14), f"{i + 1}  \u00b7  x{cnt}", 8, BLUE_D if cnt else GREY, W_BLACK, False)
            self.hits.append((br, key))
        bx = R.right() - 10 - 2 * 48 + 8
        mr = QRectF(bx - 112, R.center().y() - 19, 104, 38)
        hov = self.hover == ("auto",)
        on = B.manual_on
        p.setPen(QtGui.QPen(col(YELLOW_D if on else BLUE, 200), 1.4))
        p.setBrush(YELLOW if on else (col(SKY, 255) if hov else col(WHITE, 250)))
        p.drawRoundedRect(mr, 9, 9)
        text(p, QRectF(mr.left(), mr.top() + 3, mr.width(), 18), "MANUAL" if on else "AUTO", 13, NAVY_D if on else NAVY, W_BLACK, True)
        text(p, QRectF(mr.left(), mr.top() + 21, mr.width(), 13), "you drive" if on else "click to drive", 8,
             NAVY if on else BLUE_D, W_BOLD, False)
        self.hits.append((mr, ("auto",)))
        for i, (key, icon) in enumerate(((("pause",), "play" if B.paused else "pause"), (("stop",), "stop"))):
            br = QRectF(bx + i * 48, R.center().y() - 19, 40, 38)
            hov = self.hover == key
            acc = RED if key == ("stop",) else BLUE
            p.setPen(QtGui.QPen(col(acc, 160 if hov else 90), 1.4)); p.setBrush(acc if hov else col(WHITE, 250))
            p.drawRoundedRect(br, 9, 9)
            glyph_icon(p, br.center(), 11, icon, WHITE if hov else acc, 2.6)
            self.hits.append((br, key))

    def on_click(self, key, right=False):
        B = self.B
        k = key[0]
        if k == "item": B.use_item(key[1])
        elif k == "auto": B.toggle_manual()
        elif k == "pause": B.set_paused(not B.paused)
        elif k == "stop":
            self.mgr.pause_menu()
            return
        B.sync_pad()
        B.focus_pad()
