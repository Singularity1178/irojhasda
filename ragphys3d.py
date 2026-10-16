#!/usr/bin/env python3
"""
Fully 3D ragdoll for the desktop pets   (cfg["ragdoll_engine"] = "3d")
=======================================================================
The pymunk engine (ragphys.py) lays her out flat in the plane of the screen.
This one gives the world a thin slab of DEPTH:

  * nobody ever moves in that depth while on her feet - every student stands,
    walks and jumps exactly in the middle of it (z = 0);
  * only once she goes limp can her pelvis, head and limbs fall into it, so a
    body topples toward you or away from you, twists onto its side, lands on
    its back with an arm flung forward, crosses one leg over the other ...
  * getting back up blends every bone home and puts her back at z = 0
    (that part lives in bapet/pet_rag3d.py).

Engine
------
Position-based dynamics: Jakobsen's "Advanced Character Physics" (the Hitman
ragdoll) run with Muller's small-step XPBD scheme. It is what a lot of shipped
ragdolls use, because unlike a stiff impulse solver it cannot explode.

  particles  one per joint (pelvis, hips, spine, neck, skull, shoulders, elbows,
             hands, knees, feet), each with a real mass share and a collision
             radius. Explicit velocity; positions are predicted, then projected
             onto the constraints, in small fixed substeps.
  torso      the pelvis group and the chest group are each a RIGID cluster,
             held rigid by shape matching (Muller 2005) with the rotation pulled
             out by Muller 2016's warm-started quaternion iteration. Those two
             rotations are also exactly what the renderer needs for the root
             and the spine.
  bones      stiff distance constraints.
  joints     anatomical limits - swing cones with four separate limits (front /
             back / out / in) for hips, shoulders and neck; true hinges for knees
             and elbows, so they only fold the way a body folds; and four
             hip-to-shoulder range constraints that bound spine bend and twist.
  tone       short-lived "muscle tone" (soft constraints across the joints) that
             decays after she goes down: a fainting crumple sags at the knees
             first instead of dropping like a puppet with its strings cut, and a
             shot body is limp almost at once.
  damping    only motion RELATIVE to her rigid-body motion is damped (limp
             tissue, joint friction). Falling and tumbling as a whole is not.
  contacts   floor / walls / ceiling, the real Windows as boxes spanning the full
             depth, the slab's invisible front and back, and other ragdolls.
             Coulomb friction with a static range and speed-dependent
             restitution are applied at velocity level, so lying bodies stay put
             and only hard hits bounce.

Pure Python: no Qt, no GL, not even numpy, so `python test_ragphys3d.py` runs
anywhere. Coordinates are GLOBAL logical screen px with y DOWN (like Qt) and z
INTO the screen; x right / y down / z away is right-handed. z = 0 is the plane
every student stands in.

Spec (built by Pet.rag3_spec, consumed by Rag3DWorld.add_skeleton)
------------------------------------------------------------------
    dict(
        scale  = float,              # her cfg["scale"]: gravity, speeds, thresholds
        ch     = float,              # her body height in px; sizes every radius
        depth  = float,              # slab half-depth in px: her z stays inside +-depth
        tone   = float,              # 0..1 muscle-tone setting (0.5 = the tuned default)
        drop   = float,              # pelvis -> feet line, window px (kept for Pet)
        pts    = {name: (x, y, z)},  # joint positions, GLOBAL px. Names: see POINTS
        head_r = float | None,       # skull radius px (None: 0.15 * ch)
        fwd    = (x, y, z) | None,   # the way she faces, if known: fixes mirrored rigs
        sole   = float | None,       # y of the line she stands on (feet radii fit above it)
    )
"""
from __future__ import annotations

import math
import random
import time
from collections import namedtuple

__all__ = ["Impact", "Rag3DWorld", "Rag3DSkeleton", "POINTS", "ORDER",
           "quat_to_mat", "mat_to_quat", "slerp_quat", "rot_between", "mat_mul", "mat_t"]

Impact = namedtuple("Impact", "owner kind strength point")

# ------------------------------------------------------------------ tunables
# Every number that decides how she falls, bounces, folds and settles.
RAG3_SUBSTEP = 1.0 / 300.0       # s per fixed substep at the DEFAULT iteration count (5 per 60 Hz frame).
                                 #   Every per-substep constant below was tuned at this rate.
RAG3_MAX_SUBSTEPS = 25           # catch-up cap per frame at the default rate; the rest of a slow frame is dropped
RAG3_MAX_CATCHUP = RAG3_MAX_SUBSTEPS * RAG3_SUBSTEP   # s of simulated catch-up per frame, at any rate
# "Physics iterations" (cfg ragdoll_3d_iters): substeps per 1/60 s. Fewer = less CPU (and less
# lag on a busy desktop) at the price of softer, slightly stretchier joints; more = stiffer.
RAG3_BASE_HZ = 60.0
RAG3_ITERS_DEFAULT = 5           # 5 x 60 Hz = 300 Hz = RAG3_SUBSTEP: exactly the tuned behaviour
RAG3_ITERS_MIN, RAG3_ITERS_MAX = 1, 10
# Sleeping: a body that has lain still for a moment costs nothing until something disturbs it
# (a grab, a shove, a shot, another ragdoll, a window moving / closing / resizing on top of her).
RAG3_SLEEP_V = 25.0              # px/s (x scale): every particle slower than this, while touching ...
RAG3_SLEEP_TIME = 0.5            # ... for this long = asleep
RAG3_WAKE_MARGIN = 4.0           # px of slack when testing whether something reaches a sleeping body
RAG3_BONE_PASSES = 2             # bone-length passes per substep (one before, one after the limits)
RAG3_SM_ITERS = 2                # rotation-extraction iterations per cluster per substep (warm-started)
RAG3_G = 2600.0                  # px/s^2 at scale 1, times max(0.6, scale): the same g as Pet.G
RAG3_MAX_V = 6000.0              # px/s ceiling per particle
RAG3_BLAST_V = 12000.0           # px/s after a frame = blow-up: she is frozen and Pet drops her
RAG3_AIR_DRAG = 0.06             # 1/s linear air drag
RAG3_LIMP_DAMP = 4.0             # 1/s damping of motion relative to her rigid motion (limp tissue)
RAG3_TONE_DAMP = 10.0            # 1/s extra relative damping at full muscle tone
RAG3_REST_DAMP = 10.0            # 1/s extra relative damping once she is slow and lying on something
RAG3_REST_DAMP_V = 140.0         # px/s (x scale): below this, while touching, REST_DAMP applies
RAG3_FRICTION = 0.85             # kinetic friction against floor / walls / windows / other pets
RAG3_STATIC = 1.15               # static friction: tangential speed below STATIC * normal change stops dead
RAG3_RESTITUTION = 0.22          # bounce of a hard hit ...
RAG3_BOUNCE_V0 = 320.0           # ... none at or below this closing speed (px/s, x scale) ...
RAG3_BOUNCE_V1 = 1600.0          # ... full at or above this one
RAG3_SLAB_FRICTION = 0.08        # the slab's front / back walls are invisible: nearly frictionless
RAG3_DEPTH = 0.35                # default slab half-depth as a fraction of her body height
RAG3_WIN_MAX_V = 4000.0          # px/s cap on a window sliding between two polls
RAG3_WIN_SNAP = 600.0            # px of movement above which a window teleports instead
RAG3_WIN_MIN_DT = 1.0 / 60       # s floor on the divisor when a move becomes a velocity
RAG3_CATCHUP = 0.5               # s a window may keep sliding after the last poll
RAG3_IMPACT_DIV = 1000.0         # closing px/s / this = impact strength; a standing-height fall is ~1
RAG3_REST_SPEED = 40.0           # px/s (x scale): slower than this while touching = at rest
RAG3_CONTACT_GRACE = 0.10        # s a contact still counts after it ends
RAG3_GRAB_RADIUS = 60.0          # px (x scale) the cursor may miss a limb by and still grab it
RAG3_GRAB_THROW_V = 3000.0       # px/s cap per particle when she is let go
RAG3_SHOVE_UP = (500.0, 900.0)   # px/s upward kick from a click, x scale x power
RAG3_SHOVE_SIDE = 6.0            # horizontal shove = (pelvis x - cursor x) * this, clamped
RAG3_SHOVE_CLAMP = 1400.0        # px/s cap on that horizontal shove
RAG3_SHOVE_Z = 260.0             # px/s random depth share of a shove, x scale x power
RAG3_SHOT_Z = 0.45               # depth share of a bullet's push (random sign): she twists as she drops
RAG3_SHOT_GRADE = (1.0, 0.18)    # velocity share at the head / at the feet: the hit is high, feet stay
RAG3_SHOT_SPIN = 0.35            # share of the caller's spin kept (the grade already rotates her)
RAG3_SLAM_Z = 140.0              # px/s random depth velocity added to an edge slam / kick
RAG3_TOPPLE_W = (0.8, 1.8)       # rad/s rigid start rotation: which way she goes over is random
RAG3_TOPPLE_DIR = (0.36, 0.28, 0.36)  # odds of going over forward / backward / sideways (her frame)
RAG3_TOPPLE_PITCH = 2.6          # rad/s extra hip fold of the upper body when she goes over forward
RAG3_OUTSIDE_H = 1.0             # body heights the pelvis may leave the screen before a snap back
RAG3_INIT_TONE = {"crumple": 0.95, "kick": 0.55, "slam": 0.35, "shot": 0.22, "throw": 0.05}
RAG3_TONE_FADE = 0.42            # s e-folding time of the muscle tone
RAG3_TONE_K = 0.30               # fraction of a tone constraint's error closed per substep at tone 1
RAG3_SELF_MARGIN = 1.0           # px of extra gap before a spawn-overlapping self pair turns solid again

# Particle table:  name -> (mass weight, radius as a fraction of her body height)
# Chibi proportions: the head is large and heavy, the legs short.
POINTS = {
    "pelvis":     (0.140, 0.075),
    "hip_l":      (0.060, 0.058), "hip_r":      (0.060, 0.058),
    "chest":      (0.140, 0.072),
    "neck":       (0.040, 0.040),
    "head":       (0.140, 0.150),     # radius normally replaced by spec["head_r"], measured off her mesh
    "shoulder_l": (0.030, 0.036), "shoulder_r": (0.030, 0.036),
    "elbow_l":    (0.025, 0.030), "elbow_r":    (0.025, 0.030),
    "hand_l":     (0.016, 0.030), "hand_r":     (0.016, 0.030),
    "knee_l":     (0.060, 0.044), "knee_r":     (0.060, 0.044),
    "foot_l":     (0.036, 0.038), "foot_r":     (0.036, 0.038),
}
ORDER = list(POINTS)
REQUIRED = ("pelvis", "hip_l", "hip_r", "neck", "head", "knee_l", "knee_r", "foot_l", "foot_r")

# Joint limits, radians, from the pose a body stands in.
# Swing cones: (front, back, out, in) - "out" is away from her midline.
RAG3_HIP = (2.00, 0.45, 0.85, 0.35)       # flexion 115 deg, extension 26, abduction 49, adduction 20
RAG3_SHOULDER = (2.90, 0.95, 2.70, 0.80)  # a shoulder swings almost everywhere except behind / across
RAG3_NECK = (0.85, 0.65, 0.60, 0.60)      # chin to chest, head back, ear to shoulder
# Hinges: (min, max) bend; positive = the anatomical way (knee folds back, elbow forward)
RAG3_KNEE = (-0.03, 2.45)
RAG3_ELBOW = (-0.03, 2.55)
RAG3_HINGE_TWIST = 0.20                   # rad a knee / elbow may wander out of its bend plane
RAG3_SPINE = (0.86, 1.12)                 # hip <-> shoulder length range, x spawn length: bend + twist
RAG3_LIMIT_SLACK = 0.06                   # rad allowed past a spawn pose already outside a limit

_sqrt = math.sqrt
_atan2 = math.atan2
_sin = math.sin
_cos = math.cos
_asin = math.asin
_MAXV2 = RAG3_MAX_V * RAG3_MAX_V


def iters_to_substep(iters):
    """cfg ragdoll_3d_iters -> seconds per substep (clamped to the slider's range)."""
    try:
        n = int(round(float(iters)))
    except (TypeError, ValueError):
        n = RAG3_ITERS_DEFAULT
    n = max(RAG3_ITERS_MIN, min(RAG3_ITERS_MAX, n))
    return n, 1.0 / (RAG3_BASE_HZ * n)


# ================================================================ small maths
# 3x3 matrices are row-major 9-tuples; quaternions are (w, x, y, z).
def mat_mul(A, B):
    return (A[0] * B[0] + A[1] * B[3] + A[2] * B[6], A[0] * B[1] + A[1] * B[4] + A[2] * B[7],
            A[0] * B[2] + A[1] * B[5] + A[2] * B[8],
            A[3] * B[0] + A[4] * B[3] + A[5] * B[6], A[3] * B[1] + A[4] * B[4] + A[5] * B[7],
            A[3] * B[2] + A[4] * B[5] + A[5] * B[8],
            A[6] * B[0] + A[7] * B[3] + A[8] * B[6], A[6] * B[1] + A[7] * B[4] + A[8] * B[7],
            A[6] * B[2] + A[7] * B[5] + A[8] * B[8])


def mat_t(A):
    return (A[0], A[3], A[6], A[1], A[4], A[7], A[2], A[5], A[8])


def _mv(R, v):
    return (R[0] * v[0] + R[1] * v[1] + R[2] * v[2],
            R[3] * v[0] + R[4] * v[1] + R[5] * v[2],
            R[6] * v[0] + R[7] * v[1] + R[8] * v[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v, fallback=(0.0, 1.0, 0.0)):
    d = _sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if d < 1e-12:
        return fallback
    return (v[0] / d, v[1] / d, v[2] / d)


def _perp_unit(v, ref):
    """`v` with its component along unit `ref` removed, normalised (or None)."""
    k = _dot(v, ref)
    p = (v[0] - k * ref[0], v[1] - k * ref[1], v[2] - k * ref[2])
    d = _sqrt(_dot(p, p))
    return None if d < 1e-6 else (p[0] / d, p[1] / d, p[2] / d)


def quat_to_mat(q):
    w, x, y, z = q
    return (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
            2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
            2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y))


def mat_to_quat(R):
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = R
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = _sqrt(tr + 1.0) * 2.0
        q = (0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s)
    elif m00 > m11 and m00 > m22:
        s = _sqrt(max(1e-12, 1.0 + m00 - m11 - m22)) * 2.0
        q = ((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s)
    elif m11 > m22:
        s = _sqrt(max(1e-12, 1.0 + m11 - m00 - m22)) * 2.0
        q = ((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s)
    else:
        s = _sqrt(max(1e-12, 1.0 + m22 - m00 - m11)) * 2.0
        q = ((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s)
    n = _sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def slerp_quat(a, b, t):
    """Shortest-path slerp from quaternion a to b."""
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if d < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3]); d = -d
    if d > 0.9995:
        q = tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    else:
        th = math.acos(min(1.0, d)); s = math.sin(th)
        ka, kb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        q = tuple(a[i] * ka + b[i] * kb for i in range(4))
    n = _sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def rot_between(a, b):
    """The minimal rotation matrix taking unit vector a onto unit vector b."""
    c = _dot(a, b)
    k = _cross(a, b)
    s2 = _dot(k, k)
    if s2 < 1e-18:
        if c > 0.0:
            return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        p = _perp_unit((1.0, 0.0, 0.0), a) or _perp_unit((0.0, 1.0, 0.0), a)
        x, y, z = p                                   # 180 degrees about any perpendicular
        return (2 * x * x - 1, 2 * x * y, 2 * x * z, 2 * x * y, 2 * y * y - 1, 2 * y * z,
                2 * x * z, 2 * y * z, 2 * z * z - 1)
    f = (1.0 - c) / s2
    kx, ky, kz = k
    return (1 - f * (ky * ky + kz * kz), -kz + f * kx * ky, ky + f * kx * kz,
            kz + f * kx * ky, 1 - f * (kx * kx + kz * kz), -kx + f * ky * kz,
            -ky + f * kx * kz, kx + f * ky * kz, 1 - f * (kx * kx + ky * ky))


def _rot_apply(a, b, v):
    """Rotate v by the minimal rotation taking unit a onto unit b (no matrix built)."""
    c = _dot(a, b)
    k = _cross(a, b)
    s = _sqrt(_dot(k, k))
    if s < 1e-9:
        if c > 0.0:
            return v
        p = _perp_unit((1.0, 0.0, 0.0), a) or _perp_unit((0.0, 1.0, 0.0), a)
        kv = _dot(p, v)
        return (2 * kv * p[0] - v[0], 2 * kv * p[1] - v[1], 2 * kv * p[2] - v[2])
    k = (k[0] / s, k[1] / s, k[2] / s)
    kxv = _cross(k, v)
    kv = _dot(k, v) * (1.0 - c)
    return (v[0] * c + kxv[0] * s + k[0] * kv,
            v[1] * c + kxv[1] * s + k[1] * kv,
            v[2] * c + kxv[2] * s + k[2] * kv)


def _extract_rotation(A, q, iters):
    """Muller et al. 2016: the rotation part of A, warm-started from quaternion q."""
    a00, a01, a02, a10, a11, a12, a20, a21, a22 = A
    w, x, y, z = q
    for _ in range(iters):
        r00 = 1 - 2 * (y * y + z * z); r01 = 2 * (x * y - w * z); r02 = 2 * (x * z + w * y)
        r10 = 2 * (x * y + w * z); r11 = 1 - 2 * (x * x + z * z); r12 = 2 * (y * z - w * x)
        r20 = 2 * (x * z - w * y); r21 = 2 * (y * z + w * x); r22 = 1 - 2 * (x * x + y * y)
        ox = (r10 * a20 - r20 * a10) + (r11 * a21 - r21 * a11) + (r12 * a22 - r22 * a12)
        oy = (r20 * a00 - r00 * a20) + (r21 * a01 - r01 * a21) + (r22 * a02 - r02 * a22)
        oz = (r00 * a10 - r10 * a00) + (r01 * a11 - r11 * a01) + (r02 * a12 - r12 * a02)
        den = abs(r00 * a00 + r10 * a10 + r20 * a20 + r01 * a01 + r11 * a11 + r21 * a21
                  + r02 * a02 + r12 * a12 + r22 * a22) + 1e-9
        ox /= den; oy /= den; oz /= den
        ang = _sqrt(ox * ox + oy * oy + oz * oz)
        if ang < 1e-9:
            break
        s = math.sin(ang * 0.5) / ang; c = math.cos(ang * 0.5)
        dx, dy, dz = ox * s, oy * s, oz * s
        w, x, y, z = (c * w - dx * x - dy * y - dz * z, c * x + dx * w + dy * z - dz * y,
                      c * y - dx * z + dy * w + dz * x, c * z + dx * y - dy * x + dz * w)
        n = _sqrt(w * w + x * x + y * y + z * z)
        w, x, y, z = w / n, x / n, y / n, z / n
    return (w, x, y, z)


def _smooth(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


# ===================================================================== world
class Rag3DWorld:
    """One 3D physics world per App, shared by every pet using the 3D engine.

    Same shape as ragphys.RagWorld (set_screen / sync_windows / add_skeleton /
    remove_skeleton / step / pop_impacts), so the App drives both the same way.
    """

    def __init__(self, iters=RAG3_ITERS_DEFAULT):
        self.rect = None                 # (l, t, r, b) of the home screen, logical px
        self._skels = {}                 # owner -> Rag3DSkeleton
        self._wins = {}                  # hwnd -> dict(rect, target, vel, t, until)
        self._win_moving = False
        self._mute = set()               # (owner, particle, hwnd): window overlapping her at spawn
        self._pet_mute = set()           # (owner_a, i, owner_b, j): two ragdolls spawned inside each other
        self._impacts = {}               # owner -> {kind: Impact}
        self._acc = 0.0
        self._wall = 0.0                 # s of simulated wall time (advances even while nobody is limp)
        self._trace = 0
        self.iters, self.substep = iters_to_substep(iters)
        self.cost_ms = 0.0               # smoothed wall-clock cost of step(), for the panel's status line
        self.active = 0                  # awake ragdolls in the last step

    # ------------------------------------------------------------ iterations
    def set_iterations(self, iters):
        """cfg ragdoll_3d_iters: substeps per 1/60 s. Safe to change mid-fall (PBD
        derives velocity from positions, so a new step size needs no conversion)."""
        self.iters, self.substep = iters_to_substep(iters)
        self._acc = min(self._acc, self.substep)
        return self.iters

    # ---------------------------------------------------------------- screen
    def set_screen(self, rect):
        new = tuple(float(v) for v in rect)
        if new != self.rect:
            self.rect = new
            for s in self._skels.values():                 # the floor moved: everybody falls again
                s.wake()

    # --------------------------------------------------------------- windows
    def sync_windows(self, wins, now, enabled):
        """Diff WinTracker.wins ((hwnd, l, t, r, b) logical px) against our boxes."""
        if not enabled:
            for w in self._wins.values():
                self._wake_rect(w["rect"])
            self._wins.clear(); self._mute.clear(); self._win_moving = False
            return
        l, t, r, b = self.rect or (0.0, 0.0, 1.0, 1.0)
        want = {}
        for h, wl, wt, wr, wb in wins:
            if wr < l or wl > r or wb < t or wt > b:      # another monitor
                continue
            want[int(h)] = (float(wl), float(wt), float(wr), float(wb))
        gone = [h for h in self._wins if h not in want]
        if gone:
            for h in gone:
                w = self._wins.pop(h)
                self._wake_rect(w["rect"])                  # she may have been lying on it
            gs = set(gone)
            self._mute = {m for m in self._mute if m[2] not in gs}
        for h, rect in want.items():
            w = self._wins.get(h)
            if w is None:
                self._wins[h] = dict(rect=list(rect), target=rect, vel=(0.0, 0.0), t=now, until=0.0)
                self._mute_window(h)
                continue
            dt = max(now - w["t"], RAG3_WIN_MIN_DT)
            w["t"] = now
            cur = w["rect"]
            if abs((rect[2] - rect[0]) - (cur[2] - cur[0])) > 0.5 or \
               abs((rect[3] - rect[1]) - (cur[3] - cur[1])) > 0.5:
                self._wake_rect(cur); self._wake_rect(rect)
                w["rect"] = list(rect); w["target"] = rect; w["vel"] = (0.0, 0.0)
                self._mute_window(h)                       # resized: rebuilt, not slid
                continue
            dx, dy = rect[0] - cur[0], rect[1] - cur[1]
            d = math.hypot(dx, dy)
            if d < 0.5:
                w["rect"] = list(rect); w["target"] = rect; w["vel"] = (0.0, 0.0)
                continue
            if d >= RAG3_WIN_SNAP:                          # teleported: snap and mute
                self._wake_rect(cur); self._wake_rect(rect)
                w["rect"] = list(rect); w["target"] = rect; w["vel"] = (0.0, 0.0)
                self._mute_window(h)
                continue
            vx, vy = dx / dt, dy / dt
            sp = math.hypot(vx, vy)
            if sp > RAG3_WIN_MAX_V:
                vx, vy = vx * RAG3_WIN_MAX_V / sp, vy * RAG3_WIN_MAX_V / sp
            w["target"] = rect; w["vel"] = (vx, vy)
            w["until"] = self._wall + min(dt, RAG3_CATCHUP) + RAG3_WIN_MIN_DT
            self._win_moving = True

    def _mute_window(self, h, skel=None):
        """A window that appears on top of her must not catapult her out of it."""
        w = self._wins.get(h)
        if w is None:
            return
        wl, wt, wr, wb = w["rect"]
        for s in (self._skels.values() if skel is None else (skel,)):
            if s.detached:
                continue
            X, Y, R, o = s.X, s.Y, s.R, s.owner
            for i in range(s.n):
                r = R[i] - 0.5
                if X[i] + r > wl and X[i] - r < wr and Y[i] + r > wt and Y[i] - r < wb:
                    self._mute.add((o, i, h))

    def _advance_windows(self, h):
        moving = False
        for w in self._wins.values():
            vx, vy = w["vel"]
            if vx == 0.0 and vy == 0.0:
                continue
            if self._wall >= w["until"]:
                w["rect"] = list(w["target"]); w["vel"] = (0.0, 0.0)
                continue
            r = w["rect"]
            r[0] += vx * h; r[2] += vx * h; r[1] += vy * h; r[3] += vy * h
            moving = True
        self._win_moving = moving

    def _settle_windows(self):
        """Nobody awake to push: every sliding window simply arrives at its target.
        (Before, a window that moved while no one was limp kept its stale slide and
        replayed it - from its OLD position - the next time someone went down.)"""
        for w in self._wins.values():
            if w["vel"] != (0.0, 0.0):
                w["rect"] = list(w["target"]); w["vel"] = (0.0, 0.0)
        self._win_moving = False

    # -------------------------------------------------------------- sleeping
    def _wake_rect(self, rect, margin=RAG3_WAKE_MARGIN):
        wl, wt, wr, wb = rect
        for s in self._skels.values():
            if s.sleeping:
                bb = s.bb
                if bb[3] + margin >= wl and bb[0] - margin <= wr and bb[4] + margin >= wt and bb[1] - margin <= wb:
                    s.wake()

    def _wake_check(self, sleepers, awake, dt):
        """Wake any sleeping body something is about to reach: a MOVING awake ragdoll
        (with this frame's travel as slack) or a window that is sliding.

        A quiet awake body (about to fall asleep itself) does not wake its
        neighbours, or two bodies lying on each other would keep waking each other
        forever and neither would ever sleep. If it starts moving, it wakes them."""
        m0 = RAG3_WAKE_MARGIN
        boxes = []
        for a in awake:
            sp = a.speed()
            if sp < RAG3_SLEEP_V * a._s and a.grab_i < 0:
                continue
            bb = a.bounds()
            m = sp * dt + m0
            boxes.append((bb[0] - m, bb[1] - m, bb[2] - m, bb[3] + m, bb[4] + m, bb[5] + m))
        if self._win_moving:
            for w in self._wins.values():
                if w["vel"] == (0.0, 0.0):
                    continue
                r, tg = w["rect"], w["target"]
                boxes.append((min(r[0], tg[0]) - m0, min(r[1], tg[1]) - m0, -1e18,
                              max(r[2], tg[2]) + m0, max(r[3], tg[3]) + m0, 1e18))
        if not boxes:
            return
        for s in sleepers:
            bb = s.bb
            for b in boxes:
                if bb[0] <= b[3] and b[0] <= bb[3] and bb[1] <= b[4] and b[1] <= bb[4] \
                   and bb[2] <= b[5] and b[2] <= bb[5]:
                    s.wake()
                    break

    # ------------------------------------------------------------- skeletons
    def add_skeleton(self, owner_id, spec, kick=None, mode="kick", hit=None):
        skel = Rag3DSkeleton(self, owner_id, spec, kick, mode, hit)
        old = self._skels.get(owner_id)
        if old is not None:
            self.remove_skeleton(old)
        self._skels[owner_id] = skel
        for h in list(self._wins):                         # she is drawn IN FRONT of windows she overlaps
            self._mute_window(h, skel)
        bs = skel.bounds()
        for o in self._skels.values():                     # two ragdolls born inside each other
            if o is skel or o.detached:
                continue
            bo = o.bounds()
            if bs[0] > bo[3] or bo[0] > bs[3] or bs[1] > bo[4] or bo[1] > bs[4] \
               or bs[2] > bo[5] or bo[2] > bs[5]:
                continue                                   # nowhere near each other
            o.wake()
            for i in range(skel.n):
                for j in range(o.n):
                    dx = skel.X[i] - o.X[j]; dy = skel.Y[i] - o.Y[j]; dz = skel.Z[i] - o.Z[j]
                    rs = skel.R[i] + o.R[j]
                    if dx * dx + dy * dy + dz * dz < rs * rs:
                        self._pet_mute.add((skel.owner, i, o.owner, j))
        return skel

    def remove_skeleton(self, skel):
        if skel is None:
            return
        if self._skels.get(skel.owner) is skel:
            self._skels.pop(skel.owner, None)
        o = skel.owner
        if self._mute:
            self._mute = {m for m in self._mute if m[0] != o}
        if self._pet_mute:
            self._pet_mute = {m for m in self._pet_mute if m[0] != o and m[2] != o}
        self._impacts.pop(o, None)
        skel.detached = True
        skel.grab_i = -1
        # whoever was lying on / under her has lost a support
        if any(s.sleeping for s in self._skels.values()):
            bb = skel.bounds()
            self._wake_rect((bb[0], bb[1], bb[3], bb[4]))

    def skel(self, owner_id):
        return self._skels.get(owner_id)

    def pop_impacts(self, owner_id):
        return list(self._impacts.pop(owner_id, {}).values())

    def _impact(self, owner, kind, strength, x, y):
        rec = self._impacts.setdefault(owner, {})
        cur = rec.get(kind)
        if cur is None or cur.strength < strength:
            rec[kind] = Impact(owner, kind, strength, (x, y))

    def trace(self, frames=60):
        self._trace = max(0, int(frames))

    # -------------------------------------------------------------- stepping
    def step(self, dt):
        """Advance by dt seconds in fixed substeps. Once per App tick, not per pet."""
        self._impacts.clear()
        dt = min(max(dt, 0.0), 0.25)
        self._wall += dt                                   # always: window slides are timed against it
        if not self._skels:
            self._acc = 0.0; self.active = 0
            if self._win_moving:
                self._settle_windows()
            self.cost_ms *= 0.9
            return
        t0 = time.perf_counter()
        live = [s for s in self._skels.values() if not s.detached]
        sleepers = [s for s in live if s.sleeping]
        awake = [s for s in live if not s.sleeping]
        if sleepers and (awake or self._win_moving):
            self._wake_check(sleepers, awake, dt)
            awake = [s for s in live if not s.sleeping]
        self.active = len(awake)
        if not awake:
            self._acc = 0.0
            if self._win_moving:
                self._settle_windows()
            self.cost_ms *= 0.9
            return
        self._acc += dt
        h = self.substep
        cap = max(1, int(math.ceil(RAG3_MAX_CATCHUP / h - 1e-9)))
        budget = min(cap, int(self._acc / h))
        for s in awake:
            s.begin_frame(budget)
        multi = len(awake) > 1
        n = 0
        while self._acc >= h and n < cap:
            if self._win_moving:
                self._advance_windows(h)
            for s in awake:
                s.predict(h, n)
                s.solve_internal()
            if multi:
                self._collide_pets(awake)
            for s in awake:
                s.solve_env(h)
                s.update_velocity(h)
            n += 1
            self._acc -= h
        if self._acc > h:                                  # slow frame: drop the backlog
            self._acc = 0.0
        if n:
            for s in awake:
                s.post_frame(n * h)
        if self._trace > 0:
            self._trace -= 1
            for s in live:
                be, lv = s.joint_error()
                print(f"  [rag3d] owner={s.owner} pelvis=({s.X[0]:.1f},{s.Y[0]:.1f},{s.Z[0]:.1f}) "
                      f"speed={s.speed():.0f} tone={s.tone:.2f} bone_err={be:.2f}px "
                      f"limit_err={math.degrees(lv):.1f}deg touching={s.touching()} "
                      f"asleep={s.sleeping} substeps={n}@{1.0 / h:.0f}Hz")
        ms = (time.perf_counter() - t0) * 1000.0
        self.cost_ms += (ms - self.cost_ms) * 0.1

    def _collide_pets(self, skels):
        """Ragdoll vs ragdoll: sphere pairs, mass-weighted, with AABB early outs.

        No per-pair allocation: the mute keys are only built while the mute set is
        non-empty (it is empty unless two bodies were spawned inside each other)."""
        for s in skels:
            s.bounds()
        mute = self._pet_mute
        fr = RAG3_FRICTION * 0.6
        for ia in range(len(skels)):
            A = skels[ia]
            for ib in range(ia + 1, len(skels)):
                B = skels[ib]
                ba, bb = A.bb, B.bb
                if ba[0] > bb[3] or bb[0] > ba[3] or ba[1] > bb[4] or bb[1] > ba[4] \
                   or ba[2] > bb[5] or bb[2] > ba[5]:
                    continue
                AX, AY, AZ, AR, AW = A.X, A.Y, A.Z, A.R, A.W
                BX, BY, BZ, BR, BW = B.X, B.Y, B.Z, B.R, B.W
                oa, ob = A.owner, B.owner
                nb = B.n
                bl, bt, bn, br, bbt, bf = bb
                for i in range(A.n):
                    ax = AX[i]; ay = AY[i]; az = AZ[i]; ar = AR[i]
                    if not mute and (ax + ar < bl or ax - ar > br or ay + ar < bt or ay - ar > bbt
                                     or az + ar < bn or az - ar > bf):
                        continue                         # this sphere cannot reach B at all
                    for j in range(nb):
                        dx = BX[j] - ax; dy = BY[j] - ay; dz = BZ[j] - az
                        rs = ar + BR[j]
                        d2 = dx * dx + dy * dy + dz * dz
                        if d2 >= rs * rs:
                            if mute:
                                k1 = (oa, i, ob, j)
                                if k1 in mute:
                                    mute.discard(k1)
                                k2 = (ob, j, oa, i)
                                if k2 in mute:
                                    mute.discard(k2)
                            continue
                        if mute and ((oa, i, ob, j) in mute or (ob, j, oa, i) in mute):
                            continue
                        wa, wb = AW[i], BW[j]
                        ws = wa + wb
                        if ws <= 0.0:
                            continue
                        d = _sqrt(d2)
                        if d < 1e-6:
                            nx, ny, nz, d = 0.0, -1.0, 0.0, 0.0
                        else:
                            nx, ny, nz = dx / d, dy / d, dz / d
                        pen = rs - d
                        ka, kb = pen * wa / ws, pen * wb / ws
                        ax -= nx * ka; ay -= ny * ka; az -= nz * ka
                        AX[i] = ax; AY[i] = ay; AZ[i] = az
                        BX[j] += nx * kb; BY[j] += ny * kb; BZ[j] += nz * kb
                        va = (A.VX[i], A.VY[i], A.VZ[i]); vb = (B.VX[j], B.VY[j], B.VZ[j])
                        A.contact(i, -nx, -ny, -nz, ka, vb, fr, RAG3_RESTITUTION, "pet")
                        B.contact(j, nx, ny, nz, kb, va, fr, RAG3_RESTITUTION, "pet")


# ================================================================ one ragdoll
class Rag3DSkeleton:
    """One pet's particles, constraints and grab, living in a shared Rag3DWorld.

    Duck-types the parts of ragphys.RagSkeleton that Pet calls from shared code
    (pose / grab / move_grab / release_grab / grab_joint / shove / touching /
    speed / lowest_point / explode_guard / outside / snap_inside / drop), so the
    existing mouse and tick paths work on it unchanged.
    """

    is3d = True

    def __init__(self, world, owner, spec, kick=None, mode="kick", hit=None):
        self.world, self.owner, self.spec = world, owner, spec
        self.scale = float(spec.get("scale", 1.0))
        s = max(0.6, self.scale)
        self._s = s
        self.ch = max(20.0, float(spec.get("ch", 300.0)))
        self.depth = max(2.0, float(spec.get("depth", RAG3_DEPTH * self.ch)))
        self.gravity = RAG3_G * s
        self.drop = float(spec.get("drop", 0.0))
        self.mode = mode if mode in RAG3_INIT_TONE else "kick"
        tone_set = min(1.0, max(0.0, float(spec.get("tone", 0.5))))
        self.tone0 = RAG3_INIT_TONE[self.mode] * 2.0 * tone_set
        self.tone = self.tone0
        self.limp_damp = RAG3_LIMP_DAMP * (0.6 + 0.8 * tone_set)
        self.age = 0.0
        self.detached = False
        self.broken = False
        self.grab_i = -1
        self.grab_at = (0.0, 0.0)
        self._grab_from = self._grab_to = (0.0, 0.0)
        self._grab_n = 1
        self._grab_w = 0.0
        self._contact_wall = -1e9
        self.contacts = []                 # this substep's contacts, for the velocity pass
        self.bb = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.sleeping = False              # lying still: skipped by the world until disturbed
        self._h = None                     # substep size the per-substep factors were made for
        self._rate_ratio = 1.0             # that size / RAG3_SUBSTEP
        self._bone_passes = RAG3_BONE_PASSES
        self._still = 0.0                  # s she has been below RAG3_SLEEP_V while touching
        self._build(spec)
        self._start_motion(kick, hit)
        self.bounds()

    # ------------------------------------------------------------------ build
    def _build(self, spec):
        pts = {k: tuple(float(c) for c in v) for k, v in spec["pts"].items()}
        for need in REQUIRED:
            if need not in pts:
                raise ValueError(f"3D ragdoll needs a {need!r} joint")
        arm = {sd: all(f"{p}_{sd}" in pts for p in ("shoulder", "elbow", "hand")) for sd in "lr"}
        has_chest = "chest" in pts and (arm["l"] or arm["r"])
        names = []
        for nm in ORDER:
            if nm not in pts:
                continue
            if nm == "chest" and not has_chest:
                continue
            side = nm[-1] if nm[-2:] in ("_l", "_r") else None
            if side and nm.split("_")[0] in ("shoulder", "elbow", "hand") and not arm[side]:
                continue
            names.append(nm)
        self.names = names
        self.idx = idx = {nm: i for i, nm in enumerate(names)}
        n = self.n = len(names)
        ch = self.ch
        # ---- radii and masses
        R = []
        mass = []
        for nm in names:
            wgt, rf = POINTS[nm]
            r = rf * ch
            if nm == "head" and spec.get("head_r"):
                r = float(spec["head_r"])
            R.append(max(1.5, r))
            mass.append(wgt)
        if not has_chest and "chest" in pts:               # fold the chest's mass into the torso
            extra = POINTS["chest"][0]
            mass[idx["pelvis"]] += extra * 0.5; mass[idx["neck"]] += extra * 0.5
        tm = sum(mass)
        mass = [m / tm for m in mass]
        # ---- positions; feet radii fit above the line she stands on
        X = [pts[nm][0] for nm in names]
        Y = [pts[nm][1] for nm in names]
        Z = [pts[nm][2] for nm in names]
        sole = spec.get("sole")
        if sole is not None:
            sole = float(sole)
            for nm in ("foot_l", "foot_r"):
                i = idx[nm]
                room = sole - Y[i]
                if 0.4 * R[i] <= room < R[i]:
                    R[i] = room
            low = max(Y[i] + R[i] for i in range(n))
            lift = low - sole
            if lift > 0.0:                                 # her soles would start in the floor
                Y = [y - lift for y in Y]
        self.lift = 0.0
        self.R = R
        self.M = mass
        self.W = [1.0 / m for m in mass]
        self.X, self.Y, self.Z = X, Y, Z
        self.OX, self.OY, self.OZ = list(X), list(Y), list(Z)
        self.VX, self.VY, self.VZ = [0.0] * n, [0.0] * n, [0.0] * n
        self._safe = list(zip(X, Y, Z))
        self.maxr = max(R)
        self.X0, self.Y0, self.Z0 = list(X), list(Y), list(Z)    # spawn pose: the rest reference
        P = lambda nm: (X[idx[nm]], Y[idx[nm]], Z[idx[nm]])
        sub = lambda a, b: (a[0] - b[0], a[1] - b[1], a[2] - b[2])
        # ---- anatomical frame of the pelvis: (left, up, fwd), right-handed
        top = "chest" if has_chest else "neck"
        left = _unit(sub(P("hip_l"), P("hip_r")), (-1.0, 0.0, 0.0))
        up = _perp_unit(sub(P(top), P("pelvis")), left) or (0.0, -1.0, 0.0)
        fwd = _cross(left, up)
        hint = spec.get("fwd")
        if hint is not None and _dot(fwd, _unit(tuple(hint))) < 0.0:
            left = (-left[0], -left[1], -left[2])           # mirrored rig: L/R swapped
            fwd = _cross(left, up)
        self.frame_pelvis = (left, up, fwd)
        if has_chest:
            ls = [nm for nm in ("shoulder_l", "shoulder_r") if nm in idx]
            if len(ls) == 2:
                cl = _unit(sub(P("shoulder_l"), P("shoulder_r")), left)
                if _dot(cl, left) < 0.0:
                    cl = (-cl[0], -cl[1], -cl[2])
            else:
                cl = left
            cu = _perp_unit(sub(P("neck"), P("chest")), cl) or up
            self.frame_chest = (cl, cu, _cross(cl, cu))
        else:
            self.frame_chest = self.frame_pelvis
        # ---- rigid clusters
        cl_p = ["pelvis", "hip_l", "hip_r"] + (["chest"] if has_chest else
                                               ["neck"] + [k for k in ("shoulder_l", "shoulder_r") if k in idx])
        self.clusters = [self._cluster("pelvis", cl_p)]
        if has_chest:
            self.clusters.append(self._cluster("chest", ["chest", "neck"] +
                                               [k for k in ("shoulder_l", "shoulder_r") if k in idx]))
        self.has_chest = has_chest
        self.cl_of = {c["name"]: k for k, c in enumerate(self.clusters)}
        torso = "chest" if has_chest else "pelvis"
        # ---- bodies the renderer maps: (name, proximal, distal, parent body)
        bodies = [("pelvis", None, None, None)]
        if has_chest:
            bodies.append(("chest", None, None, "pelvis"))
        bodies.append(("head", "neck", "head", torso))
        for sd in "lr":
            if arm[sd]:
                bodies.append((f"upperarm_{sd}", f"shoulder_{sd}", f"elbow_{sd}", torso))
                bodies.append((f"forearm_{sd}", f"elbow_{sd}", f"hand_{sd}", f"upperarm_{sd}"))
            bodies.append((f"thigh_{sd}", f"hip_{sd}", f"knee_{sd}", "pelvis"))
            bodies.append((f"calf_{sd}", f"knee_{sd}", f"foot_{sd}", f"thigh_{sd}"))
        self.bodies = [(nm, par) for nm, _a, _b, par in bodies]
        self.bone_of = {}
        for nm, a, b, par in bodies:
            if a is None:
                continue
            ia, ib = idx[a], idx[b]
            self.bone_of[nm] = (ia, ib, _unit(sub(P(b), P(a))), par)
        # ---- constraints
        bl = lambda a, b: math.dist(P(a), P(b))
        self.bones = [(ia, ib, bl(names[ia], names[ib])) for (ia, ib, _u, _p) in self.bone_of.values()]
        self.ranges = []
        if has_chest:
            for hp in ("hip_l", "hip_r"):
                for sh in ("shoulder_l", "shoulder_r"):
                    if sh in idx:
                        L = bl(hp, sh)
                        self.ranges.append((idx[hp], idx[sh], L * RAG3_SPINE[0], L * RAG3_SPINE[1]))
        # Muscle tone across the joints, with a weight each: a fainting body loses
        # its knees first and its neck and back last.
        tone = [("hip_l", "foot_l", 0.45), ("hip_r", "foot_r", 0.45),     # knees
                ("pelvis", "knee_l", 0.8), ("pelvis", "knee_r", 0.8),     # hips
                (torso, "head", 1.3)]                                     # neck
        if has_chest:
            tone.append(("pelvis", "neck", 1.2))                          # spine
        for sd in "lr":
            if arm[sd]:
                tone.append((f"shoulder_{sd}", f"hand_{sd}", 0.6))       # elbows
        self.tone_c = [(idx[a], idx[b], bl(a, b), wt) for a, b, wt in tone]
        self._build_limits(P, sub, arm, torso)
        self._build_self_pairs(P)
        self.cl_R = [(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)] * len(self.clusters)
        self._mmax = max(mass)
        # Flat copies of the hinge table for the hot loop: the parent cluster index is
        # resolved once here instead of two dict lookups per hinge per substep.
        self._hinge_fast = []
        for bone, j, k, c, h0, (lo, hi), tol in self.hinges:
            _j, _k, u0, par = self.bone_of[bone]
            self._hinge_fast.append((self.cl_of[par], j, k, c, u0, h0, lo, hi, tol))

    def _cluster(self, name, members):
        idx = [self.idx[m] for m in members]
        ms = [self.M[i] for i in idx]
        Mt = sum(ms)
        cx = sum(m * self.X[i] for m, i in zip(ms, idx)) / Mt
        cy = sum(m * self.Y[i] for m, i in zip(ms, idx)) / Mt
        cz = sum(m * self.Z[i] for m, i in zip(ms, idx)) / Mt
        q = [(self.X[i] - cx, self.Y[i] - cy, self.Z[i] - cz) for i in idx]
        return dict(name=name, idx=idx, m=ms, M=Mt, q=q, quat=(1.0, 0.0, 0.0, 0.0))

    def _build_limits(self, P, sub, arm, torso):
        """Swing cones for hips, shoulders and neck; hinges for knees and elbows.

        Every axis is stored in WORLD coordinates of the spawn pose and turned by
        the parent cluster's current rotation at run time. A spawn pose that is
        already past a limit widens that limit, so nothing snaps on frame one.
        """
        pl, pu, pf = self.frame_pelvis
        cl, cu, cf = self.frame_chest
        mid_p = P("pelvis")
        self.cones = []
        self.hinges = []

        def cone(cluster, j, c, n0, f0, out_dir, lims):
            u = _unit(sub(P(c), P(j)))
            f0 = _perp_unit(f0, n0) or _perp_unit((0.0, 0.0, -1.0), n0)
            o0 = _cross(n0, f0)
            if _dot(o0, out_dir) < 0.0:
                o0 = (-o0[0], -o0[1], -o0[2])
            Lf, Lb, Lo, Li = lims
            un, uf, uo = _dot(u, n0), _dot(u, f0), _dot(u, o0)
            sp = _sqrt(uf * uf + uo * uo)
            if sp > 1e-9:
                th = math.atan2(sp, un)
                tf, to = th * uf / sp, th * uo / sp
                if tf >= 0.0:
                    Lf = max(Lf, abs(tf) + RAG3_LIMIT_SLACK)
                else:
                    Lb = max(Lb, abs(tf) + RAG3_LIMIT_SLACK)
                if to >= 0.0:
                    Lo = max(Lo, abs(to) + RAG3_LIMIT_SLACK)
                else:
                    Li = max(Li, abs(to) + RAG3_LIMIT_SLACK)
                e = (tf / (Lf if tf >= 0 else Lb)) ** 2 + (to / (Lo if to >= 0 else Li)) ** 2
                if e > 1.0:
                    k = _sqrt(e) * 1.02
                    Lf, Lb, Lo, Li = Lf * k, Lb * k, Lo * k, Li * k
            self.cones.append((self.cl_of[cluster], self.idx[j], self.idx[c], n0, f0, o0,
                               (min(Lf, 3.05), min(Lb, 3.05), min(Lo, 3.05), min(Li, 3.05))))

        def hinge(bone, child, default_axis, lims):
            j, k, u0, par = self.bone_of[bone]
            k2, c, _u1, _p = self.bone_of[child]
            d = u0
            u = _unit(sub(P(self.names[c]), P(self.names[k])))
            nrm = _cross(d, u)
            sn = _sqrt(_dot(nrm, nrm))
            h = None
            if sn > math.sin(math.radians(12.0)):
                h = (nrm[0] / sn, nrm[1] / sn, nrm[2] / sn)   # bent at spawn: trust the authored pose
            if h is None:
                h = _perp_unit(default_axis, d) or _perp_unit(pf, d) or _perp_unit((1.0, 0.0, 0.0), d)
            hd = _cross(h, d)
            a0 = math.atan2(_dot(u, hd), _dot(u, d))
            lo, hi = lims
            lo = min(lo, a0 - RAG3_LIMIT_SLACK)
            hi = max(hi, a0 + RAG3_LIMIT_SLACK)
            self.hinges.append((bone, j, k, c, h, (lo, hi), RAG3_HINGE_TWIST))

        for sd in "lr":
            hip, knee = f"hip_{sd}", f"knee_{sd}"
            out = _perp_unit(sub(P(hip), mid_p), pu) or (pl if sd == "l" else (-pl[0], -pl[1], -pl[2]))
            cone("pelvis", hip, knee, (-pu[0], -pu[1], -pu[2]), pf, out, RAG3_HIP)
            hinge(f"thigh_{sd}", f"calf_{sd}", pl, RAG3_KNEE)            # knee folds back about +left
            if arm[sd]:
                sh, el = f"shoulder_{sd}", f"elbow_{sd}"
                mid_c = P("chest") if self.has_chest else P("neck")
                out = _perp_unit(sub(P(sh), mid_c), cu) or (cl if sd == "l" else (-cl[0], -cl[1], -cl[2]))
                cone(torso, sh, el, (-cu[0], -cu[1], -cu[2]), cf, out, RAG3_SHOULDER)
                hinge(f"upperarm_{sd}", f"forearm_{sd}", (-cl[0], -cl[1], -cl[2]), RAG3_ELBOW)
        cone(torso, "neck", "head", cu, cf, cl, RAG3_NECK)

    def _build_self_pairs(self, P):
        """Limb-vs-body sphere pairs (no pair joined by a bone or sharing a chain)."""
        idx = self.idx
        limbs = [k for k in ("elbow_l", "elbow_r", "hand_l", "hand_r", "knee_l", "knee_r",
                             "foot_l", "foot_r") if k in idx]
        torso = [k for k in ("pelvis", "chest", "hip_l", "hip_r", "head") if k in idx]
        chain = lambda a: a.split("_")[1] if "_" in a else ""
        arm_part = lambda a: a.split("_")[0] in ("shoulder", "elbow", "hand")
        pairs = set()
        for a in limbs:
            for b in torso:
                if a.startswith(("knee", "foot")) and b in ("hip_l", "hip_r") and chain(b) == chain(a):
                    continue                                 # own hip: the hip cone owns that
                pairs.add(tuple(sorted((idx[a], idx[b]))))
            for b in limbs:
                if a == b:
                    continue
                if chain(a) == chain(b) and arm_part(a) == arm_part(b):
                    continue                                 # same arm / same leg: hinge owns it
                pairs.add(tuple(sorted((idx[a], idx[b]))))
        self.self_pairs = []
        self.self_mute = set()
        for i, j in sorted(pairs):
            rs = self.R[i] + self.R[j]
            self.self_pairs.append((i, j, rs, rs * rs, (rs + RAG3_SELF_MARGIN) ** 2))
            if math.dist(P(self.names[i]), P(self.names[j])) < rs + RAG3_SELF_MARGIN:
                self.self_mute.add((i, j))                  # overlapping at spawn: settle in first

    def _start_motion(self, kick, hit):
        """Initial velocities. Never a geometric change: every constraint starts satisfied,
        so the first rendered frame is exactly the pose on screen."""
        vx, vy, w = (tuple(kick) + (0.0, 0.0, 0.0))[:3] if kick else (0.0, 0.0, 0.0)
        s = self._s
        i0 = self.idx["pelvis"]
        px, py, pz = self.X[i0], self.Y[i0], self.Z[i0]
        ytop = min(self.Y); ybot = max(self.Y)
        span = max(1.0, ybot - ytop)
        if self.mode == "shot":
            # The round lands high, so the push is graded from the head (full) down to
            # the feet (a little): the upper body is driven back over planted feet and
            # the knees fold. Part of it goes into the depth with a random sign, plus a
            # twist about her spine, so she turns as she drops instead of falling flat.
            sp = math.hypot(vx, vy)
            zsign = random.choice((-1.0, 1.0))
            twist = random.uniform(-1.0, 1.0)
            hi, lo = RAG3_SHOT_GRADE
            for i in range(self.n):
                g = lo + (hi - lo) * (ybot - self.Y[i]) / span     # 1 at the top of her, low at the feet
                lat = (self.X[i] - px) / span                     # about -0.3 .. 0.3 across her body
                self.VX[i] = vx * g
                self.VY[i] = vy * g
                self.VZ[i] = sp * g * (zsign * RAG3_SHOT_Z + twist * 1.2 * lat)
            w *= RAG3_SHOT_SPIN
        else:
            vz = random.uniform(-RAG3_SLAM_Z, RAG3_SLAM_Z) * s if self.mode in ("slam", "kick") else 0.0
            for i in range(self.n):
                self.VX[i], self.VY[i], self.VZ[i] = vx, vy, vz
        # in-plane spin about the pelvis (y-down: positive = clockwise on screen)
        if w:
            for i in range(self.n):
                dx, dy = self.X[i] - px, self.Y[i] - py
                self.VX[i] += -w * dy
                self.VY[i] += w * dx
        # A small random rigid tip-over about her feet, so which way she goes down is
        # never the same twice and she never balances on her heels. The direction is
        # picked in HER frame - forward onto her face, backward, or to either side -
        # because a body's own knees otherwise bias every faint the same way (they
        # fold backward, which drops the pelvis behind the feet).
        if self.mode != "throw":
            left, _up, fwd = self.frame_pelvis
            r = random.random()
            pf, pb, _ps = RAG3_TOPPLE_DIR
            if r < pf:
                ax, k = left, 1.35                           # head goes forward
            elif r < pf + pb:
                ax, k = (-left[0], -left[1], -left[2]), 1.0  # head goes back
            else:
                sgn = random.choice((-1.0, 1.0))
                ax, k = (fwd[0] * sgn, fwd[1] * sgn, fwd[2] * sgn), 1.1
            k *= random.uniform(*RAG3_TOPPLE_W) * (0.4 if self.mode == "shot" else 1.0)
            ox, oy, oz = ax[0] * k, ax[1] * k, ax[2] * k
            fy = self.Y[self.idx["foot_l"]] * 0.5 + self.Y[self.idx["foot_r"]] * 0.5
            for i in range(self.n):                          # v = w x r about her feet
                rx, ry, rz = self.X[i] - px, self.Y[i] - fy, self.Z[i] - pz
                self.VX[i] += oy * rz - oz * ry
                self.VY[i] += oz * rx - ox * rz
                self.VZ[i] += ox * ry - oy * rx
            if k > 0.0 and ax is left:
                # Going over forward also folds her at the hips: the upper body pitches
                # over the buckling knees, which is what puts a fainting body on its face.
                q = RAG3_TOPPLE_PITCH * (0.4 if self.mode == "shot" else 1.0)
                qx, qy, qz = left[0] * q, left[1] * q, left[2] * q
                for i in range(self.n):
                    if self.Y[i] >= py:
                        continue                             # only what is above the pelvis
                    rx, ry, rz = self.X[i] - px, self.Y[i] - py, self.Z[i] - pz
                    self.VX[i] += qy * rz - qz * ry
                    self.VY[i] += qz * rx - qx * rz
                    self.VZ[i] += qx * ry - qy * rx
        if hit is not None:
            self.impulse(hit[:2], hit[2:5] if len(hit) >= 5 else (hit[2], hit[3], 0.0))
        for i in range(self.n):                              # no particle starts faster than RAG3_MAX_V
            v2 = self.VX[i] ** 2 + self.VY[i] ** 2 + self.VZ[i] ** 2
            if v2 > _MAXV2:
                k = RAG3_MAX_V / _sqrt(v2)
                self.VX[i] *= k; self.VY[i] *= k; self.VZ[i] *= k

    # -------------------------------------------------------------- stepping
    def begin_frame(self, n):
        if self.grab_i < 0:
            return
        i = self.grab_i
        self._grab_from = (self.X[i], self.Y[i])
        self._grab_to = self.grab_at
        self._grab_n = max(1, int(n))

    def predict(self, h, sub_i):
        if h != self._h:
            self._set_rate(h)
        g = self.gravity * h
        drag = 1.0 - RAG3_AIR_DRAG * h
        X, Y, Z, VX, VY, VZ, W = self.X, self.Y, self.Z, self.VX, self.VY, self.VZ, self.W
        OX, OY, OZ = self.OX, self.OY, self.OZ
        for i in range(self.n):
            OX[i] = X[i]; OY[i] = Y[i]; OZ[i] = Z[i]
            if W[i] == 0.0:
                continue
            vx = VX[i] * drag; vy = VY[i] * drag + g; vz = VZ[i] * drag
            VX[i] = vx; VY[i] = vy; VZ[i] = vz
            X[i] += vx * h; Y[i] += vy * h; Z[i] += vz * h
        gi = self.grab_i
        if gi >= 0:                                          # the held particle follows the cursor
            t = min(1.0, (sub_i + 1) / self._grab_n)
            fx, fy = self._grab_from
            tx, ty = self._grab_to
            nx, ny = fx + (tx - fx) * t, fy + (ty - fy) * t
            VX[gi] = (nx - OX[gi]) / h; VY[gi] = (ny - OY[gi]) / h; VZ[gi] = 0.0
            X[gi] = nx; Y[gi] = ny
        self.contacts.clear()

    def _set_rate(self, h):
        """Per-substep factors for a new step size (the iteration slider moved).

        The tone constraint closes a FRACTION of its error per substep, so at a
        different rate the same fraction would make her stiffer or limper. It is
        converted so the fraction closed per SECOND matches the tuned 300 Hz feel.
        Fewer, longer substeps also get an extra bone pass or two, which keeps limb
        lengths honest for very little cost.
        """
        self._h = h
        ratio = h / RAG3_SUBSTEP
        self._rate_ratio = ratio
        self._bone_passes = RAG3_BONE_PASSES + max(0, min(2, int(round((ratio - 1.0) * 0.5))))

    def _tone_k(self):
        f = self.tone * RAG3_TONE_K
        return f, self._rate_ratio

    def solve_internal(self):
        self._solve_bones()
        for k, cl in enumerate(self.clusters):
            self.cl_R[k] = self._shape_match(cl)
        if self.ranges:
            self._solve_ranges()
        if self.tone > 0.01:
            self._solve_tone()
        self._solve_cones()
        self._solve_hinges()
        if self.self_pairs:
            self._solve_self()
        for _ in range(self._bone_passes - 1):
            self._solve_bones()

    def _solve_bones(self):
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        for i, j, rest in self.bones:
            wi = W[i]; wj = W[j]; ws = wi + wj
            if ws == 0.0:
                continue
            dx = X[j] - X[i]; dy = Y[j] - Y[i]; dz = Z[j] - Z[i]
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < 1e-12:
                continue
            d = _sqrt(d2)
            k = (d - rest) / (d * ws)
            a = k * wi; b = k * wj
            X[i] += dx * a; Y[i] += dy * a; Z[i] += dz * a
            X[j] -= dx * b; Y[j] -= dy * b; Z[j] -= dz * b

    def _solve_ranges(self):
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        for i, j, lo, hi in self.ranges:
            dx = X[j] - X[i]; dy = Y[j] - Y[i]; dz = Z[j] - Z[i]
            d2 = dx * dx + dy * dy + dz * dz
            if lo * lo <= d2 <= hi * hi:
                continue                                     # inside the range: no sqrt needed
            d = _sqrt(d2)
            if d < 1e-9:
                continue
            ws = W[i] + W[j]
            if ws == 0.0:
                continue
            k = (d - (lo if d < lo else hi)) / (d * ws)
            a = k * W[i]; b = k * W[j]
            X[i] += dx * a; Y[i] += dy * a; Z[i] += dz * a
            X[j] -= dx * b; Y[j] -= dy * b; Z[j] -= dz * b

    def _solve_tone(self):
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        f0, ratio = self._tone_k()
        same_rate = abs(ratio - 1.0) < 1e-9
        for i, j, rest, wt in self.tone_c:
            dx = X[j] - X[i]; dy = Y[j] - Y[i]; dz = Z[j] - Z[i]
            d = _sqrt(dx * dx + dy * dy + dz * dz)
            ws = W[i] + W[j]
            if d < 1e-9 or ws == 0.0:
                continue
            f = f0 * wt
            f = f if f < 1.0 else 1.0
            if not same_rate:                                # same closure per second at any rate
                f = 1.0 - (1.0 - f) ** ratio
            k = f * (d - rest) / (d * ws)
            a = k * W[i]; b = k * W[j]
            X[i] += dx * a; Y[i] += dy * a; Z[i] += dz * a
            X[j] -= dx * b; Y[j] -= dy * b; Z[j] -= dz * b

    def _shape_match(self, cl):
        """Project a cluster onto its rigid best fit; returns its rotation since spawn."""
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        idx, ms, qs, Mt = cl["idx"], cl["m"], cl["q"], cl["M"]
        cx = cy = cz = 0.0
        for m, i in zip(ms, idx):
            cx += m * X[i]; cy += m * Y[i]; cz += m * Z[i]
        cx /= Mt; cy /= Mt; cz /= Mt
        a00 = a01 = a02 = a10 = a11 = a12 = a20 = a21 = a22 = 0.0
        for m, i, q in zip(ms, idx, qs):
            px = (X[i] - cx) * m; py = (Y[i] - cy) * m; pz = (Z[i] - cz) * m
            qx, qy, qz = q
            a00 += px * qx; a01 += px * qy; a02 += px * qz
            a10 += py * qx; a11 += py * qy; a12 += py * qz
            a20 += pz * qx; a21 += pz * qy; a22 += pz * qz
        quat = _extract_rotation((a00, a01, a02, a10, a11, a12, a20, a21, a22), cl["quat"], RAG3_SM_ITERS)
        cl["quat"] = quat
        r = quat_to_mat(quat)
        r0, r1, r2, r3, r4, r5, r6, r7, r8 = r
        for i, q in zip(idx, qs):
            if W[i] == 0.0:
                continue
            qx, qy, qz = q
            X[i] = cx + r0 * qx + r1 * qy + r2 * qz
            Y[i] = cy + r3 * qx + r4 * qy + r5 * qz
            Z[i] = cz + r6 * qx + r7 * qy + r8 * qz
        return r

    def _move_pair(self, j, c, gx, gy, gz):
        """Move particle c toward (gx, gy, gz), pushing joint j the other way by mass."""
        W = self.W
        wj, wc = W[j], W[c]
        ws = wj + wc
        if ws == 0.0:
            return
        ex = gx - self.X[c]; ey = gy - self.Y[c]; ez = gz - self.Z[c]
        kc, kj = wc / ws, wj / ws
        self.X[c] += ex * kc; self.Y[c] += ey * kc; self.Z[c] += ez * kc
        self.X[j] -= ex * kj; self.Y[j] -= ey * kj; self.Z[j] -= ez * kj

    def _solve_cones(self):
        # Same maths as before, with the cluster rotation of each axis and the
        # pair move written out in place: this runs ~5 cones x every substep.
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        clR = self.cl_R
        for ci, j, c, n0, f0, o0, (Lf, Lb, Lo, Li) in self.cones:
            r0, r1, r2, r3, r4, r5, r6, r7, r8 = clR[ci]
            a, b, e_ = n0
            nx = r0 * a + r1 * b + r2 * e_; ny = r3 * a + r4 * b + r5 * e_; nz = r6 * a + r7 * b + r8 * e_
            a, b, e_ = f0
            fx = r0 * a + r1 * b + r2 * e_; fy = r3 * a + r4 * b + r5 * e_; fz = r6 * a + r7 * b + r8 * e_
            a, b, e_ = o0
            ox = r0 * a + r1 * b + r2 * e_; oy = r3 * a + r4 * b + r5 * e_; oz = r6 * a + r7 * b + r8 * e_
            xj = X[j]; yj = Y[j]; zj = Z[j]
            dx = X[c] - xj; dy = Y[c] - yj; dz = Z[c] - zj
            d = _sqrt(dx * dx + dy * dy + dz * dz)
            if d < 1e-9:
                continue
            ux, uy, uz = dx / d, dy / d, dz / d
            un = ux * nx + uy * ny + uz * nz
            uf = ux * fx + uy * fy + uz * fz
            uo = ux * ox + uy * oy + uz * oz
            sp = _sqrt(uf * uf + uo * uo)
            if sp < 1e-9:
                if un > 0.0:
                    continue                                 # dead on the neutral axis: inside
                uf, sp = 1e-6, 1e-6
            th = _atan2(sp, un)
            tf = th * uf / sp; to = th * uo / sp
            qa = tf / (Lf if tf >= 0.0 else Lb)
            qb = to / (Lo if to >= 0.0 else Li)
            e = qa ** 2 + qb ** 2                            # ** (not q*q): bit-identical to the tuned original
            if e <= 1.0:
                continue
            th2 = th / _sqrt(e)
            cf, co = uf / sp, uo / sp
            s2, c2 = _sin(th2), _cos(th2)
            gx = xj + (c2 * nx + s2 * (cf * fx + co * ox)) * d
            gy = yj + (c2 * ny + s2 * (cf * fy + co * oy)) * d
            gz = zj + (c2 * nz + s2 * (cf * fz + co * oz)) * d
            wj, wc = W[j], W[c]
            ws = wj + wc
            if ws == 0.0:
                continue
            ex = gx - X[c]; ey = gy - Y[c]; ez = gz - Z[c]
            kc, kj = wc / ws, wj / ws
            X[c] += ex * kc; Y[c] += ey * kc; Z[c] += ez * kc
            X[j] = xj - ex * kj; Y[j] = yj - ey * kj; Z[j] = zj - ez * kj

    def _bone_frame_axis(self, bone, axis0):
        """axis0 (spawn world) carried along by `bone`'s rotation: parent cluster, then swing."""
        j, k, u0, par = self.bone_of[bone]
        Rp = self.cl_R[self.cl_of[par]]
        a = _mv(Rp, u0)
        v = _mv(Rp, axis0)
        u = _unit((self.X[k] - self.X[j], self.Y[k] - self.Y[j], self.Z[k] - self.Z[j]), a)
        return _rot_apply(a, u, v), u

    def _solve_hinges(self):
        # _bone_frame_axis + _perp_unit + _move_pair, written out in place (no tuples).
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        clR = self.cl_R
        for ci, j, k, c, u0, h0, lo, hi, tol in self._hinge_fast:
            r0, r1, r2, r3, r4, r5, r6, r7, r8 = clR[ci]
            p, q, s_ = u0
            ax = r0 * p + r1 * q + r2 * s_; ay = r3 * p + r4 * q + r5 * s_; az = r6 * p + r7 * q + r8 * s_
            p, q, s_ = h0
            vx = r0 * p + r1 * q + r2 * s_; vy = r3 * p + r4 * q + r5 * s_; vz = r6 * p + r7 * q + r8 * s_
            xk = X[k]; yk = Y[k]; zk = Z[k]
            ux = xk - X[j]; uy = yk - Y[j]; uz = zk - Z[j]
            L0 = _sqrt(ux * ux + uy * uy + uz * uz)
            if L0 < 1e-12:
                ux, uy, uz = ax, ay, az
            else:
                ux /= L0; uy /= L0; uz /= L0
            # hinge axis = v turned by the minimal rotation taking a onto u
            cc = ax * ux + ay * uy + az * uz
            kx = ay * uz - az * uy; ky = az * ux - ax * uz; kz = ax * uy - ay * ux
            s = _sqrt(kx * kx + ky * ky + kz * kz)
            if s >= 1e-9:
                kx /= s; ky /= s; kz /= s
                kv = (kx * vx + ky * vy + kz * vz) * (1.0 - cc)
                hx = vx * cc + (ky * vz - kz * vy) * s + kx * kv
                hy = vy * cc + (kz * vx - kx * vz) * s + ky * kv
                hz = vz * cc + (kx * vy - ky * vx) * s + kz * kv
            elif cc > 0.0:
                hx, hy, hz = vx, vy, vz
            else:
                hx, hy, hz = _rot_apply((ax, ay, az), (ux, uy, uz), (vx, vy, vz))
            # bend reference = bone direction with its hinge-axis part removed
            kk = ux * hx + uy * hy + uz * hz
            dx = ux - kk * hx; dy = uy - kk * hy; dz = uz - kk * hz
            dn = _sqrt(dx * dx + dy * dy + dz * dz)
            if dn < 1e-6:
                continue
            dx /= dn; dy /= dn; dz /= dn
            wx = X[c] - xk; wy = Y[c] - yk; wz = Z[c] - zk
            L = _sqrt(wx * wx + wy * wy + wz * wz)
            if L < 1e-9:
                continue
            wx /= L; wy /= L; wz /= L
            hdx = hy * dz - hz * dy; hdy = hz * dx - hx * dz; hdz = hx * dy - hy * dx
            uh = wx * hx + wy * hy + wz * hz
            a = _atan2(wx * hdx + wy * hdy + wz * hdz, wx * dx + wy * dy + wz * dz)
            b = _asin(-1.0 if uh < -1.0 else (1.0 if uh > 1.0 else uh))
            a2 = lo if a < lo else (hi if a > hi else a)
            b2 = -tol if b < -tol else (tol if b > tol else b)
            if a2 == a and b2 == b:
                continue
            ca, sa, cb, sb = _cos(a2), _sin(a2), _cos(b2), _sin(b2)
            gx = xk + (cb * (ca * dx + sa * hdx) + sb * hx) * L
            gy = yk + (cb * (ca * dy + sa * hdy) + sb * hy) * L
            gz = zk + (cb * (ca * dz + sa * hdz) + sb * hz) * L
            wk, wc = W[k], W[c]
            ws = wk + wc
            if ws == 0.0:
                continue
            ex = gx - X[c]; ey = gy - Y[c]; ez = gz - Z[c]
            kc, kj = wc / ws, wk / ws
            X[c] += ex * kc; Y[c] += ey * kc; Z[c] += ez * kc
            X[k] = xk - ex * kj; Y[k] = yk - ey * kj; Z[k] = zk - ez * kj

    def _solve_self(self):
        X, Y, Z, W = self.X, self.Y, self.Z, self.W
        mute = self.self_mute
        for i, j, rs, rs2, free2 in self.self_pairs:
            dx = X[j] - X[i]; dy = Y[j] - Y[i]; dz = Z[j] - Z[i]
            d2 = dx * dx + dy * dy + dz * dz
            if d2 >= rs2:
                if mute and d2 > free2 and (i, j) in mute:
                    mute.discard((i, j))
                continue
            if mute and (i, j) in mute:
                continue
            ws = W[i] + W[j]
            if ws == 0.0:
                continue
            d = _sqrt(d2)
            if d < 1e-9:
                continue
            k = (d - rs) / (d * ws)
            a = k * W[i]; b = k * W[j]
            X[i] += dx * a; Y[i] += dy * a; Z[i] += dz * a
            X[j] -= dx * b; Y[j] -= dy * b; Z[j] -= dz * b

    def contact(self, i, nx, ny, nz, pen, wv, mu, e, kind):
        """Record a contact for this substep's velocity pass (and the impact report)."""
        self.contacts.append((i, nx, ny, nz, pen, wv, mu, e, kind))

    def bounds(self):
        X, Y, Z, m = self.X, self.Y, self.Z, self.maxr
        self.bb = (min(X) - m, min(Y) - m, min(Z) - m, max(X) + m, max(Y) + m, max(Z) + m)
        return self.bb

    def solve_env(self, h):
        """Hard non-penetration: screen planes, the depth slab, then the real Windows."""
        rect = self.world.rect
        X, Y, Z, R = self.X, self.Y, self.Z, self.R
        D = self.depth
        zero = (0.0, 0.0, 0.0)
        add = self.contacts.append
        fr, rest = RAG3_FRICTION, RAG3_RESTITUTION
        if rect is not None:
            l, t, r, b = rect
            for i in range(self.n):
                rad = R[i]
                y = Y[i]
                if y + rad > b:
                    pen = y + rad - b; Y[i] = b - rad
                    add((i, 0.0, -1.0, 0.0, pen, zero, fr, rest, "screen"))
                elif y - rad < t:
                    pen = t - (y - rad); Y[i] = t + rad
                    add((i, 0.0, 1.0, 0.0, pen, zero, fr, rest, "screen"))
                x = X[i]
                if x - rad < l:
                    pen = l - (x - rad); X[i] = l + rad
                    add((i, 1.0, 0.0, 0.0, pen, zero, fr, rest, "screen"))
                elif x + rad > r:
                    pen = x + rad - r; X[i] = r - rad
                    add((i, -1.0, 0.0, 0.0, pen, zero, fr, rest, "screen"))
        # The depth slab applies with or without a screen rect (before, a world that
        # had not been given a screen yet let bodies drift out of the slab forever).
        sf = RAG3_SLAB_FRICTION
        for i in range(self.n):
            lim = D - R[i]
            if lim < 0.0:
                lim = 0.0
            z = Z[i]
            if z > lim:
                add((i, 0.0, 0.0, -1.0, z - lim, zero, sf, 0.0, "slab"))
                Z[i] = lim
            elif z < -lim:
                add((i, 0.0, 0.0, 1.0, -lim - z, zero, sf, 0.0, "slab"))
                Z[i] = -lim
        wins = self.world._wins
        if not wins:
            return
        bb = self.bounds()
        mute = self.world._mute
        o = self.owner
        for hw, w in wins.items():
            wl, wt, wr, wb = w["rect"]
            if bb[3] < wl or bb[0] > wr or bb[4] < wt or bb[1] > wb:
                continue
            vx, vy = w["vel"]
            wv = (vx, vy, 0.0)
            for i in range(self.n):
                x, y, rad = X[i], Y[i], R[i]
                if x + rad <= wl or x - rad >= wr or y + rad <= wt or y - rad >= wb:
                    if mute and (o, i, hw) in mute:
                        mute.discard((o, i, hw))
                    continue
                if mute and (o, i, hw) in mute:
                    continue
                cx = wl if x < wl else (wr if x > wr else x)
                cy = wt if y < wt else (wb if y > wb else y)
                dx, dy = x - cx, y - cy
                d2 = dx * dx + dy * dy
                if d2 > 1e-12:
                    if d2 >= rad * rad:
                        continue
                    d = _sqrt(d2)
                    nx, ny, pen = dx / d, dy / d, rad - d
                else:                                        # centre inside: out the nearest side
                    el, er, et, eb = x - wl, wr - x, y - wt, wb - y
                    m = min(el, er, et, eb)
                    if m == et:
                        nx, ny, pen = 0.0, -1.0, et + rad
                    elif m == eb:
                        nx, ny, pen = 0.0, 1.0, eb + rad
                    elif m == el:
                        nx, ny, pen = -1.0, 0.0, el + rad
                    else:
                        nx, ny, pen = 1.0, 0.0, er + rad
                X[i] = x + nx * pen; Y[i] = y + ny * pen
                add((i, nx, ny, 0.0, pen, wv, fr, rest, "window"))

    def update_velocity(self, h):
        """v from the positions, then friction and restitution per contact."""
        X, Y, Z, OX, OY, OZ = self.X, self.Y, self.Z, self.OX, self.OY, self.OZ
        VX, VY, VZ = self.VX, self.VY, self.VZ
        inv = 1.0 / h
        contacts = self.contacts
        if contacts:                                         # approach speed BEFORE this substep's solve
            PX, PY, PZ = VX[:], VY[:], VZ[:]                 # (a C-level copy beats a per-contact dict)
        for i in range(self.n):
            vx = (X[i] - OX[i]) * inv; vy = (Y[i] - OY[i]) * inv; vz = (Z[i] - OZ[i]) * inv
            s2 = vx * vx + vy * vy + vz * vz
            if s2 > _MAXV2:
                k = RAG3_MAX_V / _sqrt(s2)
                vx *= k; vy *= k; vz *= k
            VX[i] = vx; VY[i] = vy; VZ[i] = vz
        if not contacts:
            return
        s = self._s
        v0, v1 = RAG3_BOUNCE_V0 * s, RAG3_BOUNCE_V1 * s
        span = max(1.0, v1 - v0)
        wall = self.world._wall
        mmax = self._mmax
        W, M = self.W, self.M
        for i, nx, ny, nz, pen, wv, mu, e, kind in contacts:
            if W[i] == 0.0:
                continue
            wvx, wvy, wvz = wv
            vpre = (PX[i] - wvx) * nx + (PY[i] - wvy) * ny + (PZ[i] - wvz) * nz
            rx = VX[i] - wvx; ry = VY[i] - wvy; rz = VZ[i] - wvz
            vn = rx * nx + ry * ny + rz * nz
            if vpre < 0.0:
                ap = -vpre
                ee = e * _smooth((ap - v0) / span) if ap > v0 else 0.0
                vn_new = ee * ap
                if kind != "slab":
                    self._contact_wall = wall
                    if ap > 60.0:
                        st = ap / RAG3_IMPACT_DIV * (0.35 + 0.65 * M[i] / mmax)
                        self.world._impact(self.owner, kind, st, X[i], Y[i])
            else:
                vn_new = vn if vn > 0.0 else 0.0
                if kind != "slab":
                    self._contact_wall = wall
            dvn = vn_new - vn
            rx += nx * dvn; ry += ny * dvn; rz += nz * dvn
            jn = vn_new - vpre if vpre < 0.0 else pen * inv
            if jn > 0.0 and mu > 0.0:
                vn2 = rx * nx + ry * ny + rz * nz
                tx, ty, tz = rx - vn2 * nx, ry - vn2 * ny, rz - vn2 * nz
                ts = _sqrt(tx * tx + ty * ty + tz * tz)
                if ts > 1e-9:
                    if ts <= RAG3_STATIC * mu * jn:
                        k = 1.0                              # static: she stays where she landed
                    else:
                        k = min(1.0, mu * jn / ts)
                    rx -= tx * k; ry -= ty * k; rz -= tz * k
            VX[i] = rx + wvx; VY[i] = ry + wvy; VZ[i] = rz + wvz

    def post_frame(self, dt):
        """Once per frame: tone decay, relative damping, blow-up net, safe pose, sleep."""
        self.age += dt
        self.tone = self.tone0 * math.exp(-self.age / RAG3_TONE_FADE)
        n = self.n
        X, Y, Z, VX, VY, VZ, M = self.X, self.Y, self.Z, self.VX, self.VY, self.VZ, self.M
        # ---- blow-up / NaN net
        worst = 0.0
        bad = False
        for i in range(n):
            x, y, z = X[i], Y[i], Z[i]
            if not (-1e9 < x < 1e9 and -1e9 < y < 1e9 and -1e9 < z < 1e9):
                bad = True; break
            s2 = VX[i] * VX[i] + VY[i] * VY[i] + VZ[i] * VZ[i]
            if not (s2 == s2):
                bad = True; break
            if s2 > worst:
                worst = s2
        if bad or worst > RAG3_BLAST_V * RAG3_BLAST_V:
            self.broken = True
            for i in range(n):
                X[i], Y[i], Z[i] = self._safe[i]
                VX[i] = VY[i] = VZ[i] = 0.0
            return
        self._safe = list(zip(X, Y, Z))
        touch = self.touching()
        # ---- sleep: lying still for a moment = skipped until something disturbs her
        sv = RAG3_SLEEP_V * self._s
        if self.grab_i < 0 and touch and worst < sv * sv:
            self._still += dt
            if self._still >= RAG3_SLEEP_TIME:
                self.sleep()
                return
        else:
            self._still = 0.0
        # ---- damp motion relative to the rigid-body motion (limp tissue, joint friction)
        damp = self.limp_damp + RAG3_TONE_DAMP * self.tone
        slow = _sqrt(worst) < RAG3_REST_DAMP_V * self._s
        if slow and touch:
            damp += RAG3_REST_DAMP
        k = 1.0 - math.exp(-damp * dt)
        if k <= 0.0:
            return
        mt = 0.0; cx = cy = cz = 0.0; px = py = pz = 0.0
        for i in range(n):
            m = M[i]; mt += m
            cx += m * X[i]; cy += m * Y[i]; cz += m * Z[i]
            px += m * VX[i]; py += m * VY[i]; pz += m * VZ[i]
        cx /= mt; cy /= mt; cz /= mt
        vcx, vcy, vcz = px / mt, py / mt, pz / mt
        Lx = Ly = Lz = 0.0
        i00 = i01 = i02 = i11 = i12 = i22 = 0.0
        for i in range(n):
            m = M[i]
            rx, ry, rz = X[i] - cx, Y[i] - cy, Z[i] - cz
            vx, vy, vz = VX[i] - vcx, VY[i] - vcy, VZ[i] - vcz
            Lx += m * (ry * vz - rz * vy); Ly += m * (rz * vx - rx * vz); Lz += m * (rx * vy - ry * vx)
            i00 += m * (ry * ry + rz * rz); i11 += m * (rx * rx + rz * rz); i22 += m * (rx * rx + ry * ry)
            i01 -= m * rx * ry; i02 -= m * rx * rz; i12 -= m * ry * rz
        det = (i00 * (i11 * i22 - i12 * i12) - i01 * (i01 * i22 - i12 * i02) + i02 * (i01 * i12 - i11 * i02))
        if abs(det) > 1e-9:
            inv = 1.0 / det
            b00 = (i11 * i22 - i12 * i12) * inv; b01 = (i02 * i12 - i01 * i22) * inv
            b02 = (i01 * i12 - i02 * i11) * inv; b11 = (i00 * i22 - i02 * i02) * inv
            b12 = (i01 * i02 - i00 * i12) * inv; b22 = (i00 * i11 - i01 * i01) * inv
            wx = b00 * Lx + b01 * Ly + b02 * Lz
            wy = b01 * Lx + b11 * Ly + b12 * Lz
            wz = b02 * Lx + b12 * Ly + b22 * Lz
        else:
            wx = wy = wz = 0.0
        W = self.W
        for i in range(n):
            if W[i] == 0.0:
                continue
            rx, ry, rz = X[i] - cx, Y[i] - cy, Z[i] - cz
            gx = vcx + wy * rz - wz * ry
            gy = vcy + wz * rx - wx * rz
            gz = vcz + wx * ry - wy * rx
            VX[i] += (gx - VX[i]) * k; VY[i] += (gy - VY[i]) * k; VZ[i] += (gz - VZ[i]) * k

    # --------------------------------------------------------------- sleeping
    def sleep(self):
        """Stop simulating her: velocities zeroed, bounding box frozen for wake tests."""
        self.sleeping = True
        self._still = 0.0
        n = self.n
        self.VX[:] = [0.0] * n; self.VY[:] = [0.0] * n; self.VZ[:] = [0.0] * n
        self.bounds()

    def wake(self):
        """Back into the simulation. She is still lying on whatever she slept on."""
        if not self.sleeping:
            return
        self.sleeping = False
        self._still = 0.0
        self._contact_wall = self.world._wall

    # ------------------------------------------------------------------ pose
    def rotations(self):
        """{body: 3x3 rotation since spawn, physics frame}. Parents before children."""
        out = {"pelvis": self.cl_R[0]}
        if self.has_chest:
            out["chest"] = self.cl_R[1]
        X, Y, Z = self.X, self.Y, self.Z
        for nm, par in self.bodies:
            if nm in out:
                continue
            j, k, u0, _p = self.bone_of[nm]
            Rp = out[par]
            a = _mv(Rp, u0)
            u = _unit((X[k] - X[j], Y[k] - Y[j], Z[k] - Z[j]), a)
            out[nm] = mat_mul(rot_between(a, u), Rp)
        return out

    def pose(self):
        """The fields shared code reads (same keys as ragphys.RagSkeleton.pose, plus z)."""
        i = self.idx["pelvis"]
        return dict(x=self.X[i], y=self.Y[i], z=self.Z[i], vx=self.VX[i], vy=self.VY[i], vz=self.VZ[i],
                    w=0.0, angle=0.0, rest=0.0, phi=[0.0] * len(self.bodies),
                    bones=[], parents=[], lims=[])

    def points(self):
        return [(nm, self.X[i], self.Y[i], self.Z[i], self.R[i]) for i, nm in enumerate(self.names)]

    def body_ends(self):
        out = []
        for nm, (j, k, _u, _p) in self.bone_of.items():
            out.append(((self.X[j], self.Y[j]), (self.X[k], self.Y[k]), self.R[k]))
        return out

    def lowest_point(self):
        return max(y + r for y, r in zip(self.Y, self.R))

    def speed(self):
        if self.sleeping:
            return 0.0
        VX, VY, VZ = self.VX, self.VY, self.VZ
        best = 0.0
        for i in range(self.n):
            s2 = VX[i] * VX[i] + VY[i] * VY[i] + VZ[i] * VZ[i]
            if s2 > best:
                best = s2
        return _sqrt(best)

    def touching(self):
        return self.sleeping or (self.world._wall - self._contact_wall) < RAG3_CONTACT_GRACE

    def joint_error(self):
        """(worst bone-length error px, worst cone/hinge overshoot rad) - tests and --rag-trace."""
        X, Y, Z = self.X, self.Y, self.Z
        be = max((abs(math.dist((X[i], Y[i], Z[i]), (X[j], Y[j], Z[j])) - L) for i, j, L in self.bones),
                 default=0.0)
        worst = 0.0
        for ci, j, c, n0, f0, o0, (Lf, Lb, Lo, Li) in self.cones:
            Rp = self.cl_R[ci]
            n = _mv(Rp, n0); f = _mv(Rp, f0); o = _mv(Rp, o0)
            u = _unit((X[c] - X[j], Y[c] - Y[j], Z[c] - Z[j]))
            un, uf, uo = _dot(u, n), _dot(u, f), _dot(u, o)
            sp = _sqrt(uf * uf + uo * uo)
            if sp < 1e-9:
                continue
            th = math.atan2(sp, un)
            tf, to = th * uf / sp, th * uo / sp
            e = (tf / (Lf if tf >= 0 else Lb)) ** 2 + (to / (Lo if to >= 0 else Li)) ** 2
            if e > 1.0:
                worst = max(worst, th - th / _sqrt(e))
        for bone, j, k, c, h0, (lo, hi), tol in self.hinges:
            h, d = self._bone_frame_axis(bone, h0)
            d = _perp_unit(d, h)
            if d is None:
                continue
            u = _unit((X[c] - X[k], Y[c] - Y[k], Z[c] - Z[k]))
            a = math.atan2(_dot(u, _cross(h, d)), _dot(u, d))
            worst = max(worst, lo - a, a - hi, abs(math.asin(max(-1.0, min(1.0, _dot(u, h))))) - tol)
        return be, max(0.0, worst)

    # ------------------------------------------------------------------ grab
    @property
    def grab_joint(self):
        """Truthy while a limb is held (ragphys.RagSkeleton exposes a joint here)."""
        return True if self.grab_i >= 0 else None

    def nearest(self, point, max_dist=None):
        md = RAG3_GRAB_RADIUS * self._s if max_dist is None else max_dist
        px, py = float(point[0]), float(point[1])
        best, bd = -1, md
        for i in range(self.n):
            d = math.hypot(self.X[i] - px, self.Y[i] - py) - self.R[i]
            d = 0.0 if d < 0.0 else d
            if d < bd:
                best, bd = i, d
        if best < 0:
            for i in range(self.n):
                d = math.hypot(self.X[i] - px, self.Y[i] - py)
                if best < 0 or d < bd:
                    best, bd = i, d
        return best, bd

    def grab(self, point, target=None):
        self.wake()
        self.release_grab()
        i, _d = self.nearest(point)
        if i < 0:
            return False
        tx, ty = target if target is not None else point
        self.grab_i = i
        self._grab_w = self.W[i]
        self.W[i] = 0.0                                      # held: infinitely heavy, the rest hangs off it
        self.grab_at = (float(tx), float(ty))
        self._grab_from = self._grab_to = (self.X[i], self.Y[i])
        self._grab_n = 1
        self.tone0 = self.tone = 0.0                         # a body hanging from a hand is fully limp
        return True

    def move_grab(self, target):
        if self.grab_i >= 0:
            self.grab_at = (float(target[0]), float(target[1]))

    def release_grab(self):
        i = self.grab_i
        if i < 0:
            return
        self.W[i] = self._grab_w or (1.0 / self.M[i])
        self.grab_i = -1
        cap = RAG3_GRAB_THROW_V
        for k in range(self.n):
            s2 = self.VX[k] ** 2 + self.VY[k] ** 2 + self.VZ[k] ** 2
            if s2 > cap * cap:
                f = cap / _sqrt(s2)
                self.VX[k] *= f; self.VY[k] *= f; self.VZ[k] *= f

    # ------------------------------------------------------------- impulses
    def impulse(self, point, imp, body=None):
        """Push the body at a screen point: dv spread over nearby particles by mass,
        so the hit limb moves most and the joints carry it into the rest of her."""
        self.wake()
        ix, iy = float(imp[0]), float(imp[1])
        iz = float(imp[2]) if len(imp) > 2 else 0.0
        px, py = float(point[0]), float(point[1])
        sig = 0.16 * self.ch
        wts = []
        for i in range(self.n):
            d2 = (self.X[i] - px) ** 2 + (self.Y[i] - py) ** 2
            wts.append(math.exp(-d2 / (2.0 * sig * sig)) * self.M[i])
        tw = sum(wts)
        if tw < 1e-9:
            i, _ = self.nearest(point, 1e9)
            wts = [0.0] * self.n; wts[i] = self.M[i]; tw = self.M[i]
        msum = sum(self.M[i] for i in range(self.n) if wts[i] > 1e-6 * tw)
        for i in range(self.n):
            if self.W[i] == 0.0 or wts[i] <= 0.0:
                continue
            share = wts[i] / tw                              # fraction of the impulse on this particle
            k = share * msum / self.M[i]                     # velocity change so momentum adds up
            self.VX[i] += ix * k; self.VY[i] += iy * k; self.VZ[i] += iz * k
        return True

    def shove(self, cursor, power=1.0):
        """Click / Launch: push her away from the cursor, the legacy direction and size."""
        self.wake()
        s = self._s
        i0 = self.idx["pelvis"]
        ix = max(-RAG3_SHOVE_CLAMP, min(RAG3_SHOVE_CLAMP, (self.X[i0] - cursor[0]) * RAG3_SHOVE_SIDE)) * power
        iy = -random.uniform(*RAG3_SHOVE_UP) * s * power
        iz = random.uniform(-RAG3_SHOVE_Z, RAG3_SHOVE_Z) * s * power
        j, _ = self.nearest(cursor, 1e9)
        for i in range(self.n):                              # the whole body moves...
            self.VX[i] += ix * 0.75; self.VY[i] += iy * 0.75; self.VZ[i] += iz * 0.5
        self.VX[j] += ix * 0.8; self.VY[j] += iy * 0.8; self.VZ[j] += iz      # ...the touched limb most
        self.tone = self.tone0 = 0.0

    # ------------------------------------------------------------ failsafes
    def explode_guard(self):
        if self.broken:
            return True
        fin = math.isfinite
        return not (all(map(fin, self.X)) and all(map(fin, self.Y)) and all(map(fin, self.Z)))

    def outside(self, rect, height):
        if not rect:
            return False
        l, t, r, b = rect
        i = self.idx["pelvis"]
        m = height * RAG3_OUTSIDE_H
        return self.X[i] < l - m or self.X[i] > r + m or self.Y[i] < t - m or self.Y[i] > b + m

    def snap_inside(self, rect, height):
        if not rect:
            return
        self.wake()
        l, t, r, b = rect
        i = self.idx["pelvis"]
        dx = (l + r) / 2.0 - self.X[i]
        dy = (b - height * 0.25) - self.Y[i]
        for k in range(self.n):
            self.X[k] += dx; self.Y[k] += dy; self.Z[k] = max(-self.depth, min(self.depth, self.Z[k]))
            self.OX[k], self.OY[k], self.OZ[k] = self.X[k], self.Y[k], self.Z[k]
            self.VX[k] = self.VY[k] = self.VZ[k] = 0.0
        self._safe = list(zip(self.X, self.Y, self.Z))
        self.bounds()

    def stop(self):
        for k in range(self.n):
            self.VX[k] = self.VY[k] = self.VZ[k] = 0.0

    def detach(self):
        self.world.remove_skeleton(self)
