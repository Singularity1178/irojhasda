"""Spawnable cover for the arena: what exists, where it goes, and how it is drawn.

Layout is mirrored for fairness - whatever one team gets on its side, the other gets on its
own (mirror axis follows the spawn layout). Every prop is an axis-aligned Box on the floor with a
height, drawn with the same oblique projection the students are rendered with (height goes up
the screen by OBLIQUE px per px), so a student standing behind a crate is hidden by its front.

    crate      wooden supply crate       full cover, breakable
    sandbags   sandbag wall              half cover: shots over it often hit the bags
    barrier    concrete jersey barrier   full cover, unbreakable
    barrel     red fuel barrel           full cover, EXPLODES when shot up
    vending    Kivotos vending machine   tall full cover, very tough
    container  shipping container        big full cover, unbreakable
"""
from __future__ import annotations

import math
import random

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

from .geometry import Box
from .theme import NOPEN, col

OBLIQUE = 0.8          # screen px up per px of height (the camera's shear; topdown.py uses the same)

KINDS = {
    "crate":     dict(w=0.56, d=0.56, h=0.52, cover="full", hp=4200, weight=4),
    "sandbags":  dict(w=1.30, d=0.38, h=0.32, cover="half", hp=None, weight=4),
    "barrier":   dict(w=1.45, d=0.32, h=0.46, cover="full", hp=None, weight=3),
    "barrel":    dict(w=0.36, d=0.36, h=0.44, cover="full", hp=650, weight=2, explosive=True),
    "vending":   dict(w=0.62, d=0.44, h=0.98, cover="full", hp=9000, weight=1),
    "container": dict(w=1.80, d=0.78, h=0.78, cover="full", hp=None, weight=1),
}
COUNTS = {"few": 4, "normal": 7, "many": 11}       # per side (mirrored)


def spawn_points(rect, n, team, layout, ch, rng):
    """Feet positions for n students of a team, plus the team's 'home' point."""
    l, t, r, b = rect
    W, H = r - l, b - t
    m = ch * 0.9
    if layout == "top_bottom":
        y = t + m + ch * 0.4 if team == 0 else b - m
        xs = [l + W * (k + 1) / (n + 1) for k in range(n)]
        pts = [(x, y + (rng.uniform(-0.3, 0.3) * ch)) for x in xs]
        home = (l + W / 2, y)
    elif layout == "corners":
        cx, cy = (l + m * 1.6, t + m * 1.6) if team == 0 else (r - m * 1.6, b - m * 1.4)
        pts = []
        for k in range(n):
            a = k * 2.399 + (0 if team == 0 else math.pi)
            rr = ch * 0.75 * math.sqrt(k + 0.5)
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.8))
        home = (cx, cy)
    elif layout == "scattered":
        pts = []
        for k in range(n):
            x = rng.uniform(l + m, l + W * 0.4) if team == 0 else rng.uniform(l + W * 0.6, r - m)
            pts.append((x, rng.uniform(t + m + ch * 0.4, b - m)))
        home = (l + W * 0.2, t + H / 2) if team == 0 else (l + W * 0.8, t + H / 2)
    else:
        x = l + m if team == 0 else r - m
        ys = [t + ch * 0.6 + (H - ch * 0.6) * (k + 1) / (n + 1) for k in range(n)]
        pts = [(x + rng.uniform(0, 0.5) * ch * (1 if team == 0 else -1), y) for y in ys]
        home = (x, t + H / 2)
    pts = [(min(max(px, l + m * 0.6), r - m * 0.6), min(max(py, t + ch * 0.9), b - m * 0.5)) for px, py in pts]
    return pts, home


def generate(rect, ch, layout, amount, barrels, blocked, keep_clear, seed=None):
    """List of Box. `blocked`: rects to stay out of (windows). `keep_clear`: (x, y, radius) spawn zones."""
    rng = random.Random(seed)
    l, t, r, b = rect
    cxm, cym = (l + r) / 2, (t + b) / 2
    kinds = [k for k in KINDS if barrels or k != "barrel"]
    weights = [KINDS[k]["weight"] for k in kinds]
    out = []

    def mirror(x, y):
        if layout == "top_bottom": return x, 2 * cym - y
        if layout in ("corners", "scattered"): return 2 * cxm - x, 2 * cym - y
        return 2 * cxm - x, y

    def fits(bl, bt, br, bb, pad):
        if bl < l + ch * 0.5 or br > r - ch * 0.5 or bt < t + ch * 1.0 or bb > b - ch * 0.4: return False
        for o in out:
            if bl - pad < o.r and br + pad > o.l and bt - pad < o.b and bb + pad > o.t: return False
        for (wl, wt, wr, wb) in blocked:
            if bl - ch * 0.5 < wr and br + ch * 0.5 > wl and bt - ch * 0.5 < wb and bb + ch * 0.5 > wt: return False
        for (kx, ky, kr) in keep_clear:
            nx, ny = min(max(kx, bl), br), min(max(ky, bt), bb)
            if math.hypot(kx - nx, ky - ny) < kr: return False
        return True

    def make(kind, x, y, vertical, seed_):
        k = KINDS[kind]
        w, d = k["w"] * ch, k["d"] * ch
        if vertical and kind not in ("vending", "barrel", "crate"): w, d = d, w
        return Box(x - w / 2, y - d / 2, x + w / 2, y + d / 2, kind, k["h"] * ch, k["cover"], k["hp"], seed=seed_)

    n = COUNTS.get(amount, 7)
    tries = 0
    placed = 0
    vert_bias = 0.7 if layout in ("left_right", "scattered", "corners") else 0.25
    while placed < n and tries < 400:
        tries += 1
        kind = rng.choices(kinds, weights)[0]
        if layout == "top_bottom":
            x = rng.uniform(l + ch, r - ch); y = rng.uniform(t + (b - t) * 0.22, cym - ch * 0.35)
        else:
            x = rng.uniform(l + (r - l) * 0.14, cxm - ch * 0.35); y = rng.uniform(t + ch * 1.2, b - ch * 0.8)
        vertical = rng.random() < vert_bias
        s = rng.randint(0, 1 << 20)
        a = make(kind, x, y, vertical, s)
        mx, my = mirror(x, y)
        bm = make(kind, mx, my, vertical, s ^ 0x5a5a)
        pad = ch * 0.85
        if not fits(a.l, a.t, a.r, a.b, pad) or not fits(bm.l, bm.t, bm.r, bm.b, pad): continue
        if a.l < bm.r + pad and a.r + pad > bm.l and a.t < bm.b + pad and a.b + pad > bm.t: continue
        out.append(a); out.append(bm); placed += 1
        # little clusters: a barrel or a crate tucked next to a wall
        if kind in ("barrier", "container", "sandbags") and rng.random() < 0.45 and placed < n:
            extra = "barrel" if (barrels and rng.random() < 0.5) else "crate"
            ox = (a.r + ch * 0.32) if rng.random() < 0.5 else (a.l - ch * 0.32)
            oy = a.b - KINDS[extra]["d"] * ch * 0.5
            e1 = make(extra, ox, oy, False, s + 7)
            ex, ey = mirror(ox, oy)
            e2 = make(extra, ex, ey, False, (s + 7) ^ 0x5a5a)
            if fits(e1.l, e1.t, e1.r, e1.b, ch * 0.05) and fits(e2.l, e2.t, e2.r, e2.b, ch * 0.05):
                out.append(e1); out.append(e2)
    # sometimes one big piece of cover in the middle of the map
    if rng.random() < 0.6:
        kind = rng.choice(["container", "barrier", "vending"])
        c = make(kind, cxm, cym, layout != "top_bottom", rng.randint(0, 1 << 20))
        if fits(c.l, c.t, c.r, c.b, ch * 0.9): out.append(c)
    return out


# ============================================================================== painting
def _faces(bx):
    hk = bx.height * OBLIQUE
    top = QRectF(bx.l, bx.t - hk, bx.r - bx.l, bx.b - bx.t)
    front = QRectF(bx.l, bx.b - hk, bx.r - bx.l, hk)
    return top, front, hk


def paint_shadow(p, bx):
    p.setPen(NOPEN); p.setBrush(QtGui.QColor(10, 20, 40, 46))
    p.drawRoundedRect(QRectF(bx.l + 4, bx.t + 3, bx.r - bx.l + 6, bx.b - bx.t + 5), 6, 6)


def paint_box(p, bx, now):
    if not bx.alive:
        _paint_debris(p, bx); return
    kind = bx.kind
    if kind == "barrel":
        _paint_barrel(p, bx, now); return
    top, front, hk = _faces(bx)
    pal = {
        "crate": ((214, 160, 96), (168, 112, 58), (120, 78, 38)),
        "sandbags": ((214, 198, 150), (176, 158, 110), (130, 114, 74)),
        "barrier": ((226, 230, 236), (184, 190, 200), (120, 130, 145)),
        "vending": ((244, 248, 255), (70, 150, 235), (30, 70, 140)),
        "container": ((92, 164, 222), (52, 118, 182), (28, 70, 120)),
    }.get(kind, ((220, 220, 220), (170, 170, 170), (110, 110, 110)))
    ctop, cfront, cline = (QtGui.QColor(*c) for c in pal)
    pen = QtGui.QPen(cline, 1.6)
    p.setPen(pen)
    g = QtGui.QLinearGradient(front.topLeft(), front.bottomLeft())
    g.setColorAt(0, cfront.lighter(108)); g.setColorAt(1, cfront.darker(118))
    p.setBrush(g); p.drawRect(front)
    gt = QtGui.QLinearGradient(top.topLeft(), top.bottomRight())
    gt.setColorAt(0, ctop.lighter(106)); gt.setColorAt(1, ctop.darker(104))
    p.setBrush(gt); p.drawRect(top)
    p.save(); p.setClipRect(front.united(top))
    rnd = random.Random(bx.seed)
    if kind == "crate":
        p.setPen(QtGui.QPen(cline, 1.2))
        n = 3
        for i in range(1, n):
            y = top.top() + top.height() * i / n
            p.drawLine(QPointF(top.left(), y), QPointF(top.right(), y))
        p.setPen(QtGui.QPen(cline, 2.2))
        p.drawRect(front.adjusted(3, 3, -3, -3))
        p.drawLine(front.topLeft() + QPointF(3, 3), front.bottomRight() - QPointF(3, 3))
        p.drawLine(QPointF(front.right() - 3, front.top() + 3), QPointF(front.left() + 3, front.bottom() - 3))
    elif kind == "sandbags":
        p.setPen(QtGui.QPen(cline, 1.1)); p.setBrush(ctop)
        horiz = top.width() >= top.height()
        n = max(2, int((top.width() if horiz else top.height()) / max(10.0, (top.height() if horiz else top.width()) * 0.9)))
        for row in range(2):
            for i in range(n):
                if horiz:
                    w = top.width() / n; r = QRectF(top.left() + i * w + (w * 0.5 if row else 0) - (w * 0.25 if row else 0),
                                                    top.top() + row * top.height() / 2, w * (0.98 if not row else 0.5 if i == n - 1 else 0.98),
                                                    top.height() / 2)
                else:
                    h = top.height() / n; r = QRectF(top.left() + row * top.width() / 2, top.top() + i * h,
                                                     top.width() / 2, h)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        p.setPen(QtGui.QPen(col(cline, 160), 1))
        steps = max(2, int(front.width() / 16))
        for i in range(1, steps):
            x = front.left() + front.width() * i / steps
            p.drawLine(QPointF(x, front.top() + 2), QPointF(x, front.bottom() - 2))
    elif kind == "barrier":
        p.setPen(NOPEN)
        stripe = front.adjusted(0, front.height() * 0.45, 0, -front.height() * 0.2)
        p.setBrush(QtGui.QColor(255, 210, 40)); p.drawRect(stripe)
        p.setBrush(QtGui.QColor(40, 40, 50))
        w = 10.0; x = stripe.left() - stripe.height()
        while x < stripe.right():
            p.drawPolygon(QtGui.QPolygonF([QPointF(x, stripe.bottom()), QPointF(x + w, stripe.bottom()),
                                           QPointF(x + w + stripe.height(), stripe.top()),
                                           QPointF(x + stripe.height(), stripe.top())]))
            x += w * 2
    elif kind == "vending":
        panel = front.adjusted(4, 4, -front.width() * 0.32, -4)
        p.setPen(NOPEN); p.setBrush(QtGui.QColor(225, 245, 255)); p.drawRect(panel)
        for j in range(4):
            for i in range(3):
                c = QtGui.QColor.fromHsv((rnd.randint(0, 359)), 150, 255)
                p.setBrush(c)
                p.drawEllipse(QPointF(panel.left() + panel.width() * (i + 0.5) / 3,
                                      panel.top() + panel.height() * (j + 0.4) / 4.4), 2.4, 3.2)
        p.setBrush(QtGui.QColor(255, 226, 63)); p.drawRect(QRectF(front.right() - front.width() * 0.26,
                                                                  front.top() + front.height() * 0.4, 5, 8))
        glow = 0.5 + 0.5 * math.sin(now * 2 + bx.seed)
        p.setBrush(QtGui.QColor(111, 224, 255, int(40 + 50 * glow))); p.drawRect(panel)
    elif kind == "container":
        p.setPen(QtGui.QPen(col(cline, 170), 1.2))
        horiz = top.width() >= top.height()
        n = int((top.width() if horiz else top.height()) / 9)
        for i in range(1, n):
            if horiz:
                x = top.left() + top.width() * i / n
                p.drawLine(QPointF(x, top.top()), QPointF(x, top.bottom()))
                p.drawLine(QPointF(x, front.top()), QPointF(x, front.bottom()))
            else:
                y = top.top() + top.height() * i / n
                p.drawLine(QPointF(top.left(), y), QPointF(top.right(), y))
        p.setPen(NOPEN); p.setBrush(QtGui.QColor(255, 255, 255, 200))
        lab = QRectF(top.center().x() - 16, top.center().y() - 5, 32, 10)
        p.drawRoundedRect(lab, 3, 3)
    # damage cracks
    if bx.hp_max:
        dmg = 1.0 - max(0.0, bx.hp) / bx.hp_max
        if dmg > 0.3:
            p.setPen(QtGui.QPen(QtGui.QColor(40, 30, 20, int(120 + 100 * dmg)), 1.4))
            for k in range(int(dmg * 6)):
                x0 = rnd.uniform(top.left(), top.right()); y0 = rnd.uniform(top.top(), front.bottom())
                pts = [QPointF(x0, y0)]
                for _ in range(3):
                    x0 += rnd.uniform(-8, 8); y0 += rnd.uniform(-6, 6); pts.append(QPointF(x0, y0))
                p.drawPolyline(QtGui.QPolygonF(pts))
    p.restore()
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 150), 1))
    p.drawLine(top.topLeft() + QPointF(1, 1), top.topRight() + QPointF(-1, 1))


def _paint_barrel(p, bx, now):
    cx = bx.cx(); rx = (bx.r - bx.l) / 2; ry = rx * 0.55
    hk = bx.height * OBLIQUE
    yb = bx.cy() + ry * 0.4
    yt = yb - hk
    red, dark = QtGui.QColor(232, 72, 62), QtGui.QColor(150, 30, 30)
    p.setPen(QtGui.QPen(dark, 1.4))
    g = QtGui.QLinearGradient(QPointF(cx - rx, 0), QPointF(cx + rx, 0))
    g.setColorAt(0, dark); g.setColorAt(0.35, red.lighter(115)); g.setColorAt(1, dark)
    body = QtGui.QPainterPath()
    body.moveTo(cx - rx, yt); body.lineTo(cx - rx, yb)
    body.arcTo(QRectF(cx - rx, yb - ry, rx * 2, ry * 2), 180, 180)
    body.lineTo(cx + rx, yt); body.closeSubpath()
    p.setBrush(g); p.drawPath(body)
    for f in (0.3, 0.7):
        y = yt + (yb - yt) * f
        p.drawArc(QRectF(cx - rx, y - ry, rx * 2, ry * 2), 180 * 16, 180 * 16)
    p.setBrush(red.lighter(108)); p.drawEllipse(QPointF(cx, yt), rx, ry)
    p.setBrush(dark); p.drawEllipse(QPointF(cx + rx * 0.35, yt), rx * 0.2, ry * 0.25)
    # hazard diamond
    s = rx * 0.45; c = QPointF(cx, yt + hk * 0.55)
    p.setPen(QtGui.QPen(QtGui.QColor(40, 20, 0), 1)); p.setBrush(QtGui.QColor(255, 220, 60))
    p.drawPolygon(QtGui.QPolygonF([QPointF(c.x(), c.y() - s), QPointF(c.x() + s, c.y()), QPointF(c.x(), c.y() + s),
                                   QPointF(c.x() - s, c.y())]))
    if bx.hp_max and bx.hp < bx.hp_max * 0.5:              # leaking / about to go
        a = int(120 + 120 * (0.5 + 0.5 * math.sin(now * 14)))
        p.setPen(NOPEN); p.setBrush(QtGui.QColor(255, 160, 40, a))
        p.drawEllipse(QPointF(cx + rx * 0.3, yt - 3), 4, 6)


def _paint_debris(p, bx):
    rnd = random.Random(bx.seed + 99)
    p.setPen(NOPEN)
    base = {"crate": (168, 112, 58), "barrel": (60, 50, 50), "vending": (180, 200, 220)}.get(bx.kind, (150, 150, 150))
    p.setBrush(QtGui.QColor(20, 20, 20, 60))
    p.drawEllipse(QPointF(bx.cx(), bx.cy()), (bx.r - bx.l) * 0.7, (bx.b - bx.t) * 0.6)
    for _ in range(9):
        x = rnd.uniform(bx.l - 6, bx.r + 6); y = rnd.uniform(bx.t - 4, bx.b + 4)
        p.setBrush(QtGui.QColor(*[max(0, min(255, c + rnd.randint(-25, 15))) for c in base]))
        p.save(); p.translate(x, y); p.rotate(rnd.uniform(0, 180))
        p.drawRect(QRectF(-rnd.uniform(2, 7), -2, rnd.uniform(5, 13), rnd.uniform(3, 5))); p.restore()


def paint_window_base(p, bx, now, team_tint=None):
    """Real windows are walls: a soft contact shadow along their foot and a faint tactical outline."""
    r = QRectF(bx.l, bx.t, bx.r - bx.l, bx.b - bx.t)
    p.setPen(NOPEN)
    for i in range(6):
        p.setBrush(QtGui.QColor(10, 20, 40, 16 - i * 2))
        p.drawRect(QRectF(r.left() - 2, r.bottom() + i * 2, r.width() + 4, 3))
    pen = QtGui.QPen(QtGui.QColor(111, 224, 255, 110), 2)
    pen.setDashPattern([6, 6]); pen.setDashOffset(-now * 12)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(r.adjusted(-3, -3, 3, 3))
