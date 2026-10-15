"""Look and feel shared by the control panel, the right-click menu and the tray menu.

Three things live here and nothing else:

  COLORS      the colour tokens. Change a colour once, here.
  QSS         the application stylesheet built from those tokens. It is a plain string
              (no Qt objects are created at import time) because the entry script
              imports it before the QApplication exists.
  icons       tiny painted icons for menus (badge_icon, check_icon). They need a running
              QApplication, so they are only called when a menu is built, never at import.

Widgets pick their look from object names (`#card`, `#alt`, `#hint` ...) and from the
`changed` / `kind` dynamic properties, so no widget code carries colours of its own.
"""
from __future__ import annotations

from functools import lru_cache
from string import Template

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QRectF, Qt


# =============================================================================
#  Colour tokens
# =============================================================================
COLORS = dict(
    bg="#f3f6fb",          # window background
    card="#ffffff",        # cards, menus, inputs
    border="#dde6f2",      # card / divider lines
    text="#1d2b45",        # body text
    muted="#6b7f9e",       # hints, captions
    faint="#a3b1c6",       # disabled text
    accent="#128cff",      # primary blue (Blue Archive)
    accent_hi="#3aa1ff",   # hover
    accent_lo="#0b6fd0",   # pressed
    accent_soft="#e6f2ff", # tinted backgrounds
    track="#d6e4f5",       # slider groove / switch off
    danger="#d92d20",
    danger_soft="#fdecec",
    warn_soft="#fff6e0",
    warn_line="#f5d58a",
    warn_text="#7a5200",
    ok="#2fb36b",
)

# Colour of the little glyph badge in front of each kind of menu / button entry.
GROUP_COLORS = dict(
    react="#ff6fa5",     # poke, pet, cut-in, say ...
    move="#35b6ff",      # summon, spin, launch, ragdoll
    anim="#8b7bff",      # raw animation clips
    combat="#ff7a45",    # shooting
    social="#2fb36b",    # conversations
    world="#14b8c4",     # wind
    settings="#6b7f9e",  # quick settings, size, presets
    people="#f5a524",    # other characters
    danger="#e5484d",    # hide / quit
)


# =============================================================================
#  Stylesheet
# =============================================================================
QSS = Template(r"""
QWidget { font-family:'Segoe UI','Noto Sans','DejaVu Sans',sans-serif; font-size:13px; color:$text; }
QWidget#root { background:$bg; }
QToolTip { background:$text; color:white; border:none; padding:5px 8px; }

/* ---- header ------------------------------------------------------------ */
QFrame#header { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0b4fb3,stop:1 #35b6ff); border-radius:12px; }
QFrame#header QLabel { background:transparent; color:white; }
QFrame#header QLabel#title { font-size:19px; font-weight:700; }
QFrame#header QLabel#subtitle { color:#d6ebff; font-size:12px; }
QLineEdit#search { background:rgba(255,255,255,0.93); color:$text; border:1px solid transparent;
                   border-radius:15px; padding:6px 14px; selection-background-color:$accent; }
QLineEdit#search:focus { background:white; border:1px solid white; }

/* ---- target bar + footer ---------------------------------------------- */
QFrame#bar, QFrame#footer { background:$card; border:1px solid $border; border-radius:10px; }
QFrame#bar QLabel, QFrame#footer QLabel { background:transparent; }
QLabel#barNote { color:$muted; font-size:11px; }
QLabel#toast { color:$accent_lo; font-weight:600; }
QLabel#statusMain { font-size:13px; }
QLabel#statusSub { color:$muted; font-size:11px; }

/* ---- navigation -------------------------------------------------------- */
QListWidget#nav { background:transparent; border:none; outline:0; }
QListWidget#nav::item { padding:9px 12px; margin:1px 0; border-radius:8px; color:#35557f; }
QListWidget#nav::item:hover:!selected { background:#e3edf9; }
QListWidget#nav::item:selected { background:$accent; color:white; font-weight:600; }

/* ---- pages and cards --------------------------------------------------- */
QScrollArea#page { background:transparent; border:none; }
QScrollArea#page > QWidget > QWidget { background:transparent; }
QFrame#card { background:$card; border:1px solid $border; border-radius:12px; }
QWidget#secHead { background:transparent; }
QLabel#secTitle { font-size:13px; font-weight:700; background:transparent; }
QLabel#secHint { color:$muted; font-size:11px; background:transparent; }
QLabel#chev { color:$muted; font-size:11px; background:transparent; }
QLabel#rowLabel { background:transparent; }
QLabel#hint { color:$muted; font-size:11px; background:transparent; }
QLabel#value { color:$text; font-weight:600; background:#eef3fa; border-radius:6px; padding:1px 8px; }
QLabel#value[changed="true"] { color:$accent_lo; background:$accent_soft; }
QLabel#empty { color:$muted; font-size:14px; }
QLabel:disabled { color:$faint; }
QLabel#value:disabled { background:#f2f5f9; }

/* ---- buttons ----------------------------------------------------------- */
QPushButton { background:$accent; color:white; border:none; border-radius:8px; padding:7px 14px; font-weight:600; }
QPushButton:hover { background:$accent_hi; }
QPushButton:pressed { background:$accent_lo; }
QPushButton:disabled { background:#e3e9f1; color:#a0aec2; }
QPushButton#alt { background:#e3eefb; color:#1d4e89; }
QPushButton#alt:hover { background:#d3e5fa; }
QPushButton#alt:pressed { background:#c3dbf6; }
QPushButton#danger { background:$danger_soft; color:$danger; }
QPushButton#danger:hover { background:#fbd9d9; }
QPushButton#action { background:#f6faff; color:#17406f; border:1px solid #d6e5f8; text-align:left;
                     padding:8px 10px; font-weight:500; }
QPushButton#action:hover { background:#e4f1ff; border-color:$accent; }
QPushButton#action:pressed { background:#cfe5ff; }
QPushButton#mini { background:#eef4fb; color:#1d4e89; border-radius:6px; padding:3px 9px; font-size:11px; font-weight:600; }
QPushButton#mini:hover { background:#dbe9f9; }
QPushButton#chip { background:$card; color:#27456e; border:1px solid #c9dcf3; border-radius:15px; padding:6px 14px; font-weight:600; }
QPushButton#chip:hover { border-color:$accent; }
QPushButton#chip:checked { background:$accent; color:white; border-color:$accent; }
QToolButton#reset { background:transparent; border:none; color:$muted; font-size:14px; border-radius:6px; }
QToolButton#reset:hover { background:$accent_soft; color:$accent; }
QToolButton#target { background:#eef4fb; color:#6b7f9e; border:none; border-radius:11px; font-size:12px; }
QToolButton#target:hover { background:#dbe9f9; }
QToolButton#target:checked { background:$accent; color:white; }

/* ---- inputs ------------------------------------------------------------ */
QSlider::groove:horizontal { height:6px; background:$track; border-radius:3px; }
QSlider::sub-page:horizontal { background:$accent; border-radius:3px; }
QSlider::handle:horizontal { background:white; border:2px solid $accent; width:14px; margin:-5px 0; border-radius:8px; }
QSlider::handle:horizontal:hover { background:$accent_soft; }
QSlider::sub-page:horizontal:disabled { background:#c3d0e2; }
QSlider::handle:horizontal:disabled { border-color:#c3d0e2; }
QComboBox { background:$card; border:1px solid #c7d9ef; border-radius:8px; padding:5px 10px; min-height:20px; }
QComboBox:hover { border-color:$accent; }
QComboBox:disabled { background:#f2f5f9; color:$faint; }
QComboBox::drop-down { border:none; width:30px; }   /* the chevron itself is painted by ui_widgets.NoWheelCombo */
QComboBox QAbstractItemView { background:$card; border:1px solid #c7d9ef; selection-background-color:$accent;
                              selection-color:white; outline:0; padding:4px; }
QTextBrowser { background:$card; border:1px solid $border; border-radius:12px; padding:10px; }

/* ---- banner ------------------------------------------------------------ */
QFrame#banner { background:$warn_soft; border:1px solid $warn_line; border-radius:10px; }
QFrame#banner QLabel { background:transparent; color:$warn_text; }

/* ---- scrollbars -------------------------------------------------------- */
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#c3d3e8; border-radius:4px; min-height:32px; }
QScrollBar::handle:vertical:hover { background:#9fb8d8; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle:horizontal { background:#c3d3e8; border-radius:4px; min-width:32px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }

/* ---- menus (right-click menu and tray menu) --------------------------- */
QMenu { background:$card; border:1px solid #c7d9ef; padding:5px; }
QMenu::item { padding:6px 26px 6px 8px; margin:1px 0; border-radius:6px; }
QMenu::item:selected { background:$accent; color:white; }
QMenu::item:disabled { color:$faint; background:transparent; }
QMenu::icon { padding-left:3px; }
QMenu::separator { height:1px; background:#e6edf7; margin:5px 6px; }
QWidget#menuHeader { background:transparent; }
QLabel#menuName { font-size:14px; font-weight:700; background:transparent; }

/* ---- shared by the cast list and the menu header ---------------------- */
QLabel#stateChip { color:$accent_lo; background:$accent_soft; border-radius:9px; padding:2px 9px; font-size:11px; font-weight:600; }
QLabel#stateChip[tone="warn"] { color:#9a5b00; background:#fff0cf; }
QFrame#castRow { background:#f6f9fe; border:1px solid #e6edf7; border-radius:10px; }
QFrame#castRow[targeted="true"] { background:$accent_soft; border:1px solid $accent; }
QFrame#castRow QLabel { background:transparent; }
QFrame#castRow QLabel#stateChip { background:$accent_soft; }
QFrame#castRow QLabel#stateChip[tone="warn"] { background:#fff0cf; }
QLabel#gunStatus { background:#f3f7fc; color:#35557f; border-radius:8px; padding:7px 10px; }
""").substitute(COLORS)


def repolish(widget: QtWidgets.QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property (`changed`, `tone`) was changed."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)


# =============================================================================
#  Painted icons (need a running QApplication)
# =============================================================================
_SCALE = 2   # draw at 2x so the icons stay sharp on high-DPI screens


def _canvas(size: int) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(size * _SCALE, size * _SCALE)
    pm.setDevicePixelRatio(_SCALE)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


@lru_cache(maxsize=256)
def badge_icon(glyph: str, color: str = COLORS["accent"], size: int = 18) -> QtGui.QIcon:
    """A rounded colour square with one white glyph in it - the icon in front of a menu entry."""
    pm = _canvas(size)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(color))
    p.drawRoundedRect(QRectF(0, 0, size, size), 5, 5)
    f = QtGui.QFont()
    f.setFamilies(["Segoe UI Symbol", "Segoe UI", "DejaVu Sans"])
    f.setPixelSize(int(size * 0.62)); f.setBold(True)
    p.setFont(f); p.setPen(QtGui.QColor("white"))
    p.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter.value), glyph)
    p.end()
    return QtGui.QIcon(pm)


@lru_cache(maxsize=8)
def check_icon(on: bool, size: int = 18) -> QtGui.QIcon:
    """A checkbox drawn as an icon: filled blue with a tick when on, an empty outline when off.

    Menu toggles use this instead of QAction.setCheckable(), so the indicator looks the same
    on every platform and the menu can stay open while you flip several of them.
    """
    pm = _canvas(size)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    box = QRectF(1.5, 1.5, size - 3, size - 3)
    if on:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(COLORS["accent"]))
        p.drawRoundedRect(box, 4, 4)
        pen = QtGui.QPen(QtGui.QColor("white"), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        s = size / 18.0
        path = QtGui.QPainterPath()
        path.moveTo(5 * s, 9.5 * s); path.lineTo(8 * s, 12.5 * s); path.lineTo(13 * s, 6 * s)
        p.drawPath(path)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#b4c4da"), 1.5)); p.setBrush(QtGui.QColor("white"))
        p.drawRoundedRect(box, 4, 4)
    p.end()
    return QtGui.QIcon(pm)


@lru_cache(maxsize=8)
def radio_icon(on: bool, size: int = 18) -> QtGui.QIcon:
    """The radio-button twin of check_icon: used for 'pick one' lists such as Size and Preset."""
    pm = _canvas(size)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    c = size / 2.0
    p.setPen(QtGui.QPen(QtGui.QColor(COLORS["accent"] if on else "#b4c4da"), 1.5))
    p.setBrush(QtGui.QColor("white"))
    p.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    if on:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QtGui.QColor(COLORS["accent"]))
        p.drawEllipse(QRectF(c - 3.5, c - 3.5, 7, 7))
    p.end()
    return QtGui.QIcon(pm)
