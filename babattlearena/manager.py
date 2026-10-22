"""ArenaManager: the glue between the desktop-pets App and every Battle Arena screen.

    title  ->  Desktop Pets (Student Select)    |   Battle Arena lobby -> battle -> results
                                                          ^      |  rematch / arena menu / title
                                                          +------+

While a battle runs the desktop pets are put away (not persisted - cfg['hidden'] is untouched) and
they come back exactly as they were when you leave the arena for the title screen.
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QTimer

from .settings import ArenaSettings


class ArenaManager:
    def __init__(self, app):
        self.app = app
        self.settings = ArenaSettings()
        self.battle = None
        self.last_teams = None
        self.saved_visible = None
        self._title = self._lobby = self._settings_win = self._pause = self._results = self._shop = None

    # ------------------------------------------------------------------ screens
    def title(self):
        if self._title is None:
            from .title import TitleScreen
            self._title = TitleScreen(self)
        return self._title

    def lobby(self):
        if self._lobby is None:
            from .lobby import ArenaLobby
            self._lobby = ArenaLobby(self)
        return self._lobby

    def shop(self):
        if self._shop is None:
            from sorashop.shop import SoraShop
            self._shop = SoraShop(self)
        return self._shop

    def _hide(self, w):
        if w is not None and w.isVisible():
            try: w.close_animated()
            except Exception: w.hide()

    def show_title(self, startup=False):
        if self.battle is not None:
            self.end_battle()
            self.restore_pets()
        self._hide(self._lobby)
        if self._shop is not None: self._shop.hide()
        try: self.app.hide_picker()
        except Exception: pass
        self.title().open()

    def open_desktop_pets(self):
        self._hide(self._title)
        team = getattr(self.app, "_startup_team", None)
        self.app._startup_team = None
        self.restore_pets()
        try:
            if team is not None:
                self.app.show_picker(team=team, startup=True)
            else:
                self.app.show_picker()
        except Exception:
            traceback.print_exc()

    def open_lobby(self):
        self._hide(self._title)
        try: self.app.hide_picker()
        except Exception: pass
        self.lobby().open()

    def open_shop(self):
        """Main menu -> Sora's shop (the scene opens where the title screen was)."""
        try:
            shop = self.shop()
        except Exception:
            traceback.print_exc()
            print("Sora's shop needs QtWebEngine:  pip install PySide6   (the full package, not PySide6-Essentials)")
            return
        t = self._title
        center = t.frameGeometry().center() if t is not None and t.isVisible() else None
        shop.open(center)
        self._hide(self._title)

    def close_shop(self):
        """Back arrow in the shop -> main menu."""
        center = None
        if self._shop is not None:
            if self._shop.isVisible():
                center = self._shop.frameGeometry().center()
            self._shop.hide()
        t = self.title()
        t.open()
        if center is not None:                  # reopen the menu where the (draggable) shop was, kept on screen
            g = t.home()
            x = min(max(center.x() - t.width() // 2, g.left()), g.right() - t.width() + 1)
            y = min(max(center.y() - t.height() // 2, g.top()), g.bottom() - t.height() + 1)
            t.move(x, y)

    def open_settings(self):
        if self._settings_win is None:
            from .settings import SettingsWindow
            self._settings_win = SettingsWindow(self)
        self._settings_win.open()

    # ------------------------------------------------------------------ battle
    def battle_active(self):
        return self.battle is not None

    def hide_pets(self):
        if self.saved_visible is None:
            self.saved_visible = [p for p in self.app.pets if p.isVisible()]
        for p in self.app.pets:
            try:
                p.rag_clear()
            except Exception:
                pass
            p.hide()
        try: self.app.end_all_chats()
        except Exception: pass

    def restore_pets(self):
        vis = self.saved_visible
        self.saved_visible = None
        if not vis: return
        for p in vis:
            try:
                p.show()
            except Exception:
                traceback.print_exc()
        try:
            self.app.restack(force=True)
        except Exception:
            pass

    def begin_battle(self, teams):
        self._hide(self._lobby); self._hide(self._settings_win); self._hide(self._title)
        self._hide(self._results); self._hide(self._pause)
        try: self.app.hide_picker()
        except Exception: pass
        self.hide_pets()
        self.last_teams = [list(teams[0]), list(teams[1])]
        self.settings.save()
        try:
            from .battle import Battle
            self.battle = Battle(self, self.last_teams, self.settings)
            self.battle.start()
        except Exception:
            traceback.print_exc()
            self.battle = None
            self.restore_pets()
            self.lobby().open()

    def end_battle(self):
        b = self.battle
        self.battle = None
        if b is not None:
            try: b.stop()
            except Exception: traceback.print_exc()
        for w in (self._pause, self._results):
            if w is not None:
                try: w.hide()
                except Exception: pass

    def pause_menu(self):
        if self.battle is None: return
        if self._results is not None and self._results.isVisible(): return
        self.battle.set_paused(True)
        if self._pause is None:
            from .hud import PauseMenu
            self._pause = PauseMenu(self)
        self._pause.open()

    def resume(self):
        self._hide(self._pause)
        if self.battle is not None:
            self.battle.set_paused(False)

    def show_results(self, battle):
        if self._results is None:
            from .hud import ResultScreen
            self._results = ResultScreen(self)
        self._results.set_battle(battle)
        self._results.open()

    def rematch(self):
        teams = self.last_teams
        self.end_battle()
        if teams:
            QTimer.singleShot(120, lambda: self.begin_battle(teams))

    def to_lobby(self):
        self.end_battle()
        self.lobby().open()

    def to_title(self):
        self.end_battle()
        self.restore_pets()
        self.title().open()


def install(app):
    """Attach the arena to the App (app.arena) and return the manager."""
    mgr = getattr(app, "arena", None)
    if mgr is None:
        mgr = ArenaManager(app)
        app.arena = mgr
    return mgr
