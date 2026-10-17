"""The right-click menu on a character and the tray-icon menu.

Right-click menu, top to bottom - most used first, rarely used tucked into submenus:

    Hina                                   [idle]      <- who this menu is for, and what she is doing
    Poke  Pet  EX Cut-in  Say something                <- reactions
    Ragdoll / Get up   Shoot a student                 <- greyed out, with the reason, when impossible
    More actions >   Animations >                      <- everything else she can do
    Behavior >   Display >   Other characters >        <- settings, with switches that stay open
    Control Panel...   Hide Hina   Hide all to tray   Quit

The actions come from ui_spec.ACTIONS, the same list the panel's Actions page uses, so the two
cannot drift apart. Switches in the menu are checkbox *icons* on plain entries, not
QAction.setCheckable(): they look identical on every platform, and StayOpenMenu lets you flip
several in a row without the menu closing.
"""
from __future__ import annotations

import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from .config import ANIM_KEYS, PRESETS
from .ui_spec import ACTION, pet_state
from .ui_theme import GROUP_COLORS, badge_icon, check_icon, radio_icon

SIZES = (50, 75, 100, 125, 150, 200)          # percent, the quick picks under Display > Size

# (cfg key, menu text, tooltip)
BEHAVIOR_TOGGLES = (
    ("wander", "Wander around", "Walk, idle and explore on her own."),
    ("look_at_cursor", "Look at my cursor", ""),
    ("follow_cursor", "Follow my cursor", "Walk over to wherever the mouse is."),
    ("perch", "Perch on my windows", "Jump onto title bars and ride them (Windows only)."),
    ("speech", "Speech bubbles", ""),
    ("chat", "Talk to each other", "Needs 2+ visible characters."),
    ("ragdoll_auto_getup", "Stand up by herself after a ragdoll", ""),
)
DISPLAY_TOGGLES = (
    ("always_on_top", "Always on top", ""),
    ("particles", "Particles", "Hearts and sparkles."),
    ("ba_vfx", "Blue Archive effects", "Flashes, sparks, beams, rings."),
    ("light_follow", "Light follows my cursor", "A 3D point light that tracks the pointer."),
)


# =============================================================================
#  Pieces
# =============================================================================
class StayOpenMenu(QtWidgets.QMenu):
    """A QMenu whose entries flagged `stay_open` run without closing it (used for switches)."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self.setToolTipsVisible(True)

    def mouseReleaseEvent(self, e):
        act = self.actionAt(e.position().toPoint())
        if act is not None and act.isEnabled() and act.property("stay_open"):
            act.trigger()
            e.accept()
            return
        super().mouseReleaseEvent(e)


def _guard(fn, *args):
    """Run a menu action; a failing one prints its traceback and leaves the app running."""
    try:
        fn(*args)
    except Exception:
        traceback.print_exc()


def _entry(menu, text, fn, glyph=None, color=None, tip="", enabled=True, stay_open=False):
    """Add one plain entry. fn takes no arguments."""
    act = QtGui.QAction(text, menu)
    if glyph: act.setIcon(badge_icon(glyph, color or GROUP_COLORS["settings"]))
    if tip: act.setToolTip(tip)
    act.setEnabled(enabled)
    if stay_open: act.setProperty("stay_open", True)
    act.triggered.connect(lambda _c=False, f=fn: _guard(f))
    menu.addAction(act)
    return act


def _toggle_entry(menu, text, initial, apply, tip=""):
    """A switch entry: checkbox icon, and the menu stays open when you flip it.

    apply(new_value) is called on every flip; the icon is redrawn from the new state.
    """
    state = [bool(initial)]
    act = QtGui.QAction(text, menu)
    act.setIcon(check_icon(state[0])); act.setProperty("stay_open", True)
    if tip: act.setToolTip(tip)

    def flip():
        state[0] = not state[0]
        apply(state[0])
        act.setIcon(check_icon(state[0]))
    act.triggered.connect(lambda _c=False: _guard(flip))
    menu.addAction(act)
    return act


def _switch(menu, app, text, key, tip=""):
    """A switch bound to cfg[key]. refresh=True keeps an open control panel in step."""
    return _toggle_entry(menu, text, app.cfg.get(key), lambda v: app.set(key, v, refresh=True), tip)


def _visible_entry(menu, app, pet):
    return _toggle_entry(menu, "Visible", pet.isVisible(), lambda v: app.set_pet_visible(pet, v))


def _submenu(menu, title, glyph, color) -> StayOpenMenu:
    sub = StayOpenMenu(title, menu)
    sub.setIcon(badge_icon(glyph, color))
    menu.addMenu(sub)
    return sub


def _action_entry(menu, app, pet, action, text=None):
    """An ui_spec.Action as a menu entry, greyed out (with the reason) when it cannot run now."""
    reason = action.unavailable(app, pet) if action.unavailable else None
    label = text or action.label_for(pet)
    return _entry(menu, label + (f"   ({reason})" if reason else ""),
                  lambda: action.run(app, pet), action.glyph, GROUP_COLORS[action.group],
                  tip=action.hint, enabled=reason is None)


def _quit_entry(menu, app):
    """Put a Quit entry that actually quits.

    A menu runs its own nested event loop, and a quit raised from inside one only unwinds
    that loop - the menu closed and the app carried on, so Quit looked like it needed a
    second press. Closing the menu first puts us back on the main loop, and the quit is
    taken from there. app.quit_app() then puts Student Select away, which is the other half
    of it (a visible formation screen also stops quit() from leaving the loop).
    """
    def run():
        menu.close()
        QtCore.QTimer.singleShot(0, app.quit_app)

    return _entry(menu, "Quit", run, "\u2715", GROUP_COLORS["danger"])


def _initial_icon(pet):
    """A badge with the character's first letter; grey while she is hidden."""
    color = GROUP_COLORS["people"] if pet.isVisible() else "#b4c4da"
    return badge_icon((pet.name or "?")[:1].upper(), color)


def _header(menu, pet):
    """Name and live state at the top of the menu."""
    w = QtWidgets.QWidget(); w.setObjectName("menuHeader")
    lay = QtWidgets.QHBoxLayout(w); lay.setContentsMargins(10, 6, 10, 4)
    name = QtWidgets.QLabel(pet.name); name.setObjectName("menuName")
    text, tone = pet_state(pet)
    chip = QtWidgets.QLabel(text); chip.setObjectName("stateChip"); chip.setProperty("tone", tone)
    lay.addWidget(name); lay.addStretch(1); lay.addWidget(chip)
    wa = QtWidgets.QWidgetAction(menu); wa.setDefaultWidget(w)
    menu.addAction(wa)


# =============================================================================
#  Right-click menu
# =============================================================================
def build_pet_menu(app, pet) -> StayOpenMenu:
    m = StayOpenMenu()
    m.setMinimumWidth(250)
    _header(m, pet)
    m.addSeparator()

    for key in ("poke", "pet", "cutin", "say"):
        _action_entry(m, app, pet, ACTION[key])
    m.addSeparator()
    _action_entry(m, app, pet, ACTION["ragdoll"])
    _action_entry(m, app, pet, ACTION["shoot"])

    more = _submenu(m, "More actions", "\u2026", GROUP_COLORS["move"])
    for key in ("tactical", "look", "spin", "launch", "summon"):
        _action_entry(more, app, pet, ACTION[key])

    anims = _submenu(m, "Animations", "\u25b6", GROUP_COLORS["anim"])
    for key, (clip, _loops) in ANIM_KEYS.items():
        act = ACTION[f"anim_{key}"]
        _action_entry(anims, app, pet, act, f"{act.label}   \u00b7   {clip}")
    m.addSeparator()

    _behavior_menu(m, app)
    _display_menu(m, app)
    _others_menu(m, app, pet)
    m.addSeparator()

    _entry(m, "Control Panel\u2026", app.show_panel, "\u2699", GROUP_COLORS["settings"])
    _entry(m, f"Hide {pet.name}", lambda: app.set_pet_visible(pet, False), "\u25cc", GROUP_COLORS["danger"],
           tip="She comes back from the tray menu or the panel's Characters page.")
    _entry(m, "Hide all to tray", app.toggle_pet, "\u25cc", GROUP_COLORS["danger"])
    _quit_entry(m, app)
    return m


def _behavior_menu(m, app):
    sub = _submenu(m, "Behavior", "\u2699", GROUP_COLORS["settings"])
    for key, text, tip in BEHAVIOR_TOGGLES:
        _switch(sub, app, text, key, tip)


def _display_menu(m, app):
    sub = _submenu(m, "Display", "\u2726", GROUP_COLORS["settings"])
    pct = int(round(float(app.cfg["scale"]) * 100))
    size = StayOpenMenu(f"Size   \u00b7   {pct}%", sub)
    size.setIcon(badge_icon("\u2194", GROUP_COLORS["settings"]))
    sub.addMenu(size)
    for p in SIZES:
        _entry(size, f"{p}%", lambda v=p: app.set("scale", v / 100, refresh=True)).setIcon(radio_icon(abs(pct - p) <= 1))
    look = StayOpenMenu(f"Shader preset   \u00b7   {app.cfg['preset']}", sub)
    look.setIcon(badge_icon("\u2726", GROUP_COLORS["react"]))
    sub.addMenu(look)
    for name in PRESETS:
        _entry(look, name, lambda n=name: app.apply_preset(n)).setIcon(radio_icon(name == app.cfg["preset"]))
    sub.addSeparator()
    for key, text, tip in DISPLAY_TOGGLES:
        _switch(sub, app, text, key, tip)


def _others_menu(m, app, pet):
    others = [q for q in app.pets if q is not pet]
    if not others: return
    sub = _submenu(m, "Other characters", "\u263a", GROUP_COLORS["people"])
    _entry(sub, "Summon everyone to cursor", lambda: [app.summon(q) for q in app.pets if q.isVisible()],
           "\u25bc", GROUP_COLORS["move"])
    if not all(q.isVisible() for q in app.pets):
        _entry(sub, "Show everyone", lambda: app.set_all_visible(True), "\u25c9", GROUP_COLORS["react"])
    sub.addSeparator()
    for q in others:
        qm = StayOpenMenu(q.name + ("" if q.isVisible() else "   (hidden)"), sub)
        qm.setIcon(_initial_icon(q))
        sub.addMenu(qm)
        _entry(qm, "Poke", lambda qq=q: qq.poke(), ACTION["poke"].glyph, GROUP_COLORS["react"])
        _entry(qm, "Summon to cursor", lambda qq=q: app.summon(qq), ACTION["summon"].glyph, GROUP_COLORS["move"])
        _entry(qm, f"Talk with {pet.name}", lambda qq=q: app.start_chat(pet, qq), "\u2709", GROUP_COLORS["social"],
               enabled=bool(app.cfg["chat"]) and q.isVisible(),
               tip="" if app.cfg["chat"] else "Switch on Talk to each other first.")
        _entry(qm, "Reset position", lambda qq=q: qq.reset_position(), "\u21ba", GROUP_COLORS["settings"])
        qm.addSeparator()
        _entry(qm, "Make active", lambda qq=q: app.set_active(qq), "\u25ce", GROUP_COLORS["settings"],
               tip="Her status shows in the panel footer.")
        _visible_entry(qm, app, q)


# =============================================================================
#  Tray menu
# =============================================================================
def _fill_tray_menu(menu, app):
    """Rebuilt every time it opens, so the entries always reflect the current state."""
    menu.clear()
    _entry(menu, "Control Panel\u2026", app.show_panel, "\u2699", GROUP_COLORS["settings"])
    any_visible = any(p.isVisible() for p in app.pets)
    _entry(menu, "Hide all" if any_visible else "Show all", app.toggle_pet,
           "\u25cc" if any_visible else "\u25c9", GROUP_COLORS["danger" if any_visible else "react"])
    menu.addSeparator()

    targets = app.targets()
    who = targets[0].name if len(targets) == 1 else "everyone"
    quick = _submenu(menu, f"Actions on {who}", "\u26a1", GROUP_COLORS["react"])
    for key in ("poke", "pet", "cutin", "say", "summon", "ragdoll"):
        act = ACTION[key]
        _entry(quick, act.label, lambda a=act: [a.run(app, p) for p in app.targets() if p.isVisible()],
               act.glyph, GROUP_COLORS[act.group], tip=act.hint)

    people = _submenu(menu, "Characters", "\u263a", GROUP_COLORS["people"])
    for p in app.pets:
        sub = StayOpenMenu(p.name + ("" if p.isVisible() else "   (hidden)"), people)
        sub.setIcon(_initial_icon(p))
        people.addMenu(sub)
        for key in ("poke", "cutin", "summon", "ragdoll"):
            act = ACTION[key]
            _entry(sub, act.label_for(p), lambda a=act, pp=p: a.run(app, pp), act.glyph, GROUP_COLORS[act.group],
                   enabled=p.isVisible())
        sub.addSeparator()
        _entry(sub, "Make active", lambda pp=p: app.set_active(pp), "\u25ce", GROUP_COLORS["settings"])
        _visible_entry(sub, app, p)
    menu.addSeparator()
    _quit_entry(menu, app)


def build_tray_menu(app) -> StayOpenMenu:
    menu = StayOpenMenu()
    menu.aboutToShow.connect(lambda: _fill_tray_menu(menu, app))
    _fill_tray_menu(menu, app)             # also filled now, so the menu is never empty
    return menu
