"""Matrix / quaternion helpers and clip sampling (column-vector convention, numpy 4x4)."""
from __future__ import annotations

import math

import numpy as np


def rot_axis(axis, ang):
    """Rodrigues: 3x3 rotation of `ang` radians about unit `axis` (right-handed)."""
    x, y, z = axis; c, s = math.cos(ang), math.sin(ang); t = 1 - c
    return np.array([[t*x*x + c,   t*x*y - s*z, t*x*z + s*y],
                     [t*x*y + s*z, t*y*y + c,   t*y*z - s*x],
                     [t*x*z - s*y, t*y*z + s*x, t*z*z + c]])


# =============================================================================
#  math helpers (column-vector convention, numpy 4x4)
# =============================================================================
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def wrap_pi(a):
    """Angle folded into [-pi, pi): the shortest signed turn."""
    return (a + math.pi) % math.tau - math.pi

def fade_back(d, a=1.6, b=2.6):
    """1 while a target is within ~90 deg of where she faces, 0 once it is behind her."""
    return clamp((b - abs(d)) / (b - a), 0.0, 1.0)

def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)

def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)

def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)

def m4(R=None, t=None):
    M = np.eye(4)
    if R is not None: M[:3, :3] = R
    if t is not None: M[:3, 3] = t
    return M

def translate(t):
    return m4(None, np.asarray(t, dtype=np.float64))

def rot_z4(a):
    M = np.eye(4); c, s = math.cos(a), math.sin(a)
    M[0, 0] = c; M[0, 1] = -s; M[1, 0] = s; M[1, 1] = c
    return M

def scale4(x, y, z):
    return np.diag([x, y, z, 1.0])

def perspective(fovy, aspect, n, f, zoom=1.0, shift_y=0.0):
    """Standard perspective.

    `zoom` scales the focal length and `shift_y` is an off-axis (lens) shift, in
    NDC. Together they open the view up without moving the camera: the projection
    stays exactly homothetic about the eye, at any depth, so the image is the old
    one scaled and translated (see Renderer.set_fit).

    The shift goes into the z coefficient rather than the w column on purpose: NDC
    is clip / w_clip with w_clip = -z, so a term in the w column is divided by the
    depth again (it would be depth-dependent, i.e. a shear), while one in the z
    coefficient survives the divide as a true constant.
    """
    t = zoom / math.tan(fovy / 2.0)
    M = np.zeros((4, 4))
    M[0, 0] = t / aspect; M[1, 1] = t
    M[1, 2] = -shift_y                            # after the divide by w_clip: +shift_y in NDC
    M[2, 2] = (f + n) / (n - f); M[2, 3] = 2 * f * n / (n - f); M[3, 2] = -1.0
    return M

def mat_bytes(M):
    return np.ascontiguousarray(np.asarray(M, dtype=np.float32).T).tobytes()

def quat_to_rot(q):
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    R = np.empty((len(q), 3, 3))
    R[:, 0, 0] = 1 - 2 * (y * y + z * z); R[:, 0, 1] = 2 * (x * y - z * w); R[:, 0, 2] = 2 * (x * z + y * w)
    R[:, 1, 0] = 2 * (x * y + z * w); R[:, 1, 1] = 1 - 2 * (x * x + z * z); R[:, 1, 2] = 2 * (y * z - x * w)
    R[:, 2, 0] = 2 * (x * z - y * w); R[:, 2, 1] = 2 * (y * z + x * w); R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R

def compose_trs(T, Q, S):
    n = len(T)
    M = np.zeros((n, 4, 4))
    M[:, :3, :3] = quat_to_rot(Q) * S[:, None, :]
    M[:, :3, 3] = T
    M[:, 3, 3] = 1.0
    return M

def pelvis_track(chain, T, Q, S):
    """World position of the pelvis bone through every frame of a clip.

    Only the ancestor chain is composed (a handful of nodes) instead of the whole
    skeleton, so this stays cheap even for long clips.
    """
    W = None
    for nd in chain:                                  # T/Q/S are (F, n_nodes, ...)
        q, t, s = Q[:, nd], T[:, nd], S[:, nd]
        L = np.zeros((len(t), 4, 4))
        L[:, :3, :3] = quat_to_rot(q) * s[:, None, :]
        L[:, :3, 3] = t
        L[:, 3, 3] = 1.0
        W = L if W is None else np.matmul(W, L)
    return W[:, :3, 3]                               # (F, 3)

def mat_to_quat(R):
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2; w = .25 * s
        x = (R[2, 1] - R[1, 2]) / s; y = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w = (R[2, 1] - R[1, 2]) / s; x = .25 * s; y = (R[0, 1] + R[1, 0]) / s; z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w = (R[0, 2] - R[2, 0]) / s; x = (R[0, 1] + R[1, 0]) / s; y = .25 * s; z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w = (R[1, 0] - R[0, 1]) / s; x = (R[0, 2] + R[2, 0]) / s; y = (R[1, 2] + R[2, 1]) / s; z = .25 * s
    q = np.array([x, y, z, w]); return q / np.linalg.norm(q)

def decompose(m):
    t = m[:3, 3].copy()
    sc = np.linalg.norm(m[:3, :3], axis=0)
    sc[sc < 1e-12] = 1.0
    if np.linalg.det(m[:3, :3]) < 0: sc[0] = -sc[0]
    return t, mat_to_quat(m[:3, :3] / sc), sc

def slerp(q0, q1, t):
    d = np.sum(q0 * q1, axis=-1, keepdims=True)
    q1 = np.where(d < 0, -q1, q1)
    d = np.clip(np.abs(d), 0.0, 1.0)
    th = np.arccos(d); sn = np.sin(th)
    near = sn < 1e-5
    den = np.where(near, 1.0, sn)
    a = np.where(near, 1.0 - t, np.sin((1.0 - t) * th) / den)
    b = np.where(near, t, np.sin(t * th) / den)
    q = a * q0 + b * q1
    return q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)

def mats_to_quats(R):
    """(N,3,3) rotation matrices -> (N,4) xyzw quaternions (vectorised mat_to_quat)."""
    r00, r01, r02 = R[:, 0, 0], R[:, 0, 1], R[:, 0, 2]
    r10, r11, r12 = R[:, 1, 0], R[:, 1, 1], R[:, 1, 2]
    r20, r21, r22 = R[:, 2, 0], R[:, 2, 1], R[:, 2, 2]
    cand = np.stack([1 + r00 - r11 - r22, 1 - r00 + r11 - r22,
                     1 - r00 - r11 + r22, 1 + r00 + r11 + r22], axis=1)
    k = cand.argmax(axis=1)
    s = np.sqrt(np.maximum(cand[np.arange(len(R)), k], 1e-12)) * 2.0
    q = np.empty((len(R), 4))
    for case, (x, y, z, w) in enumerate((
            (.25 * s, (r01 + r10) / s, (r02 + r20) / s, (r21 - r12) / s),
            ((r01 + r10) / s, .25 * s, (r12 + r21) / s, (r02 - r20) / s),
            ((r02 + r20) / s, (r12 + r21) / s, .25 * s, (r10 - r01) / s),
            ((r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s, .25 * s))):
        m = k == case
        q[m, 0], q[m, 1], q[m, 2], q[m, 3] = x[m], y[m], z[m], w[m]
    return q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)

def smootherstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)

def _split_world(W):
    """World matrices -> (translation, quaternion, scale, clean?).

    `clean` is False for a node that cannot be split without loss (mirrored, a
    collapsed show/hide scale, or sheared by a rotated non-uniform parent). Those
    are blended linearly instead, which is what the old code did for everything.
    """
    A = W[:, :3, :3]
    sc = np.linalg.norm(A, axis=1)                          # column lengths
    ok = sc.min(axis=1) > 1e-3
    R = A / np.where(sc < 1e-9, 1.0, sc)[:, None, :]
    ok &= np.linalg.det(R) > 0.5
    q = mats_to_quats(R)
    ok &= np.abs(quat_to_rot(q) * sc[:, None, :] - A).max(axis=(1, 2)) <= 2e-3 * np.maximum(sc.max(axis=1), 1e-6)
    return W[:, :3, 3], q, sc, ok

def blend_world(Wa, Wb, k):
    """Blend two sets of world matrices: slerp the rotation, lerp position and scale.

    Lerping the raw matrices (what this used to do) shrinks every limb in the middle
    of a fade - the in-between rotation has a length < 1 - which reads as the whole
    character pulsing smaller and swimming between clips. Rotating along the arc keeps
    bone lengths, so a limb swings from one pose to the other instead of folding.
    """
    if k <= 0.0: return Wa.copy()
    if k >= 1.0: return Wb.copy()
    ta, qa, sa, oka = _split_world(Wa)
    tb, qb, sb, okb = _split_world(Wb)
    out = Wa * (1 - k) + Wb * k                              # fallback for the unclean nodes
    ok = oka & okb
    if ok.any():
        q = slerp(qa[ok], qb[ok], np.full((int(ok.sum()), 1), k))
        sc = sa[ok] * (1 - k) + sb[ok] * k
        blk = out[ok]
        blk[:, :3, :3] = quat_to_rot(q) * sc[:, None, :]
        blk[:, :3, 3] = ta[ok] * (1 - k) + tb[ok] * k
        out[ok] = blk
    return out

def _loop_seam(c):
    """Seconds over which a looping clip is eased back onto its own first frame.

    Most clips loop cleanly (last frame == first frame) and get 0. A clip whose last
    pose differs from its first would visibly pop once per loop, so its final stretch
    is blended toward frame 0 - the wrap is then continuous.
    """
    s = getattr(c, "_seam", None)
    if s is None:
        s = 0.0
        if c.T.shape[0] > 2 and c.duration > 0:
            d = np.abs(np.sum(c.Q[0] * c.Q[-1], axis=-1)).clip(0.0, 1.0)
            if float(np.max(2.0 * np.arccos(d))) > 0.02:      # > ~1 degree on some bone
                s = min(0.12, 0.2 * c.duration)
        c._seam = s
    return s

def sample_clip(c, t, loop):
    """One clip at time t -> (T, Q, S, root offset, morph weights or None)."""
    F = c.T.shape[0]
    if F < 2:
        return c.T[0], c.Q[0], c.S[0], c.origin + c.pin[0], (c.Wt[0] if c.Wt is not None else None)
    f = min(t / c.duration, 1.0) * (F - 1) if c.duration > 0 else 0.0
    i0 = min(int(f), F - 2); u = f - i0
    T = c.T[i0] * (1 - u) + c.T[i0 + 1] * u
    S = c.S[i0] * (1 - u) + c.S[i0 + 1] * u
    Q = slerp(c.Q[i0], c.Q[i0 + 1], np.full((c.Q.shape[1], 1), u))
    # A1: the root-motion pin rides along with the pose so it cross-fades too,
    # instead of snapping on the first frame of the new clip.
    pin = c.pin[i0] * (1 - u) + c.pin[i0 + 1] * u
    if loop:
        seam = _loop_seam(c)
        if seam > 0.0 and t > c.duration - seam:
            w = smootherstep((t - (c.duration - seam)) / seam)
            T = T * (1 - w) + c.T[0] * w
            S = S * (1 - w) + c.S[0] * w
            Q = slerp(Q, c.Q[0], np.full((Q.shape[0], 1), w))
            pin = pin * (1 - w) + c.pin[0] * w
    return T, Q, S, c.origin + pin, (c.Wt[i0] if c.Wt is not None else None)
