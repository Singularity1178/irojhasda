"""What the UI offers, written as data.

The control panel (panel.py) and the right-click menu (ui_menu.py) are both *built from* this
file, so a setting or an action is described exactly once.

  Adding a setting      add one `Toggle(...)` / `Slider(...)` / `Choice(...)` line to a section
                        in PAGES below. It then shows up on its page, is found by the search
                        box, is greyed out when its `enabled` rule says so, and gets a
                        "reset to default" button for free. The key must exist in
                        config.DEFAULTS.
  Adding an action      add one `Action(...)` to ACTIONS. It appears on the Actions page and,
                        if you list it in ui_menu.py, in the right-click menu too.
  Adding a page         add a `Page(...)` to PAGES.

Nothing in here touches Qt, so it is safe to import anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .config import ANIM_KEYS
from .deps import HAVE_PYMUNK


# =============================================================================
#  Facts about a pet, for labels and status lines
# =============================================================================
STATE_WORDS = {
    "idle": "idle", "walk": "walking", "alert": "alert", "shot": "reacting",
    "fall": "airborne", "shoot": "shooting", "flee": "running away", "drag": "held",
}


def pet_state(p) -> tuple[str, str]:
    """(short text, tone) for what a character is doing right now. tone is 'ok' or 'warn'."""
    if getattr(p, "ragdoll", False): return "limp", "warn"
    if getattr(p, "dragging", False): return "held", "warn"
    state = getattr(p, "state", "idle")
    if state in ("shoot", "flee"): return STATE_WORDS[state], "warn"
    try:
        if p.busy_chat(): return "talking", "ok"
    except Exception:
        pass
    return STATE_WORDS.get(state, str(state)), "ok"


def has_weapon(p) -> bool:
    """A character with no attack animations has no weapon (see Pet.try_shoot)."""
    try:
        from .combat_data import attack_sets
        return bool(attack_sets(p.model))
    except Exception:
        return True          # cannot tell: do not grey anything out on a guess


def weapon_label(p) -> str:
    """'Assault Rifle', 'armed' or 'no weapon' - one short word for the cast list."""
    if not has_weapon(p): return "no weapon"
    try:
        w = p.weapon_type()
    except Exception:
        w = None
    return w if isinstance(w, str) and w else "armed"


# =============================================================================
#  Actions (one-shot buttons). Shared by the Actions page and the right-click menu.
# =============================================================================
@dataclass(frozen=True)
class Action:
    key: str
    label: str
    glyph: str                                   # one symbol, drawn in the menu badge / button
    group: str                                   # also the colour key in ui_theme.GROUP_COLORS
    run: Callable                                # run(app, pet); pet is None when scope == "app"
    hint: str = ""
    scope: str = "pet"                           # "pet": once per target - "app": once in total
    live_label: Optional[Callable] = None        # live_label(pet) -> str, for entries that flip
    unavailable: Optional[Callable] = None       # (app, pet) -> reason text, or None when fine

    def label_for(self, pet=None) -> str:
        if self.live_label is not None and pet is not None:
            try: return self.live_label(pet)
            except Exception: pass
        return self.label


def _ragdoll_toggle(app, p):
    p.rag_getup() if p.ragdoll else p.start_ragdoll(kick=False)


def _shoot_blocker(app, p):
    if not has_weapon(p): return "no weapon"
    try:
        if not p.shoot_targets(): return "nobody to shoot at"
    except Exception:
        pass
    return None


ANIM_LABELS = {
    "idle": "Idle", "walk": "Walk", "alert": "Alert stance", "react": "Reaction",
    "pickup": "Pick-up pose", "cutin": "EX cut-in clip", "tactical": "Tactical clip", "reload": "Reload",
}


def _anim_actions() -> list[Action]:
    out = []
    for key, (clip, _loops) in ANIM_KEYS.items():
        out.append(Action(
            f"anim_{key}", ANIM_LABELS.get(key, clip), "\u25b6", "anim",
            lambda app, p, k=key: p.play_anim(k), hint=f"Play the {clip} clip on its own.",
            unavailable=lambda app, p, k=key: None if p.clips.get(k) else "clip missing in this model"))
    return out


ACTIONS: list[Action] = [
    # --- react -------------------------------------------------------------
    Action("poke", "Poke", "\u25c9", "react", lambda a, p: p.poke(), "Cafe_Reaction - same as a click."),
    Action("pet", "Pet", "\u2665", "react", lambda a, p: p.pet(), "A head-pat: she bows and blushes."),
    Action("cutin", "EX Cut-in", "\u2605", "react", lambda a, p: p.do_cutin(), "Exs_Cutin plus the screen banner - same as a double-click."),
    Action("tactical", "Tactical Start", "\u2691", "react", lambda a, p: p.do_tactical(), "The Tactical_Start entrance."),
    Action("say", "Say something", "\u275d", "react", lambda a, p: p.say(p.line("idle", "poke")), "Show a speech bubble."),
    Action("look", "Look around", "\u25d0", "react", lambda a, p: p.look_around(), "Turn left and right, then back."),
    # --- move & physics ----------------------------------------------------
    Action("summon", "Summon to cursor", "\u25bc", "move", lambda a, p: a.summon(p), "Drop her at the mouse pointer."),
    Action("spin", "Spin 360\u00b0", "\u21bb", "move", lambda a, p: p.spin(), "A full 3D turn."),
    Action("launch", "Launch!", "\u25b2", "move", lambda a, p: p.launch(), "Throw her across the desktop."),
    Action("ragdoll", "Ragdoll / get up", "\u2935", "move", _ragdoll_toggle,
           "Go limp and tumble; use it again to stand up.",
           live_label=lambda p: "Get up" if p.ragdoll else "Ragdoll"),
    # --- combat ------------------------------------------------------------
    Action("shoot", "Shoot a student", "\u2694", "combat", lambda a, p: p.try_shoot(force=True),
           "Open fire on another student until she goes down.", unavailable=_shoot_blocker),
    # --- together (app level) ---------------------------------------------
    Action("chat", "Start a chat", "\u2709", "social", lambda a, p: a.start_chat(),
           "Two characters talk. Needs 2+ visible characters.", scope="app"),
    Action("intro", "Introduce everyone", "\u263a", "social", lambda a, p: a.introduce_all(),
           "Everyone says hi to the next one.", scope="app"),
    Action("hush", "Stop all chats", "\u25a0", "social", lambda a, p: a.end_all_chats(),
           "End every chat in progress.", scope="app"),
    # --- world -------------------------------------------------------------
    Action("gust", "Gust at cursor", "\u224b", "world", lambda a, p: a.spawn_gust(),
           "Blow hair and clothes away from the pointer.", scope="app"),
] + _anim_actions()

ACTION = {a.key: a for a in ACTIONS}


# =============================================================================
#  Settings schema
# =============================================================================
def on(key: str) -> Callable[[dict], bool]:
    """enabled-rule: the row is live only while cfg[key] is truthy."""
    return lambda cfg: bool(cfg.get(key))


def off(key: str) -> Callable[[dict], bool]:
    """enabled-rule: the row is live only while cfg[key] is falsy."""
    return lambda cfg: not cfg.get(key)


def is_(key: str, value) -> Callable[[dict], bool]:
    """enabled-rule: the row is live only while cfg[key] == value."""
    return lambda cfg: cfg.get(key) == value


@dataclass
class Toggle:
    key: str
    label: str
    hint: str = ""
    enabled: Optional[Callable] = None           # rule from on()/off()/is_(), or any f(cfg) -> bool
    tags: str = ""                               # extra words the search box should match


@dataclass
class Slider:
    key: str
    label: str
    lo: float
    hi: float
    mult: float = 100                            # slider integer = value * mult
    fmt: str = "{:.2f}"
    hint: str = ""
    enabled: Optional[Callable] = None
    show: float = 1.0                            # displayed number = value * show (100 for %)
    tags: str = ""


def pct(key, label, hint="", enabled=None, tags="") -> Slider:
    """A 0..1 chance shown as 0..100 %."""
    return Slider(key, label, 0.0, 1.0, 100, "{:.0f}%", hint, enabled, 100.0, tags)


def level(key, label, lo, hi, hint="", enabled=None, tags="") -> Slider:
    """A 0..1-ish amount shown as a percentage (1.0 = 100%). Used for the shader sliders."""
    return Slider(key, label, lo, hi, 100, "{:.0f}%", hint, enabled, 100.0, tags)


@dataclass
class Choice:
    key: str
    label: str
    options: Sequence[tuple]                     # (text, value) pairs
    hint: str = ""
    enabled: Optional[Callable] = None
    disabled: Sequence = ()                      # option values that cannot be picked right now
    tags: str = ""


@dataclass
class Btn:
    label: str
    run: Callable                                # run(panel)
    kind: str = "alt"                            # "primary" | "alt" | "danger"
    hint: str = ""


@dataclass
class Buttons:
    items: Sequence[Btn]
    columns: int = 3


@dataclass
class Actions:
    """A grid of Action buttons, picked by group (and optionally by key)."""
    group: str
    only: Optional[Sequence[str]] = None
    columns: int = 3


@dataclass
class Info:
    fn: Callable                                 # fn(panel) -> rich text
    live: bool = False                           # refresh on every status tick


@dataclass
class Custom:
    """A composite row defined in ui_rows.py (see ui_rows.CUSTOM_ROWS)."""
    name: str


@dataclass
class Section:
    title: str
    rows: list
    hint: str = ""
    collapsed: bool = False


@dataclass
class Page:
    key: str
    title: str
    glyph: str
    sections: list = field(default_factory=list)
    html: str = ""                               # a page that is just formatted text (Help)


# ---- live text used by Info rows --------------------------------------------
def _chat_note(P) -> str:
    n = sum(1 for q in P.A.pets if q.isVisible())
    if not P.A.cfg["chat"] or n < 2:
        return "Needs 2 or more visible characters and <b>Talk to each other</b> switched on."
    return f"Topics they can talk about: {P.A.dialogue.topic_label_text()}."


def _react_note(P) -> str:
    c = P.A.cfg
    fight, flee = float(c.get("shoot_retaliate_chance", 0)), float(c.get("shoot_flee_chance", 0))
    total = min(1.0, fight + flee)
    return (f"An armed student who is shot at reacts <b>{total:.0%}</b> of the time "
            f"(shoot back + run, capped at 100%) and does nothing otherwise. The situation then "
            f"decides the split: outnumbered or shaken students run more; with nowhere to run "
            f"she always fights.")


def _settings_path_note(P) -> str:
    from .config import SETTINGS_PATH
    return f"Saved automatically to <b>{SETTINGS_PATH.name}</b> next to the script."


# ---- the pages ---------------------------------------------------------------
PAGES: list[Page] = [
    Page("characters", "Characters", "\u263a", [
        Section("Screen", [Custom("screen")],
                "All characters live on one monitor: they spawn, walk and jump there."),
        Section("Cast", [
            Custom("hidden_banner"),
            Custom("cast"),
            Buttons([
                Btn("Show all", lambda P: P.A.set_all_visible(True), "primary"),
                Btn("Hide all", lambda P: P.A.set_all_visible(False)),
                Btn("Summon everyone", lambda P: [P.A.summon(p) for p in P.A.pets], hint="Bring every character to the cursor."),
                Btn("Reset positions", lambda P: [p.reset_position() for p in P.A.pets], hint="Put everyone back at the right edge."),
            ], columns=2),
        ], "Click a character's target button to aim the Actions page at just that one."),
    ]),

    Page("actions", "Actions", "\u26a1", [
        Section("React", [Actions("react")], "Quick reactions. They run on whoever is chosen in \u201cActions apply to\u201d above."),
        Section("Move & physics", [Actions("move", columns=2)]),
        Section("Play an animation", [Actions("anim", ("anim_idle", "anim_walk", "anim_alert", "anim_pickup", "anim_reload"))]),
        Section("Combat", [Actions("combat")]),
        Section("Together", [Actions("social", columns=2)], "These involve several characters, so they ignore the target."),
        Section("World", [Actions("world")]),
    ]),

    Page("behavior", "Behavior", "\u2699", [
        Section("Movement", [
            Toggle("wander", "Wander around", "Walks, idles and explores on her own."),
            Toggle("follow_cursor", "Follow my cursor", "Walks over to wherever the mouse is."),
            Toggle("perch", "Perch on my windows", "Jumps onto title bars, rides them, falls if you close them. Windows only.", tags="jump window"),
            Slider("walk_speed", "Walk speed", 20, 220, 1, "{:.0f} px/s", "Pixels per second at 100% size."),
            pct("depth_roam", "Depth roaming", "How often a walk heads toward or away from you instead of sideways.", on("wander")),
        ]),
        Section("Attention", [
            Toggle("look_at_cursor", "Look at my cursor", "Head and body turn to follow the pointer."),
            Slider("cursor_gaze_range", "Notice range", 0.5, 8.0, 10, "{:.1f}\u00d7", "In body widths. Closer than this she always looks at you.", on("look_at_cursor")),
            pct("cursor_gaze_far", "Notice from far away", "Chance of still looking at the cursor beyond that range.", on("look_at_cursor")),
        ]),
        Section("Idle motion", [
            Toggle("look_around", "Look around when idle", "Now and then she turns left and right, then back."),
            pct("look_around_chance", "How often", "Chance that a wander decision becomes a look-around.", on("look_around")),
            Toggle("rotation_return", "Turn back after I rotate her", "A student turned by hand eases back to face the desktop."),
            Slider("rotation_return_delay", "Turn-back delay", 0.0, 10.0, 10, "{:.1f} s", "Wait after you let go.", on("rotation_return")),
        ]),
        Section("Posture", [
            Slider("pitch_offset", "Lean forward / back", -90, 90, 1, "{:.0f}\u00b0"),
            Slider("tilt_offset", "Lean left / right", -40, 40, 1, "{:.0f}\u00b0"),
            Buttons([Btn("Reset lean", lambda P: (P.A.set("pitch_offset", 0.0), P.A.set("tilt_offset", 0.0, refresh=True)))], columns=1),
        ]),
    ]),

    Page("social", "Social", "\u2709", [
        Section("Noticing each other", [
            Toggle("peer_look", "Glance at each other", "Between idle animations they look at a nearby friend. Your cursor still wins when it is close."),
            pct("peer_look_rate", "How often", "", on("peer_look")),
        ]),
        Section("Conversations", [
            Toggle("chat", "Talk to each other", "They start chats on their own: topics, reactions, greetings."),
            pct("chat_rate", "Chattiness", "", on("chat")),
            Toggle("chat_meetup", "Walk over before talking", "", on("chat")),
            Info(_chat_note, live=True),
            Actions("social", columns=2),
        ]),
        Section("Speech & emotes", [
            Toggle("speech", "Speech bubbles", "Lines of dialogue above her head."),
            Toggle("emotes", "Emote balloons", "The ! ? \u2665 \u266a balloons from the cafe story mode."),
        ]),
    ]),

    Page("combat", "Combat", "\u2694", [
        Section("Shooting events", [
            Toggle("shoot_events", "Random shooting events", "Every so often a student opens fire on another until she goes down."),
            pct("shoot_chance", "Event frequency", "Chance that a wander decision becomes a fight.", on("shoot_events")),
        ]),
        Section("Accuracy & damage", [
            pct("shoot_hit_chance", "Hit chance", "At close and medium range; lower when far or flinching."),
            pct("shoot_intercept_chance", "Stray bullets hit bystanders", "A student standing in the line of fire takes the bullet."),
            pct("shoot_ragdoll_chance", "Knock-down on hit", "Chance a hit student goes limp. She is shot at until this happens, so keep it low."),
            Toggle("damage_numbers", "Damage numbers", "Floating damage / CRITICAL / MISS / BLOCK text."),
        ]),
        Section("When shot at", [
            pct("shoot_retaliate_chance", "Shoot back", "Base odds that an armed student returns fire."),
            pct("shoot_flee_chance", "Run away", "Base odds that she runs instead."),
            pct("shoot_cover_chance", "Take cover behind a student", "Kneel behind a nearby student and use her as a shield."),
            Info(_react_note, live=True),
        ], collapsed=False),
        Section("Weapon test gun", [Custom("gun")]),
    ]),

    Page("appearance", "Appearance", "\u2726", [
        Section("Size", [
            Slider("scale", "Character size", 0.5, 2.5, 100, "{:.0f}%", "The mouse wheel over a character resizes everyone too.", show=100.0),
        ]),
        Section("Style", [Custom("presets")], "Presets set every shading slider below at once."),
        Section("Toon shading", [
            level("toon_threshold", "Shadow threshold", 0.05, 0.95, "Where light turns to shadow."),
            Slider("toon_softness", "Shadow softness", 0.002, 0.30, 1000, "{:.3f}", "Low = hard cel edge, high = soft blend."),
            level("shadow_strength", "Shadow strength", 0.0, 1.0),
            level("deep_shadow", "Deep shadow band", 0.0, 1.0),
            level("exposure", "Light intensity", 0.4, 1.5),
            level("saturation", "Saturation", 0.4, 1.7),
            level("rim", "Rim light", 0.0, 1.5, "The bright edge on the shadow side."),
            level("spec", "Specular tick", 0.0, 1.0, "Small hard highlights."),
        ]),
        Section("Outline", [
            Slider("outline_px", "Outline width", 0.0, 5.0, 100, "{:.1f} px"),
            level("outline_dark", "Outline darkness", 0.0, 1.0),
        ]),
        Section("Lighting", [
            Toggle("light_follow", "Light follows my cursor", "A 3D point light that tracks the pointer."),
            Slider("light_az", "Light direction", -180, 180, 1, "{:.0f}\u00b0", "Left\u2013right angle of the fixed light.", off("light_follow"), tags="azimuth"),
            Slider("light_el", "Light height", -20, 85, 1, "{:.0f}\u00b0", "Up\u2013down angle of the fixed light.", off("light_follow"), tags="elevation"),
        ]),
        Section("Effects", [
            Toggle("ba_vfx", "Blue Archive effects", "Muzzle flashes, sparks, beams, landing rings, tap ripples.", tags="vfx"),
            Toggle("particles", "Particles", "Hearts and sparkles."),
            Toggle("eyes_through_bangs", "Eyes through bangs", "Experimental: draw her eyes over her fringe."),
        ]),
    ]),

    Page("physics", "Physics", "\u21af", [
        Section("Ragdoll", [
            Choice("ragdoll_engine", "Engine", [("Realistic 3D", "3d"), ("Articulated (pymunk)", "pymunk"),
                                                ("Simple rod (legacy)", "legacy")],
                   "Applies the next time someone goes limp. Realistic 3D lets her body fall into the depth "
                   "of the screen, with real joint limits." + ("" if HAVE_PYMUNK else " pymunk is not installed."),
                   disabled=() if HAVE_PYMUNK else ("pymunk",), tags="3d realistic depth"),
            Slider("ragdoll_3d_depth", "3D depth", 0.10, 1.00, 100, "{:.0f}%",
                   "How far into the screen a limp body may fall, as a share of her height. "
                   "Standing students always stay in the middle.", is_("ragdoll_engine", "3d"), 100.0),
            Slider("ragdoll_3d_tone", "Muscle tone", 0.0, 1.0, 100, "{:.0f}%",
                   "0% = limp the instant she goes down. Higher = she sags at the knees first.",
                   is_("ragdoll_engine", "3d"), 100.0),
            Slider("ragdoll_3d_iters", "Physics iterations", 1, 10, 1, "{:.0f} / frame",
                   "Solver steps per 1/60 s (5 = the tuned default). Lower it if ragdolls make "
                   "things lag: 2\u20133 roughly halves the cost, 1 is cheapest but limbs stretch on hard "
                   "hits. Higher = stiffer and more exact. The live cost shows in the status line.",
                   is_("ragdoll_engine", "3d"), tags="substeps lag performance speed cpu quality solver"),
            Toggle("ragdoll_auto_getup", "Stand back up by herself", "She gets up after lying still for a few seconds."),
            Toggle("ragdoll_self_collide", "Limbs collide with each other", "Looks better but roughly doubles physics cost.",
                   is_("ragdoll_engine", "pymunk")),
            Toggle("ragdoll_edge_slam", "Hard hits on a screen edge knock her over", "Thrown fast enough, she goes limp instead of bouncing."),
            Slider("ragdoll_edge_slam_speed", "Slam speed", 600, 6000, 0.01, "{:.0f} px/s", "Speed at 100% size that counts as a slam.", on("ragdoll_edge_slam")),
        ], "Right-click a character, or press Ctrl + 1 over her, to go limp."),
        Section("Wind", [
            Toggle("blow_mode", "Blow mode", "Double-middle-click gusts wind from the cursor: hair and clothes flutter."),
            Slider("blow_strength", "Gust strength", 0.2, 2.5, 100, "{:.2f}\u00d7", enabled=on("blow_mode")),
            Actions("world"),
        ]),
        Section("Debug", [
            Toggle("ragdoll_debug", "Draw ragdoll colliders", "Capsules, joints and window colliders over each character."),
        ], collapsed=True),
    ]),

    Page("system", "System", "\u2630", [
        Section("Window", [
            Toggle("always_on_top", "Always on top", "Keep the characters above your other windows."),
            Toggle("click_through", "Click through transparent areas", "Only her body catches clicks. Per-pixel on Windows, a mask elsewhere."),
        ]),
        Section("Performance", [
            Choice("fps", "Frame rate", [("30 fps", 30), ("60 fps", 60)], "60 is smoother; 30 is lighter on the GPU."),
        ]),
        Section("Settings", [
            Info(_settings_path_note),
            Buttons([
                Btn("Hide to tray", lambda P: P.A.toggle_pet(), "alt", "Hide every character; bring them back from the tray icon."),
                Btn("Reset all settings", lambda P: P.reset_defaults(), "danger", "Restore every option to its default. Screen, positions and hidden characters are kept."),
                Btn("Quit", lambda P: P.A.qapp.quit(), "danger"),
            ]),
        ]),
    ]),
]


# =============================================================================
#  Help page
# =============================================================================
def _key(text: str) -> str:
    return (f'<span style="background-color:#e8f1fc; color:#0b4a8f; font-weight:600;">'
            f'&nbsp;{text}&nbsp;</span>')


def _table(rows) -> str:
    body = "".join(
        f'<tr><td width="34%" valign="top">{k}</td><td valign="top">{v}</td></tr>' for k, v in rows)
    return f'<table width="100%" cellspacing="0" cellpadding="6">{body}</table>'


HELP_HTML = f"""
<h2 style="color:#0b4fb3;">Using Desktop Pets</h2>
<p>Every <code>.glb</code> in the <code>model</code> folder is its own character with its own window,
animations and dialogue. Drop another in and restart to add one. All of them stay on <b>one screen</b>
(Characters page).</p>

<h3>On a character</h3>
{_table([
    (_key("Click"), "Poke."),
    (_key("Double-click"), "EX cut-in."),
    (_key("Drag"), "Pick her up. Let go while moving to <b>throw</b>."),
    (_key("Stroke over her head"), "Petting: move the cursor back and forth. She bows as you go."),
    (_key("Right-click"), "Her quick menu: reactions, animations, quick settings, other characters."),
    (_key("Mouse wheel"), "Resize everyone."),
    (_key("Ctrl + wheel") + " " + _key("Middle-drag") + " " + _key("Ctrl + drag"),
     "Turn only that student. She eases back a moment after you let go (Behavior &rarr; Idle motion). "
     "Hold <b>Shift</b> when the drag starts to lean her sideways instead."),
    (_key("Shift + wheel"), "Turn every student at once."),
    (_key("Double-middle-click"), "A gust of wind from the cursor. Needs <i>Blow mode</i> (Physics page)."),
    (_key("Ctrl + left click"), "Fires the weapon picked under <i>Weapon test gun</i> (Combat page) from the middle "
     "of the screen to your cursor; hold to keep firing. With the gun on <i>Off</i> the click goes to the app underneath."),
    (_key("Click a limp student"), "Shoves her away from the cursor. You can still pick her up and throw her."),
])}

<h3>Keyboard</h3>
{_table([
    (_key("Ctrl + 1"), "Works over <i>any</i> window: whoever is under the cursor goes limp, with a short sound "
     "(press again to stand her up). Bare desktop does nothing. The app swallows this shortcut while it runs."),
    (_key("Ctrl + F"), "In this panel: jump to the search box. <b>Esc</b> clears the search, then closes the panel."),
])}

<h3>Together</h3>
<p>With two or more characters they glance at each other, start conversations, comment when you poke
one of them, and say hello when they walk past. Everything is under the <b>Social</b> page.</p>

<h3>Windows</h3>
<p>With <i>Perch on my windows</i> on they jump onto your open windows, walk along the title bars, ride
them while you move them, and fall if you close or minimise them.</p>

<h3>Good to know</h3>
<ul>
<li>The <b>search box</b> at the top finds any setting by name or description, e.g. <i>speed</i>,
<i>shadow</i>, <i>ragdoll</i>.</li>
<li>A small <b>&#8634;</b> beside a slider means it differs from the default; click it to reset that one.</li>
<li>Greyed-out rows depend on a switch above them being on.</li>
<li>Run the script with <code>--dump</code> to print every model's bones, animations and materials.</li>
<li>If nobody shows up at startup, someone was left hidden: Characters &rarr; <b>Show all</b>.</li>
</ul>
"""

PAGES.append(Page("help", "Help", "?", html=HELP_HTML))
