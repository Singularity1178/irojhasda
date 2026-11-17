"""Campaign mode: the screens and the flow between them (the rules live in campaign_data.py, the fights in
campaign_battle.py).

    title -> HUB (squad, supplies, control, threat level) -> DOORS -> battle -> REWARD (pick a support) -> DOORS ...
                 ^            |  Sora's shop                    |  Sora's field stall / cafe (no fight)
                 +------------+--------------------- RESULT <---+  squad wiped, run abandoned, or the last boss fell

    Campaign         the controller hanging off ArenaManager (mgr.campaign): owns the save, the current Run and the
                     screens, starts each room's CampaignBattle and receives its result.
    CampaignScreen   one BAWindow that draws whichever of the screens above is current (`mode`). It also has a
                     plain COUNTER (the same stock and prices as Sora's shop, drawn natively) that is used only
                     when the real shop cannot open because QtWebEngine is not installed.
    CampaignPause    the pause menu during a campaign fight: Resume / Abandon Run / Title Screen.
"""
from __future__ import annotations

import math
import time
import traceback

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer

from .campaign_data import (AREAS, BOON_BY_ID, ITEM_BY_ID, RARITY, ROOMS_PER_AREA, SCHOOL_COL, TOTAL_ROOMS, Run,
                            area_of, boon_text, get_save, is_boss_room)
from .hud import ArenaOverlay, portrait
from .stats import CombatProfile
from .theme import (AF, BLUE, BLUE_D, CYAN, GREEN, GREY, NAVY, NAVY_D, NOPEN, ORANGE, PINK, PURPLE, RED, RED_T, SKY,
                    WHITE, YELLOW, YELLOW_D, BAWindow, W_BLACK, W_BOLD, clamp, col, ease_back, ease_out, font,
                    glyph_icon, para, poly_path, rounded, text)

REWARD_COL = {"boon": BLUE, "credits": YELLOW_D, "pyrox": QtGui.QColor(70, 150, 255), "supply": ORANGE,
              "heal": GREEN, "halo": QtGui.QColor(255, 200, 70)}
RARITY_COL = (GREY, BLUE, PURPLE)
ROMAN = ("I", "II", "III")
CONTROLS = ("WASD move  \u00b7  hold LMB to fire at the cursor  \u00b7  RMB / Q: EX skill  \u00b7  SPACE: dash (brief "
            "invulnerability)  \u00b7  R reload  \u00b7  1-4 supplies  \u00b7  TAB: control the next student  \u00b7  "
            "T: manual / auto  \u00b7  ESC pause")


def qc(rgb):
    return QtGui.QColor(*rgb)


def wrapped(p, r, s, px, color, weight=W_BOLD, align=AF.AlignLeft | AF.AlignTop, italic=False):
    opt = QtGui.QTextOption(align)
    opt.setWrapMode(QtGui.QTextOption.WrapMode.WordWrap)
    p.setFont(font(px, weight, italic)); p.setPen(color)
    p.drawText(r, s, opt)


# ============================================================================== controller
class Campaign:
    def __init__(self, mgr):
        self.mgr = mgr
        self.app = mgr.app
        self.save = get_save()
        self.run = None
        self._screen = None
        self._pause = None
        self._ending = False

    def entries(self):
        return self.app.picker().entries

    def by_name(self):
        return {e.name: e for e in self.entries()}

    def screen(self):
        if self._screen is None:
            self._screen = CampaignScreen(self)
        return self._screen

    def run_active(self):
        return self.run is not None and self.run.over is None

    # ------------------------------------------------------------------ flow
    def open(self):
        """Main menu (or Sora's shop) -> the campaign: the hub, or the run that is still going."""
        scr = self.screen()
        if self.run_active():
            if scr.mode not in ("doors", "reward", "stall", "cafe"): scr.set_mode("doors")
        elif scr.mode != "result" or self.run is None:
            scr.set_mode("hub")
        scr.open()

    def start_run(self):
        scr = self.screen()
        squad = scr.squad()
        if not squad: return
        names = [e.name for e in self.entries()]
        self.save.d["squad"] = squad
        self.save.d["leader"] = scr.leader()
        self.save.save()
        self.run = Run(self.save, squad, scr.leader(), [n for n in names if n not in squad],
                       heat=int(self.save.d.get("heat", 0)))
        scr.set_mode("doors")

    def enter_door(self, i):
        run = self.run
        if not self.run_active() or not (0 <= i < len(run.doors)): return
        door = run.enter(i)
        if door["kind"] == "cafe":
            run.rest(); self.screen().set_mode("cafe")
        elif door["kind"] == "stall":
            run.open_stall(); self.screen().set_mode("stall")
        else:
            self.begin_battle()

    def begin_battle(self):
        mgr, run = self.mgr, self.run
        for w in (self._screen, mgr._title, mgr._lobby, mgr._settings_win, mgr._results, mgr._pause):
            mgr._hide(w)
        try: self.app.hide_picker()
        except Exception: pass
        mgr.hide_pets()
        try:
            from .campaign_battle import CampaignBattle
            B = CampaignBattle(mgr, run, run.door, self.by_name(), mgr.settings, manual=bool(self.save.d.get("manual", True)))
            mgr.battle = B
            self._ending = False
            B.start()
        except Exception:
            traceback.print_exc()
            mgr.battle = None
            scr = self.screen()
            scr.set_mode("doors"); scr.flash("That room could not be started - see the console")
            scr.open()

    def on_battle_end(self, battle):
        """Battle.step -> ArenaManager.show_results -> here. We are inside the battle's own tick, so the
        tear-down waits for the event loop."""
        if self._ending: return
        self._ending = True
        QTimer.singleShot(0, lambda: self._finish_room(battle))

    def _finish_room(self, battle):
        self._ending = False
        if self.mgr.battle is not battle: return
        try:
            rep = battle.report()
        except Exception:
            traceback.print_exc()
            rep = dict(win=False, kills=0, credits=0, squad=[])
        self.mgr.end_battle()
        run = self.run
        scr = self.screen()
        if run is None:
            scr.set_mode("hub")
        elif run.room_result(rep["win"], rep["kills"], rep["credits"], rep["squad"]):
            scr.set_mode("reward")
        else:
            scr.set_mode("result")
        scr.open()

    def leave_room(self):
        """Reward / stall / cafe -> the next doors, or the result screen after the last boss."""
        run = self.run
        if not self.run_active() or run.pending: return
        self.screen().set_mode("doors" if run.advance() else "result")

    def abandon(self):
        self.mgr.end_battle()
        if self.run_active(): self.run.finish(False, abandoned=True)
        scr = self.screen()
        scr.set_mode("result" if self.run is not None else "hub")
        scr.open()

    def to_hub(self):
        if not self.run_active(): self.run = None
        self.screen().set_mode("hub")

    def to_title(self):
        """Leave for the main menu. Mid-fight that gives the run up; between rooms the run waits for you."""
        if self.mgr.battle is not None and self.run_active():
            self.run.finish(False, abandoned=True)
            if self._screen is not None: self._screen.set_mode("result")
        self.mgr._hide(self._screen)
        self.mgr.to_title()

    # ------------------------------------------------------------------ pause
    def pause(self):
        B = self.mgr.battle
        if B is None: return
        B.set_paused(True)
        try: B.sync_pad()
        except Exception: pass
        if self._pause is None:
            self._pause = CampaignPause(self)
        self._pause.open()

    def hide_pause(self):
        if self._pause is not None and self._pause.isVisible():
            self._pause.hide()


# ============================================================================== the screen
class CampaignScreen(BAWindow):
    def __init__(self, camp):
        super().__init__(camp.mgr, 1240, 800, "Campaign - Blue Archive")
        self.camp = camp
        self.save = camp.save
        self.mode = "hub"
        self.t_mode = time.perf_counter()
        self.picker = self.app.picker()
        self.entries = self.picker.entries
        self.by_name = {e.name: e for e in self.entries}
        self.profiles = {e.name: CombatProfile(e.ch) for e in self.entries}
        self.scroll = self.scroll_target = self.max_scroll = 0.0
        self.msg = None
        self.hint = None
        self.confirm_t = 0.0
        self.counter_tab = "training"

    # ------------------------------------------------------------------ state
    def set_mode(self, mode):
        self.mode = mode
        self.t_mode = time.perf_counter()
        self.hover = None
        self.confirm_t = 0.0
        self.update()

    def flash(self, s, good=False):
        self.msg = (s, time.perf_counter(), good)

    def open_shop(self):
        """Sora's shop; without QtWebEngine, her plain counter inside this window."""
        if self.mode == "result": self.camp.to_hub()
        if not self.mgr.open_shop(origin="campaign"):
            self.set_mode("counter")
            self.flash("Sora's animated shop needs QtWebEngine (pip install PySide6) - this is the same stock at the same prices")

    def squad(self):
        cap = 1 + int(self.save.meta()["squad_slots"])
        return [n for n in self.save.d.get("squad", []) if n in self.by_name][:cap]

    def leader(self):
        sq = self.squad()
        l = self.save.d.get("leader")
        return l if l in sq else (sq[0] if sq else None)

    def set_squad(self, sq, leader=None):
        self.save.d["squad"] = list(sq)
        l = leader if leader in sq else self.save.d.get("leader")
        self.save.d["leader"] = l if l in sq else (sq[0] if sq else None)
        self.save.save()

    def toggle_member(self, name, make_leader=False):
        sq = self.squad()
        cap = 1 + int(self.save.meta()["squad_slots"])
        if name in sq and not make_leader:
            sq.remove(name)
        elif name not in sq:
            if len(sq) >= cap:
                if cap == 1: sq = []                         # a one-student squad: clicking simply swaps her
                elif make_leader and self.leader() in sq:    # full squad + "make leader": she replaces the leader
                    sq.remove(self.leader())
                else:
                    self.flash("The squad is full - remove someone, or unlock a Squad Slot at Sora's shop")
                    return
            sq.append(name)
        self.set_squad(sq, name if (make_leader or len(sq) == 1) else None)

    def on_open(self):
        self.msg = None

    def on_escape(self):
        if self.mode == "counter":
            self.camp.to_hub()
        elif self.mode in ("hub", "doors", "result"):
            self.close_animated()
            if self.mode == "result": self.camp.to_hub()
            self.mgr.show_title()

    def tick(self, now):
        self.scroll_target = clamp(self.scroll_target, 0.0, self.max_scroll)
        self.scroll += (self.scroll_target - self.scroll) * 0.3
        for _ in range(2):                                    # roster portraits, a couple per frame
            e = next((q for q in self.entries if not q.still_state), None)
            if e is None: break
            try: self.picker.engine.bake(e)
            except Exception: e.still_state = 2

    def on_wheel(self, d, pos):
        if self.mode == "hub":
            self.scroll_target = clamp(self.scroll_target - d * 0.7, 0.0, self.max_scroll)

    # ------------------------------------------------------------------ frame
    def paint_content(self, p, R, now):
        self.hint = None
        run = self.camp.run
        mode = self.mode
        if mode != "hub" and run is None: mode = "hub"
        getattr(self, "paint_" + mode)(p, R, now)

    # -------- shared pieces
    def wallet(self, p, xr, T):
        x = xr
        for label, val, c in (("PYROXENE", self.save.pyrox, QtGui.QColor(70, 150, 255)), ("CREDITS", self.save.credits, YELLOW_D)):
            w = 150.0
            r = QRectF(x - w, T.top() + 15, w, T.height() - 30)
            p.setPen(QtGui.QPen(col(c, 150), 1.2)); p.setBrush(col(WHITE, 245)); p.drawPolygon(para(r, 8))
            p.setPen(NOPEN); p.setBrush(c); p.drawPolygon(para(QRectF(r.left() + 3, r.top() + 3, 7, r.height() - 6), 3))
            text(p, QRectF(r.left() + 18, r.top(), w - 26, r.height() * 0.6), f"{val:,}", 15, NAVY, W_BLACK, True,
                 AF.AlignRight | AF.AlignVCenter)
            text(p, QRectF(r.left() + 18, r.top() + r.height() * 0.52, w - 26, r.height() * 0.45), label, 8, c.darker(125),
                 W_BLACK, False, AF.AlignRight | AF.AlignVCenter, 1.4)
            x -= w + 10
        return x

    def footer(self, p, R, h=78):
        F = QRectF(R.left(), R.bottom() - h, R.width(), h)
        p.fillRect(F, col(WHITE, 236)); p.fillRect(QRectF(F.left(), F.top(), F.width(), 1.5), col(BLUE, 60))
        return F

    def footer_text(self, p, r, default=""):
        s, c = default, col(NAVY, 190)
        if self.hint: s, c = self.hint, NAVY
        if self.msg is not None:
            age = time.perf_counter() - self.msg[1]
            if age < 3.5: s, c = self.msg[0], (BLUE_D if self.msg[2] else RED.darker(115))
            else: self.msg = None
        if s: wrapped(p, r, s, 12, c, W_BOLD, AF.AlignCenter)

    def panel(self, p, r, title=None, accent=BLUE):
        p.setPen(QtGui.QPen(col(accent, 70), 1.2)); p.setBrush(col(WHITE, 215)); p.drawRoundedRect(r, 12, 12)
        if title:
            p.setPen(NOPEN); p.setBrush(accent); p.drawPolygon(para(QRectF(r.left() + 12, r.top() + 10, 6, 16), 3))
            text(p, QRectF(r.left() + 26, r.top() + 8, r.width() - 40, 20), title, 12, NAVY, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, 1.6)

    def label(self, p, x, y, w, s, accent=BLUE):
        p.setPen(NOPEN); p.setBrush(accent); p.drawPolygon(para(QRectF(x, y + 2, 6, 14), 3))
        text(p, QRectF(x + 12, y, w, 18), s, 11, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.6)

    def lives(self, p, x, cy, n, c=BLUE, size=5.0):
        for k in range(max(0, int(n))):
            cx = x + k * (size * 2 + 3)
            d = QtGui.QPolygonF([QPointF(cx, cy - size), QPointF(cx + size * 0.85, cy), QPointF(cx, cy + size),
                                 QPointF(cx - size * 0.85, cy)])
            p.setPen(QtGui.QPen(WHITE, 1)); p.setBrush(c); p.drawPolygon(d)

    def badge(self, p, c, rad, kind, color):
        """The round emblem on a door / offer card."""
        p.setPen(QtGui.QPen(col(color, 90), 2)); p.setBrush(col(color, 34)); p.drawEllipse(c, rad, rad)
        p.setPen(NOPEN); p.setBrush(color); p.drawEllipse(c, rad * 0.74, rad * 0.74)
        if kind in ("boon", "boss", "heal", "stall", "cafe"):
            icon = {"boon": "flag", "boss": "cross", "heal": "cross_med", "stall": "home", "cafe": "heart"}[kind]
            glyph_icon(p, c, rad * 0.42, icon, WHITE, max(2.4, rad * 0.09))
        elif kind == "pyrox":
            r = rad * 0.44
            d = QtGui.QPolygonF([QPointF(c.x(), c.y() - r), QPointF(c.x() + r * 0.8, c.y() - r * 0.1), QPointF(c.x(), c.y() + r),
                                 QPointF(c.x() - r * 0.8, c.y() - r * 0.1)])
            p.setPen(QtGui.QPen(WHITE, 2)); p.setBrush(col(WHITE, 200)); p.drawPolygon(d)
        elif kind == "halo":
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QtGui.QPen(WHITE, max(3.0, rad * 0.12)))
            p.drawEllipse(c, rad * 0.46, rad * 0.2)
        else:
            s = {"credits": "CR", "supply": "KIT"}.get(kind, str(kind)[:4].upper())
            text(p, QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2), s, max(9, int(rad * 0.5 if len(s) < 3 else rad * 0.38)),
                 WHITE, W_BLACK, True)

    def squad_strip(self, p, r, run):
        n = max(1, len(run.squad))
        gap = 10.0
        w = min(270.0, (r.width() - (n - 1) * gap) / n)
        x0 = r.center().x() - (n * w + (n - 1) * gap) / 2
        for i, m in enumerate(run.squad):
            cr = QRectF(x0 + i * (w + gap), r.top(), w, r.height())
            lead = m["name"] == run.leader
            p.setPen(QtGui.QPen(col(YELLOW_D if lead else BLUE, 200 if lead else 90), 2 if lead else 1.2))
            p.setBrush(col(WHITE, 228 if not m["out"] else 150)); p.drawRoundedRect(cr, 10, 10)
            ph = cr.height() - 12
            pr = QRectF(cr.left() + 6, cr.top() + 6, ph, ph)
            e = self.by_name.get(m["name"])
            if e is not None: portrait(p, e, pr, 8)
            if m["out"]:
                p.setPen(QtGui.QPen(col(RED, 220), 3))
                p.drawLine(pr.topLeft(), pr.bottomRight()); p.drawLine(pr.topRight(), pr.bottomLeft())
            tx = pr.right() + 10
            tw = cr.right() - 10 - tx
            text(p, QRectF(tx, cr.top() + 5, tw, 18), m["name"], 13, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter,
                 elide=True)
            if lead:
                self.chip(p, QRectF(cr.right() - 62, cr.top() - 7, 54, 14), "LEADER", YELLOW_D, NAVY_D, 8)
            if m["out"]:
                text(p, QRectF(tx, cr.top() + 26, tw, 16), "RETIRED", 11, RED, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.5)
            else:
                bar = QRectF(tx, cr.top() + 28, tw, 8)
                p.setPen(NOPEN); p.setBrush(col(NAVY, 50)); p.drawRoundedRect(bar, 4, 4)
                hp = clamp(m["hp"], 0.0, 1.0)
                p.setBrush(GREEN if hp > 0.5 else (YELLOW_D if hp > 0.25 else RED))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * hp, bar.height()), 4, 4)
                text(p, QRectF(tx, bar.bottom() + 1, tw, 14), f"{hp * 100:.0f}% HP", 9, GREY, W_BOLD, False,
                     AF.AlignRight | AF.AlignVCenter)
                self.lives(p, tx + 6, bar.bottom() + 9, m["lives"], BLUE, 4.5)

    def boon_strip(self, p, r, run):
        self.label(p, r.left(), r.top() + (r.height() - 18) / 2, 90, "SUPPORTS")
        x = r.left() + 104
        if not run.boons:
            text(p, QRectF(x, r.top(), r.width() - 110, r.height()), "none yet - clear rooms behind the blue doors", 11,
                 col(GREY, 230), W_BOLD, True, AF.AlignLeft | AF.AlignVCenter)
            return
        fm = QtGui.QFontMetrics(font(10, W_BLACK, True))
        for i, (bid, rar) in enumerate(run.boons):
            b = BOON_BY_ID[bid]
            s = f"{b['name']} {ROMAN[rar]}"
            w = fm.horizontalAdvance(s) + 26
            if x + w > r.right() - 40:
                text(p, QRectF(x, r.top(), 60, r.height()), f"+{len(run.boons) - i}", 11, NAVY, W_BLACK, True,
                     AF.AlignLeft | AF.AlignVCenter)
                break
            cr = QRectF(x, r.center().y() - 11, w, 22)
            key = ("boon", i)
            c = qc(SCHOOL_COL.get(b["school"], (30, 161, 255)))
            p.setPen(QtGui.QPen(col(RARITY_COL[rar], 255), 2 if self.hover == key else 1.2)); p.setBrush(col(c, 235))
            p.drawPolygon(para(cr, 6))
            text(p, cr, s, 10, WHITE if c.lightness() < 170 else NAVY_D, W_BLACK, True, AF.AlignCenter, 0.4)
            self.hits.append((cr, key))
            if self.hover == key:
                self.hint = f"{b['school']}  \u00b7  {b['name']} ({RARITY[rar]}):  {boon_text(bid, rar)}"
            x += w + 6

    # ------------------------------------------------------------------ HUB
    def paint_hub(self, p, R, now):
        T, xr = self.header(p, R, "Campaign",
                            "OPERATION: KIVOTOS GAUNTLET  \u00b7  \u30ed\u30fc\u30b0\u30e9\u30a4\u30c8")
        self.wallet(p, xr, T)
        F = self.footer(p, R, 84)
        L = QRectF(R.left() + 18, T.bottom() + 12, 430, F.top() - T.bottom() - 24)
        G = QRectF(L.right() + 16, L.top(), R.right() - 18 - L.right() - 16, L.height())
        self.paint_setup(p, L, now)
        self.paint_roster(p, G, now)
        cy = F.center().y()
        self.button(p, QRectF(F.left() + 24, cy - 22, 190, 44), "Sora's Shop", ("shop",), accent=PINK, px=15, icon="heart")
        self.button(p, QRectF(F.left() + 226, cy - 22, 170, 44), "Title Screen", ("title",), accent=ORANGE, px=14, icon="home")
        ok = bool(self.squad())
        bw = 300.0
        self.big_button(p, QRectF(F.right() - 28 - bw, cy - 29, bw, 58), "SORTIE", "\u51fa\u6483  \u00b7  begin a new run",
                        ("sortie",), now, enabled=ok)
        self.footer_text(p, QRectF(F.left() + 410, F.top() + 8, F.width() - 410 - bw - 50, F.height() - 16),
                         "Pick a leader and her squad, pack supplies, then sortie. Everything you earn is spent at "
                         "Sora's shop: permanent training and consumable supplies.")

    def paint_setup(self, p, L, now):
        save = self.save
        meta = save.meta()
        self.panel(p, L)
        x, w = L.left() + 14, L.width() - 28
        y = L.top() + 12
        # ---- squad
        sq = self.squad()
        lead = self.leader()
        cap = 1 + int(meta["squad_slots"])
        self.label(p, x, y, w, f"SQUAD  {len(sq)}/{cap}")
        y += 24
        gap = 8.0
        sw = (w - 3 * gap) / 4
        sh = 100.0
        for i in range(4):
            r = QRectF(x + i * (sw + gap), y, sw, sh)
            if i < len(sq):
                name = sq[i]
                e = self.by_name[name]
                key = ("slot", i)
                is_lead = name == lead
                c = YELLOW_D if is_lead else BLUE
                p.setPen(QtGui.QPen(col(c, 255), 3 if (is_lead or self.hover == key) else 1.6)); p.setBrush(WHITE)
                p.drawRoundedRect(r, 9, 9)
                portrait(p, e, r.adjusted(3, 3, -3, -22), 7)
                nr = QRectF(r.left() + 2, r.bottom() - 21, r.width() - 4, 19)
                p.setPen(NOPEN); p.setBrush(col(NAVY, 230)); p.drawRoundedRect(nr, 6, 6)
                text(p, nr.adjusted(3, 0, -3, 0), name, 10, WHITE, W_BLACK, True, AF.AlignCenter, elide=True)
                self.chip(p, QRectF(r.left() + 4, r.top() + 4, 52 if is_lead else 40, 14), "LEADER" if is_lead else "ALLY", c,
                          NAVY_D if is_lead else WHITE, 8)
                self.hits.append((r, key))
            elif i < cap:
                pen = QtGui.QPen(col(BLUE, 130), 1.6); pen.setDashPattern([4, 4])
                p.setPen(pen); p.setBrush(col(SKY, 120)); p.drawRoundedRect(r, 9, 9)
                text(p, r, "EMPTY", 11, col(BLUE_D, 200), W_BLACK, True)
            else:
                p.setPen(QtGui.QPen(col(GREY, 90), 1.2)); p.setBrush(col(GREY, 40)); p.drawRoundedRect(r, 9, 9)
                text(p, r.adjusted(0, -8, 0, -8), "LOCKED", 11, col(GREY, 220), W_BLACK, True)
                text(p, r.adjusted(0, 22, 0, 22), "Sora's shop", 9, col(GREY, 200), W_BOLD, False)
        y += sh + 4
        wrapped(p, QRectF(x, y, w, 30), "Click a squad member to make her the leader (the student you control). "
                                       "Right-click sends her home.", 10, col(GREY, 235))
        y += 36
        # ---- supplies
        lo = save.loadout()
        self.label(p, x, y, w, f"SUPPLIES  {sum(1 for s in lo if s)}/{len(lo)}", ORANGE)
        y += 24
        ih = 58.0
        for i in range(4):
            r = QRectF(x + i * (sw + gap), y, sw, ih)
            if i < len(lo):
                key = ("supply", i)
                hov = self.hover == key
                iid = lo[i]
                p.setPen(QtGui.QPen(col(ORANGE, 255 if hov else 150), 2 if hov else 1.4))
                p.setBrush(WHITE if iid else col(SKY, 120)); p.drawRoundedRect(r, 9, 9)
                if iid:
                    c = ITEM_BY_ID[iid]
                    text(p, QRectF(r.left(), r.top() + 4, sw, 20), c["tag"], 14, QtGui.QColor.fromHsv(int(c["hue"]) % 360, 190, 220),
                         W_BLACK, True)
                    text(p, QRectF(r.left() + 3, r.top() + 24, sw - 6, 14), c["name"], 9, NAVY, W_BOLD, False, AF.AlignCenter, elide=True)
                    text(p, QRectF(r.left(), r.top() + 38, sw, 16), f"x{save.count(iid)}", 11, BLUE_D, W_BLACK, True)
                    if hov: self.hint = f"{c['name']}:  {c['desc']}"
                else:
                    text(p, r, "EMPTY", 11, col(BLUE_D, 200), W_BLACK, True)
                self.hits.append((r, key))
            else:
                p.setPen(QtGui.QPen(col(GREY, 90), 1.2)); p.setBrush(col(GREY, 40)); p.drawRoundedRect(r, 9, 9)
                text(p, r, "LOCKED", 10, col(GREY, 220), W_BLACK, True)
        y += ih + 4
        text(p, QRectF(x, y, w, 16), "Click a slot to change what you pack. Stock is bought at Sora's shop.", 10,
             col(GREY, 235), W_BOLD, False, AF.AlignLeft | AF.AlignVCenter)
        y += 26
        # ---- control
        manual = bool(save.d.get("manual", True))
        row = QRectF(x, y, w, 30)
        text(p, row, "Manual control", 13, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter)
        self.toggle(p, row, manual, ("manual",))
        y += 30
        text(p, QRectF(x, y, w, 16), "You drive the leader yourself." if manual else "Autopilot: the whole squad fights on its own tactics.",
             10, col(GREY, 235), W_BOLD, False, AF.AlignLeft | AF.AlignVCenter)
        y += 24
        # ---- threat level
        unlocked = int(save.d.get("heat_unlocked", 0))
        row = QRectF(x, y, w, 30)
        text(p, row, "Threat level", 13, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter)
        if unlocked > 0:
            self.stepper(p, row, f"{int(save.d.get('heat', 0))} / {unlocked}", ("heat",))
        else:
            text(p, row, "clear the campaign to unlock", 10, col(GREY, 220), W_BOLD, True, AF.AlignRight | AF.AlignVCenter)
        y += 38
        # ---- record
        st = save.d["stats"]
        self.label(p, x, y, w, "RECORD", GREEN)
        y += 22
        lines = (f"Runs {st['runs']}   \u00b7   Clears {st['wins']}   \u00b7   Best: room {st['best_room']}/{TOTAL_ROOMS}   \u00b7   KOs {st['kills']}",
                 f"Lives {int(meta['lives'])}   \u00b7   Heal between rooms {meta['heal_between'] * 100:.0f}%   \u00b7   Re-rolls {int(meta['rerolls'])}",
                 f"HP x{meta['hp']:.2f}   \u00b7   Damage x{meta['dmg']:.2f}   \u00b7   Damage taken x{meta['taken']:.2f}   \u00b7   Crit +{meta['crit'] * 100:.0f}%")
        for s in lines:
            text(p, QRectF(x, y, w, 16), s, 10, NAVY, W_BOLD, False, AF.AlignLeft | AF.AlignVCenter, elide=True)
            y += 17
        if L.bottom() - y > 84:
            y += 8
            self.label(p, x, y, w, "CONTROLS", PURPLE)
            wrapped(p, QRectF(x, y + 22, w, L.bottom() - y - 30), CONTROLS, 10, col(GREY, 240))

    def paint_roster(self, p, G, now):
        self.panel(p, G)
        sq = self.squad()
        lead = self.leader()
        self.label(p, G.left() + 14, G.top() + 12, 300, f"STUDENTS  {len(self.entries)}")
        text(p, QRectF(G.left() + 200, G.top() + 12, G.width() - 216, 18),
             "click: add / remove   \u00b7   right-click: leader   \u00b7   the rest are your enemies", 10,
             col(GREY, 235), W_BOLD, False, AF.AlignRight | AF.AlignVCenter, elide=True)
        V = QRectF(G.left() + 10, G.top() + 40, G.width() - 20, G.height() - 50)
        cw, ch, gap = 108.0, 134.0, 10.0
        cols = max(1, int((V.width() + gap) // (cw + gap)))
        rows = math.ceil(len(self.entries) / cols)
        self.max_scroll = max(0.0, rows * (ch + gap) - gap - V.height())
        x0 = V.left() + (V.width() - (cols * cw + (cols - 1) * gap)) / 2
        p.save(); p.setClipRect(V, Qt.ClipOperation.IntersectClip)
        for i, e in enumerate(self.entries):
            row, cix = divmod(i, cols)
            r = QRectF(x0 + cix * (cw + gap), V.top() + row * (ch + gap) - self.scroll, cw, ch)
            if r.bottom() < V.top() or r.top() > V.bottom(): continue
            key = ("card", e.name)
            hov = self.hover == key
            inq = e.name in sq
            is_lead = e.name == lead
            c = YELLOW_D if is_lead else (BLUE if inq else col(NAVY, 60))
            if hov: r = r.translated(0, -2)
            p.setPen(QtGui.QPen(c, 3 if inq else (2 if hov else 1.2))); p.setBrush(WHITE); p.drawRoundedRect(r, 10, 10)
            portrait(p, e, r.adjusted(3, 3, -3, -26), 8)
            nr = QRectF(r.left() + 2, r.bottom() - 25, r.width() - 4, 23)
            p.setPen(NOPEN); p.setBrush(col(NAVY, 230) if not inq else c.darker(110) if not is_lead else YELLOW_D)
            p.drawRoundedRect(nr, 7, 7)
            text(p, nr.adjusted(3, 0, -3, 0), e.name, 11, NAVY_D if is_lead else WHITE, W_BLACK, True, AF.AlignCenter, elide=True)
            prof = self.profiles[e.name]
            self.chip(p, QRectF(r.left() + 5, r.top() + 5, 30, 14), prof.short(), BLUE_D, px=8)
            if inq:
                self.chip(p, QRectF(r.right() - 57, r.top() + 5, 52, 14), "LEADER" if is_lead else "SQUAD", c,
                          NAVY_D if is_lead else WHITE, 8)
            if hov:
                self.hint = f"{e.name}  \u00b7  {prof.role}  \u00b7  {prof.weapon}  \u00b7  EX: {prof.ex_name[0]}"
            vis = r.intersected(V)
            self.hits.append((vis, key))
        p.restore()
        if self.max_scroll > 0:
            tr = QRectF(G.right() - 8, V.top(), 4, V.height())
            p.setPen(NOPEN); p.setBrush(col(NAVY, 30)); p.drawRoundedRect(tr, 2, 2)
            th = max(30.0, tr.height() * V.height() / (V.height() + self.max_scroll))
            p.setBrush(col(BLUE, 170))
            p.drawRoundedRect(QRectF(tr.left(), tr.top() + (tr.height() - th) * (self.scroll / self.max_scroll), 4, th), 2, 2)

    # ------------------------------------------------------------------ DOORS
    def paint_doors(self, p, R, now):
        run = self.camp.run
        a = area_of(run.room)
        area = AREAS[a]
        ac = qc(area["color"])
        step = run.room % ROOMS_PER_AREA + 1
        T, xr = self.header(p, R, f"Area {a + 1}  \u00b7  {area['name']}",
                            f"ROOM {step}/{ROOMS_PER_AREA}  \u00b7  {area['jp']}  \u00b7  CHOOSE YOUR PATH", accent=ac)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 70)
        y = T.bottom() + 10
        self.paint_track(p, QRectF(R.left() + 40, y, R.width() - 80, 40), run, now)
        y += 46
        self.squad_strip(p, QRectF(R.left() + 20, y, R.width() - 40, 72), run)
        y += 80
        self.boon_strip(p, QRectF(R.left() + 24, y, R.width() - 48, 28), run)
        y += 34
        box = QRectF(R.left() + 20, y, R.width() - 40, F.top() - y - 10)
        doors = run.doors
        n = max(1, len(doors))
        gap = 24.0
        cw = min(350.0, (box.width() - (n - 1) * gap) / n)
        x0 = box.center().x() - (n * cw + (n - 1) * gap) / 2
        for i, d in enumerate(doors):
            a_in = ease_out((now - self.t_mode - i * 0.08) / 0.35)
            self.paint_door(p, QRectF(x0 + i * (cw + gap), box.top() + (1 - a_in) * 24, cw, box.height()), d, i, now, a_in)
        cy = F.center().y()
        sure = now - self.confirm_t < 3.0
        self.button(p, QRectF(F.left() + 24, cy - 20, 230, 40), "Click again to abandon" if sure else "Abandon Run",
                    ("abandon",), accent=RED if sure else ORANGE, px=13, icon="close")
        self.footer_text(p, QRectF(F.left() + 270, F.top() + 6, F.width() - 540, F.height() - 12),
                         f"Rooms cleared {run.cleared}/{TOTAL_ROOMS}   \u00b7   KOs {run.kills}   \u00b7   this run: "
                         f"+{run.credits:,} Credits, +{run.pyrox} Pyroxene")
        text(p, QRectF(F.right() - 270, F.top(), 246, F.height()), "HP and lives carry over between rooms", 10,
             col(GREY, 230), W_BOLD, True, AF.AlignRight | AF.AlignVCenter)

    def paint_track(self, p, r, run, now):
        n = TOTAL_ROOMS
        y = r.center().y()
        xs = [r.left() + r.width() * i / (n - 1) for i in range(n)]
        for i in range(n - 1):
            c = qc(AREAS[area_of(i)]["color"])
            p.setPen(QtGui.QPen(col(c, 230) if i < run.room else col(NAVY, 50), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(xs[i], y), QPointF(xs[i + 1], y))
        for i in range(n):
            c = qc(AREAS[area_of(i)]["color"])
            boss = is_boss_room(i)
            rad = 12.0 if boss else 7.5
            if i == run.room:
                pulse = 0.5 + 0.5 * math.sin(now * 5)
                p.setPen(QtGui.QPen(col(YELLOW_D, 120 + 120 * pulse), 3)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(xs[i], y), rad + 5, rad + 5)
            p.setPen(QtGui.QPen(c if i <= run.room else col(NAVY, 90), 2))
            p.setBrush(c if i < run.room else (YELLOW if i == run.room else WHITE))
            p.drawEllipse(QPointF(xs[i], y), rad, rad)
            if boss:
                glyph_icon(p, QPointF(xs[i], y), 6, "cross", WHITE if i < run.room else (NAVY_D if i == run.room else col(NAVY, 150)), 2)

    def paint_door(self, p, r, d, i, now, a=1.0):
        key = ("door", i)
        hov = self.hover == key
        kind = d["kind"]
        if kind == "boss": c, tag, bk = RED_T, "BOSS", "boss"
        elif kind == "stall": c, tag, bk = PINK, "NO FIGHT", "stall"
        elif kind == "cafe": c, tag, bk = GREEN, "NO FIGHT", "cafe"
        else: c, tag, bk = REWARD_COL.get(d["reward"], BLUE), ("ELITE" if d["elite"] else ""), d["reward"]
        if hov: r = r.translated(0, -5)
        p.save(); p.setOpacity(a)
        path = rounded(r, 14)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 40)); p.drawPath(rounded(r.translated(0, 7), 14))
        p.setPen(QtGui.QPen(col(YELLOW_D if hov else c, 255), 3 if hov else 1.6)); p.setBrush(col(WHITE, 245)); p.drawPath(path)
        p.save(); p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        band = QRectF(r.left(), r.top(), r.width(), 58)
        g = QtGui.QLinearGradient(band.topLeft(), band.topRight())
        g.setColorAt(0, c); g.setColorAt(1, c.darker(125))
        p.fillRect(band, g)
        p.setPen(QtGui.QPen(col(WHITE, 34), 9))
        sx = band.left() - 60 + (now * 30) % 44
        while sx < band.right():
            p.drawLine(QPointF(sx, band.bottom()), QPointF(sx + 34, band.top())); sx += 44
        p.restore()
        text(p, QRectF(r.left() + 16, r.top() + 6, r.width() - 32, 30), d["title"], 20, WHITE, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, elide=True)
        sub = "AREA BOSS" if kind == "boss" else ("SAFE ROOM" if kind in ("stall", "cafe") else
                                                  ("ELITE GUARD  \u00b7  better reward" if d["elite"] else "REWARD AFTER THE FIGHT"))
        text(p, QRectF(r.left() + 17, r.top() + 36, r.width() - 32, 16), sub, 9, col(WHITE, 235), W_BLACK, False,
             AF.AlignLeft | AF.AlignVCenter, 1.6)
        if tag:
            self.chip(p, QRectF(r.right() - 84, r.top() + 10, 70, 18), tag, PURPLE if tag == "ELITE" else NAVY_D, WHITE, 9)
        body_h = r.height() - 58
        rad = clamp(body_h * 0.14, 20.0, 40.0)
        bc = QPointF(r.center().x(), band.bottom() + 14 + rad)
        self.badge(p, bc, rad, bk, c)
        ty = bc.y() + rad + 8
        en = d.get("enemies") or []
        foot = 46.0
        en_h = 74.0 if en else 0.0
        wrapped(p, QRectF(r.left() + 18, ty, r.width() - 36, max(20.0, r.bottom() - foot - en_h - ty)), d["desc"], 12,
                NAVY, W_BOLD, AF.AlignHCenter | AF.AlignTop)
        if en:
            ey = r.bottom() - foot - en_h
            text(p, QRectF(r.left() + 16, ey, r.width() - 32, 16), f"HOSTILES  \u00d7{len(en)}", 10, col(GREY, 240), W_BLACK,
                 True, AF.AlignLeft | AF.AlignVCenter, 1.4)
            ps = min(46.0, (r.width() - 32 - (len(en) - 1) * 6) / len(en))
            for k, sp in enumerate(en):
                pr = QRectF(r.left() + 16 + k * (ps + 6), ey + 20, ps, ps)
                e = self.by_name.get(sp["name"])
                if e is not None: portrait(p, e, pr, 7)
                tc = {"boss": YELLOW_D, "elite": PURPLE}.get(sp["tier"], col(RED_T, 170))
                p.setPen(QtGui.QPen(tc, 3 if sp["tier"] != "grunt" else 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(pr, 7, 7)
                if sp["tier"] != "grunt":
                    self.chip(p, QRectF(pr.left() - 2, pr.bottom() - 9, min(ps + 4, 42.0), 12), sp["tier"].upper(), tc,
                              NAVY_D if sp["tier"] == "boss" else WHITE, 7)
        er = QRectF(r.left() + 14, r.bottom() - foot + 6, r.width() - 28, foot - 16)
        p.setPen(NOPEN); p.setBrush(YELLOW if hov else col(c, 40)); p.drawPolygon(para(er, 8))
        text(p, er, "ENTER  \u25b6" if kind in ("fight", "boss") else "VISIT  \u25b6", 13, NAVY_D if hov else c.darker(140), W_BLACK,
             True, AF.AlignCenter, 2.0)
        p.restore()
        self.hits.append((path, key))

    # ------------------------------------------------------------------ REWARD / STALL / CAFE
    def room_banner(self, p, R, T, title, sub, c, run, now):
        ban = QRectF(R.left(), T.bottom(), R.width(), 92)
        g = QtGui.QLinearGradient(ban.topLeft(), ban.topRight())
        g.setColorAt(0, col(c, 240)); g.setColorAt(1, col(c.darker(140), 240))
        p.fillRect(ban, g)
        p.setPen(QtGui.QPen(col(WHITE, 36), 10))
        x = ban.left() - 200 + (now * 60) % 80
        while x < ban.right():
            p.drawLine(QPointF(x, ban.bottom()), QPointF(x + 80, ban.top())); x += 80
        pop = ease_back(clamp((now - self.t_mode) / 0.45, 0, 1))
        p.save(); p.translate(ban.left() + 36, ban.center().y() - 6); p.scale(pop, pop)
        ArenaOverlay.outlined(p, QRectF(0, -34, 520, 56), title, 46, WHITE, NAVY_D)
        p.restore()
        text(p, QRectF(ban.left() + 40, ban.bottom() - 30, 600, 22), sub, 13, col(WHITE, 240), W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 2.4)
        rep = run.report or {}
        stats = (("KOs", str(rep.get("kills", 0))), ("CREDITS", f"+{rep.get('credits', 0):,}"), ("PYROXENE", f"+{rep.get('pyrox', 0)}"))
        for k, (lab, val) in enumerate(stats):
            sr = QRectF(ban.right() - 30 - (3 - k) * 138, ban.top() + 20, 128, 52)
            p.setPen(NOPEN); p.setBrush(col(WHITE, 235)); p.drawPolygon(para(sr, 10))
            text(p, QRectF(sr.left(), sr.top() + 3, sr.width(), 28), val, 19, NAVY, W_BLACK, True)
            text(p, QRectF(sr.left(), sr.top() + 31, sr.width(), 16), lab, 9, BLUE_D, W_BLACK, False, AF.AlignCenter, 1.6)
        return ban

    def notes(self, p, R, y, run):
        for s in (run.report or {}).get("notes", []):
            r = QRectF(R.left() + 40, y, R.width() - 80, 28)
            p.setPen(NOPEN); p.setBrush(col(WHITE, 225)); p.drawPolygon(para(r, 8))
            p.setBrush(YELLOW_D); p.drawPolygon(para(QRectF(r.left() + 3, r.top() + 3, 7, r.height() - 6), 3))
            text(p, r.adjusted(22, 0, -12, 0), s, 13, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, elide=True)
            y += 34
        return y

    def paint_reward(self, p, R, now):
        run = self.camp.run
        door = (run.report or {}).get("door") or {}
        boss = door.get("kind") == "boss"
        T, xr = self.header(p, R, "Room Clear", "\u6226\u95d8\u7d42\u4e86  \u00b7  COLLECT YOUR REWARD", back=False, close=False)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 78)
        ban = self.room_banner(p, R, T, "BOSS DOWN" if boss else "ROOM CLEAR",
                               door.get("title", "") + ("  \u00b7  ELITE" if door.get("elite") else ""),
                               qc(AREAS[door.get("area", 0)]["color"]), run, now)
        y = self.notes(p, R, ban.bottom() + 12, run)
        self.squad_strip(p, QRectF(R.left() + 20, y + 2, R.width() - 40, 66), run)
        y += 78
        pend = run.pending
        cy = F.center().y()
        if pend and pend.get("type") == "boon":
            self.label(p, R.left() + 40, y, 400, "CHOOSE ONE SUPPORT  \u00b7  it lasts until the run ends", YELLOW_D)
            y += 26
            ch = pend["choices"]
            n = len(ch)
            gap = 22.0
            box = QRectF(R.left() + 40, y, R.width() - 80, F.top() - y - 12)
            cw = min(340.0, (box.width() - (n - 1) * gap) / n)
            x0 = box.center().x() - (n * cw + (n - 1) * gap) / 2
            for i, (bid, rar) in enumerate(ch):
                a_in = ease_out((now - self.t_mode - 0.15 - i * 0.08) / 0.35)
                self.paint_boon(p, QRectF(x0 + i * (cw + gap), box.top() + (1 - a_in) * 20, cw, box.height()), bid, rar,
                                ("pick", i), a_in, run)
            self.button(p, QRectF(F.left() + 24, cy - 20, 220, 40), f"Re-roll  ({run.rerolls} left)", ("reroll",),
                        accent=PURPLE, px=13, icon="shuffle", enabled=run.rerolls > 0)
            self.footer_text(p, QRectF(F.left() + 260, F.top() + 6, F.width() - 520, F.height() - 12),
                             "Click a card to take it. Rarer supports are stronger; the same support can be taken twice.")
        else:
            last = run.room >= TOTAL_ROOMS - 1
            self.big_button(p, QRectF(F.right() - 28 - 300, cy - 28, 300, 56), "FINISH" if last else "CONTINUE",
                            "the campaign is won" if last else "\u6b21\u3078  \u00b7  to the next doors", ("continue",), now)
            self.footer_text(p, QRectF(F.left() + 24, F.top() + 6, F.width() - 380, F.height() - 12),
                             "Credits and Pyroxene are banked at once - they are yours even if the run fails.")

    def paint_boon(self, p, r, bid, rar, key, a, run):
        b = BOON_BY_ID[bid]
        hov = self.hover == key
        c = qc(SCHOOL_COL.get(b["school"], (30, 161, 255)))
        rc = RARITY_COL[rar]
        if hov: r = r.translated(0, -5)
        p.save(); p.setOpacity(a)
        path = rounded(r, 14)
        p.setPen(NOPEN); p.setBrush(col(NAVY_D, 40)); p.drawPath(rounded(r.translated(0, 7), 14))
        p.setPen(QtGui.QPen(YELLOW_D if hov else rc, 3 if (hov or rar) else 1.6)); p.setBrush(col(WHITE, 248)); p.drawPath(path)
        p.save(); p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        band = QRectF(r.left(), r.top(), r.width(), 44)
        g = QtGui.QLinearGradient(band.topLeft(), band.topRight())
        g.setColorAt(0, c); g.setColorAt(1, c.darker(130))
        p.fillRect(band, g)
        p.restore()
        ink = WHITE if c.lightness() < 170 else NAVY_D
        text(p, QRectF(r.left() + 16, r.top(), r.width() - 110, 44), b["school"].upper(), 13, ink, W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 2.4)
        self.chip(p, QRectF(r.right() - 92, r.top() + 13, 78, 18), RARITY[rar].upper(), rc, WHITE, 9)
        body = r.height() - 44
        rad = clamp(body * 0.13, 16.0, 30.0)
        self.badge(p, QPointF(r.center().x(), band.bottom() + 12 + rad), rad, "boon", c)
        ty = band.bottom() + 20 + rad * 2
        text(p, QRectF(r.left() + 12, ty, r.width() - 24, 28), b["name"], 19, NAVY, W_BLACK, True, AF.AlignCenter, elide=True)
        wrapped(p, QRectF(r.left() + 20, ty + 32, r.width() - 40, max(20.0, r.bottom() - 40 - ty - 32)), boon_text(bid, rar),
                13, NAVY, W_BOLD, AF.AlignHCenter | AF.AlignTop)
        have = sum(1 for x, _r in run.boons if x == bid)
        tr = QRectF(r.left() + 14, r.bottom() - 34, r.width() - 28, 24)
        p.setPen(NOPEN); p.setBrush(YELLOW if hov else col(c, 40)); p.drawPolygon(para(tr, 7))
        text(p, tr, "TAKE" + (f"   (you have {have})" if have else ""), 12, NAVY_D if hov else c.darker(150), W_BLACK, True,
             AF.AlignCenter, 2.0)
        p.restore()
        self.hits.append((path, key))

    def paint_stall(self, p, R, now):
        run = self.camp.run
        T, xr = self.header(p, R, "Sora's Field Stall", "\u30bd\u30e9\u306e\u51fa\u5f35\u30b7\u30e7\u30c3\u30d7  \u00b7  CREDITS ONLY",
                            back=False, close=False, accent=PINK)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 78)
        y = T.bottom() + 14
        wrapped(p, QRectF(R.left() + 40, y, R.width() - 80, 40),
                "\u201cOh! Sensei... I, um, brought the cart. Please take a look, if you'd like.\u201d  Everything here is paid in "
                "Credits and used right away (supplies go into your stock).", 13, NAVY, W_BOLD, AF.AlignLeft | AF.AlignVCenter, True)
        y += 50
        self.squad_strip(p, QRectF(R.left() + 20, y, R.width() - 40, 66), run)
        y += 80
        offers = run.stall or []
        n = max(1, len(offers))
        gap = 14.0
        box = QRectF(R.left() + 30, y, R.width() - 60, F.top() - y - 12)
        cw = min(240.0, (box.width() - (n - 1) * gap) / n)
        x0 = box.center().x() - (n * cw + (n - 1) * gap) / 2
        for i, o in enumerate(offers):
            r = QRectF(x0 + i * (cw + gap), box.top(), cw, min(box.height(), 300.0))
            key = ("stall", i)
            hov = self.hover == key and not o["sold"]
            c = QtGui.QColor.fromHsv(int(o["hue"]) % 360, 170, 235)
            afford = self.save.credits >= o["price"]
            p.save(); p.setOpacity(0.5 if o["sold"] else 1.0)
            p.setPen(QtGui.QPen(YELLOW_D if hov else col(c, 220), 3 if hov else 1.6)); p.setBrush(col(WHITE, 245))
            p.drawRoundedRect(r, 12, 12)
            rad = clamp(r.height() * 0.13, 18.0, 34.0)
            self.badge(p, QPointF(r.center().x(), r.top() + 16 + rad), rad, o["tag"], c)
            ty = r.top() + 24 + rad * 2
            text(p, QRectF(r.left() + 8, ty, r.width() - 16, 24), o["name"], 16, NAVY, W_BLACK, True, AF.AlignCenter, elide=True)
            wrapped(p, QRectF(r.left() + 14, ty + 28, r.width() - 28, max(20.0, r.bottom() - 52 - ty - 28)), o["desc"], 11,
                    col(NAVY, 230), W_BOLD, AF.AlignHCenter | AF.AlignTop)
            br = QRectF(r.left() + 12, r.bottom() - 44, r.width() - 24, 32)
            p.setPen(NOPEN)
            p.setBrush(col(GREY, 120) if o["sold"] else (YELLOW if hov else (col(YELLOW_D, 230) if afford else col(GREY, 90))))
            p.drawPolygon(para(br, 8))
            text(p, br, "SOLD" if o["sold"] else f"{o['price']:,}  CREDITS", 13, NAVY_D if (afford or o["sold"]) else col(NAVY, 150),
                 W_BLACK, True, AF.AlignCenter, 1.0)
            p.restore()
            if not o["sold"]: self.hits.append((r, key))
        cy = F.center().y()
        self.big_button(p, QRectF(F.right() - 28 - 280, cy - 28, 280, 56), "MOVE ON", "\u6b21\u3078  \u00b7  back to the doors",
                        ("continue",), now)
        self.footer_text(p, QRectF(F.left() + 24, F.top() + 6, F.width() - 360, F.height() - 12),
                         "Sora's real shop (main menu) sells the permanent upgrades.")

    def paint_cafe(self, p, R, now):
        run = self.camp.run
        T, xr = self.header(p, R, "Caf\u00e9 Break", "\u30ab\u30d5\u30a7  \u00b7  THE SQUAD CATCHES ITS BREATH", back=False,
                            close=False, accent=GREEN)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 78)
        ban = self.room_banner(p, R, T, "TAKE FIVE", "no fight in this room", GREEN.darker(115), run, now)
        y = self.notes(p, R, ban.bottom() + 16, run)
        self.squad_strip(p, QRectF(R.left() + 20, y + 6, R.width() - 40, 78), run)
        y += 100
        self.boon_strip(p, QRectF(R.left() + 40, y, R.width() - 80, 28), run)
        self.big_button(p, QRectF(F.right() - 28 - 280, F.center().y() - 28, 280, 56), "MOVE ON",
                        "\u6b21\u3078  \u00b7  back to the doors", ("continue",), now)
        self.footer_text(p, QRectF(F.left() + 24, F.top() + 6, F.width() - 360, F.height() - 12), "")

    # ------------------------------------------------------------------ RESULT
    def paint_result(self, p, R, now):
        run = self.camp.run
        win = run.over == "win"
        T, xr = self.header(p, R, "Campaign Report", "\u4f5c\u6226\u5831\u544a  \u00b7  OPERATION: KIVOTOS GAUNTLET", back=False,
                            close=False)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 84)
        c = YELLOW_D if win else (GREY if run.over == "abandon" else RED_T)
        title = "CAMPAIGN CLEAR" if win else ("RUN ABANDONED" if run.over == "abandon" else "SQUAD RETIRED")
        a = area_of(min(run.room, TOTAL_ROOMS - 1))
        sub = ("every area boss has fallen  \u00b7  \u5b8c\u5168\u52dd\u5229" if win else
               f"stopped in Area {a + 1}, room {min(run.room, TOTAL_ROOMS - 1) % ROOMS_PER_AREA + 1}  \u00b7  {AREAS[a]['name']}")
        ban = QRectF(R.left(), T.bottom(), R.width(), 120)
        g = QtGui.QLinearGradient(ban.topLeft(), ban.topRight())
        g.setColorAt(0, col(c, 240)); g.setColorAt(1, col(c.darker(150), 240))
        p.fillRect(ban, g)
        p.setPen(QtGui.QPen(col(WHITE, 36), 10))
        x = ban.left() - 200 + (now * 60) % 80
        while x < ban.right():
            p.drawLine(QPointF(x, ban.bottom()), QPointF(x + 80, ban.top())); x += 80
        pop = ease_back(clamp((now - self.t_mode) / 0.5, 0, 1))
        p.save(); p.translate(ban.left() + 40, ban.center().y() - 8); p.scale(pop, pop)
        ArenaOverlay.outlined(p, QRectF(0, -40, 760, 64), title, 58, WHITE, NAVY_D)
        p.restore()
        text(p, QRectF(ban.left() + 44, ban.bottom() - 36, R.width() - 88, 24), sub, 14, col(WHITE, 240), W_BLACK, True,
             AF.AlignLeft | AF.AlignVCenter, 2.4)
        y = ban.bottom() + 18
        tiles = (("ROOMS CLEARED", f"{run.cleared} / {TOTAL_ROOMS}", BLUE), ("KNOCK-OUTS", str(run.kills), RED_T),
                 ("CREDITS EARNED", f"+{run.credits:,}", YELLOW_D),
                 ("PYROXENE EARNED", f"+{run.pyrox}", QtGui.QColor(70, 150, 255)))
        tw = (R.width() - 80 - 3 * 16) / 4
        for k, (lab, val, tc) in enumerate(tiles):
            tr = QRectF(R.left() + 40 + k * (tw + 16), y, tw, 84)
            p.setPen(QtGui.QPen(col(tc, 120), 1.4)); p.setBrush(col(WHITE, 235)); p.drawRoundedRect(tr, 12, 12)
            p.setPen(NOPEN); p.setBrush(tc); p.drawPolygon(para(QRectF(tr.left() + 10, tr.top() + 12, 7, 20), 3))
            text(p, QRectF(tr.left() + 24, tr.top() + 10, tw - 34, 22), lab, 10, tc.darker(130), W_BLACK, False,
                 AF.AlignLeft | AF.AlignVCenter, 1.6)
            text(p, QRectF(tr.left() + 12, tr.top() + 34, tw - 24, 42), val, 30, NAVY, W_BLACK, True)
        y += 100
        if win and run.win_bonus:
            text(p, QRectF(R.left() + 40, y, R.width() - 80, 20), f"Clear bonus: +{run.win_bonus} Pyroxene (included above)"
                 + ("   \u00b7   a higher threat level is now available in the hub" if run.heat < 3 else ""), 12, NAVY, W_BLACK,
                 True, AF.AlignLeft | AF.AlignVCenter)
            y += 26
        self.squad_strip(p, QRectF(R.left() + 20, y, R.width() - 40, 72), run)
        y += 84
        self.boon_strip(p, QRectF(R.left() + 40, y, R.width() - 80, 28), run)
        y += 40
        if F.top() - y > 44:
            wrapped(p, QRectF(R.left() + 40, y, R.width() - 80, F.top() - y - 8),
                    "Everything you earned is already in your wallet. Visit Sora: Pyroxene buys permanent training (HP, damage, "
                    "lives, squad slots, re-rolls ...), Credits buy supplies to pack for the next run.", 13, col(NAVY, 230), W_BOLD)
        cy = F.center().y()
        self.big_button(p, QRectF(F.right() - 28 - 300, cy - 29, 300, 58), "CAMPAIGN MENU", "squad, supplies and a new sortie",
                        ("hub",), now)
        self.button(p, QRectF(F.right() - 28 - 300 - 20 - 200, cy - 22, 200, 44), "Sora's Shop", ("shop",), accent=PINK, px=15,
                    icon="heart")
        self.button(p, QRectF(F.right() - 28 - 300 - 20 - 200 - 14 - 190, cy - 22, 190, 44), "Title Screen", ("title",),
                    accent=ORANGE, px=14, icon="home")
        self.footer_text(p, QRectF(F.left() + 24, F.top() + 6, F.width() - 800, F.height() - 12), "")

    # ------------------------------------------------------------------ COUNTER (no QtWebEngine)
    def paint_counter(self, p, R, now):
        save = self.save
        T, xr = self.header(p, R, "Sora's Counter", "\u30bd\u30e9\u306e\u30b7\u30e7\u30c3\u30d7  \u00b7  PERMANENT UPGRADES & SUPPLIES",
                            accent=PINK)
        self.wallet(p, xr, T)
        F = self.footer(p, R, 70)
        st = save.shop_state()
        y = T.bottom() + 12
        for i, (tid, lab) in enumerate((("training", "Training"), ("unlocks", "Unlocks"), ("supplies", "Supplies"))):
            self.button(p, QRectF(R.left() + 30 + i * 190, y, 176, 38), lab, ("tab", tid), accent=PINK, px=14,
                        active=self.counter_tab == tid)
        text(p, QRectF(R.left() + 620, y, R.width() - 650, 38),
             "Training and unlocks are permanent (Pyroxene). Supplies are used up (Credits).", 11, col(GREY, 235), W_BOLD,
             True, AF.AlignRight | AF.AlignVCenter, elide=True)
        y += 52
        items = st["items"] if self.counter_tab == "supplies" else [u for u in st["upgrades"] if u["tab"] == self.counter_tab]
        cols, gap = 4, 14.0
        box = QRectF(R.left() + 30, y, R.width() - 60, F.top() - y - 12)
        rows = max(1, math.ceil(len(items) / cols))
        cw = (box.width() - (cols - 1) * gap) / cols
        ch = min(230.0, (box.height() - (rows - 1) * gap) / rows)
        for i, it in enumerate(items):
            row, cix = divmod(i, cols)
            r = QRectF(box.left() + cix * (cw + gap), box.top() + row * (ch + gap), cw, ch)
            key = ("buy", it["id"])
            maxed = it["price"] is None
            afford = (not maxed) and (save.pyrox if it["cur"] == "pyrox" else save.credits) >= it["price"]
            hov = self.hover == key and not maxed
            c = QtGui.QColor.fromHsv(int(it["hue"]) % 360, 170, 235)
            p.setPen(QtGui.QPen(YELLOW_D if hov else col(c, 220), 3 if hov else 1.6)); p.setBrush(col(WHITE, 245))
            p.drawRoundedRect(r, 12, 12)
            rad = 24.0
            self.badge(p, QPointF(r.left() + 16 + rad, r.top() + 14 + rad), rad, it["tag"], c)
            tx = r.left() + 28 + rad * 2
            text(p, QRectF(tx, r.top() + 12, r.right() - 12 - tx, 22), it["name"], 14, NAVY, W_BLACK, True,
                 AF.AlignLeft | AF.AlignVCenter, elide=True)
            lab = (f"Owned {it['level']}/{it['max']}" + ("  \u00b7  packed" if it.get("equipped") else "")) \
                if it["tab"] == "supplies" else f"Rank {it['level']}/{it['max']}"
            text(p, QRectF(tx, r.top() + 36, r.right() - 12 - tx, 16), lab, 10, BLUE_D, W_BLACK, False, AF.AlignLeft | AF.AlignVCenter)
            wrapped(p, QRectF(r.left() + 16, r.top() + 72, r.width() - 32, max(16.0, r.height() - 72 - 52)), it["desc"], 11,
                    col(NAVY, 230))
            br = QRectF(r.left() + 12, r.bottom() - 44, r.width() - 24, 32)
            p.setPen(NOPEN)
            p.setBrush(col(GREY, 110) if maxed else (YELLOW if hov else (col(YELLOW_D, 230) if afford else col(GREY, 90))))
            p.drawPolygon(para(br, 8))
            cur = "PYROXENE" if it["cur"] == "pyrox" else "CREDITS"
            text(p, br, "MAX" if maxed else f"{it['price']:,}  {cur}", 13, NAVY_D if (afford or maxed) else col(NAVY, 150),
                 W_BLACK, True, AF.AlignCenter, 1.0)
            if not maxed: self.hits.append((r, key))
        self.button(p, QRectF(F.right() - 28 - 240, F.center().y() - 22, 240, 44), "Back to Campaign", ("hub",), px=15, icon="back")
        self.footer_text(p, QRectF(F.left() + 24, F.top() + 6, F.width() - 320, F.height() - 12),
                         "Everything bought here is saved at once (campaign_save.json).")

    # ------------------------------------------------------------------ input
    def on_click(self, key, right=False):
        k = key[0]
        camp, save, run = self.camp, self.save, self.camp.run
        if self.mode == "counter" and k != "close":
            if k in ("back", "hub", "title"): camp.to_hub()
            elif k == "tab": self.counter_tab = key[1]
            elif k == "buy":
                ok, msg = save.buy(key[1])
                self.flash(("Purchased: " if ok else "") + msg, ok)
            return
        if k in ("back", "close", "title"):
            self.close_animated()
            if self.mode == "result": camp.to_hub()
            self.mgr.show_title()
        elif k == "shop":
            self.open_shop()
        elif self.mode == "hub":
            if k == "slot":
                sq = self.squad()
                if key[1] < len(sq):
                    if right:
                        sq.pop(key[1]); self.set_squad(sq)
                    else:
                        self.set_squad(sq, sq[key[1]])
            elif k == "card": self.toggle_member(key[1], make_leader=right)
            elif k == "supply": save.cycle_slot(key[1], back=right)
            elif k == "manual":
                save.d["manual"] = not bool(save.d.get("manual", True)); save.save()
            elif k == "heat":
                save.d["heat"] = int(clamp(int(save.d.get("heat", 0)) + key[1], 0, int(save.d.get("heat_unlocked", 0))))
                save.save()
            elif k == "sortie": camp.start_run()
        elif self.mode == "doors":
            if k == "door": camp.enter_door(key[1])
            elif k == "abandon":
                now = time.perf_counter()
                if now - self.confirm_t < 3.0: camp.abandon()
                else: self.confirm_t = now
        elif self.mode == "reward":
            if k == "pick" and run is not None:
                if run.take_boon(key[1]): camp.leave_room()
            elif k == "reroll" and run is not None:
                if run.reroll(): self.t_mode = time.perf_counter() - 0.15
            elif k == "continue": camp.leave_room()
        elif self.mode == "stall":
            if k == "stall" and run is not None:
                ok, msg = run.stall_buy(key[1])
                if msg: self.flash(msg, ok)
            elif k == "continue": camp.leave_room()
        elif self.mode == "cafe":
            if k == "continue": camp.leave_room()
        elif self.mode == "result":
            if k == "hub": camp.to_hub()


# ============================================================================== pause menu
class CampaignPause(BAWindow):
    def __init__(self, camp):
        super().__init__(camp.mgr, 560, 470, "Campaign - Paused", tool=True)
        self.camp = camp
        self.confirm_t = 0.0

    def on_open(self):
        self.confirm_t = 0.0

    def on_escape(self):
        self.mgr.resume()

    def paint_content(self, p, R, now):
        self.header(p, R, "Paused", "\u4f5c\u6226\u4e2d\u65ad  \u00b7  CAMPAIGN ON HOLD", back=False)
        run = self.camp.run
        y = R.top() + 86
        if run is not None:
            a = area_of(run.room)
            r = QRectF(R.left() + 30, y, R.width() - 60, 30)
            p.setPen(NOPEN); p.setBrush(col(qc(AREAS[a]["color"]), 60)); p.drawPolygon(para(r, 8))
            text(p, r.adjusted(18, 0, -14, 0), f"Area {a + 1}  \u00b7  {AREAS[a]['name']}  \u00b7  room {run.room % ROOMS_PER_AREA + 1}/{ROOMS_PER_AREA}",
                 13, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter)
            text(p, QRectF(R.left() + 30, y + 34, R.width() - 60, 20),
                 f"{len(run.boons)} supports  \u00b7  +{run.credits:,} Credits  \u00b7  +{run.pyrox} Pyroxene so far", 11, GREY, W_BOLD,
                 False, AF.AlignCenter)
        y += 70
        bw, bh = R.width() - 120, 54
        x = R.left() + 60
        self.big_button(p, QRectF(x, y, bw, bh), "RESUME", "\u4f5c\u6226\u518d\u958b  \u00b7  back to the fight", ("resume",), now)
        y += bh + 20
        sure = now - self.confirm_t < 3.0
        self.button(p, QRectF(x + 10, y, bw - 20, 46), "Click again: the run ends here" if sure else "Abandon Run", ("abandon",),
                    accent=RED if sure else ORANGE, px=15, icon="close")
        y += 58
        self.button(p, QRectF(x + 10, y, bw - 20, 46), "Title Screen  (abandons the run)", ("title",), accent=ORANGE, px=14,
                    icon="home")
        text(p, QRectF(R.left() + 20, R.bottom() - 34, R.width() - 40, 20), "What you already earned stays in your wallet.", 11,
             col(GREY, 230), W_BOLD, True)

    def on_click(self, key, right=False):
        k = key[0]
        if k in ("resume", "close"): self.mgr.resume()
        elif k == "abandon":
            now = time.perf_counter()
            if now - self.confirm_t < 3.0:
                self.hide(); self.camp.abandon()
            else:
                self.confirm_t = now
        elif k == "title":
            self.hide(); self.camp.to_title()
