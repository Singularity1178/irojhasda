"""App mixin: the tray icon, the control panel window and the right-click menu.

This file is only the glue. What the menus contain lives in ui_menu.py, what the panel contains
lives in ui_spec.py / panel.py, and how it all looks lives in ui_theme.py.
"""
from __future__ import annotations

from PySide6 import QtWidgets

from .icons import make_icon
from .ui_menu import build_pet_menu, build_tray_menu


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
        self.panel.refresh()
        self.panel.update_status()
        self.panel.show(); self.panel.raise_(); self.panel.activateWindow()

    def show_menu(self, pos, p=None):
        """The right-click menu for one character (built fresh each time, so it is never stale)."""
        p = p or self.active or (self.pets[0] if self.pets else None)
        if p is None: return
        build_pet_menu(self, p).exec(pos)

    def setup_tray(self):
        self.tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.show_panel(); return
        self.tray = QtWidgets.QSystemTrayIcon(make_icon(self.active.name if self.active else "A"), self)
        self.tray.setToolTip("Desktop Pets")
        self.tray_menu = build_tray_menu(self)        # keeps itself up to date every time it opens
        self.tray.setContextMenu(self.tray_menu)
        reasons = QtWidgets.QSystemTrayIcon.ActivationReason
        self.tray.activated.connect(lambda r: self.show_panel() if r in (reasons.DoubleClick, reasons.Trigger) else None)
        self.tray.show()
