"""Iroha - the only student who brings her own tank to the desktop.

multi_single_screen_pet_ba.py looks for a module named after a model file
(`model/Iroha.glb` -> `iroha.py`, see load_profile in the main file) and reads
PROFILE out of it. A character without one keeps every default, so this file is
the only place that has to change to make the tank fit.

SHE IS AN ORDINARY STUDENT UNTIL SHE FIGHTS
    On foot she is exactly like everybody else: this file gives her no window of
    her own, no clip overrides and no scale, so she walks, idles, chats and is
    dragged around in a 380x520 window at the same size as the rest of the class.
    The tank is not in that state at all.

THE PROBLEM WITH SHOWING IT
    The tank is ordinary geometry inside her .glb, not a second model, so it is
    part of the bounding box the camera is fitted to. On foot she is 1.00 unit
    tall and the window is sized for exactly that; with the tank up the rig is
    2.22 units tall and 1.96 wide, with the gun reaching 4.0 units forward. A
    window sized for her body would crop the tracks off it, and a window sized
    for the tank would leave her standing two times too tall - so the ride state
    has to come with a window of its own. That is what the `ride` block below is:
    a second set of clips AND a second window, used only while she is fighting
    and for the reload she does from the seat once a fight is over.

      ride.window_scale    2.2, the ratio between the two poses (2.22 / 1.00):
                          any more and she is oversized, any less and she comes
                          out smaller than the class;
      ride.window_aspect   widen on top of that, for two reasons. A tank is far
                          wider than a student is tall - at the stock 380x520 the
                          tip of the barrel already lands ~3% outside the frame.
                          And she turns: a walk faces her WALK_TURN (77 degrees)
                          off front, which swings her 4.0-unit length ACROSS the
                          screen instead of into it. Measured over every clip and
                          every heading, 1.3 left her 50% too wide side-on; 2.0 is
                          the first value that contains her at all of them;
      ride.fit_clip        the riding pose the window is measured from, so there
                          is room for the whole thing (and her riding clips put
                          her pelvis 1.23 up, which a camera fitted to the raw
                          pose would frame as empty air).

    At --scale 0.5 that is an 836x572 window against everybody else's 190x260,
    and her body still covers 149 px against their 151 - she is in the tank, not
    bigger than them. Drop window_scale if that costs too much frame time - it is
    a GPU readback per pet per frame, and her riding window has ~10x the pixels
    of the others. window_aspect is much cheaper: it only widens the window, it
    does not make her any bigger.

HOW THE TRANSITION WORKS
    Her rig keys Tank_Move to 0.001 on every on-foot clip and to 1.0 on every
    riding one, and puts character_root at 1000 to put the scale back on her
    body. Two clips that disagree about bone scale like that cannot be blended -
    the main file hard-cuts between them on purpose, and so does this one, which
    is why you see her swap into the seat rather than glide into it. What IS
    faded is the tank: the main file works out which of her primitives belong to
    it (everything collapsed onto Tank_Move's origin while she is on foot) and
    draws them at rising opacity over `ride.fade` seconds, so the tank deploys
    around her instead of blinking in between two frames. Her window grows on the
    same frame; because the tank fills it, the swap is masked by the fade.

ATTACKS AND THE TANK SHELL
    `attack_clips` swaps her attack animations for the Tank_Normal_Attack_* set,
    and `bullet` makes what she fires a tank shell that always ragdolls whoever it
    hits. Both only ever play inside the ride state, which is why they are safe to
    leave as they are: the main file drives a tank clip and the ride state
    together. The main file only reads these keys; all the values live here.
"""

PROFILE = dict(
    # --- on foot: nothing to say, she is a normal student -------------------------
    # Only the reload is named, and only because she has no Normal_Reload: without
    # this she logs a warning and reloads standing in Formation_Idle anyway.
    anim={"reload": "Formation_Idle"},

    # --- riding: her tank, and only while she is fighting ------------------------
    ride=dict(
        # Her model ships a whole second animation set for riding. Everything not
        # listed here keeps the on-foot clip from the `anim` block above - the
        # looping flag still comes from ANIM_KEYS in the main file, so only the
        # clip name is replaced.
        clips={
            "idle":   "SM015601_Riding_Idle",       # sitting in the hatch
            "walk":   "SM015601_Riding_Ing",        # driving
            "alert":  "SM015601_Riding_Idle",       # combat idle
            "reload": "SM015601_Riding_Reload",     # loading a shell
            "react":  "SM015601_Riding_Panic",      # hit on the tank
        },
        # pickup / cutin / tactical are deliberately left out: those all stow the
        # tank first (they are not combat states), so a riding version of them
        # would never play.
        window_scale=2.2,
        window_aspect=2.0,
        fit_clip="SM015601_Riding_Idle",
        fade=0.6,     # seconds the tank takes to deploy / stow
    ),

    # --- textures her own file is missing ------------------------------------------------
    # Iroha.glb's tank hull material CH0156_Tank_01 has no baseColorTexture at
    # all, so it draws flat white. The real 512x512 texture - the hull paint
    # with her crest and the crates stowed on the back - is in other_models/,
    # which is where Blue Archive's separately exported, separately rigged tank
    # sits: the same asset, and the only copy the export got right. Paths in a
    # profile are relative to multi_single_screen_pet_ba.py, not to whatever
    # directory you happen to launch from.
    #
    # The fragment matches both tank primitives on purpose: in Iroha.glb the
    # mesh CH0156_Tank carries two primitives over the SAME vertices with two
    # different materials, and the second one (CH0164_Tank_02, a near-blank
    # 128x128 plate that is a separate small mesh in the good file) is drawn on
    # top of the first. Giving both the hull texture makes them agree; the
    # result is the hull drawn twice, which looks identical to drawing it once.
    textures={
        "ch0156_tank": {"glb": "other_models/toramaru_rigged__blue_archive.glb",
                        "image": 0,
                        # V flipped, and this is the whole trick. The character
                        # export writes this asset's UVs upside down relative to
                        # the standalone tank: on 93% of the hull's vertices
                        # v_here == 1 - v_there (u agrees). Without the flip the
                        # atlas lands the wrong way up, which is what was
                        # missing the wheel and track shading and dropping a
                        # brown crate panel onto the barrel.
                        "flip_v": True},
    },

    # --- being shot at -----------------------------------------------------------
    # The tank is armour: while she is riding it, a bullet that reaches her never knocks
    # her down (0% ragdoll, whatever the panel's "Ragdoll on hit" slider says). On foot
    # this override is ignored and she ragdolls at the normal panel rate. A student who is
    # shooting at her gives up after 1.5-3 s, says a line, and goes for somebody else.
    shot_ragdoll_chance=0.0,
    shot_give_up=(1.5, 3.0),
    hit_lines=["*clang* The armor held!", "Tank's fine! Is that all you've got?",
               "That tickles! Tanks don't ragdoll!", "Direct hit? Barely a scratch!"],
    give_up_lines=["It's a tank... my bullets just bounce off!", "Forget it, that armor is too thick!",
                   "This is pointless against Iroha's tank!", "Okay, okay, I can't scratch that thing!"],

    # --- how she attacks ---------------------------------------------------------
    # The main file only recognises <Normal|Stand|Kneel>_Attack_* clips, and skips
    # anything with a Tank_ prefix on purpose, so her tank clips would never be
    # picked up by name. This hands them over directly: one stance, "tank", so
    # every fight she is in (shooting or retaliating) plays Start -> Ing (once per
    # shell, back to back) -> End. Start and End are optional; Ing is required.
    # If one of these names is wrong, the console prints "attack clip ... not found"
    # at startup - run with --dump to list the real clip names.
    attack_clips={
        "tank": {"start": "Tank_Normal_Attack_Start",
                 "ing":   "Tank_Normal_Attack_Ing",
                 "end":   "Tank_Normal_Attack_End"},
    },

    # --- her tank shell ------------------------------------------------------------
    # Every shot she fires is this instead of a rifle bullet. A shell that lands
    # ragdolls the student 100% of the time (ignoring the panel's "Ragdoll on hit"
    # slider) and sends her flying harder than a normal knock. It can still miss, be
    # dodged by a runner, or hit someone standing in its path - "100%" is the chance
    # once it HITS. Her ammo stats still come from combat_index.json.
    bullet=dict(
        ragdoll_chance=1.0,
        knock=1.6,              # x the normal knock-back speed
        speed=3000.0,           # px/s, slower and heavier than the 4200 of a rifle round
        color=(255, 120, 40),   # glow around the shell
        width=9.0,              # fat tracer; the shell nose scales with it
        trail=120.0,
        impact_size=2.4,        # bigger explosion sparks
        muzzle_flash=2,         # draw the flash this many times (overlaps = brighter)
        # Name fragment of the bone the shell leaves from. Unset = the model's
        # "muzzle" bone, else her right hand - and she has neither: her model has
        # no muzzle bone at all, so an unset value fires the shell out of her fist
        # while she is sitting in a tank. bone_tank_barrel is the gun.
        muzzle_bone="barrel",
        # Splash: the shell explodes, and every student inside the blast also takes it
        # (damage number, ragdoll roll, knock away from the centre; a running student
        # cannot dodge a blast). The reach is the drawn shockwave ring: vfx.explosion_radius
        # of the explosion size impact_size gives (216 * 1.32 = ~285 px here).
        # splash_radius multiplies that (1.0 = exactly the ring); splash=False turns it off.
        splash=True,
        splash_radius=1.0,
    ),
)