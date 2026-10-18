"""Iroha's tank in the Battle Arena.

Her EX summons the tank around her (Tank_Appearance) and she drives it for TANK["duration"]
seconds. While she rides:

    * she is INVULNERABLE - bullets, blasts and grenades read IMMUNE, nothing suppresses her
    * anything on its feet that the hull drives over is CRUSHED: an instant ragdoll (one life,
      like every ragdoll in the arena), flung by the crush knock. Allies included.
    * the main gun fires shells. A shell that lands instantly ragdolls EVERY student inside
      its blast radius - both teams, friendly fire always on, whatever the setting says.
    * the hull is a much bigger, taller body than a student: it blocks far more shots for
      whoever stands behind it (Battle.trace / Battle.cover_value use TANK["block_r"]).
    * crates and barrels in her way are flattened (barrels explode - also friendly fire).
      Barriers, containers, vending machines and desktop windows stop her.

Everything that may be tuned is here. The things the design fixes - invulnerable, crushes
whoever she drives over, shells ragdoll everyone in the radius, friendly fire - are rules,
not numbers, and live in the code that implements them (fighter.py / battle.py).
"""
from __future__ import annotations

import math

TANK = dict(
    # ---- the EX itself
    ex_cost=30.0,          # s of passive charge for a full gauge (others: 14-18). Damage dealt /
                           # taken still speeds it up a little, like every other EX.
    ex_start_max=0.15,     # her gauge never starts above this: no tank in the first 20 s
    duration=11.0,         # s she drives before the tank is stowed again
    deploy=0.9,            # s the summon takes (Tank_Appearance plays, she can't move or fire)
    stow=0.6,              # s the dismount takes (she's still immune while hopping out)

    # ---- driving (student heights per second / radians per second)
    speed=2.05,            # ch/s. Students run 1.75-1.93, so she catches anyone who hesitates
                           # but not someone who runs straight away from her
    reverse=0.9,           # ch/s backing up when the way forward is blocked
    turn=2.4,              # rad/s. Slow enough that a side-step beats her
    accel=4.0,             # how quickly she reaches speed (1/s)

    # ---- the hull
    crush_r=0.50,          # ch, radius of the crush capsule...
    crush_len=0.70,        # ch, ...which runs this far ahead of and behind her centre
    crush_min_speed=0.25,  # fraction of top speed she must be moving to crush (a parked tank is a wall)
    crush_knock=1250.0,    # knock-back power of a crush (bullets 420-1000, explosions 900)
    crush_dmg=4000.0,      # damage credited to her for a crush (x the damage setting). The crush
                           # itself always ragdolls; this is what the scoreboard sees
    block_r=0.80,          # ch, the radius that catches bullets aimed past her (a student: 0.17)
    push_r=0.62,           # ch, how far she shoves standing students away (smaller than the crush
                           # capsule's reach ahead, so whoever is in front goes under, not ahead)
    prop_dps=9000.0,       # damage per second to a breakable prop she is pushing into
    height=1.65,           # ch, hull height for drawing / the physics pillar

    # ---- the main gun
    shell_range=7.0,       # ch
    shell_speed=6.3,       # ch/s. A rifle is hitscan; a rocket flies 9.0. Dodgeable at range
    shell_radius=1.0,      # ch, everyone inside is ragdolled
    shell_dmg=2200.0,      # credited damage per victim (x damage setting); the ragdoll is the point
    shell_rof=2.4,         # s between shells
    shell_mag=3,           # shells before she reloads
    shell_reload=3.2,      # s (SM015601_Riding_Reload / Tank_Normal_Reload)
    shell_aim=0.45,        # s she must be lined up before the first shell
    shell_turn=3.2,        # rad/s the gun (= hull) lines up at while she is parked
    shell_min=1.6,         # ch, she won't shell anything closer than this (it would be in her own blast)
    shell_ally_block=True, # never fire a shell that would land on an ally (the AI's choice, not a rule)
    shell_knock=1000.0,    # knock-back power on the victims

    # ---- what other students assume about her
    danger_r=2.6,          # ch, enemies start evading when she is this close and coming their way
    front_r=1.6,           # ch, allies keep out of this cone in front of her (she crushes allies too)
    splash_pad=1.15,       # x shell_radius - nobody stands this close to her current target
)

TANK_EX_NAME = ("Toramaru, Deploy!", "\u6226\u8eca\u5c55\u958b")      # 戦車展開

# clip names in Iroha.glb (first that exists wins; the profile's ride clips are the fallback)
TANK_CLIPS = {
    "appear": ("Tank_Appearance",),
    "idle":   ("Tank_Normal_Idle", "SM015601_Riding_Idle"),
    "move":   ("Tank_Move_Ing", "SM015601_Riding_Ing"),
    "reload": ("Tank_Normal_Reload", "SM015601_Riding_Reload"),
    "end":    ("Tank_Move_End_Normal", "SM015601_Riding_End_Normal"),
    "atk_start": ("Tank_Normal_Attack_Strat", "Tank_Normal_Attack_Start", "SM015601_Riding_Attack_Start"),
    "atk_ing":   ("Tank_Normal_Attack_Ing", "SM015601_Riding_Attack_Ing"),
    "atk_end":   ("Tank_Normal_Attack_End", "SM015601_Riding_Attack_End"),
}


def has_tank(ch):
    """Does this character bring a tank? (a profile with ride clips, i.e. Iroha)."""
    return getattr(ch, "ride_clips", None) is not None


def riding(f):
    """Is this fighter in her tank right now (deploying, driving or stowing)?"""
    return getattr(f, "tank", None) is not None


def active_tanks(battle):
    return [f for f in battle.fighters if f.alive and f.tank is not None]


def crush_dist(f, x, y):
    """Distance from a point to the tank's crush capsule axis (centre +- crush_len along heading)."""
    sz = f.size
    L = TANK["crush_len"] * sz
    c, s = math.cos(f.heading), math.sin(f.heading)
    ax, ay = f.x - c * L, f.y - s * L
    bx, by = f.x + c * L, f.y + s * L
    dx, dy = bx - ax, by - ay
    u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / max(1e-6, dx * dx + dy * dy)))
    return math.hypot(x - (ax + dx * u), y - (ay + dy * u))


def in_front(f, x, y, reach):
    """Is (x, y) inside the forward cone a tank is about to drive through?"""
    dx, dy = x - f.x, y - f.y
    d = math.hypot(dx, dy)
    if d > reach or d < 1e-6: return False
    c, s = math.cos(f.heading), math.sin(f.heading)
    return (dx * c + dy * s) / d > 0.55


def side_step(f, tk, dist):
    """Where a student at f should go to get out of tank tk's way: sideways off its heading,
    on whichever side she already is, biased away from the hull."""
    c, s = math.cos(tk.heading), math.sin(tk.heading)
    rx, ry = f.x - tk.x, f.y - tk.y
    side = 1.0 if (rx * -s + ry * c) >= 0 else -1.0
    nx, ny = -s * side, c * side
    # a touch backwards along the tank's heading too, so she is not simply run down later
    ax, ay = rx, ry
    d = math.hypot(ax, ay) or 1.0
    ax, ay = ax / d, ay / d
    gx = f.x + (nx * 0.85 + ax * 0.35) * dist
    gy = f.y + (ny * 0.85 + ay * 0.35) * dist
    return gx, gy


def find_clip(ch, key):
    """A tank clip for `key` from TANK_CLIPS, else the profile ride clip, else None."""
    model = ch.model
    for name in TANK_CLIPS.get(key, ()):
        c = model.find_clip(name)
        if c is not None: return c
    rc = getattr(ch, "ride_clips", None) or {}
    alias = {"idle": "alert", "move": "walk", "reload": "reload", "end": "idle", "appear": "idle"}
    k = alias.get(key)
    if k and rc.get(k) is not None: return rc[k]
    return None


def tank_fit(ch):
    """Bounding fit of the riding pose (tank included), cached on the character."""
    fit = getattr(ch, "_arena_tank_fit", None)
    if fit is not None: return fit
    fit = None
    try:
        c = find_clip(ch, "idle")
        if c is not None:
            fit = ch.model.compute_fit(ch.model.posed0(c))
    except Exception:
        fit = None
    if fit is None:
        rw = getattr(ch, "ride_win", None)
        fit = rw["fit"] if rw else ch.fit
    ch._arena_tank_fit = fit
    return fit
