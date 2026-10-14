"""App mixin: changing, applying and saving settings; summoning."""
from __future__ import annotations

import json

from PySide6 import QtGui

from .config import PRESETS, SETTINGS_PATH


class AppSettings:
    # ---- settings ----
    def set(self, key, val, refresh=False):
        self.cfg[key] = val; self.save_timer.start(600)
        if key == "scale":
            for p in self.pets: p.apply_scale()
        elif key == "always_on_top":
            for p in self.pets: p.apply_flags()
        elif key == "fps": self.timer.setInterval(int(1000 / max(1, val)))
        elif key == "click_through":
            for p in self.pets: p.mask_dirty = True
        elif key == "perch" and not val: self.tracker.wins = []
        elif key == "screen":
            # the home screen moved, so the physics walls have to move with it
            self.resolve_screen()
            if self.rag_world is not None:
                g = self.home
                self.rag_world.set_screen((g.left(), g.top(), g.right() + 1, g.bottom() + 1))
        if refresh and hasattr(self, "panel"): self.panel.refresh()

    def apply_preset(self, name):
        if name in PRESETS:
            self.cfg.update(PRESETS[name]); self.cfg["preset"] = name; self.save_timer.start(600); self.panel.refresh()

    def save(self):
        try:
            pos = {p.name: p.feet_pos()[0] for p in self.pets}
            self.cfg["positions"] = pos
            if not self.stashed():
                # only remember a character as hidden when the rest are still up;
                # a fully-hidden screen is 'Hide to tray' and is not a real choice
                self.cfg["hidden"] = [p.name for p in self.pets if not p.isVisible()]
            if self.pets: self.cfg["pos_x"] = self.pets[0].feet_pos()[0]
            SETTINGS_PATH.write_text(json.dumps(self.cfg, indent=2))
        except Exception: pass

    # ---- ui ----
    def summon(self, pet=None):
        g = self.resolve_screen()
        c = QtGui.QCursor.pos()
        if not (g.left() <= c.x() <= g.right() and g.top() <= c.y() <= g.bottom()):
            c = g.center()                                   # cursor is on another monitor
        for p in (self.targets() if pet is None else [pet]):
            p.rag_clear()
            p.support = None; p.grounded = False; p.dragging = False
            p.chat_abort(); p.meet_target = None
            fx = self.clamp_x(c.x(), p.W)
            p.set_feet(fx, min(c.y() - 40, g.bottom() - p.H * 0.2))
            p.vx = p.vy = 0; p.air_kind = "thrown"
            p.enter("fall"); p.recall()
