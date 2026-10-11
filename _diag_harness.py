#!/usr/bin/env python3
"""
Drive ragdiag.py headlessly, exactly the way --rag-diag does, over the real
rigs. This is the only way to know the logger works without clicking Ctrl+1 in
a GUI, and it reproduces the Chinatsu case that will not auto-get-up.
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ragphys
import ragdiag
import test_ragphys_rigs as T


class FakeApp:
    rag_diag = 40


class FakePet:
    """Stands in for Pet: the probes must never depend on a live Qt widget."""
    name = "TestChar"
    px = 900.0
    py = 1080.0
    cfg = {"ragdoll_engine": "pymunk", "scale": 1.0}
    grounded = True
    dragging = False

    def __init__(self):
        self.rag_owner = 4242
        self.name = "TestChar"

    def isVisible(self):
        return True


def main():
    frames = ragdiag.enable(FakeApp())
    print(f"ragdiag.enable -> {frames}\n")

    name = sys.argv[1] if len(sys.argv) > 1 else "Chinatsu"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    rig = T.RIGS[name]
    pet = FakePet()

    ragphys.RAGP_SELF_COLLIDE = True
    random.seed(seed)
    world = T.RagWorld()
    world.set_screen((0, 0, 1920, 1080))
    spec, _ = T.build_spec(rig, 1.0, 900.0 - 190.0, T.FLOOR - T.feet_of(rig, 1.0))

    ragdiag.diag_start(pet, "harness standing spawn, kick=False")
    skel = T.add_skeleton(world, spec, pet.rag_owner, (0.0, 0.0, 0.0))
    ragdiag.diag_pm_ready(skel, pet)

    # rag-trace, which is where the per-frame lines come from
    world.trace(frames)

    fps = 60.0
    total = int(14 * fps)
    rest = 0.0
    rest_at = None
    got_up = None
    peak = 0.0
    for f in range(total):
        world.step(1.0 / fps)
        sp = skel.speed()
        peak = max(peak, sp)
        if skel.touching() and sp < ragphys.RAGP_REST_SPEED:
            rest += 1.0 / fps
            if rest > ragphys.RAGP_REST_TIME and rest_at is None:
                rest_at = (f + 1) / fps
                ragdiag.diag_getup(pet.rag_owner, "auto", rest)
        else:
            rest = 0.0
        # Every frame, so the harness exercises the same dedup path the app does.
        ragdiag.diag_tick(pet.rag_owner, f, sp, ragphys.RAGP_REST_SPEED,
                          skel.touching(), rest, ragphys.RAGP_REST_TIME,
                          False, True)

    print()
    ragdiag.diag_verdict(pet.rag_owner, skel, got_up, rest_at, peak, total)
    print(f"\n(name={name} seed={seed} expected get-up "
          f"{'at %.1fs' % rest_at if rest_at else 'NEVER'})")


if __name__ == "__main__":
    main()
