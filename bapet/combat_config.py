"""Shooting and combat-AI tunables (ranges, ammo, nerve, flee, cover) and the shooting dialogue lines."""
from __future__ import annotations



# ------------------------------------------------------------------- shooting
# A "shoot" event plays the character's own attack clips (ATTACK_ANIMATIONS.md):
#     Start (once) -> Ing (once per shot, repeated back to back) -> End (once) -> idle
# The shooter keeps firing at the same student until that student ragdolls. The *_Delay
# clip is deliberately never played, so there is no pause between shots.
# Characters with no attack clips (the cafe-only models) raise Formation_Idle and
# fire from that pose instead, so they can still take part.
SHOOT_STANCE_WEIGHT = {"normal": 3.0, "stand": 1.0, "kneel": 1.0}   # which stance she picks

SHOOT_FIRE_FRAC = 0.40         # the shot leaves this far into each Ing clip
SHOOT_BULLET_SPEED = 4200.0    # px/s of the tracer
SHOOT_MAX_TIME = 60.0          # hard stop for the whole event, whatever the clips do
SHOOT_MOCK_PERIOD = 0.45       # s between shots for characters with no attack clips
SHOOT_BODY_HALF_W = 0.16       # half-width of a student's hit box, as a fraction of her height
SHOOT_KNOCK_SPEED = (1100.0, 2000.0)   # px/s (x scale) a hit student is sent flying along the shot
SHOOT_KNOCK_LIFT = (120.0, 380.0)      # px/s (x scale) of upward pop added to the knock
SHOOT_KNOCK_SPIN = (2.0, 6.0)          # rad/s of spin; the sign follows the shot direction
SHOOT_LINES = {
    "student": ["Sorry, this is training!", "Eyes up!", "Heads up!", "Target practice!",
                "Don't take it personally!", "Fire!"],
    "hit":     ["Ow!", "Hey, that stings!", "Rude!", "Ah! You got me!", "Ouch..."],
    "miss":    ["Missed me!", "Too slow!", "Whoa, that was close!", "Hey! Watch it!"],
    "knocked": ["Waaah!", "Kyaa!", "Ahhh!", "I'm flying!", "Uwaaah!"],
}
# ------------------------------------------------------------------- combat AI
# An armed student who is shot at reacts to the SITUATION rather than rolling dice for every move.
#
# Deciding whether to fight or run (react_odds): the two panel chances are the starting point; being
# outnumbered, shaken or short on nerve pushes toward running, and a student with nowhere to run
# always fights.
#
# Fighting (combat_decide, between shots) is "fire and manoeuvre":
#   * RANGE   each fight she picks a preferred distance (ENGAGE_RANGE, in character heights). Out of
#             range she closes in; if the opponent is on top of her and shooting she backs off. She
#             only ever moves to a spot on her own side of the opponent, never through them.
#   * COVER   after a few shots from one spot while someone is shooting at her she relocates inside her
#             range band - a runner is much harder to hit (SHOOT_RUN_DODGE).
#   * AMMO    every bullet costs one round of her magazine (ammo_to_reload in combat_index.json); an attack
#             fires ammo_per_attack bullets spread across its animation. At 0 she plays Normal_Reload,
#             standing exposed. The magazine carries over between fights, and once a fight is over she
#             reloads again if she is on her feet and has spent any (see combat_over). She also reloads
#             BEFORE she is empty when it is tactically sensible: while an opponent is running away from
#             her, or by falling back out of the line of fire to reload and then coming back.
#   * NERVE   a hit or a near miss adds STRESS, which fades. Stress spoils her aim; a shaken student
#             with somewhere to run breaks and flees. Each student has her own nerve.
#   * AIM     accuracy falls with distance and she flinches after being hit (aim_accuracy).
#   * TARGET  she shoots at whoever is shooting at her (nearest first), not at a runner.
#
# Running away (plan_escape / flee_step): she picks a goal on HER side of every threat - as far from
# them as her floor / window top allows - re-plans as they move, and never turns back through them.
# When she cannot get further away (cornered, boxed in, out of breath) she turns and fights.
COMBAT_RUN_SPEED = 6.0          # x walk_speed while running
# ONE knob for how far apart students fight. 1.0 = each character's normal firing range (the
# firing_range in combat_index.json, e.g. 350 cm for Yuuka), 2.0 = twice that (700 cm for Yuuka).
# It stretches every combat distance below (preferred range, accuracy falloff, flee distances, the
# screen-width cap on range) AND the per-move time limits, so hit rates at the same *relative*
# distance are unchanged - they just happen at a bigger absolute distance.
COMBAT_DISTANCE_SCALE = 1.0
_CDS = COMBAT_DISTANCE_SCALE
ENGAGE_RANGE = (2.0 * _CDS, 3.8 * _CDS)       # character heights: her preferred fighting distance is drawn from here
ENGAGE_BAND = 0.55 * _CDS       # ... and she is content anywhere within +- this of it
MIN_ENGAGE = 1.3 * _CDS         # character heights: never prefer to fight closer than this
MOVE_MIN = 0.35 * _CDS          # character heights: a move shorter than this is not worth making
MOVE_MAX_TIME = {"advance": 2.5 * _CDS, "retreat": 1.6 * _CDS, "shift": 1.4 * _CDS, "cover": 2.5 * _CDS,
                 "shield": 3.5 * _CDS, "wincover": 3.5 * _CDS}   # s per move before she plants and shoots
ACC_NEAR, ACC_FAR = 2.0 * _CDS, 6.0 * _CDS    # character heights: full accuracy up to NEAR, ACC_FAR_MULT of it at FAR
ACC_FAR_MULT = 0.45
FLINCH_TIME = 0.9               # s after a hit that her aim is spoiled ...
FLINCH_AIM = 0.55               # ... multiplying her accuracy by this
MAG_SIZE = (6, 10)              # fallback magazine (rounds) for a model with no ammo stats in combat_index.json
AMMO_PER_ATTACK_DEFAULT = 1     # ... and its bullets per attack animation
BURST_SPAN = (0.15, 0.90)       # a multi-bullet attack spreads its bullets across this part of the Ing clip
# Reloading BEFORE the magazine is empty (see combat_decide):
RELOAD_CHASE_FRAC = 0.80        # the opponent is running: use the lull to reload if the magazine is at or below this
RELOAD_TACTICAL_CHANCE = 0.60   # ... and when the run is only a tactical move (a fighter repositioning), she reloads with this
                                # chance, rolled once per run of theirs; otherwise she keeps shooting / chasing as before
RELOAD_COVER_FRAC = 0.50        # being shot at with the magazine at or below this: she may fall back to reload ...
RELOAD_COVER_CHANCE = 0.55      # ... with this chance at each decision (she then comes back by herself: out of range = advance)
RELOAD_TIME = (1.3, 2.1)        # s standing still and exposed (only when the model has no Normal_Reload clip)
EXPOSURE_SHOTS = (2, 4)         # shots from one spot, while being shot at, before she relocates
STRESS_HIT, STRESS_NEAR = 0.22, 0.07   # stress added by a hit / by a bullet that went past her
STRESS_TAU = 5.0                # s: stress fades with this time constant
NERVE_RANGE = (0.35, 0.90)      # each student draws her nerve from here, once
FLEE_MIN_GAIN = 0.6 * _CDS      # character heights she must be able to gain, or running is pointless
FLEE_SAFE = 5.0 * _CDS          # character heights: far enough that more distance is worth nothing
FLEE_PASS_PAD = 0.7 * _CDS      # character heights she stays short of a threat (never runs past one)
FLEE_REPLAN = 0.35              # s between re-plans of where to run
FLEE_STAMINA = (6.0, 10.0)      # s a student can keep running
NO_FLEE_AFTER_TURN = 10.0       # s after turning to fight she will not break and run again
# Taking cover behind another student (begin_cover / cover_* below). Only for a model that has
# Kneel_Attack_* clips (the same names as Normal_Attack_*, kneeling). When she starts a fight (as the
# attacker or as a retaliator) she may run to a student on her own side of the opponent, stand just
# behind her and fight from the kneel clips, using her as a shield. Move_End_Kneel (when the model has
# it) is the move-end clip that drops her into the kneel. While she is settled behind her shield:
#   * her own bullets pass through the shield: shoot_fire leaves her shield out of shot_blocker, so
#     the student she hides behind can never take a bullet from her;
#   * shots at her are much less likely to be on target (COVER_AIM_MULT) - and the shield is physically
#     in the line of fire, so a bullet that misses her can still hit the shield (shoot_intercept_chance);
#   * she holds the spot instead of advancing / retreating / relocating, and follows the shield if
#     the shield wanders off;
#   * she leaves when the shield goes down, runs, turns hostile or is dragged away (then she either
#     finds another shield or fights from where she is), or after COVER_HOLD seconds (she stands up
#     and fights in a standing stance, so she never kneels there forever).
COVER_AIM_MULT = 0.40           # x the shooter's accuracy against a student who is settled behind a shield
COVER_GAP = 0.30                # character heights behind the shield's feet she kneels
COVER_SEEK = 6.0 * _CDS         # character heights: how far away a shield may be
COVER_HOLD = (9.0, 18.0)        # s she stays behind one shield before standing up and fighting in the open
COVER_DRIFT = 0.55              # character heights the shield may wander before she follows
COVER_MIN_BEHIND = 0.15         # character heights: her spot must really be behind the shield (not a wall-clamped fake)
# Taking cover behind a WINDOW (begin_cover / wincover_* in pet_cover.py). The same tactic as the
# student shield above, but the cover is an open desktop window instead of a student, and she fights
# from the Stand_Attack_* clips (Move_End_Stand drops her into the stance) instead of the kneel ones.
# Only for a model that has Stand_Attack_* clips. A window counts as cover when, seen from the floor /
# window top she stands on:
#   * its bottom edge is close enough to that ground (COVER_WIN_GROUND_GAP character heights above it
#     at most - a window that reaches down behind the taskbar / below her window top is fine), so it
#     reads as a wall standing on her ground and not as something floating over her head;
#   * the part of it rising above that ground is at least slightly taller than she is
#     (COVER_WIN_MIN_H x her body height) - a terminal on the taskbar, or a small window sitting on
#     the window she stands on. There is deliberately NO upper bound: she stands BESIDE the window
#     (COVER_WIN_GAP past its edge), never behind it, so a window towering over her still reads as a
#     wall she is hugging - and a taller one earns its keep, because a bullet only crosses the window
#     rect (seg_rect_t in pet_attack) when its path really passes through it, so more height is more
#     intercepted rounds, not free protection. Only the lower bound matters: it keeps her from
#     treating a 40px sliver - a toolbar, a thin notification window - as cover;
#   * it is not the window she stands on, it is still visible (WinTracker), and it lies between her
#     spot and her opponent, with her spot on her own side of the opponent.
# She stands just past the window's edge on the side away from the opponent. While settled there:
#   * shots at her are less likely to be on target (COVER_WIN_AIM_MULT), and a bullet whose path
#     crosses the window is stopped by it with COVER_WIN_BLOCK chance (spark on the window, BLOCK);
#   * she holds the spot, follows the window if it is dragged, and gives it up when it is closed /
#     covered / moved away from her ground, or after COVER_HOLD seconds.
COVER_WIN_AIM_MULT = 0.50       # x the shooter's accuracy against a student settled behind a window
COVER_WIN_BLOCK = 0.60          # chance a bullet whose path crosses her cover window is stopped by it
COVER_WIN_GAP = 0.22            # character heights past the window's edge she stands
COVER_WIN_GROUND_GAP = 0.25     # character heights the window's bottom may float above her ground
COVER_WIN_MIN_H = 0.55          # x her body height: the window must stand at least this far above
                                #   her ground. No maximum - see the block comment above.
COVER_WIN_MIN_W = 0.25          # character heights: a narrower visible strip is no cover
PROVOKE_COOLDOWN = 6.0          # s before the same shooter can trigger another react roll
CHASE_GIVE_UP = (4.0, 9.0)      # s a shooter keeps after a runner she can't bring down before giving up
SHOOT_RUN_DODGE = 0.80          # chance a bullet misses a student who is running
# Bullets arrive far faster than a bubble lasts, so a reactive line said on every hit would replace the
# text several times a second and read as babbling. Reactive lines go through say_combat and are held
# back until this many seconds have passed since her last one (Pet.say_combat). Beats that only happen
# once - knocked over, giving up on a tank - pass force=True and always get through.
COMBAT_LINE_COOLDOWN = 4.0
SHOOT_LINES["retaliate"] = ["You want a fight?!", "Fine, then!", "Return fire!", "Two can play at that!"]
SHOOT_LINES["flee"] = ["Run!", "Nope nope nope!", "Retreat!", "I'm out of here!"]
SHOOT_LINES["break"] = ["I can't take this!", "Too much! Fall back!", "Nope, nope, nope!", "Cover me!"]
SHOOT_LINES["cornered"] = ["Nowhere left to run!", "Fine, I'll fight!", "Back against the wall...!", "Cornered!"]
SHOOT_LINES["winded"] = ["Can't... run... anymore!", "Okay, okay, fighting!", "Phew... enough!"]
SHOOT_LINES["safe"] = ["Phew...", "Think I lost them.", "That was close..."]
SHOOT_LINES["reload"] = ["Reloading!", "Changing mags!", "Cover me, reloading!", "Out of ammo!"]
SHOOT_LINES["rearm"] = ["Reloading...", "Fresh mag.", "Topping up.", "Ready again!"]
SHOOT_LINES["cover"] = ["Falling back to reload!", "Cover me, I'm low!", "Back off, I need a reload!", "Pulling back!"]
SHOOT_LINES["wincover"] = ["Taking cover!", "Behind the window!", "This'll stop a few rounds!", "Using this for cover!"]
SHOOT_LINES["shield"] = ["Stay in front of me!", "Mind if I borrow you?", "Cover me!", "Keep your head up, I'm behind you!"]
SHOOT_LINES["chase"] = ["Run all you want, reloading!", "Not so fast... reloading.", "Changing mags while you run!"]
# A student who has been shooting at a target whose profile sets `shot_give_up` (Iroha's tank) stops
# and says one of these. A profile can also supply its own `give_up_lines`.
SHOOT_LINES["give_up"] = ["It's a tank... my bullets just bounce off!", "Forget it, that armor is too thick!",
                          "This is pointless against a tank!", "Okay, okay, I can't scratch that thing!"]
# ------------------------------------------------------------------- weapon test gun
# A weapon picked on the Interact tab turns Ctrl + left mouse button into a bench for
# the per-weapon looks in vfx.WEAPON_FX: a round leaves the middle of the pets' screen
# for the cursor and lands on the first student it crosses, hit for real through
# Pet.shot_landed (flinch, damage number, ragdoll chance). It is not a fight: no shooter
# to answer, no magazine, no aim roll - so nothing here has to be balanced, only the
# spacing of the rounds so a held button reads as a stream rather than a blur.
TEST_GUN_INTERVAL = 0.15    # s between rounds while the button is held
