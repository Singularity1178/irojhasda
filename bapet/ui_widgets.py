"""Reusable building blocks for the control panel. None of them knows what a pet is.

Every settings row follows one small contract (class Row):

    sync()                    pull the current value from app.cfg into the widget (no signals)
    update_enabled()          grey the row out when its `enabled` rule says so
    filter(tokens, extra)     show/hide for the search box, returns True if it stays visible

and talks to the rest of the panel only through `ctx`, which is the Panel and offers:

    ctx.A                     the App (cfg, set(), pets, ...)
    ctx.set(key, value)       change a setting and refresh whatever depends on it
    ctx.touch()               re-evaluate enabled rules and live text after a change
    ctx.run_action(action)    run a ui_spec.Action on the chosen target
    ctx.flash(text)           a short confirmation in the bar at the top
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRectF, Qt

from .config import DEFAULTS
from .ui_theme import COLORS, repolish

AlignV = Qt.AlignmentFlag.AlignVCenter


# =============================================================================
#  Small helpers
# =============================================================================
def make_button(text: str, fn: Callable, kind: str = "primary", tip: str = "") -> QtWidgets.QPushButton:
    """A styled button that calls fn() with no arguments.

    clicked(bool) hands its `checked` flag to whatever it is connected to; a plain
    one-argument lambda would be given `False` and break, so fn is wrapped to take nothing.
    kind: "primary" (solid blue) | "alt" | "danger" | "action" | "mini" | "chip".
    """
    b = QtWidgets.QPushButton(text)
    if kind != "primary": b.setObjectName(kind)
    if tip: b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(lambda _checked=False, f=fn: f())
    return b


def text_block(label: str, hint: str = "") -> QtWidgets.QWidget:
    """A bold-ish label with a small muted hint under it."""
    box = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(1)
    lb = QtWidgets.QLabel(label); lb.setObjectName("rowLabel"); lay.addWidget(lb)
    if hint:
        h = QtWidgets.QLabel(hint); h.setObjectName("hint"); h.setWordWrap(True); lay.addWidget(h)
    return box


def tokens_match(tokens: Sequence[str], text: str) -> bool:
    """Every search word must appear somewhere in text (already lower-case)."""
    return all(t in text for t in tokens)


class NoWheelSlider(QtWidgets.QSlider):
    """A slider that only reacts to the wheel once it has focus.

    Without this, scrolling a long page with the wheel changes every slider the pointer
    happens to cross.
    """
    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


class NoWheelCombo(QtWidgets.QComboBox):
    """A combo box that ignores the wheel until focused, and draws its own chevron.

    The chevron is painted here because a stylesheet that touches ::drop-down or ::down-arrow
    removes Qt's native arrow, and the native one clashes with the rounded border anyway.
    """
    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Size to a fixed character count, not to the longest item: one long entry would
        # otherwise make a whole page wider than its window and clip the right-hand controls.
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(14)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(COLORS["muted"] if self.isEnabled() else COLORS["faint"]), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 16.0, self.height() / 2.0
        p.drawPolyline([QtCore.QPointF(cx - 4, cy - 2), QtCore.QPointF(cx, cy + 2), QtCore.QPointF(cx + 4, cy - 2)])


class Switch(QtWidgets.QAbstractButton):
    """An on/off pill. Painted by hand so it looks the same everywhere."""
    W, H = 38, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(self.W, self.H)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        on, live = self.isChecked(), self.isEnabled()
        if live: track = COLORS["accent"] if on else "#c3d1e4"
        else:    track = "#c9d6e6" if on else "#e3e9f2"
        r = QRectF(0, 1, self.W, self.H - 2)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(track))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        knob = r.height() - 6
        x = r.right() - 3 - knob if on else r.left() + 3
        p.setBrush(QtGui.QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 3, knob, knob))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(COLORS["accent_hi"]), 1.5))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), r.height() / 2, r.height() / 2)


# =============================================================================
#  Rows
# =============================================================================
class Row(QtWidgets.QWidget):
    """Base class: one line (or block) inside a Section."""

    def __init__(self, ctx, label: str = "", hint: str = "", enabled: Optional[Callable] = None,
                 tags: str = "", keys: Sequence[str] = ()):
        super().__init__()
        self.ctx, self.enabled_if = ctx, enabled
        self.blob = " ".join(s for s in (label, hint, tags, *keys) if s).lower()
        if hint: self.setToolTip(hint)

    # -- contract ------------------------------------------------------------
    def sync(self) -> None: pass

    def update_enabled(self) -> None:
        if self.enabled_if is not None:
            self.setEnabled(bool(self.enabled_if(self.ctx.A.cfg)))

    def filter(self, tokens: Sequence[str], extra: str = "") -> bool:
        ok = (not tokens) or tokens_match(tokens, self.blob + extra)
        self.setVisible(ok)
        return ok


class ToggleRow(Row):
    """label + hint on the left, an on/off switch on the right. The whole row is clickable."""

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec.label, spec.hint, spec.enabled, spec.tags, (spec.key,))
        self.key = spec.key
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        lay.addWidget(text_block(spec.label, spec.hint), 1)
        self.switch = Switch(); lay.addWidget(self.switch, 0, AlignV)
        self.switch.toggled.connect(lambda v: self.ctx.set(self.key, bool(v)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync()

    def sync(self):
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(self.ctx.A.cfg[self.key]))
        self.switch.blockSignals(False)
        self.switch.update()

    def mouseReleaseEvent(self, e):
        if self.isEnabled() and e.button() == Qt.MouseButton.LeftButton \
                and self.rect().contains(e.position().toPoint()):
            self.switch.toggle()
        super().mouseReleaseEvent(e)


class SliderRow(Row):
    """label, current value and a reset arrow on one line; the slider underneath.

    The value turns blue and a reset arrow appears whenever the setting differs from
    config.DEFAULTS, so changed settings are easy to spot.
    """

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec.label, spec.hint, spec.enabled, spec.tags, (spec.key,))
        self.key, self.mult, self.fmt, self.show = spec.key, spec.mult, spec.fmt, spec.show
        self.default = DEFAULTS.get(spec.key)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(5)
        head = QtWidgets.QHBoxLayout(); head.setSpacing(6)
        head.addWidget(text_block(spec.label, spec.hint), 1)
        self.value = QtWidgets.QLabel(); self.value.setObjectName("value")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter); self.value.setMinimumWidth(66)
        head.addWidget(self.value, 0, AlignV)
        self.reset = QtWidgets.QToolButton(); self.reset.setObjectName("reset"); self.reset.setText("\u21ba")
        self.reset.setFixedSize(24, 24); self.reset.setCursor(Qt.CursorShape.PointingHandCursor)
        sp = self.reset.sizePolicy(); sp.setRetainSizeWhenHidden(True); self.reset.setSizePolicy(sp)
        if self.default is not None:
            self.reset.setToolTip("Reset to default (" + self.fmt.format(float(self.default) * self.show) + ")")
        head.addWidget(self.reset, 0, AlignV)
        lay.addLayout(head)
        self.slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(round(spec.lo * self.mult)), int(round(spec.hi * self.mult)))
        lay.addWidget(self.slider)
        self.slider.valueChanged.connect(self._moved)
        self.reset.clicked.connect(self._reset)
        self.sync()

    def _moved(self, i: int):
        v = round(i / self.mult, 6)
        self.ctx.set(self.key, v)
        self._paint(v)

    def _reset(self):
        if self.default is None: return
        self.ctx.set(self.key, self.default)
        self.sync()

    def _paint(self, v: float):
        self.value.setText(self.fmt.format(v * self.show))
        changed = self.default is not None and abs(v - float(self.default)) > 0.5 / self.mult + 1e-9
        self.value.setProperty("changed", changed); repolish(self.value)
        self.reset.setVisible(changed)

    def sync(self):
        v = float(self.ctx.A.cfg[self.key])
        self.slider.blockSignals(True); self.slider.setValue(int(round(v * self.mult))); self.slider.blockSignals(False)
        self._paint(v)


class ChoiceRow(Row):
    """label + hint on the left, a drop-down on the right."""

    def __init__(self, ctx, spec):
        super().__init__(ctx, spec.label, spec.hint, spec.enabled, spec.tags, (spec.key,))
        self.key = spec.key
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        lay.addWidget(text_block(spec.label, spec.hint), 1)
        self.combo = NoWheelCombo(); self.combo.setMinimumWidth(190)
        for text, value in spec.options:
            self.combo.addItem(text, value)
            if value in spec.disabled:
                item = self.combo.model().item(self.combo.count() - 1)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        lay.addWidget(self.combo, 0, AlignV)
        self.combo.currentIndexChanged.connect(lambda i: self.ctx.set(self.key, self.combo.itemData(i)))
        self.sync()

    def sync(self):
        v = self.ctx.A.cfg[self.key]
        i = self.combo.findData(v)
        self.combo.blockSignals(True)
        if i < 0:                                   # e.g. --fps 45: show it rather than lie
            self.combo.addItem(str(v), v); i = self.combo.count() - 1
        self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)


class ButtonsRow(Row):
    """A grid of equal-width buttons. Under a search it keeps only the buttons that match."""

    def __init__(self, ctx, entries: Sequence[dict], columns: int = 3):
        """entries: dicts with label, fn, kind, hint (and optionally blob for the search)."""
        super().__init__(ctx)
        self.columns, self.items = max(1, columns), []
        self.grid = QtWidgets.QGridLayout(self); self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8); self.grid.setVerticalSpacing(8)
        for c in range(self.columns): self.grid.setColumnStretch(c, 1)
        for e in entries:
            kind = e.get("kind", "alt")
            b = make_button(e["label"], e["fn"], kind, e.get("hint", ""))
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(36 if kind == "action" else 32)
            self.items.append((b, (e["label"] + " " + e.get("hint", "") + " " + e.get("blob", "")).lower()))
        self._place([b for b, _ in self.items])

    def _place(self, shown: Sequence[QtWidgets.QWidget]):
        for b, _ in self.items: self.grid.removeWidget(b)
        for i, b in enumerate(shown): self.grid.addWidget(b, i // self.columns, i % self.columns)
        keep = set(shown)
        for b, _ in self.items: b.setVisible(b in keep)

    def filter(self, tokens, extra=""):
        shown = [b for b, blob in self.items if (not tokens) or tokens_match(tokens, blob + extra)]
        self._place(shown)
        self.setVisible(bool(shown))
        return bool(shown)


class InfoRow(Row):
    """A paragraph of muted text produced by fn(ctx). `live` rows are refreshed every status tick."""

    def __init__(self, ctx, fn: Callable, live: bool = False):
        super().__init__(ctx)
        self.fn, self.live = fn, live
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel(); self.label.setObjectName("hint")
        self.label.setWordWrap(True); self.label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.label)
        self.sync()

    def sync(self):
        self.label.setText(self.fn(self.ctx))


# =============================================================================
#  Section card
# =============================================================================
class _Header(QtWidgets.QWidget):
    """The clickable title strip of a Section."""

    def __init__(self, title: str, hint: str, on_click: Callable):
        super().__init__()
        self.setObjectName("secHead"); self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        top = QtWidgets.QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0)
        self.title = QtWidgets.QLabel(title); self.title.setObjectName("secTitle")
        self.chev = QtWidgets.QLabel(); self.chev.setObjectName("chev")
        top.addWidget(self.title); top.addStretch(1); top.addWidget(self.chev)
        lay.addLayout(top)
        self.hint = QtWidgets.QLabel(hint); self.hint.setObjectName("secHint"); self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint)); lay.addWidget(self.hint)

    def set_open(self, is_open: bool):
        self.chev.setText("\u25be" if is_open else "\u25b8")
        self.hint.setVisible(is_open and bool(self.hint.text()))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.on_click()


class Section(QtWidgets.QFrame):
    """A white card with a title, an optional one-line hint and a stack of rows. Click the title to fold it."""

    def __init__(self, title: str, hint: str = "", collapsed: bool = False):
        super().__init__()
        self.setObjectName("card")
        self.title, self.hint = title, hint
        self.expanded, self.searching, self.rows = not collapsed, False, []
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(16, 12, 16, 14); outer.setSpacing(12)
        self.head = _Header(title, hint, self.toggle); outer.addWidget(self.head)
        self.body = QtWidgets.QWidget()
        self.body_lay = QtWidgets.QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0); self.body_lay.setSpacing(14)
        outer.addWidget(self.body)
        self._apply()

    def add(self, row: Row) -> Row:
        self.body_lay.addWidget(row); self.rows.append(row)
        return row

    def toggle(self):
        self.expanded = not self.expanded
        self._apply()

    def _apply(self):
        open_now = self.expanded or self.searching     # a search always unfolds what it found
        self.body.setVisible(open_now)
        self.head.set_open(open_now)

    def apply_filter(self, tokens: Sequence[str], page_title: str) -> int:
        """Show only matching rows; hide the whole card when none match. Returns how many matched."""
        extra = f" {page_title} {self.title} {self.hint}".lower()
        n = sum(1 for r in self.rows if r.filter(tokens, extra))
        self.searching = bool(tokens)
        self.setVisible(n > 0 or not tokens)
        self._apply()
        return n
