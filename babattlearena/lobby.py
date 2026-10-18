"""Battle Arena lobby: the team builder.

    +-----------------------------------------------------------------------------------+
    | [<]  Battle Arena  TACTICAL CHALLENGE                              [gear] [x]     |
    |  +---------- BLUE TEAM -----------+   VS   +----------- RED TEAM -----------+     |
    |  | [card][card][card] ...         |        | [card][card] ...                |     |
    |  +--------------------------------+        +---------------------------------+     |
    |  STUDENTS (20)  [All][Unassigned]   [Random teams] [Balance] [Clear]              |
    |  [avatar][avatar][avatar][avatar] ...   (left click: active team, right: other)  |
    |  Lives 3 - No time limit - ...          [Settings]          [ BEGIN BATTLE ]      |
    +-----------------------------------------------------------------------------------+

Avatar cards use the same baked portraits as Student Select (no live 3D previews here).
"""
from __future__ import annotations

import math
import random

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt

from bapet.picker import StudentPicker
from .hud import portrait
from .stats import CombatProfile
from .theme import (AF, BLUE, BLUE_D, CYAN, GREEN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PINK, RED, RED_T, SKY,
                    TEAM_COL, TEAM_COL_D, TEAM_NAME, TEAM_SUB, WHITE, YELLOW, YELLOW_D, BAWindow, W_BLACK, W_BOLD,
                    W_DEMI, clamp, col, ease_out, font, glyph_icon, para, poly_path, rounded, spinner, text)

ROLE_COL = {"Tank": QtGui.QColor(90, 140, 255), "Attacker": QtGui.QColor(255, 96, 110),
            "Healer": QtGui.QColor(58, 200, 140), "Support": QtGui.QColor(255, 176, 60),
            "Tactical Support": QtGui.QColor(170, 120, 255)}


class ArenaLobby(BAWindow):
    def __init__(self, mgr):
        super().__init__(mgr, 1280, 820, "Battle Arena - Team Select")
        self.picker = self.app.picker()
        self.entries = self.picker.entries
        self.profiles = {id(e): CombatProfile(e.ch) for e in self.entries}
        self.teams = [[], []]
        self.side = 0
        self.filter = "all"
        self.scroll = self.scroll_target = self.max_scroll = 0.0
        self.card_step = 150.0
        self.hov_amt = {}

    def on_open(self):
        if self.mgr.last_teams:
            ids = [{id(e) for e in t} for t in self.mgr.last_teams]
            self.teams = [[e for e in self.entries if id(e) in ids[0]], [e for e in self.entries if id(e) in ids[1]]]

    def on_escape(self):
        self.close_animated()
        self.mgr.show_title()

    # ------------------------------------------------------------------ edits
    def team_of(self, e):
        for t in (0, 1):
            if e in self.teams[t]: return t
        return None

    def assign(self, e, team):
        cur = self.team_of(e)
        if cur is not None: self.teams[cur].remove(e)
        if cur != team: self.teams[team].append(e)

    def randomize(self):
        pool = list(self.entries)
        random.shuffle(pool)
        n = len(self.teams[0]) + len(self.teams[1])
        if n < 2: n = min(len(pool), 6)
        n -= n % 2
        pool = pool[:max(2, n)]
        self.teams = [pool[0::2], pool[1::2]]

    def balance(self):
        """Even the teams out by role mix and HP (greedy)."""
        pool = self.teams[0] + self.teams[1]
        if len(pool) < 2: pool = list(self.entries)[:6]

        def val(e):
            p = self.profiles[id(e)]
            return p.hp / 1000.0 + (2.5 if p.attacks else 1.2) + (1.0 if p.healer else 0.0)
        pool.sort(key=val, reverse=True)
        a, b = [], []
        for e in pool:
            (a if sum(map(val, a)) <= sum(map(val, b)) and len(a) <= len(b) else b).append(e)
        self.teams = [a, b]

    # ------------------------------------------------------------------ frame
    def tick(self, now):
        self.scroll_target = clamp(self.scroll_target, 0.0, self.max_scroll)
        self.scroll += (self.scroll_target - self.scroll) * 0.3
        for _ in range(2):                         # bake the avatar portraits a couple per frame
            e = next((q for q in self.entries if not q.still_state), None)
            if e is None: break
            try: self.picker.engine.bake(e)
            except Exception: e.still_state = 2
        for e in self.entries:
            tgt = 1.0 if self.hover == ("card", e) else 0.0
            self.hov_amt[id(e)] = self.hov_amt.get(id(e), 0.0) + (tgt - self.hov_amt.get(id(e), 0.0)) * 0.35

    def paint_content(self, p, R, now):
        T, xr = self.header(p, R, "Battle Arena",
                            "TACTICAL CHALLENGE  \u00b7  \u6226\u8853\u5bfe\u6297\u6226  \u00b7  TEAM SELECT")
        gb = QRectF(xr - 46, T.top() + 14, 46, T.height() - 28)
        hov = self.hover == ("settings",)
        p.setPen(QtGui.QPen(col(BLUE, 160 if hov else 90), 1.2)); p.setBrush(BLUE if hov else col(WHITE, 240))
        p.drawRoundedRect(gb, 8, 8)
        glyph_icon(p, gb.center(), 13, "gear", WHITE if hov else BLUE_D, 2.4)
        self.hits.append((gb, ("settings",)))
        B = QRectF(R.left(), R.bottom() - 84, R.width(), 84)
        mid_h = B.top() - T.bottom()
        teams = QRectF(R.left(), T.bottom(), R.width(), mid_h * 0.47)
        head = QRectF(R.left(), teams.bottom(), R.width(), 44)
        roster = QRectF(R.left(), head.bottom(), R.width(), B.top() - head.bottom())
        self.paint_teams(p, teams, now)
        self.paint_roster_head(p, head, now)
        self.paint_roster(p, roster, now)
        self.paint_bottom(p, B, now)

    def paint_teams(self, p, S, now):
        g = QtGui.QLinearGradient(S.topLeft(), S.bottomLeft())
        g.setColorAt(0, QtGui.QColor(200, 232, 255)); g.setColorAt(1, QtGui.QColor(236, 247, 255))
        p.fillRect(S, g)
        text(p, QRectF(S.left() + 20, S.top() + 2, S.width(), 100), "TACTICAL CHALLENGE", 78, col(BLUE, 18), W_BLACK,
             True, AF.AlignLeft | AF.AlignTop)
        gap = 120.0
        pw = (S.width() - 40 - gap) / 2
        for t in (0, 1):
            r = QRectF(S.left() + 20 + t * (pw + gap), S.top() + 16, pw, S.height() - 30)
            self.paint_team_panel(p, r, t, now)
        c = QPointF(S.center().x(), S.center().y() + 6)
        rad = 44
        p.setPen(QtGui.QPen(col(WHITE, 230), 3)); p.setBrush(NAVY_D); p.drawEllipse(c, rad, rad)
        pen = QtGui.QPen(col(YELLOW, 200), 3); pen.setDashPattern([2, 5]); pen.setDashOffset(now * 8)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(c, rad + 9, rad + 9)
        text(p, QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2), "VS", 34, YELLOW, W_BLACK, True)

    def paint_team_panel(self, p, r, t, now):
        c, cd = TEAM_COL[t], TEAM_COL_D[t]
        active = self.side == t
        p.setPen(QtGui.QPen(col(c, 255 if active else 120), 3 if active else 1.5))
        p.setBrush(col(WHITE, 215)); p.drawRoundedRect(r, 14, 14)
        hr = QRectF(r.left(), r.top(), r.width(), 46)
        p.save(); p.setClipPath(rounded(r, 14), Qt.ClipOperation.IntersectClip)
        hg = QtGui.QLinearGradient(hr.topLeft(), hr.topRight())
        hg.setColorAt(0, c); hg.setColorAt(1, cd)
        p.fillRect(hr, hg)
        p.setPen(QtGui.QPen(col(WHITE, 40), 8))
        x = hr.left() - 40 + (now * 30) % 40
        while x < hr.right():
            p.drawLine(QPointF(x, hr.bottom()), QPointF(x + 30, hr.top())); x += 40
        p.restore()
        text(p, hr.adjusted(18, 2, 0, -hr.height() * 0.42), TEAM_NAME[t], 18, WHITE, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 2)
        text(p, hr.adjusted(19, hr.height() * 0.55, 0, -2), TEAM_SUB[t], 9, col(WHITE, 220), W_BOLD, False,
             AF.AlignLeft | AF.AlignVCenter, 2)
        tag = QRectF(hr.right() - 160, hr.top() + 10, 146, 26)
        p.setPen(NOPEN); p.setBrush(YELLOW if active else col(WHITE, 60)); p.drawPolygon(para(tag, 8))
        text(p, tag, "ASSIGNING HERE" if active else "CLICK TO ASSIGN", 10, NAVY_D if active else WHITE, W_BLACK, True,
             AF.AlignCenter, 1.2)
        self.hits.append((hr, ("side", t)))
        n = len(self.teams[t])
        text(p, QRectF(hr.right() - 300, hr.top(), 128, hr.height()), f"{n} student{'s' if n != 1 else ''}", 13,
             WHITE, W_BLACK, True, AF.AlignRight | AF.AlignVCenter)
        body = QRectF(r.left() + 12, hr.bottom() + 10, r.width() - 24, r.height() - hr.height() - 20)
        self.hits.append((QRectF(r.left(), hr.bottom(), r.width(), r.height() - hr.height()), ("side", t)))
        if not self.teams[t]:
            text(p, body, "Click students below to add them", 14, col(GREY, 230), W_BLACK, True)
            return
        # pick the grid (rows x cols) that gives the biggest card that still fits every student
        gx, gy, aspect = 8.0, 6.0, 1.18
        best = None
        for rows in range(1, n + 1):
            cols = math.ceil(n / rows)
            cw = min(110.0, (body.width() - (cols - 1) * gx) / cols)
            ch = min(cw * aspect, (body.height() - (rows - 1) * gy) / rows)
            cw = min(cw, ch / aspect)
            if best is None or cw > best[0] + 0.01:
                best = (cw, cols, rows)
        cw, cols, rows = best
        cw = max(cw, 24.0)
        ch = cw * aspect
        plate_h = clamp(ch * 0.26, 14.0, 22.0)
        name_px = 11 if cw >= 80 else (9 if cw >= 56 else 8)
        for i, e in enumerate(self.teams[t]):
            row, cix = divmod(i, cols)
            cr = QRectF(body.left() + cix * (cw + gx), body.top() + row * (ch + gy), cw, ch)
            hov = self.hover == ("unassign", e)
            p.setPen(QtGui.QPen(col(c, 255 if hov else 160), 2)); p.setBrush(WHITE); p.drawRoundedRect(cr, 9, 9)
            portrait(p, e, cr.adjusted(2, 2, -2, -plate_h), 8)
            nr = QRectF(cr.left() + 1, cr.bottom() - plate_h - 1, cr.width() - 2, plate_h)
            p.setPen(NOPEN); p.setBrush(col(NAVY, 230))
            p.drawRoundedRect(nr, 6, 6)
            text(p, nr.adjusted(3, 0, -3, 0), e.name, name_px, WHITE, W_BLACK, True, AF.AlignCenter, elide=True)
            prof = self.profiles[id(e)]
            self.chip(p, QRectF(cr.left() + 4, cr.top() + 4, min(30.0, cw * 0.55), 14), prof.short(), c, px=8)
            if hov:
                bc = QPointF(cr.right() - 10, cr.top() + 10)
                p.setPen(QtGui.QPen(WHITE, 2)); p.setBrush(RED); p.drawEllipse(bc, 9, 9)
                glyph_icon(p, bc, 7, "close", WHITE, 2)
            self.hits.append((cr, ("unassign", e)))

    def paint_roster_head(self, p, H, now):
        p.fillRect(H, col(WHITE, 220))
        p.fillRect(QRectF(H.left(), H.top(), H.width(), 1.5), col(BLUE, 60))
        x = H.left() + 22
        p.setPen(NOPEN); p.setBrush(BLUE); p.drawPolygon(para(QRectF(x, H.top() + 11, 7, H.height() - 22), 3))
        text(p, QRectF(x + 16, H.top(), 140, H.height()), "STUDENTS", 16, NAVY, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 1.5)
        x += 136
        n_un = sum(1 for e in self.entries if self.team_of(e) is None)
        for key, label in (("all", f"All  {len(self.entries)}"), ("free", f"Unassigned  {n_un}")):
            r = QRectF(x, H.top() + 8, 140, H.height() - 16)
            self.button(p, r, label, ("tab", key), px=12, slant=8, active=self.filter == key)
            x += 148
        bx = H.right() - 22
        for key, label, icon, acc in ((("clear",), "Clear", "close", ORANGE), (("balance",), "Balance", "target", BLUE),
                                      (("random",), "Random", "shuffle", PINK)):
            w = 128.0
            r = QRectF(bx - w, H.top() + 7, w, H.height() - 14)
            self.button(p, r, label, key, accent=acc, px=12, slant=8, icon=icon)
            bx -= w + 8
        text(p, QRectF(x + 6, H.top(), bx - x - 12, H.height()),
             "left-click: highlighted team  \u00b7  right-click: other team", 11, GREY, W_BOLD, False,
             AF.AlignCenter | AF.AlignVCenter, elide=True)

    def filtered(self):
        if self.filter == "free": return [e for e in self.entries if self.team_of(e) is None]
        return list(self.entries)

    def paint_roster(self, p, Rr, now):
        lst = self.filtered()
        pad, gap = 26.0, 14.0
        card_h = max(90.0, Rr.height() - 28)
        card_w = card_h * 0.74
        self.card_step = card_w + gap
        content = pad * 2 + len(lst) * (card_w + gap) - (gap if lst else 0)
        self.max_scroll = max(0.0, content - Rr.width())
        x = Rr.left() + pad - self.scroll
        p.save(); p.setClipRect(Rr, Qt.ClipOperation.IntersectClip)
        for idx, e in enumerate(lst):
            r = QRectF(x, Rr.top() + 12, card_w, card_h)
            x += card_w + gap
            if r.right() < Rr.left() - 20 or r.left() > Rr.right() + 20: continue
            self.paint_card(p, e, r, now, idx)
        if not lst:
            text(p, Rr, "Everybody has a team", 15, col(GREY, 230), W_BLACK, True)
        for side in (-1, 1):
            can = self.scroll > 1 if side < 0 else self.scroll < self.max_scroll - 1
            if not can: continue
            bc = QPointF(Rr.left() + 22 if side < 0 else Rr.right() - 22, Rr.center().y())
            hov = self.hover == ("arrow", side)
            p.setPen(QtGui.QPen(col(BLUE, 120), 1)); p.setBrush(BLUE if hov else col(WHITE, 245))
            p.drawEllipse(bc, 17, 17)
            glyph_icon(p, bc, 9, "back" if side < 0 else "play", WHITE if hov else BLUE, 2.6)
            self.hits.append((QRectF(bc.x() - 17, bc.y() - 17, 34, 34), ("arrow", side)))
        p.restore()

    def paint_card(self, p, e, r, now, idx):
        t = self.team_of(e)
        prof = self.profiles[id(e)]
        hv = self.hov_amt.get(id(e), 0.0)
        a = ease_out((now - self.t_open - 0.1 - idx * 0.04) / 0.4)
        hit = QRectF(r)
        r = r.translated(0, (1 - a) * 40 - 8 * hv)
        p.save(); p.setOpacity(a)
        c = r.center(); p.translate(c); p.shear(-0.06, 0); p.translate(-c)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 35 + 35 * hv)); p.drawRoundedRect(r.translated(0, 6), 10, 10)
        path = rounded(r, 10)
        p.setBrush(WHITE); p.drawPath(path)
        port = QRectF(r.left(), r.top(), r.width(), r.height() - 60)
        portrait(p, e, port, 10)
        if e.still is None and not e.still_state:
            spinner(p, port.center(), 14, now)
        plate = QRectF(r.left(), r.bottom() - 60, r.width(), 60)
        p.save(); p.setClipPath(path, Qt.ClipOperation.IntersectClip)    # keep the roster clip: replacing it let the plate spill out
        p.fillRect(plate, WHITE)
        rc = ROLE_COL.get(prof.role, BLUE)
        p.fillRect(QRectF(plate.left(), plate.top(), plate.width(), 3), TEAM_COL[t] if t is not None else rc)
        p.restore()
        text(p, QRectF(plate.left() + 10, plate.top() + 5, plate.width() - 16, 22), e.name, 14, NAVY, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, elide=True)
        cy = plate.top() + 30
        self.chip(p, QRectF(plate.left() + 8, cy, 36, 15), prof.short(), NAVY, px=9)
        self.chip(p, QRectF(plate.left() + 48, cy, 64, 15), prof.role.upper()[:9], rc, px=8)
        text(p, QRectF(plate.left() + 10, cy + 15, plate.width() - 16, 14),
             f"{prof.position.upper()} \u00b7 {prof.weapon}", 9, GREY, W_DEMI, False, AF.AlignLeft | AF.AlignVCenter,
             elide=True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if t is not None:
            tc = TEAM_COL[t]
            p.setPen(QtGui.QPen(col(tc, 90 + 50 * math.sin(now * 4)), 8)); p.drawPath(path)
            p.setPen(QtGui.QPen(tc, 3)); p.drawPath(path)
            rib = QRectF(r.left() + 8, r.top() + 9, 70, 20)
            p.setPen(NOPEN); p.setBrush(tc); p.drawPolygon(para(rib, 6))
            text(p, rib, "BLUE" if t == 0 else "RED", 11, WHITE, W_BLACK, True, AF.AlignCenter, 1.5)
            k = self.teams[t].index(e) + 1
            bc = QPointF(r.right() - 16, r.top() + 16)
            p.setPen(QtGui.QPen(WHITE, 2.5)); p.setBrush(tc); p.drawEllipse(bc, 14, 14)
            text(p, QRectF(bc.x() - 14, bc.y() - 14, 28, 28), str(k), 13, WHITE, W_BLACK, True)
        elif hv > 0.05:
            p.setPen(QtGui.QPen(col(TEAM_COL[self.side], 220 * hv), 2.5)); p.drawPath(path)
        else:
            p.setPen(QtGui.QPen(col(NAVY, 40), 1)); p.drawPath(path)
        if not prof.attacks:
            self.chip(p, QRectF(r.right() - 66, port.bottom() - 22, 58, 16), "HEALER" if prof.healer else "SUPPORT",
                      GREEN if prof.healer else ORANGE, px=8)
        p.restore()
        self.hits.append((hit, ("card", e)))

    def paint_bottom(self, p, B, now):
        p.fillRect(B, col(WHITE, 238))
        p.fillRect(QRectF(B.left(), B.top(), B.width(), 1.5), col(BLUE, 60))
        cy = B.center().y()
        sb = QRectF(B.left() + 24, cy - 22, 160, 44)
        self.button(p, sb, "Settings", ("settings",), px=14, icon="gear")
        dep = QRectF(B.right() - 26 - 280, cy - 30, 280, 60)
        n0, n1 = len(self.teams[0]), len(self.teams[1])
        ok = n0 > 0 and n1 > 0
        summ = QRectF(sb.right() + 20, B.top(), dep.left() - sb.right() - 40, B.height())
        text(p, QRectF(summ.left(), summ.top() + 10, summ.width(), 26), self.mgr.settings.summary(), 12, BLUE_D, W_BLACK,
             True, AF.AlignLeft | AF.AlignVCenter, elide=True)
        msg = f"{n0} vs {n1}" if ok else "Both teams need at least one student"
        text(p, QRectF(summ.left(), summ.top() + 38, summ.width(), 24), msg, 12, NAVY if ok else ORANGE, W_BOLD, False,
             AF.AlignLeft | AF.AlignVCenter, elide=True)
        self.big_button(p, dep, "BEGIN BATTLE", f"\u6226\u95d8\u958b\u59cb  \u00b7  {n0} vs {n1}", ("begin",), now,
                        enabled=ok, px=24)

    # ------------------------------------------------------------------ input
    def on_click(self, key, right=False):
        k = key[0]
        if k in ("back", "close"):
            self.on_escape()
        elif k == "settings":
            self.mgr.open_settings()
        elif k == "side":
            self.side = key[1]
        elif k == "card":
            team = (1 - self.side) if right else self.side
            self.assign(key[1], team)
        elif k == "unassign":
            e = key[1]
            t = self.team_of(e)
            if t is not None:
                if right: self.assign(e, 1 - t)
                else: self.teams[t].remove(e)
        elif k == "tab":
            self.filter = key[1]; self.scroll_target = 0.0
        elif k == "arrow":
            self.scroll_target += key[1] * self.card_step * 3
        elif k == "random":
            self.randomize()
        elif k == "balance":
            self.balance()
        elif k == "clear":
            self.teams = [[], []]
        elif k == "begin":
            if self.teams[0] and self.teams[1]:
                self.mgr.begin_battle([list(self.teams[0]), list(self.teams[1])])

    def on_wheel(self, d, pos):
        self.scroll_target = clamp(self.scroll_target - d * 0.9, 0.0, self.max_scroll)

    def on_key(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.on_click(("begin",))
        elif ev.key() == Qt.Key.Key_Tab:
            self.side = 1 - self.side
