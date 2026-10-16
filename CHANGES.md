# 3D ragdoll: physics iteration slider, bug fixes, performance

Drop these files over the repo (paths are relative to the repo root). Nothing else changes.
`multi_single_screen_pet_ba_settings.json` is intentionally not included: the new
`ragdoll_3d_iters` key is picked up from `config.DEFAULTS` (5) automatically.

## New: Physics iterations slider
Control panel -> Physics -> Ragdoll -> **Physics iterations** (shown while Engine = Realistic 3D).

* `ragdoll_3d_iters` (1..10, default 5) = solver substeps per 1/60 s. 5 = 300 Hz = exactly the old tuned behaviour.
* Applies live, even mid-fall (`Rag3DWorld.set_iterations`). Out-of-range / junk values clamp.
* Muscle tone is converted per substep (`1 - (1 - f) ** (h / h0)`), so tone feels the same at every setting.
* Low settings get 1-2 extra bone-length passes per substep (cheap) so limbs don't stretch as much.
* Status line in the panel now shows the live cost: `3D physics 0.4 ms (2 active, 5x)`.

Measured, 4 ragdolls + 10 windows, active phase (ms per 60 Hz frame):

| setting | cost | vs original |
|---|---|---|
| original (300 Hz) | 1.75 ms | 1.0x |
| 5 (300 Hz) | 1.55 ms | 1.1x faster (same output, bit for bit) |
| 4 (240 Hz) | 1.24 ms | 1.4x |
| 3 (180 Hz) | 0.99 ms | 1.8x |
| 2 (120 Hz) | 0.72 ms | 2.4x |
| 1 (60 Hz)  | 0.41 ms | 4.2x |

## New: sleeping bodies
A body that has lain still (< 25 px/s, touching) for 0.5 s is skipped by the solver until disturbed:
grab, shove, shot, a moving ragdoll reaching her, a window sliding / resizing / closing on or under her,
or the home screen changing. `touching()` stays True and `speed()` is 0 while asleep, so the Pet's
rest -> auto get-up timing is unchanged. A quiet awake body does not wake a sleeping neighbour
(otherwise two bodies lying on each other would wake each other forever).

## Bug fixes
1. **Physics walls stayed on the old monitor** (`app.py`). With `screen = "cursor"` (the default)
   `resolve_screen()` moves `App.home` to the cursor's monitor, but the physics worlds' walls were only
   set at start-up and when the *setting* changed. `snap_inside` then put a limp body on a screen the
   physics didn't know about, so she was slammed into the old walls, blew up or was dropped.
   New `App.sync_phys_screen()` runs every tick (one tuple compare) and rebuilds walls only on change.
2. **Stale window slides** (`ragphys3d.py`). `Rag3DWorld.step()` returned early while nobody was limp,
   freezing its clock. A window dragged in that time kept its velocity and old rect, and replayed the
   slide from the old position the next time someone went down. The clock now always runs and idle
   slides settle straight to their target.
3. **Depth slab ignored without a screen rect** (`ragphys3d.py`). The z clamp lived inside
   `if rect is not None`, so a world without a screen let bodies drift out of the slab forever.
4. **Tone stiffness depended on the substep rate** (`ragphys3d.py`). Fixed as above; required for the slider.
5. **Off-by-one in the pymunk failsafe** (`pet_rag_step.py`). It used `right()/bottom()` while the walls use
   `right() + 1 / bottom() + 1` (QRect is inclusive).
6. Misleading comment in `_start_motion` ("no particle starts above the ceiling" -> it caps speed).

## Performance (output unchanged)
* `_solve_cones` / `_solve_hinges`: the 3x3 rotations, `_rot_apply`, `_perp_unit` and `_move_pair` are
  written out in place. No tuple allocation, no per-hinge dict lookups (parent cluster precomputed in
  `_hinge_fast`). These two were around 30% of the step.
* `_collide_pets`: no per-pair key tuples (only built while the spawn-mute set is non-empty), and a
  per-sphere AABB reject against the other body.
* `update_velocity`: pre-solve velocities via a C-level list copy instead of a per-substep dict;
  `max(self.M)` precomputed.
* `_solve_self`: squared radii precomputed. `_solve_ranges`: no sqrt while inside the range.
* `solve_env`: bound `append`; `predict` reuses the contacts list.
* `add_skeleton`: AABB reject before the O(n^2) spawn-overlap test.
* `pet_rag3d.rag3_posts_from`: `B (R_i R_j^T) B^T` with `B = K^T R_root^T`, so 2 matmuls per bone
  instead of 4, and each rotation is converted to an array once (checked equal to 5.6e-16).
* `ragdoll_step_3d` / the pymunk failsafe use the cached `App.home` instead of calling
  `resolve_screen()` (which walks every QScreen) a second time per pet per frame.

With sleeping disabled, `test_ragphys3d.py` tests 1-10 print **identical** numbers to the original
(one `x ** 2` was deliberately kept instead of `x * x`: libm's pow differs from a multiply in about 0.1%
of cases, which would have nudged chaotic tests).

## Tests
`python test_ragphys3d.py`: 12/12 pass (the 10 originals, plus `test_11_iterations_slider` and
`test_12_sleep_and_wake`).
