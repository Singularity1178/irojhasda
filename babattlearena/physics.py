"""Top-down ragdolls: ragphys3d with the screen turned into the floor.

The desktop pets' 3D engine (ragphys3d.py) simulates bodies in screen px with y DOWN (gravity)
and z INTO the screen. For the arena the computer screen is the floor, so the same engine is
used with its axes re-labelled - nothing in the solver changes:

    physics X = screen x
    physics Y = FLOOR - height above the floor      (gravity still pulls +Y: down onto the screen)
    physics Z = CZ - screen y                       (CZ = middle of the screen)

That is a proper rotation of the arena's GL frame G = (screen x, height, screen y) - the same
F = diag(1, -1, -1) the pets use between their GL world and physics - so pet_rag3d's bone
mapping (rag3_tokens / rag3_skull / rag3_build_map / rag3_posts_from) is reused unchanged.

What the engine sees as its "screen" walls becomes:
    floor         rect bottom (FLOOR = 0)        - the desktop
    left / right  the screen's left and right edges
    slab front/back (+-depth in Z)               - the screen's top and bottom edges
On top of that ArenaSkeleton.solve_env adds:
    boxes    3D boxes for props (crates are 0.5 heights tall - a body can land ON one) and real
             windows (infinitely tall walls), with the window's own velocity, so dragging a
             window into a lying student shoves her across the floor
    pillars  standing students as vertical cylinders: a flying body bounces off the people
             still on their feet
"""
from __future__ import annotations

import math

import numpy as np

import ragphys3d as R3
from bapet.pet_rag3d import PetRag3D, _F
from bapet.pet_skeleton import PetRagSkeleton

FLOOR = 0.0
TALL = 1.0e6


class ArenaSkeleton(R3.Rag3DSkeleton):
    def solve_env(self, h):
        super().solve_env(h)                      # floor, side walls, slab (screen top / bottom)
        W = self.world
        X, Y, Z, R = self.X, self.Y, self.Z, self.R
        add = self.contacts.append
        fr, rest = R3.RAG3_FRICTION, R3.RAG3_RESTITUTION
        bb = self.bounds()
        for (x0, x1, y0, y1, z0, z1, wv) in W.boxes:
            if bb[3] < x0 or bb[0] > x1 or bb[4] < y0 or bb[1] > y1 or bb[5] < z0 or bb[2] > z1:
                continue
            for i in range(self.n):
                x, y, z, rad = X[i], Y[i], Z[i], R[i]
                if x + rad <= x0 or x - rad >= x1 or y + rad <= y0 or y - rad >= y1 or z + rad <= z0 or z - rad >= z1:
                    continue
                cx = x0 if x < x0 else (x1 if x > x1 else x)
                cy = y0 if y < y0 else (y1 if y > y1 else y)
                cz = z0 if z < z0 else (z1 if z > z1 else z)
                dx, dy, dz = x - cx, y - cy, z - cz
                d2 = dx * dx + dy * dy + dz * dz
                if d2 > 1e-12:
                    if d2 >= rad * rad:
                        continue
                    d = math.sqrt(d2)
                    nx, ny, nz, pen = dx / d, dy / d, dz / d, rad - d
                else:                              # centre inside: leave by the nearest face
                    faces = ((x - x0, -1.0, 0.0, 0.0), (x1 - x, 1.0, 0.0, 0.0), (y - y0, 0.0, -1.0, 0.0),
                             (z - z0, 0.0, 0.0, -1.0), (z1 - z, 0.0, 0.0, 1.0))
                    m, nx, ny, nz = min(faces)
                    pen = m + rad
                X[i] = x + nx * pen; Y[i] = y + ny * pen; Z[i] = z + nz * pen
                add((i, nx, ny, nz, pen, wv, fr, rest, "window"))
        for (px, pz, pr, top) in W.pillars:
            if bb[3] < px - pr or bb[0] > px + pr or bb[5] < pz - pr or bb[2] > pz + pr:
                continue
            for i in range(self.n):
                if Y[i] < -top - R[i]:
                    continue
                dx, dz = X[i] - px, Z[i] - pz
                rs = pr + R[i]
                d2 = dx * dx + dz * dz
                if d2 >= rs * rs:
                    continue
                d = math.sqrt(d2) if d2 > 1e-9 else 1e-4
                nx, nz = (dx / d, dz / d) if d2 > 1e-9 else (1.0, 0.0)
                pen = rs - d
                X[i] += nx * pen; Z[i] += nz * pen
                add((i, nx, 0.0, nz, pen, (0.0, 0.0, 0.0), 0.5, 0.3, "pet"))


class ArenaWorld(R3.Rag3DWorld):
    def __init__(self, rect, iters=5):
        super().__init__(iters)
        l, t, r, b = rect
        self.screen = rect
        self.CZ = (t + b) / 2.0
        self.depth = (b - t) / 2.0
        self.boxes = []                           # (x0, x1, y0, y1, z0, z1, wall velocity)
        self.pillars = []                         # (x, z, radius, height)
        self.set_screen((l, FLOOR - TALL, r, FLOOR))

    # frames ----------------------------------------------------------
    def to_phys(self, sx, sy, h):
        return sx, FLOOR - h, self.CZ - sy

    def to_screen(self, X, Y, Z):
        """-> (screen x, screen y, height)"""
        return X, self.CZ - Z, FLOOR - Y

    def g_to_phys(self, g):                       # arena GL frame G = (x, height, y)
        return float(g[0]), FLOOR - float(g[1]), self.CZ - float(g[2])

    # colliders -------------------------------------------------------
    def set_boxes(self, boxes):
        """boxes: geometry.Box list (props + windows)."""
        out = []
        for bx in boxes:
            if not bx.alive: continue
            h = TALL if bx.kind == "window" else bx.height
            out.append((bx.l, bx.r, FLOOR - h, FLOOR + 1.0, self.CZ - bx.b, self.CZ - bx.t,
                        (bx.vx, 0.0, -bx.vy)))
        if out != self.boxes:
            self.boxes = out
            for s in self._skels.values():
                s.wake()

    def set_pillars(self, pillars):
        self.pillars = pillars

    def add_skeleton(self, owner_id, spec, kick=None, mode="kick", hit=None):
        skel = ArenaSkeleton(self, owner_id, spec, kick, mode, hit)
        old = self._skels.get(owner_id)
        if old is not None:
            self.remove_skeleton(old)
        self._skels[owner_id] = skel
        bs = skel.bounds()
        for o in self._skels.values():
            if o is skel or o.detached:
                continue
            bo = o.bounds()
            if bs[0] > bo[3] or bo[0] > bs[3] or bs[1] > bo[4] or bo[1] > bs[4] or bs[2] > bo[5] or bo[2] > bs[5]:
                continue
            o.wake()
            for i in range(skel.n):
                for j in range(o.n):
                    dx = skel.X[i] - o.X[j]; dy = skel.Y[i] - o.Y[j]; dz = skel.Z[i] - o.Z[j]
                    rs = skel.R[i] + o.R[j]
                    if dx * dx + dy * dy + dz * dz < rs * rs:
                        self._pet_mute.add((skel.owner, i, o.owner, j))
        return skel

    def blast(self, sx, sy, radius, power, exclude=()):
        """An explosion on the floor pushes every ragdoll in reach (they are already down)."""
        X0, _Y0, Z0 = self.to_phys(sx, sy, 0.0)
        for s in list(self._skels.values()):
            if s.detached or s.owner in exclude:
                continue
            i = s.idx["pelvis"]
            dx, dz = s.X[i] - X0, s.Z[i] - Z0
            d = math.hypot(dx, dz)
            if d > radius:
                continue
            k = (1.0 - d / radius) * power
            nx, nz = (dx / d, dz / d) if d > 1e-3 else (0.0, 0.0)
            s.impulse((s.X[i], s.Y[i]), (nx * k, -k * 0.9, nz * k))


class RagBinding:
    """The pet code's bone mapping, bound to a Character instead of a Pet window."""
    rag_bone = PetRagSkeleton.rag_bone
    rag3_tokens = PetRag3D.rag3_tokens
    rag3_skull = PetRag3D.rag3_skull
    rag3_build_map = PetRag3D.rag3_build_map
    rag3_posts_from = staticmethod(PetRag3D.rag3_posts_from)

    def __init__(self, ch):
        self.ch = ch
        self.model = ch.model
        self.clips = ch.clips
        self.name = ch.name
        self.rag_names = [n.lower() for n in ch.model.names]
        self.ok = self.rag3_tokens() is not None


_BINDINGS = {}


def binding_for(ch):
    b = _BINDINGS.get(id(ch))
    if b is None or b.ch is not ch:
        b = _BINDINGS[id(ch)] = RagBinding(ch)
    return b


def build_spec(world, binding, Wb, M0, ch_px, scale, sole=FLOOR):
    """ragphys3d spec from the frozen pose Wb and the arena model matrix M0 (model -> G px)."""
    tok = binding.rag3_tokens()
    if tok is None:
        return None

    def P(p3):
        g = M0 @ np.append(np.asarray(p3, dtype=np.float64), 1.0)
        return world.g_to_phys(g)
    pts = {nm: P(Wb[node][:3, 3]) for nm, node in tok.items() if nm != "head"}
    sc = float(abs(np.linalg.det(M0[:3, :3]))) ** (1.0 / 3.0)
    skull = binding.rag3_skull()
    head_r = None
    if skull is not None:
        loc, rad = skull
        pts["head"] = P((Wb[tok["head"]] @ np.append(loc, 1.0))[:3])
        head_r = max(0.07 * ch_px, min(0.22 * ch_px, rad * sc))
    else:
        hb, nk = np.array(P(Wb[tok["head"]][:3, 3])), np.array(pts["neck"])
        up = hb - nk
        n = np.linalg.norm(up)
        up = up / n if n > 1e-6 else np.array([0.0, -1.0, 0.0])
        pts["head"] = tuple(hb + up * 0.12 * ch_px)
    fwd = None
    toes = getattr(binding, "_rag3_toes", (None, None))
    vs = []
    for sd, t in zip("lr", toes):
        if t is not None:
            vs.append(np.array(P(Wb[t][:3, 3])) - np.array(pts[f"foot_{sd}"]))
    if vs:
        v = np.sum(vs, axis=0); v[1] = 0.0
        if np.linalg.norm(v) > 1e-6:
            fwd = tuple(v / np.linalg.norm(v))
    pel = pts["pelvis"]
    return dict(scale=scale, ch=ch_px, depth=world.depth, tone=0.45, drop=sole - pel[1], pts=pts,
                head_r=head_r, fwd=fwd, sole=sole)


def posts_and_root(binding, sk, st):
    rots = sk.rotations()
    return binding.rag3_posts_from(rots, st), np.asarray(rots["pelvis"], dtype=np.float64).reshape(3, 3)


def ragdoll_matrix(st, Rr, g_now):
    """Model matrix while limp: spawn matrix turned about the spawn pelvis, moved to the live one."""
    R4 = np.eye(4); R4[:3, :3] = _F @ Rr @ _F
    T1 = np.eye(4); T1[:3, 3] = g_now
    T0 = np.eye(4); T0[:3, 3] = -np.asarray(st["P0"])
    return T1 @ R4 @ T0 @ st["M0"]
