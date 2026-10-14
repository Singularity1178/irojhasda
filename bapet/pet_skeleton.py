"""Pet mixin: ragdoll bone lookup and building the pymunk skeleton spec."""
from __future__ import annotations

import numpy as np

from .deps import ragphys
from .mathutil import clamp
from .ragdoll_config import RAG_COM_FRAC, RAG_COM_PAD, RAG_LIMBS
from .renderer import Renderer


class PetRagSkeleton:
    # ---------------- ragdoll: bone lookup + centre of mass ----------------
    def rag_resolve(self):
        """Find the limb bones and measure her centre of mass, once, at startup.

        A model whose rig uses other names simply skips those limbs and they
        keep playing their baked animation - the body still tumbles.
        """
        names = [n.lower() for n in self.model.names]
        self.rag_names = names            # cached, rag_bone() hits it every frame
        def find(s):
            for i, n in enumerate(names):
                if n == s or n.endswith(" " + s): return i      # exact token: skips "...Twist" bones
            return None
        self.rag_bones = []
        for b, c, lim, k, damp in RAG_LIMBS:
            bi, ci = find(b), find(c)
            if bi is not None and ci is not None:
                self.rag_bones.append(dict(b=bi, c=ci, lim=lim, k=k, damp=damp, d=0.0, dd=0.0))
        # Where the rod's centre of mass has to sit so that the point she actually
        # rotates about (the pelvis, used by render_frame) sits ON the surface once
        # she is lying flat. Her pelvis rides at a different fraction of her height
        # in every rig, so measure it in the limp base pose instead of guessing:
        #   pivot_y = COM + drop - pelvis_frac*ch, and the rod resting on the floor
        #   means COM + thickness == ground, so COM = pelvis_frac + thickness/ch.
        self.rag_com = RAG_COM_FRAC
        try:
            c = self.clips.get("pickup") or self.clips.get("idle")
            if c is not None:
                W = self.model.pose_world(c.T[-1], c.Q[-1], c.S[-1])
                pts = self.model.posed_positions(W, skip_fx=True)
                if len(pts):
                    y = pts[:, 1]
                    lo, hi = float(np.percentile(y, 0.2)), float(np.percentile(y, 99.8))
                    frac = (float(W[self.model.pelvis][1, 3]) - lo) / max(1e-6, hi - lo)
                    self.rag_com = clamp(frac, 0.15, 0.75) + RAG_COM_PAD / Renderer.FRAC
        except Exception as e:
            print(f"[warn] {self.name}: could not measure the ragdoll centre of mass: {e}")
        print(f"[ragdoll] {self.name}: {len(self.rag_bones)}/{len(RAG_LIMBS)} limbs found, "
              f"COM {self.rag_com * 100:.1f}% up")

    # ---------------- ragdoll: the articulated skeleton (pymunk) ----------------
    # The body table lives in ragphys.py's RAGP_* block; this is just the bones.
    # (origin bone, end bone, radius x her height, mass weight, joint limit)
    RAGP_LINKS = [
        ("pelvis", "chest", 0.045, 0.20, ragphys.RAGP_TORSO_LIM),
        ("chest", "neck", 0.050, 0.30, ragphys.RAGP_TORSO_LIM),
        ("neck", "head", 0.060, 0.07, ragphys.RAGP_HEAD_LIM),
        ("l upperarm", "l forearm", 0.018, 0.03, 2.4),
        ("l forearm", "l hand", 0.016, 0.025, 1.6),
        ("r upperarm", "r forearm", 0.018, 0.03, 2.4),
        ("r forearm", "r hand", 0.016, 0.025, 1.6),
        ("l thigh", "l calf", 0.028, 0.09, 1.5),
        ("l calf", "l foot", 0.022, 0.06, 1.2),
        ("r thigh", "r calf", 0.028, 0.09, 1.5),
        ("r calf", "r foot", 0.022, 0.06, 1.2),
    ]

    def rag_bone(self, token):
        """Rig node index for a bone name, or None. Same matching as rag_resolve:
        an exact token, so "...Twist" bones never match."""
        names = self.rag_names
        for i, n in enumerate(names):
            if n == token or n.endswith(" " + token):
                return i
        return None

    def rag_project(self, node):
        """Bone `node` in WINDOW px, y down - the same maths as rag_limb_post."""
        # Must go through the renderer's real camera (eye offset + perspective),
        # NOT just last_M / world_per_px: that gives world units from the world
        # ORIGIN, not from the window's top-left, so everything built from it
        # (the physics skeleton, the muzzle) landed about half a window up-left
        # of where the model is actually drawn.
        R = self.ch.renderer
        x, y = R.project(self.rig.world_base[node][:3, 3], self.last_M)
        return (float(x) * self.W / max(1, R.w), float(y) * self.H / max(1, R.h))

    def rag_spec(self):
        """Build the pymunk skeleton spec from the CURRENT frame, or None.

        Built here, at ragdoll start, rather than once at startup: that way
        face_yaw, the cfg yaw_offset and her scale are all already baked into
        the pose being measured, so no extra transform has to be reconstructed
        later. Yaw in particular changes which way a limb points on screen.

        Returns None when her rig cannot support it - no pelvis, no thighs, no
        head, or fewer than a handful of bodies - and the caller falls back to
        the legacy rod for this pet.
        """
        if ragphys is None or self.last_M is None or not np.all(np.isfinite(self.last_M)):
            return None
        pel = self.rag_bone("pelvis")
        if pel is None or not self.rag_bone("l thigh") or not self.rag_bone("neck"):
            return None
        ch = self.rag_h()                               # her body height, window px
        # A rig with no chest bone (most of them - the torso is Spine + Spine1)
        # gets ONE torso body spanning pelvis -> neck instead of two, per the
        # body table. Without this every one of her links that ran through the
        # chest would be dropped and she would have no root at all.
        table = list(self.RAGP_LINKS)
        if self.rag_bone("chest") is None:
            table = [(a, b, r, w, l) for a, b, r, w, l in table if a != "chest"]
            table.insert(0, ("pelvis", "neck", 0.050, 0.30, ragphys.RAGP_TORSO_LIM))
        links, idx = [], {}
        for a, b, rad, w, lim in table:
            ia, ib = self.rag_bone(a), self.rag_bone(b)
            if ia is None or ib is None:
                continue
            idx[a] = len(links)
            links.append((a, b, ia, ib, rad, w, lim))
        if len(links) < ragphys.RAGP_MIN_BODIES or "pelvis" not in idx:
            return None
        # every parent has to exist and come earlier in the list
        parent = {}
        for a, b, _ia, _ib, _r, _w, _l in links:
            p = self.rag_parent_of(a)
            parent[a] = None if p is None else idx.get(p, -1)
        bodies = []
        for a, b, ia, ib, rad, w, lim in links:
            k, damp = self.rag_spring(a)
            bodies.append(dict(
                name=a, bone=ia, parent=parent[a],
                p=self.rag_project(ia), c=self.rag_project(ib),
                r=rad * ch, w=w, lim=lim, k=k, damp=damp,
                head=(a == "neck")))                    # the skull rides on the neck body
        # Where her feet are, below the pelvis, in window px: this is what the
        # physics pelvis position is converted back into (window x, window y).
        # NOTE: this must be the window's own feet line (the line set_feet() and
        # feet_pos() use), NOT the foot bone origin. The bone origin sits above
        # the sole, so using it made set_feet(x, pelvis_y + drop) place the window
        # that gap too high the instant the ragdoll started - the model jumped up
        # and everything derived from the window (bullet origin, aim points)
        # followed it.
        feet = self.H * (1 - self.PADB)
        # set_feet() centres the window on the pelvis x; remember how far the real
        # pelvis sits from the window centre so the window is not nudged sideways.
        self.rag_pel_dx = self.rag_project(pel)[0] - self.W / 2
        return dict(scale=self.cfg["scale"], px=self.px, py=self.py,
                    root=idx["pelvis"], drop=feet - self.rag_project(pel)[1], bodies=bodies)

    def rag_parent_of(self, bone):
        """The physics body `bone` hangs off: its nearest ancestor that has one.

        Walks the real rig hierarchy rather than assuming a shape, because the
        chain differs per model. Mika for instance has no chest bone and the arms
        reach the torso through Clavicle -> Spine1 -> Spine, so an upperarm's
        nearest ancestor with a body is the pelvis (the single torso body), while
        a forearm's is the upperarm - which is exactly what chains the arm into
        an elbow instead of pinning both segments to her spine.
        """
        m = self.model
        n = self.rag_bone(bone)
        have = {t for t in ("pelvis", "chest") if self.rag_bone(t) is not None}
        # bodies are named by their ORIGIN bone (the first column), because that
        # is the joint they hang from and the bone their post rotation turns
        have |= {a for a, _b, _r, _w, _l in self.RAGP_LINKS}
        cur = int(m.parent[n]) if n is not None else -1
        while cur >= 0:
            nm = m.names[cur].lower()
            for tok in have:
                if nm == tok or nm.endswith(" " + tok):
                    return tok
            cur = int(m.parent[cur])
        return None

    def rag_spring(self, bone):
        """(stiffness, damping) for a link, reusing the RAG_LIMBS numbers."""
        for b, _c, lim, k, damp in RAG_LIMBS:
            if b == bone:
                return k, damp
        if bone in ("pelvis", "chest"):
            return ragphys.RAGP_TORSO_K, ragphys.RAGP_TORSO_DAMP
        if bone == "neck":
            return ragphys.RAGP_HEAD_K, ragphys.RAGP_HEAD_DAMP
        return ragphys.RAGP_TORSO_K, ragphys.RAGP_TORSO_DAMP
