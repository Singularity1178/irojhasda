"""App: owns every Pet, the timer loop and the shared overlays. Features live in the app_* mixins."""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import moderngl
from PySide6 import QtCore
from PySide6.QtCore import QTimer, Qt

from dialogue import ChatDirector, DialogueEngine, StateReactor, SystemWatcher
from .deps import HAVE_PYMUNK, RagWorld
from .app_effects import AppEffects
from .app_hotkey import AppHotkey
from .app_pets import AppPets
from .app_screen import AppScreen
from .app_settings import AppSettings
from .app_testgun import AppTestGun
from .app_ui import AppUI
from .character import Character
from .config import DEFAULTS, SETTINGS_PATH
from .overlays import Cutin, ShotFX
from .panel import Panel
from .pet import Pet
from .profiles import load_profile
from .renderer import Renderer
from .wintracker import WinTracker


class App(AppHotkey, AppPets, AppScreen, AppSettings, AppTestGun, AppEffects, AppUI, QtCore.QObject):
    def __init__(self, qapp, paths, args):
        super().__init__()
        self.qapp, self.args = qapp, args
        self.cfg = dict(DEFAULTS)
        try:
            if SETTINGS_PATH.exists(): self.cfg.update({k: v for k, v in json.loads(SETTINGS_PATH.read_text()).items() if k in DEFAULTS})
        except Exception: pass
        if not isinstance(self.cfg.get("positions"), dict): self.cfg["positions"] = {}
        if not isinstance(self.cfg.get("hidden"), list): self.cfg["hidden"] = []
        if args.scale: self.cfg["scale"] = args.scale
        if args.fps: self.cfg["fps"] = args.fps
        if getattr(args, "rag_debug", False): self.cfg["ragdoll_debug"] = True
        self.rag_trace = int(getattr(args, "rag_trace", 0) or 0)
        self.rag_diag = int(getattr(args, "rag_diag", 0) or 0)
        if self.rag_diag:
            # Every character starts logging, not just the first: a pop you
            # cannot reproduce is usually a specific character in a specific
            # spot, so the log has to cover all of them.
            import ragdiag
            ragdiag.enable(self)
            if self.rag_diag > 0 and not self.rag_trace:
                # ragdiag prints more than rag-trace; running both just
                # duplicates the same numbers into the terminal.
                self.rag_trace = self.rag_diag
        if getattr(args, "screen", None) is not None: self.cfg["screen"] = args.screen
        self.home = self.resolve_screen()
        print("Locked to screen:", self.screen_label())
        paths = [Path(p) for p in paths]
        print(f"{len(paths)} model(s) found.")
        self.chars = []
        for i, p in enumerate(paths):
            try:
                self.chars.append(Character(p, i, args.dump, load_profile(p)))
            except Exception as e:
                print(f"[error] could not load {p.name}: {type(e).__name__}: {e}")
                traceback.print_exc()
        if not self.chars:
            raise RuntimeError("none of the .glb files could be loaded")
        self.ctx = moderngl.create_standalone_context(require=330)
        print("GL:", self.ctx.info.get("GL_RENDERER"))
        self.tracker = WinTracker(); self.trk_t = 0.0
        # One physics world for the whole app, shared by every pet, so two of
        # them can collide with each other. Only exists with pymunk; without it
        # every pet falls back to the legacy rod ragdoll.
        self.rag_world = RagWorld() if HAVE_PYMUNK else None
        if self.rag_world is not None:
            g = self.home
            self.rag_world.set_screen((g.left(), g.top(), g.right() + 1, g.bottom() + 1))
        self.trk_wins = None                              # last window list we synced
        self.cutin = Cutin()
        self.shotfx = ShotFX()
        self.gusts = []                        # active wind bursts: dicts(x, y, t0)
        # dialogue: the lines, the computer-state tags, and who talks to whom
        self.dialogue = DialogueEngine()
        # the watcher polls on its own thread so a slow sample can never
        # stutter the render loop
        self.watcher = SystemWatcher(priority=self.dialogue.state_order,
                                     threaded=True,
                                     debug=bool(getattr(args, "debug_tags", False)))
        self.chats = ChatDirector(self)
        self.pets = []
        self.z_order = []                    # pets by bubble age, oldest first (no longer drives stacking)
        self.z_base = []                     # fixed back-to-front order, filled as pets are created
        self.z_sig = None
        self.z_t = 0.0
        self.active = None
        self.target = -1                                   # -1 = all characters
        hidden = set(self.cfg["hidden"])
        print(f"Saved hidden characters: {len(hidden)} ({', '.join(sorted(hidden)) or 'none'})")
        for i, ch in enumerate(self.chars):
            ch.renderer = Renderer(ch.model, ch.fit, self.ctx)
            pet = Pet(self, ch)
            self.pets.append(pet)
        self.active = self.pets[0]
        if self.test_weapon(): self.setup_mouse_hook()   # only while a weapon is picked: see setup_mouse_hook
        self.panel = Panel(self)             # picker and asks the gun how it is doing
        self.setup_tray()
        self.save_timer = QTimer(self); self.save_timer.setSingleShot(True); self.save_timer.timeout.connect(self.save)
        # one pet reacts to a computer-state change, e.g. opening a game
        self.reactor = StateReactor(self.dialogue, self.watcher, self.pets,
                                    clock=time.perf_counter)
        self.last = time.perf_counter(); self.fps = 30.0; self.status_t = 0.0; self.errors = 0
        self.timer = QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick); self.timer.start(int(1000 / self.cfg["fps"]))
        qapp.aboutToQuit.connect(self.save)
        for i, p in enumerate(self.pets):
            p.spawn(i)
        # apply the saved hidden state only once every pet has spawned - doing it
        # inside the loop above judged later pets while they were still invisible
        self.apply_hidden_state(hidden)
        self.setup_hotkey()
        self.setup_rag_sound()
        qapp.aboutToQuit.connect(self.shutdown_hotkey)
        qapp.aboutToQuit.connect(self.shutdown_mouse_hook)

    # ---- main loop ----
    def tick(self):
        now = time.perf_counter(); dt = min(0.1, now - self.last); self.last = now
        self.fps = 0.9 * self.fps + 0.1 * (1.0 / max(dt, 1e-3))
        # The keyboard hook only raises a flag; the real work happens here, off the
        # hook callback. Checked outside the try below so one bad hotkey target can
        # never take the whole app down.
        hk = getattr(self, "hotkey", None)
        if hk is not None and hk.fired:
            hk.fired = False
            try:
                self.hotkey_fire()
            except Exception:
                traceback.print_exc()
        try:
            if self.cfg["perch"] and self.tracker.enabled and now - self.trk_t > 0.12:
                self.tracker.refresh(self.active.dpr if self.active else 1.0, self.home.top()); self.trk_t = now
            # Physics: window colliders first (only when the list actually
            # changed), then ONE step for the whole app - not one per pet, or
            # four pets on screen would advance the world four times as fast.
            if self.rag_world is not None:
                if self.tracker.wins is not self.trk_wins:
                    self.trk_wins = self.tracker.wins
                    try:
                        self.rag_world.sync_windows(self.tracker.wins, self.trk_t,
                                                    bool(self.cfg["perch"] and self.tracker.enabled))
                    except Exception:
                        traceback.print_exc()
                self.rag_world.step(dt)
            self.watcher.tick()                                # cheap; throttles itself
            self.dialogue.set_context(self.watcher.current_context())
            self.reactor.reconfigure(self.pets)
            self.reactor.poll()
            for p in self.pets:
                if p.isVisible(): p.tick(dt)
            self.test_gun_step(dt)                        # Ctrl + left click test weapon
            if self.cutin.active: self.cutin.step()
            if self.shotfx.active: self.shotfx.step(dt)
            self.restack()                                     # cheap: only acts when a shield changes the order
            if now - self.z_t > 0.4: self.z_t = now; self.sort_bubble_zorder()
            if self.panel.isVisible() and now - self.status_t > 0.25: self.panel.update_status(); self.status_t = now
            self.errors = 0
        except Exception:
            traceback.print_exc(); self.errors += 1
            if self.errors > 30:
                print("Too many errors, stopping."); self.timer.stop()
