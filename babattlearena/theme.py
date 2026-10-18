"""Blue Archive look for every Battle Arena screen.

The palette and the small drawing helpers are the Student Select ones (bapet/picker.py), so
the arena reads as the same game. On top of that this module adds:

    BAWindow     a frameless, translucent, hand-painted window with the picker's frame, a hit
                 list (hover / press / click / right-click), drag-by-title-bar, fade in / out
                 and a 30 fps repaint timer while it is visible. Every arena screen (title,
                 lobby, settings, pause menu, results, HUD bar) is one of these.
    button()     the white slanted BA button with its coloured edge
    big_button() the yellow primary button (DEPLOY / BEGIN BATTLE)
    header()     the top bar: back arrow, yellow tick, title + small caps subtitle, close
    toggle() / stepper() / chip()   settings controls
"""
from __future__ import annotations

import math
import random
import time
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer

from bapet.picker import (AF, BLUE, BLUE_D, CYAN, GREEN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PINK, RED,
                          SKY, WHITE, YELLOW, YELLOW_D, YELLOW_L, clamp, col, ease_back, ease_out, font,
                          para, poly_path, rounded, spinner, text)

__all__ = ["AF", "BLUE", "BLUE_D", "CYAN", "GREEN", "GREY", "NAVY", "NAVY_D", "NOPEN", "ORANGE", "PINK",
           "RED", "SKY", "WHITE", "YELLOW", "YELLOW_D", "YELLOW_L", "clamp", "col", "ease_back", "ease_out",
           "font", "para", "poly_path", "rounded", "spinner", "text", "TEAM_COL", "TEAM_COL_D", "TEAM_NAME",
           "TEAM_SUB", "RED_T", "RED_TD", "PURPLE", "BAWindow", "W_BLACK", "W_BOLD", "W_DEMI", "glyph_icon"]

RED_T = QtGui.QColor(255, 76, 104)          # the red team (a touch warmer than the danger red)
RED_TD = QtGui.QColor(200, 34, 66)
PURPLE = QtGui.QColor(150, 110, 255)
TEAM_COL = {0: BLUE, 1: RED_T}
TEAM_COL_D = {0: BLUE_D, 1: RED_TD}
TEAM_NAME = {0: "BLUE TEAM", 1: "RED TEAM"}
TEAM_SUB = {0: "\u9752\u7d44  \u00b7  SCHALE", 1: "\u8d64\u7d44  \u00b7  OPPOSITION"}

W_BLACK = QtGui.QFont.Weight.Black
W_BOLD = QtGui.QFont.Weight.Bold
W_DEMI = QtGui.QFont.Weight.DemiBold


def glyph_icon(p, c, r, kind, color=WHITE, width=2.6):
    """Tiny vector icons drawn with the painter (no image files needed)."""
    p.save()
    pen = QtGui.QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    x, y = c.x(), c.y()
    if kind == "gear":
        p.drawEllipse(c, r * 0.42, r * 0.42)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(x + math.cos(a) * r * 0.62, y + math.sin(a) * r * 0.62),
                       QPointF(x + math.cos(a) * r * 0.95, y + math.sin(a) * r * 0.95))
    elif kind == "pause":
        p.drawLine(QPointF(x - r * 0.3, y - r * 0.55), QPointF(x - r * 0.3, y + r * 0.55))
        p.drawLine(QPointF(x + r * 0.3, y - r * 0.55), QPointF(x + r * 0.3, y + r * 0.55))
    elif kind == "play":
        p.setBrush(color); p.setPen(NOPEN)
        p.drawPolygon(QtGui.QPolygonF([QPointF(x - r * 0.4, y - r * 0.6), QPointF(x + r * 0.6, y),
                                       QPointF(x - r * 0.4, y + r * 0.6)]))
    elif kind == "stop":
        p.setBrush(color); p.setPen(NOPEN)
        p.drawRoundedRect(QRectF(x - r * 0.5, y - r * 0.5, r, r), 2, 2)
    elif kind == "back":
        p.drawPolyline(QtGui.QPolygonF([QPointF(x + r * 0.35, y - r * 0.6), QPointF(x - r * 0.3, y),
                                        QPointF(x + r * 0.35, y + r * 0.6)]))
    elif kind == "close":
        p.drawLine(QPointF(x - r * 0.5, y - r * 0.5), QPointF(x + r * 0.5, y + r * 0.5))
        p.drawLine(QPointF(x + r * 0.5, y - r * 0.5), QPointF(x - r * 0.5, y + r * 0.5))
    elif kind == "heart":
        path = QtGui.QPainterPath()
        path.moveTo(x, y + r * 0.7)
        path.cubicTo(x - r * 1.1, y - r * 0.1, x - r * 0.5, y - r * 0.95, x, y - r * 0.35)
        path.cubicTo(x + r * 0.5, y - r * 0.95, x + r * 1.1, y - r * 0.1, x, y + r * 0.7)
        p.setBrush(color); p.setPen(NOPEN); p.drawPath(path)
    elif kind == "cross":                      # crossed rifles / swords: the battle mark
        p.drawLine(QPointF(x - r * 0.75, y - r * 0.75), QPointF(x + r * 0.75, y + r * 0.75))
        p.drawLine(QPointF(x + r * 0.75, y - r * 0.75), QPointF(x - r * 0.75, y + r * 0.75))
        p.drawLine(QPointF(x - r * 0.75, y - r * 0.35), QPointF(x - r * 0.35, y - r * 0.75))
        p.drawLine(QPointF(x + r * 0.75, y - r * 0.35), QPointF(x + r * 0.35, y - r * 0.75))
    elif kind == "target":
        p.drawEllipse(c, r * 0.8, r * 0.8); p.drawEllipse(c, r * 0.4, r * 0.4)
        p.drawLine(QPointF(x, y - r), QPointF(x, y - r * 0.55)); p.drawLine(QPointF(x, y + r), QPointF(x, y + r * 0.55))
        p.drawLine(QPointF(x - r, y), QPointF(x - r * 0.55, y)); p.drawLine(QPointF(x + r, y), QPointF(x + r * 0.55, y))
    elif kind == "shuffle":
        p.drawLine(QPointF(x - r * 0.8, y - r * 0.45), QPointF(x + r * 0.8, y + r * 0.45))
        p.drawLine(QPointF(x - r * 0.8, y + r * 0.45), QPointF(x + r * 0.8, y - r * 0.45))
        p.drawPolyline(QtGui.QPolygonF([QPointF(x + r * 0.45, y + r * 0.6), QPointF(x + r * 0.8, y + r * 0.45),
                                        QPointF(x + r * 0.6, y + r * 0.1)]))
        p.drawPolyline(QtGui.QPolygonF([QPointF(x + r * 0.45, y - r * 0.6), QPointF(x + r * 0.8, y - r * 0.45),
                                        QPointF(x + r * 0.6, y - r * 0.1)]))
    elif kind == "flag":
        p.drawLine(QPointF(x - r * 0.5, y + r * 0.8), QPointF(x - r * 0.5, y - r * 0.8))
        p.setBrush(color)
        p.drawPolygon(QtGui.QPolygonF([QPointF(x - r * 0.5, y - r * 0.8), QPointF(x + r * 0.7, y - r * 0.45),
                                       QPointF(x - r * 0.5, y - r * 0.1)]))
    elif kind == "speed":
        for k in (-0.45, 0.25):
            p.drawPolyline(QtGui.QPolygonF([QPointF(x + r * k, y - r * 0.55), QPointF(x + r * (k + 0.45), y),
                                            QPointF(x + r * k, y + r * 0.55)]))
    elif kind == "home":
        p.drawPolyline(QtGui.QPolygonF([QPointF(x - r * 0.75, y), QPointF(x, y - r * 0.7), QPointF(x + r * 0.75, y)]))
        p.drawRect(QRectF(x - r * 0.5, y - r * 0.1, r, r * 0.75))
    elif kind == "retry":
        p.drawArc(QRectF(x - r * 0.65, y - r * 0.65, r * 1.3, r * 1.3), 40 * 16, 290 * 16)
        p.drawPolyline(QtGui.QPolygonF([QPointF(x + r * 0.62, y - r * 0.75), QPointF(x + r * 0.55, y - r * 0.3),
                                        QPointF(x + r * 0.1, y - r * 0.38)]))
    elif kind == "shield":
        path = QtGui.QPainterPath()
        path.moveTo(x, y - r * 0.85); path.lineTo(x + r * 0.7, y - r * 0.55)
        path.cubicTo(x + r * 0.7, y + r * 0.2, x + r * 0.35, y + r * 0.6, x, y + r * 0.85)
        path.cubicTo(x - r * 0.35, y + r * 0.6, x - r * 0.7, y + r * 0.2, x - r * 0.7, y - r * 0.55)
        path.closeSubpath(); p.drawPath(path)
    elif kind == "cross_med":                 # healer plus
        p.setBrush(color); p.setPen(NOPEN)
        p.drawRect(QRectF(x - r * 0.22, y - r * 0.7, r * 0.44, r * 1.4))
        p.drawRect(QRectF(x - r * 0.7, y - r * 0.22, r * 1.4, r * 0.44))
    p.restore()


class BAWindow(QtWidgets.QWidget):
    """A hand-painted Blue Archive window. Subclasses implement paint_content() and on_click()."""

    MARGIN = 16
    RADIUS = 16
    FPS = 30

    def __init__(self, mgr, w, h, title="Blue Archive", tool=False, modal_top=True):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        flags |= Qt.WindowType.Tool if tool else Qt.WindowType.Window
        super().__init__(None, flags)
        self.mgr = mgr
        self.app = mgr.app
        self.base_w, self.base_h = w, h
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(title)
        self.hits = []
        self.hover = None
        self.press = None
        self.drag_origin = None
        self.t_open = time.perf_counter()
        self._closing = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(self._fade_done)
        rnd = random.Random(id(self) & 0xffff)
        self.shapes = [(rnd.random(), rnd.random(), rnd.uniform(10, 40), rnd.uniform(0.004, 0.015),
                        rnd.uniform(0, 360), rnd.uniform(-26, 26), rnd.randint(14, 40)) for _ in range(16)]
        try:
            tray = getattr(self.app, "tray", None)
            if tray is not None: self.setWindowIcon(tray.icon())
        except Exception:
            pass
        self.app.qapp.aboutToQuit.connect(self.timer.stop)

    # ------------------------------------------------------------ open / close
    def home(self):
        try: return self.app.resolve_screen()
        except Exception: return self.app.qapp.primaryScreen().availableGeometry()

    def place(self):
        g = self.home()
        w = int(min(self.base_w, g.width() * 0.96)); h = int(min(self.base_h, g.height() * 0.95))
        self.resize(w, h)
        self.move(g.center().x() - w // 2, g.center().y() - h // 2)

    def open(self):
        if not self.isVisible() or self._closing:
            self.place()
            self._closing = False
            self.t_open = time.perf_counter()
            self.hover = self.press = self.drag_origin = None
            self.fade.stop()
            self.setWindowOpacity(0.0)
            self.show()
            self.fade.setDuration(260); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start()
            self.timer.start(int(1000 / self.FPS))
            self.on_open()
        self.raise_(); self.activateWindow(); self.setFocus()

    def on_open(self):
        pass

    def closing(self):
        return self._closing

    def close_animated(self):
        if not self.isVisible() or self._closing: return
        self._closing = True
        self.fade.stop()
        self.fade.setDuration(170); self.fade.setStartValue(self.windowOpacity()); self.fade.setEndValue(0.0)
        self.fade.start()

    def _fade_done(self):
        if self._closing:
            self._closing = False
            self.hide()

    def closeEvent(self, ev):
        ev.ignore()
        self.on_escape()

    def hideEvent(self, ev):
        self.timer.stop()
        super().hideEvent(ev)

    def on_escape(self):
        self.close_animated()

    def _tick(self):
        if self.isVisible():
            self.tick(time.perf_counter())
            self.update()

    def tick(self, now):
        pass

    # ------------------------------------------------------------ painting
    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.SmoothPixmapTransform
                         | QtGui.QPainter.RenderHint.TextAntialiasing)
        now = time.perf_counter()
        self.hits = []
        M = self.MARGIN
        R = QRectF(self.rect()).adjusted(M, M, -M, -M)
        p.setPen(NOPEN)
        for i in range(M, 0, -2):
            p.setBrush(col(NAVY_D, 3 + (M - i) * 0.9))
            p.drawRoundedRect(R.adjusted(-i, -i + 4, i, i + 4), self.RADIUS + i, self.RADIUS + i)
        frame = rounded(R, self.RADIUS)
        p.setClipPath(frame)
        try:
            self.paint_bg(p, R, now)
            self.paint_content(p, R, now)
        except Exception:
            traceback.print_exc()
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(col(WHITE, 220), 1.5)); p.drawPath(frame)
        p.setPen(QtGui.QPen(col(BLUE, 70), 1)); p.drawRoundedRect(R.adjusted(-1, -1, 1, 1), self.RADIUS + 1, self.RADIUS + 1)
        p.end()

    def paint_bg(self, p, R, now, tint=None):
        g = QtGui.QLinearGradient(R.topLeft(), R.bottomRight())
        g.setColorAt(0, QtGui.QColor(247, 252, 255)); g.setColorAt(0.55, QtGui.QColor(233, 246, 255))
        g.setColorAt(1, QtGui.QColor(219, 238, 253))
        p.fillRect(R, g)
        p.setPen(QtGui.QPen(col(tint or BLUE, 13), 1))
        step = 22.0; off = (now * 9) % step
        x = R.left() - R.height() + off
        while x < R.right():
            p.drawLine(QPointF(x, R.bottom()), QPointF(x + R.height(), R.top())); x += step
        for xf, yf, sz, sp, rot, rs, a in self.shapes:
            y = R.top() - 40 + ((yf - now * sp) % 1.0) * (R.height() + 80)
            x = R.left() + xf * R.width()
            p.save(); p.translate(x, y); p.rotate(rot + now * rs)
            tri = QtGui.QPolygonF([QPointF(0, -sz * 0.6), QPointF(sz * 0.52, sz * 0.3), QPointF(-sz * 0.52, sz * 0.3)])
            p.setPen(QtGui.QPen(col(tint or BLUE, a), 1.3)); p.setBrush(col(CYAN, a * 0.35)); p.drawPolygon(tri)
            p.restore()

    def paint_content(self, p, R, now):
        pass

    # ------------------------------------------------------------ widgets
    def header(self, p, R, title, sub, h=66, back=True, close=True, accent=YELLOW):
        T = QRectF(R.left(), R.top(), R.width(), h)
        g = QtGui.QLinearGradient(T.topLeft(), T.bottomLeft())
        g.setColorAt(0, col(WHITE, 250)); g.setColorAt(1, col(WHITE, 228))
        p.fillRect(T, g)
        p.fillRect(QRectF(T.left(), T.bottom() - 2, T.width(), 2), col(BLUE, 70))
        self.hits.append((QRectF(T), ("drag",)))
        x = T.left() + 16
        if back:
            b = QRectF(x, T.top() + 13, 60, h - 26)
            hov = self.hover == ("back",)
            path = poly_path(para(b, 10))
            p.setPen(NOPEN); p.setBrush(NAVY if hov else BLUE); p.drawPath(path)
            glyph_icon(p, b.center(), 10, "back", WHITE, 3.4)
            self.hits.append((path, ("back",)))
            x = b.right() + 20
        p.setPen(NOPEN); p.setBrush(accent)
        p.drawPolygon(para(QRectF(x, T.top() + 15, 9, h - 30), 4))
        text(p, QRectF(x + 18, T.top() + 4, 520, 38), title, 29, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter)
        text(p, QRectF(x + 21, T.top() + 40, 520, 16), sub, 10, BLUE_D, W_BOLD, False,
             AF.AlignLeft | AF.AlignVCenter, 2.6)
        xr = T.right() - 16
        if close:
            cb = QRectF(xr - 42, T.top() + 14, 42, h - 28)
            hov = self.hover == ("close",)
            p.setPen(QtGui.QPen(col(RED if hov else NAVY, 255 if hov else 90), 1.2))
            p.setBrush(RED if hov else col(WHITE, 240)); p.drawRoundedRect(cb, 8, 8)
            glyph_icon(p, cb.center(), 14, "close", WHITE if hov else NAVY, 2.6)
            self.hits.append((QRectF(cb), ("close",)))
            xr = cb.left() - 12
        return T, xr

    def button(self, p, r, label, key, accent=BLUE, slant=10, px=14, enabled=True, icon=None, active=False):
        hov = enabled and self.hover == key
        path = poly_path(para(r, slant))
        if active:
            p.setPen(NOPEN); p.setBrush(accent)
        else:
            p.setPen(QtGui.QPen(col(accent, 160 if hov else 90), 1.4))
            p.setBrush(col(SKY, 255) if hov else col(WHITE, 252 if enabled else 170))
        p.drawPath(path)
        if not active:
            p.setPen(NOPEN); p.setBrush(accent if enabled else col(GREY, 120))
            p.drawPolygon(para(QRectF(r.left() + 3, r.top() + 4, 6, r.height() - 8), 3))
        ink = WHITE if active else (NAVY if enabled else col(GREY, 200))
        tr = r.adjusted(slant, 0, -4, 0)
        if icon:
            fm = QtGui.QFontMetrics(font(px, W_BLACK, True))
            tw = fm.horizontalAdvance(label) + px + 8
            ix = tr.center().x() - tw / 2 + px / 2
            glyph_icon(p, QPointF(ix, tr.center().y()), px * 0.62, icon, accent if not active else WHITE, 2.2)
            tr = QRectF(ix + px / 2 + 6, tr.top(), tw, tr.height())
            text(p, tr, label, px, ink, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter)
        else:
            text(p, tr, label, px, ink, W_BLACK, True)
        if enabled:
            self.hits.append((path, key))

    def big_button(self, p, r, label, sub, key, now, enabled=True, px=24, colors=None):
        hov = enabled and self.hover == key
        path = poly_path(para(r, 16))
        c0, c1, c2, edge = colors or (YELLOW_L, YELLOW, YELLOW_D, QtGui.QColor(206, 146, 0))
        if enabled:
            pulse = 0.5 + 0.5 * math.sin(now * 4.2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(col(c2, 150 if hov else 60 + 90 * pulse), 9)); p.drawPath(path)
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, c0.lighter(106) if hov else c0); g.setColorAt(0.5, c1.lighter(105) if hov else c1)
            g.setColorAt(1, c2)
            p.setPen(QtGui.QPen(edge, 1.5)); p.setBrush(g); p.drawPath(path)
            p.save(); p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.fillRect(QRectF(r.left(), r.top(), r.width(), r.height() * 0.45), col(WHITE, 70))
            p.setPen(QtGui.QPen(col(WHITE, 55), 10))
            sx = r.left() + ((now * 90) % (r.width() + 120)) - 60
            p.drawLine(QPointF(sx, r.bottom()), QPointF(sx + 30, r.top()))
            p.restore()
        else:
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, QtGui.QColor(246, 248, 251)); g.setColorAt(1, QtGui.QColor(222, 230, 240))
            p.setPen(QtGui.QPen(QtGui.QColor(196, 208, 223), 1.5)); p.setBrush(g); p.drawPath(path)
        ink = NAVY_D if enabled else GREY
        if colors is not None and enabled:
            ink = WHITE
        text(p, QRectF(r.left() + 12, r.top() + 3, r.width() - 24, r.height() * 0.62), label, px, ink, W_BLACK, True,
             AF.AlignCenter, 2.0, elide=True)
        if sub:
            text(p, QRectF(r.left() + 10, r.top() + r.height() * 0.58, r.width() - 26, r.height() * 0.36), sub, 11,
                 col(ink, 200 if enabled else 150), W_BOLD, False, elide=True)
        if enabled:
            self.hits.append((path, key))

    def toggle(self, p, r, on, key):
        hov = self.hover == key
        track = QRectF(r.right() - 52, r.center().y() - 12, 52, 24)
        p.setPen(QtGui.QPen(col(BLUE if on else GREY, 200 if hov else 140), 1.4))
        p.setBrush(BLUE if on else col(WHITE, 250)); p.drawRoundedRect(track, 12, 12)
        k = QPointF(track.right() - 12 if on else track.left() + 12, track.center().y())
        p.setPen(QtGui.QPen(col(NAVY, 60), 1)); p.setBrush(WHITE); p.drawEllipse(k, 9, 9)
        text(p, QRectF(track.left() - 60, r.top(), 52, r.height()), "ON" if on else "OFF", 11,
             BLUE_D if on else GREY, W_BLACK, True, AF.AlignRight | AF.AlignVCenter)
        self.hits.append((QRectF(track.left() - 64, r.top(), track.width() + 64, r.height()), key))

    def stepper(self, p, r, value, key):
        """[<]  value  [>] - keys are (key..., -1) and (key..., +1)."""
        w = 170.0
        box = QRectF(r.right() - w, r.center().y() - 14, w, 28)
        p.setPen(QtGui.QPen(col(BLUE, 80), 1)); p.setBrush(col(WHITE, 250)); p.drawRoundedRect(box, 14, 14)
        for side in (-1, 1):
            c = QPointF(box.left() + 14 if side < 0 else box.right() - 14, box.center().y())
            k = key + (side,)
            hov = self.hover == k
            p.setPen(NOPEN); p.setBrush(BLUE if hov else col(SKY, 255)); p.drawEllipse(c, 11, 11)
            p.setPen(QtGui.QPen(WHITE if hov else BLUE_D, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QtGui.QPolygonF([QPointF(c.x() - 2.5 * side, c.y() - 5), QPointF(c.x() + 2.5 * side, c.y()),
                                            QPointF(c.x() - 2.5 * side, c.y() + 5)]))
            self.hits.append((QRectF(c.x() - 14, c.y() - 14, 28, 28), k))
        text(p, box.adjusted(26, 0, -26, 0), str(value), 13, NAVY, W_BLACK, True)

    def chip(self, p, r, label, color, ink=WHITE, px=10):
        p.setPen(NOPEN); p.setBrush(color); p.drawPolygon(para(r, min(6, r.height() / 3)))
        text(p, r, label, px, ink, W_BLACK, True, AF.AlignCenter, 0.8)

    # ------------------------------------------------------------ input
    def _hit(self, pos):
        for shape, key in reversed(self.hits):
            if shape.contains(pos): return key
        return None

    def _set_hover(self, key):
        if key != self.hover:
            self.hover = key
            clickable = key is not None and key[0] != "drag"
            self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def mouseMoveEvent(self, ev):
        if self.drag_origin is not None:
            self.move(ev.globalPosition().toPoint() - self.drag_origin); return
        self._set_hover(self._hit(ev.position()))

    def leaveEvent(self, ev):
        if self.drag_origin is None: self._set_hover(None)
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        key = self._hit(ev.position())
        self.press = (key, ev.button())
        if ev.button() == Qt.MouseButton.LeftButton and key is not None and key[0] == "drag":
            self.drag_origin = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseReleaseEvent(self, ev):
        if self.drag_origin is not None:
            self.drag_origin = None; self.press = None; return
        key = self._hit(ev.position())
        if self.press is not None and key is not None and key == self.press[0] and key[0] != "drag":
            right = ev.button() == Qt.MouseButton.RightButton
            try:
                self.on_click(key, right)
            except Exception:
                traceback.print_exc()
            self.update()
        self.press = None

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)

    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.angleDelta().x()
        self.on_wheel(d, ev.position())
        ev.accept()

    def on_wheel(self, d, pos):
        pass

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.on_escape()
        else:
            self.on_key(ev)

    def on_key(self, ev):
        pass

    def on_click(self, key, right=False):
        pass
