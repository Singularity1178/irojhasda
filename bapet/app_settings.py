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
        elif key == "test_weapon":
            # A WH_MOUSE_LL hook is called on the raw input thread for every mouse move
            # and has to take the GIL to answer, which is visible as cursor lag on a
            # render loop this busy. Fit it only while the gun is actually in use.
            if val: self.setup_mouse_hook()
            else: self.remove_mouse_hook()
        elif key == "ragdoll_3d_iters":
            # Physics iterations: live, even mid-fall (the PBD solver derives velocity
            # from positions, so a new substep size needs no conversion).
            w3 = getattr(self, "rag_world3d", None)
            if w3 is not None:
                self.cfg[key] = w3.set_iterations(val)     # store the clamped integer
        elif key == "ragdoll_window_scale":
            # Live, even mid-fall: whoever is limp right now takes the new size,
            # with her feet left exactly where they are.
            for p in self.pets: p.rag_window(p.ragdoll)
        elif key == "screen":
            # the home screen moved, so the physics walls have to move with it
            self.resolve_screen()
            self.sync_phys_screen()
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
