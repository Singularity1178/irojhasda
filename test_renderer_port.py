"""Tests for the renderer / baker port: shared programs, uniform caching, draw(flip_y=, into=),
the reusable pet frame buffer, renderbuffer release on resize, and the batched clip baker.

    python -m unittest test_renderer_port -v                (Linux: xvfb-run -a python -m unittest ...)
    BAKE_TEST_MODELS=all python -m unittest test_renderer_port.BakeTests -v      (every model/*.glb)

Tests that need an OpenGL 3.3 context are SKIPPED, with the reason, when none can be created -
they are never silently passed. Everything else (the two traps' unit tests, the baker, uniform
caching) needs no GL.
"""
from __future__ import annotations

import math
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from bapet.config import BAKE_FPS
from bapet.gltf import norm_name, sample_channel, sample_channels, sample_plan
from bapet.mathutil import pelvis_track

HERE = Path(__file__).resolve().parent
MODELS = sorted((HERE / "model").glob("*.glb"))


# --------------------------------------------------------------------------- GL availability
def make_ctx(mode=None):
    import moderngl
    ctx = moderngl.create_standalone_context(require=330)
    if mode: ctx.gc_mode = mode
    return ctx


_GL_ERR = None
try:
    make_ctx().release()
except Exception as e:                                   # no libGL / no display / GL < 3.3
    _GL_ERR = f"{type(e).__name__}: {e}"
need_gl = unittest.skipIf(_GL_ERR is not None, f"no OpenGL 3.3 context ({_GL_ERR})")
need_models = unittest.skipUnless(MODELS, "no model/*.glb files")


def dead(o):
    """moderngl 5.13 has no .released; a released object's mglo becomes an InvalidObject."""
    return type(o.mglo).__name__ == "InvalidObject"


# --------------------------------------------------------------------------- reference baker
def bake_per_channel(m, name, a):
    """The ORIGINAL (main) Model._bake_clip, verbatim: one sample_channel call per channel."""
    from bapet.gltf import Clip
    g = m.g
    chans, dur = [], 0.0
    for ch in a["channels"]:
        tg = ch["target"]
        if "node" not in tg or tg["path"] not in ("translation", "rotation", "scale", "weights"): continue
        sm = a["samplers"][ch["sampler"]]
        times = g.accessor(sm["input"]).astype(np.float64).reshape(-1)
        vals = g.accessor(sm["output"]).astype(np.float64)
        chans.append((tg["node"], tg["path"], times, vals, sm.get("interpolation", "LINEAR")))
        dur = max(dur, float(times[-1]))
    dur = max(dur, 1 / 30)
    F = max(2, int(math.ceil(dur * BAKE_FPS)) + 1)
    ts = np.linspace(0, dur, F)
    cT = np.repeat(m.rest_T.astype(np.float32)[None], F, 0); cQ = np.repeat(m.rest_Q.astype(np.float32)[None], F, 0); cS = np.repeat(m.rest_S.astype(np.float32)[None], F, 0)
    cW = np.repeat(m.node_w0.astype(np.float32)[None], F, 0)
    for node, path, times, vals, interp in chans:
        if path == "weights":
            nt = max(1, vals.size // (len(times) * (3 if interp == "CUBICSPLINE" else 1)))
            cW[:, node] = sample_channel(times, vals.reshape(-1, nt), interp, ts, path)[:, 0]
            continue
        v = sample_channel(times, vals, interp, ts, path)
        if path == "translation": cT[:, node] = v
        elif path == "rotation": cQ[:, node] = v
        else: cS[:, node] = v
    c = Clip(name, dur, cT, cQ, cS, cW)
    P = pelvis_track(m.pelvis_chain, c.T, c.Q, c.S)
    d = P[-1] - P[0]; d[1] = 0
    c.drift = d if np.linalg.norm(d) > 0.02 * m.height else None
    c.pin = -(P - P[0]); c.pin[:, 1] = 0.0
    c.ssig = np.log(np.maximum(c.S[:, m.pelvis_chain].mean(axis=0).mean(axis=1), 1e-9))
    if m._pivot is not None:
        c.origin = m._pivot - P[0]
    token = norm_name(name)
    if "kneel" in token and "attack" in token and m._pivot is not None:
        if m._floor is None: m._floor = m._lowest(m._idle_ref)
        c.origin[1] += m._floor - m._lowest(c)
    return c


def same(x, y):
    if x is None or y is None: return x is None and y is None
    return x.dtype == y.dtype and x.shape == y.shape and np.array_equal(x, y)


def assert_clips_equal(tc, new, old, label):
    for f in ("T", "Q", "S", "Wt", "pin", "origin", "ssig"):
        tc.assertTrue(same(getattr(new, f), getattr(old, f)), f"{label}: {f} differs")
    tc.assertTrue(same(new.drift, old.drift), f"{label}: drift differs")
    tc.assertEqual(new.duration, old.duration, f"{label}: duration differs")


# =========================================================================== batched baker
class SampleChannelsTests(unittest.TestCase):
    """sample_plan + sample_channels == sample_channel, bit for bit, on random data (no model)."""

    def check(self, interp, path, dim, keys=7, chans=5, seed=1):
        rng = np.random.default_rng(seed)
        times = np.sort(rng.uniform(0, 2.0, keys)); times[0] = 0.0
        ts = np.linspace(0, float(times[-1]) * 1.1, 41)            # runs past the last key too
        vals = rng.normal(size=(chans, keys, dim))
        if path == "rotation": vals /= np.linalg.norm(vals, axis=-1, keepdims=True)
        idx, u = sample_plan(times, ts)
        got = sample_channels(vals, idx, u, interp == "STEP", path == "rotation")
        for ci in range(chans):
            want = sample_channel(times, vals[ci], interp, ts, path)
            self.assertTrue(np.array_equal(got[ci], want), f"{interp}/{path} channel {ci}")

    def test_linear_translation(self): self.check("LINEAR", "translation", 3)
    def test_step_scale(self): self.check("STEP", "scale", 3)
    def test_linear_rotation_slerp(self): self.check("LINEAR", "rotation", 4)
    def test_step_rotation(self): self.check("STEP", "rotation", 4, seed=3)
    def test_two_keys(self): self.check("LINEAR", "translation", 3, keys=2)


class StubModel:
    """Just enough of Model for the unbound _bake_clip: two nodes, a hand-written glTF."""
    def __init__(self, accessors):
        self.g = SimpleNamespace(accessor=lambda i: accessors[i])
        self.rest_T = np.zeros((2, 3)); self.rest_Q = np.tile([0, 0, 0, 1.0], (2, 1)); self.rest_S = np.ones((2, 3))
        self.node_w0 = np.zeros(2)
        self.pelvis_chain = np.array([0, 1]); self.height = 1.0
        self._pivot = None; self._floor = None; self._idle_ref = None


class BakeTests(unittest.TestCase):
    def test_stub_odd_channels_and_overwrite_order(self):
        """STEP, CUBICSPLINE, a single key, an unshared time track, and two channels fighting over
        the same node (the LATER one must win, as in the per-channel loop)."""
        from bapet.model import Model
        rng = np.random.default_rng(7)
        f32 = lambda *shape: rng.normal(size=shape).astype(np.float32)
        unit = lambda n: (lambda q: (q / np.linalg.norm(q, axis=1, keepdims=True)).astype(np.float32))(rng.normal(size=(n, 4)))
        acc = {0: np.array([0, .5, 1.0], np.float32),
               1: np.array([0, .25, .5, .75, 1.0], np.float32),
               2: np.array([0.3], np.float32),
               10: f32(3, 3),      # translation, node 0, time track 0
               11: f32(3, 3),      # translation, node 1, time track 0, STEP
               12: f32(9, 3),      # translation, node 1, time track 0, CUBICSPLINE (3 values per key)
               13: f32(5, 3),      # scale, node 0, time track 1
               14: f32(1, 3),      # scale, node 1, ONE key
               15: f32(5, 3),      # translation, node 0 AGAIN, time track 1 (later channel wins)
               16: unit(3),        # rotation, node 0
               17: unit(5),        # rotation, node 1, STEP
               18: f32(3)}         # weights, node 1
        S = lambda i, o, k="LINEAR": {"input": i, "output": o, "interpolation": k}
        samplers = [S(0, 10), S(0, 11, "STEP"), S(0, 12, "CUBICSPLINE"), S(1, 13), S(2, 14),
                    S(1, 15), S(0, 16), S(1, 17, "STEP"), S(0, 18)]
        tgt = [(0, "translation"), (1, "translation"), (1, "translation"), (0, "scale"), (1, "scale"),
               (0, "translation"), (0, "rotation"), (1, "rotation"), (1, "weights")]
        anim = {"samplers": samplers,
                "channels": [{"sampler": i, "target": {"node": n, "path": p}} for i, (n, p) in enumerate(tgt)]}
        new = Model._bake_clip(StubModel(acc), "stub", anim)
        old = bake_per_channel(StubModel(acc), "stub", anim)
        assert_clips_equal(self, new, old, "stub")
        self.assertEqual(new.T.dtype, np.float32)

    @need_models
    def test_batched_bake_matches_per_channel_and_is_float32(self):
        """Every clip of the chosen models: new batched bake == old per-channel bake, bit for bit,
        and the baked tracks are float32 (the main-branch contract, not the handoff's float64)."""
        from bapet.model import Model
        pick = MODELS if os.environ.get("BAKE_TEST_MODELS") == "all" else \
            [p for p in MODELS if p.stem in ("Iroha", "Hoshino", "Ako")] or MODELS[:2]
        total = 0
        for path in pick:
            m = Model(path)
            for name, dc in m.clips.items():
                new = dc                         # DeferredClip -> Model._bake_clip (the batched one)
                old = bake_per_channel(m, name, dc._animation)
                self.assertEqual(new.T.dtype, np.float32, f"{path.stem}/{name}: c.T.dtype")
                for f in ("Q", "S", "Wt"): self.assertEqual(getattr(new, f).dtype, np.float32)
                assert_clips_equal(self, new, old, f"{path.stem}/{name}")
                total += 1
        print(f"\n  batched == per-channel for {total} clips in {len(pick)} model(s); T/Q/S/Wt float32")

    @need_models
    def test_clips_stay_deferred(self):
        """DeferredClip is kept: loading a model bakes (at most) the idle reference clip."""
        from bapet.model import DeferredClip, Model
        m = Model(MODELS[0])
        self.assertTrue(all(isinstance(c, DeferredClip) for c in m.clips.values()))
        baked = [n for n, c in m.clips.items() if c._data is not None]
        self.assertLessEqual(len(baked), 1, baked)
        self.assertGreater(len(m.clips), 5)

    @need_models
    def test_level_parents_matches_parent_lookup(self):
        from bapet.mathutil import compose_trs
        from bapet.model import Model
        m = Model(MODELS[0])
        self.assertEqual(len(m.level_parents), len(m.levels))
        for idx, lp in zip(m.levels, m.level_parents):
            self.assertTrue(np.array_equal(lp, m.parent[idx]))
        c = m.find_clip("Cafe_Idle") or m.rest_clip
        T, Q, S = c.T[0], c.Q[0], c.S[0]
        L = compose_trs(T, Q, S); W = np.empty_like(L)
        for d, idx in enumerate(m.levels):                  # the old pose_world, inline
            W[idx] = L[idx] if d == 0 else np.matmul(W[m.parent[idx]], L[idx])
        self.assertTrue(np.array_equal(m.pose_world(T, Q, S), W))


# =========================================================================== uniform caching / trap 2
class FakeUniform:
    def __init__(self, log, name): self.log, self.name = log, name
    def write(self, data): self.log.append((self.name, "write", data))
    @property
    def value(self): return None
    @value.setter
    def value(self, v): self.log.append((self.name, "value", v))


def fake_prog(log, names=("u_node", "u_skinned", "u_base", "u_basecol", "u_alpha_mode", "u_cutoff", "u_shade", "u_fade")):
    from bapet.renderer import _Prog
    q = _Prog.__new__(_Prog)
    q.prog, q.h, q.last = {n: FakeUniform(log, n) for n in names}, {}, {}
    return q


def fake_prim(skinned, node=0):
    tex = SimpleNamespace(use=lambda unit: None); vao = SimpleNamespace(render=lambda: None)
    return SimpleNamespace(tex=tex, vao=vao, vao_o=vao, node=node, skin=0 if skinned else -1,
                           u_skinned=int(skinned), u_base=0, u_basecol=(1.0, 1.0, 1.0, 1.0),
                           u_amode=0, u_cutoff=0.5, u_shade=1.0)


class UniformCacheTests(unittest.TestCase):
    def test_set_skips_unchanged_values_and_unknown_uniforms(self):
        log = []; q = fake_prog(log, ("u_a",))
        q.set("u_a", 1.0); q.set("u_a", 1.0); q.set("u_a", (1.0, 2.0)); q.set("u_a", (1.0, 2.0))
        q.set("optimised_away", 3)                         # not in the program: ignored, no KeyError
        self.assertEqual([e[2] for e in log], [1.0, (1.0, 2.0)])

    def test_trap2_nonskinned_prim_resets_u_node_cache(self):
        """skinned -> NON-skinned -> skinned: the last prim must be given the identity again.
        Without `q.last["u_node"] = None` in Renderer._draw the third write is skipped (the cache
        still says 'identity') and the skinned prim is drawn with the non-skinned prim's matrix."""
        from bapet.renderer import IDENTITY_BYTES, Renderer
        log = []; pg = fake_prog(log)
        r = Renderer.__new__(Renderer); r._pg, r._po = pg, fake_prog([])
        moved = np.eye(4); moved[:3, 3] = (1, 2, 3)
        world = {5: moved}
        r._draw(fake_prim(True), world, False)
        r._draw(fake_prim(False, 5), world, False)
        self.assertIsNone(pg.last["u_node"], "non-skinned _draw must clear the u_node cache")
        r._draw(fake_prim(True), world, False)
        nodes = [e[2] for e in log if e[0] == "u_node"]
        self.assertEqual(len(nodes), 3, "the skinned prim after a non-skinned one must re-write u_node")
        self.assertEqual(nodes[0], IDENTITY_BYTES); self.assertNotEqual(nodes[1], IDENTITY_BYTES)
        self.assertEqual(nodes[2], IDENTITY_BYTES, "later skinned prim must not inherit the previous matrix")

    def test_consecutive_skinned_prims_write_identity_once(self):
        from bapet.renderer import Renderer
        log = []; pg = fake_prog(log)
        r = Renderer.__new__(Renderer); r._pg, r._po = pg, fake_prog([])
        for _ in range(4): r._draw(fake_prim(True), {}, False)
        self.assertEqual(len([e for e in log if e[0] == "u_node"]), 1)


# =========================================================================== trap 1 (no GL)
class FakeRenderer:
    """Honours flip_y exactly as a GL framebuffer read does: GL rows are bottom-first, and
    flip_y=True mirrors the projection so the same scene arrives top-first.
    Scene: the TOP row of the picture is opaque, everything else empty."""
    def __init__(self, w, h): self.w, self.h = w, h
    def draw(self, world, M, light, cfg, flip_y=False, into=None):
        img = np.zeros((self.h, self.w, 4), np.uint8)
        img[0 if flip_y else self.h - 1] = 255            # the scene's top row, in the order GL returns it
        into[:] = img.tobytes()
        return into


def new_pet():
    return SimpleNamespace(_fbuf=None, light=np.zeros(3), dpr=1.0, raw=None, img=None, alpha=None)


class PetFrameTests(unittest.TestCase):
    def test_trap1_flip_y_and_alpha_index_land_together(self):
        """Picture and click-through mask must agree about which row is the top. With flip_y=True the
        QImage is unmirrored and alpha is [:, :, 3]; changing one without the other swaps them."""
        from bapet.pet_render import PetRender
        w, h = 6, 4
        pet = new_pet(); PetRender.grab_frame(pet, FakeRenderer(w, h), None, None, {})
        self.assertTrue((pet.alpha[0] == 255).all() and (pet.alpha[1:] == 0).all(),
                        "mask: the scene's top row must be row 0")
        top, bottom = pet.img.pixelColor(2, 0).alpha(), pet.img.pixelColor(2, h - 1).alpha()
        self.assertEqual((top, bottom), (255, 0), "picture: the scene's top row must be row 0")
        for y in range(h):                                  # and the two agree pixel for pixel
            for x in range(w):
                self.assertEqual(pet.img.pixelColor(x, y).alpha(), int(pet.alpha[y, x]))

    def test_frame_buffer_is_reused_and_reallocated_on_resize(self):
        from bapet.pet_render import PetRender
        pet = new_pet(); PetRender.grab_frame(pet, FakeRenderer(6, 4), None, None, {}); first = pet._fbuf
        PetRender.grab_frame(pet, FakeRenderer(6, 4), None, None, {})
        self.assertIs(pet._fbuf, first, "same size: same buffer")
        self.assertIs(pet.raw, first)
        PetRender.grab_frame(pet, FakeRenderer(8, 5), None, None, {})
        self.assertIsNot(pet._fbuf, first); self.assertEqual(len(pet._fbuf), 8 * 5 * 4)
        self.assertEqual(pet.alpha.shape, (5, 8))

    def test_alpha_views_the_buffer_not_a_copy(self):
        from bapet.pet_render import PetRender
        pet = new_pet(); PetRender.grab_frame(pet, FakeRenderer(6, 4), None, None, {})
        self.assertTrue(np.shares_memory(pet.alpha, np.frombuffer(pet._fbuf, np.uint8)))


# =========================================================================== real GL
CFG = dict(exposure=1.0, toon_threshold=0.5, toon_softness=0.05, shadow_strength=0.5, rim=0.3, spec=0.3,
           saturation=1.0, deep_shadow=0.3, outline_px=1.5, outline_dark=0.5)
LIGHT = np.array([0.3, 0.5, 0.8])


@need_gl
@need_models
class GLTests(unittest.TestCase):
    path = next((p for p in MODELS if p.stem == "Ako"), MODELS[0] if MODELS else None)

    def renderer(self, ctx):
        from bapet.model import Model
        from bapet.renderer import Renderer
        m = Model(self.path)
        c = m.find_clip("Cafe_Idle") or m.rest_clip
        W = m.pose_world(c.T[0], c.Q[0], c.S[0])
        r = Renderer(m, m.compute_fit(W), ctx); r.set_size(96, 128)
        return r, W

    def test_shared_programs_one_pair_per_context(self):
        from bapet.renderer import shared_programs
        ctx = make_ctx("context_gc"); self.addCleanup(ctx.release)
        r1, _ = self.renderer(ctx); r2, _ = self.renderer(ctx)
        self.assertIs(r1.pg, r2.pg); self.assertIs(r1.po, r2.po)
        self.assertIs(shared_programs(ctx)[0].prog, r1.pg)
        ctx2 = make_ctx(); self.addCleanup(ctx2.release)
        self.assertIsNot(shared_programs(ctx2)[0].prog, r1.pg, "a different context gets its own programs")

    @staticmethod
    def nonflat(x, thr=8):
        """True where the 3x3 neighbourhood contains a colour step > thr (an edge)."""
        p = np.pad(x, ((1, 1), (1, 1), (0, 0)), mode="edge"); rng = np.zeros(x.shape[:2])
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                rng = np.maximum(rng, np.abs(p[1 + dy:1 + dy + x.shape[0], 1 + dx:1 + dx + x.shape[1]] - x).max(axis=2))
        return rng > thr

    def test_flip_y_gives_the_vertically_mirrored_frame(self):
        """flip_y=True == the plain frame turned over. Not pixel-exact: 4x MSAA's sample pattern is not
        vertically symmetric, so pixels on colour edges differ slightly (measured: the mismatch is all
        edge pixels and shrinks as the frame grows). Flat regions must be IDENTICAL."""
        ctx = make_ctx("context_gc"); self.addCleanup(ctx.release)
        r, W = self.renderer(ctx); M = np.eye(4)
        up = np.frombuffer(r.draw(W, M, LIGHT, CFG), np.uint8).reshape(128, 96, 4).astype(int)
        buf = bytearray(96 * 128 * 4)
        self.assertIs(r.draw(W, M, LIGHT, CFG, flip_y=True, into=buf), buf)
        fl = np.frombuffer(buf, np.uint8).reshape(128, 96, 4).astype(int)
        cover = int((up[..., 3] > 0).sum())
        self.assertGreater(cover, 1000, "the model must actually be in the frame")
        a = up[::-1]; diff = np.abs(a - fl).max(axis=2)
        flat = ~(self.nonflat(a) | self.nonflat(fl))
        self.assertEqual(int(((diff > 8) & flat).sum()), 0, "flat regions must match exactly")
        self.assertLess(float(np.abs(a - fl).mean()), 1.5)
        self.assertLess(int(((a[..., 3] > 0) != (fl[..., 3] > 0)).sum()), 0.03 * cover, "silhouette differs")
        # and it really is the other way up: un-mirrored it must NOT match
        self.assertGreater(float(np.abs(up - fl).mean()), 4 * float(np.abs(a - fl).mean()))

    def test_pet_alpha_through_real_renderer_matches_old_path(self):
        """grab_frame with the real renderer: the new alpha is the old `draw()[::-1, :, 3]` (silhouette
        up to MSAA edge noise), and clearly NOT the un-reversed one."""
        from bapet.pet_render import PetRender
        ctx = make_ctx("context_gc"); self.addCleanup(ctx.release)
        r, W = self.renderer(ctx); M = np.eye(4)
        plain = np.frombuffer(r.draw(W, M, LIGHT, CFG), np.uint8).reshape(128, 96, 4)[..., 3]
        old = plain[::-1] > 12
        pet = new_pet(); pet.light = LIGHT
        PetRender.grab_frame(pet, r, W, M, CFG)
        new = pet.alpha > 12
        self.assertLess(int((new != old).sum()), 0.03 * int(old.sum()))
        self.assertGreater(int((new != (plain > 12)).sum()), 0.3 * int(old.sum()), "must not be the un-flipped mask")

    def test_set_size_releases_old_renderbuffers_with_gc_mode_none(self):
        """gc_mode None (a bare Renderer(ctx=None)): every resize used to strand 3 renderbuffers."""
        ctx = make_ctx(None); self.addCleanup(ctx.release)
        r, _ = self.renderer(ctx)
        old = list(r._fb)
        self.assertEqual(len(old), 5)
        r.set_size(100, 130)
        self.assertTrue(all(dead(o) for o in old), [type(o).__name__ for o in old if not dead(o)])
        self.assertFalse(any(dead(o) for o in r._fb))
        for i in range(10): r.set_size(101 + i, 131 + i)
        self.assertEqual(len(r._fb), 5)
        r.set_size(110, 140)                                  # same size is a no-op: nothing released
        self.assertFalse(any(dead(o) for o in r._fb))

    def test_set_size_with_context_gc_mode_leaves_release_to_ctx_gc(self):
        """Under the app's mode a hand release would make ctx.gc() raise (moderngl 5.13): resize must
        leave that to ctx.gc(), which must keep working and keep rendering."""
        ctx = make_ctx("context_gc"); self.addCleanup(ctx.release)
        r, W = self.renderer(ctx)
        for i in range(5):
            old = list(r._fb)
            r.set_size(100 + i, 130 + i)
            self.assertFalse(any(dead(o) for o in old), "no hand release under context_gc")
            ctx.gc()                                          # must not raise
        r.draw(W, np.eye(4), LIGHT, CFG)

    def test_uniform_uploads_collapse_after_the_first_draw(self):
        """Counted at the real uniform handles: draw #2 of an identical pose uploads a fraction of #1."""
        import moderngl
        ctx = make_ctx("context_gc"); self.addCleanup(ctx.release)
        r, W = self.renderer(ctx)
        n = {"v": 0}
        class Count:
            def __init__(s, u): s.u = u
            def write(s, d): n["v"] += 1; s.u.write(d)
            @property
            def value(s): return s.u.value
            @value.setter
            def value(s, v): n["v"] += 1; s.u.value = v
        for q in (r._pg, r._po):
            for name in list(q.prog):
                u = q.prog[name]
                if isinstance(u, moderngl.Uniform): q.h[name] = Count(u)
        M = np.eye(4)
        r.draw(W, M, LIGHT, CFG); first = n["v"]
        n["v"] = 0; r.draw(W, M, LIGHT, CFG); second = n["v"]
        print(f"\n  uniform uploads per draw: first {first}, second {second}")
        self.assertGreater(first, second)
        self.assertLess(second, 0.5 * first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
