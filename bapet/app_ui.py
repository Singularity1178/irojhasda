"""App mixin: the tray icon, the control panel window, the right-click menu and Student Select.

This file is only the glue. What the menus contain lives in ui_menu.py, what the panel contains
lives in ui_spec.py / panel.py, how it all looks lives in ui_theme.py, and the formation screen
lives in picker.py.

Tray icon
    left-click / double-click   Student Select
    middle-click                Control Panel
    right-click                 the right-click menu of the active student (exactly what you get
                                by right-clicking her), with Student Select on top and the old tray
                                menu as a submenu. With nobody on the desktop it is a short menu
                                (Student Select, Deploy everyone, Control Panel, Quit), so the app
                                can always be reached and closed.
"""
from __future__ import annotations

import traceback

from PySide6 import QtCore, QtGui, QtWidgets

from .icons import make_icon
from .picker import StudentPicker
from .ui_menu import StayOpenMenu, build_pet_menu, build_tray_menu
from .ui_theme import GROUP_COLORS, badge_icon

PICKER_TEXT = "Student Select\u2026"
PICKER_COLOR = "#1ea1ff"


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

    # ------------------------------------------------------------------
    #  Student Select (picker.py)
    # ------------------------------------------------------------------
    def picker(self):
        """The formation screen, created on first use (it needs the GL context and every pet)."""
        pk = getattr(self, "_picker", None)
        if pk is None:
            pk = self._picker = StudentPicker(self)
        return pk

    def picker_visible(self):
        pk = getattr(self, "_picker", None)
        return pk is not None and pk.isVisible() and not pk.closing()

    def show_picker(self, team=None, startup=False):
        arena = getattr(self, "arena", None)
        if arena is not None and arena.battle_active():
            arena.pause_menu()               # mid-battle the tray / menus open the pause menu instead
            return
        try:
            self.picker().open(team=team, startup=startup)
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------
    #  Title screen / Battle Arena (babattlearena)
    # ------------------------------------------------------------------
    def show_title(self):
        arena = getattr(self, "arena", None)
        if arena is None:
            self.show_picker(); return
        try:
            arena.show_title()
        except Exception:
            traceback.print_exc()

    def show_arena(self):
        arena = getattr(self, "arena", None)
        if arena is None: return
        try:
            if arena.battle_active(): arena.pause_menu()
            else: arena.open_lobby()
        except Exception:
            traceback.print_exc()

    def start_with_title(self):
        """Startup: hold every student back and open the title screen (Desktop Pets / Battle Arena).

        The students that would have come up are remembered, so picking Desktop Pets opens
        Student Select with last session's team already in the formation."""
        if getattr(self, "arena", None) is None:
            self.start_with_picker(); return
        self._startup_team = [p for p in self.pets if p.isVisible()]
        for p in self.pets:
            try: p.hide()
            except Exception: traceback.print_exc()
        if getattr(self.panel, "sync_char_rows", None): self.panel.sync_char_rows()
        self.show_title()

    def hide_picker(self):
        pk = getattr(self, "_picker", None)
        if pk is not None: pk.close_animated()

    def toggle_picker(self):
        self.hide_picker() if self.picker_visible() else self.show_picker()

    def quit_app(self):
        """Quit, from anywhere - including from a menu, and with Student Select on screen.

        With the formation screen up, quit() on its own never leaves the event loop (it tore
        down the menu that asked for it and then the app carried on, which is why Quit looked
        like it needed pressing twice). So the screen is put away first - that is what unblocks
        it - and the quit is then asked for twice: now, and once more from a zero-timer that
        lands on the main loop, so it works from a menu's nested loop as well.
        """
        pk = getattr(self, "_picker", None)
        if pk is not None:
            try:
                pk.hide()                     # the object is kept, so its portraits survive
            except Exception:
                traceback.print_exc()
        self.qapp.quit()
        QtCore.QTimer.singleShot(0, self.qapp.quit)

    def picker_from_panel(self):
        """The Control Panel's way into Student Select.

        The mirror of the picker's own "Control Panel" button: step out of the way first, so
        the formation screen is not opened behind the panel (the pets re-raise the picker a
        few times a second, but a panel left on top would still look like nothing happened).
        """
        try:
            self.panel.hide()
        except Exception:
            traceback.print_exc()
        self.show_picker()

    def start_with_picker(self):
        """Startup: hold every student back and open the formation screen instead.

        The students that WOULD have come up (saved visibility) are pre-selected, so
        pressing DEPLOY straight away gives you last session's team. Hiding here is
        not persisted (cfg['hidden'] is untouched), and it happens before the event
        loop runs, so nobody flashes onto the desktop first.
        """
        team = [p for p in self.pets if p.isVisible()]
        for p in self.pets:
            try: p.hide()
            except Exception: traceback.print_exc()
        if getattr(self.panel, "sync_char_rows", None): self.panel.sync_char_rows()
        self.show_picker(team=team, startup=True)

    def _picker_action(self, menu):
        act = QtGui.QAction(PICKER_TEXT, menu)
        act.setIcon(badge_icon("\u2605", PICKER_COLOR))
        act.setToolTip("Open the formation screen: pick which students are on the desktop.")
        f = act.font(); f.setBold(True); act.setFont(f)
        act.triggered.connect(lambda _c=False: self.show_picker())
        return act

    def add_picker_entry(self, menu, top=False):
        """Put 'Student Select...' into a menu built by ui_menu.

        top=False  just above 'Control Panel...' (the student right-click menu)
        top=True   first real entry, under the header (the tray menu)
        """
        act = self._picker_action(menu)
        before = None
        for a in menu.actions():
            if top:
                if not isinstance(a, QtWidgets.QWidgetAction) and not a.isSeparator():
                    before = a; break
            elif a.text().startswith("Control Panel"):
                before = a; break
        if before is None: menu.addAction(act)
        else: menu.insertAction(before, act)
        return act

    # ------------------------------------------------------------------
    #  Menus
    # ------------------------------------------------------------------
    def show_menu(self, pos, p=None):
        """The right-click menu for one character (built fresh each time, so it is never stale).

        exec(), not popup(): exec() gives the native Windows menu, which stays above the
        pets as they re-stack themselves every 0.4s (sort_bubble_zorder). The Qt-drawn popup
        gets covered by them instead.
        """
        p = p or self.active or (self.pets[0] if self.pets else None)
        if p is None: return
        m = build_pet_menu(self, p)
        self.add_picker_entry(m)
        m.exec(pos)

    def _tray_target(self):
        vis = [p for p in self.pets if p.isVisible()]
        if not vis: return None
        return self.active if self.active in vis else vis[0]

    def _fill_tray_root(self):
        """Rebuilt every time the tray menu opens, so it always matches the desktop."""
        m = self.tray_root
        m.clear()
        self._tray_src = None                 # drops the previous student menu (and its actions)
        pet = self._tray_target()
        if pet is not None:
            # The student's own right-click menu, action for action. The actions stay
            # owned by `src` (kept alive in _tray_src), so switches that stay open,
            # submenus and the header all behave exactly as on a right-click.
            src = build_pet_menu(self, pet)
            self.add_picker_entry(src, top=True)
            for a in list(src.actions()):
                m.addAction(a)
            self._tray_src = src
            m.addSeparator()
            self._arena_entries(m)
            m.addMenu(self.tray_menu)
            return
        # Nobody on the desktop: there is no student to right-click, so this is the way in / out.
        w = QtWidgets.QWidget(); w.setObjectName("menuHeader")
        lay = QtWidgets.QHBoxLayout(w); lay.setContentsMargins(10, 6, 10, 4)
        name = QtWidgets.QLabel("Desktop Pets"); name.setObjectName("menuName")
        chip = QtWidgets.QLabel("no students out"); chip.setObjectName("stateChip"); chip.setProperty("tone", "idle")
        lay.addWidget(name); lay.addStretch(1); lay.addWidget(chip)
        wa = QtWidgets.QWidgetAction(m); wa.setDefaultWidget(w); m.addAction(wa)
        m.addSeparator()
        m.addAction(self._picker_action(m))
        self._tray_entry(m, "Deploy everyone", lambda: self.picker().quick_deploy(None), "\u25b2",
                         GROUP_COLORS.get("people", PICKER_COLOR))
        m.addSeparator()
        self._arena_entries(m)
        self._tray_entry(m, "Control Panel\u2026", self.show_panel, "\u2699", GROUP_COLORS.get("settings", "#6a7f9e"))
        m.addMenu(self.tray_menu)
        m.addSeparator()
        self._tray_entry(m, "Quit", self.quit_app, "\u2715", GROUP_COLORS.get("danger", "#ff5468"))

    def _arena_entries(self, m):
        """Title Screen... / Battle Arena... (only when babattlearena is installed)."""
        arena = getattr(self, "arena", None)
        if arena is None: return
        self._tray_entry(m, "Title Screen\u2026", self.show_title, "\u2302", "#1ea1ff")
        label = "Battle Arena: pause menu\u2026" if arena.battle_active() else "Battle Arena\u2026"
        self._tray_entry(m, label, self.show_arena, "\u2694", "#ff4c68")
        m.addSeparator()

    @staticmethod
    def _tray_entry(menu, text, fn, glyph, color):
        act = QtGui.QAction(text, menu)
        act.setIcon(badge_icon(glyph, color))

        def run():
            try: fn()
            except Exception: traceback.print_exc()
        act.triggered.connect(lambda _c=False: run())
        menu.addAction(act)
        return act

    def setup_tray(self):
        self.tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.show_panel(); return
        self.tray = QtWidgets.QSystemTrayIcon(make_icon(self.active.name if self.active else "A"), self)
        self.tray.setToolTip("Desktop Pets - click: Student Select, right-click: menu")
        # The old tray menu still exists (it keeps itself up to date every time it opens)
        # and is offered as a submenu of the new one.
        self.tray_menu = build_tray_menu(self)
        self.tray_menu.setTitle("All students && tray options")
        self.tray_menu.setIcon(badge_icon("\u2630", GROUP_COLORS.get("settings", "#6a7f9e")))
        self.tray_root = StayOpenMenu()
        self.tray_root.setMinimumWidth(250)
        self.tray_root.aboutToShow.connect(self._fill_tray_root)
        self._tray_src = None
        self._fill_tray_root()
        self.tray.setContextMenu(self.tray_root)
        reasons = QtWidgets.QSystemTrayIcon.ActivationReason

        def activated(r):
            if r in (reasons.Trigger, reasons.DoubleClick): self.show_picker()
            elif r == reasons.MiddleClick: self.show_panel()
        self.tray.activated.connect(activated)
        self.tray.show()
