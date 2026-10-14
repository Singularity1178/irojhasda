"""App mixin: the wind gust."""
from __future__ import annotations

import math
import time

from PySide6 import QtGui

from .config import GUST_DUR, GUST_RADIUS, GUST_SPEED


class AppEffects:
    def spawn_gust(self, pos=None):
        """Burst wind out of the cursor: double-middle-click with Blow mode on,
        or the Interact-tab button. Hits every visible pet in radius."""
        try: c = QtGui.QCursor.pos() if pos is None else pos
        except Exception: return
        self.gusts.append(dict(x=float(c.x()), y=float(c.y()), t0=time.time()))
        self.gusts = self.gusts[-6:]                       # never stockpile
        for p in self.pets:
            if p.isVisible():
                p.emit_wind(c.x(), c.y(), float(self.cfg.get("blow_strength", 1.0)))

    def gust_wind_at(self, x, y):
        """Radial wind (px/s) + 0..1 energy at screen point (x, y). Summed over
        active gusts: fast attack, exponential decay, smooth distance falloff."""
        if not self.gusts: return 0.0, 0.0, 0.0
        now = time.time()
        strength = float(self.cfg.get("blow_strength", 1.0))
        self.gusts = [g for g in self.gusts if now - g["t0"] < GUST_DUR + 0.4]
        wx = wy = e = 0.0
        for g in self.gusts:
            age = now - g["t0"]
            if age < 0 or age > GUST_DUR: continue
            dx, dy = x - g["x"], y - g["y"]
            d = math.hypot(dx, dy)
            if d > GUST_RADIUS: continue
            if d < 8.0: dx, dy, d = 0.0, -8.0, 8.0       # dead centre -> push up
            env = min(1.0, age / 0.08) * math.exp(-2.5 * age)
            fall = (1.0 - d / GUST_RADIUS) ** 1.5
            m = GUST_SPEED * strength * env * fall
            wx += dx / d * m; wy += dy / d * m
            e = max(e, min(1.0, m / 900.0))
        return wx, wy, e
