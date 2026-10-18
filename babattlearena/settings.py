"""Battle Arena settings: the values, where they are saved, and the settings screen.

Saved to battle_arena_settings.json next to the main script (separate from the desktop pets'
settings file, which only keeps keys it knows). Unknown / broken values fall back to defaults.
"""
from __future__ import annotations

import json
import traceback

from PySide6.QtCore import QRectF

from bapet.config import HERE
from .theme import (AF, BLUE, BLUE_D, GREY, NAVY, NOPEN, ORANGE, WHITE, BAWindow, W_BLACK, W_BOLD, col, para,
                    text)

SETTINGS_PATH = HERE / "battle_arena_settings.json"

DEFAULTS = dict(
    lives=3,                  # lives per student; one is lost every time she is ragdolled
    invuln=2.0,               # s of invulnerability after getting back up
    down_time=2.5,            # s she lies there before getting up (if she has lives left)
    time_limit=0,             # s, 0 = until one team is wiped out
    layout="left_right",      # spawn layout
    speed=1.0,                # game speed
    damage=1.0,               # damage multiplier
    hp=1.0,                   # HP multiplier
    friendly_fire=False,      # allies still block bullets (body cover) - this decides if it hurts them
    ex_skills=True,           # EX skills (grenades, shields, mass heals, barrages ...)
    difficulty="veteran",     # rookie / veteran / elite: reaction time, accuracy, tactical depth
    obstacles=True,           # spawn cover at the start
    obstacle_amount="normal", # few / normal / many
    barrels=True,             # explosive barrels among the obstacles
    windows_cover=True,       # real desktop windows are walls (move them mid-fight!)
    size=120,                 # student height on screen, px
    hp_bars=True,
    damage_numbers=True,
    team_panels=True,
    fps=30,
)

CHOICES = {
    "time_limit": [(0, "None"), (120, "2 min"), (180, "3 min"), (300, "5 min"), (600, "10 min")],
    "layout": [("left_right", "Left vs Right"), ("top_bottom", "Top vs Bottom"), ("corners", "Corners"),
               ("scattered", "Scattered")],
    "difficulty": [("rookie", "Rookie"), ("veteran", "Veteran"), ("elite", "Elite")],
    "obstacle_amount": [("few", "Few"), ("normal", "Normal"), ("many", "Many")],
    "fps": [(20, "20 fps"), (30, "30 fps"), (45, "45 fps"), (60, "60 fps")],
}

# (section, [(key, label, kind, extra)])   kind: int (lo, hi, step) / float (lo, hi, step) / bool / choice
SPEC = [
    ("MATCH", "\u5bfe\u6226\u30eb\u30fc\u30eb", [
        ("lives", "Lives per student", "int", (1, 9, 1)),
        ("time_limit", "Time limit", "choice", None),
        ("layout", "Spawn layout", "choice", None),
        ("speed", "Game speed", "float", (0.25, 2.0, 0.25)),
        ("difficulty", "AI tactics", "choice", None),
    ]),
    ("COMBAT", "\u6226\u95d8", [
        ("damage", "Damage", "float", (0.25, 3.0, 0.25)),
        ("hp", "Student HP", "float", (0.5, 3.0, 0.25)),
        ("down_time", "Down time before getting up", "float", (1.0, 8.0, 0.5)),
        ("invuln", "Invulnerability after get-up", "float", (0.0, 6.0, 0.5)),
        ("friendly_fire", "Friendly fire", "bool", None),
        ("ex_skills", "EX skills", "bool", None),
    ]),
    ("BATTLEFIELD", "\u6226\u5834", [
        ("obstacles", "Spawn obstacles / cover", "bool", None),
        ("obstacle_amount", "Obstacle amount", "choice", None),
        ("barrels", "Explosive barrels", "bool", None),
        ("windows_cover", "Desktop windows are cover", "bool", None),
        ("size", "Student size (px)", "int", (70, 220, 10)),
    ]),
    ("DISPLAY", "\u8868\u793a", [
        ("hp_bars", "HP bars & lives over heads", "bool", None),
        ("team_panels", "Team panels at the sides", "bool", None),
        ("damage_numbers", "Damage numbers", "bool", None),
        ("fps", "Frame rate", "choice", None),
    ]),
]


class ArenaSettings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.load()

    def load(self):
        try:
            if SETTINGS_PATH.exists():
                raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if k in DEFAULTS and type(v) in (type(DEFAULTS[k]), int, float, bool, str):
                        self[k] = v
        except Exception:
            traceback.print_exc()
        self.sanitize()

    def sanitize(self):
        for k, v in DEFAULTS.items():
            cur = self.get(k)
            if isinstance(v, bool):
                self[k] = bool(cur)
            elif isinstance(v, (int, float)) and not isinstance(cur, (int, float)):
                self[k] = v
            elif isinstance(v, str) and not isinstance(cur, str):
                self[k] = v
        for k, opts in CHOICES.items():
            if self[k] not in [o[0] for o in opts]:
                self[k] = DEFAULTS[k]

    def save(self):
        try:
            SETTINGS_PATH.write_text(json.dumps(dict(self), indent=2), encoding="utf-8")
        except Exception:
            traceback.print_exc()

    def label(self, key):
        v = self[key]
        if key in CHOICES:
            return dict(CHOICES[key]).get(v, str(v))
        if isinstance(v, bool):
            return "ON" if v else "OFF"
        if isinstance(v, float):
            if key in ("down_time", "invuln"): return f"{v:.1f} s"
            return f"x{v:.2f}".rstrip("0").rstrip(".")
        return str(v)

    def summary(self):
        parts = [f"Lives {self['lives']}", self.label("time_limit") if self["time_limit"] else "No time limit",
                 f"Obstacles {self.label('obstacle_amount') if self['obstacles'] else 'OFF'}",
                 f"Windows {'ON' if self['windows_cover'] else 'OFF'}", f"AI {self.label('difficulty')}"]
        if self["speed"] != 1.0: parts.append(f"Speed x{self['speed']:g}")
        return "  \u00b7  ".join(parts)

    def step(self, key, kind, extra, d):
        if kind == "bool":
            self[key] = not self[key]
        elif kind == "choice":
            opts = [o[0] for o in CHOICES[key]]
            i = opts.index(self[key]) if self[key] in opts else 0
            self[key] = opts[(i + d) % len(opts)]
        else:
            lo, hi, st = extra
            v = self[key] + st * d
            v = max(lo, min(hi, v))
            self[key] = int(round(v)) if kind == "int" else round(v, 3)


class SettingsWindow(BAWindow):
    """Arena rules. Opened from the lobby; changes save at once."""

    def __init__(self, mgr):
        super().__init__(mgr, 1040, 640, "Battle Arena Settings", tool=True)
        self.st = mgr.settings

    def on_escape(self):
        self.st.save()
        self.close_animated()
        lob = getattr(self.mgr, "_lobby", None)
        if lob is not None and lob.isVisible(): lob.raise_()

    def on_click(self, key, right=False):
        k = key[0]
        if k in ("close", "back", "done"):
            self.on_escape(); return
        if k == "reset":
            self.st.clear(); self.st.update(DEFAULTS); self.st.save(); return
        if k == "set":
            _k, name, kind, extra, d = key
            self.st.step(name, kind, extra, d * (-1 if right else 1))
            self.st.save()

    def paint_content(self, p, R, now):
        T, _xr = self.header(p, R, "Settings", "BATTLE ARENA  \u00b7  \u8a2d\u5b9a  \u00b7  RULES OF ENGAGEMENT",
                             back=True)
        body = QRectF(R.left() + 24, T.bottom() + 16, R.width() - 48, R.height() - T.height() - 96)
        colw = (body.width() - 24) / 2
        cols = [SPEC[:2], SPEC[2:]]
        for ci, secs in enumerate(cols):
            x = body.left() + ci * (colw + 24)
            y = body.top()
            for title, jp, rows in secs:
                hr = QRectF(x, y, colw, 30)
                p.setPen(NOPEN); p.setBrush(NAVY); p.drawPolygon(para(QRectF(x, y + 4, 8, 22), 3))
                text(p, QRectF(x + 16, y, colw, 30), title, 15, NAVY, W_BLACK, True, AF.AlignLeft | AF.AlignVCenter, 1.6)
                text(p, QRectF(x + 16, y, colw - 16, 30), jp, 11, col(BLUE_D, 170), W_BOLD, False,
                     AF.AlignRight | AF.AlignVCenter, 1.0)
                y = hr.bottom() + 4
                for key, label, kind, extra in rows:
                    rr = QRectF(x, y, colw, 38)
                    hov = self.hover is not None and len(self.hover) > 1 and self.hover[1] == key
                    p.setPen(QtPen(col(BLUE, 40)))
                    p.setBrush(col(WHITE, 235 if hov else 205)); p.drawRoundedRect(rr, 8, 8)
                    text(p, rr.adjusted(14, 0, -200, 0), label, 13, NAVY, W_BOLD, False,
                         AF.AlignLeft | AF.AlignVCenter, elide=True)
                    inner = rr.adjusted(0, 0, -10, 0)
                    if kind == "bool":
                        self.toggle(p, inner, bool(self.st[key]), ("set", key, kind, extra, 1))
                    else:
                        self._stepper(p, inner, self.st.label(key), key, kind, extra)
                    y = rr.bottom() + 6
                y += 12
        # footer
        F = QRectF(R.left(), R.bottom() - 70, R.width(), 70)
        p.fillRect(F, col(WHITE, 236)); p.fillRect(QRectF(F.left(), F.top(), F.width(), 1.5), col(BLUE, 60))
        text(p, QRectF(F.left() + 26, F.top(), F.width() - 420, F.height()),
             "Click a value to change it  \u00b7  right-click steps back  \u00b7  saved automatically", 12, GREY, W_BOLD,
             False, AF.AlignLeft | AF.AlignVCenter, elide=True)
        cy = F.center().y()
        self.button(p, QRectF(F.right() - 26 - 170, cy - 22, 170, 44), "Done", ("done",), px=16)
        self.button(p, QRectF(F.right() - 26 - 170 - 14 - 170, cy - 22, 170, 44), "Reset to default", ("reset",),
                    accent=ORANGE, px=13)

    def _stepper(self, p, r, value, key, kind, extra):
        w = 170.0
        box = QRectF(r.right() - w, r.center().y() - 14, w, 28)
        p.setPen(QtPen(col(BLUE, 80))); p.setBrush(col(WHITE, 250)); p.drawRoundedRect(box, 14, 14)
        for side in (-1, 1):
            c_x = box.left() + 14 if side < 0 else box.right() - 14
            k = ("set", key, kind, extra, side)
            hov = self.hover == k
            cr = QRectF(c_x - 11, box.center().y() - 11, 22, 22)
            p.setPen(NOPEN); p.setBrush(BLUE if hov else col(QtColor(206, 236, 255), 255)); p.drawEllipse(cr)
            text(p, cr, "\u2039" if side < 0 else "\u203a", 18, WHITE if hov else BLUE_D, W_BLACK, False)
            self.hits.append((cr.adjusted(-3, -3, 3, 3), k))
        mid = box.adjusted(26, 0, -26, 0)
        text(p, mid, str(value), 13, NAVY, W_BLACK, True)
        self.hits.append((mid, ("set", key, kind, extra, 1)))


def QtPen(c, w=1.0):
    from PySide6 import QtGui
    return QtGui.QPen(c, w)


def QtColor(r, g, b):
    from PySide6 import QtGui
    return QtGui.QColor(r, g, b)
