"""Pet mixin: the animation overlay - what is playing on each character, written on her.

A test bench, not a feature. It is off by default (cfg `anim_debug`) and nothing
here runs unless something switches it on: `--anim-debug`, the Debug toggle on the
Physics page, or run_anim_debug.bat, which is the whole app with this flag forced.

The point is to answer, while watching, the questions that are otherwise a guess:
which clip is on screen RIGHT NOW - not the one that was asked for, because an
attack phase or a fleeing run plays straight onto the rig, and a key the model has
no clip for plays nothing at all - how far through it she is, what the state
machine thinks her state and phase are, and which clip she is cross-fading out of.
One coloured panel per character, one colour per state, so two of them doing different
things can be told apart at a glance.

Deliberately ugly: fixed-width text, a black box, one progress bar. Readable beats
pretty, and nothing in here may be mistaken for the real art.
"""
from __future__ import annotations

import math
from collections import deque

from PySide6 import QtGui
from PySide6.QtCore import QRectF, Qt

from .mathutil import clamp


# Header colour per state. `ragdoll` wins over self.state: a limp body is not in a
# state machine any more, it is in the physics.
STATE_COLORS = {
    "idle":    "#3ddc84",
    "walk":    "#41c9ff",
    "alert":   "#ffd34d",
    "shot":    "#ff7ad9",
    "shoot":   "#ff5a4d",
    "flee":    "#ff9d2e",
    "drag":    "#c08bff",
    "fall":    "#8fa0b8",
    "ragdoll": "#ff2f6d",
}

BG = "#0b0d12"
FG = "#e8eef6"
DIM = "#9fb0c4"
BAR_H = 5                 # clip progress bar under the last line


def legend():
    """The colour key, for the console (the test launcher prints it)."""
    return ", ".join(f"{k}={v}" for k, v in STATE_COLORS.items())


class PetAnimDebug:
    # ---------------- --anim-debug overlay ----------------
    # The panel is rebuilt only when its text changes, and both the painter and the
    # click-through mask ask for the SAME geometry (anim_debug_panel), because a
    # label whose rectangle the mask does not know about is a label that gets
    # clipped away on every platform that still masks.
    def anim_debug_panel(self):
        """(lines, rect, font, pad, line height) for the overlay: rebuilt only when
        the text or the window width changes."""
        font = self._anim_debug_font()
        lines = self.anim_debug_lines()
        c = getattr(self, "_ad_panel", None)
        if c is not None and c[0] == self.W and c[1] == lines:
            return c[2]
        fm = QtGui.QFontMetrics(font)
        lh = max(1, fm.height()); pad = max(3, lh // 3)
        rows = max(1, int((self.H - 6.0 - pad * 2.0 - BAR_H) // lh))
        if len(lines) > rows:                     # keep the head, drop the tail
            lines = lines[:rows]
        avail = max(40.0, float(self.W) - 6.0)
        w = min(avail, max(fm.horizontalAdvance(s) for s in lines) + pad * 2.0)
        h = lh * len(lines) + pad * 2.0 + BAR_H
        rect = QRectF(3.0, 3.0, float(w), float(h))
        out = (lines, rect, font, pad, lh)
        self._ad_panel = (self.W, lines, out)
        return out

    def _anim_debug_font(self):
        """Fixed-pitch bold, sized off --scale like every other font in the app."""
        px = max(7.0, 10.5 * math.sqrt(max(0.25, float(self.cfg.get("scale", 1.0)))))
        f = getattr(self, "_adfont", None)
        if f is None or abs(f.pointSizeF() - px) > 0.25:
            f = QtGui.QFont("Consolas")            # Qt falls back to any fixed font
            if not QtGui.QFontInfo(f).exactMatch():
                f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
            f.setBold(True); f.setPointSizeF(px)
            self._adfont = f
        return f

    def anim_debug_lines(self):
        """Every line of this character's panel, rebuilt each frame.

        Ordered most useful first: the painter drops from the bottom when the window
        is too small for all of them.
        """
        rig = self.rig
        st = "ragdoll" if self.ragdoll else str(self.state)
        out = [f"{self.name}  [{st}]"]
        clip = getattr(rig, "clip", None)
        if clip is None:
            out.append("clip  (none)")
            return out
        nm = str(getattr(clip, "name", "?"))
        key = str(self.anim_key)
        # The last key the state machine asked for, and the clip that key resolves
        # to. They are not always the clip on screen: an attack phase, a flee run or
        # a vehicle swap plays straight onto the rig without going through play(),
        # so the key goes stale - and a key with no clip at all (a model with no
        # Normal_Reload) plays nothing and leaves the previous clip running. Either
        # way the mismatch is the thing worth seeing, so say it on this line.
        want = self.clips.get(key)
        if want is not None and getattr(want, "name", None) != getattr(clip, "name", None):
            nm += f"   (key {key} = {want.name})"
        elif want is None and key not in self.clips:
            nm += f"   (no clip for key {key} - nothing was played)"
        out.append(f"clip  {nm}")

        dur = float(getattr(clip, "duration", 0.0) or 0.0)
        t = float(getattr(rig, "t", 0.0) or 0.0)
        bits = [f"t {t:5.2f}/{dur:.2f}s" if dur > 0 else f"t {t:5.2f}s"]
        bits.append("loop" if getattr(rig, "loop", True) else "once")
        spd = float(getattr(rig, "speed", 1.0) or 0.0)
        if abs(spd - 1.0) > 1e-3: bits.append(f"x{spd:.2f}")
        if getattr(rig, "done", False): bits.append("ENDED")
        if getattr(rig, "limp", False): bits.append("FROZEN")
        out.append(" ".join(bits))

        sd = float(getattr(self, "state_dur", 0.0) or 0.0)
        out.append(f"state={self.state} key={key}  in-state {self.state_t:4.1f}"
                   + (f"/{sd:.1f}s" if sd > 0 else "s"))
        out.append(self._anim_debug_phase())

        flags = []
        if self.dragging: flags.append("DRAGGING")
        elif not self.grounded: flags.append("air=" + str(self.air_kind))
        if getattr(self, "support", None) is not None: flags.append("on-window")
        if self.ride_on: flags.append(f"RIDE {self.ride_t:.2f}")
        if self.ragdoll:
            eng = self.cfg.get("ragdoll_engine", "?")
            flags.append(f"RAGDOLL[{eng}] {self.rag_state} t={self.rag_t:.1f}s")
        if flags: out.append(" ".join(flags))

        chain = self._anim_debug_fade()
        if chain: out.append("fade " + chain)

        hist = self._anim_debug_history(clip)
        if len(hist) > 1: out.append("recent " + " > ".join(hist))
        return out

    def _anim_debug_phase(self):
        """Which beat of which event is driving her right now (combat, flee, cover)."""
        bits = []
        a = self.atk
        if a:
            bits.append(f"atk={a.get('phase')}")
            if a.get("stance"): bits.append(str(a["stance"]))
            bits.append(f"ammo {self.ammo}/{self.ammo_max}")
            if a.get("reload_anim"): bits.append("reload-clip")
            if a.get("fired"): bits.append("FIRED")
            cv = a.get("cover")
            if cv: bits.append("cover=" + ("window" if cv.get("win") else "student")
                               + ("+shield" if cv.get("shield") else ""))
            if a.get("target") is not None: bits.append("target=" + a["target"].name)
        f = self.flee
        if f:
            bits.append(f"flee={f.get('phase')} {f.get('t', 0.0):.1f}s")
        if self.state == "shot" and self.shot_key: bits.append(f"shot_key={self.shot_key}")
        return " ".join(bits) if bits else "phase -"

    def _anim_debug_fade(self):
        """`0.35 <- ClipA <- ClipB`: the outgoing cross-fade chain, newest first.

        Up to three clips can be alive at once (Rig caps the chain), and a pose that
        looks wrong for the first tenth of a second is usually the tail of the clip
        underneath the one you asked for.
        """
        rig = self.rig
        f = float(getattr(rig, "fade", 1.0) or 0.0)
        if getattr(rig, "prev", None) is None or f >= 1.0: return ""
        parts = [f"{f:.2f}"]
        lay = rig.prev
        while lay is not None and len(parts) < 5:
            c = getattr(lay, "clip", None)
            parts.append(getattr(c, "name", "?"))
            lay = getattr(lay, "prev", None)
        return " <- ".join(parts)

    def _anim_debug_history(self, clip):
        """The last few clips that started, newest last. Cheap change detector.

        Only touched while the overlay is on, so a normal run pays nothing for it.
        """
        last = getattr(self, "_ad_last", None)
        if clip is not last:
            self._ad_last = clip
            h = getattr(self, "_ad_hist", None)
            if h is None: h = self._ad_hist = deque(maxlen=4)
            h.append(getattr(clip, "name", "?"))
        return list(getattr(self, "_ad_hist", ()))

    # ---------------- painting ----------------
    def anim_debug_draw(self, p):
        """Draw the panel. Any failure here disables the overlay instead of taking
        the paint loop down with it - a debug overlay must never be the bug."""
        try:
            lines, rect, font, pad, lh = self.anim_debug_panel()
            fm = QtGui.QFontMetrics(font)
            st = "ragdoll" if self.ragdoll else str(self.state)
            col = QtGui.QColor(STATE_COLORS.get(st, "#c8d2e0"))
            p.save()
            p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
            p.fillRect(rect, QtGui.QColor(BG))
            p.setPen(QtGui.QPen(col, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(rect)
            # header stripe: this character's state, in its colour
            p.fillRect(QRectF(rect.x() + 1.0, rect.y() + 1.0, rect.width() - 2.0, lh + pad - 1.0), col)
            aw = rect.width() - pad * 2.0
            p.setFont(font)
            for i, s in enumerate(lines):
                y = rect.y() + pad + lh * i
                box = QRectF(rect.x() + pad, y, aw, lh)
                p.setPen(QtGui.QColor("#000000") if i == 0 else QtGui.QColor(FG if i < 4 else DIM))
                p.drawText(box, int(Qt.AlignmentFlag.AlignLeft.value) | int(Qt.AlignmentFlag.AlignVCenter.value),
                           fm.elidedText(s, Qt.TextElideMode.ElideRight, int(aw)))
            self._anim_debug_bar(p, rect, pad, col)
            p.restore()
        except Exception as e:
            print(f"[anim-debug] disabled on {self.name}: {type(e).__name__}: {e}")
            self.cfg["anim_debug"] = False

    def _anim_debug_bar(self, p, rect, pad, col):
        """How far through the clip she is. One line, filled left to right."""
        rig = self.rig
        clip = getattr(rig, "clip", None)
        dur = float(getattr(clip, "duration", 0.0) or 0.0) if clip is not None else 0.0
        bar = QRectF(rect.x() + pad, rect.bottom() - pad - BAR_H + 1.0,
                     max(1.0, rect.width() - pad * 2.0), float(BAR_H))
        p.fillRect(bar, QtGui.QColor(255, 255, 255, 40))
        if dur > 0:
            frac = clamp(float(getattr(rig, "t", 0.0) or 0.0) / dur, 0.0, 1.0)
            if getattr(rig, "done", False) or getattr(rig, "limp", False): frac = 1.0
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * frac, bar.height()), col)