"""Composite rows: the few controls that are more than one label and one widget.

They follow the same contract as ui_widgets.Row and are placed on a page from ui_spec with
`Custom("<name>")`; CUSTOM_ROWS at the bottom maps that name to the class.
"""
from __future__ import annotations

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import vfx
from .config import PRESETS
from .ui_spec import ACTION, pet_state, weapon_label
from .ui_theme import repolish
from .ui_widgets import NoWheelCombo, Row, Switch, make_button, text_block, tokens_match


# =============================================================================
#  Screen picker
# =============================================================================
class ScreenRow(Row):
    """Which monitor the characters live on. Apply is only live when the pick differs from the current screen."""

    def __init__(self, ctx):
        super().__init__(ctx, "Screen monitor display", tags="screen monitor display lock")
        A = ctx.A
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        line = QtWidgets.QHBoxLayout(); line.setSpacing(8)
        self.combo = NoWheelCombo()
        for i, s in enumerate(A.qapp.screens()):
            g = s.availableGeometry()
            self.combo.addItem(f"{i}: {s.name()}  ({g.width()}\u00d7{g.height()})", i)
        self.combo.addItem("Cursor's screen at startup", "cursor")
        self.combo.addItem("Primary screen", "primary")
        self.combo.currentIndexChanged.connect(lambda _i: self._pick_changed())
        self.apply_btn = make_button("Move here", self._apply, "primary", "Teleport every character to the chosen screen.")
        line.addWidget(self.combo, 1); line.addWidget(self.apply_btn)
        lay.addLayout(line)
        self.note = QtWidgets.QLabel(); self.note.setObjectName("hint"); self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.sync()

    def _saved_spec(self):
        v = self.ctx.A.cfg.get("screen", "cursor")
        return int(v) if isinstance(v, str) and v.isdigit() else v     # --screen 1 arrives as "1"

    def _pick_changed(self):
        self.apply_btn.setEnabled(self.combo.currentData() != self._saved_spec())

    def _apply(self):
        self.ctx.A.set_screen(self.combo.currentData())
        self.sync()
        self.ctx.flash("Moved everyone to the chosen screen")

    def sync(self):
        i = self.combo.findData(self._saved_spec())
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(i if i >= 0 else self.combo.count() - 2)
        self.combo.blockSignals(False)
        self._pick_changed()
        self.sync_note()

    def sync_note(self):
        A = self.ctx.A
        # A.home is the cached choice. resolve_screen() would re-read the cursor position for
        # the "cursor" setting and could silently move everyone, so it is not called from here.
        g = getattr(A, "home", None) or A.resolve_screen()
        self.note.setText(f"Currently on <b>{A.screen_label()}</b> "
                          f"(x {g.left()}\u2013{g.right()}, y {g.top()}\u2013{g.bottom()}).")


# =============================================================================
#  Shader preset chips
# =============================================================================
class PresetRow(Row):
    """One chip per preset; the active one is filled. Says so when sliders have drifted from it."""

    def __init__(self, ctx):
        super().__init__(ctx, "Preset shader style look", tags="toon cel pastel night flat", keys=tuple(PRESETS))
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        grid = QtWidgets.QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        self.chips = {}
        for i, name in enumerate(PRESETS):
            b = make_button(name, lambda n=name: self.ctx.A.apply_preset(n), "chip")
            b.setCheckable(True)
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            grid.addWidget(b, i // 3, i % 3); self.chips[name] = b
        for c in range(3): grid.setColumnStretch(c, 1)
        lay.addLayout(grid)
        line = QtWidgets.QHBoxLayout()
        self.note = QtWidgets.QLabel(); self.note.setObjectName("hint")
        line.addWidget(self.note, 1)
        self.redo = make_button("Re-apply preset", lambda: self.ctx.A.apply_preset(self.ctx.A.cfg["preset"]), "mini")
        line.addWidget(self.redo)
        lay.addLayout(line)
        self.sync()

    def modified(self) -> bool:
        cfg = self.ctx.A.cfg
        want = PRESETS.get(cfg.get("preset"))
        return want is None or any(abs(float(cfg[k]) - float(v)) > 1e-4 for k, v in want.items())

    def sync(self):
        cur = self.ctx.A.cfg.get("preset")
        for name, b in self.chips.items():
            b.blockSignals(True); b.setChecked(name == cur); b.blockSignals(False)
        mod = self.modified()
        self.note.setText("Customised: some sliders differ from this preset." if mod
                          else "Matches the preset exactly.")
        self.redo.setVisible(mod)

    refresh_live = sync          # a shader slider moved: re-check "customised" straight away


# =============================================================================
#  Cast list
# =============================================================================
class CastRow(QtWidgets.QFrame):
    """One character: target button, name, live state, quick buttons and a visibility switch."""

    QUICK = (("Poke", "poke"), ("Say", "say"), ("Summon", "summon"))

    def __init__(self, ctx, index: int, pet):
        super().__init__()
        self.ctx, self.index, self.pet = ctx, index, pet
        self.setObjectName("castRow")
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(8, 8, 10, 8); lay.setSpacing(6)
        self.target = QtWidgets.QToolButton(); self.target.setObjectName("target"); self.target.setText("\u25ce")
        self.target.setCheckable(True); self.target.setFixedSize(24, 24)
        self.target.setCursor(Qt.CursorShape.PointingHandCursor)
        self.target.setToolTip(f"Aim the Actions page at {pet.name} only (click again for everyone)")
        self.target.clicked.connect(lambda _c=False: ctx.toggle_target(self.index))
        lay.addWidget(self.target)
        lay.addWidget(text_block(pet.name, weapon_label(pet)), 1)
        self.state = QtWidgets.QLabel(); self.state.setObjectName("stateChip")
        lay.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)
        self.quick = []
        for text, key in self.QUICK:
            b = make_button(text, lambda k=key: ctx.run_action(ACTION[k], [self.pet]), "mini", ACTION[key].hint)
            lay.addWidget(b); self.quick.append(b)
        b = make_button("Reset", lambda: self.pet.reset_position(), "mini", "Put her back at the right edge.")
        lay.addWidget(b); self.quick.append(b)
        self.switch = Switch(); self.switch.setToolTip("Visible")
        self.switch.toggled.connect(lambda v: ctx.A.set_pet_visible(self.pet, bool(v)))
        lay.addWidget(self.switch)
        self.sync(); self.set_state()

    def sync(self):
        vis = self.pet.isVisible()
        self.switch.blockSignals(True); self.switch.setChecked(vis); self.switch.blockSignals(False)
        for b in self.quick: b.setEnabled(vis)

    def set_state(self):
        text, tone = pet_state(self.pet) if self.pet.isVisible() else ("hidden", "warn")
        self.state.setText(text)
        self.state.setProperty("tone", tone); repolish(self.state)

    def set_targeted(self, on: bool):
        self.target.blockSignals(True); self.target.setChecked(on); self.target.blockSignals(False)
        self.setProperty("targeted", on); repolish(self)


class CastList(Row):
    """Every character as a CastRow."""

    def __init__(self, ctx):
        super().__init__(ctx, "Characters cast visible hide show", tags="visible hide show target")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.rows = [CastRow(ctx, i, p) for i, p in enumerate(ctx.A.pets)]
        for r in self.rows: lay.addWidget(r)

    def sync(self):
        for r in self.rows: r.sync()
        self.sync_target()

    def sync_target(self):
        t = self.ctx.A.target
        for r in self.rows: r.set_targeted(r.index == t)

    def refresh_live(self):
        for r in self.rows: r.set_state()


class HiddenBanner(Row):
    """A warning that only exists while every character is hidden - the usual reason for a blank desktop."""

    def __init__(self, ctx):
        super().__init__(ctx, "hidden everyone nobody visible show all")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        frame = QtWidgets.QFrame(); frame.setObjectName("banner"); lay.addWidget(frame)
        fl = QtWidgets.QHBoxLayout(frame); fl.setContentsMargins(12, 8, 10, 8)
        msg = QtWidgets.QLabel("<b>Every character is hidden.</b> That is why the desktop looks empty.")
        msg.setWordWrap(True); fl.addWidget(msg, 1)
        fl.addWidget(make_button("Show all", lambda: ctx.A.set_all_visible(True), "primary"))
        self._needed = True
        self.sync()

    def sync(self):
        self._needed = bool(self.ctx.A.pets) and not any(p.isVisible() for p in self.ctx.A.pets)
        self.setVisible(self._needed)

    def filter(self, tokens, extra=""):
        ok = self._needed and ((not tokens) or tokens_match(tokens, self.blob + extra))
        self.setVisible(ok)
        return ok


# =============================================================================
#  Weapon test gun
# =============================================================================
class GunRow(Row):
    """Pick a weapon, then Ctrl + left click fires it from the middle of the screen at the cursor."""

    def __init__(self, ctx):
        super().__init__(ctx, "Weapon test gun Ctrl click fire hotkey", tags="weapon test gun vfx tracer beam explosion")
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        line = QtWidgets.QHBoxLayout(); line.setSpacing(8)
        line.addWidget(text_block("Test weapon", "Arms Ctrl + left click."), 1)
        self.combo = NoWheelCombo(); self.combo.setMinimumWidth(190)
        self.combo.addItem("Off", "")
        for name in vfx.WEAPON_FX: self.combo.addItem(name, name)
        self.combo.currentIndexChanged.connect(self._picked)
        line.addWidget(self.combo)
        line.addWidget(make_button("Fire one", self._fire_now, "alt", "One round at the cursor, no click needed."))
        lay.addLayout(line)
        self.status = QtWidgets.QLabel(); self.status.setObjectName("gunStatus"); self.status.setWordWrap(True)
        lay.addWidget(self.status)
        note = QtWidgets.QLabel(
            "Press or hold <b>Ctrl + left click</b> anywhere: a round flies from the middle of this screen to "
            "your cursor and hits any student it crosses \u2014 a bench for each weapon's tracer, beam or explosion. "
            "On a student it always works; elsewhere it needs the system mouse hook (the line above says which). "
            "While a weapon is picked the gun takes Ctrl + click; on <i>Off</i> it reaches the app underneath.")
        note.setObjectName("hint"); note.setWordWrap(True); lay.addWidget(note)
        self.sync()

    def _picked(self, _i):
        self.ctx.A.set("test_weapon", self.combo.currentData())
        self.refresh_live()

    def _fire_now(self):
        w = self.ctx.A.cfg.get("test_weapon") or ""
        if not w:
            self.status.setText("Pick a weapon first, then press Fire one.")
            return
        self.ctx.A.test_gun_fire(w, QtGui.QCursor.pos())
        self.refresh_live()

    def sync(self):
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.ctx.A.cfg.get("test_weapon") or "")))
        self.combo.blockSignals(False)
        self.refresh_live()

    def refresh_live(self):
        self.status.setText(self.ctx.A.gun_status())


CUSTOM_ROWS = {
    "screen": ScreenRow,
    "presets": PresetRow,
    "cast": CastList,
    "hidden_banner": HiddenBanner,
    "gun": GunRow,
}
