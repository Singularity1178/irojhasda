"""Ragdoll tunables (rest time, edge slam, centre of mass) and the limb spring table."""
from __future__ import annotations



# ------------------------------------------------------------------- ragdoll
# Two engines, chosen per pet by cfg["ragdoll_engine"]:
#
#   "pymunk" (default) - the articulated ragdoll in ragphys.py. One capsule body
#      per limb, pinned and angle-limited against its parent, colliding with the
#      screen edges, the other pets and the real Windows. Every tunable lives in
#      the RAGP_* block there. She maps back onto the rig with one `post`
#      rotation per body (see rag_limb_post).
#
#   "legacy" - the original two-layer ragdoll, kept working unchanged:
#   1. the whole body is ONE rigid rod (head end <-> foot end) in screen space.
#      Gravity, walls, ceiling and floor / window-top contacts are solved with
#      plain impulses. The rod's position moves her window; its angle rotates
#      the model about her pelvis. Tumbling, bouncing, sliding, lying flat.
#   2. every limb (and the head) is a damped pendulum - one angle and one
#      velocity driven by apparent gravity, the body's acceleration and its spin.
#      The result is fed to the rig's existing `post` rotation list.
# Hair / skirt / tie need nothing: they already ride the hold-physics springs,
# and either engine keeps self.vx / self.vy equal to the body she is lying on.
RAG_REST_TIME = 3.0        # seconds lying still before she gets up on her own

RAG_GETUP_TIME = 0.7
# ---- edge slam: a screen edge hit hard enough knocks her over ----
# She normally bounces off the sides and the ceiling (see air / walk / mouseMoveEvent),
# which is right for a pet ambling around but not for one that has been thrown across
# the desktop. Any of those clamps calls Pet.edge_slam() with the speed she arrived
# with, and past this threshold she goes limp instead of bouncing. The threshold is
# px/s at scale 1.0 and gets multiplied by her scale, like the rest of the ragdoll.
RAG_EDGE_SLAM = 2400.0     # px/s (x scale) that turns a screen edge into a knock-down
RAG_EDGE_SLAM_MAX_V = 6000.0  # px/s ceiling on that test, so one bunched batch of Qt move
                              # events cannot read as a 40000 px/s slam
RAG_EDGE_SLAM_MAX_T = 9.0  # s she stays down after an edge slam even if ragdoll_auto_getup
                           # is off or she cannot settle, so "a few seconds then up" holds
RAG_COM_FRAC = 0.5         # fallback COM height as a fraction of her pixel height
RAG_COM_PAD = 0.05         # body thickness as a fraction of the window height
RAG_REST_E, RAG_FRICTION = 0.2, 0.55   # [v2] was 0.35, 0.6; limp tissue barely bounces
# (bone, child bone, joint limit rad, return-to-pose stiffness, damping)
# The child is only used to measure the limb's on-screen direction and length.
# The damping numbers are roughly 0.6 * 2 * sqrt(gravity gain + stiffness) for each
# limb, i.e. a well-damped swing: enough to flop and whip, not enough to trampoline
# itself into the joint limits every time she hits something.
RAG_LIMBS = [
    ("l upperarm", "l forearm", 2.4, 3.0, 8.0), ("l forearm", "l hand", 1.6, 5.0, 10.0),
    ("r upperarm", "r forearm", 2.4, 3.0, 8.0), ("r forearm", "r hand", 1.6, 5.0, 10.0),
    ("l thigh", "l calf", 1.5, 6.0, 9.0),       ("l calf", "l foot", 1.2, 8.0, 9.5),
    ("r thigh", "r calf", 1.5, 6.0, 9.0),       ("r calf", "r foot", 1.2, 8.0, 9.5),
    ("neck", "head", 0.7, 10.0, 11.0),          # head lags behind the body
]
