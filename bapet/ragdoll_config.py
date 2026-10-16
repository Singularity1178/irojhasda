"""Ragdoll tunables (rest time, edge slam, centre of mass) and the limb spring table."""
from __future__ import annotations



# ------------------------------------------------------------------- ragdoll
# Three engines, chosen per pet by cfg["ragdoll_engine"]:
#
#   "3d" - the fully 3D ragdoll in ragphys3d.py (pure Python, always available).
#      The world gets a thin slab of depth. Nobody moves in it on her feet; once
#      limp, her pelvis, head and limbs can fall into it (toppling toward or away
#      from you, landing on her back / front / side, a leg crossing in front of
#      the other), and getting up puts her back in the middle of it. Joints have
#      anatomical limits (knees and elbows only fold one way), muscle tone fades
#      as she goes down, and only hard hits bounce. Every physics tunable is in
#      the RAG3_* block there; the two below are the Pet side. She maps back onto
#      the rig with one FULL 3x3 post rotation per body (see pet_rag3d.py).
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
RAG3_GETUP_TIME = 0.9      # s, 3D engine: blend from lying (any 3D orientation) back to standing
RAG3_HEAD_R = 80.0         # percentile of head-vertex distances from their centre used as her skull radius
RAG3_PERSPECTIVE = 0.0     # 0..1 share of the camera's true size change for her depth (0 = matches the
                           # physics exactly; 1 = nearer looks bigger but feet can dip into the floor)
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
# ---- the window a limp student gets ------------------------------------------
# A body on the floor is wider and taller than the standing pose its window was
# sized for, so a tumbling limb or a flung arm used to be cut off by the edge of
# her own frame. Her window is multiplied by this the moment she goes limp (and
# by 1.0 again the moment she is back on her feet).
#
# A multiplier, not a size: the models differ by a factor of a few, so what she
# needs is room AROUND her, and a ratio carries over whatever window she already
# has (profile scale, --scale, a ride window). It is only extra room - the camera
# inside the window widens by the same factor (Renderer.set_fit), so she is drawn
# at exactly the same size in exactly the same place and the physics, which all
# measures real screen px, does not see a different character. 1.0 turns it off.
#
# Physics page -> Ragdoll -> "Limp window", cfg `ragdoll_window_scale`.
RAG_WINDOW_SCALE = 1.5
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
