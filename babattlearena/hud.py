"""Everything drawn during a match.

ArenaOverlay   a click-through, always-on-top transparent window over the whole home screen.
               It is the battlefield: props, students (their top-down renders), shadows, tracers,
               explosions, HP bars / lives over heads, the team panels, kill feed and banners
               (3-2-1, BATTLE START, EX cut-ins, RETIRE, VICTORY). Mouse clicks go straight through
               to your desktop, so windows can be moved / opened mid-fight and the students react.
ArenaHUD       the small interactive bar at the top: score, clock, pause, speed, stop.
PauseMenu      Resume / Restart / Arena Menu / Title Screen.
ResultScreen   the Blue Archive style results: winner banner, MVP, per-student stats,
               Rematch / Arena Menu / Title Screen.
"""
from __future__ import annotations

import math
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt

from bapet.picker import StudentPicker
from .obstacles import OBLIQUE, paint_box, paint_shadow, paint_window_base
from .theme import (AF, BLUE, BLUE_D, CYAN, GREEN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PINK, RED, RED_T, SKY,
                    TEAM_COL, TEAM_COL_D, TEAM_NAME, TEAM_SUB, WHITE, YELLOW, YELLOW_D, BAWindow, W_BLACK, W_BOLD,
                    W_DEMI, clamp, col, ease_back, ease_out, font, glyph_icon, para, rounded, text)


def portrait(p, e, r, round_=8, fallback_col=GREY):
    """A student's baked roster portrait (from Student Select), cropped into r."""
    p.save()
    path = rounded(r, round_)
    p.setClipPath(path, Qt.ClipOperation.IntersectClip)
    g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QtGui.QColor.fromHsv(getattr(e, "hue", 200), 70, 255)); g.setColorAt(1, WHITE)
    p.fillRect(r, g)
    still = getattr(e, "still", None)
    if still is not None:
        p.drawImage(r, still, StudentPicker._portrait_src(e, r))
    else:
        p.setPen(NOPEN); p.setBrush(col(fallback_col, 120))
        h = r.height()
        p.drawEllipse(QPointF(r.center().x(), r.top() + h * 0.42), h * 0.2, h * 0.2)
        p.drawRoundedRect(QRectF(r.center().x() - h * 0.28, r.top() + h * 0.64, h * 0.56, h * 0.5), h * 0.2, h * 0.2)
    p.restore()


# ============================================================================== overlay
class ArenaOverlay(QtWidgets.QWidget):
    def __init__(self, battle):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.B = battle
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Battle Arena")

    def show_on(self, g):
        self.setGeometry(g)
        self.show()

    def paintEvent(self, ev):
        B = self.B
        p = QtGui.QPainter(self)
        p.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.SmoothPixmapTransform
                         | QtGui.QPainter.RenderHint.TextAntialiasing)
        now = time.perf_counter()
        g = B.home
        try:
            p.save()
            sh = B.fx.shake
            p.translate(-g.left() + (math.sin(now * 91) * sh if sh > 0.3 else 0),
                        -g.top() + (math.cos(now * 77) * sh if sh > 0.3 else 0))
            self.paint_field(p, now)
            p.restore()
            p.translate(-g.left(), -g.top())
            self.paint_ui(p, now)
        except Exception:
            import traceback; traceback.print_exc()
        p.end()

    # ------------------------------------------------------------------ battlefield
    def paint_field(self, p, now):
        B = self.B
        l, t, r, b = B.rect
        if B.phase == "intro":
            a = clamp(1.0 - max(0.0, B.phase_t - 2.6) / 0.8, 0.0, 1.0)
            pen = QtGui.QPen(col(BLUE, 26 * a), 1)
            p.setPen(pen)
            step = B.size * 0.8
            x = l
            while x < r: p.drawLine(QPointF(x, t), QPointF(x, b)); x += step
            y = t
            while y < b: p.drawLine(QPointF(l, y), QPointF(r, y)); y += step
        for bx in B.win_boxes.values():
            paint_window_base(p, bx, now)
        for bx in B.props:
            paint_shadow(p, bx) if bx.alive else None
        # painter's order: everything by the screen y of its front edge
        items = []
        for bx in B.props:
            items.append((bx.b if bx.alive else bx.t - 9999, 0, bx))
        for f in B.fighters:
            if B.real_t < f.visible_t: continue
            down = f.state in ("down", "out")
            items.append((f.y - (B.size * 0.35 if down else 0.0), 1, f))
        for pr in B.projectiles:
            items.append((pr["y"], 2, pr))
        items.sort(key=lambda it: (it[0], it[1]))
        # shadows / team rings under everyone standing
        for _y, kind, obj in items:
            if kind == 1 and obj.state in ("alive", "getup"):
                f = obj
                p.setPen(NOPEN); p.setBrush(QtGui.QColor(10, 20, 40, 60))
                p.drawEllipse(QPointF(f.x, f.y), f.radius * 1.5, f.radius * 0.75)
                c = TEAM_COL[f.team]
                p.setPen(QtGui.QPen(col(c, 200), 2.2)); p.setBrush(col(c, 40))
                p.drawEllipse(QPointF(f.x, f.y), f.radius * 1.35, f.radius * 0.68)
                if f.target is not None and f.want_fire and B.phase == "fight":
                    a = math.atan2(f.target.y - f.y, f.target.x - f.x)
                    tip = QPointF(f.x + math.cos(a) * f.radius * 2.0, f.y + math.sin(a) * f.radius * 1.0)
                    p.setBrush(col(c, 200)); p.setPen(NOPEN)
                    p.drawPolygon(QtGui.QPolygonF([tip, QPointF(f.x + math.cos(a + 0.3) * f.radius * 1.4,
                                                               f.y + math.sin(a + 0.3) * f.radius * 0.7),
                                                   QPointF(f.x + math.cos(a - 0.3) * f.radius * 1.4,
                                                           f.y + math.sin(a - 0.3) * f.radius * 0.7)]))
        for _y, kind, obj in items:
            if kind == 0:
                paint_box(p, obj, now)
            elif kind == 1:
                self.paint_fighter(p, obj, now)
            else:
                self.paint_projectile(p, obj)
        B.fx.paint(p, now)

    def paint_fighter(self, p, f, now):
        B = self.B
        a = 1.0
        if f.alive and B.t < f.invuln_until:
            a = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(now * 28))
        if f.state == "out":
            a = 0.75
        appear = clamp((B.real_t - f.visible_t) / 0.35, 0.0, 1.0)
        if f.img is not None and f.img_rect is not None:
            x, y, w, h = f.img_rect
            p.save()
            p.setOpacity(a * appear)
            if appear < 1.0:
                s = ease_back(appear)
                p.translate(f.x, f.y); p.scale(0.85 + 0.15 * s, max(0.05, s)); p.translate(-f.x, -f.y)
            p.drawImage(QRectF(x, y, w, h), f.img)
            if f.flash_t > 0 and f.alive:
                p.setOpacity(min(1.0, f.flash_t * 6) * 0.55)
                p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Plus)
                p.drawImage(QRectF(x, y, w, h), f.img)
            p.restore()
        else:
            # no 3D render available: a BA token
            c = TEAM_COL[f.team]
            h = f.size * OBLIQUE
            p.setPen(QtGui.QPen(WHITE, 2)); p.setBrush(col(c, 230 * a))
            if f.state in ("down", "out"):
                p.drawEllipse(QPointF(f.x, f.y), f.radius * 1.8, f.radius * 0.9)
            else:
                p.drawRoundedRect(QRectF(f.x - f.radius, f.y - h, f.radius * 2, h), f.radius, f.radius)
            text(p, QRectF(f.x - 30, f.y - h * 0.7, 60, 20), f.name[:2], 13, WHITE, W_BLACK, True)
        if f.alive and B.t < f.shield_until:
            r = f.size * 0.55
            p.setPen(QtGui.QPen(col(CYAN, 200), 2)); p.setBrush(col(CYAN, 40))
            p.drawEllipse(QPointF(f.x, f.y - f.size * 0.4 * OBLIQUE), r, r)
        if f.alive and B.t < f.invuln_until:
            pen = QtGui.QPen(col(CYAN, 210), 2); pen.setDashPattern([3, 3]); pen.setDashOffset(-now * 20)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(f.x, f.y), f.radius * 1.7, f.radius * 0.85)
        if f.alive and B.t < f.buff_until:
            p.setPen(QtGui.QPen(col(YELLOW, 200), 2)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(f.x, f.y), f.radius * 1.9 + math.sin(now * 6) * 2, f.radius * 0.95)

    def paint_projectile(self, p, pr):
        if pr["t"] < 0: return
        x, y, h = pr["x"], pr["y"], max(0.0, pr["h"])
        p.setPen(NOPEN); p.setBrush(QtGui.QColor(10, 20, 40, 70))
        p.drawEllipse(QPointF(x, y), 5, 2.5)
        if pr["lob"]:
            p.setBrush(QtGui.QColor(255, 80, 60, 70)); p.setPen(QtGui.QPen(QtGui.QColor(255, 80, 60, 120), 1.5))
            rr = pr["radius"]
            p.drawEllipse(QPointF(pr["tx"], pr["ty"]), rr * 0.95, rr * 0.55)
        pts = [QPointF(tx, ty - th * OBLIQUE) for tx, ty, th in pr["trail"]]
        if len(pts) > 1:
            p.setPen(QtGui.QPen(QtGui.QColor(230, 230, 230, 120), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPolyline(QtGui.QPolygonF(pts))
        p.setPen(QtGui.QPen(QtGui.QColor(40, 40, 40), 1.2)); p.setBrush(QtGui.QColor(90, 100, 80))
        p.drawEllipse(QPointF(x, y - h * OBLIQUE), 5, 5)

    # ------------------------------------------------------------------ UI layer
    def paint_ui(self, p, now):
        B = self.B
        S = B.settings
        for f in B.fighters:
            if B.real_t < f.visible_t: continue
            if S["hp_bars"]: self.paint_bars(p, f, now)
        if S["team_panels"]:
            self.paint_panel(p, 0, now); self.paint_panel(p, 1, now)
        self.paint_killfeed(p, now)
        self.paint_banners(p, now)

    def paint_bars(self, p, f, now):
        B = self.B
        if f.state == "out": return
        top = f.y - f.size * OBLIQUE * 1.02
        w = f.size * 0.62
        r = QRectF(f.x - w / 2, top - 10, w, 7)
        c = TEAM_COL[f.team]
        if f.state in ("down", "getup"):
            k = clamp(f.down_t / max(0.1, B.settings["down_time"]), 0, 1) if f.state == "down" else 1.0
            cr = QPointF(f.x, f.y - f.size * 0.25)
            p.setPen(QtGui.QPen(col(NAVY_D, 120), 4)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(cr, 13, 13)
            p.setPen(QtGui.QPen(c, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(cr.x() - 13, cr.y() - 13, 26, 26), 90 * 16, int(-360 * 16 * k))
            text(p, QRectF(cr.x() - 40, cr.y() + 14, 80, 16), "DOWN", 10, WHITE, W_BLACK, True)
            return
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 170)); p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 3, 3)
        hpf = f.hp_frac()
        fill = QRectF(r.left(), r.top(), r.width() * hpf, r.height())
        cc = GREEN if hpf > 0.5 else (YELLOW if hpf > 0.25 else RED)
        p.setBrush(c if f.team == 0 else RED_T)
        p.drawRoundedRect(fill, 2.5, 2.5)
        p.setBrush(col(cc, 120)); p.drawRect(QRectF(fill.left(), fill.top(), fill.width(), 2))
        # lives (diamonds) and EX gauge
        n = f.lives
        for i in range(n):
            cx = r.left() + 5 + i * 9
            d = QtGui.QPolygonF([QPointF(cx, r.top() - 9), QPointF(cx + 3.5, r.top() - 5), QPointF(cx, r.top() - 1),
                                 QPointF(cx - 3.5, r.top() - 5)])
            p.setPen(QtGui.QPen(WHITE, 1)); p.setBrush(c); p.drawPolygon(d)
        if B.settings["ex_skills"]:
            ex = QRectF(r.left(), r.bottom() + 2, r.width() * f.ex, 2.5)
            p.setPen(NOPEN); p.setBrush(YELLOW if f.ex >= 1.0 else col(SKY, 230)); p.drawRect(ex)
        icon = None
        if f.reload_t > 0: icon = ("retry", GREY)
        elif f.ex_cast is not None: icon = ("flag", YELLOW_D)
        elif f.suppression > 0.6: icon = ("shield", ORANGE)
        if icon:
            glyph_icon(p, QPointF(r.right() + 9, r.center().y()), 6, icon[0], icon[1], 2)

    def paint_panel(self, p, team, now):
        B = self.B
        g = B.home
        fs = [f for f in B.fighters if f.team == team]
        if not fs: return
        w, h = 236.0, 54.0
        ax = g.left() + 14 if team == 0 else g.right() - 14        # the screen edge the panel hugs
        y = g.top() + 92
        # many students: shrink the whole panel so it never runs off the bottom of the screen
        # (the right panel also leaves room for the kill feed underneath it)
        avail = g.bottom() - 24 - y - (180 if team == 1 else 0)
        s = clamp(avail / max(1.0, len(fs) * (h + 6)), 0.45, 1.0)
        p.save()
        p.translate(ax, y); p.scale(s, s)
        x, y = (0.0 if team == 0 else -w), 0.0
        c = TEAM_COL[team]
        hd = QRectF(x, y - 30, w, 24)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 200)); p.drawPolygon(para(hd, 8))
        p.setBrush(c); p.drawPolygon(para(QRectF(hd.left() + 3, hd.top(), 8, hd.height()), 4))
        alive = sum(1 for f in fs if f.in_play)
        text(p, hd.adjusted(18, 0, -10, 0), TEAM_NAME[team], 12, WHITE, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.5)
        text(p, hd.adjusted(18, 0, -14, 0), f"{alive}/{len(fs)}", 12, YELLOW, W_BLACK, True, AF.AlignRight | AF.AlignVCenter)
        for i, f in enumerate(fs):
            r = QRectF(x, y + i * (h + 6), w, h)
            out = f.state == "out"
            p.save()
            p.setOpacity(0.55 if out else 0.95)
            p.setPen(QtGui.QPen(col(WHITE, 200), 1)); p.setBrush(col(WHITE, 225))
            p.drawPolygon(para(r, 10))
            pr = QRectF(r.left() + 12, r.top() + 4, h - 8, h - 8)
            portrait(p, f.entry, pr, 6)
            if out:
                p.setPen(QtGui.QPen(col(RED, 220), 3))
                p.drawLine(pr.topLeft(), pr.bottomRight()); p.drawLine(pr.topRight(), pr.bottomLeft())
            tx = pr.right() + 8
            text(p, QRectF(tx, r.top() + 3, w - (tx - r.left()) - 52, 18), f.name, 12, NAVY, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, elide=True)
            self.mini_chip(p, QRectF(r.right() - 44, r.top() + 5, 32, 14), f.st.short(), c)
            bar = QRectF(tx, r.top() + 24, w - (tx - r.left()) - 18, 7)
            p.setPen(NOPEN); p.setBrush(col(NAVY, 50)); p.drawRoundedRect(bar, 3, 3)
            if f.state == "alive":
                p.setBrush(GREEN if f.hp_frac() > 0.5 else YELLOW if f.hp_frac() > 0.25 else RED)
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * f.hp_frac(), bar.height()), 3, 3)
            if B.settings["ex_skills"] and f.state == "alive":
                exr = QRectF(bar.left(), bar.bottom() + 3, bar.width() * f.ex, 3)
                p.setBrush(YELLOW if f.ex >= 1 else col(BLUE, 160)); p.drawRect(exr)
            for k in range(int(B.settings["lives"])):
                cx = tx + 5 + k * 11
                cy = r.bottom() - 9
                d = QtGui.QPolygonF([QPointF(cx, cy - 4.5), QPointF(cx + 4, cy), QPointF(cx, cy + 4.5), QPointF(cx - 4, cy)])
                p.setPen(QtGui.QPen(col(NAVY, 120), 1)); p.setBrush(c if k < f.lives else col(GREY, 60)); p.drawPolygon(d)
            status = {"down": ("DOWN", ORANGE), "getup": ("RISING", CYAN), "out": ("RETIRE", RED)}.get(f.state)
            if status is None and f.state == "alive":
                if f.reload_t > 0: status = ("RELOAD", GREY)
                elif f.ex >= 1.0 and B.settings["ex_skills"]: status = ("EX", YELLOW_D)
                elif f.tactic in ("cover", "retreat", "flank", "heal", "advance", "engage"):
                    status = ({"cover": "COVER", "retreat": "RETREAT", "flank": "FLANK", "heal": "HEAL",
                               "advance": "PUSH", "engage": "FIRE"}[f.tactic], col(BLUE_D, 200))
            if status:
                self.mini_chip(p, QRectF(r.right() - 74, r.bottom() - 17, 62, 13), status[0], status[1], 8)
            p.restore()
        p.restore()

    @staticmethod
    def mini_chip(p, r, label, color, px=9):
        p.setPen(NOPEN); p.setBrush(color); p.drawPolygon(para(r, 4))
        text(p, r, label, px, WHITE, W_BLACK, True, AF.AlignCenter, 0.6)

    def paint_killfeed(self, p, now):
        B = self.B
        g = B.home
        y = g.bottom() - 40
        shown = 0
        for k in reversed(B.killfeed):
            age = B.real_t - k["t"]
            if age > 6.0: continue
            if shown >= 5: break                       # newest five only, so the feed can't pile up the screen
            shown += 1
            a = clamp(min(age * 4, (6.0 - age) * 2), 0, 1)
            r = QRectF(g.right() - 374, y - 30, 360, 28)
            p.save(); p.setOpacity(a)
            p.setPen(NOPEN); p.setBrush(col(NAVY_D, 190)); p.drawPolygon(para(r, 8))
            an = k["a"].name if k["a"] is not None else "?"
            ac = TEAM_COL[k["a"].team] if k["a"] is not None else GREY
            text(p, QRectF(r.left() + 14, r.top(), 150, r.height()), an, 12, ac.lighter(130), W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, elide=True)
            glyph_icon(p, QPointF(r.center().x() - 4, r.center().y()), 7, "cross", WHITE, 2)
            text(p, QRectF(r.center().x() + 10, r.top(), 164, r.height()), k["b"].name + ("  RETIRE" if k["out"] else ""),
                 12, TEAM_COL[k["b"].team].lighter(130), W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, elide=True)
            p.restore()
            y -= 34

    def paint_banners(self, p, now):
        B = self.B
        g = QRectF(B.home)
        cx, cy = g.center().x(), g.center().y()
        if B.phase == "intro" and B.phase_t > 0.6:
            n = 3 - int((B.phase_t - 0.6) / 0.9)
            f = ((B.phase_t - 0.6) % 0.9) / 0.9
            if n >= 1:
                s = 1.0 + (1 - ease_out(f * 2)) * 0.8
                p.save(); p.translate(cx, cy); p.scale(s, s); p.setOpacity(clamp(1.0 - f * 1.1, 0, 1))
                self.outlined(p, QRectF(-200, -90, 400, 180), str(n), 140, WHITE, NAVY)
                p.restore()
            text(p, QRectF(cx - 300, cy + 70, 600, 30), "STAND BY  \u00b7  \u4f5c\u6226\u958b\u59cb\u6e96\u5099", 16,
                 col(NAVY, 200), W_BLACK, True, AF.AlignCenter, 3)
        for bn in B.banners:
            k = bn["kind"]; t = bn["t"]
            if k == "start":
                self.strip_banner(p, g, t, bn["life"], "BATTLE START", "\u6226\u95d8\u958b\u59cb", YELLOW)
            elif k == "end":
                w = B.winner
                if w in (0, 1):
                    self.strip_banner(p, g, t, 99, f"{TEAM_NAME[w]} WINS", "VICTORY  \u00b7  \u52dd\u5229", TEAM_COL[w],
                                      hold=True)
                else:
                    self.strip_banner(p, g, t, 99, "DRAW", "\u5f15\u304d\u5206\u3051", GREY, hold=True)
            elif k == "ex":
                self.ex_cutin(p, g, bn)
            elif k == "out":
                f = bn["f"]
                a = clamp(min(t * 5, (bn["life"] - t) * 3), 0, 1)
                r = QRectF(cx - 150, g.top() + 166, 300, 34)       # below the last-10-seconds countdown
                p.save(); p.setOpacity(a)
                p.setPen(NOPEN); p.setBrush(col(RED, 220)); p.drawPolygon(para(r, 10))
                text(p, r, f"RETIRE  \u00b7  {f.name}", 15, WHITE, W_BLACK, True, AF.AlignCenter, 1.5)
                p.restore()
        tl = B.time_left()
        if tl is not None and tl < 10 and B.phase == "fight":
            self.outlined(p, QRectF(cx - 100, g.top() + 96, 200, 60), f"{tl:.0f}", 44, RED, WHITE)

    @staticmethod
    def outlined(p, r, s, px, fill, line):
        fnt = font(px, W_BLACK, True)
        path = QtGui.QPainterPath()
        fm = QtGui.QFontMetricsF(fnt)
        w = fm.horizontalAdvance(s)
        path.addText(r.center().x() - w / 2, r.center().y() + fm.ascent() * 0.36, fnt, s)
        p.setPen(QtGui.QPen(line, max(3.0, px * 0.07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        p.setPen(NOPEN); p.setBrush(fill); p.drawPath(path)

    def strip_banner(self, p, g, t, life, title, sub, accent, hold=False):
        cx, cy = g.center().x(), g.center().y()
        a_in = ease_out(t / 0.3)
        a_out = 1.0 if hold else clamp((life - t) / 0.35, 0, 1)
        h = 120 * a_in
        r = QRectF(g.left(), cy - h / 2, g.width(), h)
        p.save(); p.setOpacity(a_out)
        gr = QtGui.QLinearGradient(r.topLeft(), r.topRight())
        gr.setColorAt(0, col(NAVY_D, 0)); gr.setColorAt(0.2, col(NAVY_D, 215)); gr.setColorAt(0.8, col(NAVY_D, 215))
        gr.setColorAt(1, col(NAVY_D, 0))
        p.fillRect(r, gr)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 3), col(accent, 230))
        p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width(), 3), col(accent, 230))
        slide = (1 - ease_out(t / 0.45)) * 300
        self.outlined(p, QRectF(cx - 500 + slide, cy - 50, 1000, 70), title, 58, accent, NAVY_D)
        text(p, QRectF(cx - 400 - slide, cy + 14, 800, 30), sub, 16, WHITE, W_BLACK, True, AF.AlignCenter, 4)
        p.restore()

    def ex_cutin(self, p, g, bn):
        f = bn["f"]; t = bn["t"]; life = bn["life"]
        a = clamp(min(t / 0.18, (life - t) / 0.3), 0, 1)
        left = f.team == 0
        w, h = 520.0, 110.0
        slide = (1 - ease_out(t / 0.3)) * w
        x = g.left() + 20 - slide if left else g.right() - 20 - w + slide
        y = g.bottom() - 220
        r = QRectF(x, y, w, h)
        c = TEAM_COL[f.team]
        p.save(); p.setOpacity(a)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 225)); p.drawPolygon(para(r, 26))
        p.setBrush(c); p.drawPolygon(para(QRectF(r.left() + (12 if left else r.width() - 30), r.top(), 18, h), 8))
        pr = QRectF(r.left() + 40, r.top() + 8, h - 16, h - 16) if left else QRectF(r.right() - 40 - (h - 16), r.top() + 8, h - 16, h - 16)
        portrait(p, f.entry, pr, 10)
        tx = QRectF(pr.right() + 16, r.top() + 10, w - h - 70, h - 20) if left else QRectF(r.left() + 36, r.top() + 10, w - h - 70, h - 20)
        en, jp = f.st.ex_name
        text(p, QRectF(tx.left(), tx.top(), tx.width(), 20), "EX SKILL", 12, YELLOW, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 3)
        text(p, QRectF(tx.left(), tx.top() + 18, tx.width(), 40), en, 26, WHITE, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, elide=True)
        text(p, QRectF(tx.left(), tx.top() + 58, tx.width(), 22), f"{f.name}  \u00b7  {jp}", 13, col(SKY, 230), W_BOLD,
             False, AF.AlignLeft | AF.AlignVCenter, 1.5, elide=True)
        p.restore()


# ============================================================================== HUD bar
class ArenaHUD(BAWindow):
    MARGIN = 8
    RADIUS = 14

    def __init__(self, battle):
        super().__init__(battle.mgr, 720, 78, "Battle Arena HUD", tool=True)
        self.B = battle
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def place(self):
        g = self.B.home
        self.resize(self.base_w, self.base_h)
        self.move(g.center().x() - self.base_w // 2, g.top() + 6)

    def _tick(self):
        pass                                # the battle repaints it

    def open(self):
        self.place(); self.setWindowOpacity(1.0); self.show(); self.raise_()

    def on_escape(self):
        self.mgr.pause_menu()

    def paint_bg(self, p, R, now, tint=None):
        g = QtGui.QLinearGradient(R.topLeft(), R.bottomLeft())
        g.setColorAt(0, col(WHITE, 248)); g.setColorAt(1, QtGui.QColor(228, 242, 255, 245))
        p.fillRect(R, g)

    def paint_content(self, p, R, now):
        B = self.B
        cx = R.center().x()
        for team in (0, 1):
            fs = [f for f in B.fighters if f.team == team]
            lives = sum(max(0, f.lives) for f in fs)
            alive = sum(1 for f in fs if f.in_play)
            c = TEAM_COL[team]
            w = 200.0
            r = QRectF(R.left() + 10, R.top() + 10, w, R.height() - 20) if team == 0 else \
                QRectF(R.right() - 10 - w - 150, R.top() + 10, w, R.height() - 20)
            p.setPen(NOPEN); p.setBrush(c); p.drawPolygon(para(r, 12))
            text(p, r.adjusted(16, 2, -12, -r.height() * 0.45), TEAM_NAME[team], 13, WHITE, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, 1.4)
            text(p, r.adjusted(16, r.height() * 0.45, -12, -2), f"{alive} standing  \u00b7  {lives} lives", 11,
                 col(WHITE, 230), W_BOLD, False, AF.AlignLeft | AF.AlignVCenter)
        tr = QRectF(R.left() + 222, R.top() + 6, R.width() - 222 - 372, R.height() - 12)
        tl = B.time_left()
        tt = tl if tl is not None else B.t
        mm, ss = int(tt // 60), int(tt % 60)
        text(p, QRectF(tr.left(), tr.top(), tr.width(), tr.height() * 0.62), f"{mm:02d}:{ss:02d}", 26,
             RED if (tl is not None and tl < 10) else NAVY, W_BLACK, True)
        ph = {"intro": "STAND BY", "fight": "PAUSED" if B.paused else "IN COMBAT", "end": "MATCH OVER"}[B.phase]
        text(p, QRectF(tr.left(), tr.top() + tr.height() * 0.56, tr.width(), tr.height() * 0.4), ph, 10, BLUE_D, W_BLACK,
             True, AF.AlignCenter, 2.4)
        bx = R.right() - 150
        for i, (key, icon, tip) in enumerate(((("pause",), "play" if B.paused else "pause", ""),
                                              (("speed",), "speed", ""), (("stop",), "stop", ""))):
            r = QRectF(bx + i * 48, R.center().y() - 19, 40, 38)
            hov = self.hover == key
            acc = RED if key == ("stop",) else BLUE
            p.setPen(QtGui.QPen(col(acc, 160 if hov else 90), 1.4)); p.setBrush(acc if hov else col(WHITE, 250))
            p.drawRoundedRect(r, 9, 9)
            glyph_icon(p, r.center(), 11, icon, WHITE if hov else acc, 2.6)
            if key == ("speed",):
                text(p, QRectF(r.left(), r.bottom() - 13, r.width(), 12), f"x{B.speed:g}", 8, WHITE if hov else NAVY,
                     W_BLACK, True)
            self.hits.append((r, key))

    def on_click(self, key, right=False):
        B = self.B
        if key[0] == "pause":
            B.set_paused(not B.paused)
        elif key[0] == "speed":
            seq = [0.5, 1.0, 1.5, 2.0]
            i = min(range(len(seq)), key=lambda k: abs(seq[k] - B.speed))
            B.speed = seq[(i + (-1 if right else 1)) % len(seq)]
        elif key[0] == "stop":
            self.mgr.pause_menu()


# ============================================================================== pause menu
class PauseMenu(BAWindow):
    def __init__(self, mgr):
        super().__init__(mgr, 560, 520, "Battle Arena - Paused", tool=True)

    def on_escape(self):
        self.mgr.resume()

    def paint_content(self, p, R, now):
        self.header(p, R, "Paused", "\u4f5c\u6226\u4e2d\u65ad  \u00b7  OPERATION ON HOLD", back=False)
        B = self.mgr.battle
        y = R.top() + 92
        if B is not None:
            for team in (0, 1):
                fs = [f for f in B.fighters if f.team == team]
                r = QRectF(R.left() + 30, y + team * 34, R.width() - 60, 28)
                p.setPen(NOPEN); p.setBrush(col(TEAM_COL[team], 40)); p.drawPolygon(para(r, 8))
                p.setBrush(TEAM_COL[team]); p.drawPolygon(para(QRectF(r.left() + 2, r.top(), 8, r.height()), 4))
                text(p, r.adjusted(18, 0, 0, 0), TEAM_NAME[team], 12, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.2)
                text(p, r.adjusted(0, 0, -14, 0),
                     f"{sum(1 for f in fs if f.in_play)}/{len(fs)} standing  \u00b7  {sum(max(0, f.lives) for f in fs)} lives",
                     12, NAVY, W_BOLD, False, AF.AlignRight | AF.AlignVCenter)
        y += 86
        bw, bh = R.width() - 120, 54
        x = R.left() + 60
        self.big_button(p, QRectF(x, y, bw, bh), "RESUME", "\u4f5c\u6226\u518d\u958b  \u00b7  back to the fight", ("resume",), now)
        y += bh + 18
        for key, label, icon, acc in ((("restart",), "Restart Match", "retry", BLUE),
                                      (("lobby",), "Arena Menu", "flag", BLUE),
                                      (("title",), "Title Screen", "home", ORANGE)):
            self.button(p, QRectF(x + 10, y, bw - 20, 46), label, key, accent=acc, px=16, icon=icon)
            y += 58

    def on_click(self, key, right=False):
        k = key[0]
        if k == "resume": self.mgr.resume()
        elif k == "restart": self.mgr.rematch()
        elif k == "lobby": self.mgr.to_lobby()
        elif k == "title": self.mgr.to_title()


# ============================================================================== results
class ResultScreen(BAWindow):
    ROW_H = 48.0                    # a student's stat row is always this tall; extra rows scroll instead
    ROW_GAP = 4.0
    SB_W = 8.0

    def __init__(self, mgr):
        super().__init__(mgr, 1060, 680, "Battle Arena - Results", tool=True)
        self.snapshot = None
        self._reset_scroll()

    def _reset_scroll(self):
        self.scroll = [0.0, 0.0]            # per team column
        self.scroll_target = [0.0, 0.0]
        self.max_scroll = [0.0, 0.0]
        self.viewports = {}                 # team -> rows viewport (set while painting)
        self.tracks = {}
        self.thumbs = {}
        self.sb_drag = None                 # (team, grab offset inside the thumb)

    def on_open(self):
        self._reset_scroll()

    def tick(self, now):
        for t in (0, 1):
            self.scroll_target[t] = clamp(self.scroll_target[t], 0.0, self.max_scroll[t])
            d = self.scroll_target[t] - self.scroll[t]
            self.scroll[t] = self.scroll_target[t] if abs(d) < 0.3 else self.scroll[t] + d * 0.3
            self.scroll[t] = clamp(self.scroll[t], 0.0, self.max_scroll[t])

    def set_battle(self, B):
        mvp = B.mvp()
        rows = []
        for f in B.fighters:
            rows.append(dict(entry=f.entry, name=f.name, team=f.team, kills=f.rec["kills"], downs=f.rec["downs"],
                             dmg=f.rec["dmg"], heal=f.rec["heal"], ex=f.rec["ex"], out=f.state == "out",
                             weapon=f.st.short(), role=f.st.role, mvp=f is mvp,
                             acc=(f.rec["hits"] / max(1, f.rec["shots"])) if f.rec["shots"] else None))
        self.snapshot = dict(winner=B.winner, rows=rows, t=B.t)
        self._reset_scroll()

    def on_escape(self):
        self.mgr.to_lobby()

    def paint_content(self, p, R, now):
        s = self.snapshot
        if s is None: return
        w = s["winner"]
        accent = TEAM_COL.get(w, GREY)
        T, _ = self.header(p, R, "Battle Result", "\u6226\u95d8\u7d50\u679c  \u00b7  TACTICAL CHALLENGE REPORT", back=False)
        ban = QRectF(R.left(), T.bottom(), R.width(), 118)
        g = QtGui.QLinearGradient(ban.topLeft(), ban.topRight())
        g.setColorAt(0, col(accent, 235)); g.setColorAt(1, col(TEAM_COL_D.get(w, NAVY), 235))
        p.fillRect(ban, g)
        p.setPen(QtGui.QPen(col(WHITE, 40), 10))
        k = ((now * 60) % 80)
        x = ban.left() - 200 + k
        while x < ban.right():
            p.drawLine(QPointF(x, ban.bottom()), QPointF(x + 80, ban.top())); x += 80
        title = "VICTORY" if w in (0, 1) else "DRAW"
        sub = f"{TEAM_NAME[w]} WINS" if w in (0, 1) else "BOTH TEAMS FELL"
        pop = ease_back(clamp((now - self.t_open) / 0.5, 0, 1))
        p.save(); p.translate(ban.left() + 40, ban.center().y()); p.scale(pop, pop)
        ArenaOverlay.outlined(p, QRectF(0, -50, 420, 70), title, 64, WHITE, NAVY_D)
        p.restore()
        text(p, QRectF(ban.left() + 44, ban.center().y() + 14, 500, 30), sub + "  \u00b7  \u52dd\u5229" if w in (0, 1) else sub,
             16, col(WHITE, 235), W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 3)
        mm, ss = int(s["t"] // 60), int(s["t"] % 60)
        text(p, QRectF(ban.right() - 300, ban.top() + 20, 270, 30), f"BATTLE TIME  {mm:02d}:{ss:02d}", 15, WHITE,
             W_BLACK, True, AF.AlignRight | AF.AlignVCenter, 2)
        mvp = next((r for r in s["rows"] if r["mvp"]), None)
        if mvp is not None:
            mr = QRectF(ban.right() - 300, ban.top() + 56, 270, 46)
            p.setPen(NOPEN); p.setBrush(col(WHITE, 235)); p.drawPolygon(para(mr, 12))
            portrait(p, mvp["entry"], QRectF(mr.left() + 14, mr.top() + 4, 38, 38), 6)
            self.chip(p, QRectF(mr.left() + 60, mr.top() + 6, 46, 16), "MVP", YELLOW_D)
            text(p, QRectF(mr.left() + 60, mr.top() + 22, 190, 20), mvp["name"], 14, NAVY, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, elide=True)
        # tables
        top = ban.bottom() + 16
        colw = (R.width() - 60) / 2
        F = QRectF(R.left(), R.bottom() - 80, R.width(), 80)
        rh, step = self.ROW_H, self.ROW_H + self.ROW_GAP
        self.viewports, self.tracks, self.thumbs = {}, {}, {}
        for team in (0, 1):
            x = R.left() + 20 + team * (colw + 20)
            rows = [r for r in s["rows"] if r["team"] == team]
            hr = QRectF(x, top, colw, 30)
            vp = QRectF(x, top + 36, colw, max(0.0, F.top() - 10 - (top + 36)))
            content = len(rows) * step
            self.max_scroll[team] = max(0.0, content - vp.height())
            scrolls = self.max_scroll[team] > 0
            rw = colw - (self.SB_W + 8 if scrolls else 0.0)          # rows leave room for the scroll bar
            self.scroll[team] = clamp(self.scroll[team], 0.0, self.max_scroll[team])
            p.setPen(NOPEN); p.setBrush(TEAM_COL[team]); p.drawPolygon(para(hr, 10))
            text(p, hr.adjusted(18, 0, 0, 0), TEAM_NAME[team] + ("  \u2605 WIN" if w == team else ""), 13, WHITE,
                 W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.5)
            heads = (("K", 0.52), ("DOWN", 0.62), ("DMG", 0.75), ("HEAL", 0.89))
            for h, fx in heads:
                text(p, QRectF(x + rw * fx - 40, top, 80, 30), h, 10, col(WHITE, 230), W_BLACK, True)
            self.viewports[team] = vp
            p.save(); p.setClipRect(vp, Qt.ClipOperation.IntersectClip)
            y = vp.top() - self.scroll[team]
            for r in rows:
                if y + rh < vp.top() or y > vp.bottom():
                    y += step; continue
                rr = QRectF(x, y, rw, rh)
                p.setPen(QtGui.QPen(col(BLUE, 40), 1)); p.setBrush(col(WHITE, 225 if not r["out"] else 175))
                p.drawRoundedRect(rr, 8, 8)
                portrait(p, r["entry"], QRectF(rr.left() + 6, rr.top() + 4, rh - 8, rh - 8), 6)
                text(p, QRectF(rr.left() + rh + 4, rr.top() + 2, rw * 0.3, rh * 0.55), r["name"], 13, NAVY, W_BLACK, True,
                     AF.AlignLeft | AF.AlignVCenter, elide=True)
                text(p, QRectF(rr.left() + rh + 4, rr.top() + rh * 0.5, rw * 0.32, rh * 0.45),
                     f"{r['weapon']} \u00b7 {r['role']}" + (f" \u00b7 {r['acc'] * 100:.0f}% acc" if r["acc"] is not None else ""),
                     9, GREY, W_BOLD, False, AF.AlignLeft | AF.AlignVCenter, elide=True)
                vals = (str(r["kills"]), str(r["downs"]), f"{int(r['dmg']):,}", f"{int(r['heal']):,}" if r["heal"] else "-")
                for (h, fx), v in zip(heads, vals):
                    text(p, QRectF(x + rw * fx - 50, rr.top(), 100, rh), v, 14, NAVY, W_BLACK, True)
                if r["mvp"]:
                    self.chip(p, QRectF(rr.right() - 46, rr.top() + 2, 40, 14), "MVP", YELLOW_D, px=9)
                y += step
            p.restore()
            if scrolls:
                track = QRectF(x + colw - self.SB_W, vp.top(), self.SB_W, vp.height())
                th_h = max(34.0, vp.height() * vp.height() / content)
                th_y = track.top() + (track.height() - th_h) * (self.scroll[team] / self.max_scroll[team])
                thumb = QRectF(track.left(), th_y, track.width(), th_h)
                self.tracks[team], self.thumbs[team] = track, thumb
                grabbed = self.sb_drag is not None and self.sb_drag[0] == team
                p.setPen(NOPEN); p.setBrush(col(NAVY, 30)); p.drawRoundedRect(track, 4, 4)
                p.setBrush(col(TEAM_COL[team], 230 if grabbed else 170)); p.drawRoundedRect(thumb, 4, 4)
        # buttons
        p.fillRect(F, col(WHITE, 236)); p.fillRect(QRectF(F.left(), F.top(), F.width(), 1.5), col(BLUE, 60))
        cy = F.center().y()
        self.big_button(p, QRectF(F.right() - 30 - 260, cy - 28, 260, 56), "REMATCH", "\u518d\u6226  \u00b7  same teams & rules",
                        ("rematch",), now)
        self.button(p, QRectF(F.right() - 30 - 260 - 20 - 200, cy - 22, 200, 44), "Arena Menu", ("lobby",), px=15, icon="flag")
        self.button(p, QRectF(F.right() - 30 - 260 - 20 - 200 - 14 - 200, cy - 22, 200, 44), "Title Screen", ("title",),
                    accent=ORANGE, px=15, icon="home")

    # ------------------------------------------------------------------ scrolling input
    def on_wheel(self, d, pos):
        t = 0 if pos.x() < self.width() / 2 else 1
        for k, vp in self.viewports.items():            # the column under the cursor scrolls
            if vp.adjusted(0, -36, 0, 0).contains(pos): t = k
        self.scroll_target[t] = clamp(self.scroll_target[t] - d * 0.6, 0.0, self.max_scroll[t])

    def _drag_scroll(self, y):
        t, off = self.sb_drag
        track, thumb = self.tracks.get(t), self.thumbs.get(t)
        if track is None or thumb is None: return
        travel = max(1.0, track.height() - thumb.height())
        f = clamp((y - off - track.top()) / travel, 0.0, 1.0)
        self.scroll_target[t] = self.scroll[t] = f * self.max_scroll[t]

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position()
            for t, track in self.tracks.items():
                if track.adjusted(-6, 0, 6, 0).contains(pos):
                    thumb = self.thumbs[t]
                    self.sb_drag = (t, pos.y() - thumb.top() if thumb.contains(pos) else thumb.height() / 2)
                    self._drag_scroll(pos.y())
                    self.press = None
                    return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self.sb_drag is not None:
            self._drag_scroll(ev.position().y()); return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.sb_drag is not None:
            self.sb_drag = None; self.press = None; return
        super().mouseReleaseEvent(ev)

    def on_click(self, key, right=False):
        k = key[0]
        if k == "rematch": self.mgr.rematch()
        elif k == "lobby": self.mgr.to_lobby()
        elif k == "title": self.mgr.to_title()
