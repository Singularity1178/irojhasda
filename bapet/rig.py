"""Rig: animation player with cross-fade, head look-at and hold-physics springs."""
from __future__ import annotations

import math
import time

import numpy as np

from .config import HOLD_GAIN, WIND_KINDS
from .mathutil import blend_world, clamp, rot_x, rot_y, rot_z, sample_clip, smootherstep


# =============================================================================
#  Animation player with cross-fade
# =============================================================================
class _Layer:
    """A clip that is on its way out: it keeps playing while the new one fades in."""
    __slots__ = ("clip", "t", "loop", "speed", "prev", "fade", "fade_dur")
    def __init__(self, clip, t, loop, speed, prev, fade, fade_dur):
        self.clip, self.t, self.loop, self.speed = clip, t, loop, speed
        self.prev, self.fade, self.fade_dur = prev, fade, fade_dur


class Rig:
    def __init__(self, model):
        self.m = model; self.clip = None; self.t = 0.0; self.loop = True; self.speed = 1.0
        self.done = False; self.fade = 1.0; self.fade_dur = 0.15; self.prev = None; self.cur_pose = None   # prev = outgoing _Layer chain
        self.world = model.W0
        self.world_base = model.W0        # same pose with the ragdoll rotations removed
        self.cur_wt = model.node_w0
        # hold-physics spring state: per jiggle chain [side, front, side-vel, front-vel]
        # (radians of lag). One extra slot drives the dangling limbs together.
        self.hold_n = len(getattr(model, "jiggle_chains", []))
        self.hold = [[0.0, 0.0, 0.0, 0.0] for _ in range(self.hold_n + 1)]
        self.hold_yaw = 0.0
        # ragdoll: limb-pendulum post rotations, written by Pet every frame
        self.rag_post = []
        # Pet turns this off while she is limp - the "limbs dangle together"
        # spring below would otherwise fight the per-limb pendulums.
        self.dangle_on = True
        # Limp = the articulated ragdoll owns the pose. Set by Pet on go-limp,
        # cleared when she is standing again. While it is set:
        #   - advance() is a no-op, so the clip cannot play (this is what used
        #     to happen: nudging a ragdolled pet started an animation),
        #   - play() is refused, so nothing can restart one either,
        #   - evaluate() drops the head-look rotations.
        self.limp = False

    def set_limp(self, on):
        """Freeze the rig into (or out of) the limp pose.

        Freezing needs the clip to be HELD, not merely paused: `advance()` with
        speed 0 keeps `t` where it is, but any later `play()` restarts it. So
        while limp the rig refuses clip changes outright and `rag_freeze_pose`
        parks the current clip on its last frame.
        """
        if on and not self.limp:
            c = self.clip
            if c is not None:
                self.speed = 0.0; self.t = c.duration; self.done = True
                self.fade = 1.0; self.prev = None
        elif not on:
            self.speed = 1.0; self.done = False
        self.limp = on

    @staticmethod
    def _incompatible(a, b):
        """Two clips that disagree about bone scale must not be blended (see Model: c.ssig)."""
        return (a is not None and b is not None and a.ssig is not None and b.ssig is not None
                and float(np.abs(a.ssig - b.ssig).max()) > 0.5)

    def play(self, clip, loop, speed=1.0, fade=0.15, restart=True):
        if clip is None or self.limp: return    # nothing may restart a limp body
        if (not restart) and clip is self.clip:
            self.loop, self.speed = loop, speed; return
        # The clip we are leaving keeps PLAYING underneath the fade (it used to be
        # frozen on the frame it was on, so every transition slid out of a statue).
        # It also carries its own unfinished fade, so interrupting a transition no
        # longer snaps back to the unblended pose first.
        old = None
        if self.clip is not None and fade > 0:
            old = _Layer(self.clip, self.t, self.loop, self.speed,
                         self.prev if self.fade < 1.0 else None, self.fade, self.fade_dur)
            if self._incompatible(clip, old.clip):
                old = None                       # hard cut beats sliding through garbage
            else:
                node, depth = old, 1
                while node.prev is not None:     # drop what cannot blend, and cap the chain
                    if depth >= 3 or self._incompatible(clip, node.prev.clip): node.prev = None; break
                    node, depth = node.prev, depth + 1
        self.prev = old
        self.fade = 0.0 if old is not None else 1.0
        self.fade_dur = max(fade, 1e-3)
        self.clip, self.t, self.loop, self.speed, self.done = clip, 0.0, loop, speed, False

    @staticmethod
    def _advance_layer(lay, dt):
        c = lay.clip
        lay.t += dt * lay.speed
        if lay.loop:
            if c.duration > 0: lay.t %= c.duration
        else:
            lay.t = min(lay.t, c.duration)       # a finished clip holds its last pose
        if lay.prev is not None: Rig._advance_layer(lay.prev, dt)
        if lay.fade < 1.0:
            lay.fade = min(1.0, lay.fade + dt / lay.fade_dur)
            if lay.fade >= 1.0: lay.prev = None

    def advance(self, dt):
        c = self.clip
        if c is None or self.limp: return      # a limp body does not animate
        self.t += dt * self.speed
        if self.loop:
            if c.duration > 0: self.t %= c.duration
        elif self.t >= c.duration:
            self.t = c.duration; self.done = True
        if self.prev is not None: self._advance_layer(self.prev, dt)
        if self.fade < 1.0:
            self.fade = min(1.0, self.fade + dt / self.fade_dur)
            if self.fade >= 1.0: self.prev = None

    def sample(self):
        """Current pose + its root-motion offset.

        Nothing is blended here. Cross-fading happens in *world* space in evaluate():
        lerping local TRS only works when the hierarchy is a plain chain, and Iroha's
        is not - her pelvis is a descendant of her head bone and 'character_root'
        carries a 364-unit local translation that only cancels once composed. Blending
        those locals sends the pelvis several body heights off screen.
        """
        T, Q, S, off, wt = sample_clip(self.clip, self.t, self.loop)
        self.cur_pose = (T, Q, S, off)
        if wt is not None: self.cur_wt = wt
        return T, Q, S, off

    def _layer_world(self, lay, S_ref, post):
        """World pose (+ root offset) of an outgoing layer, with its own fade folded in."""
        m = self.m
        T, Q, S, off, _ = sample_clip(lay.clip, lay.t, lay.loop)
        # A2: a leaf bone scaled to 0 is a weapon/prop show-hide key, not an
        # animation. Hand the outgoing pose the incoming scale so it never ramps
        # through a visible grow/shrink (and so zero-scale normals can't go NaN).
        # Leaves only: structural bones are never show/hide keys.
        hide = np.minimum(S, S_ref).min(axis=1) < 0.05
        hide &= m.is_leaf
        if hide.any():
            S = S.copy(); S[hide] = S_ref[hide]
        W = m.pose_world(T, Q, S, post)
        if lay.prev is not None and lay.fade < 1.0:
            Wp, offp = self._layer_world(lay.prev, S, post)
            k = smootherstep(lay.fade)
            W = blend_world(Wp, W, k)
            off = offp * (1 - k) + off * k
        return W, off

    def update_hold(self, dt, vx, vy, energy, yaw=0.0, wx=0.0, wy=0.0, we=0.0):
        """Drive the secondary-motion springs from window velocity (px/s).

        vx/vy = smoothed window velocity, energy = 0..1 how "held" she is
        (1 while dragging, decays after release). yaw = model facing so screen
        motion maps into model space. Always integrated (so it settles softly)
        but targets collapse to ~0 when energy is 0, leaving baked anim alone.
        wx/wy/we = gust wind (px/s + 0..1 energy). Wind bends only WIND_KINDS
        (hair + clothes) - body and limbs never see it.
        """
        m = self.m
        if not getattr(m, "jiggle_chains", None) and not getattr(m, "dangle_bones", None):
            return
        dt = clamp(dt, 1e-4, 0.05)
        self.hold_yaw = yaw
        # screen -> model space (model faces +Z at yaw 0; screen X is camera X)
        c, s = math.cos(yaw), math.sin(yaw)
        lat = (vx * c) * energy
        dep = (vx * s) * energy
        fwd = (-vy * c) * energy
        wlat = wx * c                    # wind already carries its own envelope + falloff
        wdep = wx * s
        wfwd = -wy * c
        # gentle idle breeze so hair never looks glued when parked
        t = time.time()
        breeze = 0.02 * energy + 0.004
        targets = []
        for ci, ch in enumerate(list(m.jiggle_chains) + [dict(nodes=[], kind="limb")]):
            kind = ch.get("kind", "cloth")
            g = HOLD_GAIN.get(kind, 0.7)
            wob = 0.8 + 0.4 * ((ci * 37) % 10) / 10.0     # desync chains
            wind = 1.0 if kind in WIND_KINDS else 0.0
            kx, kf = 0.00045 * g * wob, 0.00038 * g * wob
            # drag lags BEHIND the motion (negative); wind pushes WITH the air (positive)
            tx = clamp(-lat * kx + wlat * wind * kx, -0.85, 0.85)
            ty = clamp(-fwd * kf + dep * kf + (wfwd - wdep) * wind * kf
                       + math.sin(t * 1.7 + ci * 1.3) * breeze * g, -0.70, 0.70)
            targets.append((tx, ty, kind))
        for (tx, ty, kind), st in zip(targets, self.hold):
            stiff = 70.0 if kind == "limb" else 95.0
            damp = 7.5 if kind == "limb" else 6.0
            for k in (0, 1):
                tgt = (tx, ty)[k]
                # critically-damped-ish spring; dep adds a touch of twist variety
                acc = stiff * (tgt - st[k]) - damp * st[k + 2]
                st[k + 2] += acc * dt
                st[k] += st[k + 2] * dt
                st[k] = clamp(st[k], -1.0, 1.0)

    def _hold(self):
        m = self.m; post = []
        if not getattr(m, "jiggle_chains", None) and not getattr(m, "dangle_bones", None):
            return post
        for ch, st in zip(m.jiggle_chains, self.hold):
            sx, sy = st[0], st[1]
            if abs(sx) < 1e-2 and abs(sy) < 1e-2: continue
            g = HOLD_GAIN.get(ch.get("kind", "cloth"), 0.7)
            for di, node in enumerate(ch["nodes"]):
                f = (0.45 + 0.55 * (di + 1) / max(1, len(ch["nodes"]))) * g
                post.append((int(node), rot_z(sx * f) @ rot_x(sy * f)))
        # limbs dangle together on the last spring slot, weaker + mirrored L/R
        # (off while she is ragdolled - Pet's own limb pendulums own the limbs)
        if getattr(m, "dangle_bones", None) and len(self.hold) and self.dangle_on:
            sx, sy = self.hold[-1][0], self.hold[-1][1]
            if abs(sx) > 1e-2 or abs(sy) > 1e-2:
                for node in m.dangle_bones:
                    nm = m.names[int(node)].lower()
                    mir = -1.0 if any(k in nm for k in ("r upperarm", "r forearm", "r thigh", "r calf", "r hand", "r foot")) else 1.0
                    amp = 0.55 if "arm" in nm or "hand" in nm else 0.35
                    post.append((int(node), rot_z(sx * amp * mir) @ rot_x(sy * amp)))
        return post

    def _look(self, yaw, pitch, face_extra=0.0):
        m = self.m; post = []
        if m.look_bones and (abs(yaw) > 1e-4 or abs(pitch) > 1e-4):
            # pitch is about the SCREEN x axis: undo the whole facing (model + hand
            # rotation + body turn), so a character turned 180 still looks up when
            # the cursor is above her instead of down
            Rf = rot_y(m.face_yaw + face_extra)                        # B6: pitch axis follows the model's facing
            for node, w in m.look_bones:
                post.append((node, rot_y(yaw * w) @ Rf.T @ rot_x(-pitch * w) @ Rf))
        return post

    def evaluate(self, yaw, pitch, face_extra=0.0):
        m = self.m; T, Q, S, off = self.sample()
        m.node_w = self.cur_wt
        # Limp: the physics owns every bone, so the rig must contribute NOTHING
        # on top of it. Head-look is the one that showed up on screen - a
        # ragdolled pet whose eyes tracked the cursor, and whose clip was still
        # running underneath the physics, looked like it was playing an
        # animation while lying on the floor. The _hold() springs stay on: they
        # are hair and cloth, which should still hang and swing while she is
        # unconscious, and they are not bones the ragdoll drives.
        post = ([] if self.limp else self._look(yaw, pitch, face_extra)) + self._hold()
        rag = self.rag_post
        W = m.pose_world(T, Q, S, post + rag)
        # The same pose with the ragdoll rotations left out. Pet measures every
        # limb's on-screen direction and length against it: measured against the
        # posed world instead, a swinging forearm would tilt the upper arm's own
        # pendulum, which tilts the forearm back, and the pair runs away into their
        # joint limits within a second.
        Wb = m.pose_world(T, Q, S, post) if rag else W.copy()
        if self.prev is not None and self.fade < 1.0:
            k = smootherstep(self.fade)
            Pb, pOff = self._layer_world(self.prev, S, post)
            W = blend_world(Pb, W, k)
            Wb = blend_world(Pb, Wb, k)
            off = pOff * (1 - k) + off * k               # A1: offset cross-fades with the pose
        elif self.fade >= 1.0:
            self.prev = None
        W[:, :3, 3] += off
        Wb[:, :3, 3] += off
        self.world = W
        self.world_base = Wb
        return W
