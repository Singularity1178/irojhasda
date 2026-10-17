"""Pet mixin: taking cover - kneeling behind another student (Kneel_* clips), or standing behind a
desktop window about her height (Stand_* clips)."""
from __future__ import annotations

import random

from .combat_config import (
    COVER_DRIFT, COVER_GAP, COVER_HOLD, COVER_MIN_BEHIND, COVER_SEEK, COVER_WIN_GAP,
    COVER_WIN_GROUND_GAP, COVER_WIN_MIN_H, COVER_WIN_MIN_W, EXPOSURE_SHOTS, MOVE_MAX_TIME,
    SHOOT_LINES, SHOOT_STANCE_WEIGHT
)
from .combat_data import attack_sets, move_sets
from .mathutil import clamp


def seg_rect_t(x0, y0, x1, y1, rect):
    """Entry fraction t (0..1) where the segment (x0,y0)->(x1,y1) first enters rect (l, t, r, b), or
    None if it never does - or if it STARTS inside it (a shooter standing in front of the window)."""
    l, t, r, b = rect
    if l <= x0 <= r and t <= y0 <= b: return None
    dx, dy = x1 - x0, y1 - y0
    tmin, tmax = 0.0, 1.0
    for o, d, lo, hi in ((x0, dx, l, r), (y0, dy, t, b)):
        if abs(d) < 1e-6:
            if o < lo or o > hi: return None
        else:
            ta, tb = (lo - o) / d, (hi - o) / d
            if ta > tb: ta, tb = tb, ta
            tmin, tmax = max(tmin, ta), min(tmax, tb)
            if tmin > tmax: return None
    return tmin


class PetCover:
    # ---------------- taking cover behind another student (Kneel_* clips) ----------------
    def shield_spot(self, sh, q):
        """x she kneels at: just behind the shield, on the side away from the opponent q."""
        sx = sh.feet_pos()[0]; tx = q.feet_pos()[0]
        away = 1 if sx >= tx else -1
        lo, hi = self.move_span()
        return clamp(sx + away * COVER_GAP * self.char_h(), lo, hi)

    def shield_ok(self, sh, q, others=()):
        """Can sh serve as her shield against q (her target) right now? She must be a standing student on
        the same floor / window top, on HER side of q (so reaching her never means running past the
        opponent), not hostile, not on the move, and there has to be room to kneel behind her."""
        if sh is None or sh is self or sh is q or sh in others: return False
        if not self.shoot_target_ok(sh) or not sh.grounded or sh.support != self.support: return False
        if sh.state == "flee" or sh.is_running(): return False
        if sh in self.threats(loose=True): return False
        fx, _ = self.feet_pos(); sx = sh.feet_pos()[0]; tx = q.feet_pos()[0]
        if (sx - tx) * (fx - tx) <= 0.0: return False             # the shield is on the opponent's far side
        away = 1 if sx >= tx else -1
        if (self.shield_spot(sh, q) - sx) * away < COVER_MIN_BEHIND * self.char_h(): return False   # wall in the way
        return True

    def pick_shield(self, q, others=()):
        """The nearest student who can be her shield against q, or None."""
        fx, _ = self.feet_pos(); reach = COVER_SEEK * self.char_h()
        best, best_d = None, reach
        for s_ in self.A.pets:
            if not self.shield_ok(s_, q, others): continue
            d = abs(s_.feet_pos()[0] - fx)
            if d <= best_d: best, best_d = s_, d
        return best

    # ---------------- taking cover behind a window (Stand_* clips) ----------------
    def cover_windows(self):
        """[(hwnd, (l, t, r, b))] of every still-visible desktop window (WinTracker), [] off Windows."""
        trk = getattr(self.A, "tracker", None)
        if trk is None or not getattr(trk, "enabled", False): return []
        return [(w[0], tuple(w[1:])) for w in (trk.wins or [])]

    def win_rect(self, h):
        trk = getattr(self.A, "tracker", None)
        return trk.rect(h) if trk is not None and h is not None else None

    def win_spot(self, rect, q):
        """(x she stands at, away side) behind window rect against opponent q: just past the window's
        edge on the side away from q. Not clamped, so the caller can spot a wall-clamped fake."""
        l, _t, r, _b = rect
        tx = q.feet_pos()[0]
        away = 1 if (l + r) * 0.5 <= self.feet_pos()[0] else -1
        if tx > r: away = -1                                       # the opponent fixes which side is "behind"
        elif tx < l: away = 1
        gap = COVER_WIN_GAP * self.char_h()
        return (r + gap if away > 0 else l - gap), away

    def window_ok(self, h, q, others=()):
        """Can window h be her cover against q right now? It must be visible, not the window she stands
        on, rise from her ground (bottom close to it), stand at least slightly taller than she is above
        that ground, stand between her spot and q, and her spot must be reachable on her floor / window
        top on her side of q. Any height above her counts: she stands BESIDE the window, not behind it,
        so a window towering over her still reads as a wall she is hugging."""
        if h is None or q is None or not self.grounded or h == self.support: return False
        rect = self.win_rect(h)
        if rect is None: return False
        l, t, r, b = rect
        ch = self.char_h(); bh = self.rag_h() if hasattr(self, "rag_h") else ch
        fx, fy = self.feet_pos(); tx, _ = q.feet_pos()
        if r - l < COVER_WIN_MIN_W * ch: return False
        if fy - b > COVER_WIN_GROUND_GAP * ch: return False        # its bottom floats above her ground
        rise = fy - t                                              # how much of it stands above her ground
        if rise < COVER_WIN_MIN_H * bh: return False                # only a sliver below her: not a wall
        if getattr(q, "support", None) == h: return False          # the opponent is standing ON it
        if l - 2.0 <= tx <= r + 2.0: return False                  # the opponent is in front of / behind it
        spot, away = self.win_spot(rect, q)
        if (spot - tx) * away <= 0.0 or (fx - tx) * away <= 0.0: return False   # spot / she on q's far side
        lo, hi = self.move_span()
        if not (lo <= spot <= hi): return False                    # no room past the window (wall / edge)
        if self.support is not None:
            trk = self.A.tracker
            if hasattr(trk, "surface_visible") and not trk.surface_visible(self.support, spot): return False
            if (fx - (l + r) * 0.5) * away < 0.0: return False     # on a window top she cannot walk through it
        if abs(spot - fx) > COVER_SEEK * ch: return False
        return True

    def pick_window(self, q, others=()):
        """(hwnd, distance) of the nearest window that can be her cover against q, or (None, inf)."""
        fx, _ = self.feet_pos()
        best, best_d = None, float("inf")
        for h, rect in self.cover_windows():
            if not self.window_ok(h, q, others): continue
            d = abs(self.win_spot(rect, q)[0] - fx)
            if d < best_d: best, best_d = h, d
        return best, best_d

    def cover_window_rect(self):
        """The rect of the window she is settled behind right now, else None (read by shooters' shoot_fire)."""
        if not self.in_cover(): return None
        cv = self.atk.get("cover")
        return self.win_rect(cv.get("win")) if cv is not None else None

    # ---------------- shared ----------------
    def pick_cover(self, q, others=(), kneel_ok=True, stand_ok=True):
        """("shield", student) / ("win", hwnd) for the nearest usable cover against q, or (None, None)."""
        fx, _ = self.feet_pos()
        opts = []
        if kneel_ok:
            sh = self.pick_shield(q, others)
            if sh is not None: opts.append((abs(self.shield_spot(sh, q) - fx), "shield", sh))
        if stand_ok:
            h, d = self.pick_window(q, others)
            if h is not None: opts.append((d, "win", h))
        if not opts: return None, None
        _d, kind, obj = min(opts, key=lambda o: o[0])
        return kind, obj

    def cover_stances(self):
        """(kneel clips or None, stand clips or None) she could take cover with."""
        sets = attack_sets(self.model)
        kc, sc = sets.get("kneel"), sets.get("stand")
        return (kc if kc is not None and "ing" in kc else None), (sc if sc is not None and "ing" in sc else None)

    def begin_cover(self, a):
        """A fight is starting (a is her fresh atk dict). She may take cover:
          * behind a student (Kneel_Attack_* clips, panel 'Take cover behind a student'), or
          * behind a window about her height on her ground (Stand_Attack_* clips, panel 'Take cover
            behind a window').
        Each kind rolls its own panel chance; of the kinds that passed she runs to the nearest cover.
        True if she did (the run is already playing), False for an ordinary fight."""
        kc, sc = self.cover_stances()
        kneel_ok = kc is not None and random.random() < float(self.cfg.get("shoot_cover_chance", 0.55))
        stand_ok = sc is not None and random.random() < float(self.cfg.get("shoot_window_cover_chance", 0.55))
        if not (kneel_ok or stand_ok): return False
        kind, obj = self.pick_cover(a["target"], (), kneel_ok, stand_ok)
        if kind == "shield": self.start_cover_run(a, obj, announce=True); return True
        if kind == "win": self.start_wincover_run(a, obj, announce=True); return True
        return False

    def start_cover_run(self, a, sh, announce=False):
        kc, _sc = self.cover_stances()
        if kc is not None: a["stance"], a["clips"] = "kneel", kc
        q = a["target"]; fx, _ = self.feet_pos(); goal = self.shield_spot(sh, q)
        side = 1 if q.feet_pos()[0] >= fx else -1
        a["cover"] = dict(shield=sh, win=None, settled=False, t=0.0, hold=random.uniform(*COVER_HOLD))
        sb = a.setdefault("shielded_by", [])
        if sh not in sb: sb.append(sh)                            # her bullets keep passing her old shields too (shoot_fire)
        a["mv"] = dict(kind="shield", goal=goal, side=side, t=MOVE_MAX_TIME["shield"])
        a["run_dir"] = 1 if goal > fx else -1
        a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
        self.atk_phase("run")
        if announce and self.bubble is None: self.say_combat(random.choice(SHOOT_LINES["shield"]), 1.8)

    def start_wincover_run(self, a, h, announce=False):
        """Run to the spot behind window h and fight from the Stand_* clips there."""
        _kc, sc = self.cover_stances()
        if sc is not None: a["stance"], a["clips"] = "stand", sc
        q = a["target"]; fx, _ = self.feet_pos()
        rect = self.win_rect(h)
        goal = self.win_spot(rect, q)[0] if rect is not None else fx
        lo, hi = self.move_span(); goal = clamp(goal, lo, hi)
        side = 1 if q.feet_pos()[0] >= fx else -1
        a["cover"] = dict(shield=None, win=h, settled=False, t=0.0, hold=random.uniform(*COVER_HOLD))
        a["mv"] = dict(kind="wincover", goal=goal, side=side, t=MOVE_MAX_TIME["wincover"])
        a["run_dir"] = 1 if goal > fx else -1
        a["planted"] = 0; a["plant_limit"] = random.randint(*EXPOSURE_SHOTS)
        self.atk_phase("run")
        if announce and self.bubble is None: self.say_combat(random.choice(SHOOT_LINES["wincover"]), 1.8)

    def start_cover(self, a, kind, obj):
        if kind == "shield": self.start_cover_run(a, obj)
        elif kind == "win": self.start_wincover_run(a, obj)

    def cover_valid(self, a):
        """Is her current cover (student or window) still good against her target?"""
        cv = a.get("cover")
        if cv is None: return False
        if cv.get("win") is not None: return self.window_ok(cv["win"], a["target"], a.get("others", ()))
        return self.shield_ok(cv.get("shield"), a["target"], a.get("others", ()))

    def cover_spot(self, a):
        """x of her spot behind her current cover."""
        cv = a["cover"]; q = a["target"]
        if cv.get("win") is not None:
            r = self.win_rect(cv["win"])
            if r is None: return self.feet_pos()[0]
            lo, hi = self.move_span()
            return clamp(self.win_spot(r, q)[0], lo, hi)
        return self.shield_spot(cv["shield"], q)

    def cover_settle(self, a):
        """She is behind her cover: Move_End_Kneel (student) / Move_End_Stand (window) if the model has
        it, else straight to the aim clip."""
        cv = a["cover"]
        if not cv["settled"]: cv["settled"] = True; cv["t"] = 0.0   # (a follow-up run keeps its timer)
        key, phase = ("stand_stop", "stand_in") if cv.get("win") is not None else ("kneel_stop", "kneel_in")
        if move_sets(self.model).get(key) is not None: self.atk_phase(phase)
        elif "start" in a["clips"]: self.atk_phase("start")
        else: self.combat_next(allow_move=False)

    def in_cover(self):
        """True while she is settled behind a student / window that is still valid cover (read by
        aim_accuracy of whoever is shooting at her)."""
        a = self.atk
        if self.state != "shoot" or not a: return False
        cv = a.get("cover")
        if cv is None or not cv["settled"] or a["phase"] in ("run", "end"): return False
        return self.cover_valid(a)

    def in_window_cover(self):
        """True while she is settled behind a window (aim_accuracy uses its own multiplier for it)."""
        a = self.atk
        return bool(a) and a.get("cover") is not None and a["cover"].get("win") is not None and self.in_cover()

    def leave_cover(self, a):
        """Stop using the cover. She steps out: back to a random standing attack stance (never kneel)."""
        a["cover"] = None
        sets = attack_sets(self.model)
        names = [n for n in sets if n != "kneel"]
        if names:
            stance = random.choices(names, [SHOOT_STANCE_WEIGHT.get(n, 1.0) for n in names])[0]
            a["stance"], a["clips"] = stance, sets[stance]

    def cover_upkeep(self, a):
        """Between shots, while she has cover. Returns True if she starts moving (follows the cover or
        goes to a new one). Gives the cover up when its time is up or it is no good any more."""
        cv = a["cover"]; ch = self.char_h()
        if cv["settled"] and cv["t"] > cv["hold"]:                # long enough here: step out and fight
            self.leave_cover(a); return False
        if not self.cover_valid(a):                               # shield down / window closed, moved, covered
            kc, sc = self.cover_stances()
            kind, obj = self.pick_cover(a["target"], a.get("others", ()), kc is not None, sc is not None)
            if kind is not None:
                self.start_cover(a, kind, obj); return True
            a["cover"] = None; return False                       # nothing else: she fights from here
        fx, _ = self.feet_pos()
        if abs(self.cover_spot(a) - fx) > COVER_DRIFT * ch:       # the cover wandered off / was dragged: follow it
            if cv.get("win") is not None: self.start_wincover_run(a, cv["win"])
            else: self.start_cover_run(a, cv["shield"])
            a["cover"].update(settled=cv["settled"], t=cv["t"], hold=cv["hold"])   # same cover: keep the timer
            return True
        return False
