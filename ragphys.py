#!/usr/bin/env python3
"""
Articulated 2D ragdoll physics for the desktop pets, on pymunk.
==================================================================
The old ragdoll (still in multi_single_screen_pet_ba.py, cfg "legacy") is one
rigid rod plus one damped pendulum per limb. This module replaces it with a
real articulated skeleton: one capsule body per limb, pinned and angle-limited
against its parent, colliding with the screen edges, the other pets' bodies
and the rectangles of the real Windows on the home screen.

Deliberately free of Qt, OpenGL and numpy so it can be imported and tested on
its own: `python test_ragphys.py` runs headless. Everything here speaks in
logical screen pixels with y pointing DOWN, the same convention Qt, pymunk and
the legacy ragdoll already use, so no sign flips are needed anywhere except
where a model-space rotation meets a screen-space angle (see build_posts).

pymunk version
--------------
This targets pymunk 7 (`pip install "pymunk>=7,<8"`), and the pin says so. The
original task pinned ">=6.6,<7", but 6.x and 7.x do not agree on the collision
API - 6 uses `Space.add_collision_handler(type_a, type_b, begin_func, ...)`
positionally, 7 uses `Space.on_collision(type_a, type_b, begin=..., separate=)`
by keyword. This module is written against the 7 spelling throughout, so
claiming a 6.x pin would be a pin that does not work. 7.3.0 is what is
installed and what the tests run on.

Two pymunk 7 behaviours cost real debugging time and are worth knowing before
changing anything here:

  - `Shape.point_query(p)` takes ONE tuple and returns a NEGATIVE distance for
    a point inside the shape. Called with two scalars it raises TypeError; read
    with abs() it reports penetration depth as if it were a distance, which
    makes a point deep in a thick torso capsule look further away than one
    grazing a thin forearm.
  - Chipmunk calls `velocity_func` on every body each step, KINEMATIC ones
    included, and the default implementation recomputes v from the position
    delta. A kinematic body is moved ONLY by its velocity, so it needs
    `_keep_velocity` or nothing you set on it survives a single substep.

Coordinates are GLOBAL screen px (Qt logical px across the whole desktop), not
window-local: a pet's window origin is added when the skeleton is built, so a
skeleton can be dropped from any window onto any surface.

Skeleton spec (built by Pet.start_ragdoll, consumed by RagWorld.add_skeleton)
--------------------------------------------------------------------------------
    dict(
        scale = float,          # her cfg["scale"], sets gravity and the rest threshold
        px, py = float,         # window origin in global screen px (added to every point)
        root  = int,            # index into `bodies` of the pelvis body
        drop  = float,          # pelvis -> feet distance in WINDOW px (window placement)
        bodies = [ body, ... ]  # parents always come before their children
    )

    body = dict(
        name   = str,           # debug label only
        bone   = int,           # rig node index -> the bone this body rotates
        parent = int | None,    # index into `bodies`, None for the root
        p      = (x, y),        # proximal joint, GLOBAL screen px (the body origin)
        c      = (x, y),        # distal joint, GLOBAL screen px (local +x end)
        r      = float,         # capsule radius, px
        w      = float,         # mass weight; all weights are normalised to 1.0
        lim    = float,         # symmetric joint limit, rad
        k      = float,         # return-to-pose stiffness  (x the child's moment)
        damp   = float,         # return-to-pose damping     (x the child's moment)
        head   = bool,          # add a skull circle past the distal end
    )
"""
from __future__ import annotations

import math
import random
from collections import namedtuple

try:
    import pymunk
    HAVE_PYMUNK = True
    PYMUNK_VERSION = getattr(pymunk, "version", "unknown")
except ImportError:                                        # pragma: no cover
    pymunk = None
    HAVE_PYMUNK = False
    PYMUNK_VERSION = "none"

__all__ = ["HAVE_PYMUNK", "PYMUNK_VERSION", "Impact", "RagWorld", "RagSkeleton",
           "CT_BODY", "CT_SCREEN", "CT_WINDOW"]


# ------------------------------------------------------------------ tunables
# Every number that decides how she falls, bounces and settles lives here.
RAGP_SUBSTEP = 1.0 / 360.0  # [v2] smaller steps converge tighter than more iterations (was 1.0 / 240.0)
RAGP_MAX_SUBSTEPS = 30  # [v2] 30/360 s = 83 ms, same catch-up window as before (was 20)
RAGP_ITERATIONS = 20  # [v2] 360 Hz x 20 costs the same as 240 Hz x 30 (was 30)
RAGP_SLOP = 0.4  # [v2] tighter at the higher rate (was 0.5)
RAGP_DAMPING = 0.99         # space damping, per second.
RAGP_MAX_LIN_V = 6000.0     # px/s ceiling enforced per body (a 6000 px/s limb moves 25 px per substep).
_DIAG = None                # lazy ragdiag.on() cache, see _diag_on()
RAGP_MAX_ANG_V = 40.0       # rad/s ceiling enforced per body (40 rad/s = 6.4 rev/s).
RAGP_BLAST_V = 12000.0      # px/s above which the whole skeleton's velocity is zeroed as a last resort.
RAGP_CT_BODY = 1            # collision type: character limbs
RAGP_CT_SCREEN = 2          # collision type: the four screen walls
RAGP_CT_WINDOW = 3          # collision type: real Windows
RAGP_BODY_FRICTION = 0.75  # [v2] clothed limb; pair with the surface = 0.6 (was 0.9)
RAGP_BODY_ELASTICITY = 0.35  # [v2] limp tissue barely bounces (was 0.5)
RAGP_ENV_FRICTION = 0.80  # [v2] floor / window top (was 0.9)
RAGP_ENV_ELASTICITY = 0.55  # [v2] pair = 0.19, and it fades to 0 at low closing speed (was 0.7)
RAGP_WALL_MARGIN = 60.0     # px the wall segments sit OUTSIDE the screen edge...
RAGP_WALL_RADIUS = 60.0     # ...and their radius, so the inner face lands exactly on the edge and nothing tunnels.
RAGP_WIN_MAX_V = 4000.0     # px/s cap on an interpolated window. Faster than a hand can flick one.
RAGP_WIN_SNAP_DIST = 600.0  # px of movement above which a window teleports instead of sliding.
RAGP_WIN_MIN_DT = 1.0 / 60  # s floor on the divisor when turning a move into a velocity.
RAGP_IMPACT_DIV = 1000.0    # impulse / (mass * this) = impact strength. A standing-height fall lands near 1.
RAGP_IMPACT_SOUND = 2.0     # strength above which a hit is loud enough to play the ragdoll sound.
RAGP_IMPACT_COOLDOWN = 0.25  # s between two dust puffs for one pet.
RAGP_SQUASH_MAX = 0.26      # self.sq ceiling on a hit, matching the legacy clamp.
RAGP_SQUASH_DIV = 6500.0    # strength / this = self.sq, matching the legacy impact/6500.
RAGP_REST_SPEED = 40.0      # px/s; below this (x scale) while touching something, she is at rest.
RAGP_CONTACT_GRACE = 0.10   # s a contact still counts after it closes; see RagSkeleton.touching
RAGP_SELF_COLLIDE = True  # [v2] ON: limbs stop passing through her own torso and head (was False)
                           # [v2: this is now ON by default] because it roughly DOUBLES the cost of the whole world: with it
                           # on, 4 ragdolls + 10 windows measure 3.5 ms per frame against
                           # 1.7 ms without, which is over the 1 ms budget in test 9. The
                           # extra cost is not the filter (categories/masks and a pre_solve
                           # callback measure the same) - it is that a limb resting against
                           # her torso is a real contact the solver then has to resolve, and
                           # there are many of them once she is lying still.
                           #
                           # It looks distinctly better: without it her arms pass through her
                           # own chest and head and she settles as a flat sprawl; with it she
                           # curls into a ball, which is what a body that has actually fallen
                           # over does. Turn it on with cfg["ragdoll_self_collide"].
RAGP_GETUP_TIME = 0.7       # s of blend from lying to standing.
RAGP_REST_TIME = 3.0        # s lying still before she gets up by herself.
RAGP_GRAB_RADIUS = 60.0     # px (x scale) the cursor may be from a limb and still grab it
RAGP_GRAB_MAX_BIAS = 2000.0 # px/s the grab joint may pull the limb in to close position error
RAGP_GRAB_FORCE = 40.0      # x her total weight (she weighs 1.0 and g = 2600, so ~40 g); the joint's force ceiling
RAGP_GRAB_THROW_V = 3000.0  # px/s cap on how fast a limb may leave the cursor on release, matching the old throw
RAGP_SHOVE_UP = (500.0, 900.0)  # px/s of upward kick from a click, times scale and power
RAGP_SHOVE_SIDE = 6.0       # horizontal shove = (pet_x - cursor_x) * this, clamped
RAGP_SHOVE_CLAMP = 1400.0   # px/s cap on that horizontal shove
# The start kick must NOT throw her into the air. At g = 2600 an upward 600-1200 px/s
# is a 70-280 px hop, which is right for an edge slam and absurd for Ctrl+1 on a pet
# standing on the floor - she visibly levitates. So VY is 0: she simply crumples and the
# random start tilt + spin (RAGP_START_TILT / RAGP_START_SPIN) do the toppling.
# These are the last dregs kept for the slam path, which passes kick=True explicitly.
RAGP_KICK_VX = (60.0, 200.0)     # px/s random sideways kick at ragdoll start (x scale)
RAGP_KICK_VY = (0.0, 0.0)        # px/s upward kick at ragdoll start: none (x scale)
RAGP_KICK_W = (1.0, 3.0)         # rad/s random pelvis spin at ragdoll start
RAGP_START_SPIN = 0.5            # rad/s of initial spin per limb. A rate, never an angle: see _build.
RAGP_START_TILT = 0.15          # rad the whole skeleton starts off vertical; never 0, a rod balances on its end
RAGP_TORSO_LIM = 0.5        # rad, spine / chest limit: the torso barely bends in 2D
RAGP_HEAD_LIM = 0.7  # [v2] neck lateral flexion about 40 deg (was 0.8)
RAGP_TORSO_K = 8.0          # torso return-to-pose stiffness (x the child's moment)
RAGP_TORSO_DAMP = 9.0       # torso return-to-pose damping (x the child's moment)
RAGP_HEAD_K = 10.0          # head return-to-pose stiffness
RAGP_HEAD_DAMP = 11.0       # head return-to-pose damping
RAGP_LIMP_K = 0.22  # [v2] less return-to-pose: a limp body does not stand itself up (was 0.35)
                           # Measured on the real rig over 3 seeds x 14 s: at 1.0 she stands
                           # back up (pelvis settles at +0.3 deg from vertical - upright on
                           # the floor, on screen as if the ragdoll never happened); at 0.35
                           # she stays down (pelvis +72..+95 deg, body 2.9-3.5x wider than
                           # tall), and she still settles inside 1 s of hitting the floor.
                           # A stiff "return to the spawn pose" spring is a spring whose job
                           # is to stand her back up, which is the opposite of fallen.
RAGP_LIMP_DAMP = 1.8  # [v2] more joint viscosity so she settles instead of oscillating (was 1.35)
                           # springs settle on the floor instead of oscillating.
RAGP_SPRING_MAX_F = 40.0    # x her weight, ceiling on the return-to-pose spring. Generous, but not infinite.
RAGP_HEAD_CIRCLE = 0.85     # skull radius as a fraction of the neck->head capsule radius
RAGP_HEAD_OFFSET = 0.8      # skull centre, as a fraction of its radius, past the head bone
RAGP_MIN_BODIES = 6         # fewer than this and the rig is not usable -> fall back to the rod
RAGP_OUTSIDE_H = 1.0        # how many character heights the pelvis may leave the screen before it is snapped back
RAGP_CATCHUP = 0.5          # s of world time a window is allowed to finish a slide after the last poll
RAGP_DEBUG = False          # flipped by --rag-debug; harmless when off
RAGP_TRACE_FRAMES = 0       # frames to print after trace() is called; 0 disables it
# ---- v2 realism tunables (added by the realism pass) ------------------------
# The numbers above were retuned in place; each one carries a "[v2]" note.
RAGP_ANTHRO = True          # [v2] masses = capsule area x tissue density, i.e. what a 2D body of that exact shape weighs
RAGP_ANTHRO_BLEND = 1.0     # 1 = fully physical, 0 = keep the weights Pet put in the spec
RAGP_MASS_MIN = 0.012       # no body lighter than this share of the whole character...
RAGP_MASS_MAX = 0.50        # ...and none heavier than this
RAGP_DENSITY = {"pelvis": 0.92, "neck": 1.07, "upperarm": 1.06, "forearm": 1.10,
                "thigh": 1.04, "calf": 1.08, "other": 1.0}   # relative tissue density; the trunk holds the lungs
RAGP_HEAD_FIX = True        # re-aim a skull whose neck->head bone is tiny or points down the spine
RAGP_HEAD_AXIS_MIN_DOT = 0.35   # cos of the largest angle between neck->head and the torso axis that is left alone
RAGP_HEAD_MIN_LEN = 0.6     # x capsule radius, shortest neck->head segment a re-aimed skull is placed from
# (outward, inward) travel in rad from the pose she starts in. Always capped by the spec's own limit.
RAGP_JOINT_RANGE = {"upperarm": (2.30, 1.10),   # shoulder: abduction vs adduction
                    "forearm": (1.50, 1.50),
                    "thigh": (1.00, 0.60),      # hip: abduction 45-57 deg, adduction about 34 deg
                    "calf": (0.75, 0.75),
                    "neck": (0.70, 0.70)}
RAGP_JOINT_K_MUL = 1.0      # extra multiplier on every return-to-pose stiffness
RAGP_JOINT_DAMP_MUL = 1.0   # extra multiplier on every return-to-pose damping
RAGP_SOFT_ZONE = 0.20       # rad before a joint limit where the progressive damper starts
RAGP_SOFT_DAMP = 60.0       # 1/s, damper strength at the limit itself
RAGP_PIVOT_BIAS = 0.25      # fraction of anchor error corrected per 1/60 s (pymunk default is 0.1)
RAGP_PIVOT_MAX_BIAS = 900.0 # px/s (x scale) ceiling on that correction, so it never snaps
RAGP_DRAG_QUAD = 3.0e-5     # quadratic air drag, 1/px; thin limbs get up to 2.5x, thick ones down to 0.6x
RAGP_DRAG_ANG = 0.12        # 1/s, angular air drag while a limb touches nothing
RAGP_ROLL_RES = 7.0         # 1/s, rolling resistance on a limb touching floor / wall / window
RAGP_STICK = 30.0           # 1/s, stand-in for static friction: bleeds creep speed on a touching limb
RAGP_STICK_V = 45.0         # px/s (x scale) below which that applies
RAGP_STICK_W = 0.9          # rad/s below which a touching limb's spin is bled too
RAGP_BOUNCE_V0 = 60.0       # px/s closing speed at or below which restitution is zero
RAGP_BOUNCE_V1 = 420.0      # px/s closing speed at which restitution is back to full


CT_BODY, CT_SCREEN, CT_WINDOW = RAGP_CT_BODY, RAGP_CT_SCREEN, RAGP_CT_WINDOW
_MAXV2 = RAGP_MAX_LIN_V * RAGP_MAX_LIN_V       # squared, so the hot loop rarely calls sqrt
_MAXV = RAGP_MAX_LIN_V
_sqrt = math.sqrt
_update_velocity = pymunk.Body.update_velocity if HAVE_PYMUNK else None

Impact = namedtuple("Impact", "owner kind strength point")


# ====================================================================== v2
# Realism pass. Nothing below changes RagWorld / RagSkeleton's public API:
#   _refine_spec                 rewrites the spec Pet hands in (head, masses)
#   RagSkeleton._refine_joints   tunes the joints once _build has made them
#   RagSkeleton._vel2            extra physics on top of the original _vel hook
#   RagSkeleton._survey_contacts per-frame contact flags that _vel2 reads
#   RagWorld._soften_bounce      speed-dependent restitution on floor / windows
_SOFTEN_OK = True


def _bone_kind(name):
    """Limb class from a body's debug label. Order matters: 'forearm' contains 'arm'."""
    n = str(name or "").lower()
    for key, kind in (("forearm", "forearm"), ("upperarm", "upperarm"), ("upper arm", "upperarm"),
                      ("thigh", "thigh"), ("calf", "calf"), ("shin", "calf"),
                      ("neck", "neck"), ("head", "neck"), ("pelvis", "pelvis"),
                      ("spine", "pelvis"), ("hip", "pelvis")):
        if key in n:
            return kind
    return "other"


def _refine_spec(bodies):
    """Return a refined copy of spec["bodies"]: a sane skull, and physical masses.

    1. HEAD. The skull circle sits past the neck->head bone, along its direction.
       On a chibi rig that bone is 5-10 px long and, in a bowed pose, can point
       down the spine, which buries the skull in the chest. When it is tiny or
       turns more than ~70 deg from the torso axis, it is re-aimed along the torso.
    2. MASS. weight = (2*r*L + pi*r^2 [+ skull circle]) x tissue density, which is
       what a 2D body of that exact capsule weighs, clamped so nothing is absurd.
       Pet normalises the weights afterwards, so only the ratios matter.
    The input is never mutated; any failure returns it untouched.
    """
    try:
        out = [dict(b) for b in bodies]
        if RAGP_HEAD_FIX:
            for b in out:
                par = b.get("parent")
                if not b.get("head") or par is None:
                    continue
                q = out[int(par)]
                ux, uy = q["c"][0] - q["p"][0], q["c"][1] - q["p"][1]
                ul = math.hypot(ux, uy)
                if ul < 1e-6:
                    continue
                ux /= ul
                uy /= ul
                hx, hy = b["c"][0] - b["p"][0], b["c"][1] - b["p"][1]
                hl = math.hypot(hx, hy)
                r = max(1.0, float(b.get("r", 4.0)))
                if hl < 1e-6 or (hx * ux + hy * uy) / hl < RAGP_HEAD_AXIS_MIN_DOT:
                    ln = max(hl, RAGP_HEAD_MIN_LEN * r)
                    b["c"] = (b["p"][0] + ux * ln, b["p"][1] + uy * ln)
        if RAGP_ANTHRO:
            area = []
            for b in out:
                L = math.hypot(b["c"][0] - b["p"][0], b["c"][1] - b["p"][1])
                r = max(1.0, float(b.get("r", 4.0)))
                a = 2.0 * r * L + math.pi * r * r
                if b.get("head"):
                    cr = r * RAGP_HEAD_CIRCLE
                    a += math.pi * cr * cr
                area.append(a * RAGP_DENSITY.get(_bone_kind(b.get("name")), 1.0))
            ta = sum(area) or 1.0
            old = [max(1e-6, float(b.get("w", 0.1))) for b in out]
            to = sum(old)
            mix = min(1.0, max(0.0, RAGP_ANTHRO_BLEND))
            w = [(1.0 - mix) * (o / to) + mix * (a / ta) for o, a in zip(old, area)]
            w = [min(RAGP_MASS_MAX, max(RAGP_MASS_MIN, x)) for x in w]
            tw = sum(w) or 1.0
            for b, x in zip(out, w):
                b["w"] = x / tw
        return out
    except Exception:
        return bodies


def wrap(a):
    """Shortest signed angle, in (-pi, pi]."""
    return (a + math.pi) % math.tau - math.pi


def _contact_key(a, b):
    """A stable, order-independent key for the pair of shapes in an arbiter."""
    ia, ib = id(a), id(b)
    return (ia, ib) if ia <= ib else (ib, ia)


def _keep_velocity(body, gravity, damping, dt):
    """A velocity_func that leaves `body.velocity` exactly as it was set.

    Chipmunk calls v_func on EVERY body each step, including KINEMATIC ones,
    and the default implementation recomputes v as (position - prev) * damping
    + gravity*dt - which throws away whatever velocity was just assigned. On the
    ragdoll bodies that is fine, because `_vel` runs afterwards and clamps it.
    On the cursor body it is fatal: the cursor is kinematic and is moved ONLY
    by the velocity we set on it, so the default function erases it, the joint
    has nothing to follow, and the limb never reaches the mouse at all.
    """


def _overlaps(a, b):
    """True if shapes `a` and `b` are touching right now.

    `shapes_collide` returns a ContactPointSet for a real contact, and in
    pymunk 7 RAISES for a non-contact rather than returning an empty set. Both
    are handled, and the answer is read off `.points` rather than off the truth
    of the result object, which is always true.
    """
    try:
        return len(a.shapes_collide(b).points) > 0
    except Exception:
        return False


def _diag_on():
    """Is ragdiag active? Imported lazily and cached so the hot path is one
    attribute load. Everything diagnostic in here is opt-in via --rag-diag;
    with it off this returns False and costs a dict lookup."""
    global _DIAG
    if _DIAG is None:
        try:
            import ragdiag
            _DIAG = [bool(ragdiag.on())]
        except Exception:
            _DIAG = [False]
    return _DIAG[0]


def _tilt_rigid(pts, a):
    """Rotate every point by `a` about the root's own origin, in place-ish.

    The start tilt has to be a rotation of the WHOLE skeleton, not a change to
    one body's angle. Rotating a parent moves its children, so setting
    root.angle after the pivots exist leaves every child anchor 10+ px from
    where the joint was told to hold it, and the solver resolves that as an
    impulse. Applying it here, to the raw coordinates, before a single body or
    joint is built, makes the tilt free: every joint starts satisfied.

    Returns a new list of (ax, ay, bx, by) tuples.
    """
    c, s = math.cos(a), math.sin(a)
    rx, ry = pts[0][0], pts[0][1]        # the root's origin is the pivot

    def rot(x, y):
        dx, dy = x - rx, y - ry
        return (rx + dx * c - dy * s, ry + dx * s + dy * c)
    out = []
    for ax, ay, bx, by in pts:
        nax, nay = rot(ax, ay)
        nbx, nby = rot(bx, by)
        out.append((nax, nay, nbx, nby))
    return out


def _lift_for_capsules(pts, radii):
    """Raise the skeleton so the lowest capsule SURFACE sits on the sole line.

    `pts` ends at the distal bone of each link, and the feet are the lowest of
    those bones - that is the `drop` distance Pet measures for window
    placement. But a capsule is a segment with round ends: the calf capsule ends
    AT the foot bone and its cap then hangs one radius below it, so building her
    exactly on the bone positions starts every ragdoll with her soles already
    buried in the floor. The solver answers that penetration with an upward
    push, which is the other half of the instant launch.

    Lifting by that same amount puts the surface on the line and leaves the
    penetration at zero. `drop` is unaffected: Pet keeps adding it to whatever
    the pelvis reports, so the render and the physics stay in step.

    Returns (points, lift).
    """
    sole = max(by for _ax, _ay, _bx, by in pts)
    surf = max(by + r for (_ax, _ay, _bx, by), r in zip(pts, radii))
    lift = surf - sole
    if lift <= 0.0:
        return pts, 0.0
    return [(ax, ay - lift, bx, by - lift) for ax, ay, bx, by in pts], lift


def _finite(*vals):
    return all(isinstance(v, float) and math.isfinite(v) for v in vals)


def _size(rect):
    """A rect's (w, h), for telling a resize apart from a move."""
    return (rect[2] - rect[0], rect[3] - rect[1])


# ------------------------------------------------------------------ the world
class RagWorld:
    """One physics world per App, shared by every pet on screen.

    Pets are told which skeleton is theirs (`add_skeleton`) and read their pose
    back each frame; the world owns the stepping, the screen walls, the real
    Windows and the collision callbacks, so two pets on one screen collide with
    each other without knowing the other one exists.
    """

    def __init__(self):
        self.space = pymunk.Space()
        self.space.iterations = RAGP_ITERATIONS
        self.space.collision_slop = RAGP_SLOP
        self.space.damping = RAGP_DAMPING
        self.gravity = 2600.0                 # replaced by the first skeleton that reports in
        self.rect = None                      # (l, t, r, b) of the home screen, logical px
        self._trace = 0                       # frames of --rag-trace output left
        self._trace_n = 0                     # frames printed so far (label)
        self._walls = []                       # the four screen segments, on static_body
        self._skels = {}                      # owner_id -> RagSkeleton
        self._wins = {}                       # hwnd -> dict(body, shape, rect, ...)
        self._ignore = set()                  # (id(shape), id(shape)) pairs to skip: limb/window
                                             # and, at spawn only, limb/limb (see _mute_spawn_overlaps)
        self._impacts = {}                    # owner_id -> {kind: Impact}
        self._win_pending = []                # windows still sliding towards their new rect
        self._wins_on = False
        self._acc = 0.0
        self._wall = 0.0                     # s of wall time, for the window slide deadlines
        self._body_owner = {}                  # pymunk body.id -> owner_id, for the collision callbacks
        self._anc = set()                     # any skeletons that need the self-collision guard
        self._shape_win = {}                  # id(window shape) -> hwnd
        self._dead = 0.0                      # seconds of contact, for rest detection
        self.g_mul = 1.0                      # Physics page: gravity multiplier (< 0 = falls up)
        self.grab_k = 1.0                     # Physics page: cursor grip 0..1
        self.throw_mul = 1.0                  # Physics page: x RAGP_GRAB_THROW_V on release
        # pymunk routes every collision of a pair of shapes to the most specific
        # handler registered for their two collision types. One handler per pair.
        self.space.on_collision(RAGP_CT_BODY, RAGP_CT_SCREEN, data="screen",
                                pre_solve=self._pre_solve_env,
                            begin=self._post_solve, separate=self._separate)
        self.space.on_collision(RAGP_CT_BODY, RAGP_CT_WINDOW, data="window",
                                pre_solve=self._pre_solve_win, begin=self._post_solve,
                                separate=self._separate)
        self.space.on_collision(RAGP_CT_BODY, RAGP_CT_BODY, data="pet",
                                pre_solve=self._pre_solve_self, begin=self._post_solve,
                                separate=self._separate)

    # ---------------------------------------------------------- screen barrier
    def set_screen(self, rect):
        """Rebuild the four walls around the home screen: (l, t, r, b) logical px."""
        rect = tuple(rect)
        if self.rect == rect:
            return
        self.rect = rect
        l, t, r, b = rect
        # Remove the old walls. They hang off space.static_body, which belongs
        # to the space and must not be removed from it - so the SHAPES go, one
        # at a time, and the shared body stays.
        for sh in self._walls:
            try:
                self.space.remove(sh)
            except Exception:
                pass
        self._walls = []
        body = self.space.static_body
        mo, ra = RAGP_WALL_MARGIN, RAGP_WALL_RADIUS
        # Each wall is a fat segment lying OUTSIDE the screen, so its inner face
        # sits exactly on the edge: a body cannot slip past it between two
        # substeps even at the velocity ceiling.
        segs = (((l - mo, t - mo), (r + mo, t - mo)),          # ceiling
                ((l - mo, b + mo), (r + mo, b + mo)),          # floor, inner face at floor_y()
                ((l - mo, t - mo), (l - mo, b + mo)),          # left
                ((r + mo, t - mo), (r + mo, b + mo)))          # right
        for a, c in segs:
            sh = pymunk.Segment(body, a, c, ra)
            sh.collision_type = RAGP_CT_SCREEN
            sh.friction = RAGP_ENV_FRICTION
            sh.elasticity = RAGP_ENV_ELASTICITY
            self.space.add(sh)
            self._walls.append(sh)

    # ------------------------------------------------------- real OS windows
    def sync_windows(self, wins, now, enabled):
        """Diff the tracker's window list against the colliders we have.

        `wins` is WinTracker.wins: (hwnd, l, t, r, b) in logical px, front to
        back, our own windows already excluded. Windows move between polls, so
        anything that shifted is either slid there over the poll interval
        (so a pet can be shoved along by it) or snapped.
        """
        if not enabled or not HAVE_PYMUNK:
            if self._wins:
                for h in list(self._wins):
                    self._drop_window(h)
                self._win_pending.clear()
            self._wins_on = False
            return
        self._wins_on = True
        l, t, r, b = self.rect or (0, 0, 1, 1)
        want = {}
        for h, wl, wt, wr, wb in wins:
            if wr < l or wl > r or wb < t or wt > b:      # lives on another monitor
                continue
            want[int(h)] = (float(wl), float(wt), float(wr), float(wb))
        # gone
        for h in list(self._wins):
            if h not in want:
                self._drop_window(h)
        # new / moved / resized
        for h, rect in want.items():
            w = self._wins.get(h)
            if w is None:
                self._add_window(h, rect, now)
            else:
                self._move_window(h, w, rect, now)

    def _add_window(self, h, rect, now):
        body = pymunk.Body(0, 0, body_type=pymunk.Body.KINEMATIC)
        cx, cy = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
        body.position = (cx, cy)
        w = max(1.0, rect[2] - rect[0]); hgt = max(1.0, rect[3] - rect[1])
        sh = pymunk.Poly.create_box(body, (w, hgt), 0)
        sh.collision_type = RAGP_CT_WINDOW
        sh.friction = RAGP_ENV_FRICTION
        sh.elasticity = RAGP_ENV_ELASTICITY
        self.space.add(body, sh)
        self._wins[h] = dict(body=body, shape=sh, rect=rect, t=now)
        self._shape_win[id(sh)] = h
        self._ignore_overlaps(sh)

    def _move_window(self, h, w, rect, now):
        dt = max(now - w["t"], RAGP_WIN_MIN_DT)
        w["t"] = now
        if _size(rect) != _size(w["rect"]):                # only a real resize rebuilds the box
            self._remove_window_body(w)
            self._wins.pop(h, None)
            self._shape_win.pop(id(w["shape"]), None)
            self._add_window(h, rect, now)
            return
        dx = (rect[0] + rect[2]) / 2.0 - w["body"].position[0]
        dy = (rect[1] + rect[3]) / 2.0 - w["body"].position[1]
        d = math.hypot(dx, dy)
        if d < 0.5:
            w["body"].velocity = (0, 0); w["rect"] = rect
            return
        if d >= RAGP_WIN_SNAP_DIST:                        # teleported, not dragged: snap it
            w["body"].position = ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)
            w["body"].velocity = (0, 0); w["rect"] = rect
            self._ignore_overlaps(w["shape"])
            return
        vx, vy = dx / dt, dy / dt
        sp = math.hypot(vx, vy)
        if sp > RAGP_WIN_MAX_V:
            vx, vy = vx * RAGP_WIN_MAX_V / sp, vy * RAGP_WIN_MAX_V / sp
        w["body"].velocity = (vx, vy)
        w["rect"] = rect
        self._win_pending = [q for q in self._win_pending if q[0] != h]
        self._win_pending.append((h, rect, now + min(dt, RAGP_CATCHUP) + RAGP_WIN_MIN_DT))
        # Deliberately NOT an ignore-until-clear here: a window that is merely
        # sliding from one poll to the next is being resolved continuously, and
        # it is supposed to shove whatever it runs into. Only a window that
        # appears out of nowhere (added, resized, or teleported) gets muted.

    def _forget_shapes(self, shape_ids):
        """Drop the ignore pairs belonging to shapes that no longer exist.

        Without this the set grows for the life of the process: id() is reused as
        soon as a shape is collected, so a stale pair can start muting a
        brand-new window.
        """
        if not self._ignore:
            return
        shape_ids = set(shape_ids)
        self._ignore = {k for k in self._ignore
                        if k[0] not in shape_ids and k[1] not in shape_ids}

    def _drop_window(self, h):
        w = self._wins.pop(h, None)
        if w is None:
            return
        self._shape_win.pop(id(w["shape"]), None)
        self._forget_shapes([id(w["shape"])])
        self._win_pending = [q for q in self._win_pending if q[0] != h]
        self._remove_window_body(w)

    def _remove_window_body(self, w):
        """Take a window's body AND its box out of the space.

        Both, not just the body. pymunk 7 does not cascade: Space.remove(body)
        detaches the body but leaves every shape that was added alongside it, so
        removing only the body leaves an invisible, immortal box in the space -
        still solid, still shoving ragdolls, with nothing on screen to explain
        it. That is precisely what a minimized window looked like: the tracker
        correctly drops it from its list, sync_windows correctly decides to
        remove it, and the collider stays anyway.
        """
        try:
            self.space.remove(w["shape"], w["body"])
        except Exception:
            pass

    def _ignore_overlaps(self, win_shape, skel=None):
        """Mute every (limb, window) pair that is genuinely overlapping right now.

        Chipmunk resolves a deep overlap by pushing the shapes apart as hard as
        it can, so a window that materialises on top of somebody - or a pet who
        goes limp inside one - launches her across the screen. Overlapping pairs
        are muted until they genuinely separate; nothing collides, so nothing
        pushes.

        The rule is that she is IN FRONT OF any window she overlaps when the
        ragdoll starts, because that is what the windows are for: she is drawn
        on top of them. The window turns solid again as soon as she has moved
        clear, which is the `separate` callback.

        The overlap test is `len(shapes_collide(...).points) > 0`, not the bare
        truthiness of the result. `shapes_collide` returns a ContactPointSet,
        which has no `__bool__` or `__len__`, so it is ALWAYS truthy - the bare
        test would mute everything, and since `separate` never fires for pairs
        that never touched, windows would go permanently inert. For the same
        reason this does NOT rely on the exception pymunk raises for a
        non-overlapping pair: that behaviour is not part of any contract, and
        raising and catching one exception per (limb, window) pair on every
        window event is both slow and fragile.
        """
        wsid = id(win_shape)
        for s in (self._skels.values() if skel is None else (skel,)):
            if s is None or s.detached:
                continue
            for sh in s.shapes:
                if _overlaps(win_shape, sh):
                    self._ignore.add((id(sh), wsid))

    def _advance_windows(self):
        """Finish any window slide whose poll interval has elapsed, then stop it."""
        for h, rect, deadline in list(self._win_pending):
            w = self._wins.get(h)
            if w is None:
                self._win_pending.remove((h, rect, deadline)); continue
            if self._wall < deadline:
                continue
            w["body"].position = ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)
            w["body"].velocity = (0, 0)
            self._win_pending.remove((h, rect, deadline))

    # ------------------------------------------------------------- collisions
    def _pre_solve_self(self, arb, space, data):
        """Mute a pet's own limbs when they are held together by a joint anyway.

        Self-collision (RAGP_SELF_COLLIDE) means a limb must not pass through her
        torso and head - without it she settles as a flat sprawl with her arms
        inside her own chest. But a parent and its DIRECT child share a pivot and
        permanently overlap by construction: their capsules are centred on the
        same joint point and each has a radius around it. Colliding them pushes
        the two apart against the pivot that is holding them together, and the
        solver loses - measured at 30 px of anchor error and a pet that never
        stops moving.

        So: adjacent pairs in the hierarchy (any ancestor/descendant, not just
        the immediate parent) are muted, everything else collides. The ancestor
        chain is what matters, because a shoulder and a hand overlap just as much
        as a shoulder and an upper arm once the arm is folded.

        Cheap: the same guard as _pre_solve, a dict lookup on the two body ids,
        and it returns before touching arb.shapes unless the pair is in the set.

        Two different mutes end up here. The ancestor set above covers a pair
        joined somewhere up the chain, for as long as she is in the world. The
        second check is the world's `_ignore` set, which carries two kinds of
        entry: (limb, window), and the spawn-time (limb, limb) pairs added by
        RagSkeleton._mute_spawn_overlaps. Both are keyed by shape id and both
        are transient - `_separate` drops each pair the moment those shapes move
        apart, which is what makes the limbs solid again once they have stopped
        overlapping. Verified against pymunk 7.3: setting `process_collision`
        to False suppresses the contact but NOT `begin`/`separate`, so a muted
        pair still tears down its arbiter normally.
        """
        # Both guards first, so the overwhelmingly common case - self-collision
        # off and nothing overlapping - returns without building a single
        # Python wrapper. `arb.bodies` and `arb.shapes` are not free.
        if not (self._anc or self._ignore):
            return True
        a, b = arb.bodies
        if a is None or b is None:
            return True
        if self._anc:
            skel = self._skels.get(self._body_owner.get(a.id))
            if skel is not None and ((a.id, b.id) in skel.anc or (b.id, a.id) in skel.anc):
                arb.process_collision = False
                return True
        if self._ignore:
            s = arb.shapes
            k1, k2 = id(s[0]), id(s[1])
            if (k1, k2) in self._ignore or (k2, k1) in self._ignore:
                arb.process_collision = False      # overlapping at spawn: let them settle in
        return True

    def _soften_bounce(self, arbiter):
        """v2: restitution that fades with closing speed. A resting limb meets the
        floor at about g*dt every substep; with a flat restitution that is a constant
        micro-bounce. Below RAGP_BOUNCE_V0 there is none, above RAGP_BOUNCE_V1 it is
        full, with a smoothstep between."""
        global _SOFTEN_OK
        if not _SOFTEN_OK:
            return
        try:
            if not arbiter.process_collision:
                return
            pts = arbiter.contact_point_set.points
            if not pts:
                return
            sa, sb = arbiter.shapes
            p = pts[0].point_a
            n = arbiter.normal
            va = sa.body.velocity_at_world_point(p)
            vb = sb.body.velocity_at_world_point(p)
            closing = -((vb.x - va.x) * n.x + (vb.y - va.y) * n.y)
            if closing <= RAGP_BOUNCE_V0:
                arbiter.restitution = 0.0
            elif closing < RAGP_BOUNCE_V1:
                t = (closing - RAGP_BOUNCE_V0) / (RAGP_BOUNCE_V1 - RAGP_BOUNCE_V0)
                arbiter.restitution = arbiter.restitution * t * t * (3.0 - 2.0 * t)
        except Exception:
            _SOFTEN_OK = False

    def _pre_solve_env(self, arbiter, space, data):
        self._soften_bounce(arbiter)

    def _pre_solve_win(self, arbiter, space, data):
        r = self._pre_solve(arbiter, space, data)
        self._soften_bounce(arbiter)
        return r

    def _pre_solve(self, arb, space, data):
        """Mute a window that appeared on top of her. See _ignore_overlaps.

        This runs on every window contact on every substep, so it must be as
        cheap as possible: `arb.shapes` builds two Python Shape wrappers, so
        when nothing is being ignored (the overwhelmingly common case) the empty
        set answers before any of that is touched.
        """
        if not self._ignore:
            return True
        shapes = arb.shapes
        a, b = id(shapes[0]), id(shapes[1])
        if (a, b) in self._ignore or (b, a) in self._ignore:
            arb.process_collision = False          # a window opened on top of her: let it pass
        return True

    def _separate(self, arb, space, data):
        # separate() also fires when a shape is removed from the space while it is
        # touching something, so the body may already be gone by now and its
        # shapes may have no body at all. Everything here has to tolerate that.
        try:
            shapes = arb.shapes
        except Exception:
            return
        if len(shapes) == 2:
            skel = self._skel_of(shapes)
            if skel is not None:
                skel.contacts.discard(_contact_key(shapes[0], shapes[1]))
            a, b = id(shapes[0]), id(shapes[1])
            self._ignore.discard((a, b)); self._ignore.discard((b, a))

    def _skel_of(self, shapes):
        """Which skeleton owns this contact, or None."""
        for s in shapes:
            b = s.body
            if b is None:
                continue
            o = self._body_owner.get(b.id)
            if o is not None:
                return self._skels.get(o)
        return None

    def _post_solve(self, arb, space, data):
        """Record the impact of a contact that has just started.

        This is registered on `begin` rather than `post_solve`, and that is a
        deliberate choice about cost, not correctness:

          - A pet lying still on the floor keeps one contact alive for the
            whole time she is down. `post_solve` fires on all of them every
            substep, so at four ragdolls that is hundreds of calls a frame, and
            every one of them builds two Python Body and two Shape wrappers to
            read a number. `begin` fires only on the frame a contact starts,
            which is exactly the frame a hit happened on.
          - `total_impulse` in `begin` is the impulse applied on the step that
            closed the contact, so it is the real impact.
          - Rest detection only needs to know a contact exists, and `begin`
            paired with `separate` gives that as a plain counter.
        """
        skel = None
        for b in arb.bodies:
            o = self._body_owner.get(b.id)
            if o is not None and self._skels.get(o) is not None:
                skel = self._skels[o]; break
        if skel is None:
            return
        # Rest detection: record WHICH contact is open, not how many. A plain
        # increment/decrement counter can be driven to zero by a separate with
        # no matching begin - which happens when a shape is removed mid-contact,
        # and when a muted pair churns - and once it is zero the `if contact > 0`
        # guard stops it ever counting again, so a pet lying still on the floor
        # reports "not touching anything" and never gets up. A set is exact:
        # adding is idempotent and so is removing a key that is not there.
        try:
            shapes = arb.shapes
            if len(shapes) == 2:
                skel.contacts.add(_contact_key(shapes[0], shapes[1]))
                skel._contact_wall = self._wall
        except Exception:
            pass
        # --rag-diag: name the contact and its impulse. The shove that starts a
        # ragdoll is one contact, on one frame; without this you see the speed
        # spike and have to guess which pair caused it.
        if _diag_on():
            try:
                import ragdiag
                names = ragdiag.skel_shape_names(skel)
                sa, sb = arb.shapes
                ragdiag.diag_contact(skel.owner,
                                     names.get(id(sa), "?"), names.get(id(sb), "?"),
                                     float(math.sqrt(mag)), data)
            except Exception:
                pass
        imp = arb.total_impulse
        mag = imp[0] * imp[0] + imp[1] * imp[1]
        if not (mag > 0.0) or not math.isfinite(mag):
            return
        mass = 0.0
        for b in arb.bodies:
            m = b.mass
            mass += m if m > 1e-6 else 1e-6
        strength = math.sqrt(mag) / (mass * RAGP_IMPACT_DIV)
        rec = self._impacts.setdefault(skel.owner, {})
        cur = rec.get(data)
        if cur is not None and cur.strength >= strength:
            return                             # only the strongest hit per kind per frame
        pts = arb.contact_point_set.points
        p = pts[0].point_b if pts else arb.bodies[0].position
        rec[data] = Impact(skel.owner, data, strength, (float(p[0]), float(p[1])))

    def pop_impacts(self, owner_id):
        """Impacts recorded for one pet since the last call, strongest per kind."""
        return list(self._impacts.pop(owner_id, {}).values())

    # ------------------------------------------------------------- tracing
    def trace(self, frames=RAGP_TRACE_FRAMES):
        """Print one line per frame for the first `frames` frames. --rag-trace.

        This is the instrument for "she launched the instant she went limp":
        a launch shows up immediately as a big anchor error, a big relative
        angle error, a pelvis that is nowhere near where the window says it is,
        or an ignore set that is empty when she spawned inside a window. All
        four are printed per frame, plus the raw window/pl pelvis pair, so the
        render side and the physics side can be compared directly.
        """
        self._trace = max(0, int(frames))    # frames still to print
        self._trace_n = 0                    # frames printed so far, for the label

    def _trace_step(self):
        if self._trace <= 0:
            return
        self._trace -= 1
        fno = self._trace_n            # counts UP: f0 is the first frame
        self._trace_n += 1
        for owner, skel in self._skels.items():
            if _diag_on():
                # ragdiag prints the same numbers with the limb names attached,
                # so running both would just double every line.
                import ragdiag
                ragdiag.diag_frame(owner, skel, fno, 60.0)
                continue
            p = skel.pose()
            anch, rel = skel.joint_error()
            sp = skel.speed()
            print(f"  [rag-trace f{fno:3d}] owner={owner:4d} "
                  f"pelvis=({p['x']:8.2f},{p['y']:8.2f}) "
                  f"v=({p['vx']:8.1f},{p['vy']:8.1f}) w={p['w']:6.2f} "
                  f"speed={sp:7.1f} anchor_err={anch:6.3f}px rel_err={rel:6.4f}rad "
                  f"contact={len(skel.contacts)} ignore={len(self._ignore)}")

    # -------------------------------------------------------- live settings
    def set_physics(self, g_mul=1.0, grab_k=1.0, throw_mul=1.0):
        """Physics page sliders. Cheap no-op unless something changed."""
        g_mul = float(g_mul); grab_k = min(1.0, max(0.02, float(grab_k)))
        self.throw_mul = max(0.0, float(throw_mul))
        if g_mul != self.g_mul:
            self.g_mul = g_mul
            self.space.gravity = (0.0, self.gravity * g_mul)
            for sk in self._skels.values():
                sk.apply_gravity()
        if grab_k != self.grab_k:
            self.grab_k = grab_k
            for sk in self._skels.values():
                sk.apply_grip()

    # ------------------------------------------------------------- skeletons
    def add_skeleton(self, owner_id, spec, kick=None):
        skel = RagSkeleton(self, owner_id, spec, kick)
        self._skels[owner_id] = skel
        self.gravity = 2600.0 * max(0.6, float(spec.get("scale", 1.0)))
        self.space.gravity = (0.0, self.gravity * self.g_mul)
        skel.apply_gravity()
        # A pet standing on the floor is IN FRONT of any window she overlaps -
        # that is where she is drawn - so going limp must not suddenly make
        # those windows solid. She is normally inside a large or maximised one:
        # the tracker only skips windows whose top is within RAGP_WALL_MARGIN of
        # the screen top, so a full-height window is very much in play. Without
        # this, the solver answers the overlap by shoving her out through the
        # nearest edge (usually the top, or the left) with nothing on screen to
        # explain it, which reads as an instant launch.
        #
        # Each pair is muted until the two genuinely separate, so the window
        # becomes solid again as soon as she is clear of it.
        for _h, w in list(self._wins.items()):
            self._ignore_overlaps(w["shape"], skel)
        return skel

    def remove_skeleton(self, skel):
        if skel is None:
            return
        if self._skels.get(skel.owner) is skel:
            self._skels.pop(skel.owner, None)
        skel.detach()

    def skel(self, owner_id):
        return self._skels.get(owner_id)

    # -------------------------------------------------------------- stepping
    def step(self, dt):
        """Advance the world by `dt` seconds in fixed substeps."""
        if not HAVE_PYMUNK or not self._skels:
            self._impacts.clear()
            return
        self._impacts.clear()                      # strongest hit per kind per frame
        self._trace_step()
        self._wall += min(dt, 0.25)
        # skel.contacts is NOT reset here: it is the live set of open contact
        # pairs, added in begin and discarded in separate, so it stays correct
        # across frames without any bookkeeping of its own.
        self._acc += min(dt, 0.25)
        # pre_step only does anything while somebody is holding a limb, and it
        # has to run before EVERY substep so the target keeps up, so track it
        # once per frame instead of walking every skeleton every substep.
        held = [s for s in self._skels.values() if s.grab_joint is not None]
        windows_moving = bool(self._win_pending)
        skels = list(self._skels.values())
        # How many substeps this frame will actually run, decided BEFORE the
        # first one. The cursor can only follow a straight line over a frame,
        # and each substep needs to know how far along that line to be.
        n_budget = min(RAGP_MAX_SUBSTEPS, int(self._acc / RAGP_SUBSTEP))
        for skel in held:
            skel.begin_frame(n_budget)
        n = 0
        while self._acc >= RAGP_SUBSTEP and n < RAGP_MAX_SUBSTEPS:
            for skel in held:
                skel.pre_step(n)
            if windows_moving:
                self._advance_windows()
            self.space.step(RAGP_SUBSTEP)
            # Containment, every substep. The walls alone are not enough: a
            # kinematic window has INFINITE mass, so when it pins somebody
            # against a wall the solver has no way to satisfy both constraints
            # and pops her through the wall instead. One cheap pass per substep
            # is what actually guarantees she is on the screen.
            if self.rect is not None:
                for skel in skels:
                    skel.contain(self.rect)
            n += 1
            self._acc -= RAGP_SUBSTEP
        if self._acc > RAGP_SUBSTEP:               # a slow frame: drop the backlog, never spiral
            self._acc = 0.0
        if n:
            for skel in self._skels.values():
                skel.post_step()


# ================================================================ one ragdoll
class RagSkeleton:
    """One pet's bodies, joints and grab, living in a shared RagWorld."""

    def __init__(self, world, owner, spec, kick=None):
        self.world, self.owner, self.spec = world, owner, spec
        self.space = world.space
        self.scale = float(spec.get("scale", 1.0))
        self.gravity = 2600.0 * max(0.6, self.scale)
        self.root = int(spec.get("root", 0))
        self.drop = float(spec.get("drop", 0.0))
        # The two rigid corrections applied at build (see _build). Kept because
        # they are not otherwise recoverable: `rest` is computed from the points
        # AFTER the tilt, so the tilt does not show up in body.angle - rest.
        self.tilt = 0.0                # rad the whole skeleton was rotated by
        self.lift = 0.0                # px it was raised to clear its own soles
        self.bodies = []          # pymunk.Body, parallel to spec["bodies"]
        self.shapes = []          # every pymunk.Shape of this character, in body order
        self.rest = []            # rest_angle per body
        self.moments = []         # moment per body
        self.lims = []            # symmetric joint limit per body
        self.radii = []           # capsule thickness per body, see contain()
        self.lengths = []         # capsule length per body, see contain()
        self._shapes_of = []      # shapes per BODY, parallel to self.bodies (see nearest)
        self.bones = []           # rig node index per body
        self.parents = []         # index of the parent body, or -1 for the root
        self.joints = []
        self.grab_body = None
        self.grab_joint = None
        self.grab_target = None
        self.grab_local = (0.0, 0.0)
        self.grab_at = (0.0, 0.0)
        self.grab_point = (0.0, 0.0)       # where on the limb she was picked up
        self._grab_from = (0.0, 0.0)       # cursor path this frame: start, end, substep count
        self._grab_to = (0.0, 0.0)
        self._grab_n = 1
        self.detached = False
        self.broken = False
        self.anc = set()                  # body-id pairs that must not self-collide
        self.contacts = set()                     # open contact pairs, see touching()
        self._contact_wall = -1e9              # world time a contact last opened
        self._build(kick)

    # ------------------------------------------------------------- build
    @staticmethod
    def _vel(body, gravity, damping, dt):
        """Per-body velocity clamp and NaN net, called once per substep per body.

        This is the hottest Python code in the module: 240 calls a second per
        limb, so it is written to be as short as possible - everything reached
        through is a module-level name or an attribute that already exists, and
        nothing is allocated unless the clamp actually fires. At four ragdolls
        on screen it is the difference between comfortably under a millisecond
        and not.

        `x == x` is the NaN test. The range check doubles as an infinity test,
        because inf fails it.
        """
        _update_velocity(body, body._rag_g, damping, dt)
        v = body.velocity
        x = v.x; y = v.y
        if not (-1e30 < x < 1e30 and -1e30 < y < 1e30):
            body.velocity = (0.0, 0.0); body.angular_velocity = 0.0
            body.position = body._rag_safe
            return
        w = body.angular_velocity
        if not (-1e30 < w < 1e30):
            body.angular_velocity = 0.0
        s = x * x + y * y
        if s > _MAXV2:
            k = _MAXV / _sqrt(s) if s == s else 0.0
            body.velocity = (x * k, y * k)

    @staticmethod
    def _vel2(body, gravity, damping, dt):
        """v2 per-substep hook: the original clamp / NaN net, then air drag, contact
        damping and the soft joint stops. Reads only attributes _build and
        _refine_joints set, all of which have safe defaults."""
        RagSkeleton._vel(body, gravity, damping, dt)
        v = body.velocity
        x = v.x
        y = v.y
        s = x * x + y * y
        if s != s:                      # NaN: the original hook has already dealt with it
            return
        w = body.angular_velocity
        cd = body._rag_cd
        if cd:                          # quadratic air drag
            k = 1.0 - cd * _sqrt(s) * dt
            if k < 0.5:
                k = 0.5
            x *= k
            y *= k
            s *= k * k
        if body._rag_ground:            # touching floor / wall / window
            if s < body._rag_sv2:       # stand-in for static friction: no endless creep
                k = 1.0 - RAGP_STICK * dt
                x *= k
                y *= k
            w *= 1.0 - RAGP_ROLL_RES * dt
            if -RAGP_STICK_W < w < RAGP_STICK_W:
                w *= 1.0 - RAGP_STICK * dt
        else:
            w *= 1.0 - RAGP_DRAG_ANG * dt
        par = body._rag_par
        if par is not None:             # progressive damper just before a joint limit
            rel = body.angle - par.angle - body._rag_rel0
            z = RAGP_SOFT_ZONE
            wr = w - par.angular_velocity
            hi = body._rag_hi - z
            lo = body._rag_lo + z
            if rel > hi and wr > 0.0:
                p = (rel - hi) / z
                w -= wr * (p if p < 1.0 else 1.0) * RAGP_SOFT_DAMP * dt
            elif rel < lo and wr < 0.0:
                p = (lo - rel) / z
                w -= wr * (p if p < 1.0 else 1.0) * RAGP_SOFT_DAMP * dt
        body.velocity = (x, y)
        body.angular_velocity = w

    def _refine_joints(self):
        """v2: anatomical joint ranges, firmer anchors, per-body drag and rest state.

        Runs once, at the end of _build, when every joint is satisfied (so the
        relative angles ARE the rest angles). Everything is looked up from the joints
        _build already made, so it follows whatever _build did. Ranges only ever
        TIGHTEN the spec's own limit, so pose()["lims"] stays a valid bound.
        """
        try:
            n = len(self.bodies)
            if n < 2:
                return
            idx = {b.id: i for i, b in enumerate(self.bodies)}
            names = [str(sb.get("name", "")) for sb in self.spec.get("bodies", [])]
            kinds = [_bone_kind(nm) for nm in names]
            while len(kinds) < n:
                kinds.append("other")
            mid = self.bodies[self.root].position.x
            sc = max(0.6, self.scale)
            # which side of the body does each limb chain hang from? (+1 = screen right)
            side = [0.0] * n
            for i in range(n):
                j, guard = i, 0
                while self.parents[j] >= 0 and self.parents[j] != self.root and guard < 16:
                    j = self.parents[j]
                    guard += 1
                ox = self.bodies[j].position.x - mid
                side[i] = 1.0 if ox > 1.0 else (-1.0 if ox < -1.0 else 0.0)
            # which rotation direction swings a limb OUTWARD, away from the midline
            out_sign = [0.0] * n
            for i in range(n):
                a = self.bodies[i].angle
                sn, cs = math.sin(a), math.cos(a)
                if side[i] == 0.0:
                    out_sign[i] = 0.0
                elif abs(sn) >= 0.3:
                    out_sign[i] = -side[i] * (1.0 if sn > 0.0 else -1.0)
                else:                   # nearly horizontal: outward means raising it
                    out_sign[i] = -(1.0 if cs > 0.0 else -1.0)
            limits, springs, pivots = {}, {}, {}
            for j in self.joints:
                ia, ib = idx.get(j.a.id), idx.get(j.b.id)
                if ia is None or ib is None:
                    continue
                if self.parents[ib] == ia:
                    child = ib
                elif self.parents[ia] == ib:
                    child = ia
                else:
                    continue
                if isinstance(j, pymunk.RotaryLimitJoint):
                    limits[child] = j
                elif isinstance(j, pymunk.DampedRotarySpring):
                    springs[child] = j
                elif isinstance(j, pymunk.PivotJoint):
                    pivots[child] = j
            for i, lj in limits.items():
                rng = RAGP_JOINT_RANGE.get(kinds[i])
                if rng is None:
                    continue
                outward, inward = rng
                if out_sign[i] > 0.0:
                    lo_r, hi_r = inward, outward
                elif out_sign[i] < 0.0:
                    lo_r, hi_r = outward, inward
                else:
                    lo_r = hi_r = max(outward, inward)
                cap = abs(self.lims[i]) if self.lims[i] else max(outward, inward)
                lo_r, hi_r = min(lo_r, cap), min(hi_r, cap)
                ch = self.bodies[i]
                par = self.bodies[self.parents[i]]
                rel0 = ch.angle - par.angle
                # RotaryLimitJoint keeps  min <= b.angle - a.angle <= max
                if lj.b.id == ch.id:
                    lj.min, lj.max = rel0 - lo_r, rel0 + hi_r
                else:
                    lj.min, lj.max = -(rel0 + hi_r), -(rel0 - lo_r)
                ch._rag_par = par
                ch._rag_rel0 = rel0
                ch._rag_lo = -lo_r
                ch._rag_hi = hi_r
            if RAGP_JOINT_K_MUL != 1.0 or RAGP_JOINT_DAMP_MUL != 1.0:
                for sp in springs.values():
                    sp.stiffness = sp.stiffness * RAGP_JOINT_K_MUL
                    sp.damping = sp.damping * RAGP_JOINT_DAMP_MUL
            for pj in pivots.values():
                pj.error_bias = pow(1.0 - RAGP_PIVOT_BIAS, 60.0)
                pj.max_bias = RAGP_PIVOT_MAX_BIAS * sc
            mean_r = sum(self.radii) / n
            for i, b in enumerate(self.bodies):
                b._rag_cd = RAGP_DRAG_QUAD * min(2.5, max(0.6, mean_r / max(1.0, self.radii[i]))) / sc
                b._rag_sv2 = (RAGP_STICK_V * sc) ** 2
        except Exception:
            if RAGP_DEBUG:
                raise

    def _survey_contacts(self):
        """v2: flag each limb that is touching the floor, a wall or a window right now.
        Called once per frame; _vel2 reads the flags during the next frame's substeps."""
        env = (RAGP_CT_SCREEN, RAGP_CT_WINDOW)
        for b in self.bodies:
            hit = [False]

            def cb(arb, hit=hit):
                if hit[0]:
                    return
                sa, sb = arb.shapes
                if sa.collision_type in env or sb.collision_type in env:
                    hit[0] = True
            try:
                b.each_arbiter(cb)
            except Exception:
                hit[0] = False
            b._rag_ground = hit[0]

    def _mute_spawn_overlaps(self):
        """Mute every self-collision pair that is ALREADY overlapping at spawn.

        `anc` covers ancestor/descendant pairs - the ones held together by a
        shared pivot. It does not cover siblings, and on a chibi rig the
        siblings overlap badly in the standing pose: thigh vs thigh, upper arm
        vs neck, hand vs thigh. Those pairs are not muted, so the ragdoll starts
        deep inside itself, and Chipmunk resolves a deep overlap by pushing the
        shapes apart as hard as it can. On the first substep she is kicked
        apart from herself - the pop.

        So the same trick `_ignore_overlaps` uses for windows: test for overlap
        now, mute those pairs, and let `_separate` un-mute each one the moment
        those shapes genuinely move apart. Nothing collides, so nothing pushes,
        and the limbs become solid again as soon as the spawn overlap is gone.
        Pairs that never overlap are untouched, so normal self-collision (arm
        through torso, head through arm) is unaffected.

        Only valid while `self.anc` is populated, i.e. only when
        RAGP_SELF_COLLIDE is on - with it off the whole character shares one
        collision group and none of this pair is ever tested. `detach` clears
        the entries via _forget_shapes, so they cannot outlive her and leak onto
        a new shape that happens to reuse the id.

        Must run after the bodies and shapes exist (so `_shapes_of` is
        populated) and after `anc` is built.
        """
        n = len(self.bodies)
        world = self.world
        for i in range(n):
            for j in range(i + 1, n):
                # An ancestor pair is muted for the whole ragdoll anyway.
                if (self.bodies[i].id, self.bodies[j].id) in self.anc:
                    continue
                for a in self._shapes_of[i]:
                    for b in self._shapes_of[j]:
                        if _overlaps(a, b):
                            world._ignore.add((id(a), id(b)))

    def _build(self, kick):
        spec = self.spec
        px, py = float(spec.get("px", 0.0)), float(spec.get("py", 0.0))
        sbody = _refine_spec(spec["bodies"])   # [v2] sane skull + physical masses
        # ---- the two corrections that must happen BEFORE anything is created ----
        # Everything below is derived from these transformed points, so the bodies
        # and the joints between them are born exactly consistent.
        pts = [(px + float(b["p"][0]), py + float(b["p"][1]),
                px + float(b["c"][0]), py + float(b["c"][1])) for b in sbody]
        radii = [max(1.0, float(b.get("r", 4.0))) for b in sbody]
        pts, self.lift = _lift_for_capsules(pts, radii)
        self.tilt = random.uniform(-RAGP_START_TILT, RAGP_START_TILT)
        pts = _tilt_rigid(pts, self.tilt)
        # masses: normalise the weights so the whole character weighs 1.0
        tw = sum(max(1e-6, float(b.get("w", 0.1))) for b in sbody) or 1.0
        for i, sb in enumerate(sbody):
            ax, ay, bx, by = pts[i]
            length = math.hypot(bx - ax, by - ay)
            rest = math.atan2(by - ay, bx - ax) if length > 1e-6 else 0.0
            mass = max(1e-4, float(sb.get("w", 0.1)) / tw)
            rad = max(1.0, float(sb.get("r", 4.0)))
            body = pymunk.Body(mass, 1.0)
            body.position = (ax, ay)
            body.angle = rest
            body._rag_g = (0.0, self.gravity)             # her own scale's gravity
            body._rag_safe = (ax, ay)
            # [v2] per-body state read by _vel2 (safe defaults; _refine_joints fills the real values)
            body._rag_cd = 0.0
            body._rag_ground = False
            body._rag_sv2 = 0.0
            body._rag_par = None
            body._rag_rel0 = 0.0
            body._rag_lo = -9.0
            body._rag_hi = 9.0
            body.velocity_func = self._vel2
            seg = pymunk.Segment(body, (0.0, 0.0), (length, 0.0), rad)
            moment = pymunk.moment_for_segment(mass, (0.0, 0.0), (length, 0.0), rad)
            shapes = [seg]
            if sb.get("head"):
                # The skull is a circle a little past the head bone, so the head
                # tips over its neck instead of wobbling on a bare stick.
                cr = rad * RAGP_HEAD_CIRCLE
                co = (length + cr * RAGP_HEAD_OFFSET, 0.0)
                cm = mass * 0.35
                circ = pymunk.Circle(body, cr, co)
                moment += pymunk.moment_for_circle(cm, 0.0, cr, co)
                shapes.append(circ)
            body.moment = max(1e-4, moment)
            for sh in shapes:
                sh.collision_type = RAGP_CT_BODY
                sh.friction = RAGP_BODY_FRICTION
                sh.elasticity = RAGP_BODY_ELASTICITY
                # Cross-pet collisions are decided by GROUP: pymunk rejects any
                # pair sharing a non-zero group, so giving every shape of one
                # character the same group means her limbs never collide with
                # each other but always with a different pet's.
                #
                # RAGP_SELF_COLLIDE turns that group OFF (0) and moves the
                # within-character decision into RagWorld._pre_solve_self, which
                # can mute individual pairs instead of the whole set - the group
                # filter is all-or-nothing, and all-or-nothing is wrong here
                # because only the ADJACENT pairs need muting. Categories/masks
                # cannot do it either: a group of 0 makes them the rule, but
                # there are only 32 bits and every pet would need its own block.
                sh.filter = pymunk.ShapeFilter(
                    group=0 if RAGP_SELF_COLLIDE else self.owner + 1)
            self.world._body_owner[body.id] = self.owner
            self.space.add(body, *shapes)
            self.bodies.append(body); self.shapes.extend(shapes)
            self._shapes_of.append(shapes)
            self.rest.append(rest); self.moments.append(body.moment)
            self.lims.append(float(sb.get("lim", RAGP_TORSO_LIM)))
            self.radii.append(rad)
            self.lengths.append(length)
            self.bones.append(int(sb["bone"]))
            par = sb.get("parent")
            self.parents.append(-1 if par is None else int(par))
        # Joints, parents before children. Three per link:
        #   PivotJoint       keeps the child's own origin welded to the parent,
        #   RotaryLimitJoint bounds the relative angle,
        #   DampedRotarySpring pulls it back to the pose it started in, at
        #     RAGP_LIMP_K of full strength - see the note there for why full
        #     strength is wrong: it stands her back up.
        for i, sb in enumerate(sbody):
            p = self.parents[i]
            if p < 0:
                continue
            pb, cb = self.bodies[p], self.bodies[i]
            # UNWRAPPED, and this matters. pymunk's RotaryLimitJoint and
            # DampedRotarySpring both measure `b.angle - a.angle` as-is, without
            # wrapping it into (-pi, pi]. On this rig the torso capsules point up
            # (rest about -pi/2) while the thighs and arms point down (about
            # +pi/2), so the true relative angle is very nearly +pi -- and
            # wrap() maps that to -pi, a 2*pi error handed straight to the
            # spring as a gigantic torque on the very first substep. Measured on
            # the real Mika spec, `l thigh` is +185.3 deg while wrap() says
            # -174.7 deg. That single joint is enough to throw her up and to the
            # left on the frame she goes limp.
            #
            # wrap() is still right for OUTPUT, in pose() and phi(), where a
            # shortest-path angle is what the caller wants. It is just never
            # right as an INPUT to a constraint.
            rel = self.rest[i] - self.rest[p]
            lim = self.lims[i]
            # RotaryLimitJoint bounds b.angle - a.angle, so the rest offset comes
            # out of the limits rather than out of the bodies' own angles.
            links = (pymunk.PivotJoint(pb, cb, pb.world_to_local(cb.position), (0.0, 0.0)),
                     pymunk.RotaryLimitJoint(pb, cb, rel - lim, rel + lim),
                     pymunk.DampedRotarySpring(pb, cb, rel,
                                               float(sb.get("k", RAGP_TORSO_K)) * self.moments[i]
                                               * RAGP_LIMP_K,
                                               float(sb.get("damp", RAGP_TORSO_DAMP)) * self.moments[i]
                                               * RAGP_LIMP_DAMP))
            links[2].max_force = RAGP_SPRING_MAX_F * self.gravity
            self.joints.extend(links)
            self.space.add(*links)
        # Every ancestor/descendant body pair, keyed by pymunk body id in both
        # orders so the pre_solve guard is one dict lookup and no sorting. These
        # are the pairs that share a joint somewhere up the chain and overlap by
        # construction, so they must not collide with each other. See
        # RagWorld._pre_solve_self.
        if RAGP_SELF_COLLIDE:
            self.anc = set()
            for i in range(len(self.bodies)):
                node = self.parents[i]
                # `is not None` first: the ROOT's parent is None, and `None >= 0`
                # is a TypeError in Python 3, not False. Testing it the other way
                # round silently built an empty set for every real rig, so
                # self-collision was on with nothing muted - which is the joint-
                # fighting case this exists to prevent.
                while node is not None and node >= 0:
                    self.anc.add((self.bodies[i].id, self.bodies[node].id))
                    self.anc.add((self.bodies[node].id, self.bodies[i].id))
                    node = self.parents[node]
            self.world._anc.add(id(self))
        # initial motion, and nothing that moves a joint anchor
        vx, vy, w = (kick or (0.0, 0.0, 0.0))[:3]
        for i, body in enumerate(self.bodies):
            body.velocity = (float(vx), float(vy))
            # As a SPIN, not an angle offset. Setting body.angle here would move
            # the body away from the point its parent's pivot was anchored to,
            # so every joint would start violated and the solver would spend its
            # first few substeps snapping them back together - which is a shove,
            # and it reads as her being flung the instant she goes limp. The
            # pelvis tilt is applied as one rigid rotation before the joints
            # exist (see the top of _build); what is left here is only a rate.
            body.angular_velocity = random.uniform(-RAGP_START_SPIN, RAGP_START_SPIN)
        root = self.bodies[self.root]
        root.angular_velocity += float(w)
        # After the bodies exist (the overlap test needs real shapes) and after
        # `anc` is built (so it can skip the pairs that are muted regardless).
        if RAGP_SELF_COLLIDE:
            self._mute_spawn_overlaps()
        self._refine_joints()   # [v2]

    # ------------------------------------------------------------- stepping
    def joint_error(self):
        """(max anchor error px, max relative-angle error rad) right now.

        The two numbers that say whether the skeleton is being solved or is
        fighting itself. Both are ZERO at build by construction and should stay
        small; a large angle error means a joint's rest angle disagrees with
        where its bodies actually are, which is what a wrapped rest angle or a
        post-hoc angle offset produces, and it shows up on screen as her being
        flung the instant she goes limp. Used by --rag-trace and by the tests.
        """
        anch = rel = 0.0
        k = 0
        for i, parent in enumerate(self.parents):
            if parent < 0:
                continue
            piv, spring = self.joints[k], self.joints[k + 2]
            pb, cb = self.bodies[parent], self.bodies[i]
            pa = pb.local_to_world(piv.anchor_a)
            ca = cb.local_to_world(piv.anchor_b)
            d = math.hypot(pa[0] - ca[0], pa[1] - ca[1])
            if d > anch:
                anch = d
            e = abs((cb.angle - pb.angle) - spring.rest_angle)
            if e > rel:
                rel = e
            k += 3
        return anch, rel

    def begin_frame(self, n):
        """Latch where the cursor is heading, once per frame.

        The cursor can only be moved along a straight line over one frame, so
        the whole frame's motion has to be known before the first substep runs.
        `n` is how many substeps this frame will take; each one then advances
        the target one n-th of the way, instead of being teleported and then
        integrated a second time.
        """
        if self.grab_joint is None or self.grab_target is None:
            return
        body = self.grab_target
        self._grab_from = (body.position.x, body.position.y)
        self._grab_to = self.grab_at
        self._grab_n = max(1, int(n))

    def pre_step(self, i=0):
        """Advance the kinematic cursor body to where it should be this substep.

        Only the VELOCITY is set. Assigning position here as well was the jank:
        the target jumped to the cursor, the space step then integrated that
        velocity again, and the pair fought - the target ended up roughly
        error*3.75 ahead of the cursor every substep and then snapped back, so
        the limb juddered instead of hanging.
        """
        if self.grab_joint is None or self.grab_target is None:
            return
        body = self.grab_target
        fx, fy = self._grab_from
        tx, ty = self._grab_to
        t = (i + 1) / self._grab_n
        # `desired` is an ABSOLUTE point on the line from where the cursor was
        # at the start of the frame to where the mouse is now. Writing it as
        # (to - from) * t instead makes it a delta measured from the origin, so
        # the first substep asks for -916 px of travel to close a 1.75 px gap:
        # a 220000 px/s lunge, which flings the cursor off the screen and is then
        # corrected on the next substep. That alternation is the judder.
        want_x = fx + (tx - fx) * t
        want_y = fy + (ty - fy) * t
        body.velocity = ((want_x - body.position.x) / RAGP_SUBSTEP,
                         (want_y - body.position.y) / RAGP_SUBSTEP)

    def contain(self, rect):
        """Put any body that has escaped the screen rect back on it.

        The walls are fat segments with radius 60, and that stops anything
        moving on its own. It does not stop a KINEMATIC window from pinning her
        against one: the window has infinite mass, so the contact has no
        solution that satisfies both bodies and the solver resolves it by
        popping her through the wall - which is exactly what a window dragged
        across the screen used to do.

        So the position invariant is enforced here rather than trusted to the
        solver. The clamp is on each body's WHOLE extent, not just its origin:
        a capsule is a segment with round ends, so once it is at an angle its
        far end reaches well past its own centre, and clamping the centre alone
        still leaves a limb lying through the floor. Only the offending
        component of the velocity is killed, so she slides along a wall instead
        of sticking to it, and `_rag_safe` follows so a later blow-up resets her
        here, not outside.

        Four comparisons per body per substep, and the trigonometry is skipped
        entirely for any body nowhere near an edge - which is nearly all of
        them, nearly always.
        """
        l, t, r, b = rect
        radii, lengths = self.radii, self.lengths
        for i, body in enumerate(self.bodies):
            x, y = body.position.x, body.position.y
            rad = radii[i]
            L = lengths[i]
            # Conservative skip: a body reaches at most L + rad from its own
            # origin in either axis, so only a body whose ORIGIN is that far
            # inside on both axes is guaranteed clear of every face. Getting this
            # the wrong way round skips precisely the bodies at risk, which is
            # how an earlier version of this left a pelvis 13 px through the
            # floor while reporting that it had been checked.
            if (l + rad + L <= x <= r - rad - L and t + rad + L <= y <= b - rad - L):
                continue                    # nowhere near an edge: nothing to do
            a = body.angle
            dx, dy = L * math.cos(a), L * math.sin(a)
            # how far the capsule reaches past its own origin, each way
            lo_x, hi_x = (dx if dx < 0.0 else 0.0), (dx if dx > 0.0 else 0.0)
            lo_y, hi_y = (dy if dy < 0.0 else 0.0), (dy if dy > 0.0 else 0.0)
            nx, ny = x, y
            if x + lo_x - rad < l:
                nx = l - lo_x + rad
            elif x + hi_x + rad > r:
                nx = r - hi_x - rad
            if y + lo_y - rad < t:
                ny = t - lo_y + rad
            elif y + hi_y + rad > b:
                ny = b - hi_y - rad
            if nx == x and ny == y:
                continue
            # pymunk's Body.position setter also moves the internal previous
            # position, so this reads as "she was already here" and does not
            # inject a phantom velocity. Verified: teleporting a body 13 px and
            # stepping leaves its velocity unchanged.
            body.position = (nx, ny)
            v = body.velocity
            body.velocity = (0.0 if nx != x else v.x, 0.0 if ny != y else v.y)
            body._rag_safe = (nx, ny)

    def post_step(self):
        """[v2] refresh the per-limb contact flags, then the original once-per-frame work."""
        self._survey_contacts()
        self._post_step_v1()

    def _post_step_v1(self):
        """Once per frame: remember a known-good position, and catch a blow-up.

        The per-substep velocity clamp already stops any single body running
        away, so this only has to notice the case where a solver went unstable
        anyway; Pet then drops her and puts her back on her feet.
        """
        worst = 0.0
        for body in self.bodies:
            p = body.position
            x, y = p.x, p.y
            if x == x and y == y and -1e30 < x < 1e30 and -1e30 < y < 1e30:
                body._rag_safe = (x, y)
            else:
                self.broken = True
                body.position = body._rag_safe
            v = body.velocity
            s = v.x * v.x + v.y * v.y
            if s > worst:
                worst = s
        if worst > RAGP_BLAST_V * RAGP_BLAST_V:
            self.broken = True
            for body in self.bodies:
                body.velocity = (0.0, 0.0); body.angular_velocity = 0.0

    # ----------------------------------------------------------------- pose
    def pose(self):
        """Everything the pet needs to draw herself this frame."""
        r = self.bodies[self.root]
        phi = [wrap(b.angle - a) for b, a in zip(self.bodies, self.rest)]
        v = r.velocity
        return dict(x=float(r.position[0]), y=float(r.position[1]), angle=float(r.angle),
                    phi=phi, vx=float(v[0]), vy=float(v[1]),
                    w=float(r.angular_velocity), rest=self.rest[self.root],
                    bones=self.bones, parents=self.parents, lims=self.lims)

    def phi(self):
        return [wrap(b.angle - a) for b, a in zip(self.bodies, self.rest)]

    def body_ends(self):
        """[(proximal, distal, radius)] in GLOBAL screen px, per body.

        Used by the tests and by --rag-debug to see where physics thinks her
        joints are. Segment shapes report `a` and `b` in the body's LOCAL frame,
        so they are transformed into world coordinates here; returning the raw
        local values would silently compare unrotated numbers against a posed
        rig.
        """
        out = []
        for b in self.bodies:
            for sh in b.shapes:
                if isinstance(sh, pymunk.Segment):
                    a = b.local_to_world((sh.a.x, sh.a.y))
                    c = b.local_to_world((sh.b.x, sh.b.y))
                    out.append(((float(a[0]), float(a[1])), (float(c[0]), float(c[1])), sh.radius))
                    break
        return out

    def lowest_point(self):
        """Deepest y any of her shapes reaches, global screen px."""
        lo = -1e18
        for sh in self.shapes:
            bb = sh.bb
            if bb is not None and bb[3] > lo:
                lo = bb[3]
        return lo

    def speed(self):
        return max((b.velocity.length for b in self.bodies), default=0.0)

    def touching(self):
        """True when at least one limb is in contact with anything.

        Tracked by the world's collision handler rather than walked here:
        `each_arbiter` takes a callback rather than returning a generator.

        Two details, both measured rather than assumed:

          - The open pairs are a SET of shape-pair keys, not a counter. A
            counter looks equivalent and is not: `separate` can fire without a
            matching `begin`, and a guarded decrement saturates at zero and then
            stops counting altogether, so a pet lying still on the floor reports
            "touching nothing" forever. Set membership is idempotent both ways.

          - There is a short GRACE on top of that. A pet at rest does not have
            stable contacts: measured on the drop test, the open-pair count
            flickers between 0 and 7 from one frame to the next while her
            lowest point sits 0.04 px from the floor. A bare bool() therefore
            reports "airborne" on some frames of a pet lying on the ground, the
            rest timer resets on each one, and she never reaches the threshold
            to get up. So she counts as touching if a contact has opened at any
            point in the last RAGP_CONTACT_GRACE seconds - which is what "resting
            on the floor" means to the code that asks.
        """
        if self.contacts:
            return True
        return (self.world._wall - self._contact_wall) < RAGP_CONTACT_GRACE

    # ------------------------------------------------------------- grab
    def nearest(self, point, max_dist=None):
        """Closest limb to a screen point, as (body, distance).

        Iterates BODIES and their shapes, because `self.shapes` is not
        parallel to `self.bodies`: the head body carries two shapes (its
        segment plus the skull circle), so indexing bodies with a shape index
        hands back the wrong limb for everything after the head - you click a
        hand and she is picked up by a leg.

        The distance is a real point query against each shape rather than the
        shape's bounding box. A capsule's box is much larger than the capsule,
        so for any diagonal limb the box answer is simply wrong, and two
        crossing limbs can order either way round.
        """
        md = RAGP_GRAB_RADIUS * max(0.6, self.scale) if max_dist is None else max_dist
        px, py = float(point[0]), float(point[1])
        best, bd = None, md
        for i, body in enumerate(self.bodies):
            for sh in self._shapes_of[i]:
                # pymunk's point_query takes ONE tuple, and reports a NEGATIVE
                # distance for a point inside the shape (the penetration depth).
                # Clamping at zero turns that into the quantity actually wanted:
                # 0 anywhere on the limb, and the true gap outside it.
                #
                # Both details matter. Called with two scalars it raises
                # TypeError, which - if swallowed - turns every lookup into "no
                # shape found" and silently degrades this to nearest-centre.
                # Taking abs() instead of clamping makes a point buried in a
                # thick torso capsule look further away than one grazing a thin
                # forearm, which is backwards.
                d = sh.point_query((px, py)).distance
                if d < 0.0:
                    d = 0.0
                if d < bd:
                    bd, best = d, body
        if best is None:                      # nothing within reach: nearest centre
            for body in self.bodies:
                d = math.hypot(body.position[0] - px, body.position[1] - py)
                if d < bd:
                    bd, best = d, body
        if best is None:
            return None
        return best, bd

    def grab(self, point, target=None):
        """Hold the limb nearest `point` (global screen px) at `target`.

        The anchor is the point that was clicked, expressed in the limb's own
        frame - not the limb's origin. Anchoring at the origin makes the limb
        snap its origin to the cursor the instant you grab it, which is a jump
        nobody asked for; anchoring at the click means she hangs from exactly
        where she was picked up, so grabbing her by the hand and by the shoulder
        both look right.

        `max_bias` is what lets the joint CLOSE a position error. At 0 the joint
        can only match velocity, so a limb that falls behind the cursor never
        catches up and she trails the mouse. It is a rate in px/s, which is the
        natural unit here: fast enough to look rigid, slow enough not to fire a
        huge correction impulse when something interrupts her.
        """
        self.release_grab()
        found = self.nearest(point)
        if found is None:
            return False
        body, _ = found
        tx, ty = target if target is not None else point
        kin = pymunk.Body(0, 0, body_type=pymunk.Body.KINEMATIC)
        kin.position = (tx, ty)
        kin.velocity_func = _keep_velocity    # nothing may overwrite the cursor's velocity
        # where on the limb the user actually clicked, in the limb's frame
        anchor_b = body.world_to_local(point)
        joint = pymunk.PivotJoint(kin, body, (0.0, 0.0), anchor_b)
        # ~40x her weight: firm enough to swing her, not so firm that a window
        # or a wall can lever her through one.
        self.space.add(kin, joint)
        self.grab_body, self.grab_joint, self.grab_target = body, joint, kin
        self.apply_grip()
        self.grab_at = (tx, ty)
        self._grab_from, self._grab_to, self._grab_n = (tx, ty), (tx, ty), 1
        self.grab_point = (float(point[0]), float(point[1]))
        return True

    def apply_gravity(self):
        """Per-body gravity = her scale's g x the world's gravity multiplier."""
        g = (0.0, self.gravity * getattr(self.world, "g_mul", 1.0))
        for b in self.bodies:
            b._rag_g = g
            try:
                b.activate()
            except Exception:
                pass

    def apply_grip(self):
        """Grab joint force / pull speed for the world's grip strength (1 = original)."""
        j = self.grab_joint
        if j is None:
            return
        k = getattr(self.world, "grab_k", 1.0)
        # Below ~1/40 of the original force she can no longer be lifted at all.
        j.max_force = RAGP_GRAB_FORCE * self.gravity * max(0.02, k * k)
        j.max_bias = RAGP_GRAB_MAX_BIAS * max(0.05, k)

    def move_grab(self, target):
        if self.grab_joint is not None:
            self.grab_at = (float(target[0]), float(target[1]))

    def release_grab(self):
        """Let go. The limbs keep the velocity they had, capped.

        The velocity is NOT zeroed: dragging her through the world is what gives
        her the momentum for a throw, and the swing she picked up is exactly
        what should carry. But a fling through the physics world can build up
        far more than the old rod ever could, so each limb is capped at
        RAGP_GRAB_THROW_V - the same 3000 px/s the rod threw at - before the
        joint comes off. Without it a fast drag can fling her off the screen.
        """
        if self.grab_joint is None:
            return
        cap = RAGP_GRAB_THROW_V * getattr(self.world, "throw_mul", 1.0)
        for body in self.bodies:
            v = body.velocity
            s = v.x * v.x + v.y * v.y
            if s > cap * cap:
                k = cap / math.sqrt(s)
                body.velocity = (v.x * k, v.y * k)
        try:
            self.space.remove(self.grab_joint)
            self.space.remove(self.grab_target)
        except Exception:
            pass
        self.grab_joint = self.grab_target = self.grab_body = None

    # ------------------------------------------------------------- shoving
    def impulse(self, point, impulse, body=None):
        """Push the limb nearest `point` (global screen px) by `impulse`."""
        if body is None:
            found = self.nearest(point, max_dist=1e9)
            if found is None:
                return False
            body = found[0]
        body.apply_impulse_at_world_point((float(impulse[0]), float(impulse[1])),
                                          (float(point[0]), float(point[1])))
        return True

    def shove(self, cursor, power=1.0):
        """Click / Launch: push her away from the cursor, the legacy direction and size."""
        p = self.pose()
        s = max(0.6, self.scale)
        ix = max(-RAGP_SHOVE_CLAMP, min(RAGP_SHOVE_CLAMP, (p["x"] - cursor[0]) * RAGP_SHOVE_SIDE)) * power
        iy = -random.uniform(*RAGP_SHOVE_UP) * s * power
        self.impulse((p["x"], p["y"]), (ix, iy))
        root = self.bodies[self.root]
        root.angular_velocity += random.uniform(-8.0, 8.0) * power

    def explode_guard(self):
        """True when something went non-finite and she must be dropped."""
        if self.broken:
            return True
        for b in self.bodies:
            p = b.position
            if not (math.isfinite(p[0]) and math.isfinite(p[1])) or not math.isfinite(b.angle):
                return True
        return False

    def outside(self, rect, height):
        """True when her pelvis has left the screen by more than one body height."""
        if not rect:
            return False
        l, t, r, b = rect
        x, y = self.bodies[self.root].position
        m = height * RAGP_OUTSIDE_H
        return x < l - m or x > r + m or y < t - m or y > b + m

    def snap_inside(self, rect, height):
        """Teleport the whole skeleton back onto the screen, dead still."""
        if not rect:
            return
        l, t, r, b = rect
        cx, cy = (l + r) / 2.0, (b - height * 0.25)
        p = self.bodies[self.root].position
        dx, dy = cx - p[0], cy - p[1]
        for body in self.bodies:
            body.position = (body.position[0] + dx, body.position[1] + dy)
            body.velocity = (0.0, 0.0); body.angular_velocity = 0.0
            body._rag_safe = (body.position[0], body.position[1])

    def stop(self):
        for b in self.bodies:
            b.velocity = (0.0, 0.0); b.angular_velocity = 0.0

    # ------------------------------------------------------------- teardown
    def detach(self):
        """Take her out of the world but keep every number, for the get-up blend."""
        if self.detached:
            return
        self.release_grab()
        self.world._anc.discard(id(self))
        self.anc = set()
        for j in self.joints:
            try:
                self.space.remove(j)
            except Exception:
                pass
        self.joints = []
        self.contacts.clear()          # separate() may fire again during teardown
        for b in self.bodies:
            self.world._body_owner.pop(b.id, None)
        # Her limbs are leaving the world, so every pair naming one has to go
        # with them. `separate` will not fire during teardown, so without this
        # the mute would outlive her and id() reuse would eventually attach it
        # to somebody else's window.
        self.world._forget_shapes([id(sh) for sh in self.shapes])
        # The SHAPES go with the bodies. pymunk 7 does not cascade on remove, so
        # detaching the bodies alone leaves every capsule behind in the space as
        # an invisible, still-solid collider: measured at 12 ghosts per pet,
        # i.e. one whole set per get-up, each one quietly shoving whoever walked
        # into where she used to be lying. Remove them explicitly.
        try:
            self.space.remove(*self.shapes)
        except Exception:
            pass
        for b in self.bodies:
            try:
                self.space.remove(b)
            except Exception:
                pass
        self.detached = True