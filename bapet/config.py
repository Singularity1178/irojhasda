"""Settings and tunables: paths, DEFAULTS, PRESETS, animation keys, hold-physics and walking constants."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt


HERE = Path(__file__).resolve().parent.parent   # the project folder (model/, dialogue/, profiles live here)

SETTINGS_PATH = HERE / "multi_single_screen_pet_ba_settings.json"   # its own settings file
MODEL_DIR = HERE / "model"          # every *.glb in here becomes a character
BASE_W, BASE_H = 380, 520
BAKE_FPS = 60

# Played when Ctrl+1 lands on a character, confirming the hit. Looked for next to
# this script first, then in sounds\, then as a plain path.
RAG_SOUND = "trimmed.mp3"
RAG_SOUND_VOLUME = 0.7

# key -> (animation name, loops?)
ANIM_KEYS = {
    "idle":     ("Cafe_Idle", True),
    "walk":     ("Cafe_Walk", True),
    "alert":    ("Formation_Idle", True),
    "react":    ("Cafe_Reaction", False),
    "pickup":   ("Formation_Pickup", False),
    "cutin":    ("Exs_Cutin", False),
    "tactical": ("Tactical_Start", False),
    "reload":   ("Normal_Reload", False),      # optional: Character leaves it out if the model has none
}

DEFAULTS = dict(
    scale=1.0, walk_speed=70.0, fps=30, always_on_top=True, wander=True,
    look_at_cursor=True, follow_cursor=False, perch=True, speech=True,
    particles=True, click_through=True, pos_x=None,
    ba_vfx=True,                 # Blue Archive effects: directional muzzle flashes, smoke, brass, hit sparks,
                                 #   per-weapon tracers / beams / explosions, landing rings, tap ripples
    emotes=True,                 # story-mode emoticon balloons over her head (! ? heart note sweat ...)
    damage_numbers=True,         # floating damage / CRITICAL / MISS / BLOCK text in fights
    rotation_return=True,        # a student turned by hand (Ctrl+wheel / rotate-drag) turns back to face the desktop
    rotation_return_delay=2.0,   # s after the last hand rotation before she turns back
    look_around=True,            # idle students now and then swivel left / right and come back
    look_around_chance=0.12,     # 0..1  chance a wander decision becomes a look-around
    pitch_offset=0.0,        # deg, lean forward/back (free 3D orientation, see render_frame)
    tilt_offset=0.0,         # deg, lean left/right (screen-plane roll)
    depth_roam=0.30,         # 0..1  chance a wander walk heads toward / away from you, not just sideways
    positions={},            # character name -> saved feet X
    hidden=[],               # character names the user turned off
    peer_look=True,          # occasionally look at another character
    peer_look_rate=0.35,     # 0..1  how often she glances over
    cursor_gaze_range=3.0,   # how many body-widths away the cursor still gets noticed
    cursor_gaze_far=0.10,    # 0..1  chance of still looking at it from far beyond that
    chat=True,               # characters talk to each other
    chat_rate=0.5,           # 0..1  chattiness
    chat_meetup=True,        # walk over before talking
    screen="cursor",         # "cursor" | "primary" | "0", "1", ...  (one screen only)
    preset="Blue Archive",
    toon_threshold=0.46, toon_softness=0.07, shadow_strength=0.62, exposure=1.0,
    deep_shadow=0.25, rim=0.45, spec=0.05, saturation=1.08, outline_px=1.5, outline_dark=0.34,
    eyes_through_bangs=False,   # C4: off by default, see Renderer.draw
    light_follow=False, light_az=-30.0, light_el=38.0,
    blow_mode=False,            # double-middle-click = gust of wind from cursor
    blow_strength=1.0,          # 0.2..2.5 gust power multiplier
    ragdoll_auto_getup=True,    # she stands back up by herself after lying still
    phys_gravity=1.0,           # ragdoll gravity x normal: 1 = normal, 0 = weightless, < 0 = falls UP (-1 = reversed).
                                #   With 0 or less nobody gets up by herself until gravity points down again.
    phys_grab_strength=1.0,     # 0.05..1  how firmly the cursor holds a limp student (1 = pinned to the cursor,
                                #   lower = she trails behind and sags, very low = too heavy to lift)
    phys_throw_strength=1.0,    # 0..2  x the speed cap a limp student keeps when you let go of her
    phys_getup_delay=3.0,       # s lying still before she gets up by herself (held = timer stays at 0)
    shoot_events=True,          # students now and then shoot each other
    shoot_chance=0.10,          # 0..1  chance that a wander decision becomes a shooting event
    shoot_hit_chance=0.75,      # 0..1  a shot lands at close/medium range (less at long range, and while
                                #       she flinches or is shaken: see aim_accuracy)
    shoot_ragdoll_chance=0.15,  # 0..1  a student who is hit is knocked down along the shot
                                #       (she is shot at until this happens, so keep it low)
    shoot_intercept_chance=0.55,  # 0..1  a student standing in the line of fire takes the bullet
    shoot_retaliate_chance=0.80,  # 0..1  starting odds that an armed student who is shot at shoots back
    shoot_flee_chance=0.15,       # 0..1  ...or runs away (whatever is left over: does nothing). These are
                                  #       only the BASE odds: being outnumbered / shaken / short of nerve
                                  #       raises the run, and a student with nowhere to run always fights
                                  #       (see react_odds). 0 here really does mean never.
    shoot_cover_chance=0.55,      # 0..1  a student with Kneel_Attack_* clips, starting a fight with another
                                  #       student standing nearby, kneels behind her and uses her as cover
                                  #       (see the COVER block). Nobody to hide behind = a normal fight.
    shoot_window_cover_chance=0.55,  # 0..1  a student with Stand_Attack_* clips, starting a fight with a
                                  #       window about her height standing on her ground between her and the
                                  #       opponent (a terminal on the taskbar, a small window on the one she
                                  #       stands on), stands behind it and uses it as cover (Stand_* clips).
    test_weapon="",             # Interact tab: pick a weapon and Ctrl + left click fires one round of it
                                #   from the middle of the screen at the cursor, holding to keep firing.
                                #   A bench for the per-weapon VFX; the round hits any student it crosses.
                                #   "" = off, and Ctrl + click then reaches the app underneath as usual.
    ragdoll_engine="3d",        # "3d" = fully 3D ragdoll (ragphys3d.py), "pymunk" = articulated 2D, "legacy" = the old rod
    ragdoll_3d_depth=0.35,      # 3D engine: how far into the screen a limp body may fall, x her height (the
                                #   half-depth of the slab; standing students always stay in its middle)
    ragdoll_3d_tone=0.5,        # 3D engine: muscle tone as she goes down. 0 = limp at once; higher = she
                                #   sags at the knees first and keeps a little stiffness a moment longer
    ragdoll_3d_iters=5,         # 3D engine: physics iterations = solver substeps per 1/60 s (1..10).
                                #   5 (300 Hz) is the tuned feel. Lower = less CPU / less lag with several
                                #   students down at once, but softer, slightly stretchier limbs on hard
                                #   hits. Applies live, even mid-fall.
    ragdoll_debug=False,        # draw the capsules, joints and window colliders over her
    anim_debug=False,           # TEST ONLY: write the clip / state / phase playing on each
                                #   character over her (pet_animdbg.py, --anim-debug,
                                #   run_anim_debug.bat). Off in normal use.
    ragdoll_edge_slam=True,     # slamming into a screen edge fast enough knocks her over
    ragdoll_edge_slam_speed=2400.0,   # px/s at scale 1.0 (x her scale) that counts as a slam
    ragdoll_self_collide=True,   # [v2] ON  # her own limbs collide with each other. Looks better (she
                                  # curls into a ball instead of lying flat with her arms
                                  # through her own torso) but roughly doubles the physics
                                  # cost: 4 ragdolls + 10 windows go 1.7 -> 3.5 ms/frame.
    ragdoll_window_scale=1.5,   # how much bigger a limp student's window gets, as a multiple of her
                                #   standing one (Physics page). A body on the floor reaches outside the
                                #   pose her window was sized for and used to be clipped by its edge;
                                #   the camera widens to match, so this is ONLY extra room around her
                                #   - she is drawn at the same size in the same place. 1.0 = off.
)

PRESETS = {
    "Blue Archive":   dict(toon_threshold=.46, toon_softness=.07,  shadow_strength=.62, exposure=1.0, deep_shadow=.25, rim=.45, spec=.05, saturation=1.08, outline_px=1.5, outline_dark=.34),
    "Soft Pastel":    dict(toon_threshold=.38, toon_softness=.14,  shadow_strength=.30, exposure=1.05, deep_shadow=.10, rim=.75, spec=.05, saturation=.95,  outline_px=1.1, outline_dark=.55),
    "Hard Cel":       dict(toon_threshold=.55, toon_softness=.006, shadow_strength=.85, exposure=1.0, deep_shadow=.35, rim=.35, spec=.30, saturation=1.20, outline_px=2.6, outline_dark=.15),
    "Night Patrol":   dict(toon_threshold=.52, toon_softness=.05,  shadow_strength=.90, exposure=.72, deep_shadow=.40, rim=1.10, spec=.20, saturation=.90, outline_px=2.0, outline_dark=.20),
    "Flat / Unshaded":dict(toon_threshold=.10, toon_softness=.05,  shadow_strength=.0,  exposure=1.0, deep_shadow=.0,  rim=.0,  spec=.0,  saturation=1.05, outline_px=1.5, outline_dark=.35),
}

# ------------------------------------------------------------------ dialogue
# Every word a pet can say lives in the dialogue package next to this file, so
# it can be edited without touching any Python here:
#
#   dialogue/engine.py          "give me a line for (character, event, states)"
#   dialogue/conversation.py    pet-to-pet talking
#   dialogue/system_watcher.py  what the computer is doing -> state tags
#   dialogue/data/*.json        the lines themselves
#
# Pet.line("poke") is the only thing the pet code needs to say something.
# ------------------------------------------------------------------ hold physics
# Test feature: while you hold / throw her, hair + coat + skirt + tie + limbs
# lag behind the window on damped springs, so she feels carried, not pasted
# onto the cursor. Purely procedural + additive: the baked clip still plays,
# we only add small post rotations (same mechanism as head look-at).
# Per-chain spring state lives on Rig, drive (window velocity) on Pet.
HOLD_JIGGLE_WORDS = ("hair", "coat", "skirt", "necktai", "necktie", "sleeve",
                      "rebon", "ribbon", "tail", "scarf", "tie", "ahoge")
HOLD_SKIP_WORDS = ("halo", "glow", "effect", "prop", "weapon", "fire", "book", "holster")
HOLD_DANGLE_WORDS = ("upperarm", "forearm", "thigh", "calf", "hand", "foot")
HOLD_GAIN = {"hair": 1.0, "cloth": 0.7, "tie": 0.9, "limb": 0.45}

# ------------------------------------------------------------------ wind gust
# Double-middle-click (with Blow mode on) bursts air out of the cursor in all
# directions. Each pet converts it to a radial push on the same hold springs
# the drag uses, so hair/coat/skirt flutter away from the cursor and settle.
GUST_DUR, GUST_RADIUS, GUST_SPEED = 0.9, 650.0, 2600.0
WIND_KINDS = ("hair", "cloth", "tie")  # gust bends these chains, never body/limbs

TWRAP = int(getattr(Qt.TextFlag.TextWordWrap, "value", Qt.TextFlag.TextWordWrap))

# ---- 3D walking --------------------------------------------------------------
# Her heading is a yaw about the vertical axis, 0 = facing you, +90 deg = facing
# screen right, -90 = left, 180 = facing away. She walks along her forward vector
# (sin h, cos h): the sine part is screen X, the cosine part is depth (toward /
# away from the camera). A desktop has no depth, so depth is shown as size: nearer
# = bigger, farther = smaller, about her feet.
WALK_TURN = 1.35            # rad  the three-quarter turn she takes for a plain left / right walk
WALK_Z_DEAD = 0.30          # |cos h| below this is a sideways walk, not a diagonal one
DEPTH_WALK_PX = 450.0       # walk px (at walk_speed, before scale) for one unit of depth
DEPTH_SCALE = 0.16          # size change at full depth: 1 +/- this
