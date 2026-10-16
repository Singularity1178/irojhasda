#!/usr/bin/env python3
"""Headless tests for ragphys3d.py (the fully 3D ragdoll). Plain `python test_ragphys3d.py`.

No Qt, no GL, no numpy: a synthetic chibi body (big head, short legs) built in
screen px. Each test prints what it measured, so a regression in feel shows up
as a number, not just a red cross.
"""
from __future__ import annotations

import math
import random
import time
import unittest

import ragphys3d as R3

SCREEN = (0.0, 0.0, 1920.0, 1040.0)
FPS = 60


def human(x=960.0, sole=1040.0, ch=300.0, z=0.0, chest=True):
    """A standing chibi in global px, y down, facing the viewer (her left = screen right)."""
    H = lambda f: sole - f * ch
    pts = {
        "foot_l": (x + 0.055 * ch, H(0.035), z), "foot_r": (x - 0.055 * ch, H(0.035), z),
        "knee_l": (x + 0.055 * ch, H(0.19), z - 0.012 * ch), "knee_r": (x - 0.055 * ch, H(0.19), z - 0.012 * ch),
        "hip_l": (x + 0.055 * ch, H(0.35), z), "hip_r": (x - 0.055 * ch, H(0.35), z),
        "pelvis": (x, H(0.38), z + 0.01 * ch),
        "neck": (x, H(0.62), z),
        "head": (x, H(0.76), z - 0.01 * ch),
        "shoulder_l": (x + 0.10 * ch, H(0.585), z), "shoulder_r": (x - 0.10 * ch, H(0.585), z),
        "elbow_l": (x + 0.13 * ch, H(0.47), z + 0.01 * ch), "elbow_r": (x - 0.13 * ch, H(0.47), z + 0.01 * ch),
        "hand_l": (x + 0.14 * ch, H(0.37), z - 0.01 * ch), "hand_r": (x - 0.14 * ch, H(0.37), z - 0.01 * ch),
    }
    if chest:
        pts["chest"] = (x, H(0.50), z + 0.005 * ch)
    return dict(scale=1.0, ch=ch, depth=0.35 * ch, tone=0.5, drop=0.38 * ch, pts=pts,
                head_r=0.15 * ch, fwd=(0.0, 0.0, -1.0), sole=sole)


def world(rect=SCREEN):
    w = R3.Rag3DWorld()
    w.set_screen(rect)
    return w


def run(w, seconds, cb=None):
    for f in range(int(seconds * FPS)):
        w.step(1.0 / FPS)
        if cb is not None and cb(f) is False:
            return f
    return int(seconds * FPS)


def inside(skel, rect=SCREEN, tol=1.0):
    l, t, r, b = rect
    for nm, x, y, z, rad in skel.points():
        if x - rad < l - tol or x + rad > r + tol or y - rad < t - tol or y + rad > b + tol:
            return False, nm
        if abs(z) > max(skel.depth - rad, 0.0) + tol:
            return False, nm + " (depth)"
    return True, ""


def lying(skel):
    """How she ended up: back / front / side, from the pelvis frame's forward axis."""
    Rp = skel.rotations()["pelvis"]
    f = R3._mv(Rp, skel.frame_pelvis[2])
    if f[1] < -0.6:
        return "on her back"
    if f[1] > 0.6:
        return "face down"
    return "on her side"


def rest_time(w, skel, seconds=8.0):
    """Seconds until she is below the rest speed while touching, held for 0.5 s."""
    held, t_rest = 0.0, None

    def cb(f):
        nonlocal held, t_rest
        if skel.touching() and skel.speed() < R3.RAG3_REST_SPEED:
            held += 1.0 / FPS
            if held > 0.5 and t_rest is None:
                t_rest = (f + 1) / FPS - 0.5
        else:
            held = 0.0
    run(w, seconds, cb)
    return t_rest


class TestFalls(unittest.TestCase):
    def test_1_crumple_settles_on_floor(self):
        """Ctrl+1: she crumples where she stands, ends down on the floor, still, inside."""
        random.seed(1)
        stats = []
        for seed in range(6):
            random.seed(seed)
            w = world()
            sk = w.add_skeleton(1, human(), (0.0, 0.0, 0.0), "crumple")
            zmax = [0.0]

            def cb(f):
                zmax[0] = max(zmax[0], max(abs(z) for z in sk.Z))
                ok, nm = inside(sk)
                self.assertTrue(ok, f"{nm} left the screen / slab on frame {f}")
            run(w, 0.01, None)
            t = rest_time(w, sk, 8.0)
            run(w, 0.5, cb)
            self.assertIsNotNone(t, f"seed {seed}: never came to rest")
            pel_h = SCREEN[3] - sk.pose()["y"]
            be, lv = sk.joint_error()
            self.assertLess(pel_h, 0.30 * sk.ch, f"seed {seed}: still standing (pelvis {pel_h:.0f}px up)")
            self.assertLess(be, 2.0, f"seed {seed}: bones stretched {be:.2f}px")
            self.assertLess(lv, 0.12, f"seed {seed}: a joint is {math.degrees(lv):.1f} deg past its limit")
            stats.append((seed, t, pel_h, max(abs(z) for z in sk.Z), lying(sk), be, math.degrees(lv)))
        print("\n  [1] crumple: seed, rest after s, pelvis height px, |z| max px, ends, bone err, limit err")
        for s in stats:
            print(f"      {s[0]}  {s[1]:.2f}s  {s[2]:5.1f}px  z={s[3]:5.1f}px  {s[4]:<12} {s[5]:.2f}px {s[6]:.2f}deg")

    def test_2_drop_from_height(self):
        """Dropped from 1500 px: lands hard (impact ~ v/1000), nothing tunnels, she settles."""
        random.seed(7)
        w = world()
        sk = w.add_skeleton(1, human(sole=SCREEN[3] - 700.0), (0.0, 0.0, 0.0), "kick")
        best = [0.0]

        def cb(f):
            for im in w.pop_impacts(1):
                best[0] = max(best[0], im.strength)
            ok, nm = inside(sk)
            self.assertTrue(ok, f"{nm} left the screen on frame {f}")
        run(w, 3.0, cb)
        t = rest_time(w, sk, 6.0)
        self.assertIsNotNone(t, "never settled after the drop")
        self.assertGreater(best[0], 0.9, "the landing reported no real impact")
        print(f"\n  [2] drop 700px: strongest impact {best[0]:.2f}, settled {t:.2f}s after landing, "
              f"ends {lying(sk)}")

    def test_3_edge_slam_contained(self):
        """Slammed into each screen edge at 5000 px/s: never leaves the screen, crumples, settles."""
        for vx, vy, x in ((5000.0, 0.0, 1700.0), (-5000.0, 0.0, 220.0), (1500.0, -5000.0, 960.0)):
            random.seed(3)
            w = world()
            sk = w.add_skeleton(1, human(x=x, sole=900.0), (vx, vy, 0.0), "slam")
            worst = [0.0]

            def cb(f):
                ok, nm = inside(sk, tol=2.0)
                self.assertTrue(ok, f"slam {vx},{vy}: {nm} tunnelled out on frame {f}")
                worst[0] = max(worst[0], sk.joint_error()[0])
            run(w, 2.0, cb)
            t = rest_time(w, sk, 8.0)
            self.assertIsNotNone(t, f"slam {vx},{vy}: never settled")
            self.assertLess(worst[0], 25.0, f"slam {vx},{vy}: bones stretched {worst[0]:.1f}px mid-hit")
            print(f"\n  [3] slam ({vx:+.0f},{vy:+.0f}): contained, worst bone stretch mid-hit "
                  f"{worst[0]:.1f}px, settled {t:.2f}s later, {lying(sk)}")

    def test_4_shot_goes_into_depth(self):
        """Shot: the upper body is driven back over planted feet, and she turns in depth."""
        zs, dx = [], []
        for seed in range(6):
            random.seed(seed)
            w = world()
            spec = human()
            sk = w.add_skeleton(1, spec, (1400.0, -300.0, 4.0), "shot")
            x0 = sk.pose()["x"]
            feet0 = sk.X[sk.idx["foot_l"]]
            zmax = [0.0]

            def cb(f):
                zmax[0] = max(zmax[0], max(abs(z) for z in sk.Z))
            run(w, 1.0, cb)
            dx.append((sk.pose()["x"] - x0, sk.X[sk.idx["foot_l"]] - feet0))
            zs.append(zmax[0])
            t = rest_time(w, sk, 8.0)
            self.assertIsNotNone(t, f"seed {seed}: never settled after the shot")
        self.assertTrue(all(p > 0 for p, _ in dx), "the shot did not push her along the bullet")
        self.assertTrue(all(p > f for p, f in dx), "the feet travelled as far as the pelvis: she slid, not fell")
        self.assertGreater(max(zs), 0.25 * 0.35 * 300.0, "nothing ever moved into the depth")
        print("\n  [4] shot: pelvis / feet travel px, deepest |z| px")
        for (p, f), z in zip(dx, zs):
            print(f"      pelvis {p:6.1f}  feet {f:6.1f}  z {z:5.1f}")


class TestWorld(unittest.TestCase):
    def test_5_lands_on_window_and_window_on_top(self):
        random.seed(5)
        w = world()
        w.sync_windows([(42, 700.0, 640.0, 1300.0, 1040.0)], 0.0, True)
        sk = w.add_skeleton(1, human(x=1000.0, sole=560.0), (0.0, 0.0, 0.0), "crumple")
        run(w, 4.0)
        low = sk.lowest_point()
        self.assertLess(abs(low - 640.0), 3.0, f"did not come to rest on the window top (low {low:.1f})")
        # a window opening right on top of a lying body must not catapult her
        w2 = world()
        sk2 = w2.add_skeleton(2, human(x=500.0), (0.0, 0.0, 0.0), "crumple")
        run(w2, 4.0)
        w2.sync_windows([(7, 300.0, 700.0, 900.0, 1040.0)], 10.0, True)
        peak = [0.0]
        run(w2, 1.0, lambda f: peak.__setitem__(0, max(peak[0], sk2.speed())))
        self.assertLess(peak[0], 150.0, f"a new window threw her at {peak[0]:.0f} px/s")
        # and a window sliding into her shoves her along
        w2.sync_windows([(7, 300.0, 700.0, 900.0, 1040.0)], 11.0, True)
        run(w2, 2.0)
        print(f"\n  [5] rests on window top (low {low:.1f} vs 640), new window on top: peak {peak[0]:.0f} px/s")

    def test_6_two_ragdolls_collide(self):
        random.seed(11)
        w = world()
        a = w.add_skeleton(1, human(x=700.0, sole=900.0), (1800.0, -400.0, 0.0), "kick")
        b = w.add_skeleton(2, human(x=1250.0, sole=900.0), (-1800.0, -400.0, 0.0), "kick")
        hits = [0]

        def cb(f):
            hits[0] += sum(1 for im in w.pop_impacts(1) if im.kind == "pet")
            w.pop_impacts(2)
        run(w, 4.0, cb)
        self.assertGreater(hits[0], 0, "they passed through each other")
        worst = 0.0
        for i in range(a.n):
            for j in range(b.n):
                d = math.dist((a.X[i], a.Y[i], a.Z[i]), (b.X[j], b.Y[j], b.Z[j]))
                worst = max(worst, a.R[i] + b.R[j] - d)
        self.assertLess(worst, 3.0, f"they ended {worst:.1f}px inside each other")
        for s in (a, b):
            self.assertFalse(s.explode_guard())
        print(f"\n  [6] two ragdolls: {hits[0]} frames with pet contacts, end overlap {max(0, worst):.2f}px")

    def test_7_grab_swing_throw(self):
        random.seed(2)
        w = world()
        sk = w.add_skeleton(1, human(), (0.0, 0.0, 0.0), "crumple")
        run(w, 2.0)
        hx, hy = sk.X[sk.idx["hand_l"]], sk.Y[sk.idx["hand_l"]]
        self.assertTrue(sk.grab((hx, hy)))
        self.assertTrue(sk.grab_joint)
        for f in range(90):                                  # lift and swing her by the hand
            t = f / 60.0
            sk.move_grab((hx + 300 * math.sin(t * 5.0), hy - 400 * min(1.0, t)))
            w.step(1 / 60)
        hang = sk.Y[sk.idx["pelvis"]] > sk.Y[sk.grab_i]
        sk.release_grab()
        self.assertIsNone(sk.grab_joint)
        top = max(math.sqrt(sk.VX[i] ** 2 + sk.VY[i] ** 2 + sk.VZ[i] ** 2) for i in range(sk.n))
        self.assertLessEqual(top, R3.RAG3_GRAB_THROW_V + 1e-6)
        t = rest_time(w, sk, 8.0)
        self.assertTrue(hang, "she did not hang below the hand she was held by")
        self.assertIsNotNone(t, "never settled after the throw")
        print(f"\n  [7] grabbed by the hand: hung below it, thrown at {top:.0f} px/s, settled {t:.2f}s later")

    def test_8_rotations_match_particles(self):
        """What the renderer gets (rotations) reproduces where the particles are."""
        random.seed(4)
        w = world()
        sk = w.add_skeleton(1, human(), (900.0, -600.0, 3.0), "shot")
        run(w, 0.6)
        rots = sk.rotations()
        worst = 0.0
        for nm, (j, k, u0, _p) in sk.bone_of.items():
            u = R3._unit((sk.X[k] - sk.X[j], sk.Y[k] - sk.Y[j], sk.Z[k] - sk.Z[j]))
            v = R3._mv(rots[nm], u0)
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, R3._dot(u, v))))))
        rig = 0.0
        for k, cl in enumerate(sk.clusters):
            Rm = rots["pelvis" if k == 0 else "chest"]
            i0 = cl["idx"][0]
            for i, q in zip(cl["idx"], cl["q"]):
                q0 = cl["q"][0]
                pr = R3._mv(Rm, (q[0] - q0[0], q[1] - q0[1], q[2] - q0[2]))
                rig = max(rig, math.dist(pr, (sk.X[i] - sk.X[i0], sk.Y[i] - sk.Y[i0], sk.Z[i] - sk.Z[i0])))
        for nm, Rm in rots.items():
            det = (Rm[0] * (Rm[4] * Rm[8] - Rm[5] * Rm[7]) - Rm[1] * (Rm[3] * Rm[8] - Rm[5] * Rm[6])
                   + Rm[2] * (Rm[3] * Rm[7] - Rm[4] * Rm[6]))
            self.assertAlmostEqual(det, 1.0, 5, f"{nm} is not a rotation")
        self.assertLess(worst, 0.01, f"a bone rotation misses its particle by {worst:.3f} deg")
        self.assertLess(rig, 1.5, f"a torso cluster is {rig:.2f}px from rigid")
        print(f"\n  [8] rotations: worst bone direction error {worst:.5f} deg, torso rigid to {rig:.3f}px")

    def test_9_no_chest_rig(self):
        """A rig without a chest bone gets one rigid torso and still works."""
        random.seed(9)
        w = world()
        sk = w.add_skeleton(1, human(chest=False), (0.0, 0.0, 0.0), "crumple")
        self.assertFalse(sk.has_chest)
        t = rest_time(w, sk, 8.0)
        self.assertIsNotNone(t)
        print(f"\n  [9] no-chest rig: {len(sk.clusters)} cluster, settled after {t:.2f}s, {lying(sk)}")

    def test_10_performance(self):
        """4 ragdolls + 10 windows: cost per 1/60 s frame."""
        random.seed(10)
        w = world()
        wins = [(100 + i, 80.0 + i * 180.0, 500.0 + (i % 3) * 60.0, 220.0 + i * 180.0, 1040.0) for i in range(10)]
        w.sync_windows(wins, 0.0, True)
        for k in range(4):
            w.add_skeleton(k + 1, human(x=300.0 + k * 420.0, sole=400.0), (random.uniform(-900, 900), 0.0, 0.0),
                           "kick")
        t0 = time.perf_counter()
        frames = run(w, 3.0)
        ms = (time.perf_counter() - t0) * 1000.0 / frames
        per = ms / 4.0
        print(f"\n  [10] 4 ragdolls + 10 windows: {ms:.2f} ms per frame ({per:.2f} ms per ragdoll, "
              f"{R3.RAG3_SUBSTEP ** -1:.0f} Hz substeps)")
        self.assertLess(per, 6.0, "far too slow for a desktop pet")

    def test_11_iterations_slider(self):
        """cfg ragdoll_3d_iters: every setting stays contained, settles and keeps her limbs
        together; fewer iterations cost proportionally less."""
        rows = []
        for it in (R3.RAG3_ITERS_MIN, 2, 3, R3.RAG3_ITERS_DEFAULT, R3.RAG3_ITERS_MAX):
            random.seed(11)
            w = world()
            self.assertEqual(w.set_iterations(it), it)
            sk = w.add_skeleton(1, human(), (2500.0, -600.0, 4.0), "slam")
            worst = [0.0]

            def cb(f):
                worst[0] = max(worst[0], sk.joint_error()[0])
                ok, nm = inside(sk, tol=2.0)
                self.assertTrue(ok, f"iters={it}: {nm} left the screen")
            t0 = time.perf_counter()
            run(w, 2.0, cb)
            ms = (time.perf_counter() - t0) * 1000.0 / (2.0 * FPS)
            t = rest_time(w, sk, 6.0)
            self.assertIsNotNone(t, f"iters={it}: never settled")
            self.assertFalse(sk.broken, f"iters={it}: blew up")
            self.assertLess(worst[0], 0.12 * sk.ch, f"iters={it}: limbs pulled apart")
            rows.append((it, ms, worst[0], t))
        # out-of-range values clamp instead of breaking the world
        w = world()
        self.assertEqual(w.set_iterations(0), R3.RAG3_ITERS_MIN)
        self.assertEqual(w.set_iterations(99), R3.RAG3_ITERS_MAX)
        self.assertEqual(w.set_iterations("junk"), R3.RAG3_ITERS_DEFAULT)
        print("\n  [11] iterations: substeps/frame, ms/frame (incl. joint checks), worst bone stretch, settle s")
        for it, ms, be, t in rows:
            print(f"      {it:2d} ({it * 60:3d} Hz)  {ms:5.2f} ms  {be:5.1f}px  {t:.2f}s")

    def test_12_sleep_and_wake(self):
        """A body lying still falls asleep (costs nothing) and wakes when disturbed:
        a shove, a grab, the window under her closing, another ragdoll landing on her."""
        random.seed(12)
        w = world()
        w.sync_windows([(7, 800.0, 700.0, 1200.0, 1040.0)], 0.0, True)
        sk = w.add_skeleton(1, human(x=1000.0, sole=700.0), (0.0, 0.0, 0.0), "crumple")
        run(w, 4.0)
        self.assertTrue(sk.sleeping, "never fell asleep on the window")
        self.assertTrue(sk.touching())
        self.assertEqual(sk.speed(), 0.0)
        self.assertEqual(w.active, 0)
        y0 = sk.Y[sk.idx["pelvis"]]
        # the window under her closes: she wakes and falls to the floor
        w.sync_windows([], 0.1, True)
        self.assertFalse(sk.sleeping, "closing the window under her did not wake her")
        run(w, 2.0)
        self.assertGreater(sk.Y[sk.idx["pelvis"]], y0 + 150.0, "she did not fall when her window closed")
        run(w, 3.0)
        self.assertTrue(sk.sleeping)
        # a shove wakes her
        sk.shove((sk.X[0] - 50.0, sk.Y[0]), 1.0)
        self.assertFalse(sk.sleeping)
        run(w, 4.0)
        self.assertTrue(sk.sleeping)
        # a grab wakes her
        self.assertTrue(sk.grab((sk.X[0], sk.Y[0])))
        self.assertFalse(sk.sleeping)
        run(w, 0.5)
        self.assertFalse(sk.sleeping, "fell asleep while held")
        sk.release_grab()
        run(w, 4.0)
        self.assertTrue(sk.sleeping)
        # another ragdoll dropped onto her wakes her
        x = sk.X[sk.idx["pelvis"]]
        sk2 = w.add_skeleton(2, human(x=x, sole=500.0), (0.0, 0.0, 0.0), "throw")
        woke = [False]
        run(w, 1.0, lambda f: woke.__setitem__(0, woke[0] or not sk.sleeping))
        self.assertTrue(woke[0], "a body landing on her did not wake her")
        run(w, 6.0)
        self.assertTrue(sk.sleeping and sk2.sleeping, "the pile never went to sleep")
        print(f"\n  [12] sleep: asleep on a window, woke on close / shove / grab / body landing, "
              f"pile asleep again, idle step {w.cost_ms:.3f} ms")

    def test_13_occluded_windows_clipped_not_just_dropped(self):
        """A window hidden behind another one (including a maximised window whose own top is
        above the screen) must not act as a perch or a collider. Fully hidden windows are
        dropped; half hidden ones are clipped to the part you can actually see."""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "wintracker", Path(__file__).resolve().parent / "bapet" / "wintracker.py")
        wt_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wt_mod)
        WT = wt_mod.WinTracker
        SCREEN = (0.0, 0.0, 1920.0, 1040.0)
        TOP_LIMIT = 0.0

        def kept(cands):
            """Drive the real refresh() filtering over a front-to-back candidate list."""
            out, above, occ = [], [], {}
            for h, l, t, r, b in cands:
                usable = not (r - l < wt_mod.MIN_WIN_W or b - t < wt_mod.MIN_WIN_H or t < TOP_LIMIT + 60.0)
                if usable:
                    v = WT._visible_rect((l, t, r, b), above, SCREEN)
                    if v is not None:
                        occ[h] = list(above)
                        out.append((h, v))
                above.append((l, t, r, b))
            return out, occ

        # A: terminal completely behind a maximised Edge window -> gone
        out, _ = kept([(1, 0.0, 0.0, 1920.0, 1040.0), (2, 300.0, 220.0, 1100.0, 750.0)])
        self.assertEqual(out, [], f"terminal behind a maximised window was kept: {out}")

        # B: terminal completely inside a normal Edge window -> gone
        out, _ = kept([(1, 150.0, 120.0, 1600.0, 920.0), (2, 300.0, 220.0, 1100.0, 750.0)])
        self.assertEqual([h for h, _ in out], [1], f"covered terminal was kept: {out}")

        # C: terminal half behind Edge -> CLIPPED to the exposed left half, not left full size
        out, _ = kept([(1, 800.0, 120.0, 1700.0, 920.0), (2, 200.0, 250.0, 1100.0, 800.0)])
        by_h = dict(out)
        self.assertIn(2, by_h, "a still-visible terminal was dropped")
        self.assertEqual(by_h[2], (200.0, 250.0, 800.0, 800.0),
                         f"terminal was not clipped to its exposed strip: {by_h[2]}")

        # D: title bar hidden behind Edge (only the body sticks out below) -> gone,
        #    because there is no visible top edge to land on
        out, _ = kept([(1, 150.0, 120.0, 1400.0, 500.0), (2, 250.0, 300.0, 1000.0, 800.0)])
        self.assertEqual([h for h, _ in out], [1], f"terminal with a hidden title bar was kept: {out}")

        # E: a 90% buried terminal reduced to a sliver is not somewhere to stand -> gone
        out, _ = kept([(1, 200.0, 220.0, 1100.0, 750.0), (2, 200.0, 220.0, 300.0, 750.0)])
        self.assertEqual([h for h, _ in out], [1], f"a 100px sliver of a window was kept: {out}")

        # the live re-check a standing student relies on: what surfaces() offers at each x
        tr = WT()
        tr.wins, tr._occ_before = [(2, 200.0, 250.0, 800.0, 800.0)], {2: [(800.0, 120.0, 1700.0, 920.0)]}
        self.assertTrue(tr.surface_visible(2, 500.0), "exposed half reported as covered")
        self.assertFalse(tr.surface_visible(2, 900.0), "covered half reported as a perch")
        self.assertEqual(tr.surfaces(500.0), [(250.0, 2)])
        self.assertEqual(tr.surfaces(900.0), [])
        print("\n  [13] occlusion: fully hidden dropped, half hidden clipped to (200, 250, 800, 800), "
              "hidden title bar dropped, sliver dropped; surface_visible tracks the covered half")


if __name__ == "__main__":
    unittest.main(verbosity=1)
