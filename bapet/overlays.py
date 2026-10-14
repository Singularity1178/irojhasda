"""Full-screen click-through overlays: the EX cut-in banner and the shooting tracers (ShotFX)."""
from __future__ import annotations

import math
import random
import time
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt

from .combat_config import SHOOT_BULLET_SPEED
from .mathutil import clamp


# =============================================================================
#  EX cut-in overlay (full-screen, click-through)
# =============================================================================
class Cutin(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.active = False; self.t0 = 0.0; self.dur = 2.0; self.anchor = (0, 0); self.who = ""

    def start(self, geom, ax, ay, dur, who=""):
        self.setGeometry(geom.x(), geom.y(), geom.width(), geom.height() - 1)
        self.anchor = (ax - geom.x(), ay - geom.y()); self.t0 = time.time(); self.dur = dur
        self.who = (who or "").upper()
        self.active = True; self.show()

    def step(self):
        if time.time() - self.t0 > self.dur: self.active = False; self.hide()
        else: self.update()

    def paintEvent(self, _e):
        if not self.active: return
        t = time.time() - self.t0
        W, H = self.width(), self.height()
        a = min(1.0, t / 0.18) * min(1.0, max(0.0, (self.dur - t) / 0.35))
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(4, 14, 40, int(125 * a)))
        ax, ay = self.anchor
        rnd = random.Random(int(t * 24))
        for _ in range(46):                                    # speed lines
            ang = rnd.uniform(0, math.tau); r0 = H * rnd.uniform(0.22, 0.4); r1 = H * rnd.uniform(0.7, 1.3)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, int(rnd.uniform(40, 120) * a)), rnd.uniform(1, 3)))
            p.drawLine(QPointF(ax + math.cos(ang) * r0, ay + math.sin(ang) * r0),
                       QPointF(ax + math.cos(ang) * r1, ay + math.sin(ang) * r1))
        slide = 1 - (1 - min(1.0, t / 0.30)) ** 3
        p.save(); p.translate(W / 2, max(H * 0.2, min(H * 0.8, ay))); p.rotate(-9)
        bw, bh = W * 1.7, H * 0.17
        x = -bw / 2 + (1 - slide) * (-W * 1.3)
        g = QtGui.QLinearGradient(x, 0, x + bw, 0)
        g.setColorAt(0.0, QtGui.QColor(10, 70, 190, 0)); g.setColorAt(0.15, QtGui.QColor(18, 120, 255, int(225 * a)))
        g.setColorAt(0.75, QtGui.QColor(70, 200, 255, int(225 * a))); g.setColorAt(1.0, QtGui.QColor(70, 200, 255, 0))
        p.fillRect(QRectF(x, -bh / 2, bw, bh), QtGui.QBrush(g))
        for yy, hh in ((-bh / 2 - 7, 4), (bh / 2 + 3, 4)):
            p.fillRect(QRectF(x + bw * 0.1, yy, bw * 0.8, hh), QtGui.QColor(255, 255, 255, int(235 * a)))
        f1 = QtGui.QFont("Arial Black"); f1.setPixelSize(int(H * 0.085)); f1.setItalic(True); f1.setBold(True)
        tx = -W * 0.30 + (1 - slide) * W * 0.6
        path = QtGui.QPainterPath(); path.addText(tx, bh * 0.08, f1, "EX SKILL")
        p.strokePath(path, QtGui.QPen(QtGui.QColor(8, 40, 120, int(255 * a)), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.fillPath(path, QtGui.QColor(255, 255, 255, int(255 * a)))
        f2 = QtGui.QFont("Arial"); f2.setPixelSize(int(H * 0.03)); f2.setBold(True); f2.setItalic(True)
        p.setFont(f2); p.setPen(QtGui.QColor(225, 245, 255, int(255 * a)))
        p.drawText(QPointF(tx + 8, bh * 0.40), self.who or "EX SKILL")
        p.restore()
        if t < 0.14:
            p.fillRect(self.rect(), QtGui.QColor(255, 255, 255, int(200 * (1 - t / 0.14))))
        p.end()


class ShotFX(QtWidgets.QWidget):
    """Full-screen, click-through overlay for the shooting event.

    Draws the tracers, muzzle flashes and impact sparks. Everything is in GLOBAL screen coordinates; paintEvent shifts
    by the window origin. A bullet carries an optional callback that runs the
    moment it arrives, which is how a hit student finds out she was hit.
    """
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.active = False; self.bullets = []; self.fx = []; self.geo = None

    def ensure(self, geom):
        if self.geo != geom:
            self.geo = QtCore.QRect(geom)
            self.setGeometry(geom.x(), geom.y(), geom.width(), geom.height() - 1)
        if not self.isVisible(): self.show()
        self.active = True

    def flash(self, x, y):
        self.fx.append(dict(kind="flash", x=x, y=y, t=0.0, life=0.09))

    def fire(self, x0, y0, x1, y1, impact="spark", cb=None, style=None):
        """style: optional dict from a character profile's `bullet` (speed, color, width, trail, impact_size)."""
        d = max(1.0, math.hypot(x1 - x0, y1 - y0))
        spd = float((style or {}).get("speed", SHOOT_BULLET_SPEED))
        self.bullets.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, t=0.0, dur=max(0.03, d / max(1.0, spd)),
                                 d=d, impact=impact, cb=cb, style=style))

    def step(self, dt):
        for b in self.bullets:
            b["t"] += dt
        done = [b for b in self.bullets if b["t"] >= b["dur"]]
        self.bullets = [b for b in self.bullets if b["t"] < b["dur"]]
        for b in done:
            if b["impact"] == "hole":
                self.fx.append(dict(kind="hole", x=b["x1"], y=b["y1"], t=0.0, life=2.4))
            big = float((b.get("style") or {}).get("impact_size", 1.0))
            self.fx.append(dict(kind="spark", x=b["x1"], y=b["y1"], t=0.0, life=0.28 * min(2.0, big),
                                rays=[(random.uniform(0, math.tau), random.uniform(10, 34) * big)
                                      for _ in range(int(9 * big))]))
            if b["cb"] is not None:
                try: b["cb"]()
                except Exception: traceback.print_exc()
        for f in self.fx: f["t"] += dt
        self.fx = [f for f in self.fx if f["t"] < f["life"]]
        if not self.bullets and not self.fx:
            self.active = False; self.hide()
        else:
            self.update()

    def paintEvent(self, _e):
        if not self.active: return
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.translate(-self.x(), -self.y())
        for f in self.fx:
            k = 1.0 - f["t"] / f["life"]
            x, y = f["x"], f["y"]
            if f["kind"] == "flash":
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(255, 230, 140, int(230 * k)))
                p.drawEllipse(QPointF(x, y), 15 * k + 4, 15 * k + 4)
                p.setBrush(QtGui.QColor(255, 255, 255, int(255 * k)))
                p.drawEllipse(QPointF(x, y), 6 * k + 2, 6 * k + 2)
            elif f["kind"] == "spark":
                p.setPen(QtGui.QPen(QtGui.QColor(255, 220, 120, int(255 * k)), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                for ang, ln in f["rays"]:
                    r0 = ln * (1 - k) * 0.6; r1 = ln * (1.1 - k * 0.5)
                    p.drawLine(QPointF(x + math.cos(ang) * r0, y + math.sin(ang) * r0),
                               QPointF(x + math.cos(ang) * r1, y + math.sin(ang) * r1))
            else:                                               # bullet hole on the cursor
                a = int(200 * min(1.0, k * 2.0))
                p.setBrush(QtGui.QColor(20, 20, 24, a)); p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, a // 2), 1.2))
                p.drawEllipse(QPointF(x, y), 4.5, 4.5)
                p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 24, a), 1.2))
                for ang in (0.4, 1.9, 3.4, 5.0):
                    p.drawLine(QPointF(x + math.cos(ang) * 5, y + math.sin(ang) * 5),
                               QPointF(x + math.cos(ang) * 11, y + math.sin(ang) * 11))
        for b in self.bullets:
            u = clamp(b["t"] / b["dur"], 0.0, 1.0)
            ux, uy = (b["x1"] - b["x0"]) / b["d"], (b["y1"] - b["y0"]) / b["d"]
            hx, hy = b["x0"] + (b["x1"] - b["x0"]) * u, b["y0"] + (b["y1"] - b["y0"]) * u
            st = b.get("style") or {}
            tl = min(float(st.get("trail", 170.0)), b["d"] * u)
            tail = QPointF(hx - ux * tl, hy - uy * tl); head = QPointF(hx, hy)
            gr, gg, gb = st.get("color", (255, 190, 70)); wd = float(st.get("width", 5.0))
            p.setPen(QtGui.QPen(QtGui.QColor(gr, gg, gb, 130), wd, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(tail, head)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 250, 225, 240), max(2.2, wd * 0.44), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(hx - ux * tl * 0.6, hy - uy * tl * 0.6), head)
            if st:                                              # a shell has a visible round nose
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(255, 245, 210, 255))
                p.drawEllipse(head, wd * 0.9, wd * 0.9)
        p.end()
