"""Pet mixin: the fully 3D ragdoll (cfg["ragdoll_engine"] = "3d").

What lives here
  start_ragdoll_3d     build the 3D skeleton spec from the frame on screen and hand
                       her to the shared Rag3DWorld (ragphys3d.py)
  ragdoll_step_3d      once per frame: window placement, impacts, rest -> get-up
  rag3_post            physics rotations -> one FULL 3x3 post rotation per bone
  rag3_model_matrix    the model matrix while she is limp: whole-body 3D rotation
                       about the pelvis, plus a touch of perspective for her depth
  rag3_getup_*         blend every rotation home and her depth back to z = 0

Depth
  Students never move in depth on their feet: they stand, walk and jump at z = 0,
  exactly as before (depth_scale() is still 1.0). Only a limp body's pelvis and
  limbs can drift into the slab ragphys3d gives the world, and the get-up blend
  puts her back in the middle of it.

Frames
  physics  x right, y DOWN, z INTO the screen (right-handed), logical px
  GL world x right, y UP,   z toward you (right-handed): the renderer's frame
  They differ by F = diag(1, -1, -1), a 180 deg turn about x, so a rotation moves
  between them as F @ R @ F.

The post formula (see Model.pose_world: each post is a model-space rotation about
the bone's own position, inherited by everything below it):
  For body i whose nearest posted ancestor in the RIG is body j, with R_* the
  physics rotations since spawn and K = F @ A (A = rotation part of the model
  matrix at spawn, model -> GL world):
      post_i = K^T @ (R_root^T @ R_i @ R_j^T @ R_root) @ K
  The root itself gets no post: its rotation goes into the model matrix about the
  pelvis (rag3_model_matrix), exactly where render_frame already turns the 2D
  ragdoll. test_ragphys3d_map.py checks the whole chain on the real Mika rig.
"""
from __future__ import annotations

import math
import random
import traceback

import numpy as np
from PySide6 import QtGui

from .deps import ragphys3d
from .mathutil import clamp, scale4, translate
from .ragdoll_config import RAG3_GETUP_TIME, RAG3_HEAD_R, RAG3_PERSPECTIVE, RAG_REST_TIME

_F = np.diag([1.0, -1.0, -1.0])            # physics <-> GL world
_QI = (1.0, 0.0, 0.0, 0.0)


def _m3(t):
    return np.asarray(t, dtype=np.float64).reshape(3, 3)


class PetRag3D:
    # ------------------------------------------------------------- bones
    def rag3_tokens(self):
        """Particle name -> rig node index, resolved once per character (or None)."""
        tok = getattr(self, "_rag3_tok", None)
        if tok is not None:
            return tok or None
        b = self.rag_bone
        m = self.model
        tok = {"pelvis": b("pelvis") if b("pelvis") is not None else m.pelvis,
               "hip_l": b("l thigh"), "hip_r": b("r thigh"),
               "knee_l": b("l calf"), "knee_r": b("r calf"),
               "foot_l": b("l foot"), "foot_r": b("r foot"),
               "neck": b("neck"), "head": b("head") if b("head") is not None else m.head}
        for sd in "lr":
            arm = (b(f"{sd} upperarm"), b(f"{sd} forearm"), b(f"{sd} hand"))
            if all(a is not None for a in arm):
                tok[f"shoulder_{sd}"], tok[f"elbow_{sd}"], tok[f"hand_{sd}"] = arm
        if any(tok.get(k) is None for k in ragphys3d.REQUIRED):
            self._rag3_tok = {}
            return None

        def anc(a, n):                                     # is node a an ancestor of node n?
            cur = int(m.parent[n])
            while cur >= 0:
                if cur == a:
                    return True
                cur = int(m.parent[cur])
            return False
        # The chest body: the spine bone the neck and both arms hang from, which the
        # legs do NOT. BA rigs have no "chest"; Spine1 is that bone (Clavicles hang
        # off it), which gives her a back that can bend and twist.
        shoulders = [tok[k] for k in ("shoulder_l", "shoulder_r") if k in tok]
        for name in ("chest", "spine2", "spine1"):
            n = b(name)
            if n is None or n == tok["pelvis"] or not shoulders:
                continue
            if anc(n, tok["neck"]) and all(anc(n, s) for s in shoulders) and \
               not anc(n, tok["hip_l"]) and not anc(n, tok["hip_r"]):
                tok["chest"] = n
                break
        # The head's post goes on the NECK bone (it turns the whole head about the
        # base of the neck) unless the arms hang off the neck, in which case turning
        # it would swing her shoulders with her head - then it goes on the head bone.
        self._rag3_head_post = tok["neck"]
        if any(anc(tok["neck"], s) for s in shoulders):
            self._rag3_head_post = tok["head"]
        self._rag3_toes = (b("l toe0"), b("r toe0"))
        self._rag3_tok = tok
        return tok

    def rag3_skull(self):
        """(skull centre in the head bone's frame, skull radius) in model units, or None.

        Measured once off her own mesh: the vertices whose strongest skin weight is the
        head bone, in the limp base pose. A chibi head is a third of her height, so a
        guessed radius either buries her face in the floor or floats her above it.
        """
        if hasattr(self, "_rag3_skull"):
            return self._rag3_skull
        self._rag3_skull = None
        try:
            m = self.model
            head = self.rag3_tokens()["head"]
            c = self.clips.get("pickup") or self.clips.get("idle")
            W = m.pose_world(c.T[-1], c.Q[-1], c.S[-1]) if c is not None else m.W0
            pts = []
            for p in m.prims:
                if p.shade == 0.0 or p.skin < 0:
                    continue
                sk = m.skins[p.skin]
                joints = np.asarray(sk.joints)
                jv = p.joints.astype(np.int64)
                wv = p.weights
                dom = jv[np.arange(len(jv)), np.argmax(wv, axis=1)]
                mask = joints[np.clip(dom, 0, len(joints) - 1)] == head
                if not mask.any():
                    continue
                bm = np.matmul(W[sk.joints], sk.ibm)
                ph = np.concatenate([p.pos[mask].astype(np.float64), np.ones((int(mask.sum()), 1))], 1)
                acc = np.zeros((len(ph), 4))
                jm, wm = jv[mask], wv[mask]
                for k in range(4):
                    ji = np.clip(jm[:, k], 0, len(bm) - 1)
                    acc += wm[:, k:k + 1] * np.einsum("vij,vj->vi", bm[ji], ph)
                pts.append(acc[:, :3])
            if not pts:
                return None
            P = np.concatenate(pts)
            if len(P) < 40:
                return None
            ctr = P.mean(axis=0)
            rad = float(np.percentile(np.linalg.norm(P - ctr, axis=1), RAG3_HEAD_R))
            loc = np.linalg.inv(W[head]) @ np.append(ctr, 1.0)
            self._rag3_skull = (loc[:3].copy(), rad)
        except Exception as e:
            print(f"[ragdoll3d] {self.name}: could not measure the skull ({e}); using a default")
        return self._rag3_skull

    # ------------------------------------------------------------- spec
    def rag3_spec(self):
        """The ragphys3d spec from the frame just rendered (frozen limp pose), or None."""
        Mn = self.last_M
        if Mn is None or not np.all(np.isfinite(Mn)):
            return None
        tok = self.rag3_tokens()
        if tok is None:
            return None
        R = self.ch.renderer
        Wb = self.rig.world_base
        wpp = R.world_per_px * max(1e-6, self.dpr)          # GL world units per LOGICAL px
        pel_m = Wb[tok["pelvis"]][:3, 3]
        gz0 = (Mn @ np.append(pel_m, 1.0))[2]

        def win(p3):                                        # window px, through the real camera
            x, y = R.project(p3, Mn)
            return float(x) * self.W / max(1, R.w), float(y) * self.H / max(1, R.h)

        def P(p3):                                          # GLOBAL px + depth into the screen
            x, y = win(p3)
            g = Mn @ np.append(p3, 1.0)
            return (self.px + x, self.py + y, -float(g[2] - gz0) / wpp)
        pts = {nm: P(Wb[node][:3, 3]) for nm, node in tok.items() if nm != "head"}
        ch = self.rag_h()
        sc = float(abs(np.linalg.det(Mn[:3, :3]))) ** (1.0 / 3.0)
        skull = self.rag3_skull()
        head_r = None
        if skull is not None:
            loc, rad = skull
            pts["head"] = P((Wb[tok["head"]] @ np.append(loc, 1.0))[:3])
            head_r = clamp(rad * sc / wpp, 0.07 * ch, 0.22 * ch)
        else:                                               # head bone + a skull's height up the neck
            hb, nk = np.array(P(Wb[tok["head"]][:3, 3])), np.array(pts["neck"])
            up = hb - nk
            n = np.linalg.norm(up)
            up = up / n if n > 1e-6 else np.array([0.0, -1.0, 0.0])
            pts["head"] = tuple(hb + up * 0.12 * ch)
        fwd = None
        toes = getattr(self, "_rag3_toes", (None, None))
        vs = []
        for sd, t in zip("lr", toes):
            if t is not None:
                vs.append(np.array(P(Wb[t][:3, 3])) - np.array(pts[f"foot_{sd}"]))
        if vs:
            v = np.sum(vs, axis=0)
            v[1] = 0.0                                      # forward is horizontal
            if np.linalg.norm(v) > 1e-6:
                fwd = tuple(v / np.linalg.norm(v))
        feet = self.H * (1 - self.PADB)
        pel_win = win(pel_m)
        self.rag_pel_dx = pel_win[0] - self.W / 2
        return dict(scale=self.cfg["scale"], ch=ch,
                    depth=clamp(float(self.cfg.get("ragdoll_3d_depth", 0.35)), 0.05, 1.5) * ch,
                    tone=clamp(float(self.cfg.get("ragdoll_3d_tone", 0.5)), 0.0, 1.0),
                    drop=feet - pel_win[1], pts=pts, head_r=head_r, fwd=fwd,
                    sole=self.py + feet)

    # ------------------------------------------------------------- start
    def start_ragdoll_3d(self, kick=True, impulse=None):
        """Hand her to the 3D world. True if she went in, False to fall back."""
        W3 = getattr(self.A, "rag_world3d", None)
        if W3 is None or ragphys3d is None or getattr(self, "rag3_failed", False):
            return False
        try:
            # The skeleton is measured off exactly what is drawn, so anything that
            # bends the drawn pose away from the plain model matrix goes first:
            # the cartoon squash and the free pitch / tilt offsets.
            self.sq = self.sq_v = 0.0
            self.ori_p = self.ori_t = 0.0
            self.enter("fall"); self.rag_freeze_pose()
            self.rig.advance(0.0)
            self.render_frame(QtGui.QCursor.pos())
            spec = self.rag3_spec()
        except Exception as e:
            traceback.print_exc()
            print(f"[ragdoll3d] {self.name}: skeleton build failed ({e}); using another engine")
            self.rag3_failed = True
            return False
        if spec is None:
            print(f"[ragdoll3d] {self.name}: rig has no usable 3D ragdoll bones; using another engine")
            self.rag3_failed = True
            return False
        s = max(0.6, self.cfg["scale"])
        vx, vy = (0.0, 0.0) if self.grounded else (self.vx, self.vy)
        w = 0.0
        if impulse is not None:
            mode = "shot"
            vx += impulse[0]; vy += impulse[1]; w = impulse[2]
        elif kick:
            mode = "slam" if self.rag_edge_slam else "kick"
            vx += random.choice([-1, 1]) * random.uniform(60.0, 200.0) * s
            w = random.choice([-1, 1]) * random.uniform(1.0, 3.0)
        else:
            mode = "crumple"                                # Ctrl+1 / menu: she faints where she stands
        try:
            sk = W3.add_skeleton(self.rag_owner, spec, (vx, vy, w), mode)
        except Exception as e:
            traceback.print_exc()
            print(f"[ragdoll3d] {self.name}: could not build the 3D skeleton ({e}); using another engine")
            self.rag3_failed = True
            return False
        M0 = self.last_M.copy()
        K, pmap = self.rag3_build_map(sk, M0)
        self.rag_skel = sk
        self.rag3 = dict(phase="fall", M0=M0, K=K, map=pmap, rots=None, Rr=np.eye(3), z=0.0,
                         fpx=float(self.ch.renderer.dist) / (self.ch.renderer.world_per_px * max(1e-6, self.dpr)),
                         up0=sk.frame_pelvis[1])
        self.ragdoll = True; self.rig.dangle_on = False
        self.grounded = False; self.support = None; self.dragging = False
        self.air_kind = "thrown"; self.bounces = 0
        self.roll = self.roll_v = 0.0; self.pitch_hold = self.pitch_hold_v = 0.0
        self.rag_state, self.rag_t, self.rag_rest = "fall", 0.0, 0.0
        self.rag_want_up = False; self.rag_hit_t = 0.0
        self.rg_ax = self.rg_ay = self.rg_alpha = 0.0
        self.rg_contact = False; self.rg_top = None
        self.rg_grav = 1.0; self.rag_strength = 1.0
        for L in self.rag_bones: L["d"] = L["dd"] = 0.0
        if getattr(self.A, "rag_trace", 0):
            W3.trace(int(self.A.rag_trace))
        self.say(self.line("launch"), 1.6)
        return True

    def rag3_build_map(self, sk, M0):
        """(K, [(body, bone node, rig parent body)]) for the post formula.

        K = F @ A turns model space into the physics frame, A being the rotation part
        of the spawn model matrix (polar decomposition, so a uniform scale or zoom in
        it does no harm). The parent is the nearest ancestor IN THE RIG that carries a
        body, because that is whose post this bone inherits in Model.pose_world.
        """
        U, _S, Vt = np.linalg.svd(M0[:3, :3])
        A = U @ Vt
        if np.linalg.det(A) < 0:
            U[:, -1] *= -1.0; A = U @ Vt
        tok = self.rag3_tokens()
        post_bone = {"head": self._rag3_head_post}
        if sk.has_chest:
            post_bone["chest"] = tok["chest"]
        for sd in "lr":
            post_bone[f"thigh_{sd}"], post_bone[f"calf_{sd}"] = tok[f"hip_{sd}"], tok[f"knee_{sd}"]
            if f"shoulder_{sd}" in sk.idx:
                post_bone[f"upperarm_{sd}"] = tok[f"shoulder_{sd}"]
                post_bone[f"forearm_{sd}"] = tok[f"elbow_{sd}"]
        body_of = {node: body for body, node in post_bone.items()}
        body_of[tok["pelvis"]] = "pelvis"
        par = self.model.parent
        pmap = []
        for body, _phys_parent in sk.bodies:
            if body == "pelvis" or body not in post_bone:
                continue
            node = post_bone[body]
            cur = int(par[node])
            while cur >= 0 and cur not in body_of:
                cur = int(par[cur])
            pmap.append((body, int(node), body_of.get(cur, "pelvis")))
        return _F @ A, pmap

    # ------------------------------------------------------------- per frame
    def ragdoll_step_3d(self, dt):
        """Read the 3D world (stepped once for the whole app in App.tick)."""
        st = self.rag3
        sk = self.rag_skel
        if st is None:
            return
        if st["phase"] == "getup" or sk is None:
            self.rag3_getup_step(dt)
            return
        try:
            if sk.detached:
                self.rag3_drop("her skeleton left the world"); return
            # ragdoll_step() resolved the home screen a moment ago (and App.tick keeps
            # the physics walls on it), so the cached one is current: resolve_screen()
            # walks every QScreen and is not free to call again per pet per frame.
            gh = getattr(self.A, "home", None) or self.A.resolve_screen()
            rect = (gh.left(), gh.top(), gh.right() + 1, gh.bottom() + 1)
            if sk.explode_guard():
                self.rag3_drop("non-finite or blown-up body"); return
            if sk.outside(rect, self.rag_h()):
                sk.snap_inside(rect, self.rag_h())
            s = max(0.6, self.cfg["scale"])
            v0x, v0y, w0 = self.rg_vx, self.rg_vy, self.rg_w
            pose = sk.pose()
            rots = sk.rotations()
            st["rots"] = rots
            st["Rr"] = _m3(rots["pelvis"])
            st["z"] = pose["z"]
            up = st["Rr"] @ np.asarray(st["up0"])            # legacy readers: in-plane body angle
            self.rg_a = math.atan2(up[0], -up[1])
            self.rg_x, self.rg_y = pose["x"], pose["y"]
            self.rg_vx, self.rg_vy, self.rg_w = pose["vx"], pose["vy"], 0.0
            self.rag_contact = sk.touching()
            self.set_feet(pose["x"] - self.rag_pel_dx, pose["y"] + sk.drop)
            self.vx, self.vy = pose["vx"], pose["vy"]       # hair / skirt / tie springs
            self.sq = self.sq_v = 0.0                        # realistic: no cartoon squash
            self.rag3_impacts()
            if self.rag_contact and sk.speed() < ragphys3d.RAG3_REST_SPEED * s:
                self.rag_rest += dt
            else:
                self.rag_rest = 0.0
            if self.rag_want_up and self.rag_rest > 0.2:
                self.rag_getup()
            elif self.cfg.get("ragdoll_auto_getup", True) and self.rag_rest > RAG_REST_TIME:
                self.rag_getup()
            self.rag_accel(dt, v0x, v0y, w0)
        except Exception:
            traceback.print_exc()
            self.rag3_drop("ragdoll_step_3d raised")

    def rag3_impacts(self):
        """Physics hits -> dust puff and sound. No squash: this engine is the realistic one."""
        W3 = getattr(self.A, "rag_world3d", None)
        if W3 is None:
            return
        for im in W3.pop_impacts(self.rag_owner):
            if im.strength < 0.08:
                continue
            if im.strength > 2.0:
                play = getattr(self.A, "play_rag_sound", None)
                if play:
                    play()
            if self.rag_hit_t > 0.25 and im.strength > 0.35:
                self.rag_hit_t = 0.0
                self.emit_impact(im.point[0] - self.px, im.point[1] - self.py, min(1.8, im.strength))

    def rag3_drop(self, why):
        print(f"[ragdoll3d] {self.name}: {why}; standing her back up")
        self.rag_clear(); self.reset_position()

    # ------------------------------------------------------------- pose -> rig
    def rag3_post(self):
        """The rig's post list: one full 3x3 model-space rotation per body."""
        st = self.rag3
        if st is None:
            return []
        if st["phase"] == "getup":
            k = st.get("sm", 0.0)
            return [(b, _m3(ragphys3d.quat_to_mat(ragphys3d.slerp_quat(q, _QI, k))))
                    for b, q in st["posts0"]]
        sk = self.rag_skel
        if sk is None:
            return []
        rots = st["rots"] or sk.rotations()
        return self.rag3_posts_from(rots, st)

    @staticmethod
    def rag3_posts_from(rots, st):
        """post_i = K^T (R_root^T R_i R_j^T R_root) K, regrouped as  B R_i R_j^T B^T
        with B = K^T R_root^T computed once: 2 matmuls per bone instead of 4, and
        each physics rotation turned into an array once instead of once per use."""
        K = st["K"]
        Rr = _m3(rots["pelvis"])
        B = K.T @ Rr.T
        Bt = B.T
        arr = {}

        def get(name):
            a = arr.get(name)
            if a is None:
                a = arr[name] = _m3(rots[name])
            return a
        out = []
        for body, node, rig_par in st["map"]:
            out.append((node, B @ (get(body) @ get(rig_par).T) @ Bt))
        return out

    def rag3_model_matrix(self, world):
        """Model matrix while limp: her spawn matrix turned in 3D about the pelvis.

        The pelvis stays put on screen (the window follows the physics pelvis), the
        rotation is the pelvis cluster's full 3D rotation, and her depth in the slab
        becomes the camera's own perspective scale, f / (f + z).
        """
        st = self.rag3
        M0 = st["M0"]
        p = (M0 @ np.append(world[self.model.pelvis][:3, 3], 1.0))[:3]
        R4 = np.eye(4)
        R4[:3, :3] = _F @ st["Rr"] @ _F
        zs = self.rag3_depth_scale(st)
        return translate(p) @ R4 @ scale4(zs, zs, zs) @ translate(-p) @ M0

    @staticmethod
    def rag3_depth_scale(st):
        """Size change for her pelvis depth: f / (f + z), times RAG3_PERSPECTIVE.

        Off by default. The physics treats the floor and the screen edges as fixed
        lines at every depth (an orthographic world), so drawing her camera-true
        bigger when she lies nearer would put her feet and head a few px through the
        floor she is lying on. The depth still shows in every limb's 3D rotation.
        """
        k = RAG3_PERSPECTIVE
        if k <= 0.0:
            return 1.0
        f = max(1.0, st["fpx"])
        return 1.0 + (f / max(1.0, f + float(st["z"])) - 1.0) * k

    # ------------------------------------------------------------- get up
    def rag3_getup_begin(self):
        """Freeze the lying pose, leave the world, and start blending home."""
        st = self.rag3
        sk = self.rag_skel
        rots = sk.rotations()
        pose = sk.pose()
        st["posts0"] = [(node, ragphys3d.mat_to_quat(tuple(P.ravel())))
                        for node, P in self.rag3_posts_from(rots, st)]
        st["q_root0"] = ragphys3d.mat_to_quat(rots["pelvis"])
        st["x0"], st["y0"], st["z0"] = pose["x"], pose["y"], pose["z"]
        st["drop"] = sk.drop
        st["low"] = sk.lowest_point()
        st["phase"] = "getup"
        st["sm"] = 0.0
        W3 = getattr(self.A, "rag_world3d", None)
        if W3 is not None:
            W3.remove_skeleton(sk)
        self.rag_skel = None
        self.rag_state, self.rag_t = "getup", 0.0

    def rag3_getup_step(self, dt):
        st = self.rag3
        if "q_root0" not in st:                             # never froze: just stand up
            self.rag_clear(); self.reset_position(); return
        self.rag_state = "getup"
        k = min(1.0, self.rag_t / RAG3_GETUP_TIME)
        sm = k * k * (3 - 2 * k)
        st["sm"] = sm
        ground, surf = self.rag_ground(st["x0"], st["low"])
        st["Rr"] = _m3(ragphys3d.quat_to_mat(ragphys3d.slerp_quat(st["q_root0"], _QI, sm)))
        st["z"] = st["z0"] * (1.0 - sm)                     # back to the middle of the depth
        y = st["y0"] + (ground - st["drop"] - st["y0"]) * sm
        self.rag_strength = 1.0 - sm
        self.rg_x, self.rg_y = st["x0"], y
        self.rg_vx = self.rg_vy = self.rg_w = 0.0
        self.rg_top = ground
        self.rag_contact = True
        self.set_feet(st["x0"] - self.rag_pel_dx, y + st["drop"])
        self.vx = self.vy = 0.0
        if k >= 1.0:
            self.rag_end(surf)

    def rag3_finish_now(self):
        """Picked up mid get-up: skip the rest of the blend and stand her up at once."""
        if self.rag3 is None or self.rag_skel is not None:
            return
        self.rag_clear()
        self.grounded = False; self.support = None

    # ------------------------------------------------------------- debug
    def rag3_debug_draw(self, p):
        """--rag-debug for the 3D engine: joints and bones, nearer = brighter, plus windows."""
        from PySide6.QtCore import QPointF, QRectF
        sk = self.rag_skel
        if sk is not None:
            D = max(1.0, sk.depth)
            pts = {nm: (x - self.px, y - self.py, z, r) for nm, x, y, z, r in sk.points()}
            p.setPen(QtGui.QPen(QtGui.QColor(255, 210, 0, 200), 1))
            for _nm, (j, k, _u, _par) in sk.bone_of.items():
                a, b = pts[sk.names[j]], pts[sk.names[k]]
                p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
            for nm, (x, y, z, r) in pts.items():
                near = clamp(0.5 - z / (2.0 * D), 0.0, 1.0)
                p.setPen(QtGui.QPen(QtGui.QColor(int(60 + 195 * near), 255, int(140 * near), 220), 1))
                p.drawEllipse(QPointF(x, y), r, r)
        W3 = getattr(self.A, "rag_world3d", None)
        if W3 is not None:
            p.setPen(QtGui.QPen(QtGui.QColor(120, 180, 255, 110), 1))
            for w in W3._wins.values():
                l, t, r_, b = w["rect"]
                p.drawRect(QRectF(l - self.px, t - self.py, r_ - l, b - t))
