"""Battle VFX in screen space (Blue Archive flavoured): tracers, beams, muzzle flashes, sparks,
explosions with shock rings, heal crosses, shield bubbles, damage numbers, summon beams.

Every effect lives on the floor at (x, y) with an optional height h; it is drawn at
y - h * OBLIQUE like everything else in the arena.
"""
from __future__ import annotations

import math
import random

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

from .obstacles import OBLIQUE
from .theme import NOPEN, W_BLACK, col, font


class Effects:
    def __init__(self):
        self.items = []
        self.shake = 0.0

    def add(self, kind, life, **kw):
        kw.update(kind=kind, life=life, t=0.0)
        self.items.append(kw)
        return kw

    # ---------------------------------------------------------- spawners
    def tracer(self, x0, y0, h0, x1, y1, h1, color, width=2.6, life=0.12, beam=False):
        self.add("beam" if beam else "tracer", life * (3.5 if beam else 1.0), x0=x0, y0=y0 - h0 * OBLIQUE,
                 x1=x1, y1=y1 - h1 * OBLIQUE, c=color, w=width * (2.4 if beam else 1.0))

    def muzzle(self, x, y, h, ang, scale=1.0, color=(255, 220, 120)):
        self.add("muzzle", 0.07, x=x, y=y - h * OBLIQUE, a=ang, s=scale, c=color)

    def sparks(self, x, y, h, color=(255, 220, 140), n=6, speed=160.0):
        for _ in range(n):
            a = random.uniform(0, math.tau); sp = random.uniform(0.3, 1.0) * speed
            self.add("spark", random.uniform(0.15, 0.35), x=x, y=y - h * OBLIQUE, vx=math.cos(a) * sp,
                     vy=math.sin(a) * sp - 40, c=color)

    def hit(self, x, y, h, crit=False):
        self.sparks(x, y, h, (255, 240, 200) if crit else (255, 200, 120), 9 if crit else 5)
        self.add("hitflash", 0.12, x=x, y=y - h * OBLIQUE, s=1.6 if crit else 1.0)

    def explosion(self, x, y, radius):
        self.add("boom", 0.55, x=x, y=y, r=radius)
        self.add("ring", 0.5, x=x, y=y, r=radius * 1.3, c=(255, 200, 120))
        for _ in range(10):
            a = random.uniform(0, math.tau); sp = random.uniform(40, 140)
            self.add("smoke", random.uniform(0.7, 1.3), x=x + math.cos(a) * radius * 0.3,
                     y=y + math.sin(a) * radius * 0.3, vx=math.cos(a) * sp, vy=math.sin(a) * sp * 0.6 - 30,
                     r=radius * random.uniform(0.25, 0.45))
        self.sparks(x, y, 10, (255, 190, 90), 16, 420)
        self.shake = min(14.0, self.shake + radius * 0.08)

    def heal(self, x, y, h, amount):
        for _ in range(5):
            self.add("plus", random.uniform(0.6, 1.0), x=x + random.uniform(-18, 18), y=y - h * OBLIQUE,
                     vy=-random.uniform(40, 80))
        self.add("ring", 0.45, x=x, y=y, r=40, c=(90, 230, 150))

    def heal_beam(self, x0, y0, h0, x1, y1, h1):
        self.add("healbeam", 0.25, x0=x0, y0=y0 - h0 * OBLIQUE, x1=x1, y1=y1 - h1 * OBLIQUE)

    def ring(self, x, y, r, color, life=0.5):
        self.add("ring", life, x=x, y=y, r=r, c=color)

    def summon(self, x, y, color, ch):
        self.add("summon", 0.7, x=x, y=y, c=color, h=ch * 2.2)
        self.add("ring", 0.6, x=x, y=y, r=ch * 0.6, c=color)

    def dust(self, x, y, n=5):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            self.add("smoke", random.uniform(0.4, 0.8), x=x, y=y, vx=math.cos(a) * 60, vy=math.sin(a) * 30,
                     r=random.uniform(6, 12), dust=True)

    def number(self, x, y, txt, color, size=18, crit=False):
        self.add("num", 0.9 if not crit else 1.15, x=x + random.uniform(-10, 10), y=y, txt=txt, c=color,
                 s=size * (1.35 if crit else 1.0), crit=crit)

    def flame(self, x0, y0, h0, ang, length):
        for _ in range(3):
            a = ang + random.uniform(-0.18, 0.18); sp = length * random.uniform(2.0, 3.2)
            self.add("fire", random.uniform(0.25, 0.4), x=x0, y=y0 - h0 * OBLIQUE, vx=math.cos(a) * sp,
                     vy=math.sin(a) * sp, r=random.uniform(6, 11))

    # ---------------------------------------------------------- update / paint
    def update(self, dt):
        keep = []
        for e in self.items:
            e["t"] += dt
            if e["t"] >= e["life"]: continue
            if "vx" in e:
                e["x"] += e["vx"] * dt; e["y"] += e["vy"] * dt
                if e["kind"] == "spark": e["vy"] += 500 * dt
                elif e["kind"] in ("smoke", "fire"): e["vx"] *= math.exp(-2.5 * dt); e["vy"] *= math.exp(-2.5 * dt)
            elif e["kind"] == "plus":
                e["y"] += e["vy"] * dt
            keep.append(e)
        self.items = keep
        self.shake *= math.exp(-8 * dt)

    def paint(self, p, now):
        for e in self.items:
            k = e["kind"]; f = e["t"] / e["life"]; inv = 1.0 - f
            if k == "tracer":
                c = QtGui.QColor(*e["c"]); c.setAlpha(int(255 * inv))
                g = QtGui.QLinearGradient(QPointF(e["x0"], e["y0"]), QPointF(e["x1"], e["y1"]))
                c0 = QtGui.QColor(c); c0.setAlpha(0); g.setColorAt(0, c0); g.setColorAt(0.65, c)
                g.setColorAt(1, QtGui.QColor(255, 255, 255, int(255 * inv)))
                p.setPen(QtGui.QPen(QtGui.QBrush(g), e["w"], Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(e["x0"], e["y0"]), QPointF(e["x1"], e["y1"]))
            elif k == "beam":
                c = QtGui.QColor(*e["c"])
                for w, a in ((e["w"] * 3.2, 50), (e["w"] * 1.6, 120), (e["w"] * 0.6, 255)):
                    cc = QtGui.QColor(c) if w > e["w"] else QtGui.QColor(255, 255, 255)
                    cc.setAlpha(int(a * inv))
                    p.setPen(QtGui.QPen(cc, max(1.0, w * (1.0 - f * 0.6)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawLine(QPointF(e["x0"], e["y0"]), QPointF(e["x1"], e["y1"]))
            elif k == "healbeam":
                pen = QtGui.QPen(QtGui.QColor(110, 240, 170, int(200 * inv)), 4, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
                pen.setDashOffset(-now * 30); p.setPen(pen)
                p.drawLine(QPointF(e["x0"], e["y0"]), QPointF(e["x1"], e["y1"]))
            elif k == "muzzle":
                p.save(); p.translate(e["x"], e["y"]); p.rotate(math.degrees(e["a"]))
                s = e["s"] * 14
                c = QtGui.QColor(*e["c"]); c.setAlpha(int(255 * inv))
                p.setPen(NOPEN); p.setBrush(c)
                p.drawPolygon(QtGui.QPolygonF([QPointF(0, -s * 0.35), QPointF(s * 1.6, 0), QPointF(0, s * 0.35),
                                               QPointF(s * 0.4, 0)]))
                p.setBrush(QtGui.QColor(255, 255, 240, int(230 * inv))); p.drawEllipse(QPointF(s * 0.2, 0), s * 0.35, s * 0.35)
                p.restore()
            elif k == "spark":
                c = QtGui.QColor(*e["c"]); c.setAlpha(int(255 * inv))
                p.setPen(QtGui.QPen(c, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(e["x"], e["y"]), QPointF(e["x"] - e["vx"] * 0.03, e["y"] - e["vy"] * 0.03))
            elif k == "hitflash":
                p.setPen(NOPEN); p.setBrush(QtGui.QColor(255, 255, 255, int(220 * inv)))
                r = 9 * e["s"] * (0.6 + f)
                p.drawEllipse(QPointF(e["x"], e["y"]), r, r)
            elif k == "boom":
                r = e["r"] * (0.4 + 0.8 * math.sqrt(f))
                g = QtGui.QRadialGradient(QPointF(e["x"], e["y"] - r * 0.3), r)
                g.setColorAt(0, QtGui.QColor(255, 255, 220, int(255 * inv)))
                g.setColorAt(0.35, QtGui.QColor(255, 190, 80, int(230 * inv)))
                g.setColorAt(0.75, QtGui.QColor(240, 90, 40, int(150 * inv)))
                g.setColorAt(1, QtGui.QColor(120, 40, 20, 0))
                p.setPen(NOPEN); p.setBrush(g)
                p.drawEllipse(QPointF(e["x"], e["y"] - r * 0.3), r, r * 0.85)
            elif k == "ring":
                c = QtGui.QColor(*e["c"]); c.setAlpha(int(220 * inv))
                p.setPen(QtGui.QPen(c, 3 * inv + 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                r = e["r"] * (0.3 + 0.7 * math.sqrt(f))
                p.drawEllipse(QPointF(e["x"], e["y"]), r, r * 0.55)
            elif k == "smoke":
                a = int((90 if e.get("dust") else 140) * inv)
                c = QtGui.QColor(200, 196, 190, a) if e.get("dust") else QtGui.QColor(70, 66, 70, a)
                p.setPen(NOPEN); p.setBrush(c)
                r = e["r"] * (1 + f)
                p.drawEllipse(QPointF(e["x"], e["y"]), r, r * 0.8)
            elif k == "fire":
                r = e["r"] * (1 + f * 1.5)
                g = QtGui.QRadialGradient(QPointF(e["x"], e["y"]), r)
                g.setColorAt(0, QtGui.QColor(255, 240, 160, int(230 * inv)))
                g.setColorAt(1, QtGui.QColor(255, 90, 20, 0))
                p.setPen(NOPEN); p.setBrush(g); p.drawEllipse(QPointF(e["x"], e["y"]), r, r)
            elif k == "plus":
                c = QtGui.QColor(90, 230, 150, int(255 * inv))
                p.setPen(NOPEN); p.setBrush(c)
                s = 5.0
                p.drawRect(QRectF(e["x"] - s * 0.35, e["y"] - s, s * 0.7, s * 2))
                p.drawRect(QRectF(e["x"] - s, e["y"] - s * 0.35, s * 2, s * 0.7))
            elif k == "summon":
                w = 46 * (1 - f * 0.6)
                g = QtGui.QLinearGradient(QPointF(e["x"] - w / 2, 0), QPointF(e["x"] + w / 2, 0))
                c = QtGui.QColor(e["c"]); c0 = QtGui.QColor(c); c0.setAlpha(0)
                c.setAlpha(int(200 * inv))
                g.setColorAt(0, c0); g.setColorAt(0.5, QtGui.QColor(255, 255, 255, int(230 * inv))); g.setColorAt(1, c0)
                p.fillRect(QRectF(e["x"] - w / 2, e["y"] - e["h"], w, e["h"]), g)
            elif k == "num":
                rise = 34 * math.sqrt(f) + (8 if e["crit"] else 0)
                pop = 1.0 + (0.5 * max(0.0, 1 - f * 6))
                p.save(); p.translate(e["x"], e["y"] - rise); p.scale(pop, pop)
                fnt = font(e["s"], W_BLACK, True)
                path = QtGui.QPainterPath(); path.addText(0, 0, fnt, e["txt"])
                br = path.boundingRect(); path.translate(-br.width() / 2, br.height() / 2)
                a = int(255 * min(1.0, inv * 2.5))
                p.setPen(QtGui.QPen(QtGui.QColor(20, 30, 60, a), 3.2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
                c = QtGui.QColor(*e["c"]); c.setAlpha(a)
                p.setPen(NOPEN); p.setBrush(c); p.drawPath(path)
                p.restore()
