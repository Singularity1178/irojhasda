"""Blue Archive style VFX: pure QPainter drawing helpers, shared by every overlay.

Nothing in here owns a window, a timer or any state. ShotFX / Cutin (overlays.py)
and the pet window (pet_render.py) call these with a QPainter, a position and a
0..1 age `u`, so an effect looks exactly the same wherever it is drawn.

The look follows the game:
  * hits        white 4-point "kira" flare + coloured ring + tapered shards
  * muzzle      forward spike + two side spikes + white core, a puff of smoke after
  * tracers     thin, hot, yellow-white; sniper / railgun leave a lingering beam
  * explosions  white flash, orange fireball, shockwave ring, debris, grey smoke
  * numbers     bold italic, navy outline; CRITICAL in gold with a label; MISS / BLOCK
  * emotes      the story-mode emoticons (! ? !? heart note ... sweat anger blush idea)
  * UI motifs   BA blue (#128CFF), sky cyan, white parallelograms, triangles, halftone
"""
from __future__ import annotations

import math
import random

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

# ----------------------------------------------------------------------------- palette
BA_BLUE = (18, 140, 255)       # the UI blue
BA_SKY = (110, 205, 255)       # halo / accent cyan
BA_NAVY = (24, 50, 90)         # text outline / dark panel
BA_DEEP = (8, 22, 52)          # cut-in backdrop
BA_PINK = (255, 112, 165)
BA_GOLD = (255, 214, 72)
BA_ORANGE = (255, 140, 36)
BA_RED = (240, 72, 72)
WHITE = (255, 255, 255)

NOPEN = Qt.PenStyle.NoPen
NOBRUSH = Qt.BrushStyle.NoBrush
ROUND = Qt.PenCapStyle.RoundCap
RJOIN = Qt.PenJoinStyle.RoundJoin


def clamp01(u):
    return 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)


def ease_out(u):
    u = clamp01(u)
    return 1.0 - (1.0 - u) ** 3


def ease_back(u, s=1.9):
    """Overshoot then settle: the BA 'pop' used by numbers, emotes and badges."""
    u = clamp01(u) - 1.0
    return 1.0 + u * u * ((s + 1.0) * u + s)


def smooth(a, b, u):
    t = clamp01((u - a) / max(1e-6, b - a))
    return t * t * (3.0 - 2.0 * t)


def lerp_rgb(c0, c1, t):
    t = clamp01(t)
    return (c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t)


def qc(rgb, a=255.0):
    a = 0 if a < 0 else (255 if a > 255 else int(a))
    return QtGui.QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), a)


def pen(rgb, a, w, cap=ROUND):
    pn = QtGui.QPen(qc(rgb, a), max(0.01, float(w)), Qt.PenStyle.SolidLine, cap, RJOIN)
    return pn


# ----------------------------------------------------------------------------- weapons
# Per weapon_type (combat_index.json). A character profile's `bullet` dict (iroha.py)
# is laid over the top of these, so a tank shell still wins over "Handgun".
#   flash   muzzle flash size        width / trail / color   the tracer
#   spark   impact size              tint                    impact colour
#   pellets shotgun pellets          spread (rad)            cone half-angle
#   beam    leave a lingering beam   explosion               impact = explosion
#   casing  eject brass              dmg                     damage-number range
WEAPON_FX = {
    "Handgun":          dict(flash=0.75, width=3.0, trail=110.0, color=(255, 226, 140), spark=0.8, tint=(255, 230, 150),
                             casing=True, dmg=(380, 620)),
    "Submachine Gun":   dict(flash=0.8, width=2.8, trail=130.0, color=(255, 214, 120), spark=0.75, tint=(255, 222, 130),
                             casing=True, dmg=(240, 420)),
    "Assault Rifle":    dict(flash=1.0, width=3.4, trail=170.0, color=(255, 200, 90), spark=1.0, tint=(255, 214, 110),
                             casing=True, dmg=(420, 700)),
    "Machine Gun":      dict(flash=1.1, width=3.8, trail=200.0, color=(255, 188, 70), spark=0.95, tint=(255, 205, 100),
                             casing=True, dmg=(260, 460)),
    "Shotgun":          dict(flash=1.45, width=2.4, trail=80.0, color=(255, 210, 120), spark=0.7, tint=(255, 220, 130),
                             casing=True, pellets=7, spread=0.085, dmg=(900, 1500)),
    "Sniper Rifle":     dict(flash=1.55, width=3.0, trail=260.0, color=(255, 246, 205), spark=1.35, tint=(255, 240, 190),
                             casing=True, beam=True, beam_width=5.0, beam_life=0.42, speed=9000.0, dmg=(2400, 3800)),
    "Railgun":          dict(flash=1.6, width=6.0, trail=300.0, color=(120, 225, 255), spark=1.6, tint=(150, 230, 255),
                             beam=True, beam_width=16.0, beam_life=0.6, speed=12000.0, dmg=(3200, 5200)),
    "Grenade Launcher": dict(flash=1.3, width=6.0, trail=60.0, color=(255, 170, 80), spark=1.0, tint=(255, 170, 70),
                             explosion=True, speed=1900.0, shell=True, dmg=(1800, 2800)),
    "Rocket Launcher":  dict(flash=1.5, width=7.0, trail=140.0, color=(255, 160, 70), spark=1.0, tint=(255, 160, 60),
                             explosion=True, speed=2300.0, shell=True, dmg=(2200, 3200)),
    "Mortar":           dict(flash=1.4, width=6.0, trail=60.0, color=(255, 170, 80), spark=1.0, tint=(255, 170, 70),
                             explosion=True, speed=1700.0, shell=True, dmg=(2000, 3000)),
    "Flamethrower":     dict(flash=1.2, width=8.0, trail=90.0, color=(255, 140, 40), spark=0.9, tint=(255, 150, 50),
                             dmg=(200, 360)),
}
DEFAULT_WEAPON = "Assault Rifle"


def weapon_fx(weapon=None, style=None):
    """The merged look of one shot: weapon defaults, then the profile bullet on top."""
    out = dict(WEAPON_FX.get(weapon or "", WEAPON_FX[DEFAULT_WEAPON]))
    if style:
        out.update(style)
        out["shell"] = True                                   # a profile bullet is a visible round
        if "impact_size" in style and "explosion" not in style:
            out["explosion"] = float(style["impact_size"]) >= 2.0
        if "color" in style and "tint" not in style:
            out["tint"] = style["color"]
    return out


def explosion_size(wf):
    """Size multiplier of the explosion a bullet look draws on impact (see overlays.ShotFX.step)."""
    return max(0.6, min(1.6, 0.55 * float(wf.get("impact_size", 1.6))))


def explosion_radius(size):
    """How far the explosion() shockwave ring reaches, in px: 26 * size at the start, growing by
    190 * size. Whatever that ring visibly sweeps over is what a splash bullet damages."""
    return 216.0 * size


def roll_damage(wf, crit_chance=0.15, mult=1.0):
    """A cosmetic BA-sized damage number for one bullet: (value, is_crit)."""
    lo, hi = wf.get("dmg", (400, 700))
    v = random.uniform(lo, hi) * mult
    crit = random.random() < crit_chance
    if crit: v *= random.uniform(1.6, 2.0)
    return int(round(v)), crit


# ----------------------------------------------------------------------------- shapes
def kira_path(r, thin=0.16):
    """The 4-point concave sparkle every BA effect is built from."""
    c = r * thin
    p = QtGui.QPainterPath(); p.moveTo(0, -r)
    p.quadTo(c, -c, r, 0); p.quadTo(c, c, 0, r); p.quadTo(-c, c, -r, 0); p.quadTo(-c, -c, 0, -r)
    p.closeSubpath()
    return p


def tri_path(r):
    p = QtGui.QPainterPath()
    p.addPolygon(QtGui.QPolygonF([QPointF(0, -r), QPointF(r * 0.866, r * 0.5), QPointF(-r * 0.866, r * 0.5)]))
    p.closeSubpath()
    return p


def heart_path(s):
    p = QtGui.QPainterPath(); p.moveTo(0, s * 0.8)
    p.cubicTo(-s * 1.1, s * 0.1, -s * 0.7, -s * 0.9, 0, -s * 0.35)
    p.cubicTo(s * 0.7, -s * 0.9, s * 1.1, s * 0.1, 0, s * 0.8)
    return p


def para_path(x, y, w, h, skew):
    """Parallelogram (BA panels lean right): skew = horizontal offset of the top edge."""
    p = QtGui.QPainterPath()
    p.addPolygon(QtGui.QPolygonF([QPointF(x + skew, y), QPointF(x + w + skew, y),
                                  QPointF(x + w, y + h), QPointF(x, y + h)]))
    p.closeSubpath()
    return p


def drop_path(s):
    p = QtGui.QPainterPath(); p.moveTo(0, -s)
    p.cubicTo(s * 0.35, -s * 0.35, s * 0.75, s * 0.15, s * 0.75, s * 0.42)
    p.arcTo(QRectF(-s * 0.75, -s * 0.33, s * 1.5, s * 1.5), 0, -180)
    p.cubicTo(-s * 0.75, s * 0.15, -s * 0.35, -s * 0.35, 0, -s)
    p.closeSubpath()
    return p


def glow(p, x, y, r, rgb, a):
    if r <= 0.5 or a <= 1: return
    g = QtGui.QRadialGradient(x, y, r)
    g.setColorAt(0.0, qc(rgb, a)); g.setColorAt(0.4, qc(rgb, a * 0.45)); g.setColorAt(1.0, qc(rgb, 0))
    p.setPen(NOPEN); p.setBrush(QtGui.QBrush(g)); p.drawEllipse(QPointF(x, y), r, r)


def text_path(txt, font, cx, base_y):
    """A centred text outline, so it can be stroked (outline) and then filled."""
    fm = QtGui.QFontMetricsF(font)
    w = fm.horizontalAdvance(txt)
    path = QtGui.QPainterPath(); path.addText(cx - w / 2.0, base_y, font, txt)
    return path, w, fm.ascent()


def ba_font(px, italic=True, black=True):
    f = QtGui.QFont("Arial Black" if black else "Arial")
    f.setStyleHint(QtGui.QFont.StyleHint.SansSerif)
    f.setPixelSize(max(1, int(px))); f.setBold(True); f.setItalic(italic)
    return f


# ----------------------------------------------------------------------------- sparkles
def sparkle(p, x, y, r, rgb=WHITE, a=255, rot=0.0, core=True):
    """Glowing kira star; core = small white heart in a coloured one."""
    if a <= 1 or r <= 0.3: return
    glow(p, x, y, r * 1.6, rgb, a * 0.55)
    p.save(); p.translate(x, y); p.rotate(rot)
    p.setPen(NOPEN); p.setBrush(qc(rgb, a)); p.drawPath(kira_path(r))
    if core:
        p.setBrush(qc(WHITE, a)); p.drawPath(kira_path(r * 0.55, 0.2))
    p.restore()


def shard(p, x, y, r, rgb, a, rot, outline=False):
    """The BA triangle confetti. outline = hollow (UI style), else filled."""
    if a <= 1: return
    p.save(); p.translate(x, y); p.rotate(rot)
    if outline:
        p.setBrush(NOBRUSH); p.setPen(pen(rgb, a, max(1.0, r * 0.22)))
    else:
        p.setPen(NOPEN); p.setBrush(qc(rgb, a))
    p.drawPath(tri_path(r))
    p.restore()


# ----------------------------------------------------------------------------- gunfire
def muzzle_flash(p, x, y, ang, k, size=1.0, tint=(255, 220, 120)):
    """k = remaining life 1..0. ang = barrel direction (rad) or None for a round flash."""
    if k <= 0: return
    s = size * (0.7 + 0.4 * k)
    glow(p, x, y, 38 * s, tint, 210 * k)
    p.save(); p.translate(x, y)
    p.setPen(NOPEN)
    if ang is not None:
        p.rotate(math.degrees(ang))
        L, w = 56 * s, 9.5 * s
        for ln, wd, off in ((L, w, 0), (L * 0.42, w * 0.62, 64), (L * 0.42, w * 0.62, -64), (L * 0.2, w * 0.5, 180)):
            p.save(); p.rotate(off)
            g = QtGui.QLinearGradient(0, 0, ln, 0)
            g.setColorAt(0.0, qc(WHITE, 255 * k)); g.setColorAt(0.35, qc(tint, 240 * k)); g.setColorAt(1.0, qc(tint, 0))
            path = QtGui.QPainterPath(); path.moveTo(-wd * 0.3, 0); path.lineTo(ln * 0.16, -wd)
            path.lineTo(ln, 0); path.lineTo(ln * 0.16, wd); path.closeSubpath()
            p.setBrush(QtGui.QBrush(g)); p.drawPath(path); p.restore()
        p.rotate(45 * (1 - k))
    p.setBrush(qc(WHITE, 255 * k)); p.drawPath(kira_path(16 * s, 0.2))
    p.drawEllipse(QPointF(0, 0), 5.5 * s, 5.5 * s)
    p.restore()


def smoke_puff(p, x, y, r, a, rgb=(235, 238, 245)):
    if a <= 1: return
    p.setPen(NOPEN)
    g = QtGui.QRadialGradient(x, y, r)
    g.setColorAt(0.0, qc(rgb, a)); g.setColorAt(0.7, qc(rgb, a * 0.55)); g.setColorAt(1.0, qc(rgb, 0))
    p.setBrush(QtGui.QBrush(g)); p.drawEllipse(QPointF(x, y), r, r)


def tracer(p, hx, hy, ux, uy, tl, width, rgb, shell=False):
    """A tracer whose head is at (hx, hy), travelling along (ux, uy), tl px long."""
    tail = QPointF(hx - ux * tl, hy - uy * tl); head = QPointF(hx, hy)
    g = QtGui.QLinearGradient(tail, head)
    g.setColorAt(0.0, qc(rgb, 0)); g.setColorAt(1.0, qc(rgb, 150))
    pn = QtGui.QPen(QtGui.QBrush(g), width * 2.2, Qt.PenStyle.SolidLine, ROUND); p.setPen(pn); p.drawLine(tail, head)
    g2 = QtGui.QLinearGradient(QPointF(hx - ux * tl * 0.65, hy - uy * tl * 0.65), head)
    g2.setColorAt(0.0, qc(WHITE, 0)); g2.setColorAt(1.0, qc((255, 252, 230), 255))
    pn2 = QtGui.QPen(QtGui.QBrush(g2), max(1.6, width * 0.5), Qt.PenStyle.SolidLine, ROUND)
    p.setPen(pn2); p.drawLine(QPointF(hx - ux * tl * 0.65, hy - uy * tl * 0.65), head)
    if shell:
        glow(p, hx, hy, width * 2.6, rgb, 220)
        p.setPen(NOPEN); p.setBrush(qc((255, 248, 220), 255)); p.drawEllipse(head, width * 0.85, width * 0.85)


def beam(p, x0, y0, x1, y1, u, width, rgb, seed=0):
    """Sniper / railgun beam: wide glow, coloured body, white core; thins and fades."""
    k = 1.0 - clamp01(u)
    if k <= 0: return
    w = width * (0.25 + 0.75 * k * k)
    a0, a1 = QPointF(x0, y0), QPointF(x1, y1)
    p.setPen(pen(rgb, 70 * k, w * 3.2)); p.drawLine(a0, a1)
    p.setPen(pen(rgb, 200 * k, w)); p.drawLine(a0, a1)
    p.setPen(pen(WHITE, 255 * k, max(1.0, w * 0.38))); p.drawLine(a0, a1)
    if width >= 10:                                           # railgun: sparkles riding the beam
        rnd = random.Random(seed)
        d = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / d, (x1 - x0) / d
        for _ in range(int(d / 70)):
            t = rnd.random(); off = rnd.uniform(-1, 1) * width * (1.4 + u * 2.0)
            sparkle(p, x0 + (x1 - x0) * t + nx * off, y0 + (y1 - y0) * t + ny * off,
                    rnd.uniform(3, 7) * (0.5 + k), BA_SKY, 230 * k, rnd.uniform(0, 90), core=True)


def hit_spark(p, x, y, u, size=1.0, tint=(255, 214, 110), rays=()):
    """BA bullet impact: kira flare that pops and spins, a ring, shards flying out."""
    u = clamp01(u); k = 1.0 - u
    if u < 0.4:
        f = 1.0 - u / 0.4
        glow(p, x, y, 46 * size * (0.6 + u), WHITE, 220 * f)
        p.save(); p.translate(x, y); p.rotate(30 * u); p.setPen(NOPEN)
        r = 34 * size * (0.45 + 0.75 * ease_out(u / 0.4))
        p.setBrush(qc(tint, 230 * f)); p.drawPath(kira_path(r * 1.1, 0.14))
        p.rotate(45); p.setBrush(qc(WHITE, 255 * f)); p.drawPath(kira_path(r * 0.62, 0.18))
        p.restore()
    rr = 8 * size + 36 * size * ease_out(u)
    p.setBrush(NOBRUSH); p.setPen(pen(tint, 230 * k, max(0.6, 3.6 * size * k))); p.drawEllipse(QPointF(x, y), rr, rr)
    p.setPen(NOPEN); p.setBrush(qc(lerp_rgb(WHITE, tint, u), 255 * k))
    for ang, ln in rays:
        d0 = ln * ease_out(u) * 0.85 + 4 * size
        d1 = d0 + ln * 0.5 * k + 3
        c, s_ = math.cos(ang), math.sin(ang); w = 2.8 * size * k + 0.4
        poly = QtGui.QPolygonF([QPointF(x + c * d0 - s_ * w, y + s_ * d0 + c * w),
                                QPointF(x + c * d1, y + s_ * d1),
                                QPointF(x + c * d0 + s_ * w, y + s_ * d0 - c * w)])
        p.drawPolygon(poly)


def explosion(p, x, y, u, size=1.0, seed=0, life=0.9):
    """BA explosion: flash, fireball blobs going yellow -> orange -> red -> smoke,
    a shockwave ring, flying debris."""
    u = clamp01(u); rnd = random.Random(seed); t = u * life
    if u < 0.16:
        glow(p, x, y, 190 * size, (255, 250, 232), 255 * (1 - u / 0.16))
    # shockwave
    su = clamp01(u * 1.7)
    if su < 1.0:
        R = 26 * size + 190 * size * ease_out(su)
        p.setBrush(NOBRUSH)
        p.setPen(pen((255, 236, 200), 210 * (1 - su), 12 * size * (1 - su) + 1)); p.drawEllipse(QPointF(x, y), R, R)
        p.setPen(pen(WHITE, 160 * (1 - su), 3 * size * (1 - su) + 0.5)); p.drawEllipse(QPointF(x, y), R * 0.86, R * 0.86)
    # smoke (behind the fire, grows late)
    for _ in range(7):
        ang = rnd.uniform(0, math.tau); dist = rnd.uniform(14, 48) * size
        sr = rnd.uniform(26, 44) * size * (0.4 + 0.9 * ease_out(u))
        sa = 170 * smooth(0.12, 0.35, u) * (1 - smooth(0.55, 1.0, u))
        smoke_puff(p, x + math.cos(ang) * dist * ease_out(u), y + math.sin(ang) * dist * ease_out(u) - 50 * size * u,
                   sr, sa, (120, 118, 126))
    # fireball
    fire_a = 1.0 - smooth(0.35, 0.75, u)
    if fire_a > 0:
        for i in range(10):
            ang = rnd.uniform(0, math.tau); dist = rnd.uniform(0, 34) * size * ease_out(min(1.0, u * 2.4))
            r = rnd.uniform(20, 38) * size * (0.35 + 0.8 * ease_out(min(1.0, u * 3.0)))
            col = lerp_rgb((255, 250, 210), (255, 168, 48), u * 3.0) if u < 0.33 else \
                lerp_rgb((255, 168, 48), (210, 60, 30), (u - 0.33) * 3.0)
            cx = x + math.cos(ang) * dist; cy = y + math.sin(ang) * dist - 24 * size * u
            g = QtGui.QRadialGradient(cx, cy, r)
            g.setColorAt(0.0, qc(lerp_rgb(col, WHITE, 0.55 * (1 - u)), 255 * fire_a))
            g.setColorAt(0.6, qc(col, 235 * fire_a)); g.setColorAt(1.0, qc(col, 0))
            p.setPen(NOPEN); p.setBrush(QtGui.QBrush(g)); p.drawEllipse(QPointF(cx, cy), r, r)
    # debris + sparks
    for i in range(14):
        ang = rnd.uniform(math.pi * 1.05, math.pi * 1.95) if i % 3 else rnd.uniform(0, math.tau)
        spd = rnd.uniform(260, 620) * size
        dx = math.cos(ang) * spd * t; dy = math.sin(ang) * spd * t + 900 * t * t
        a = 255 * (1 - u)
        if i % 2:
            p.setPen(pen((255, 220, 140), a, 2.2 * size)); vx, vy = math.cos(ang) * spd, math.sin(ang) * spd + 1800 * t
            vl = math.hypot(vx, vy) or 1.0
            p.drawLine(QPointF(x + dx, y + dy), QPointF(x + dx - vx / vl * 14 * size, y + dy - vy / vl * 14 * size))
        else:
            p.setPen(NOPEN); p.setBrush(qc((60, 52, 58), a)); p.drawEllipse(QPointF(x + dx, y + dy), 2.6 * size, 2.6 * size)


def casing(p, x, y, rot, a, s=1.0):
    p.save(); p.translate(x, y); p.rotate(rot); p.setPen(pen((120, 80, 20), a, 0.8))
    g = QtGui.QLinearGradient(0, -2.2 * s, 0, 2.2 * s)
    g.setColorAt(0, qc((255, 226, 130), a)); g.setColorAt(1, qc((196, 140, 40), a))
    p.setBrush(QtGui.QBrush(g)); p.drawRoundedRect(QRectF(-4.5 * s, -2.0 * s, 9 * s, 4 * s), 1.2, 1.2)
    p.restore()


def bullet_hole(p, x, y, k):
    a = int(200 * min(1.0, k * 2.0))
    p.setBrush(qc((20, 20, 24), a)); p.setPen(pen(WHITE, a // 2, 1.2))
    p.drawEllipse(QPointF(x, y), 4.5, 4.5)
    p.setPen(pen((20, 20, 24), a, 1.2))
    for ang in (0.4, 1.9, 3.4, 5.0):
        p.drawLine(QPointF(x + math.cos(ang) * 5, y + math.sin(ang) * 5),
                   QPointF(x + math.cos(ang) * 11, y + math.sin(ang) * 11))


# ----------------------------------------------------------------------------- numbers
def damage_text(p, x, y, text, u, kind="normal", scale=1.0):
    """Floating combat text. kind: normal | crit | miss | block | heal."""
    u = clamp01(u)
    pop = ease_back(min(1.0, u / 0.16), 2.6)
    a = 255 * (1.0 if u < 0.62 else 1.0 - (u - 0.62) / 0.38)
    rise = (36 if kind != "crit" else 26) * scale * ease_out(u)
    px = {"crit": 40, "miss": 26, "block": 24, "heal": 28}.get(kind, 30) * scale
    p.save(); p.translate(x, y - rise); p.scale(0.35 + 0.65 * pop, 0.35 + 0.65 * pop)
    if kind == "crit": p.rotate(-4)
    f = ba_font(px)
    path, w, asc = text_path(text, f, 0, px * 0.36)
    if kind == "crit":
        fill = QtGui.QLinearGradient(0, -px * 0.5, 0, px * 0.4)
        fill.setColorAt(0, qc((255, 250, 190), a)); fill.setColorAt(0.5, qc(BA_GOLD, a)); fill.setColorAt(1, qc(BA_ORANGE, a))
        brush, out_rgb = QtGui.QBrush(fill), (110, 34, 0)
    elif kind == "miss":
        brush, out_rgb = QtGui.QBrush(qc((236, 242, 252), a)), (60, 78, 110)
    elif kind == "block":
        brush, out_rgb = QtGui.QBrush(qc(BA_SKY, a)), BA_NAVY
    elif kind == "heal":
        brush, out_rgb = QtGui.QBrush(qc((140, 255, 160), a)), (16, 80, 40)
    else:
        brush, out_rgb = QtGui.QBrush(qc(WHITE, a)), BA_NAVY
    p.strokePath(path, pen(out_rgb, a, px * 0.2))
    p.fillPath(path, brush)
    if kind in ("crit", "block"):
        lab = "CRITICAL" if kind == "crit" else "BLOCK"
        lf = ba_font(px * 0.38)
        lpath, lw, _ = text_path(lab, lf, 0, -px * 0.62)
        if kind == "crit":                                    # a little skewed tag behind the label
            p.setPen(NOPEN); p.setBrush(qc((200, 50, 10), a * 0.92))
            p.drawPath(para_path(-lw / 2 - 8, -px * 0.62 - px * 0.36, lw + 16, px * 0.48, 6))
        p.strokePath(lpath, pen(out_rgb, a, px * 0.1))
        p.fillPath(lpath, QtGui.QBrush(qc(WHITE, a)))
    p.restore()


# ----------------------------------------------------------------------------- emotes
BALLOON_EMOTES = ("exclaim", "question", "surprise", "heart", "note", "dots", "idea")
FREE_EMOTES = ("sweat", "angry", "shy")
EMOTES = BALLOON_EMOTES + FREE_EMOTES


def _balloon(p, w, h):
    path = QtGui.QPainterPath(); path.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), h * 0.42, h * 0.42)
    tail = QtGui.QPainterPath()
    tail.addPolygon(QtGui.QPolygonF([QPointF(-w * 0.28, h * 0.36), QPointF(-w * 0.04, h * 0.42), QPointF(-w * 0.36, h * 0.78)]))
    path = path.united(tail)
    p.setPen(pen((124, 188, 255), 255, 2.4)); p.setBrush(qc(WHITE, 250)); p.drawPath(path)


def _bang(p, x, y, s, rgb):
    """A chunky exclamation mark at (x, y), s = height."""
    bar = QtGui.QPainterPath()
    bar.addPolygon(QtGui.QPolygonF([QPointF(x - s * 0.17, y - s * 0.5), QPointF(x + s * 0.17, y - s * 0.5),
                                    QPointF(x + s * 0.08, y + s * 0.18), QPointF(x - s * 0.08, y + s * 0.18)]))
    bar.closeSubpath(); bar.addEllipse(QPointF(x, y + s * 0.38), s * 0.11, s * 0.11)
    p.strokePath(bar, pen(BA_NAVY, 255, s * 0.12)); p.fillPath(bar, qc(rgb))


def emote(p, kind, x, y, u, size=1.0):
    """Story-mode emoticon above a head. u = 0..1 over its lifetime."""
    u = clamp01(u)
    pop = ease_back(min(1.0, u / 0.2), 2.4)
    a = 1.0 if u < 0.8 else (1.0 - u) / 0.2
    if a <= 0.01: return
    p.save(); p.setOpacity(p.opacity() * a)
    bob = math.sin(u * math.tau * 1.6) * 2.0 * size
    p.translate(x, y + bob)
    # BA emotes jump in with a small squash
    sq = 1.0 + 0.12 * math.sin(min(1.0, u / 0.25) * math.pi)
    p.scale(size * pop * sq, size * pop / sq)
    if kind in BALLOON_EMOTES:
        _balloon(p, 46, 38)
    if kind == "exclaim":
        _bang(p, 0, -2, 26, BA_RED)
    elif kind == "surprise":
        _bang(p, -7, -2, 24, BA_RED)
        f = ba_font(24, italic=False); path, _w, _a = text_path("?", f, 9, 7)
        p.strokePath(path, pen(BA_NAVY, 255, 3.2)); p.fillPath(path, qc(BA_BLUE))
    elif kind == "question":
        f = ba_font(28, italic=False); path, _w, _a = text_path("?", f, 0, 10)
        p.strokePath(path, pen(BA_NAVY, 255, 3.4)); p.fillPath(path, qc(BA_BLUE))
    elif kind == "heart":
        p.save(); p.translate(0, -1); s = 13 * (1.0 + 0.08 * math.sin(u * math.tau * 3))
        hp = heart_path(s); p.strokePath(hp, pen((200, 40, 100), 255, 2.2)); p.fillPath(hp, qc(BA_PINK))
        p.setPen(NOPEN); p.setBrush(qc(WHITE, 220)); p.drawEllipse(QPointF(-s * 0.42, -s * 0.28), s * 0.18, s * 0.12)
        p.restore()
    elif kind == "note":
        p.setPen(pen(BA_NAVY, 255, 3.0)); p.setBrush(qc(BA_NAVY))
        p.drawEllipse(QPointF(-6, 8), 5.2, 4.0); p.drawLine(QPointF(-1.2, 8), QPointF(-1.2, -11))
        fl = QtGui.QPainterPath(); fl.moveTo(-1.2, -11); fl.cubicTo(6, -8, 9, -4, 7, 2)
        p.setBrush(NOBRUSH); p.drawPath(fl)
        sparkle(p, 12, -10, 4.5, BA_GOLD, 255, 0, core=False)
    elif kind == "dots":
        p.setPen(NOPEN); p.setBrush(qc(BA_NAVY))
        for i in range(3):
            if u * 6.0 > i * 0.6:
                p.drawEllipse(QPointF(-11 + i * 11, 2), 3.4, 3.4)
    elif kind == "idea":
        sparkle(p, 0, 0, 15, BA_GOLD, 255, u * 90)
    elif kind == "sweat":
        dy = 10.0 * ease_out(u)
        dp = drop_path(11); p.translate(4, dy)
        g = QtGui.QLinearGradient(0, -11, 0, 11); g.setColorAt(0, qc((200, 236, 255))); g.setColorAt(1, qc((70, 160, 255)))
        p.strokePath(dp, pen(BA_NAVY, 255, 2.0)); p.fillPath(dp, QtGui.QBrush(g))
        p.setPen(NOPEN); p.setBrush(qc(WHITE, 230)); p.drawEllipse(QPointF(-2.5, 2), 2.0, 3.0)
    elif kind == "angry":
        pulse = 1.0 + 0.15 * math.sin(u * math.tau * 4)
        p.scale(pulse, pulse); p.setBrush(NOBRUSH)
        for q in range(4):
            p.save(); p.rotate(q * 90 + 45)
            arc = QtGui.QPainterPath(); arc.moveTo(4, -9); arc.quadTo(4, -4, 9, -4)
            p.setPen(pen(WHITE, 255, 7.0)); p.drawPath(arc)
            p.setPen(pen(BA_RED, 255, 3.8)); p.drawPath(arc)
            p.restore()
    elif kind == "shy":
        for i in range(3):
            xx = -12 + i * 9
            p.setPen(pen(WHITE, 220, 5.0)); p.drawLine(QPointF(xx + 4, -6), QPointF(xx - 2, 6))
            p.setPen(pen(BA_PINK, 255, 2.6)); p.drawLine(QPointF(xx + 4, -6), QPointF(xx - 2, 6))
    p.restore()


# ----------------------------------------------------------------------------- UI bits
def reload_gauge(p, x, y, frac, r=17.0, a=255):
    """BA reload indicator: dark disc, cyan arc filling clockwise, bullet icon, label."""
    frac = clamp01(frac)
    p.save(); p.translate(x, y)
    p.setPen(NOPEN); p.setBrush(qc(BA_DEEP, a * 0.72)); p.drawEllipse(QPointF(0, 0), r + 3, r + 3)
    p.setBrush(NOBRUSH); p.setPen(pen(WHITE, a * 0.25, 4.0)); p.drawEllipse(QPointF(0, 0), r - 1, r - 1)
    g = QtGui.QConicalGradient(0, 0, 90); g.setColorAt(0.0, qc(WHITE, a)); g.setColorAt(0.5, qc(BA_SKY, a)); g.setColorAt(1.0, qc(BA_BLUE, a))
    pn = QtGui.QPen(QtGui.QBrush(g), 4.0, Qt.PenStyle.SolidLine, ROUND); p.setPen(pn)
    p.drawArc(QRectF(-r + 1, -r + 1, 2 * r - 2, 2 * r - 2), 90 * 16, -int(360 * 16 * frac))
    # bullet icon
    p.setPen(NOPEN); p.setBrush(qc(WHITE, a))
    b = QtGui.QPainterPath(); b.moveTo(-3.2, 6); b.lineTo(-3.2, -2); b.quadTo(-3.2, -8.5, 0, -9.5)
    b.quadTo(3.2, -8.5, 3.2, -2); b.lineTo(3.2, 6); b.closeSubpath(); p.drawPath(b)
    p.setBrush(qc(BA_SKY, a)); p.drawRect(QRectF(-3.8, 6.4, 7.6, 2.4))
    lf = ba_font(9.5); lp, _w, _a = text_path("RELOAD", lf, 0, r + 15)
    p.strokePath(lp, pen(BA_NAVY, a, 3.0)); p.fillPath(lp, qc(WHITE, a))
    p.restore()


def ground_ring(p, x, y, u, rmax, rgb=BA_SKY, flat=0.3, width=4.0):
    """Expanding ellipse on the floor: landings, spawn halo, EX burst."""
    u = clamp01(u); k = 1.0 - u
    r = rmax * (0.15 + 0.85 * ease_out(u))
    p.save(); p.translate(x, y); p.scale(1.0, flat)
    g = QtGui.QRadialGradient(0, 0, r)
    g.setColorAt(0.0, qc(rgb, 0)); g.setColorAt(0.75, qc(rgb, 50 * k)); g.setColorAt(1.0, qc(rgb, 0))
    p.setPen(NOPEN); p.setBrush(QtGui.QBrush(g)); p.drawEllipse(QPointF(0, 0), r, r)
    p.setBrush(NOBRUSH)
    p.setPen(pen(rgb, 230 * k, (width * k + 1.0) / max(0.2, flat) * 0.5)); p.drawEllipse(QPointF(0, 0), r, r)
    p.setPen(pen(WHITE, 200 * k, (width * 0.4 * k + 0.6) / max(0.2, flat) * 0.5)); p.drawEllipse(QPointF(0, 0), r * 0.8, r * 0.8)
    p.restore()


def tap_fx(p, x, y, u, size=1.0, seed=0):
    """The BA touch effect: cyan ring + inner white ring + tiny triangles darting out."""
    u = clamp01(u); k = 1.0 - u
    r = 10 * size + 28 * size * ease_out(u)
    p.setBrush(NOBRUSH)
    p.setPen(pen(BA_SKY, 240 * k, 4 * size * k + 0.5)); p.drawEllipse(QPointF(x, y), r, r)
    p.setPen(pen(WHITE, 255 * k, 2 * size * k + 0.4)); p.drawEllipse(QPointF(x, y), r * 0.62, r * 0.62)
    rnd = random.Random(seed)
    for i in range(6):
        ang = i * math.tau / 6 + rnd.uniform(-0.3, 0.3)
        d = r * 1.05 + 14 * size * ease_out(u)
        shard(p, x + math.cos(ang) * d, y + math.sin(ang) * d, 4.2 * size * k + 0.5,
              BA_SKY if i % 2 else WHITE, 255 * k, math.degrees(ang) + 90 + 120 * u)
    if u < 0.3:
        sparkle(p, x, y, 12 * size * (1 - u / 0.3), WHITE, 255 * (1 - u / 0.3), 0)


def dust_cloud(p, x, y, r, a, seed=0):
    """Stylised BA dust: chunky white-grey puffs with a pale blue edge."""
    if a <= 1: return
    rnd = random.Random(seed)
    p.setPen(pen((196, 210, 228), a * 0.8, max(0.8, r * 0.08)))
    p.setBrush(qc((250, 250, 252), a * 0.9))
    path = QtGui.QPainterPath()
    for _ in range(4):
        ox, oy = rnd.uniform(-0.55, 0.55) * r, rnd.uniform(-0.35, 0.2) * r
        rr = r * rnd.uniform(0.45, 0.7)
        path.addEllipse(QPointF(x + ox, y + oy), rr, rr * 0.86)
    p.drawPath(path.simplified())


def halftone(p, rect, rgb, a, step=10.0, rmax=3.2, fade_x=True):
    """Halftone dot field (BA panels): dots shrink across the rect."""
    path = QtGui.QPainterPath()
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    nx, ny = int(w / step) + 1, int(h / step) + 1
    for j in range(ny):
        for i in range(nx):
            t = i / max(1, nx - 1) if fade_x else j / max(1, ny - 1)
            r = rmax * (1.0 - t)
            if r < 0.4: continue
            ox = (step * 0.5) if j % 2 else 0.0
            path.addEllipse(QPointF(x0 + i * step + ox, y0 + j * step), r, r)
    p.setPen(NOPEN); p.setBrush(qc(rgb, a)); p.drawPath(path)
