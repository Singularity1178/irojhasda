"""Top-down camera: each student's OWN renderer (the desktop toon shader), pointed straight down.

The arena GL frame G is (screen x, height above the floor, screen y), right-handed, in screen px.
The camera is an oblique ("cabinet") projection: a point on the floor lands exactly on its screen
pixel, and height goes up the screen by OBLIQUE px per px - so the desktop really is the floor,
props and students line up with it, and you still see the students' faces instead of the tops
of their heads.

The 'view' matrix is that shear plus a depth axis (camera space looks down -z, which the outline
pass relies on), the projection is orthographic. Everything Renderer.draw writes is saved and
restored around each shot, exactly like the Student Select previews do, so a desktop pet that is
somehow still on screen is never disturbed. One shared off-screen buffer for all students.
"""
from __future__ import annotations

import math
import traceback

import numpy as np
from PySide6 import QtGui

from bapet.mathutil import m4, rot_y
from .obstacles import OBLIQUE

KEYS = ("fbo", "fbo_rs", "w", "h", "fit", "fit_scale", "V_world", "dist", "eye", "view", "proj", "PV",
        "world_per_px", "lens_px", "ride_fade")
DEPTH_A, DEPTH_B = 0.82, 0.57          # which way 'toward the camera' points (up, and down the screen)
LIGHT = np.array([-0.38, 0.84, 0.38]) / np.linalg.norm([-0.38, 0.84, 0.38])


def T(v):
    M = np.eye(4); M[:3, 3] = v; return M


def standing_matrix(ch, x, y, heading, s, lift=0.0):
    """Model -> G px. heading: screen angle she faces (0 = right, pi/2 = down the screen)."""
    fit = ch.fit
    a = math.pi / 2 - heading + float(getattr(ch.model, "face_yaw", 0.0) or 0.0)
    return (T([x, lift, y]) @ m4(rot_y(a)) @ np.diag([s, s, s, 1.0])
            @ T([-float(fit["cx"]), -float(fit["miny"]), -float(fit["cz"])]))


def project(g):
    """G point -> screen (x, y)."""
    return float(g[0]), float(g[2]) - float(g[1]) * OBLIQUE


class TopDownRenderer:
    def __init__(self, ctx, side):
        self.ctx = ctx
        self.side = int(side)
        self.ok = True
        self.fbo = self.rs = None
        try:
            try:
                c = ctx.renderbuffer((self.side, self.side), 4, samples=4)
                d = ctx.depth_renderbuffer((self.side, self.side), samples=4)
                self.fbo = ctx.framebuffer(color_attachments=[c], depth_attachment=d)
            except Exception:
                c = ctx.renderbuffer((self.side, self.side), 4); d = ctx.depth_renderbuffer((self.side, self.side))
                self.fbo = ctx.framebuffer(color_attachments=[c], depth_attachment=d)
            self.rs = ctx.framebuffer(color_attachments=[ctx.renderbuffer((self.side, self.side), 4)])
        except Exception:
            traceback.print_exc()
            print("[arena] could not create the top-down framebuffer - students will be drawn as tokens.")
            self.ok = False

    def release(self):
        for o in (self.fbo, self.rs):
            try:
                if o is not None: o.release()
            except Exception:
                pass
        self.fbo = self.rs = None
        self.ok = False

    def render(self, ch, W, M, cx, cy, half, cfg):
        """Draw pose W with model matrix M, centred on screen point (cx, cy), `half` px each way.
        Returns a premultiplied QImage of side x side px (or None)."""
        if not self.ok or ch.renderer is None:
            return None
        r = ch.renderer
        saved = {k: getattr(r, k) for k in KEYS if hasattr(r, k)}
        try:
            K, a, b = OBLIQUE, DEPTH_A, DEPTH_B
            D = half * 6.0
            V = np.array([[1.0, 0.0, 0.0, -cx],
                          [0.0, K, -1.0, cy],
                          [0.0, a, b, -b * cy],
                          [0.0, 0.0, 0.0, 1.0]])
            P = np.array([[1.0 / half, 0.0, 0.0, 0.0],
                          [0.0, 1.0 / half, 0.0, 0.0],
                          [0.0, 0.0, -1.0 / D, 0.0],
                          [0.0, 0.0, 0.0, 1.0]])
            r.fbo, r.fbo_rs = self.fbo, self.rs
            r.w = r.h = self.side
            r.view, r.proj = V, P
            r.eye = np.array([cx, a * 1.0e5, cy + b * 1.0e5])
            r.world_per_px = 2.0 * half / self.side
            if hasattr(r, "ride_fade") and getattr(ch, "ride_win", None) is not None:
                r.ride_fade = 0.0
            data = r.draw(W, M, LIGHT, cfg)
            arr = np.frombuffer(data, np.uint8).reshape(self.side, self.side, 4)[::-1]
            arr = np.ascontiguousarray(arr)
            return QtGui.QImage(arr.data, self.side, self.side, self.side * 4,
                                QtGui.QImage.Format.Format_RGBA8888_Premultiplied).copy()
        except Exception:
            traceback.print_exc()
            return None
        finally:
            for k, v in saved.items():
                try: setattr(r, k, v)
                except Exception: pass
