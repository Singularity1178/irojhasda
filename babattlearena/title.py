"""Title screen (placeholder): two choices, Desktop Pets or Battle Arena."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

from .theme import (AF, BLUE, BLUE_D, CYAN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PINK, RED_T, WHITE, YELLOW, BAWindow,
                    W_BLACK, W_BOLD, clamp, col, ease_back, ease_out, glyph_icon, para, poly_path, rounded, text)


SHOP_ICON = Path(__file__).resolve().parent / "assets" / "MP_Shop.png"


class TitleScreen(BAWindow):
    _shop_pix = None

    def __init__(self, mgr):
        super().__init__(mgr, 1000, 600, "Blue Archive - Desktop")

    def on_escape(self):
        self.close_animated()

    def paint_content(self, p, R, now):
        # halo
        hc = QPointF(R.center().x(), R.top() + 150)
        rad = 120
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(col(WHITE, 200), 3)); p.drawEllipse(hc, rad, rad * 0.32)
        pen = QtGui.QPen(col(BLUE, 70), 3); pen.setDashPattern([2, 6]); pen.setDashOffset(now * 6)
        p.setPen(pen); p.drawEllipse(hc, rad * 1.18, rad * 0.4)
        p.setPen(QtGui.QPen(col(PINK, 110), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        a0 = int((now * 30) % 360 * 16)
        p.drawArc(QRectF(hc.x() - rad * 1.3, hc.y() - rad * 0.45, rad * 2.6, rad * 0.9), a0, 50 * 16)
        # logo
        pop = ease_back(clamp((now - self.t_open) / 0.6, 0, 1))
        p.save(); p.translate(R.center().x(), R.top() + 140); p.scale(pop, pop)
        text(p, QRectF(-420, -60, 840, 80), "Blue Archive", 62, NAVY, W_BLACK, True, AF.AlignCenter)
        p.setPen(NOPEN); p.setBrush(BLUE); p.drawPolygon(para(QRectF(-150, 22, 300, 30), 10))
        text(p, QRectF(-150, 22, 300, 30), "DESKTOP  \u00b7  \u30c7\u30b9\u30af\u30c8\u30c3\u30d7", 14, WHITE, W_BLACK, True,
             AF.AlignCenter, 3)
        p.restore()
        text(p, QRectF(R.left(), R.top() + 200, R.width(), 24), "SCHALE  \u00b7  FEDERAL INVESTIGATION CLUB", 11,
             col(BLUE_D, 160), W_BOLD, False, AF.AlignCenter, 3)
        # options
        cw, ch = 380.0, 230.0
        gap = 40.0
        y = R.top() + 250
        opts = ((("pets",), "Desktop Pets", "\u30c7\u30b9\u30af\u30c8\u30c3\u30d7\u30da\u30c3\u30c8",
                 "Student Select & your desktop companions", "heart", BLUE),
                (("arena",), "Battle Arena", "\u6226\u8853\u5bfe\u6297\u6226",
                 "Two teams, top-down, real ragdolls & cover", "cross", RED_T))
        for i, (key, title, jp, sub, icon, acc) in enumerate(opts):
            a = ease_out((now - self.t_open - 0.15 - i * 0.1) / 0.4)
            x = R.center().x() - cw - gap / 2 + i * (cw + gap)
            r = QRectF(x, y + (1 - a) * 30, cw, ch)
            hov = self.hover == key
            if hov: r = r.translated(0, -6)
            p.save(); p.setOpacity(a)
            path = poly_path(para(r, 22))
            p.setPen(NOPEN); p.setBrush(col(NAVY_D, 50)); p.drawPath(poly_path(para(r.translated(0, 8), 22)))
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, acc.lighter(115) if hov else acc); g.setColorAt(1, acc.darker(125))
            p.setBrush(g); p.drawPath(path)
            p.save(); p.setClipPath(path)
            p.setPen(QtGui.QPen(col(WHITE, 30), 14))
            sx = r.left() - 200 + (now * 50) % 60
            while sx < r.right():
                p.drawLine(QPointF(sx, r.bottom()), QPointF(sx + 100, r.top())); sx += 60
            glyph_icon(p, QPointF(r.right() - 90, r.center().y() + 10), 70, icon, col(WHITE, 60), 10)
            p.restore()
            glyph_icon(p, QPointF(r.left() + 66, r.top() + 64), 26, icon, WHITE, 4)
            text(p, QRectF(r.left() + 40, r.top() + 104, cw - 60, 46), title, 34, WHITE, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter)
            text(p, QRectF(r.left() + 38, r.top() + 148, cw - 60, 20), jp, 13, col(WHITE, 220), W_BOLD, False,
                 AF.AlignLeft | AF.AlignVCenter, 2)
            text(p, QRectF(r.left() + 30, r.top() + 176, cw - 60, 20), sub, 12, col(WHITE, 235), W_BOLD, False,
                 AF.AlignLeft | AF.AlignVCenter)
            if hov:
                p.setPen(QtGui.QPen(col(YELLOW, 230), 4)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
            p.restore()
            self.hits.append((path, key))
        # footer
        fy = R.bottom() - 54
        self.button(p, QRectF(R.left() + 30, fy, 170, 38), "Control Panel", ("panel",), px=13, icon="gear")
        self.button(p, QRectF(R.right() - 30 - 130, fy, 130, 38), "Quit", ("quit",), accent=ORANGE, px=13, icon="close")
        text(p, QRectF(R.left(), fy, R.width(), 38), "TAP TO START", 13,
             col(NAVY, 120 + 100 * (0.5 + 0.5 * math.sin(now * 3))), W_BLACK, True, AF.AlignCenter, 4)
        self.hits.append((QRectF(R.left(), R.top(), R.width(), 230), ("drag",)))
        self.shop_button(p, R, now)

    def shop_button(self, p, R, now):
        """Sora's shop icon, top left. Added to the hit list last so it wins over the drag strip."""
        if TitleScreen._shop_pix is None:
            TitleScreen._shop_pix = QtGui.QPixmap(str(SHOP_ICON))
        pix = TitleScreen._shop_pix
        if pix.isNull():
            return
        w = 108.0
        r = QRectF(R.left() + 26, R.top() + 22, w, w * pix.height() / pix.width())
        hov = self.hover == ("shop",)
        if hov: r = r.translated(0, -3)
        a = ease_out((now - self.t_open - 0.05) / 0.35)
        p.save(); p.setOpacity(a)
        if hov:
            p.setPen(NOPEN); p.setBrush(col(YELLOW, 60)); p.drawEllipse(r.center(), r.width() * 0.62, r.height() * 0.62)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(r, pix, QRectF(pix.rect()))
        p.restore()
        self.hits.append((QRectF(r), ("shop",)))

    def on_click(self, key, right=False):
        k = key[0]
        if k == "shop": self.mgr.open_shop()
        elif k == "pets": self.mgr.open_desktop_pets()
        elif k == "arena": self.mgr.open_lobby()
        elif k == "panel":
            self.close_animated()
            self.app.show_panel()
        elif k == "quit": self.app.quit_app()
