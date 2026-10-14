"""Per-model profiles (iroha.py style): defaults, reading and validating them."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from .config import HERE
from .mathutil import clamp


# =============================================================================
#  One character = one .glb + its own animations, renderer and dialogue
# =============================================================================
# Most students need nothing but the defaults below. A model that has to be
# treated differently ships a module of the same name next to this file -
# model/Iroha.glb reads iroha.py, because her tank is far bigger than a
# student is and needs a bigger window. See iroha.py for the worked example.
PROFILE_DEFAULTS = dict(
    window_scale=1.0,    # her window, as a multiple of the shared --scale one
    window_aspect=1.0,   # ... and of the 380x520 base shape, for a tank that is
                         #     much wider than it is tall
    fit_clip=None,       # pose the window is sized for (default: her idle)
    anim={},             # ANIM_KEYS key -> the clip name she really uses
    ride={},             # a SECOND set of clips + window, used only while she is
                         #     fighting: dict(clips={anim key: name}, window_scale=,
                         #     window_aspect=, fit_clip=, fade=). Anything she does
                         #     not name falls back to the one above. The vehicle
                         #     fades in when a fight starts and out when it ends
                         #     (Iroha's tank) - see Pet.set_ride.
    textures={},         # prim-name fragment -> (glb to read, image index in it)
    pet=True,            # False = this .glb is a PART, loaded only as a texture source
    shot_ragdoll_chance=None,  # 0..1 overrides the panel's "Ragdoll on hit" for bullets hitting HER (0 = never)
    shot_give_up=None,   # (min_s, max_s): a student shooting at her stops after this long and picks another target
    hit_lines=[],        # what she says when a bullet hits her (default: SHOOT_LINES["hit"])
    give_up_lines=[],    # what a student says on giving up on her (default: SHOOT_LINES["give_up"])
    attack_clips={},     # stance -> {"start"/"ing"/"end": clip name}: her OWN attack clips (e.g. Tank_Normal_Attack_Ing),
                         #     used instead of the <Stance>_Attack_* ones the main file finds by name
    bullet=None,         # dict: a special bullet she fires (ragdoll_chance, knock, speed, color, width, trail,
                         #     impact_size, muzzle_flash, muzzle_bone). None = ordinary bullets
)

# How long a vehicle takes to fade in when a fight starts, and out when it ends
# (profile `ride` block, see Pet.set_ride). Long enough to read as the tank
# deploying rather than blinking into existence.
RIDE_FADE = 0.55


_PROFILE_CACHE = {}


def load_profile(glb_path):
    """Overrides for one model, read from the <name>.py next to this file.

    Returns PROFILE_DEFAULTS when there is no such module, and also when the
    module is broken or asks for something nonsensical: one bad profile must
    never stop the pets from starting. Keys it does not mention keep the
    default, so a profile only ever has to state what it changes.

    Cached per model: find_models asks first (to skip parts) and App asks again
    when it builds the character, and a profile is only worth reading once.
    """
    stem = Path(glb_path).stem
    if stem in _PROFILE_CACHE: return dict(_PROFILE_CACHE[stem])
    prof = _read_profile(stem)
    _PROFILE_CACHE[stem] = prof
    return dict(prof)


def _read_ride(prof, src):
    """The profile's `ride` block, normalised. {} when there is not one.

    Everything except the clip list is optional and falls back to the top-level
    window numbers, so `ride=dict(clips={...})` alone is a valid profile: she
    simply fights in the window she already has. A block with no usable clips is
    dropped entirely - it is what tells Character a model has no vehicle at all.
    """
    rd = prof.get("ride")
    if not isinstance(rd, dict):
        if rd is not None: print(f"[warn] {src.name}: ride must be a dict - ignored")
        return {}
    cl = rd.get("clips")
    cl = {str(k): str(v) for k, v in cl.items() if isinstance(v, str) and v} if isinstance(cl, dict) else {}
    if not cl: return {}
    for k in ("window_scale", "window_aspect"):
        try: rd[k] = max(0.1, float(rd[k]))
        except (KeyError, TypeError, ValueError): rd[k] = float(prof[k])
    fc = rd.get("fit_clip"); rd["fit_clip"] = fc if isinstance(fc, str) and fc else None
    try: rd["fade"] = clamp(float(rd.get("fade", RIDE_FADE)), 0.0, 5.0)
    except (TypeError, ValueError): rd["fade"] = RIDE_FADE
    rd["clips"] = cl
    return rd


def _read_profile(stem):
    prof = dict(PROFILE_DEFAULTS)
    src = HERE / f"{stem}.py"
    if not src.is_file():                          # Windows is case-insensitive,
        src = next((q for q in HERE.glob("*.py")   # this is for anything else.
                    if q.stem.lower() == stem.lower()), None)
    if src is None or not src.is_file(): return prof
    try:
        spec = importlib.util.spec_from_file_location(f"pet_profile_{src.stem}", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = getattr(mod, "PROFILE", {})
        if not isinstance(data, dict): raise TypeError(f"PROFILE must be a dict, got {type(data).__name__}")
        prof.update(data)
    except Exception as e:
        print(f"[warn] {src.name}: {type(e).__name__}: {e} - using the default character setup")
        return dict(PROFILE_DEFAULTS)
    try:
        prof["window_scale"] = max(0.1, float(prof["window_scale"]))
        prof["window_aspect"] = max(0.1, float(prof["window_aspect"]))
    except (TypeError, ValueError):
        print(f"[warn] {src.name}: window_scale / window_aspect must be numbers - using the defaults")
        prof["window_scale"] = PROFILE_DEFAULTS["window_scale"]
        prof["window_aspect"] = PROFILE_DEFAULTS["window_aspect"]
    if not isinstance(prof.get("anim"), dict):
        prof["anim"] = {}
    fit = prof.get("fit_clip")
    prof["fit_clip"] = fit if isinstance(fit, str) and fit else None
    prof["ride"] = _read_ride(prof, src)
    prof["pet"] = bool(prof.get("pet", True))
    try:
        rp = prof.get("shot_ragdoll_chance")
        prof["shot_ragdoll_chance"] = None if rp is None else clamp(float(rp), 0.0, 1.0)
        gu = prof.get("shot_give_up")
        if gu is None: prof["shot_give_up"] = None
        else:
            if isinstance(gu, (int, float)): gu = (gu, gu)
            lo, hi = float(gu[0]), float(gu[1])
            prof["shot_give_up"] = (max(0.1, min(lo, hi)), max(0.1, max(lo, hi)))
    except (TypeError, ValueError, IndexError):
        print(f"[warn] {src.name}: shot_ragdoll_chance / shot_give_up are invalid - ignored")
        prof["shot_ragdoll_chance"] = None; prof["shot_give_up"] = None
    ac = prof.get("attack_clips")
    prof["attack_clips"] = {str(k): {str(ph): str(n) for ph, n in v.items()} for k, v in ac.items()
                            if isinstance(v, dict)} if isinstance(ac, dict) else {}
    prof["bullet"] = dict(prof["bullet"]) if isinstance(prof.get("bullet"), dict) else None
    for k in ("hit_lines", "give_up_lines"):
        v = prof.get(k)
        prof[k] = [str(s) for s in v if s] if isinstance(v, (list, tuple)) else []
    print(f"{src.name}: window x{prof['window_scale']:.2f} (aspect x{prof['window_aspect']:.2f}), "
          f"{len(prof['anim'])} clip override(s)"
          + (f", sized for '{prof['fit_clip']}'" if prof["fit_clip"] else "")
          + (f", rides with {len(prof['ride']['clips'])} clip(s) in a x{prof['ride']['window_scale']:.2f} window"
             if prof["ride"] else "")
          + ("" if prof["pet"] else " - not a pet, a part other models borrow from"))
    return prof
