"""App mixin: tray icon, panel, and the right-click menu."""
from __future__ import annotations

from PySide6 import QtWidgets

from .config import ANIM_KEYS, PRESETS
from .icons import make_icon


class AppUI:
    def toggle_pet(self):
        """Hide / show everything. Deliberately NOT persisted - this is a
        temporary 'get them off my screen' action, not a per-character choice.
        """
        vis = not all(p.isVisible() for p in self.pets)
        for p in self.pets: p.show() if vis else p.hide()
        if getattr(self.panel, "sync_char_rows", None): self.panel.sync_char_rows()

    def stashed(self):
        """True while everything is hidden by toggle_pet (so save() can tell them apart)."""
        return bool(self.pets) and not any(p.isVisible() for p in self.pets)

    def show_panel(self):
        self.panel.refresh(); self.panel.sync_char_rows(); self.panel.show(); self.panel.raise_(); self.panel.activateWindow()

    def show_menu(self, pos, p=None):
        p = p or self.active or (self.pets[0] if self.pets else None)
        if p is None: return
        m = QtWidgets.QMenu()
        m.setTitle(p.name)
        for t, fn in (("Poke", p.poke), ("Pet", p.pet), ("EX Cut-in", p.do_cutin),
                      ("Tactical Start", p.do_tactical), ("Spin (3D)", p.spin), ("Launch!", p.launch),
                      ("Look around", p.look_around),
                      ("Shoot a student", lambda: p.try_shoot(force=True))):
            m.addAction(t, fn)
        if p.ragdoll: m.addAction("Get up", p.rag_getup)
        else:         m.addAction("Ragdoll", lambda: p.start_ragdoll(kick=False))
        a = m.addAction("Ragdoll: auto get-up"); a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("ragdoll_auto_getup", True)))
        a.toggled.connect(lambda v: self.set("ragdoll_auto_getup", v, refresh=True))
        am = m.addMenu("Animations")
        for key, (name, _l) in ANIM_KEYS.items(): am.addAction(name, lambda k=key: p.play_anim(k))
        m.addSeparator()
        pm = m.addMenu("Other characters")
        for q in self.pets:
            if q is p: continue
            sm = pm.addMenu(q.name)
            sm.addAction("Make active", lambda pp=q: self.set_active(pp))
            sm.addAction("Summon", lambda pp=q: self.summon(pp))
            sm.addAction("Poke", lambda pp=q: pp.poke())
            sm.addAction("Reset position", lambda pp=q: pp.reset_position())
            a = sm.addAction(f"Talk with {q.name}"); a.setEnabled(self.cfg["chat"])
            a.triggered.connect(lambda _c=False, pp=p, qq=q: self.start_chat(pp, qq))
            a = sm.addAction("Visible"); a.setCheckable(True); a.setChecked(q.isVisible())
            a.toggled.connect(lambda v, pp=q: self.set_pet_visible(pp, v))
        m.addSeparator()
        for label, key in (("Wander", "wander"), ("Look at cursor", "look_at_cursor"), ("Follow cursor", "follow_cursor"),
                           ("Perch on windows", "perch"), ("Speech bubbles", "speech"), ("Particles", "particles"),
                           ("Always on top", "always_on_top"), ("Light follows cursor", "light_follow")):
            a = m.addAction(label); a.setCheckable(True); a.setChecked(bool(self.cfg[key]))
            a.toggled.connect(lambda v, k=key: self.set(k, v, refresh=True))
        sm = m.addMenu("Size")
        for pct in (50, 75, 100, 125, 150, 200): sm.addAction(f"{pct}%", lambda v=pct: self.set("scale", v / 100, refresh=True))
        pm = m.addMenu("Shader preset")
        for name in PRESETS: pm.addAction(name, lambda n=name: self.apply_preset(n))
        m.addSeparator()
        m.addAction("Control Panel...", self.show_panel); m.addAction("Hide to tray", self.toggle_pet); m.addAction("Quit", self.qapp.quit)
        m.exec(pos)

    def setup_tray(self):
        self.tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.show_panel(); return
        self.tray = QtWidgets.QSystemTrayIcon(make_icon(self.active.name if self.active else "A"), self)
        self.tray.setToolTip("Desktop Pets")
        menu = QtWidgets.QMenu()
        menu.addAction("Show / Hide all", self.toggle_pet); menu.addAction("Control Panel...", self.show_panel)
        menu.addSeparator()
        menu.addAction("Summon target to cursor", self.summon)
        menu.addAction("EX Cut-in (target)", lambda: self.each(lambda p: p.do_cutin()))
        menu.addAction("Poke (target)", lambda: self.each(lambda p: p.poke()))
        cm = menu.addMenu("Characters")
        for p in self.pets:
            sub = cm.addMenu(p.name)
            sub.addAction("Make active", lambda pp=p: self.set_active(pp))
            sub.addAction("Summon", lambda pp=p: self.summon(pp))
            sub.addAction("EX Cut-in", lambda pp=p: pp.do_cutin())
            sub.addAction("Ragdoll", lambda pp=p: pp.start_ragdoll(kick=False))
            a = sub.addAction("Visible"); a.setCheckable(True); a.setChecked(p.isVisible())
            a.toggled.connect(lambda v, pp=p: self.set_pet_visible(pp, v))
        menu.addSeparator()
        menu.addAction("Quit", self.qapp.quit)
        self.tray_menu = menu; self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_panel() if r in (QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
                                                                          QtWidgets.QSystemTrayIcon.ActivationReason.Trigger) else None)
        self.tray.show()
