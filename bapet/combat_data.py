"""combat_index.json loading, attack/move clip lookup, and the pure flee / react-odds maths."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .combat_config import AMMO_PER_ATTACK_DEFAULT, FLEE_PASS_PAD, FLEE_SAFE
from .config import HERE
from .gltf import norm_name


_ATK_RE = re.compile(r"(normal|stand|kneel)attack(start|strat|ing|delay|end)")
_ATK_STRAT = re.compile(r"attackstrat$")     # the 'Strat' typo, folded by Model.find_clip

# ------------------------------------------------------------------- combat index
# combat_index.json (next to this script) holds per-character combat stats:
#   "firing_range"     (cm, raw wiki value) scales how far she likes to fight from her opponent and how far
#                      her aim stays accurate;
#   "ammo_per_attack"  bullets fired during ONE attack animation (spread across it);
#   "ammo_to_reload"   her magazine: after this many bullets she has to reload.
# A model whose .glb file name matches an entry uses that entry; any other model (or an entry whose ammo
# numbers are 0, e.g. the healers) uses the defaults above. Keys may be "Mika.glb" or "model/Mika.glb":
# only the file name counts.
COMBAT_INDEX_PATH = HERE / "combat_index.json"
FIRING_RANGE_DEFAULT = 650.0        # cm: the spacing the combat constants above were tuned for
FIRING_RANGE_SCALE = (0.4, 2.5)     # clamp on firing_range / FIRING_RANGE_DEFAULT
_COMBAT_INDEX = None


def load_combat_index():
    """{lowercase glb file name: stats dict}, read once. Missing / broken file = empty, so every
    character simply uses the default combat stats."""
    global _COMBAT_INDEX
    if _COMBAT_INDEX is not None: return _COMBAT_INDEX
    out = {}
    try:
        raw = json.loads(COMBAT_INDEX_PATH.read_text(encoding="utf-8"))
        for key, val in raw.items():
            if key.startswith("_") or not isinstance(val, dict): continue
            out[Path(key).name.lower()] = val
    except FileNotFoundError:
        print(f"[info] {COMBAT_INDEX_PATH.name} not found - every character uses default combat stats")
    except Exception as e:
        print(f"[warn] could not read {COMBAT_INDEX_PATH.name}: {e} - using default combat stats")
    _COMBAT_INDEX = out
    return out


def firing_range_for(glb_path):
    """(firing range in cm, True if it came from the index) for one model file."""
    ent = load_combat_index().get(Path(glb_path).name.lower())
    if ent is not None:
        try:
            fr = float(ent.get("firing_range"))
            if fr > 0: return fr, True
        except (TypeError, ValueError):
            pass
    return FIRING_RANGE_DEFAULT, False


def ammo_for(glb_path):
    """(bullets per attack, magazine size or None, True if from the index) for one model file.
    None for the magazine means "no usable stats": the caller draws one from MAG_SIZE."""
    ent = load_combat_index().get(Path(glb_path).name.lower())
    if ent is not None:
        try:
            per, mag = int(ent.get("ammo_per_attack")), int(ent.get("ammo_to_reload"))
            if per > 0 and mag > 0: return per, mag, True
        except (TypeError, ValueError):
            pass
    return AMMO_PER_ATTACK_DEFAULT, None, False


def weapon_for(glb_path):
    """Her weapon_type from combat_index.json ("Shotgun", "Sniper Rifle", "Railgun", ...), or None.
    Only drives the look of her shots (vfx.WEAPON_FX): tracer, muzzle flash, impact, damage numbers."""
    ent = load_combat_index().get(Path(glb_path).name.lower())
    if ent is None: return None
    w = ent.get("weapon_type")
    return w if isinstance(w, str) and w else None


def move_sets(model):
    """{"run": Move_Ing clip, "stop": Move_End_Normal clip, "kneel_stop": Move_End_Kneel clip,
    "stand_stop": Move_End_Stand clip} for one model (any may be missing)."""
    cached = getattr(model, "_move_sets", None)
    if cached is not None: return cached
    out = {}
    for name, clip in model.clips.items():
        base = norm_name(re.split(r"[|:/]", name)[-1])
        if base == "moveing": out["run"] = clip
        elif base == "moveendnormal": out["stop"] = clip
        elif base == "moveendkneel": out["kneel_stop"] = clip
        elif base == "moveendstand": out["stand_stop"] = clip
    model._move_sets = out
    return out


def attack_sets(model):
    """{stance: {phase: Clip}} for one model, cached on it.

    Names are folded the way ATTACK_ANIMATIONS.md asks: case-insensitive, and the
    real typos 'Strat' / 'STart' count as 'Start'. Tank_* and *_Riding_* clips are
    left out on purpose (the prefix stops the pattern matching). A stance with no
    'Ing' clip cannot fire, so it is dropped. Empty dict = no attack animations.
    (A 'delay' clip is still collected here but the shoot state machine never plays it.)
    """
    cached = getattr(model, "_atk_sets", None)
    if cached is not None: return cached
    sets = {}
    for name, clip in model.clips.items():
        base = re.split(r"[|:/]", name)[-1]
        m = _ATK_RE.fullmatch(norm_name(base))
        if not m: continue
        phase = "start" if m.group(2) == "strat" else m.group(2)
        sets.setdefault(m.group(1), {})[phase] = clip
    sets = {k: v for k, v in sets.items() if "ing" in v}
    model._atk_sets = sets
    return sets


def plan_escape(fx, lo, hi, threats, ch):
    """Where should a student standing at fx run to, on a floor spanning lo..hi, to get away from
    `threats` (their x positions)?  Returns (goal, gain): the goal x, and how many px further from
    the nearest threat it is than where she stands now. (fx, 0.0) means nowhere is any better.

    What makes it look like running away rather than wandering:
      * she never plans a path through a threat: she stays on her own side of every one of them,
        FLEE_PASS_PAD character heights short of it, so a run can never bring her closer;
      * of what she can reach she takes the point farthest from the nearest threat - but past
        FLEE_SAFE character heights extra distance is worth nothing, so a student who is already
        far enough does not sprint to the wall;
      * boxed in between threats, the best point is the middle of the gap."""
    if not threats: return fx, 0.0
    pad = FLEE_PASS_PAD * ch
    left = [t for t in threats if t <= fx]; right = [t for t in threats if t > fx]
    L, R = lo, hi
    if left: L = max(L, max(left) + pad)
    if right: R = min(R, min(right) - pad)
    L, R = min(L, fx), max(R, fx)           # already inside the pad: she can stay put or go away, not closer
    safe = FLEE_SAFE * ch
    def worth(g): return min(safe, min(abs(g - t) for t in threats))
    here = worth(fx); best, best_w = fx, here
    n = 24
    for i in range(n + 1):
        g = L + (R - L) * i / n; w = worth(g)
        if w > best_w + 1e-6 or (abs(w - best_w) <= 1e-6 and abs(g - fx) < abs(best - fx)):
            best, best_w = g, w
    return best, best_w - here


def react_odds(fight, flee, can_run, attackers, stress, nerve):
    """The odds that an armed student who is shot at (fights back, runs away) in THIS situation.

    The two panel chances fix how often she reacts at all (their sum, capped at 1; the rest of the
    time she does nothing). The situation only decides the split between the two: being outnumbered,
    shaken, or short of nerve tips it toward running, a brave student leans toward fighting, and with
    nowhere to run it is always a fight. A chance set to 0 stays 0."""
    total = min(1.0, fight + flee)
    if total <= 0.0: return 0.0, 0.0
    if not can_run: return total, 0.0
    w_flee = flee * (1.0 + 0.7 * max(0, attackers - 1)) * (1.0 - 0.8 * (nerve - 0.625)) * (0.8 + 0.8 * stress)
    w_fight = fight * (1.0 + 0.5 * (nerve - 0.625))
    share = w_flee / (w_flee + w_fight) if w_flee + w_fight > 0.0 else 0.0
    return total * (1.0 - share), total * share
