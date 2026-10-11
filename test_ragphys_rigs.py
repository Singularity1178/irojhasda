#!/usr/bin/env python3
"""
test_ragphys_rigs.py - headless drop test of ragphys.py on the five real BA rigs.

Each rig below is the pose the app captured for that model: the 10 physics bones,
window-local screen px at scale 1.0, y down. A skeleton spec is built from it the way
Pet.start_ragdoll does, dropped from a height with a kick, and stepped for a few
seconds. The checks are the ones that decide whether it LOOKS right:

  * nothing goes non-finite or faster than RAGP_MAX_LIN_V
  * the lowest capsule surface never sinks more than a few px into the floor
  * joints stay welded (max anchor error, px)
  * she comes to rest

The capsule radii / weights / limits below are stand-ins for what Pet derives from the
rig, so this checks the ENGINE, not Pet.

    python test_ragphys_rigs.py [--seconds 9] [--fps 60] [--scale 1.0] [--seeds 3]
                                [--self-collide 0|1]
"""
from __future__ import annotations

import argparse
import inspect
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ragphys
from ragphys import RagWorld, HAVE_PYMUNK

BONES = ["pelvis", "neck", "l upperarm", "l forearm", "r upperarm", "r forearm",
         "l thigh", "l calf", "r thigh", "r calf"]

# bone: (rig node, proximal x, proximal y, distal x, distal y)
RIGS = {
    "Chinatsu": {
        "pelvis": (7, 190.0, 372.327, 190.0, 288.555),
        "neck": (4, 190.0, 288.555, 190.0, 278.925),
        "l upperarm": (23, 213.984, 303.137, 238.681, 322.237),
        "l forearm": (53, 238.681, 322.237, 267.192, 344.609),
        "r upperarm": (62, 166.016, 303.137, 141.319, 322.237),
        "r forearm": (61, 141.319, 322.237, 112.808, 344.609),
        "l thigh": (46, 213.601, 372.327, 216.241, 423.580),
        "l calf": (51, 216.241, 423.580, 218.956, 467.213),
        "r thigh": (48, 166.399, 372.327, 163.759, 423.580),
        "r calf": (52, 163.759, 423.580, 161.043, 467.213),
    },
    "Fuuka": {
        "pelvis": (6, 190.0, 372.909, 190.0, 289.569),
        "neck": (3, 190.0, 289.569, 190.0, 279.990),
        "l upperarm": (10, 213.859, 304.076, 238.428, 323.076),
        "l forearm": (9, 238.428, 323.076, 266.790, 345.332),
        "r upperarm": (33, 166.141, 304.076, 141.572, 323.076),
        "r forearm": (32, 141.572, 323.076, 113.210, 345.332),
        "l thigh": (67, 213.478, 372.909, 216.104, 423.893),
        "l calf": (69, 216.104, 423.893, 218.806, 467.298),
        "r thigh": (68, 166.522, 372.909, 163.896, 423.893),
        "r calf": (71, 163.896, 423.893, 161.194, 467.298),
    },
    "Mika": {
        "pelvis": (13, 190.0, 367.226, 194.296, 284.345),
        "neck": (10, 194.296, 284.345, 195.068, 275.349),
        "l upperarm": (55, 216.666, 303.082, 227.090, 327.462),
        "l forearm": (126, 227.090, 327.462, 220.218, 298.002),
        "r upperarm": (84, 169.153, 302.032, 171.831, 333.141),
        "r forearm": (135, 171.831, 333.141, 209.291, 337.325),
        "l thigh": (109, 214.129, 368.065, 206.590, 420.201),
        "l calf": (108, 206.590, 420.201, 209.233, 463.860),
        "r thigh": (104, 165.838, 366.386, 179.065, 417.515),
        "r calf": (103, 179.065, 417.515, 186.319, 462.837),
    },
    "Mutsuki": {
        "pelvis": (4, 190.0, 301.918, 215.101, 271.173),
        "neck": (12, 215.101, 271.173, 219.648, 271.669),
        "l upperarm": (8, 228.077, 270.122, 231.213, 296.701),
        "l forearm": (18, 231.213, 296.701, 232.610, 330.493),
        "r upperarm": (10, 188.531, 277.744, 166.614, 295.235),
        "r forearm": (15, 166.614, 295.235, 169.992, 329.139),
        "l thigh": (13, 208.862, 299.764, 209.213, 346.205),
        "l calf": (20, 209.213, 346.205, 216.210, 385.550),
        "r thigh": (61, 170.928, 304.096, 178.735, 350.905),
        "r calf": (69, 178.735, 350.905, 169.394, 386.937),
    },
    "Yuuka": {
        "pelvis": (2, 190.0, 359.070, 202.353, 283.884),
        "neck": (36, 202.353, 283.884, 203.024, 288.899),
        "l upperarm": (18, 222.191, 295.882, 224.727, 333.213),
        "l forearm": (17, 224.727, 333.213, 185.673, 329.393),
        "r upperarm": (40, 174.745, 293.639, 169.029, 329.342),
        "r forearm": (39, 169.029, 329.342, 206.544, 332.196),
        "l thigh": (28, 215.507, 360.100, 202.247, 414.177),
        "l calf": (29, 202.247, 414.177, 197.436, 462.133),
        "r thigh": (31, 164.504, 358.041, 181.935, 408.349),
        "r calf": (49, 181.935, 408.349, 179.326, 445.467),
    },
}

# stand-ins for what Pet derives from the rig: radius px, weight, joint limit rad, k, damp
PARAMS = {
    "pelvis":   dict(r=24.0, w=0.40, lim=0.5, k=8.0, damp=9.0),
    "neck":     dict(r=22.0, w=0.14, lim=0.8, k=10.0, damp=11.0),
    "upperarm": dict(r=6.5, w=0.04, lim=2.4, k=3.0, damp=8.0),
    "forearm":  dict(r=5.5, w=0.03, lim=1.6, k=5.0, damp=10.0),
    "thigh":    dict(r=11.0, w=0.09, lim=1.5, k=6.0, damp=9.0),
    "calf":     dict(r=9.0, w=0.06, lim=1.2, k=8.0, damp=9.5),
}

FLOOR = 1080.0


def kind_of(bone):
    if bone in ("pelvis", "neck"):
        return bone
    return bone.split()[-1]


def build_spec(rig, scale, px, py):
    bodies, index = [], {}
    for i, b in enumerate(BONES):
        node, ax, ay, cx, cy = rig[b]
        par = None
        if b == "neck" or b.endswith("upperarm") or b.endswith("thigh"):
            par = index["pelvis"]
        elif b.endswith("forearm"):
            par = index[b.replace("forearm", "upperarm")]
        elif b.endswith("calf"):
            par = index[b.replace("calf", "thigh")]
        d = PARAMS[kind_of(b)]
        bodies.append(dict(name=b, bone=node, parent=par,
                           p=(ax * scale, ay * scale), c=(cx * scale, cy * scale),
                           r=d["r"] * scale, w=d["w"], lim=d["lim"], k=d["k"],
                           damp=d["damp"], head=(b == "neck")))
        index[b] = i
    feet = max(rig["l calf"][4], rig["r calf"][4]) * scale
    return dict(scale=scale, px=px, py=py, root=0,
                drop=feet - rig["pelvis"][2] * scale, bodies=bodies), feet


def add_skeleton(world, spec, owner, kick):
    fn = world.add_skeleton
    kw = {}
    for pname, prm in inspect.signature(fn).parameters.items():
        low = pname.lower()
        if "spec" in low:
            kw[pname] = spec
        elif "kick" in low:
            kw[pname] = kick
        elif "owner" in low or low in ("pet", "who", "key", "uid"):
            kw[pname] = owner
        elif (prm.default is inspect.Parameter.empty
              and prm.kind in (prm.POSITIONAL_OR_KEYWORD, prm.KEYWORD_ONLY)):
            raise RuntimeError("add_skeleton() wants an argument this test does not know: " + pname)
    skel = fn(**kw)
    if skel is None:
        skel = getattr(world, "_skels", {}).get(owner)
    if skel is None:
        raise RuntimeError("could not get the RagSkeleton back from add_skeleton()")
    return skel


def wrap(a):
    return (a + math.pi) % math.tau - math.pi


def drop(rig, scale, fps, seconds, seed):
    random.seed(seed)
    world = RagWorld()
    world.set_screen((0, 0, 1920, 1080))
    height = 380.0 * scale
    spec, feet = build_spec(rig, scale, 900.0 - 190.0 * scale, FLOOR - feet_of(rig, scale) - height)
    kick = (random.uniform(-600, 600) * scale, -random.uniform(300, 900) * scale, random.uniform(-8, 8))
    skel = add_skeleton(world, spec, 0, kick)
    dt = 1.0 / fps
    t = still = 0.0
    first = rest = None
    pen = anchor = vmax = 0.0
    bad = None
    for _ in range(int(seconds * fps)):
        world.step(dt)
        t += dt
        p = skel.pose()
        if not (math.isfinite(p["x"]) and math.isfinite(p["y"]) and math.isfinite(p["angle"])) or skel.explode_guard():
            bad = "non-finite or exploded at t=%.2fs" % t
            break
        touching = skel.touching()
        if touching and first is None:
            first = t
        if first is not None:
            pen = max(pen, skel.lowest_point() - FLOOR)
        anchor = max(anchor, skel.joint_error()[0])
        sp = skel.speed()
        vmax = max(vmax, sp)
        if sp < 40.0 * scale and touching:
            still += dt
            if still >= 0.5 and rest is None:
                rest = t
        else:
            still = 0.0
    ends = skel.body_ends()
    xs = [q[0][0] for q in ends] + [q[1][0] for q in ends]
    ys = [q[0][1] for q in ends] + [q[1][1] for q in ends]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    lean = abs(wrap(skel.pose()["angle"] + math.pi / 2))
    return dict(bad=bad, rest=rest, pen=pen, anchor=anchor, vmax=vmax,
                lean=math.degrees(lean), aspect=w / max(h, 1.0))


def feet_of(rig, scale):
    return max(rig["l calf"][4], rig["r calf"][4]) * scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=9.0)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--self-collide", type=int, default=-1)
    a = ap.parse_args()
    if not HAVE_PYMUNK:
        print('pymunk is not installed:  pip install "pymunk>=7,<8"')
        return 2
    if a.self_collide >= 0:
        ragphys.RAGP_SELF_COLLIDE = bool(a.self_collide)
    print("pymunk %s  substep 1/%d  iterations %d  self-collide %s" % (
        ragphys.PYMUNK_VERSION, round(1.0 / ragphys.RAGP_SUBSTEP), ragphys.RAGP_ITERATIONS,
        ragphys.RAGP_SELF_COLLIDE))
    print("%-9s %4s  %7s %7s %8s %8s %8s %7s" % ("rig", "seed", "rest s", "lean", "w/h", "sink px", "joint px", "vmax"))
    fails = 0
    for name, rig in RIGS.items():
        for seed in range(a.seeds):
            r = drop(rig, a.scale, a.fps, a.seconds, seed)
            problems = []
            if r["bad"]:
                problems.append(r["bad"])
            if r["rest"] is None:
                problems.append("never came to rest")
            if r["pen"] > 3.0 * a.scale:
                problems.append("sank %.1f px into the floor" % r["pen"])
            if r["anchor"] > 8.0 * a.scale:
                problems.append("joint tore %.1f px" % r["anchor"])
            if r["vmax"] > ragphys.RAGP_MAX_LIN_V * 1.01:
                problems.append("exceeded the speed ceiling")
            print("%-9s %4d  %7s %6.0fd %8.2f %8.2f %8.2f %7.0f  %s" % (
                name, seed, "-" if r["rest"] is None else "%.2f" % r["rest"], r["lean"], r["aspect"],
                r["pen"], r["anchor"], r["vmax"], "FAIL: " + "; ".join(problems) if problems else "ok"))
            fails += bool(problems)
    print("")
    print("all rigs ok" if not fails else "%d run(s) failed" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
