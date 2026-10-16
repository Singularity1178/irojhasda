#!/usr/bin/env python3
"""Lifecycle smoke test for the 3D engine through the REAL Pet mixins, headless.

start_ragdoll (engine "3d") -> fall frames (ragdoll_step / rag_limb_post / the 3D
model matrix) -> rest -> rag_getup -> blend -> rag_end -> standing, clean world.
Qt / GL are stubbed; the rig, model and maths are real (model/Mika.glb).
"""
from __future__ import annotations

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
_deps.ragphys3d, _deps.ragphys, _deps.np = R3, None, np
sys.modules["bapet.deps"] = _deps

from bapet.model import Model  # noqa: E402
from bapet.pet_rag3d import PetRag3D  # noqa: E402
from bapet.pet_rag_pose import PetRagPose  # noqa: E402
from bapet.pet_rag_step import PetRagStep  # noqa: E402
from bapet.pet_ragdoll import PetRagdoll  # noqa: E402
from test_ragphys3d_map import FLOOR, MODEL, FakePet  # noqa: E402


class Rect:
    def __init__(self, l, t, r, b): self.l, self.t, self.r, self.b = l, t, r, b
    def left(self): return self.l
    def top(self): return self.t
    def right(self): return self.r
    def bottom(self): return self.b


class Rig:
    def __init__(self, W): self.world_base, self.limp, self.dangle_on, self.rag_post = W, False, True, []
    def play(self, *a, **k): pass
    def set_limp(self, on): self.limp = on
    def advance(self, dt): pass


class Pet(PetRagdoll, PetRagStep, PetRagPose, FakePet):        # FakePet brings PetRag3D
    G = 2600.0

    def __init__(self, model, clip, W):
        FakePet.__init__(self, model, clip, W, model.face_yaw + 0.3)
        self.M_base = self.last_M.copy()
        self.rig = Rig(W)
        self.T, self.Q, self.S = clip.T[-1], clip.Q[-1], clip.S[-1]
        self.A = types.SimpleNamespace(rag_world=None, rag_world3d=R3.Rag3DWorld(), rag_trace=0,
                                       resolve_screen=lambda: Rect(0, 0, 1919, FLOOR - 1),
                                       surfaces=lambda x, perch: [], floor_y=lambda x: FLOOR,
                                       play_rag_sound=lambda: None)
        self.A.rag_world3d.set_screen((0.0, 0.0, 1920.0, FLOOR))
        self.cfg.update(ragdoll_engine="3d", ragdoll_auto_getup=True, perch=False)
        for k in ("rag_t", "rag_rest", "rag_hit_t", "rg_x", "rg_y", "rg_vx", "rg_vy", "rg_a", "rg_w",
                  "rg_ax", "rg_ay", "rg_alpha", "vx", "vy", "sq", "sq_v", "ori_p", "ori_t", "roll", "roll_v",
                  "pitch_hold", "pitch_hold_v"):
            setattr(self, k, 0.0)
        self.ragdoll = self.dragging = self.rag_want_up = self.rag_edge_slam = self.rag_contact = False
        self.rag_skel = self.rag3 = self.rg_top = self.rag_phi = self.meet_target = None
        self.rag_state, self.rag_owner, self.rag_bones, self.rag_com = "fall", 1, [], 0.5
        self.grounded, self.support, self.rag3_failed, self.rag_pm_failed = True, None, False, False
        self.rg_grav = self.rag_strength = 1.0
        self.state, self.events = "idle", []

    # --- the parts of Pet the ragdoll calls, reduced to their effect
    def isVisible(self): return True
    def chat_abort(self): pass
    def set_ride(self, *a, **k): pass
    def say(self, *a, **k): pass
    def line(self, k): return k
    def plan_next(self): pass
    def emit_impact(self, *a): self.events.append("impact")
    def enter(self, state, *a): self.state = state
    def set_feet(self, fx, fy): self.px, self.py = fx - self.W / 2, fy - self.H * (1 - self.PADB)
    def feet_pos(self): return self.px + self.W / 2, self.py + self.H * (1 - self.PADB)
    def reset_position(self): self.events.append("reset")

    # The limp window (PetWindow): this harness has a fixed-size stub camera with no
    # fit to widen, and the window it draws into is not what is under test here, so
    # growing it is a no-op and the standing size is simply the window size.
    def rag_window(self, on): self.events.append("rag_window" if on else "rag_window_off")
    def stand_w(self): return self.W
    def stand_h(self): return self.H

    def render_frame(self, _cur=None):
        post = self.rag_limb_post(1 / 60) if self.ragdoll else []
        world = self.model.pose_world(self.T, self.Q, self.S, post)
        self.last_M = self.rag3_model_matrix(world) if (self.ragdoll and self.rag3) else self.M_base
        return world


class TestLifecycle(unittest.TestCase):
    def test_start_fall_getup_stand(self):
        if not os.path.isfile(MODEL):
            self.skipTest("model/Mika.glb not found")
        random.seed(2)
        model = Model(MODEL)
        clip = model.find_clip("Formation_Pickup") or model.rest_clip
        W = model.pose_world(clip.T[-1], clip.Q[-1], clip.S[-1])
        pet = Pet(model, clip, W)
        pet.start_ragdoll(kick=False, impulse=(1200.0, -250.0, 3.0))       # shot
        self.assertTrue(pet.ragdoll and pet.rag3 is not None, "3D engine did not take her")
        self.assertTrue(getattr(pet.rag_skel, "is3d", False))
        frames, phases = 0, set()
        while pet.ragdoll and frames < 60 * 15:
            pet.A.rag_world3d.step(1 / 60)
            pet.ragdoll_step(1 / 60)
            if pet.ragdoll:
                pet.render_frame()
                self.assertTrue(np.all(np.isfinite(pet.last_M)))
                phases.add(pet.rag3["phase"] if pet.rag3 else "done")
            frames += 1
        self.assertFalse(pet.ragdoll, "she never got back up")
        self.assertIn("getup", phases)
        self.assertIsNone(pet.rag3); self.assertIsNone(pet.rag_skel)
        self.assertFalse(pet.A.rag_world3d._skels, "her skeleton was left in the world")
        self.assertEqual(pet.state, "shot")                                # rag_end's react clip
        fx, fy = pet.feet_pos()
        self.assertAlmostEqual(fy, FLOOR, delta=1.0)
        self.assertNotIn("reset", pet.events, "a failsafe fired")
        self.assertEqual(pet.events.count("rag_window"), 1,
                         "she went limp without ever being given the bigger window")
        self.assertEqual(pet.events.count("rag_window_off"), 1,
                         "the bigger window was never handed back when she stood up")
        print(f"\n  [pet] shot -> down -> up in {frames / 60:.2f}s, feet back on the floor at y={fy:.1f}, "
              f"{pet.events.count('impact')} dust puffs, phases {sorted(phases)}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
