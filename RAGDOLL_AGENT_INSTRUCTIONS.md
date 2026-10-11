# Task: replace the rod ragdoll with an articulated 2D pymunk ragdoll
# By Claude
Target file: `multi_single_screen_pet_ba.py`. The physics goes in a new module, `ragphys.py`, next to it.

## 0. Scope

**In scope:**
- The physics world, skeletons, joints and environment colliders.
- Mapping physics poses onto the rig.
- Mouse grabbing, shoving, impact events, and the get-up blend.
- Headless tests.

**Out of scope. Do not touch these:**
- Pet window size or clipping of limbs outside the 380×520 window.
- The render loop rate.
- `WinTracker` polling or logic.
- Dialogue, UI panel layout, and the shader.
- Making OS windows move.

Where an out-of-scope problem blocks you, work around it and leave a `# TODO(later):` comment.

## 1. Understand the existing code first

Read these before writing anything. Quote what you rely on in your final report.

- **Constants and legacy ragdoll:** `RAG_*` constants (line ~183) and the `Pet` ragdoll methods: `rag_resolve`, `rag_freeze_pose`, `rag_geom`, `start_ragdoll`, `rag_shove`, `rag_getup`, `rag_end`, `rag_ground`, `ragdoll_step`, `rag_accel`, `rag_drag_step`, `rag_limb_post`, `rag_clear`.
- **Per-frame flow:** `Pet.tick`, `Pet.render_frame` (note `M = translate(p) @ rot_z4(self.roll - self.rg_a) @ translate(-p) @ B`), and `Pet.procedural`. `procedural` keeps `roll`, `pitch_hold` and hold-springs consistent with `self.vx` and `self.vy`.
- **Mouse:** `mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`.
- **`Rig.evaluate`:** it applies `rag_post`, a list of `(bone_index, 3x3 rotation)`.
- **`Model.pose_world(T, Q, S, post)`:**
  - Each post rotation is applied about that bone's own world position, and it is applied level by level down the hierarchy.
  - A child therefore inherits its ancestors' post rotations.
  - All ragdoll rotations are about one axis, so they add.
  - Consequence: the post angle for a bone is its angle relative to its nearest physics-body ancestor, not its absolute angle.
- **App and environment:** `App.tick`, `App.floor_y`, `App.surfaces`, `App.resolve_screen`, `WinTracker.wins`. `wins` is a list of `(hwnd, l, t, r, b)` in logical px, ordered front to back, with the app's own windows excluded.
- **Bone names:** run `python multi_single_screen_pet_ba.py --dump` on `Mika.glb`. The model's main skin has 141 joints. Record the real names of the pelvis, spine, chest, neck, head, clavicle, upperarm, forearm, hand, thigh, calf and foot bones. Reuse the `find()` matching from `rag_resolve`, which does an exact token match and skips "Twist" bones.

## 2. Dependency and fallback

- Add `pymunk` to the install line and the `ImportError` message. Pin `pymunk>=6.6,<7`.
  - If a newer version is installed, use that version's collision-handler API.
  - pymunk 7 renamed the handler API, so check the installed docs rather than guessing.
- Add cfg key `ragdoll_engine` to `DEFAULTS`, with values `"pymunk"` (default) or `"legacy"`.
- Keep all legacy rod code working under `"legacy"`.
- If pymunk fails to import, or a character's skeleton can't be built (see §5), fall back to legacy for that pet and print one `[ragdoll]` line saying why.

## 3. Module layout (`ragphys.py`, no Qt or GL imports)

```
class RagWorld:           # one per App, shared by all pets
    def __init__(self)
    def set_screen(self, rect)                      # (left, top, right, bottom) logical px; rebuild the 4 wall segments
    def sync_windows(self, wins, now, enabled)      # called when tracker.wins changed
    def add_skeleton(self, owner_id, spec, kick) -> RagSkeleton
    def remove_skeleton(self, skel)
    def step(self, dt)                              # fixed-substep accumulator
    def pop_impacts(self, owner_id) -> list[Impact]
class RagSkeleton:
    def pose(self) -> dict      # pelvis (x, y, angle), per-bone phi, velocities
    def lowest_point(self) -> float
    def speed(self) -> float    # max body speed, for rest detection
    def grab(self, point, target) / move_grab(target) / release_grab()
    def impulse(self, point, impulse, body=None)
    def freeze(self)            # remove from space, keep the pose for the get-up blend
class Impact: namedtuple(owner, kind, strength, point)    # kind: "screen" | "window" | "pet"
```

Coordinates are logical screen px with y down, the same as Qt and the existing code. Gravity is `(0, +G)` with `G = 2600 * max(0.6, scale)`, the same as `Pet.G`. Use one global G taken from the first pet's scale, or per-body force if scales differ.

## 4. World and solver settings (put them in a `RAGP_*` constant block)

- **Substep:** fixed `h = 1/240`. On each `step(dt)`, add dt to an accumulator and run at most 8 substeps. If more are owed, discard the excess.
- **Solver:** `space.iterations = 30`. Set `collision_slop` to about 0.5 px.
- **Damping:** `space.damping = 0.99`, plus a per-body `velocity_func` that clamps linear speed to 6000 px/s and angular speed to 40 rad/s. Check for NaN or inf in the same place.
- **Sleeping:** none. Rest detection is done manually (§9).
- **Collision types:** `CT_BODY=1`, `CT_SCREEN=2`, `CT_WINDOW=3`.
- **Collision filter:** use `ShapeFilter(group=owner_id+1)` on all of one character's shapes, so a character never collides with itself. Different characters collide with each other.
- **Materials:** pymunk multiplies the two shapes' values.
  - Character shapes: friction 0.9, elasticity 0.5.
  - Screen walls and windows: friction 0.9, elasticity 0.7.
  - The product is about 0.81 friction and 0.35 restitution, matching `RAG_REST_E`.
  - Tune later via named constants.

## 5. Skeleton construction (`spec` built by Pet at ragdoll start)

Build at `start_ragdoll()` from the current frame, not once at startup. That way yaw, `yaw_offset` and scale are always baked in.

1. **Pose:** use the limp base pose, `rag_freeze_pose()`'s last frame of the `pickup` clip.
2. **Projection:** for each needed bone, take the world position from `rig.world_base` and project it with the same maths as `rag_limb_post`. Use `Mn @ pos` with `Mn = last_M` and `wpp = R.world_per_px * dpr`, or use `R.project(...)` converted by `x * W / w` the way `head_px` does. Pick one, and prove it with a test that the projected head and feet land where the rendered character's head and feet are. The result is each joint's screen position in px (y down, window-local, then add `px, py`).
3. **Bodies:** one capsule per link, built with `pymunk.Segment`. The body's origin is the proximal joint. The segment runs from `(0,0)` to the child joint in local space. Set `body.angle` to the rest direction, `atan2(dy, dx)` in y-down screen coordinates, so local +x runs along the limb. Store `rest_angle` per body.

| Body | Origin bone → end bone | Radius (× ch) | Mass weight |
|---|---|---|---|
| pelvis (root) | pelvis → chest | 0.045 | 0.20 |
| chest | chest → neck | 0.050 | 0.30 |
| head | neck → head, plus a circle | 0.060 | 0.07 |
| upperarm L/R | upperarm → forearm | 0.018 | 0.03 |
| forearm L/R | forearm → hand | 0.016 | 0.025 |
| thigh L/R | thigh → calf | 0.028 | 0.09 |
| calf L/R | calf → foot | 0.022 | 0.06 |

Notes on the table:
- `ch = H * Renderer.FRAC`. Hands and feet ride on their parent's body; no separate body.
- For the head, use `pymunk.Circle` centred a little past the head bone along the neck→head direction. Compute the moment with `moment_for_circle` or `moment_for_segment`.
- Normalise masses so the total is 1.0. Compute each moment with `pymunk.moment_for_segment`.
- If the model has no distinct chest bone, make the torso one body (pelvis → neck).
- If the pelvis, thighs or head can't be found, or fewer than 6 bodies result, return `None` and fall back to legacy.

4. **Joints:** for each link (child body c, parent body p):
   - `PivotJoint(p, c, p.world_to_local(child_origin_world), (0, 0))`. This keeps the joint exactly at the child's origin.
   - `RotaryLimitJoint(p, c, min, max)`. Use symmetric limits with the `lim` values from `RAG_LIMBS` (shoulder 2.4, elbow 1.6, hip 1.5, knee 1.2, neck 0.7).
   - Add equivalent values for new links: spine and chest about 0.5, chest→head about 0.8. This is a front-facing 2D simulation, so anatomical bend direction does not apply.
   - Note that `RotaryLimitJoint` limits relative angle, so subtract rest angles by passing limits as `(rest_c - rest_p) ± lim`.
   - `DampedRotarySpring(p, c, rest_angle=(rest_c - rest_p), stiffness=k*I_c, damping=c*I_c)`. Reuse the `k` and `damp` columns of `RAG_LIMBS`, where `I_c` is the child's moment. Add similar values for the torso (about 8 / 9). Keep these in the constants block so they can be tuned.

5. **Initial state:** every body gets the pet's current `vx, vy` and the legacy random kick (`rg_vx` and `rg_vy` equivalents), applied as velocity on all bodies. The angular velocity is `random.choice([-1, 1]) * uniform(4, 10)` on the pelvis only. Never start the pelvis exactly aligned with gravity. Jitter the initial angles slightly.

## 6. Environment colliders

**Screen barrier:** four static `Segment`s forming a box around `A.resolve_screen()` (the `availableGeometry`, which is already the taskbar-free area).
- Place them 60 px outside each edge, with radius 60, so the inner face sits exactly at the edge. This prevents tunnelling.
- The floor face is at `floor_y()`.
- Rebuild them if the home screen rect changes.
- Walls are solid from both sides, but nothing should ever be outside.

**Windows:** one kinematic body per hwnd in `tracker.wins`, each with a `Poly.create_box` of the full rect.
- Keep a dict `hwnd -> (body, shape, rect)`.
- Only build them when `cfg["perch"]` and `tracker.enabled`. Otherwise remove them all.
- Add and remove them by diffing against the new `wins` list.
- Moves:
  - A window that moved by less than 600 px since the last poll is interpolated. Set `body.velocity = (target - pos) / max(poll_dt, 1/60)` and let it travel for `poll_dt`, then snap and zero the velocity.
  - Larger jumps, or any resize (rebuild the shape), snap with zero velocity.
  - Cap window velocity at 4000 px/s.
- Windows are solid on all four sides. This is deliberate, so hitting a window's side or underside deflects the pet.
- Ignore-until-clear (so a window opening on top of a lying pet doesn't catapult it out):
  - If a character's body overlaps a window shape at the moment the window is created or moved, add `(shape_id, window_id)` to an ignore set.
  - Return False from the pre-solve handler for ignored pairs.
  - Remove the pair when the separation callback fires or a point query says no overlap.
  - Same for a ragdoll starting while inside a window.
  - Implement with `pre_solve` / `separate` handlers, or by toggling a sensor flag.
- Skip any window whose rect is entirely outside the screen rect.

**Other pets:** a ragdolled pet's shapes collide with other ragdolled pets' shapes automatically, because they are in the same space.

## 7. Impact events

In a `post_solve` handler (or the equivalent in your pymunk version), read `arbiter.total_impulse` and `arbiter.contact_point_set`. Compute `strength = |impulse| / (mass * 1000)`, normalised so a fall from a standing height is about 1.0, with the same mapping as the legacy `impact > 700*s`. Record `Impact(owner_id, kind, strength, point)` per owner, and keep only the strongest one per kind per frame.

`pop_impacts()` is read by Pet to drive:
- `self.sq = min(0.26, ...)` (the squash)
- `self.emit("puff", ...)`, at most one every 0.25 s per pet, as the legacy `rag_hit_t` does
- a call to `self.A.play_rag_sound()` on strong hits only (strength > 2.0), if it's already a method on App

No new dialogue events.

## 8. Mapping physics to the rig (this must be exact)

Per frame, `Pet.ragdoll_step` should:

1. Read `skel.pose()`.
2. **Window position:** keep the model's rotation pivot (the pelvis, as in `render_frame`) at the pelvis body's position. Measure `pelvis_drop`, the pelvis-to-feet distance in window px, from the base pose when building. Then `set_feet(pelvis.x, pelvis.y + pelvis_drop)`. The old `rag_com` / `rag_geom` code is not used on this path.
3. **Pelvis angle:** set `self.rg_a` to the pelvis angle delta, `phi_pelvis = body.angle - rest_angle`, with the sign convention below. `render_frame`'s existing `rot_z4(self.roll - self.rg_a)` about the pelvis then rotates the whole model. Keep `roll` at 0 while ragdolled.
4. **Per-bone post list (replaces `rag_limb_post`):** for each non-root body i, `post_i = -(phi_i - phi_parent_i)`, where:
   - `phi_i = wrap(body_i.angle - rest_angle_i)`, wrapped to (-π, π].
   - `parent_i` is the nearest ancestor that has a physics body (the pelvis for thighs and the chest, the chest for arms and head).
   - The bone index is the body's origin bone.
   - The rotation is `rot_axis(axis, angle)` with `axis = Mn[:3,:3].T @ [0,0,1]`, normalised, exactly as in the existing `rag_limb_post`.
   - Leave the pelvis out of the list.
   - Multiply the angle by `self.rag_strength`, to be used for the get-up blend.
5. **Sign convention:** pymunk and `atan2` in y-down screen space increase clockwise on screen. `rot_axis` about +Z (toward the viewer, y up) is counter-clockwise on screen. That is why the sign is negated above. You must prove this with a numeric test with no GL context: apply a known screen-space angle to one arm and check that the projected child bone lands where the physics says. Fix the sign and write down what you found.
6. **Legacy fields:** set `self.vx, self.vy` to the pelvis velocity so the hair, skirt and tie springs keep working. Keep `self.rag_contact`, which Pet reads. Set `self.rg_x, self.rg_y` to the pelvis position, for the old code that reads them.

Also add `skel.lowest_point()` for the get-up.

## 9. State machine

`rag_state` is `"fall"` or `"getup"`, as before.

**Rest detection:** `skel.speed() < 40 * s` and at least one body in contact for `RAG_REST_TIME` seconds (existing constants, existing `ragdoll_auto_getup` flag, existing `rag_want_up` behaviour) gives `rag_getup()`.

**Get-up:**
1. Record each body's `phi_i`, the pelvis position and the pelvis angle, then freeze the skeleton (`skel.freeze()`, which removes it from the space).
2. Over `RAG_GETUP_TIME`, smoothstep `k` from 0 to 1. Set `phi_i * (1 - k)` for every bone (including the pelvis via `rg_a`, using the shortest wrap), and ease the pelvis y to the standing height above `ground`.
3. Get `ground` from the existing `rag_ground(x, y_ref)` with `y_ref = skel.lowest_point()`.
4. At `k >= 1`, call `rag_end(surf)`.
5. While getting up, the pet isn't in the physics world, so nothing hits it. That is acceptable.

**Cleanup:** `rag_clear()` and `reset_position()` must always remove the skeleton from the world. Hiding a pet, or any exception, does the same.

**Failsafes:**
- If any pose value is non-finite, remove the skeleton, print one line, call `rag_clear()` and `reset_position()`.
- If the pelvis is outside the screen rect by more than one character height, snap the whole skeleton back inside with zero velocity.
- If total kinetic energy explodes (speed > 12000 px/s), zero the velocities.

## 10. Mouse and shoving

- **Grab:**
  - When the user starts dragging a ragdolled pet (in `mouseMoveEvent`, where `dragging` becomes True), do not set `self.px/py` or call `self.move(...)`. The physics owns the window position.
  - Find the nearest body to the press point with a `point_query_nearest` in screen coordinates. Fall back to the nearest body centre if nothing is within 60 px × scale.
  - Create a kinematic target body at the cursor and a `PivotJoint` or `DampedSpring` to the grabbed body, with a bounded `max_force`.
  - Each frame, set the target body's position and velocity to the cursor's (global logical px).
  - She hangs and swings from whichever limb was grabbed.
- **Release:** remove the joint. Do not overwrite velocities with the legacy `rg_vx`, `rg_w` throw code, because the bodies already carry the throw momentum. `mouseReleaseEvent`'s ragdoll branch only releases the grab and sets `rag_state="fall"` and `rag_rest=0`.
- **Replaces `rag_drag_step`.**
- **`rag_shove(power)`** (called by click and by the Launch action): apply an impulse at the nearest body, away from the cursor, the same direction and magnitude scale as the legacy version (`(rg_x - cur.x) * 6` clamped to ±1400 horizontally, upward 500–900 × s), plus a random spin.

## 11. App wiring

- `App.__init__`: create `self.rag_world = RagWorld()` if pymunk is available; call `set_screen` with `resolve_screen()`.
- `App.tick`: after the tracker refresh and before the per-pet `p.tick(dt)` loop, do:
  - `rag_world.sync_windows(self.tracker.wins, now, self.cfg["perch"] and self.tracker.enabled)`, only when the list changed;
  - `rag_world.step(dt)` once per app tick, not per pet.
- Handle a changed screen setting by calling `set_screen` again.
- `Pet.start_ragdoll`: if the engine is pymunk and the world exists, build the spec and `add_skeleton`. Otherwise run the legacy path unchanged.

## 12. Optional extras (do these last, each behind its own cfg flag, off by default)

- `ragdoll_on_throw`: if a release speed exceeds `ragdoll_throw_speed` (default 1800 px/s), call `start_ragdoll(kick=False)` with the release velocity instead of the normal thrown state.
- Standing, non-ragdolled pets as kinematic upright capsules in the world. An impact above a threshold calls `start_ragdoll(kick=False)` on that pet with the hit velocity.

## 13. Tests (headless, plain `python`, no Qt or GL)

Write `test_ragphys.py` with a synthetic 11-body spec. Tests must pass without a display.

1. A ragdoll dropped from 1500 px onto the floor settles. Every body stays inside the screen rect, and speed falls below the rest threshold within 6 s.
2. Fired at 5000 px/s at each of the four screen edges, no body ever leaves the rect (no tunnelling).
3. A static window box: a body thrown at its side, underside and top is deflected by each, and rests on the top.
4. A kinematic window moving at 3000 px/s into a lying skeleton pushes it and imparts velocity, and nothing explodes: no non-finite values and no speed above the clamp.
5. A window created on top of a lying skeleton does not eject it (the ignore-until-clear logic).
6. Two skeletons collide with each other but never with themselves, and neither pair's limbs cross the joints' limits. Check relative angle limits stay within tolerance after a hard impact.
7. Mapping test (§8.5): the sign of the post angle, and that bone positions after applying `post_i` match the physics body ends within 2 px. Do it with the real `Model` for `Mika.glb` if you can import it without GL, otherwise with a small synthetic skeleton, and say which.
8. Get-up blend: at `k = 0` the pose equals the frozen ragdoll pose and at `k = 1` all `phi` are 0.
9. A determinism and performance check: 4 skeletons plus 10 windows run at under 1 ms per 1/60 s of simulated time.

Also add a `--rag-debug` flag that draws capsules, joints and window colliders in `Pet.paintEvent` over the render. This is off by default.

## 14. Deliverables and reporting

- Modified `multi_single_screen_pet_ba.py`, new `ragphys.py`, and `test_ragphys.py`. Do not reformat unrelated code.
- Put every tunable in one `RAGP_*` block with a one-line comment per value.
- In your final report, state what you verified by running it and what you couldn't verify. You cannot see the app on screen, so say plainly that the visual feel is untested on Windows. List the sign-convention result from §8.5, the pymunk version used, and the bone names you matched for `Mika.glb`.