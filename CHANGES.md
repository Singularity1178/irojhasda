# Perching / window colliders: the window list came back empty

## Fixed: students walked and fell straight through every window on screen

`WinTracker.refresh` could return an **empty** list, so there were no perches to
stand on and no colliders for either physics world. Two separate reasons, both
confirmed against a live desktop:

* **Ordinary windows near the top of the screen were thrown away.** The
  usability test read `t < top_limit + 60.0`, where `top_limit` is the top of the
  screen the pets are locked to. Anything with its title bar within 60 px of that
  was dropped - which is *every maximised window*, since a maximised title bar sits
  exactly at the screen top, plus any ordinary window parked high up. The rule is
  now what it was trying to say: a window is a surface only if there is screen
  **above** its title bar for a student to stand on, so the test is
  `t <= top_limit + TOP_SLACK` (`TOP_SLACK = 4`, slack for the DWM frame sitting a
  pixel proud of the title bar).

  A maximised window is therefore ignored outright - `WinTracker.keep()` rejects
  it, so it is never a perch and never a collider, exactly as if there were no
  window there. That is right twice over: a student on it would be drawn off the
  top of the screen, and a maximised window covers the whole screen, so as a
  collider it would only repeat the screen walls the physics world already has.
  **Un-maximise a window** and students can stand on it and land on it again.
* **One see-through overlay in front emptied the list.** Since the window-occlusion
  pass, *every* visible window was appended to the occluder list, including
  overlay chrome: a cursor follower or a layered always-on-top tool window sized
  to the whole desktop. Being in front, it "covered" everything, so
  `_uncovered_area` returned 0 for every real window and all of them were dropped
  as buried. Such windows are now recognised by their extended style
  (`WS_EX_TRANSPARENT`, or `WS_EX_LAYERED` + `WS_EX_TOOLWINDOW`) and dropped
  before the list is built - they are neither a perch nor an occluder. A plain
  layered application window is still solid and still occludes.

The two rules are now `WinTracker.keep()` and `WinTracker.ghost()`, so the tests
drive the same code the app does. `test_ragphys3d.py` test 13 gained the
overlay-chrome case and asserts the new top-edge rule (level with the screen ->
ignored, 120 px below -> kept); its old case A, which asserted that a maximised
window is dropped, is kept because that is still true - but now for the stated
reason. Test 14 drives the whole pipeline over a mixed desktop: an overlay, a
maximised window and an ordinary one, and checks that only the ordinary window
becomes a perch and a collider.

The 3D engine itself was never at fault: bodies already rested on window tops
correctly, and test 5's window test is unchanged.

# Combat: taking cover behind a window (Stand_* clips)

## New: Combat -> When shot at -> **Take cover behind a window** (`shoot_window_cover_chance`, default 55%)

The kneel-behind-a-student tactic now has a window version. A student with
`Stand_Attack_*` clips who starts a fight (as attacker or retaliator) may run to a
desktop window and fight from behind it, using the **Stand** clips
(`Stand_Attack_Start / Ing / End`, `Move_End_Stand` to settle) instead of the
Kneel ones.

A window counts as cover (`PetCover.window_ok`) when, seen from the ground she
stands on (the floor / taskbar, or the window top she is perched on):

* it is still visible (WinTracker list) and is not the window she stands on;
* its bottom edge is no more than `COVER_WIN_GROUND_GAP` character heights above
  her ground - it may reach down behind the taskbar / below her window top;
* the part rising above her ground is at least `COVER_WIN_MIN_H` (0.55) x her
  body height (`rag_h`), i.e. slightly taller than a student. **There is no
  upper bound** - she stands *beside* the window, not behind it, so a window
  towering over her still reads as a wall she is hugging, and a taller one
  earns its keep: a bullet is only stopped when its path really crosses the
  window rect, so more height is more intercepted rounds, not free protection.
  The lower bound is what still matters: it keeps her from treating a 40 px
  sliver (a toolbar, a thin notification window) as cover;
* it stands between her spot and her opponent, her spot is on her side of the
  opponent, inside her floor span, and (on a window top) on a visible part of it.

Examples: a terminal sitting on the taskbar; students standing on a big window
with a small window sitting on top of it next to them.

While settled behind it: shots at her use `COVER_WIN_AIM_MULT`, and a round whose
path crosses the window is stopped by it with `COVER_WIN_BLOCK` chance (spark on
the window + BLOCK). She follows the window if it is dragged, picks new cover (a
student or another window) when it is closed / covered / moved off her ground, and
steps out after `COVER_HOLD` seconds, like the student shield.

Files: `bapet/pet_cover.py`, `bapet/pet_attack.py`, `bapet/pet_combat.py`,
`bapet/combat_config.py`, `bapet/combat_data.py`, `bapet/config.py`,
`bapet/ui_spec.py`, `bapet/app_pets.py` (docstring only).

# Ragdoll: a bigger window while she is limp

## New: Physics -> Ragdoll -> **Limp window** (`ragdoll_window_scale`, default 1.5x)

A ragdolled body is wider than the standing pose its window was sized for, so a
tumbling limb or a flung arm was clipped by the edge of her own frame. Her window
is now multiplied by this factor for as long as she is limp, and by 1.0 again the
moment she is back on her feet.

It is a **multiplier**, not a size, on purpose: the models differ by a factor of a
few, so what she needs is room *around* her, and a ratio carries over whatever
window she already has (profile `window_scale`, `--scale`, a ride window).

Nothing about her changes size:

* The window keeps its feet line, so the extra room goes entirely above and to
  either side of her (`PetWindow.rag_window` reads `feet_pos()` before it touches
  `W`/`H` and puts them back after).
* The camera inside the window widens by the same factor (`Renderer.set_fit(fit,
  scale)`): view height, camera distance and near/far planes all scale, which
  leaves `world_per_px` untouched. Same pixels per world unit means she is drawn
  at exactly the same size in exactly the same place, and the outline width
  (`outline_px * world_per_px`) does not change either.
* Sizes read off the window (`char_h`, `rag_h`, the rod's body thickness, the
  screen-edge margin) go through `stand_w()` / `stand_h()`, which divide the limp
  factor back out - they measure her, not the frame. The capsule radii, COM,
  pelvis drop and camera mapping the physics builds are therefore bit-identical
  to before; the skeleton is still built from the frame on screen right now.

Applies live: whoever is limp right now takes the new size, feet unmoved
(`AppSettings.set`). `1.00x` turns it off and restores the old behaviour exactly.

Cost: her GL buffer and MSAA renderbuffers are `(1.5x)^2 = 2.25x` the pixels
while she is down, so several students limp at once is more fill. Lower the
slider if that shows.

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
