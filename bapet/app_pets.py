"""App mixin: selecting pets, stacking order, pet-to-pet helpers."""
from __future__ import annotations


from .config import BASE_W


class AppPets:
    # ---- character selection ----
    def set_active(self, pet):
        if pet is not self.active:
            self.active = pet
            if getattr(self.panel, "sel_box", None):
                i = self.pets.index(pet) if pet in self.pets else -1
                self.panel.sel_box.blockSignals(True); self.panel.sel_box.setCurrentIndex(i); self.panel.sel_box.blockSignals(False)

    def set_active_by_index(self, i):
        if 0 <= i < len(self.pets): self.set_active(self.pets[i])

    def set_target(self, i):
        self.target = i

    def each(self, fn):
        for p in self.targets(): fn(p)

    def targets(self):
        if 0 <= self.target < len(self.pets): return [self.pets[self.target]]
        return list(self.pets)

    # ---- bubble z-order ----
    def touch_zorder(self, pet):
        """Record that `pet` just started talking: newest line goes on top."""
        try:
            self.z_order.remove(pet)
        except Exception:
            pass
        self.z_order.append(pet)

    def shield_pairs(self):
        """(user, shield) for every student currently hiding behind another one (window cover has no
        shield student, so it never reorders anybody)."""
        out = []
        for p in self.pets:
            if not p.isVisible(): continue
            at = getattr(p, "atk", None)
            cv = at.get("cover") if at else None
            if cv is None: continue
            sh = cv.get("shield")
            if sh is not None and sh is not p and sh.isVisible(): out.append((p, sh))
        return out

    def stack_order(self):
        """Back-to-front list of visible pets.

        The base order is fixed (the order the characters were loaded in) and is never
        changed by the cursor, clicks, dragging or speech. The one thing that overrides
        it: a student using another as a shield is always BEHIND that shield.
        """
        for p in self.pets:
            if p not in self.z_base: self.z_base.append(p)
        order = [p for p in self.z_base if p.isVisible()]
        pairs = self.shield_pairs()
        for _ in range(len(order) + 1):                      # settles in a few passes
            moved = False
            for user, sh in pairs:
                if user in order and sh in order and order.index(sh) < order.index(user):
                    order.remove(user)
                    order.insert(order.index(sh), user)       # directly behind her shield
                    moved = True
            if not moved: break
        return order

    def restack(self, force=False):
        """Apply stack_order to the real windows (back to front, so the last is on top).
        Only touches the windows when the order changed, or when force is set (after a
        click, when the OS may have lifted the clicked window)."""
        order = self.stack_order()
        sig = tuple(id(p) for p in order)
        if not force and sig == self.z_sig: return
        self.z_sig = sig
        for p in order:
            try: p.raise_()
            except Exception: pass

    def sort_bubble_zorder(self):
        """Kept under its old name: re-applies the fixed stacking order a couple of times a
        second, because window managers reshuffle top-level windows (a new window, a menu,
        alt-tab)."""
        self.restack(force=True)

    # ---- pet-to-pet ----
    def peers_of(self, p, max_dist=None, same_surface=False):
        """Other visible characters near `p`, nearest first.

        max_dist      horizontal reach in px (default ~1.6 character widths)
        same_surface  only characters perched on the same window as `p`
        """
        if max_dist is None: max_dist = BASE_W * 1.6 * self.cfg["scale"]
        fx, fy = p.feet_pos(); out = []
        for q in self.pets:
            if q is p or not q.isVisible(): continue
            qx, qy = q.feet_pos()
            d = abs(qx - fx)
            if d > max_dist: continue
            if same_surface and (q.support is not p.support or q.support is None): continue
            if abs(qy - fy) > p.H * 0.6: continue          # not on the same level
            home = getattr(self, "home", None)
            if home is not None:      # single-screen build: never pair up across monitors
                if qx + q.W * 0.5 < home.left() or qx - q.W * 0.5 > home.right(): continue
            out.append((d + abs(qy - fy) * 0.5, q))
        out.sort(key=lambda t: t[0])
        return [q for _k, q in out]

    def start_chat(self, a=None, b=None):
        """Kick off a conversation, either between two given pets or a free pair."""
        return self.chats.start(a, b)

    def introduce_all(self):
        """Round-robin greeting: everyone says hi to the next one."""
        return self.chats.introduce_all()

    def end_all_chats(self):
        return self.chats.end_all()
