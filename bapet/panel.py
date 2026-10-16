"""The control panel.

  +----------------------------------------------------------------+
  |  Desktop Pets   7 of 7 characters visible          [ search  ] |  header
  |  Actions apply to [ Everyone v ]               done: Poke > Hina|  target bar, on every page
  +------------+---------------------------------------------------+
  | Characters |  +- Section card ------------------------------+ |
  | Actions    |  | rows: switches, sliders, drop-downs, buttons | |
  | Behavior   |  +----------------------------------------------+ |
  | ...        |                                                   |
  +------------+---------------------------------------------------+
  |  Hina . idle . Cafe_Idle . looking at cursor    Status of [v]  |  live status footer
  +----------------------------------------------------------------+

*What* is on each page is data in ui_spec.PAGES; this file only assembles it, owns the search,
the target and the live status, and is the `ctx` every row talks to (see ui_widgets).

Other modules call into the panel through a handful of names, all kept from the old panel:
refresh(), sync_char_rows(), sync_screen_note(), sync_gun_box(), update_status(), plus the
widgets `sel_box` and `status` and the module-level QSS.
"""
from __future__ import annotations

import html
import re
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from .config import ANIM_KEYS, DEFAULTS
from .icons import make_icon
from .ui_rows import CUSTOM_ROWS
from .ui_spec import (ACTIONS, PAGES, Actions, Buttons, Choice, Custom, Info, Slider, Toggle,
                      pet_state)
from .ui_theme import QSS                      # re-exported: the entry script imports it from here
from .ui_widgets import (ButtonsRow, ChoiceRow, InfoRow, NoWheelCombo, Section, SliderRow,
                         ToggleRow, tokens_match)

__all__ = ["Panel", "QSS"]


class PageView:
    """One entry of the page stack: its widget, its sections, and what the search can match."""

    def __init__(self, spec, widget, sections=(), blob=""):
        self.spec, self.widget, self.sections, self.blob = spec, widget, list(sections), blob

    def apply_filter(self, tokens) -> int:
        """Narrow the page to what matches. Returns how many rows (or 1 for a text page) matched."""
        if not self.sections:                                   # a text page such as Help
            return 1 if (not tokens or tokens_match(tokens, self.blob)) else 0
        return sum(s.apply_filter(tokens, self.spec.title) for s in self.sections)


class Panel(QtWidgets.QWidget):
    def __init__(self, A):
        super().__init__()
        self.A = A
        self.rows = []            # every settings row, so refresh() can re-sync them all
        self.live_rows = []       # rows that show live text (refreshed on every status tick)
        self.named = {}           # composite rows by their Custom(...) name
        self.views = []           # PageView per sidebar entry, same order as PAGES
        self.tokens = []          # the current search words
        self._page = 0            # page to come back to once the search is cleared
        self._toast = QtCore.QTimer(self); self._toast.setSingleShot(True)
        self._toast.timeout.connect(lambda: self.toast.setText(""))

        self.setObjectName("root")
        self.setWindowTitle("Desktop Pets - Control Panel")
        self.setWindowIcon(make_icon("D"))
        self.resize(860, 740); self.setMinimumSize(700, 540)

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(10)
        root.addWidget(self._build_header())
        root.addWidget(self._build_bar())
        body = QtWidgets.QHBoxLayout(); body.setSpacing(12)
        self.nav = QtWidgets.QListWidget(); self.nav.setObjectName("nav"); self.nav.setFixedWidth(158)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stack = QtWidgets.QStackedWidget()
        body.addWidget(self.nav); body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_footer())

        self._build_pages()
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)
        QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Find), self, activated=self._focus_search)
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, activated=self._escape)
        self.refresh()

    # =========================================================================
    #  Building the window
    # =========================================================================
    def _build_header(self):
        head = QtWidgets.QFrame(); head.setObjectName("header")
        lay = QtWidgets.QHBoxLayout(head); lay.setContentsMargins(18, 12, 14, 12)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(0)
        self.title = QtWidgets.QLabel("Desktop Pets"); self.title.setObjectName("title")
        self.subtitle = QtWidgets.QLabel(""); self.subtitle.setObjectName("subtitle")
        col.addWidget(self.title); col.addWidget(self.subtitle)
        lay.addLayout(col); lay.addStretch(1)
        self.search = QtWidgets.QLineEdit(); self.search.setObjectName("search")
        self.search.setPlaceholderText("Search settings\u2026  (Ctrl+F)")
        self.search.setClearButtonEnabled(True); self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._on_search)
        lay.addWidget(self.search)
        return head

    def _build_bar(self):
        """'Actions apply to' lives above every page so it is never a tab away from the buttons."""
        bar = QtWidgets.QFrame(); bar.setObjectName("bar")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(14, 8, 14, 8); lay.setSpacing(10)
        lay.addWidget(QtWidgets.QLabel("Actions apply to"))
        self.who_box = NoWheelCombo(); self.who_box.setMinimumWidth(190)
        self.who_box.addItem("Everyone", -1)
        for i, p in enumerate(self.A.pets): self.who_box.addItem(p.name, i)
        self.who_box.currentIndexChanged.connect(lambda i: self._set_target(self.who_box.itemData(i)))
        lay.addWidget(self.who_box)
        note = QtWidgets.QLabel("for the Actions page and quick buttons"); note.setObjectName("barNote")
        lay.addWidget(note); lay.addStretch(1)
        self.toast = QtWidgets.QLabel(""); self.toast.setObjectName("toast"); lay.addWidget(self.toast)
        return bar

    def _build_footer(self):
        foot = QtWidgets.QFrame(); foot.setObjectName("footer")
        lay = QtWidgets.QHBoxLayout(foot); lay.setContentsMargins(14, 8, 14, 8); lay.setSpacing(10)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(1)
        self.status = QtWidgets.QLabel(""); self.status.setObjectName("statusMain")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status_sub = QtWidgets.QLabel(""); self.status_sub.setObjectName("statusSub")
        col.addWidget(self.status); col.addWidget(self.status_sub)
        lay.addLayout(col, 1)
        cap = QtWidgets.QLabel("Status of"); cap.setObjectName("barNote"); lay.addWidget(cap)
        self.sel_box = NoWheelCombo(); self.sel_box.setMinimumWidth(140)
        self.sel_box.addItems([p.name for p in self.A.pets] or ["-"])
        self.sel_box.currentIndexChanged.connect(lambda i: self.A.set_active_by_index(max(0, i)))
        lay.addWidget(self.sel_box)
        return foot

    def _build_pages(self):
        for page in PAGES:
            view = self._html_page(page) if page.html else self._settings_page(page)
            self.views.append(view)
            self.stack.addWidget(view.widget)
            self.nav.addItem(self._nav_text(page))
        self.empty = QtWidgets.QLabel(""); self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)

    def _nav_text(self, page, hits=None) -> str:
        return f"{page.glyph}   {page.title}" + ("" if hits is None else f"    {hits}")

    def _settings_page(self, page) -> PageView:
        scroll = QtWidgets.QScrollArea(); scroll.setObjectName("page"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host); lay.setContentsMargins(0, 0, 6, 8); lay.setSpacing(12)
        sections = []
        for sp in page.sections:
            sec = Section(sp.title, sp.hint, sp.collapsed)
            for rs in sp.rows: sec.add(self._make_row(rs))
            lay.addWidget(sec); sections.append(sec)
        lay.addStretch(1)
        scroll.setWidget(host)
        return PageView(page, scroll, sections)

    def _html_page(self, page) -> PageView:
        tb = QtWidgets.QTextBrowser(); tb.setOpenExternalLinks(True); tb.setHtml(page.html)
        text = html.unescape(re.sub(r"<[^>]+>", " ", page.html)).lower()
        return PageView(page, tb, blob=f"{page.title.lower()} {text}")

    def _make_row(self, spec):
        """One spec object from ui_spec -> one live row."""
        t = type(spec)
        if t is Toggle: row = ToggleRow(self, spec)
        elif t is Slider: row = SliderRow(self, spec)
        elif t is Choice: row = ChoiceRow(self, spec)
        elif t is Info:
            row = InfoRow(self, spec.fn, spec.live)
            if spec.live: self.live_rows.append(row)
        elif t is Buttons:
            row = ButtonsRow(self, [dict(label=b.label, fn=(lambda f=b.run: f(self)), kind=b.kind, hint=b.hint)
                                    for b in spec.items], spec.columns)
        elif t is Actions:
            acts = [a for a in ACTIONS if a.group == spec.group and (spec.only is None or a.key in spec.only)]
            if spec.only: acts.sort(key=lambda a: spec.only.index(a.key))
            row = ButtonsRow(self, [dict(label=f"{a.glyph}  {a.label}", fn=(lambda a=a: self.run_action(a)),
                                         kind="action", hint=a.hint, blob=f"{a.key} {a.group}") for a in acts],
                             spec.columns)
        elif t is Custom:
            row = CUSTOM_ROWS[spec.name](self)
            self.named[spec.name] = row
            if hasattr(row, "refresh_live"): self.live_rows.append(row)
        else:
            raise TypeError(f"unknown row spec: {spec!r}")
        self.rows.append(row)
        return row

    # =========================================================================
    #  ctx: what the rows call
    # =========================================================================
    def set(self, key, value):
        """A row changed a setting."""
        self.A.set(key, value)
        self.touch()

    def touch(self):
        """Something changed: grey out rows that no longer apply, refresh live text."""
        for r in self.rows: r.update_enabled()
        for r in self.live_rows:
            if hasattr(r, "refresh_live"): r.refresh_live()
            else: r.sync()

    def flash(self, text: str, ms: int = 3200):
        """A short confirmation at the right of the target bar."""
        self.toast.setText(text); self._toast.start(ms)

    def run_action(self, action, pets=None):
        """Run a ui_spec.Action on `pets` (default: the chosen target) and say what happened."""
        A = self.A
        try:
            if action.scope == "app":
                action.run(A, None); who = ""
            else:
                chosen = A.targets() if pets is None else list(pets)
                chosen = [p for p in chosen if p.isVisible()]
                if not chosen:
                    self.flash("Nobody visible to act on"); return
                for p in chosen: action.run(A, p)
                who = chosen[0].name if len(chosen) == 1 else f"{len(chosen)} characters"
        except Exception as e:                       # a bad action must never kill the panel
            traceback.print_exc()
            self.flash(f"{action.label} failed: {type(e).__name__}: {e}", 6000); return
        self.flash(f"\u2714 {action.label}" + (f" \u2192 {who}" if who else ""))

    def toggle_target(self, index: int):
        """Aim at one character, or back at everyone when she already is the target."""
        self._set_target(-1 if self.A.target == index else index)

    def reset_defaults(self):
        keep = {"screen", "positions", "hidden", "pos_x"}       # where things are is not a 'setting'
        ask = QtWidgets.QMessageBox.question(
            self, "Reset all settings",
            "Restore every option to its default?\n\nThe screen, character positions and which "
            "characters are hidden are kept.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if ask != QtWidgets.QMessageBox.StandardButton.Yes: return
        for key, val in DEFAULTS.items():
            if key not in keep: self.A.set(key, val)        # through set(): scale / fps / flags apply at once
        self.refresh()
        self.flash("All settings restored to their defaults")

    # =========================================================================
    #  Target
    # =========================================================================
    def _set_target(self, index):
        A = self.A
        index = -1 if index is None else int(index)
        A.set_target(index)
        if 0 <= index < len(A.pets): A.set_active(A.pets[index])    # the footer follows the target
        self.sync_target()

    def sync_target(self):
        A = self.A
        t = A.target if 0 <= A.target < len(A.pets) else -1
        self.who_box.blockSignals(True); self.who_box.setCurrentIndex(max(0, self.who_box.findData(t)))
        self.who_box.blockSignals(False)
        cast = self.named.get("cast")
        if cast is not None: cast.sync_target()

    # =========================================================================
    #  Search + navigation
    # =========================================================================
    def _on_nav(self, row: int):
        if row < 0: return
        self.stack.setCurrentIndex(row); self._page = row

    def _focus_search(self):
        self.search.setFocus(); self.search.selectAll()

    def _escape(self):
        if self.search.text(): self.search.clear()
        else: self.hide()

    def _on_search(self, text: str):
        self.tokens = text.lower().split()
        hits = [v.apply_filter(self.tokens) for v in self.views]
        for i, n in enumerate(hits):
            item = self.nav.item(i)
            item.setHidden(bool(self.tokens) and n == 0)
            item.setText(self._nav_text(PAGES[i], n if self.tokens else None))
        cur = self.nav.currentRow()
        if not self.tokens:                                     # cleared: stay where you are
            self.nav.setCurrentRow(cur if cur >= 0 else self._page)
            self.stack.setCurrentIndex(self.nav.currentRow())
        elif not any(hits):
            self.nav.setCurrentRow(-1)
            self.empty.setText(f"Nothing matches \u201c{html.escape(text.strip())}\u201d.\n\n"
                               "Try fewer or shorter words, such as speed, shadow or ragdoll.")
            self.stack.setCurrentWidget(self.empty)
        else:
            if cur < 0 or hits[cur] == 0:
                self.nav.setCurrentRow(next(i for i, n in enumerate(hits) if n))
            self.stack.setCurrentIndex(self.nav.currentRow())

    # =========================================================================
    #  Keeping the window in step with the app (names other modules call)
    # =========================================================================
    def refresh(self):
        """Re-read every setting from the app (after a preset, a wheel resize, a reset ...)."""
        for r in self.rows: r.sync()
        self.touch()
        self.sync_target()
        self._summary()

    def sync_char_rows(self):
        """Visibility changed somewhere else (tray, menu, startup)."""
        for name in ("cast", "hidden_banner"):
            if name in self.named: self.named[name].sync()
        self._summary()

    def sync_screen_note(self):
        if "screen" in self.named: self.named["screen"].sync_note()

    def sync_gun_box(self):
        """Put the weapon picker back on what the settings file says."""
        if "gun" in self.named: self.named["gun"].sync()

    def _summary(self):
        A = self.A
        n = sum(1 for p in A.pets if p.isVisible())
        self.subtitle.setText(f"{n} of {len(A.pets)} characters visible  \u00b7  screen {A.screen_label()}")

    def update_status(self):
        """Called about four times a second while the panel is open."""
        A = self.A
        p = A.active or (A.pets[0] if A.pets else None)
        if p is None: return
        short = A.dialogue.display_name
        state, _tone = pet_state(p)
        if p.gaze_peer is not None and p.gaze_left > 0: looking = f"looking at {short(p.gaze_peer.name)}"
        elif not p.cur_look: looking = "looking off into the room"
        else: looking = "looking at cursor"
        bits = [state, ANIM_KEYS.get(p.anim_key, (p.anim_key,))[0], looking]
        if p.busy_chat():
            if p.meet_target is not None: bits.append(f"walking over to {short(p.meet_target.name)}")
            elif p.chat_with is not None: bits.append(f"{A.dialogue.topic_label(p.chat_topic)} with {short(p.chat_with.name)}")
        self.status.setText(f"<b>{html.escape(p.name)}</b> &nbsp;\u00b7&nbsp; " + " \u00b7 ".join(html.escape(b) for b in bits))
        place = "on a window" if p.support is not None else ("on the floor" if p.grounded else "in the air")
        n = sum(1 for q in A.pets if q.isVisible())
        phys = ""
        w3 = getattr(A, "rag_world3d", None)
        if w3 is not None and (w3.active or w3.cost_ms > 0.05):
            # live cost of the 3D ragdolls, so the Physics iterations slider can be tuned by eye
            phys = f"  \u00b7  3D physics {w3.cost_ms:.1f} ms ({w3.active} active, {w3.iters}\u00d7)"
        self.status_sub.setText(f"{n} of {len(A.pets)} visible  \u00b7  {A.fps:.0f} fps  \u00b7  "
                                f"at {int(p.px)}, {int(p.py)}  \u00b7  {place}{phys}")
        self._summary()
        for r in self.live_rows:
            if hasattr(r, "refresh_live"): r.refresh_live()
            else: r.sync()
