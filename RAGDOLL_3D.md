# Realistic 3D ragdoll (`ragdoll_engine = "3d"`)

## Turning it on
Control panel → **Physics** → **Ragdoll** → Engine → **Realistic 3D**.
Two new sliders show up while it's selected:

- **3D depth** (default 35% of her height): how far into the screen a limp body can fall.
- **Muscle tone** (default 50%): 0% means she goes limp instantly. Higher values make her sag at the knees first.

You can also set `"ragdoll_engine": "3d"` in `multi_single_screen_pet_ba_settings.json`.
The default is still `"pymunk"`. If a rig can't support the 3D engine, that pet falls back to pymunk, then to the rod, and prints one `[ragdoll3d]` line explaining why.

## What it does
- **Slight depth.** The world gets a thin slab of depth. Students never move in it while standing, walking or jumping: they stay at z = 0 exactly as before.
- **Ragdolls use the depth.** Only a limp body's pelvis, head and limbs can fall into the slab. She can topple toward or away from you, land on her back, front or side, or cross one leg in front of the other.
- **Getting up.** The get-up blends every bone's 3D rotation home and puts her back in the middle of the depth.
- **Getting shot.** The push is graded from the head down to the feet, so her upper body is driven back over planted feet and her knees fold. Part of the push goes into depth, with a twist, so she turns as she drops.
- **Screen-edge slam.** She hits the wall at full speed, crumples against it and slides down. Friction and speed-dependent bounce apply: soft contacts don't bounce, hard hits bounce a little.
- **Fainting (Ctrl+1 or the menu).** Muscle tone fades over about 0.4 s, so her knees buckle before she goes over. She falls forward, backward or sideways in her own frame.
- **Joint limits.** Knees and elbows are true hinges that only fold the anatomical way. Hips, shoulders and neck use swing cones with separate front/back/out/in limits. The spine's bend and twist are bounded.
- **Collisions.** She collides with the floor, walls and ceiling, the real Windows (boxes spanning the full depth), other ragdolled students (who are also 3D), and her own body (hands and knees don't pass through her torso or head).
- **Grabbing.** You can grab any limb and she hangs from it; let go to throw her.

## Engine
Position-based dynamics run at 300 Hz in small substeps, which is stable by construction.
- **Particles:** one per joint, with chibi mass and radius proportions. The skull radius is measured from each character's own head mesh.
- **Torso:** two rigid clusters (pelvis and Spine1) held together by shape matching. Their rotations drive the root and spine directly.
- **Damping:** only motion relative to her rigid-body motion is damped, so limbs settle but the body as a whole still tumbles freely.
- **Dependencies:** pure Python, with no pymunk or numpy needed.

## Mapping onto the rig
Each body gets a **full 3×3 post rotation**:
`post_i = Kᵀ (R_rootᵀ R_i R_jᵀ R_root) K`

- `j` is the nearest posted ancestor in the rig.
- `K` maps model space to the physics frame.

The root's 3D rotation goes into the model matrix about the pelvis, which is where the 2D ragdoll was already turned.

## Files
| File | |
|---|---|
| `ragphys3d.py` | **new**: the 3D physics world |
| `bapet/pet_rag3d.py` | **new**: Pet mixin: spec from the frame, posts, get-up |
| `test_ragphys3d.py` | **new**: 10 headless physics tests |
| `test_ragphys3d_map.py` | **new**: physics → rig mapping on the real Mika rig |
| `test_ragphys3d_pet.py` | **new**: full lifecycle through the real Pet mixins |
| `bapet/pet.py` `pet_ragdoll.py` `pet_rag_step.py` `pet_rag_pose.py` `pet_render.py` `pet_input.py` | engine dispatch hooks |
| `bapet/app.py` `app_settings.py` `deps.py` | the shared 3D world: created, stepped once per tick, windows synced |
| `bapet/config.py` `ui_spec.py` `ragdoll_config.py` | settings, panel rows, constants |
| `multi_single_screen_pet_ba.py` | docs only |

## Verified headless (Linux, Python 3, numpy 2)
- `test_ragphys3d.py`: all 10 tests pass.
  - A crumple settles in about 0.9–2.2 s.
  - Nothing tunnels at 5000 px/s into any edge.
  - Bodies rest on window tops, and a window opening on a body doesn't throw her.
  - Torso clusters stay rigid to 0.2 px.
  - 4 ragdolls plus 10 windows cost about 1.7 ms per frame (about 0.43 ms per ragdoll).
- `test_ragphys3d_map.py`: on Mika, every rendered joint lands within 5.2 px of its physics particle on screen and within 2.5 px in depth. This was checked for a 3/4-view shot, a front-view crumple and a near-profile slam. The remaining error is the camera's 16° perspective on limbs turned out of plane.
- `test_ragphys3d_pet.py`: shot → down → up in 4.9 s, with her feet back on the floor and no skeleton left behind.

**Not verified:** the on-screen feel on Windows. It wasn't run with a display, Qt or GL here. Tunables to try first are in the `RAG3_*` block at the top of `ragphys3d.py`.
