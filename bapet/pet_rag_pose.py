"""Pet mixin: turning the physics pose into bone rotations."""
from __future__ import annotations

import math

import numpy as np

from .mathutil import clamp, rot_axis


class PetRagPose:
    # ---------------- ragdoll: layer 2, limbs as damped pendulums ----------------
    def rag_limb_post(self, dt):
        """The rig's `post` list for this frame.

        With the articulated engine this is the physics pose written straight
        onto the bones (rag_post_pm). Otherwise it is the legacy layer-2 model:
        one angle and one velocity per limb, driven by apparent gravity, the
        body's acceleration and its spin.
        """
        if self.rag3 is not None:                    # fully 3D engine: full 3x3 posts (pet_rag3d.py)
            return self.rag3_post()
        if self.rag_skel is not None:
            return self.rag_post_pm()
        if self.rag_phi is not None:                 # get-up blend, no skeleton left
            return self.rag_post_getup()
        if not self.rag_bones: return []
        # world_base, not world: measuring against the posed world would let each
        # limb's own swing tilt its parent's pendulum (see Rig.evaluate).
        W, Mn = self.rig.world_base, self.last_M; R = self.ch.renderer; G = self.G
        if Mn is None or not np.all(np.isfinite(Mn)): return []
        # rotating about the SCREEN Z axis, expressed in model space
        # (robust to face_yaw / yaw_offset / the body rotation itself)
        axis = Mn[:3, :3].T @ np.array([0.0, 0.0, 1.0]); axis = axis / (np.linalg.norm(axis) + 1e-12)
        # apparent gravity in screen space (y up), in units of g. Free fall -> (0, 0): limbs float.
        gx, gy = -self.rg_ax / G, -1.0 + self.rg_ay / G
        target = 0.15 if self.rag_contact else 1.0          # lying on the floor: arms relax, don't sink through it
        self.rg_grav += (target - self.rg_grav) * (1 - math.exp(-dt * 6))
        grav = self.rg_grav if self.rag_state == "fall" else 0.0
        n = max(1, int(math.ceil(dt * 90.0))); h = dt / n
        wpp = R.world_per_px * max(1e-6, self.dpr)
        post = []
        for L in self.rag_bones:
            pb = Mn @ np.append(W[L["b"]][:3, 3], 1.0); pc = Mn @ np.append(W[L["c"]][:3, 3], 1.0)
            d0 = pc[:2] - pb[:2]; ln = float(np.hypot(d0[0], d0[1]))
            if ln < 1e-9: continue
            d0 /= ln
            ln_px = ln / wpp
            K = min(80.0, G / max(30.0, ln_px))            # pendulum gain = g / length
            k_soft = L["k"] * (1.0 + 2.0 * (1.0 - self.rg_grav))
            for _ in range(n):
                # Where the limb points right now: the base direction turned by the
                # angle we are about to apply. pose_world rotates every bone rigidly
                # about its own position, so this is exactly what ends up on screen.
                c_, s_ = math.cos(L["d"]), math.sin(L["d"])
                dx, dy = d0[0] * c_ - d0[1] * s_, d0[0] * s_ + d0[1] * c_
                cross = dx * gy - dy * gx                                   # >0 = pulls limb CCW
                acc = K * grav * cross + self.rg_alpha - k_soft * L["d"] - L["damp"] * L["dd"]
                L["dd"] += acc * h; L["d"] += L["dd"] * h
                if abs(L["d"]) > L["lim"]:
                    L["d"] = clamp(L["d"], -L["lim"], L["lim"]); L["dd"] *= -0.3
            post.append((int(L["b"]), rot_axis(axis, L["d"] * self.rag_strength)))
        return post

    def rag_post_axis(self):
        """The screen Z axis expressed in model space, for the post rotations.

        Same expression as the legacy code below: robust to face_yaw, the cfg
        yaw_offset and the body rotation itself, because it is derived from the
        matrix that actually put her on screen.
        """
        Mn = self.last_M
        if Mn is None or not np.all(np.isfinite(Mn)):
            return None
        axis = Mn[:3, :3].T @ np.array([0.0, 0.0, 1.0])
        return axis / (np.linalg.norm(axis) + 1e-12)

    def rag_post_pm(self):
        """Physics pose -> one post rotation per bone.

        For every non-root body, the angle to write is the RELATIVE one:

            post_i = -(phi_i - phi_parent_i)

        Two reasons it is relative rather than absolute. Model.pose_world applies
        each post about that bone's own position and composes down the hierarchy,
        so a child already inherits its ancestors' posts - writing an absolute
        angle would apply the parent's rotation twice. And the root itself is not
        in the list at all: its figure rotation is render_frame's
        rot_z4(-rg_a), applied to the model matrix, and rg_a = +phi_pelvis.

        The sign is negated because the two spaces disagree. Physics measures
        angles with atan2 in y-DOWN screen px, where positive turns clockwise on
        screen; rot_axis about +Z is right-handed in a y-UP frame, where positive
        turns counter-clockwise on screen. test_ragphys.py 7a/7b/7c pins this
        down against the real rig, and 7c checks the whole chain to 2 px.
        """
        sk = self.rag_skel
        axis = self.rag_post_axis()
        if sk is None or axis is None:
            return []
        phi = sk.pose()["phi"]
        parents, bones = sk.parents, sk.bones
        st = self.rag_strength
        post = []
        for i in range(len(phi)):
            p = parents[i]
            if p < 0:
                continue                            # the root is rg_a's job
            post.append((int(bones[i]), rot_axis(axis, -(phi[i] - phi[p]) * st)))
        return post

    def rag_post_getup(self):
        """The get-up blend: the same relative posts, scaled to zero."""
        axis = self.rag_post_axis()
        phi = self.rag_phi
        if axis is None or not phi:
            return []
        sk = self.rag_pm_bones
        if not sk:
            return []
        post = []
        for i in range(len(phi)):
            p = sk["parents"][i]
            if p < 0:
                continue
            post.append((int(sk["bones"][i]), rot_axis(axis, -(phi[i] - phi[p]))))
        return post
