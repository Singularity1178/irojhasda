"""Full-screen click-through overlays: the EX cut-in banner and the shooting effects (ShotFX).

Both draw with the Blue Archive VFX kit in vfx.py. ShotFX keeps its old API (ensure, flash,
fire, step) so older callers still work; the new calls (popup, explode, beam, casing, burst)
are what pet_attack.py uses for the damage numbers, MISS / BLOCK / CRITICAL and the
per-weapon looks (shotgun pellets, sniper / railgun beams, launcher explosions).
"""
from __future__ import annotations

import math
import random
import time
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt

from . import vfx
from .combat_config import SHOOT_BULLET_SPEED
from .mathutil import clamp


def _overlay_flags():
    return (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)


# =============================================================================
#  EX cut-in overlay (full-screen, click-through)
# =============================================================================
class Cutin(QtWidgets.QWidget):
    """The EX skill activation: white flash, the screen dims to BA navy, speed lines
    converge on the student, a halo ring bursts out, and the skewed BA-blue banner with
    halftone dots slides in carrying the EX badge and her name, triangles drifting over it.
    It slides out the other way at the end."""

    def __init__(self):
        super().__init__(None, _overlay_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.active = False; self.t0 = 0.0; self.dur = 2.0; self.anchor = (0, 0); self.who = ""
        self.seed = 0
        self.t_override = None                     # tests / previews can pin the clock

    def start(self, geom, ax, ay, dur, who=""):
        self.setGeometry(geom.x(), geom.y(), geom.width(), geom.height() - 1)
        self.anchor = (ax - geom.x(), ay - geom.y()); self.t0 = time.time(); self.dur = dur
        self.who = (who or "").upper()
        self.seed = random.randint(0, 1 << 30)
        self.active = True; self.show()

    def step(self):
        if time.time() - self.t0 > self.dur: self.active = False; self.hide()
        else: self.update()

    def paintEvent(self, _e):
        if not self.active: return
        p = QtGui.QPainter(self)
        try:
            self.paint_at(p, (time.time() - self.t0) if self.t_override is None else self.t_override)
        finally:
            p.end()

    def paint_at(self, p, t):
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height(); dur = self.dur
        a_in = vfx.ease_out(t / 0.2)
        out_u = vfx.clamp01((t - (dur - 0.38)) / 0.38)
        a = a_in * (1.0 - out_u)
        ax, ay = self.anchor
        # --- backdrop: BA navy dim + vignette ---------------------------------------
        p.fillRect(self.rect(), vfx.qc(vfx.BA_DEEP, 135 * a))
        vg = QtGui.QRadialGradient(ax, ay, max(W, H) * 0.75)
        vg.setColorAt(0.0, vfx.qc(vfx.BA_BLUE, 40 * a)); vg.setColorAt(0.45, vfx.qc(vfx.BA_DEEP, 0))
        vg.setColorAt(1.0, vfx.qc((2, 8, 24), 150 * a))
        p.fillRect(self.rect(), QtGui.QBrush(vg))
        # --- speed lines converging on her ------------------------------------------
        rnd = random.Random(self.seed + int(t * 24))
        p.setPen(vfx.NOPEN)
        for _ in range(54):
            ang = rnd.uniform(0, math.tau); r0 = H * rnd.uniform(0.2, 0.36); r1 = H * rnd.uniform(0.95, 1.5)
            w = rnd.uniform(1.0, 4.5); c, s = math.cos(ang), math.sin(ang)
            poly = QtGui.QPolygonF([QPointF(ax + c * r0, ay + s * r0),
                                    QPointF(ax + c * r1 - s * w * 2.2, ay + s * r1 + c * w * 2.2),
                                    QPointF(ax + c * r1 + s * w * 2.2, ay + s * r1 - c * w * 2.2)])
            p.setBrush(vfx.qc(vfx.WHITE if rnd.random() < 0.7 else vfx.BA_SKY, rnd.uniform(50, 140) * a))
            p.drawPolygon(poly)
        # --- halo burst at her head ---------------------------------------------------
        for i, (delay, rr, col) in enumerate(((0.0, H * 0.34, vfx.WHITE), (0.08, H * 0.26, vfx.BA_SKY), (0.16, H * 0.42, vfx.BA_SKY))):
            u = vfx.clamp01((t - delay) / 0.6)
            if 0 < u < 1:
                p.setBrush(vfx.NOBRUSH); p.setPen(vfx.pen(col, 230 * (1 - u) * a, 6 * (1 - u) + 1))
                R = rr * vfx.ease_out(u); p.drawEllipse(QPointF(ax, ay), R, R)
        # --- the banner ---------------------------------------------------------------
        slide = vfx.ease_out(t / 0.32)
        exit_dx = vfx.ease_out(out_u) * W * 1.5
        cy = max(H * 0.22, min(H * 0.78, ay))
        p.save(); p.translate(W / 2, cy); p.rotate(-8)
        bw, bh = W * 1.8, H * 0.19
        x = -bw / 2 + (1 - slide) * (-W * 1.4) + exit_dx
        band = vfx.para_path(x, -bh / 2, bw, bh, bh * 0.35)
        g = QtGui.QLinearGradient(x, 0, x + bw, 0)
        g.setColorAt(0.0, vfx.qc((10, 70, 190), 0)); g.setColorAt(0.12, vfx.qc(vfx.BA_BLUE, 235 * a))
        g.setColorAt(0.62, vfx.qc((60, 180, 255), 235 * a)); g.setColorAt(1.0, vfx.qc(vfx.BA_SKY, 0))
        p.setPen(vfx.NOPEN); p.fillPath(band, QtGui.QBrush(g))
        p.save(); p.setClipPath(band)
        vfx.halftone(p, QRectF(x + bw * 0.38, -bh / 2, bw * 0.4, bh), vfx.WHITE, 70 * a, step=11, rmax=3.6)
        sh = QtGui.QLinearGradient(0, -bh / 2, 0, bh / 2)                 # gloss on the top half
        sh.setColorAt(0.0, vfx.qc(vfx.WHITE, 70 * a)); sh.setColorAt(0.45, vfx.qc(vfx.WHITE, 0))
        p.fillRect(QRectF(x, -bh / 2, bw + bh, bh), QtGui.QBrush(sh))
        p.restore()
        # white rails above / below, sliding in from the other side
        rx = bw * 0.1 + (1 - slide) * W * 1.2 - exit_dx * 0.6 - bw / 2
        p.setBrush(vfx.qc(vfx.WHITE, 240 * a))
        p.drawPath(vfx.para_path(rx, -bh / 2 - 12, bw * 0.78, 5, 3))
        p.drawPath(vfx.para_path(rx + bw * 0.05, bh / 2 + 7, bw * 0.7, 5, 3))
        p.setBrush(vfx.qc(vfx.BA_SKY, 200 * a))
        p.drawPath(vfx.para_path(rx + bw * 0.3, -bh / 2 - 26, bw * 0.3, 8, 5))
        # triangles drifting over the banner
        tr = random.Random(self.seed)
        for i in range(20):
            sx = tr.uniform(-W * 0.6, W * 0.6) + t * tr.uniform(60, 180) * (1 if i % 2 else -1)
            sy = tr.uniform(-bh * 0.9, bh * 0.9); r = tr.uniform(5, 14)
            vfx.shard(p, sx + exit_dx, sy, r, vfx.WHITE if i % 3 else vfx.BA_SKY, tr.uniform(120, 230) * a,
                      tr.uniform(0, 360) + t * tr.uniform(-120, 120), outline=(i % 4 == 0))
        # text: EX badge + her name + subtitle
        tslide = vfx.ease_out((t - 0.06) / 0.34)
        tx = -W * 0.32 + (1 - tslide) * W * 0.7 + exit_dx * 1.1
        pop = vfx.ease_back((t - 0.12) / 0.3, 2.2)
        p.save(); p.translate(tx, -bh * 0.02); p.scale(max(0.01, pop), max(0.01, pop))
        bx, bwid, bht = -bh * 0.75, bh * 0.68, bh * 0.5
        p.setBrush(vfx.qc(vfx.WHITE, 255 * a)); p.drawPath(vfx.para_path(bx, -bht * 0.65, bwid, bht, bht * 0.3))
        ef = vfx.ba_font(bht * 0.7); ep, _w, _a = vfx.text_path("EX", ef, bx + bwid * 0.57, bht * 0.12)
        p.fillPath(ep, vfx.qc(vfx.BA_BLUE, 255 * a))
        p.restore()
        name = self.who or "EX SKILL"
        f1 = vfx.ba_font(H * 0.085)
        fm = QtGui.QFontMetricsF(f1)
        path = QtGui.QPainterPath(); path.addText(tx, bh * 0.1, f1, name)
        p.strokePath(path, vfx.pen((8, 40, 120), 255 * a, 10))
        p.fillPath(path, vfx.qc(vfx.WHITE, 255 * a))
        f2 = vfx.ba_font(H * 0.026)
        sub = QtGui.QPainterPath(); sub.addText(tx + 10, bh * 0.36, f2, "EX SKILL  \u25b6  ACTIVATE")
        p.strokePath(sub, vfx.pen(vfx.BA_NAVY, 220 * a, 4)); p.fillPath(sub, vfx.qc((225, 245, 255), 255 * a))
        # twinkles along the name
        for i in range(5):
            k = (math.sin(t * 9 + i * 1.7) + 1) * 0.5
            vfx.sparkle(p, tx + fm.horizontalAdvance(name) * (0.1 + 0.2 * i), -bh * 0.3 + (i % 2) * bh * 0.55,
                        5 + 7 * k, vfx.WHITE, 255 * a * k, i * 20)
        p.restore()
        if t < 0.14:
            p.fillRect(self.rect(), vfx.qc(vfx.WHITE, 220 * (1 - t / 0.14)))


# =============================================================================
#  Shooting effects overlay
# =============================================================================
class ShotFX(QtWidgets.QWidget):
    """Full-screen, click-through overlay for the shooting event.

    Draws the tracers, muzzle flashes, smoke, brass, impact sparks, explosions, beams and the
    floating combat text. Everything is in GLOBAL screen coordinates; paintEvent shifts by the
    window origin. A bullet carries an optional callback that runs the moment it arrives, which
    is how a hit student finds out she was hit.
    """
    MAX_FX = 260

    def __init__(self):
        super().__init__(None, _overlay_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.active = False; self.bullets = []; self.fx = []; self.geo = None
        self.fancy = True                   # pet_attack mirrors cfg["ba_vfx"] here

    def ensure(self, geom):
        if self.geo != geom:
            self.geo = QtCore.QRect(geom)
            self.setGeometry(geom.x(), geom.y(), geom.width(), geom.height() - 1)
        if not self.isVisible(): self.show()
        self.active = True

    def _add(self, **f):
        f.setdefault("t", 0.0)
        self.fx.append(f)
        if len(self.fx) > self.MAX_FX: self.fx = self.fx[-self.MAX_FX:]

    # ---- spawners -------------------------------------------------------------------
    def flash(self, x, y, ang=None, size=1.0, tint=None, smoke=True):
        """Muzzle flash. ang = barrel direction (rad); None = an old-style round flash."""
        tint = tuple(tint) if tint else (255, 220, 120)
        self._add(kind="flash", x=x, y=y, life=0.06 + 0.035 * size, ang=ang, size=size, tint=tint)
        if smoke and self.fancy:
            dx, dy = (math.cos(ang), math.sin(ang)) if ang is not None else (0.0, -1.0)
            for i in range(2 if size < 1.3 else 4):
                self._add(kind="smoke", x=x + dx * 8 * i, y=y + dy * 8 * i, life=random.uniform(0.45, 0.8),
                          vx=dx * random.uniform(30, 70) + random.uniform(-15, 15), vy=dy * 40 - random.uniform(20, 50),
                          r=random.uniform(6, 10) * size)

    def casing(self, x, y, side=1):
        """Brass flicking out of the ejection port, falling with a spin."""
        if not self.fancy: return
        self._add(kind="casing", x=x, y=y, life=0.75, vx=-side * random.uniform(80, 170), vy=-random.uniform(200, 300),
                  rot=random.uniform(0, 360), w=random.uniform(500, 1100) * random.choice([-1, 1]))

    def popup(self, x, y, text, kind="normal", scale=1.0):
        """Floating combat text (damage / CRITICAL / MISS / BLOCK). Stacks upward when several
        land on the same spot within a moment, like the game does."""
        x += random.uniform(-16, 16); y += random.uniform(-6, 6)
        for f in self.fx:
            if f["kind"] == "text" and f["t"] < 0.25 and abs(f["x"] - x) < 60 and abs(f["y"] - y) < 26:
                y = f["y"] - 26 * scale
        self._add(kind="text", x=x, y=y, text=str(text), style=kind, scale=scale,
                  life=1.15 if kind == "crit" else 0.95)

    def explode(self, x, y, size=1.0):
        self._add(kind="explosion", x=x, y=y, size=size, life=0.7 + 0.25 * size, seed=random.randint(0, 1 << 30))
        self._add(kind="spark", x=x, y=y, life=0.32, size=size * 1.2, tint=(255, 236, 190),
                  rays=[(random.uniform(0, math.tau), random.uniform(30, 70) * size) for _ in range(12)])

    def burst(self, x, y, size=1.6, tint=(255, 236, 170)):
        """A big knock-down hit: oversized spark + ring of shards."""
        self._add(kind="spark", x=x, y=y, life=0.42, size=size, tint=tint,
                  rays=[(random.uniform(0, math.tau), random.uniform(24, 60) * size) for _ in range(14)])
        self._add(kind="ring", x=x, y=y, life=0.45, size=70 * size, tint=tint)

    def beam(self, x0, y0, x1, y1, width=6.0, color=(255, 246, 205), life=0.4):
        self._add(kind="beam", x=x0, y=y0, x1=x1, y1=y1, width=width, tint=tuple(color), life=life,
                  seed=random.randint(0, 1 << 30))

    def fire(self, x0, y0, x1, y1, impact="spark", cb=None, style=None, weapon=None):
        """One round from (x0, y0) to (x1, y1).
        style   optional dict from a character profile's `bullet` (speed, color, width, trail, impact_size).
        weapon  weapon_type from combat_index.json; picks the per-weapon look (see vfx.WEAPON_FX)."""
        st = vfx.weapon_fx(weapon, style)
        d = max(1.0, math.hypot(x1 - x0, y1 - y0))
        spd = float(st.get("speed", SHOOT_BULLET_SPEED))
        self.bullets.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, t=0.0, dur=max(0.03, d / max(1.0, spd)),
                                 d=d, impact=impact, cb=cb, style=st))
        if st.get("beam") and self.fancy:
            self.beam(x0, y0, x1, y1, st.get("beam_width", 6.0), st.get("color", (255, 246, 205)), st.get("beam_life", 0.4))
        n = int(st.get("pellets", 0)) if self.fancy else 0
        if n > 1:                                         # shotgun: the rest of the pellets (cosmetic)
            base = math.atan2(y1 - y0, x1 - x0); spread = float(st.get("spread", 0.08))
            pst = dict(st); pst["pellets"] = 0; pst["spark"] = st.get("spark", 0.7) * 0.6
            for _ in range(n - 1):
                ang = base + random.uniform(-spread, spread); dd = d * random.uniform(0.82, 1.06)
                ex, ey = x0 + math.cos(ang) * dd, y0 + math.sin(ang) * dd
                self.bullets.append(dict(x0=x0, y0=y0, x1=ex, y1=ey, t=random.uniform(-0.02, 0.0),
                                         dur=max(0.03, dd / max(1.0, spd)), d=dd, impact="pellet", cb=None, style=pst))

    # ---- simulation -----------------------------------------------------------------
    def step(self, dt):
        for b in self.bullets:
            b["t"] += dt
        done = [b for b in self.bullets if b["t"] >= b["dur"]]
        self.bullets = [b for b in self.bullets if b["t"] < b["dur"]]
        for b in done:
            st = b.get("style") or {}
            if b["impact"] == "hole":
                self._add(kind="hole", x=b["x1"], y=b["y1"], life=2.4)
            big = float(st.get("impact_size", 1.0)) * float(st.get("spark", 1.0))
            if st.get("explosion") and self.fancy:
                self.explode(b["x1"], b["y1"], clamp(0.55 * float(st.get("impact_size", 1.6)), 0.6, 1.6))
            else:
                nr = int((5 if b["impact"] == "pellet" else 9) * min(2.2, big)) if self.fancy else int(9 * big)
                self._add(kind="spark", x=b["x1"], y=b["y1"], life=0.3 * min(2.0, max(0.6, big)), size=big,
                          tint=tuple(st.get("tint", (255, 214, 110))),
                          rays=[(random.uniform(0, math.tau), random.uniform(10, 34) * big) for _ in range(max(3, nr))])
            if b["cb"] is not None:
                try: b["cb"]()
                except Exception: traceback.print_exc()
        for f in self.fx:
            f["t"] += dt
            k = f["kind"]
            if k == "smoke":
                f["x"] += f["vx"] * dt; f["y"] += f["vy"] * dt
                f["vx"] *= math.exp(-2.2 * dt); f["vy"] = f["vy"] * math.exp(-1.5 * dt) - 12 * dt
            elif k == "casing":
                f["x"] += f["vx"] * dt; f["y"] += f["vy"] * dt; f["vy"] += 1400 * dt; f["rot"] += f["w"] * dt
        self.fx = [f for f in self.fx if f["t"] < f["life"]]
        if not self.bullets and not self.fx:
            self.active = False; self.hide()
        else:
            self.update()

    # ---- drawing --------------------------------------------------------------------
    def paintEvent(self, _e):
        if not self.active: return
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            p.translate(-self.x(), -self.y())
            self.paint_fx(p)
        finally:
            p.end()

    def paint_fx(self, p):
        order = ("smoke", "hole", "ring", "beam", "explosion", "spark", "flash", "casing")
        by = {k: [] for k in order}
        texts = []
        for f in self.fx:
            if f["kind"] == "text": texts.append(f)
            elif f["kind"] in by: by[f["kind"]].append(f)
        for f in by["smoke"]:
            u = f["t"] / f["life"]
            vfx.smoke_puff(p, f["x"], f["y"], f["r"] * (1 + 1.6 * u), 120 * (1 - u))
        for f in by["hole"]:
            vfx.bullet_hole(p, f["x"], f["y"], 1.0 - f["t"] / f["life"])
        for f in by["ring"]:
            u = f["t"] / f["life"]; k = 1 - u; R = f["size"] * vfx.ease_out(u)
            p.setBrush(vfx.NOBRUSH); p.setPen(vfx.pen(f["tint"], 230 * k, 5 * k + 0.5)); p.drawEllipse(QPointF(f["x"], f["y"]), R, R)
        for f in by["beam"]:
            vfx.beam(p, f["x"], f["y"], f["x1"], f["y1"], f["t"] / f["life"], f["width"], f["tint"], f["seed"])
        for b in self.bullets:
            if b["t"] < 0: continue
            u = clamp(b["t"] / b["dur"], 0.0, 1.0)
            ux, uy = (b["x1"] - b["x0"]) / b["d"], (b["y1"] - b["y0"]) / b["d"]
            hx, hy = b["x0"] + (b["x1"] - b["x0"]) * u, b["y0"] + (b["y1"] - b["y0"]) * u
            st = b.get("style") or {}
            tl = min(float(st.get("trail", 170.0)), b["d"] * u)
            vfx.tracer(p, hx, hy, ux, uy, tl, float(st.get("width", 3.4)), tuple(st.get("color", (255, 190, 70))),
                       shell=bool(st.get("shell")))
        for f in by["explosion"]:
            vfx.explosion(p, f["x"], f["y"], f["t"] / f["life"], f["size"], f["seed"], f["life"])
        for f in by["spark"]:
            vfx.hit_spark(p, f["x"], f["y"], f["t"] / f["life"], f.get("size", 1.0), f.get("tint", (255, 214, 110)), f["rays"])
        for f in by["flash"]:
            vfx.muzzle_flash(p, f["x"], f["y"], f.get("ang"), 1.0 - f["t"] / f["life"], f.get("size", 1.0), f.get("tint"))
        for f in by["casing"]:
            vfx.casing(p, f["x"], f["y"], f["rot"], 255 * min(1.0, (1 - f["t"] / f["life"]) * 3))
        for f in texts:
            vfx.damage_text(p, f["x"], f["y"], f["text"], f["t"] / f["life"], f["style"], f.get("scale", 1.0))
