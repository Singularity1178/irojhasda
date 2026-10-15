"""The tabbed control panel and its stylesheet."""
from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from .config import ANIM_KEYS, PRESETS


# =============================================================================
#  Control panel (tabs)
# =============================================================================
QSS = """
QWidget { font-family: 'Segoe UI','Noto Sans',sans-serif; font-size: 12px; color:#1d2b45; }
QWidget#root { background:#eef4fb; }
QTabWidget::pane { border:1px solid #c9daf0; border-radius:8px; background:white; top:-1px; }
QTabBar::tab { padding:7px 18px; background:#dbe8f7; border-top-left-radius:8px; border-top-right-radius:8px; margin-right:2px; color:#3a5a86; }
QTabBar::tab:selected { background:#128cff; color:white; font-weight:600; }
QPushButton { background:#128cff; color:white; border:none; border-radius:8px; padding:7px 12px; font-weight:600; }
QPushButton:hover { background:#3aa1ff; } QPushButton:pressed { background:#0b6fd0; }
QPushButton#alt { background:#dbe8f7; color:#1d4e89; } QPushButton#alt:hover { background:#c7ddf5; }
QSlider::groove:horizontal { height:6px; background:#d6e4f5; border-radius:3px; }
QSlider::sub-page:horizontal { background:#128cff; border-radius:3px; }
QSlider::handle:horizontal { background:white; border:2px solid #128cff; width:14px; margin:-6px 0; border-radius:8px; }
QComboBox { border:1px solid #bcd3ee; border-radius:6px; padding:4px 8px; background:white; }
QMenu { background:white; border:1px solid #bcd3ee; padding:4px; }
QMenu::item { padding:6px 24px; border-radius:4px; } QMenu::item:selected { background:#128cff; color:white; }
QMenu::separator { height:1px; background:#dbe8f7; margin:4px 8px; }
QLabel#title { font-size:16px; font-weight:700; color:white; }
QLabel#status { font-family:Consolas,monospace; background:#f2f7fd; border:1px solid #d3e3f6; border-radius:6px; padding:6px; }
"""

class Panel(QtWidgets.QWidget):
    def __init__(self, A):
        super().__init__()
        self.A = A; self.ctrl = {}
        self.setObjectName("root"); self.setWindowTitle("Desktop Pets - Control Panel"); self.resize(520, 660)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(10, 10, 10, 10)
        head = QtWidgets.QFrame(); head.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0b4fb3,stop:1 #35b6ff); border-radius:10px;")
        hl = QtWidgets.QHBoxLayout(head)
        self.title = QtWidgets.QLabel("Desktop Pets"); self.title.setObjectName("title"); hl.addWidget(self.title)
        lay.addWidget(head)
        tabs = QtWidgets.QTabWidget(); lay.addWidget(tabs, 1)
        tabs.addTab(self.tab_chars(), "Characters"); tabs.addTab(self.tab_pet(), "Pet")
        tabs.addTab(self.tab_shader(), "Shader"); tabs.addTab(self.tab_interact(), "Interact")
        tabs.addTab(self.tab_help(), "Help")
        self.status = QtWidgets.QLabel(""); self.status.setObjectName("status"); lay.addWidget(self.status)

    # ---- widgets helpers ----
    def check(self, lay, label, key):
        cb = QtWidgets.QCheckBox(label); cb.setChecked(bool(self.A.cfg[key]))
        cb.toggled.connect(lambda v, k=key: self.A.set(k, v)); lay.addWidget(cb); self.ctrl[key] = ("check", cb)

    def slider(self, lay, label, key, lo, hi, mult, fmt="{:.2f}"):
        row = QtWidgets.QHBoxLayout(); lb = QtWidgets.QLabel(label); lb.setMinimumWidth(135)
        sl = QtWidgets.QSlider(Qt.Orientation.Horizontal); sl.setRange(int(lo * mult), int(hi * mult))
        sl.setValue(int(self.A.cfg[key] * mult)); vl = QtWidgets.QLabel(fmt.format(self.A.cfg[key])); vl.setMinimumWidth(46)
        def ch(v, k=key, m=mult, vl=vl, fmt=fmt): vl.setText(fmt.format(v / m)); self.A.set(k, v / m)
        sl.valueChanged.connect(ch)
        row.addWidget(lb); row.addWidget(sl, 1); row.addWidget(vl); lay.addLayout(row)
        self.ctrl[key] = ("slider", sl, mult, vl, fmt)

    def button(self, text, fn, alt=False):
        # clicked(bool) into a plain callable: Qt fills any parameter it can, so a
        # one-argument lambda would be handed `False` and blow up. Take no args.
        if callable(fn):
            def go(_=None, _f=fn):
                _f()
            fn = go
        b = QtWidgets.QPushButton(text); b.clicked.connect(fn)
        if alt: b.setObjectName("alt")
        return b

    def refresh(self):
        for key, c in self.ctrl.items():
            v = self.A.cfg[key]
            if c[0] == "check":
                c[1].blockSignals(True); c[1].setChecked(bool(v)); c[1].blockSignals(False)
            else:
                c[1].blockSignals(True); c[1].setValue(int(v * c[2])); c[1].blockSignals(False); c[3].setText(c[4].format(v))
        self.preset_box.blockSignals(True); self.preset_box.setCurrentText(self.A.cfg["preset"]); self.preset_box.blockSignals(False)

    # ---- tabs ----
    def tab_chars(self):
        w = QtWidgets.QWidget(); l = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout(); row.addWidget(QtWidgets.QLabel("Screen"))
        self.screen_box = QtWidgets.QComboBox()
        for i, s in enumerate(self.A.qapp.screens()):
            g = s.availableGeometry()
            self.screen_box.addItem(f"{i}: {s.name()}  ({g.width()}x{g.height()})", i)
        self.screen_box.addItem("Cursor screen at startup", "cursor")
        self.screen_box.addItem("Primary screen", "primary")
        cur = self.A.cfg.get("screen", "cursor")
        idx = self.screen_box.findData(cur)
        self.screen_box.setCurrentIndex(idx if idx >= 0 else self.screen_box.count() - 2)
        self.screen_box.currentIndexChanged.connect(self.on_screen_changed)
        row.addWidget(self.screen_box, 1)
        bt = self.button("Apply", self.on_screen_apply, True); row.addWidget(bt)
        l.addLayout(row)
        self.screen_note = QtWidgets.QLabel(""); self.screen_note.setWordWrap(True); l.addWidget(self.screen_note)
        self.sync_screen_note()
        l.addSpacing(6)
        row = QtWidgets.QHBoxLayout(); row.addWidget(QtWidgets.QLabel("Act on"))
        self.who_box = QtWidgets.QComboBox()
        self.who_box.addItems(["All characters"] + [p.name for p in self.A.pets])
        self.who_box.currentIndexChanged.connect(lambda _i: self.A.set_target(self.who_box.currentIndex()))
        row.addWidget(self.who_box, 1); l.addLayout(row)
        row = QtWidgets.QHBoxLayout(); row.addWidget(QtWidgets.QLabel("Selected"))
        self.sel_box = QtWidgets.QComboBox()
        self.sel_box.addItems([p.name for p in self.A.pets] or ["-"])
        self.sel_box.currentIndexChanged.connect(lambda i: self.A.set_active_by_index(max(0, i)))
        row.addWidget(self.sel_box, 1); l.addLayout(row)
        l.addSpacing(6)
        self.char_rows = []
        for p in self.A.pets:
            box = QtWidgets.QGroupBox(p.name); g = QtWidgets.QGridLayout(box)
            cbs = QtWidgets.QCheckBox("visible"); cbs.setChecked(p.isVisible())
            cbs.toggled.connect(lambda v, pp=p: self.A.set_pet_visible(pp, v))
            g.addWidget(cbs, 0, 0)
            g.addWidget(self.button("Reset pos", lambda pp=p: pp.reset_position(), True), 0, 1)
            g.addWidget(self.button("Summon", lambda pp=p: self.A.summon(pp), True), 0, 2)
            g.addWidget(self.button("Poke", lambda pp=p: pp.poke(), True), 0, 3)
            g.addWidget(self.button("Say", lambda pp=p: pp.say(pp.line("idle", "poke")), True), 0, 4)
            g.addWidget(self.button("Spin", lambda pp=p: pp.spin(), True), 0, 5)
            l.addWidget(box)
            self.char_rows.append((p, cbs))
        l.addWidget(self.button("Show all", lambda: self.A.set_all_visible(True)))
        l.addWidget(self.button("Hide all", lambda: self.A.set_all_visible(False)))
        note = QtWidgets.QLabel("Tip: if no characters appear at startup, something was left "
                                "hidden last time. Press <b>Show all</b>.")
        note.setWordWrap(True); l.addWidget(note)
        l.addStretch(1); return w

    def sync_char_rows(self):
        for p, cb in getattr(self, "char_rows", ()):
            cb.blockSignals(True); cb.setChecked(p.isVisible()); cb.blockSignals(False)

    def sync_screen_note(self):
        if getattr(self, "screen_note", None):
            g = self.A.resolve_screen()
            self.screen_note.setText(f"All characters are locked to screen {self.A.screen_label()}  "
                                     f"(x {g.left()}..{g.right()}, y {g.top()}..{g.bottom()}).")

    def on_screen_changed(self, _i): self.sync_screen_note()

    def on_screen_apply(self):
        self.A.set_screen(self.screen_box.currentData())
        self.sync_screen_note()

    def tab_pet(self):
        w = QtWidgets.QWidget(); l = QtWidgets.QVBoxLayout(w)
        self.slider(l, "Size", "scale", 0.5, 2.5, 100)
        self.slider(l, "Walk speed", "walk_speed", 20, 220, 1, "{:.0f}")
        self.slider(l, "Lean forward / back (deg)", "pitch_offset", -90, 90, 1, "{:.0f}")
        self.slider(l, "Lean left / right (deg)", "tilt_offset", -40, 40, 1, "{:.0f}")
        self.check(l, "Hand-rotated students turn back to face the desktop", "rotation_return")
        self.slider(l, "Turn-back delay (s)", "rotation_return_delay", 0.0, 10.0, 10, "{:.1f}")
        self.check(l, "Idle students look around (turn left / right, then back)", "look_around")
        self.slider(l, "Look-around chance", "look_around_chance", 0.0, 1.0, 100, "{:.2f}")
        l.addSpacing(6)
        for label, key in (("Wander around on her own", "wander"), ("Look at my cursor", "look_at_cursor"),
                           ("Follow my cursor (walk to it)", "follow_cursor"),
                           ("Perch / jump on top of my windows (Windows only)", "perch"),
                           ("Speech bubbles", "speech"), ("Particles (hearts / sparkles)", "particles"),
                           ("Blue Archive VFX (flashes, sparks, beams, rings)", "ba_vfx"),
                           ("Emote balloons (! ? \u2665 \u266a ...)", "emotes"),
                           ("Damage numbers / CRITICAL / MISS / BLOCK", "damage_numbers"),
                           ("Always on top", "always_on_top"), ("Click-through transparent areas", "click_through")):
            self.check(l, label, key)
        l.addSpacing(6)
        l.addWidget(QtWidgets.QLabel("Together"))
        self.check(l, "Look at other characters", "peer_look")
        self.slider(l, "How often they glance over", "peer_look_rate", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Cursor notice range (widths)", "cursor_gaze_range", 0.5, 8.0, 10, "{:.1f}")
        self.slider(l, "Still-noticed when far", "cursor_gaze_far", 0.0, 1.0, 100, "{:.2f}")
        self.check(l, "Talk to each other", "chat")
        self.slider(l, "Chattiness", "chat_rate", 0.0, 1.0, 100, "{:.2f}")
        self.check(l, "Walk over before talking", "chat_meetup")
        row = QtWidgets.QHBoxLayout(); row.addWidget(QtWidgets.QLabel("Frame rate"))
        self.fps_box = QtWidgets.QComboBox(); self.fps_box.addItems(["30", "60"]); self.fps_box.setCurrentText(str(int(self.A.cfg["fps"])))
        self.fps_box.currentTextChanged.connect(lambda s: self.A.set("fps", int(s))); row.addWidget(self.fps_box); row.addStretch(1); l.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.button("Reset lean", lambda: (self.A.set("pitch_offset", 0.0), self.A.set("tilt_offset", 0.0, refresh=True)), True))
        row.addWidget(self.button("Reset positions", lambda: [p.reset_position() for p in self.A.pets], True))
        row.addWidget(self.button("Hide to tray", lambda: self.A.toggle_pet(), True)); l.addLayout(row)
        l.addStretch(1); return w

    def tab_shader(self):
        w = QtWidgets.QWidget(); l = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout(); row.addWidget(QtWidgets.QLabel("Preset"))
        self.preset_box = QtWidgets.QComboBox(); self.preset_box.addItems(list(PRESETS)); self.preset_box.setCurrentText(self.A.cfg["preset"])
        self.preset_box.currentTextChanged.connect(self.A.apply_preset); row.addWidget(self.preset_box, 1); l.addLayout(row)
        self.slider(l, "Shadow threshold", "toon_threshold", 0.05, 0.95, 100)
        self.slider(l, "Shadow softness", "toon_softness", 0.002, 0.30, 1000, "{:.3f}")
        self.slider(l, "Shadow strength", "shadow_strength", 0.0, 1.0, 100)
        self.slider(l, "Deep shadow band", "deep_shadow", 0.0, 1.0, 100)
        self.slider(l, "Light intensity", "exposure", 0.4, 1.5, 100)
        self.slider(l, "Rim light", "rim", 0.0, 1.5, 100)
        self.slider(l, "Specular tick", "spec", 0.0, 1.0, 100)
        self.slider(l, "Saturation", "saturation", 0.4, 1.7, 100)
        self.slider(l, "Outline width (px)", "outline_px", 0.0, 5.0, 100)
        self.slider(l, "Outline darkness", "outline_dark", 0.0, 1.0, 100)
        self.check(l, "Eyes through bangs (experimental)", "eyes_through_bangs")
        self.check(l, "Light follows my cursor (3D point light)", "light_follow")
        self.slider(l, "Manual light azimuth", "light_az", -180, 180, 1, "{:.0f}")
        self.slider(l, "Manual light elevation", "light_el", -20, 85, 1, "{:.0f}")
        l.addStretch(1); return w

    def tab_interact(self):
        w = QtWidgets.QWidget(); l = QtWidgets.QVBoxLayout(w)
        note = QtWidgets.QLabel("Applies to the target chosen on the Characters tab (All = everyone).")
        note.setWordWrap(True); l.addWidget(note)
        grid = QtWidgets.QGridLayout()
        def run(fn):
            self.A.each(fn)
        items = [("Poke  (Cafe_Reaction)", lambda p: p.poke()), ("Pet  (patting)", lambda p: p.pet()),
                 ("EX Cut-in  (Exs_Cutin)", lambda p: p.do_cutin()), ("Tactical Start", lambda p: p.do_tactical()),
                 ("Spin 360° (3D)", lambda p: p.spin()), ("Launch!", lambda p: p.launch()),
                 ("Ragdoll  (go limp)", lambda p: p.start_ragdoll(kick=False)),
                 ("Cafe_Idle", lambda p: p.play_anim("idle")), ("Cafe_Walk", lambda p: p.play_anim("walk")),
                 ("Formation_Idle", lambda p: p.play_anim("alert")), ("Formation_Pickup", lambda p: p.play_anim("pickup"))]
        for i, (t, fn) in enumerate(items):
            grid.addWidget(self.button(t, lambda f=fn: run(f), alt=i >= 7), i // 2, i % 2)
        grid.addWidget(self.button("Shoot a student", lambda: run(lambda p: p.try_shoot(force=True))), 6, 0)
        grid.addWidget(self.button("Say something", lambda: self.A.each(lambda p: p.say(p.line("idle", "poke")))), 6, 1)
        grid.addWidget(self.button("Summon to cursor", lambda: self.A.summon()), 7, 0)
        grid.addWidget(self.button("Look around", lambda: run(lambda p: p.look_around())), 7, 1)
        l.addLayout(grid)
        l.addSpacing(8)
        l.addWidget(QtWidgets.QLabel("Shooting"))
        self.check(l, "Random shooting events (students shoot each other)", "shoot_events")
        self.slider(l, "Event chance", "shoot_chance", 0.0, 0.6, 100, "{:.2f}")
        self.slider(l, "Hit chance", "shoot_hit_chance", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Stray bullet hits one in the way", "shoot_intercept_chance", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Ragdoll on hit", "shoot_ragdoll_chance", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Armed target shoots back (base odds)", "shoot_retaliate_chance", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Armed target runs away (base odds)", "shoot_flee_chance", 0.0, 1.0, 100, "{:.2f}")
        self.slider(l, "Kneel behind a student for cover", "shoot_cover_chance", 0.0, 1.0, 100, "{:.2f}")
        l.addSpacing(8)
        l.addWidget(QtWidgets.QLabel("Together"))
        h = QtWidgets.QHBoxLayout()
        h.addWidget(self.button("Start a conversation", lambda: self.A.start_chat()))
        h.addWidget(self.button("Introduce everyone", self.A.introduce_all))
        l.addLayout(h)
        h2 = QtWidgets.QHBoxLayout()
        h2.addWidget(self.button("Stop all conversations", self.A.end_all_chats, True))
        l.addLayout(h2)
        self.chat_note = QtWidgets.QLabel(""); self.chat_note.setWordWrap(True); l.addWidget(self.chat_note)
        l.addSpacing(8)
        l.addWidget(QtWidgets.QLabel("Blow"))
        self.check(l, "Blow mode: double-middle-click gusts wind from cursor", "blow_mode")
        self.slider(l, "Gust strength", "blow_strength", 0.2, 2.5, 100, "{:.2f}")
        h3 = QtWidgets.QHBoxLayout()
        h3.addWidget(self.button("Gust at cursor now", lambda: self.A.spawn_gust()))
        l.addLayout(h3)
        l.addStretch(1); return w

    def tab_help(self):
        tb = QtWidgets.QTextBrowser(); tb.setOpenExternalLinks(True)
        tb.setHtml("""<h3>Characters</h3><p>Every <code>.glb</code> file in the <code>model</code> folder becomes its own character with its own
        window, animations, walk cycle and dialogue. Drop another <code>.glb</code> in and restart to add more.</p>
        <h3>One screen only</h3><p>All of them are locked to a single monitor - they spawn on it, walk on it, only jump onto
        windows that sit on it, and can't be dragged off it. Pick which monitor on the Characters tab.</p>
        <h3>Together</h3><p>With more than one character they notice each other:</p><ul>
        <li>They <b>glance at each other</b> between idle animations. Move your cursor near one and she looks at you instead.</li>
        <li>They start <b>conversations</b> on their own - different topics, a few lines each, and whoever is
        listening faces the speaker and reacts. Poke one and a nearby character comments on it.</li>
        <li>When two of them walk past each other they say hello.</li></ul>
        <p>All of it is on the Pet tab (<i>Together</i>) and the Interact tab.</p>
        <h3>Controls</h3><ul>
        <li><b>Move cursor</b> - head and body follow it when it is <i>near</i>; further away
        they mostly glance at a friend or off into the room instead
        (<i>Cursor notice range</i> / <i>Still-noticed when far</i> on the Pet tab).</li>
        <li><b>Click</b> - poke. <b>Double-click</b> - EX cut-in.</li>
        <li><b>Drag</b> - pick up (Formation_Pickup). Release while moving to <b>throw</b>.</li>
<li><b>Right-click &rarr; Ragdoll</b> - she goes limp: tumbles, bounces off the floor and
your window title bars, flops about, lies there a few seconds, then gets back up on her own
(turn <i>Ragdoll: auto get-up</i> off to keep her down). While she's limp, <b>click</b> shoves her
away from the cursor and you can still pick her up and throw her.</li>
<li><b>Ctrl + 1</b> - works from <i>any</i> window, including ones you are typing in:
whatever character is under the cursor goes limp, with a short sound to confirm the hit
(press it again to stand her back up). On bare desktop it does nothing at all. Note that
Ctrl+1 is swallowed while this is running, so the app underneath will not act on it
either.</li>
        <li><b>Double-middle-click</b> - gust of wind from the cursor (needs <i>Blow mode</i> on the Interact tab). Hair and clothes flutter - the body stays put.</li>
        <li><b>Stroke the cursor back and forth over her head</b> - petting. She bows as you go.</li>
        <li><b>Wheel</b> - resize everyone. <b>Ctrl+wheel / middle-drag / Ctrl+drag</b> - turn ONLY that student; she eases back to facing the desktop a couple of seconds after you let go (Pet tab). <b>Shift+wheel</b> - turn EVERY student the same way; they all ease back by themselves. Idle students also occasionally <i>look around</i> by themselves.</li>
        <li><b>Right-click a character</b> - its own quick menu. Tray icon: show/hide, panel, quit.</li></ul>
        <p><b>Click-through</b> is a per-pixel Windows hit-test; on Linux/macOS it falls back to a mask region.</p>
        <h3>Windows</h3><p>With <i>Perch</i> on they jump up onto your open windows, walk along their title bars,
        ride them while you move them, and fall if you close or minimise them.</p>
        <h3>Tips</h3><p>Run with <code>--dump</code> to print
        bone / animation / material names for every model.</p>""")
        return tb

    def update_status(self):
        p = self.A.active or (self.A.pets[0] if self.A.pets else None)
        if p is None: return
        n = sum(1 for q in self.A.pets if q.isVisible())
        short = self.A.dialogue.display_name
        if p.gaze_peer is not None and p.gaze_left > 0: looking = f"looking at {short(p.gaze_peer.name)}"
        elif not p.cur_look: looking = "looking off into the room"
        else: looking = "looking at cursor"
        chat = ""
        if p.busy_chat():
            if p.meet_target is not None: chat = f"walking over to {short(p.meet_target.name)}"
            elif p.chat_with is not None:
                chat = f"{self.A.dialogue.topic_label(p.chat_topic)} with {short(p.chat_with.name)}"
        self.status.setText(f"{n} character(s) | screen {self.A.screen_label()} | fps: {self.A.fps:4.0f}\n"
                            f"{p.name}: state {p.state:<6} anim: {ANIM_KEYS[p.anim_key][0]:<17} "
                            f"pos: {int(p.px)},{int(p.py)}  grounded: {p.grounded}  on-window: {p.support is not None}\n"
                            f"{looking}" + (f"  |  {chat}" if chat else ""))
        if getattr(self, "chat_note", None):
            if not self.A.cfg["chat"] or n < 2:
                self.chat_note.setText("Needs 2+ visible characters and <i>Talk to each other</i> on.")
            else:
                self.chat_note.setText(f"Topics: {self.A.dialogue.topic_label_text()}.")
