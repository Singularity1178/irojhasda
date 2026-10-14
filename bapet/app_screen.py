"""App mixin: the one screen pets live on, visibility, floor and window surfaces."""
from __future__ import annotations

from PySide6 import QtGui

from .mathutil import clamp


class AppScreen:
    def set_screen(self, spec):
        """Move every character onto the chosen screen and keep them there."""
        self.cfg["screen"] = spec
        self.resolve_screen(spec)
        self.end_all_chats()                      # nobody mid-conversation when the screen changes
        g = self.home
        print("Locked to screen:", self.screen_label())
        n = len(self.pets) or 1
        for i, p in enumerate(self.pets):
            frac = 0.9 - i * min(0.75 / n, 0.25)
            p.rag_clear()
            p.support = None; p.grounded = True; p.vx = p.vy = 0
            p.set_feet(self.clamp_x(g.left() + (g.right() - g.left()) * frac, p.W), g.bottom() + 1)
            p.enter("idle")
        self.save_timer.start(600)
        if hasattr(self, "panel"): self.panel.sync_screen_note()

    def set_pet_visible(self, pet, vis):
        """Show/hide one character.

        Only this character's own name is touched - the list is never rebuilt
        from every pet's isVisible(), which used to mark not-yet-spawned pets
        as hidden and cascade into "everything stays hidden" across restarts.
        """
        if vis: pet.show()
        else:
            # hiding her mid-tumble: drop the ragdoll so she comes back as a
            # normal falling pet instead of freezing halfway through a throw
            pet.rag_clear()
            pet.hide()
        names = set(self.cfg.get("hidden") or [])
        if vis: names.discard(pet.name)
        else: names.add(pet.name)
        self.cfg["hidden"] = [p.name for p in self.pets if p.name in names]
        self.save_timer.start(600)
        if getattr(self, "panel", None) and getattr(self.panel, "sync_char_rows", None):
            self.panel.sync_char_rows()

    def set_all_visible(self, vis):
        for p in self.pets: self.set_pet_visible(p, vis)
        if getattr(self.panel, "sync_char_rows", None): self.panel.sync_char_rows()

    def apply_hidden_state(self, hidden):
        """Restore per-character visibility from the saved list (after spawning).

        Two safety nets, both so a bad save can never leave you with a blank screen:
          * stale entries (a character whose .glb is gone) are dropped
          * a list that hides *every* character is the signature of the old
            'Hide to tray' bug, not a real choice, so everybody comes back
        """
        hidden = set(hidden or ())
        known = {p.name for p in self.pets}
        stale = hidden - known
        if known and hidden >= known:
            print("[info] every character was saved as hidden (leftover 'Hide to tray' "
                  "state) - showing them all.")
            hidden = set()
        for p in self.pets:
            p.show() if p.name not in hidden else p.hide()
        self.cfg["hidden"] = sorted(known & hidden)
        if stale:
            print("[info] dropping hidden characters that no longer exist:",
                  ", ".join(sorted(stale)))
        if getattr(self.panel, "sync_char_rows", None): self.panel.sync_char_rows()

    # ---- one screen only: every character is locked to self.home ----
    def resolve_screen(self, spec=None):
        """Pick the single screen the pets live on and cache it as self.home."""
        spec = self.cfg.get("screen", "cursor") if spec is None else spec
        screens = self.qapp.screens()
        home = None
        if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
            i = int(spec)
            if 0 <= i < len(screens): home = screens[i].availableGeometry()
        if home is None and spec == "primary":
            home = self.qapp.primaryScreen().availableGeometry()
        if home is None:                                   # "cursor" and any bad value
            c = QtGui.QCursor.pos()
            scr = self.qapp.screenAt(c) or self.qapp.primaryScreen()
            home = scr.availableGeometry()
        self.home = home
        return home

    def screen_label(self):
        for i, s in enumerate(self.qapp.screens()):
            if s.availableGeometry() == getattr(self, "home", None):
                return f"{i}: {s.name()} ({s.availableGeometry().width()}x{s.availableGeometry().height()})"
        return "-"

    def bounds(self):
        g = self.resolve_screen()
        return g.left(), g.right() + 1

    def top(self): return self.resolve_screen().top()

    def screen_size(self):
        g = self.resolve_screen(); return g.width(), g.height()

    def floor_y(self, fx):
        return self.resolve_screen().bottom() + 1

    def surfaces(self, fx, perch):
        home = self.resolve_screen()
        res = []
        if perch and self.tracker.enabled:
            for top, h in self.tracker.surfaces(fx):
                if top < home.top() - 4 or top > home.bottom() + 4: continue   # other monitors
                if fx < home.left() + 6 or fx > home.right() - 6: continue
                res.append((top, h))
        res.sort(key=lambda s: s[0]); res.append((self.floor_y(fx), None)); return res

    def clamp_x(self, fx, w):
        """Keep a character's feet inside the home screen."""
        g = self.resolve_screen(); m = w * 0.18
        return clamp(fx, g.left() + m, max(g.left() + m, g.right() - m))
