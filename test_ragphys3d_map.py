#!/usr/bin/env python3
"""The 3D ragdoll's physics -> rig mapping, checked end to end on the REAL Mika rig.

Headless: Qt and moderngl are stubbed, the camera is the renderer's own maths
(same as the renderer builds it, minus the GL context). The chain under test is
exactly the production code in bapet/pet_rag3d.py:

    rag3_spec            bones -> 3D particles through the real camera (+ depth)
    Rag3DWorld           simulate a shot / a crumple / a slam
    rag3_build_map       K and the rig parent of every body
    rag3_posts_from      physics rotations -> 3x3 model-space posts
    Model.pose_world     posts applied the way the rig applies them
    rag3_model_matrix    the root's 3D rotation about the pelvis + depth scale
    window placement     set_feet(pelvis - rag_pel_dx, pelvis + drop)

and every rendered joint must land on its physics particle on screen (and in
depth). Run: python test_ragphys3d_map.py
"""
from __future__ import annotations

import math
import os
import random
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _m in ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtMultimedia",
           "moderngl"):
    sys.modules.setdefault(_m, mock.MagicMock())

import numpy as np  # noqa: E402

import ragphys3d as R3  # noqa: E402

_deps = types.ModuleType("bapet.deps")
_deps.ragphys3d = R3
_deps.ragphys = None
_deps.np = np
sys.modules["bapet.deps"] = _deps

from bapet.mathutil import m4, perspective, rot_y, scale4, translate  # noqa: E402
from bapet.model import Model  # noqa: E402
from bapet.pet_rag3d import PetRag3D, _m3  # noqa: E402

MODEL = os.path.join(HERE, "model", "Mika.glb")
FRAC, PADB, FOV = 0.58, 0.07, math.radians(16)
WIN_W, WIN_H = 380, 520
FLOOR = 1040.0


class Cam:
    """The renderer's camera without a GL context (see Renderer.set_fit / project)."""

    def __init__(self, fit):
        H = fit["H"]; V = H / FRAC
        self.V_world = V
        self.dist = V / (2 * math.tan(FOV / 2))
        cy = fit["miny"] + V / 2 - PADB * V
        self.eye = np.array([fit["cx"], cy, fit["cz"] + self.dist])
        self.view = translate(-self.eye)
        self.w, self.h = WIN_W, WIN_H
        self.proj = perspective(FOV, WIN_W / WIN_H, max(self.dist - H * 2.0, self.dist * 0.05), self.dist + H * 3.0)
        self.world_per_px = V / self.h
        self.PV = self.proj @ self.view

    def project(self, p3, M):
        v = self.PV @ (M @ np.array([p3[0], p3[1], p3[2], 1.0]))
        x, y = v[0] / v[3], v[1] / v[3]
        return (x * 0.5 + 0.5) * self.w, (1 - (y * 0.5 + 0.5)) * self.h


class FakePet(PetRag3D):
    """Just the attributes PetRag3D reads."""

    def __init__(self, model, clip, W, yaw):
        self.model, self.name = model, "Mika"
        self.clips = {"pickup": clip}
        fit = model.compute_fit(W)
        self.cam = Cam(fit)
        self.ch = types.SimpleNamespace(renderer=self.cam, body_frac=1.0)
        self.rig = types.SimpleNamespace(world_base=W)
        feet = np.array([fit["cx"], fit["miny"], fit["cz"]])
        self.last_M = translate(feet) @ scale4(1, 1, 1) @ m4(rot_y(yaw)) @ translate(-feet)
        self.dpr = 1.0
        self.W, self.H, self.PADB = WIN_W, WIN_H, PADB
        self.px = 760.0
        self.py = FLOOR - WIN_H * (1 - PADB)
        self.cfg = {"scale": 1.0, "ragdoll_3d_depth": 0.35, "ragdoll_3d_tone": 0.5}
        self.rag_names = [n.lower() for n in model.names]

    def rag_bone(self, token):
        for i, n in enumerate(self.rag_names):
            if n == token or n.endswith(" " + token):
                return i
        return None

    def rag_h(self):
        return self.H * FRAC


def _load():
    if not os.path.isfile(MODEL):
        return None
    model = Model(MODEL)
    clip = model.find_clip("Formation_Pickup") or model.rest_clip
    W = model.pose_world(clip.T[-1], clip.Q[-1], clip.S[-1])
    return model, clip, W


class TestMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load()

    def _check(self, yaw_extra, kick, mode, seconds, seed):
        if self.data is None:
            self.skipTest("model/Mika.glb not found")
        model, clip, W = self.data
        random.seed(seed)
        pet = FakePet(model, clip, W, model.face_yaw + yaw_extra)
        spec = pet.rag3_spec()
        self.assertIsNotNone(spec, "no spec for Mika")
        world = R3.Rag3DWorld()
        world.set_screen((0.0, 0.0, 1920.0, FLOOR))
        sk = world.add_skeleton(1, spec, kick, mode)
        for _ in range(int(seconds * 60)):
            world.step(1 / 60)
        K, pmap = pet.rag3_build_map(sk, pet.last_M)
        rots = sk.rotations()
        post = PetRag3D.rag3_posts_from(rots, dict(K=K, map=pmap))
        for _node, P in post:
            self.assertLess(float(np.abs(P @ P.T - np.eye(3)).max()), 1e-6, "a post is not a rotation")
        W2 = model.pose_world(clip.T[-1], clip.Q[-1], clip.S[-1], post)
        pose = sk.pose()
        pet.rag3 = dict(M0=pet.last_M, Rr=_m3(rots["pelvis"]), z=pose["z"],
                        fpx=pet.cam.dist / pet.cam.world_per_px)
        M3 = pet.rag3_model_matrix(W2)
        # the window follows the pelvis exactly as ragdoll_step_3d places it
        px = pose["x"] - pet.rag_pel_dx - WIN_W / 2
        py = pose["y"] + sk.drop - WIN_H * (1 - PADB)
        tok = pet.rag3_tokens()
        loc, _rad = pet.rag3_skull()
        wpp = pet.cam.world_per_px
        zs = PetRag3D.rag3_depth_scale(pet.rag3)
        gp = M3 @ np.append(W2[model.pelvis][:3, 3], 1.0)
        rows, worst, worst_z = [], 0.0, 0.0
        for nm, x, y, z, r in sk.points():
            p3 = (W2[tok["head"]] @ np.append(loc, 1.0))[:3] if nm == "head" else W2[tok[nm]][:3, 3]
            sx, sy = pet.cam.project(p3, M3)
            sx = px + sx * WIN_W / pet.cam.w
            sy = py + sy * WIN_H / pet.cam.h
            g = M3 @ np.append(p3, 1.0)
            zr = -(g[2] - gp[2]) / wpp / zs                  # depth in physics px, undoing the scale
            e = math.hypot(sx - x, sy - y)
            ez = abs(zr - (z - pose["z"]))
            worst = max(worst, e); worst_z = max(worst_z, ez)
            rows.append((nm, x, y, z, sx, sy, e, ez))
        spread = max(abs(z - pose["z"]) for _n, _x, _y, z, _r in sk.points())
        return sk, spec, rows, worst, worst_z, spread, pmap

    def _report(self, title, out):
        sk, spec, rows, worst, worst_z, spread, pmap = out
        print(f"\n  [{title}] worst on-screen error {worst:.2f}px, depth error {worst_z:.2f}px, "
              f"depth spread {spread:.0f}px, skull r {spec['head_r']:.1f}px "
              f"({spec['head_r'] / spec['ch']:.3f} x height), chest body: {sk.has_chest}")
        for nm, x, y, z, sx, sy, e, ez in rows:
            print(f"      {nm:<11} physics ({x:7.1f},{y:7.1f},{z:6.1f})  rendered ({sx:7.1f},{sy:7.1f})"
                  f"  err {e:5.2f}px  z err {ez:5.2f}")

    def test_a_shot_three_quarter_view(self):
        out = self._check(0.5, (1300.0, -250.0, 3.0), "shot", 0.55, 3)
        self._report("shot, 3/4 view", out)
        self.assertGreater(out[5], 15.0, "nothing moved in depth: not a 3D test")
        self.assertLess(out[3], 6.0, "rendered joints are off their physics particles")
        self.assertLess(out[4], 6.0, "rendered depth disagrees with the physics depth")

    def test_b_crumple_settled(self):
        out = self._check(0.0, (0.0, 0.0, 0.0), "crumple", 4.0, 5)
        self._report("crumple, settled, front view", out)
        self.assertLess(out[3], 6.0)
        self.assertLess(out[4], 6.0)

    def test_c_slam_profile(self):
        out = self._check(1.2, (2600.0, -200.0, 0.0), "slam", 1.2, 8)
        self._report("slam, near profile", out)
        self.assertLess(out[3], 6.0)
        self.assertLess(out[4], 6.0)

    def test_d_parents_follow_the_rig(self):
        out = self._check(0.0, (0.0, 0.0, 0.0), "kick", 0.1, 1)
        pmap = dict((b, p) for b, _n, p in out[6])
        print(f"\n  [d] rig parents: {pmap}")
        self.assertEqual(pmap.get("thigh_l"), "pelvis")
        self.assertEqual(pmap.get("calf_l"), "thigh_l")
        self.assertEqual(pmap.get("forearm_r"), "upperarm_r")
        self.assertIn(pmap.get("upperarm_l"), ("chest", "pelvis"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
