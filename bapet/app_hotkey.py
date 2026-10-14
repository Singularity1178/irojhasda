"""App mixin: global hotkey and the ragdoll sound."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from .deps import HAVE_AUDIO, QAudioOutput, QMediaPlayer
from .config import HERE, RAG_SOUND, RAG_SOUND_VOLUME
from .hotkey import GlobalHotkey


class AppHotkey:
    # ---- global Ctrl+1: flop the character under the cursor ----
    def setup_hotkey(self):
        """System-wide Ctrl+1, with an in-app shortcut as the fallback.

        The hook only raises a flag (see GlobalHotkey); tick() does the work, so no
        Qt call ever happens inside a low-level keyboard callback.
        """
        self.hotkey = GlobalHotkey(self)
        if not self.hotkey.enabled:
            # No hook (or Windows said no): Ctrl+1 still works while this app has
            # focus, which is the whole app rather than one window.
            sc = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+1"), self.active)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(self.hotkey_fire)
            self.hotkey_shortcut = sc
            print("[info] Ctrl+1 works while the pets have focus")

    def setup_rag_sound(self):
        """The sound that plays when the hotkey lands on a character. Never fatal."""
        self.rag_player = None
        if not HAVE_AUDIO:
            print("[warn] no Qt multimedia - Ctrl+1 will be silent")
            return
        for cand in (HERE / RAG_SOUND, HERE / "sounds" / RAG_SOUND, Path(RAG_SOUND)):
            try:
                if cand.is_file():
                    # Qt 6 keeps the volume on the audio output, not the player.
                    out = QAudioOutput(); out.setVolume(RAG_SOUND_VOLUME)
                    pl = QMediaPlayer(); pl.setAudioOutput(out)
                    pl.setSource(QtCore.QUrl.fromLocalFile(str(cand.resolve())))
                    self.rag_player, self.rag_output = pl, out
                    print(f"[info] hotkey sound: {cand.name}")
                    return
            except Exception as e:
                print(f"[warn] hotkey sound {cand} unusable: {e}")
        print(f"[warn] {RAG_SOUND} not found - Ctrl+1 will be silent")

    def play_rag_sound(self):
        pl = self.rag_player
        if pl is None: return
        try:
            pl.setPosition(0)                    # replay immediately if still going
            pl.play()
        except Exception as e:
            print(f"[warn] could not play {RAG_SOUND}: {e}")

    def shutdown_hotkey(self):
        hk = getattr(self, "hotkey", None)
        if hk is not None:
            hk.fired = False; hk.remove()
        pl = getattr(self, "rag_player", None)
        if pl is not None:
            try: pl.stop(); pl.setSource(QtCore.QUrl())
            except Exception: pass

    def pet_under_cursor(self):
        """The visible character whose pixels the cursor is on, or None.

        Same per-pixel test cursor_logic() uses for hover, so the hotkey picks the
        character you can actually click, not the one whose window box you are over.
        Two characters can overlap; the nearer head wins.
        """
        cur = QtGui.QCursor.pos(); best, bd = None, None
        for p in self.pets:
            if not p.isVisible(): continue
            lx, ly = cur.x() - p.px, cur.y() - p.py
            if not (0 <= lx < p.W and 0 <= ly < p.H): continue
            a = p.alpha
            if a is not None:
                h, w = a.shape
                if a[min(h - 1, int(ly * h / p.H)), min(w - 1, int(lx * w / p.W))] <= 16: continue
            d = math.hypot(lx - p.head_px[0], ly - p.head_px[1])
            if bd is None or d < bd: bd, best = d, p
        return best

    def hotkey_fire(self):
        """Ctrl+1: ragdoll whoever is under the cursor, with a sound for the hit.

        The sound is the confirmation that the press landed on somebody. Bare
        desktop is silent - there is nothing there to confirm, and a "you missed"
        noise on every stray press just gets irritating.
        """
        p = self.pet_under_cursor()
        if p is None: return None
        if p.ragdoll: p.rag_getup()              # already limp: stand her back up
        else: p.start_ragdoll(kick=False)        # Ctrl+1: crumple in place, no launch
        self.play_rag_sound()
        return p
