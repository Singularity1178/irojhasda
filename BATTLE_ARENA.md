# Battle Arena

Startup now opens a **title screen** with two options:

* **Desktop Pets**: Student Select and the desktop pets, same as before. The back arrow in Student Select returns to the title.
* **Battle Arena**: a team builder that uses avatar cards (the baked Student Select portraits, not live 3D previews).
  * Left-click a card to add it to the highlighted team. Right-click adds it to the other team. Click a team header to make it the active one.
  * Random / Balance / Clear buttons.
  * Gear button opens the arena settings.
  * **BEGIN BATTLE** starts the match.

The **shop icon** in the top left corner of the title screen opens **Sora's shop** (`babattlearena/shop.py`): the Spine 3.8 lobby scene from `assets/sora_shop/` (`.skel`, `.atlas`, two pages; the `localize/` folder is not used), drawn by the Spine WebGL runtime in `assets/spine-webgl.js` inside a QtWebEngine view (full `pip install PySide6`). She plays her arrival clip then `Idle_01`; her eyes follow the cursor; hold the left button on her head to pat her (`Pat_01_M`, then `PatEnd_01`); tap her to make her talk (`Talk_01`-`07`). The round dark-blue arrow in the top left corner (or Esc) returns to the title screen. Voice lines play if the `Sora_Shop_*.wav` files are put next to the `.skel`.

`run_battle_arena.bat` (or `--arena`) goes straight to the lobby. The tray menu also has *Title Screen…* and *Battle Arena…* entries.

## The match
* The screen is the floor and the view is top-down. Students keep their real 3D models, drawn by their own toon renderer through an oblique top-down camera (`babattlearena/topdown.py`).
* Ragdolls are the real 3D ragdolls: `ragphys3d` with its axes relabelled so the desktop is the ground (`babattlearena/physics.py`). Bodies collide with props, windows and students who are still standing.
* Each student has **3 lives** (configurable). A student loses a life every time she is ragdolled (HP hits 0). She gets back up after the down time with a short invulnerability (blinking + shield ring).
* **Desktop windows are walls.** Move, open or close windows mid-fight. Students re-plan and lying bodies get shoved around.
* Optional spawned cover is mirrored for fairness: crates (breakable), sandbags (half cover), concrete barriers, explosive barrels, vending machines, containers.
* Weapon, role, row, range and magazine come from `combat_index.json`. Healers heal and supports buff.
* EX skills: grenade, piercing shot, barrage, breach, shield, mass heal, tactical command, artillery strike. Each one shows a BA cut-in.
* AI (`babattlearena/ai.py`): a team commander picks a posture (push / hold / fall back), focus fire and flankers. Each student scores cover spots, including standing allies as living shields, for protection, a firing line, preferred range, travel danger and crowding. Students then engage, take cover, advance, flank, retreat toward the healer, regroup, reload behind cover and dodge grenades.
* The HUD bar at the top has pause, speed and stop. Stop (or Esc, or the tray) opens a pause menu: Resume / Restart / Arena Menu / Title Screen.
* The results screen shows the winner banner, MVP and per-student stats, with Rematch / Arena Menu / Title Screen.

Settings are saved to `battle_arena_settings.json`.

## AI update: nobody stands around, smarter cover, breaching

* **Idle watchdog** (`ai.Brain.watchdog`). A student who has neither moved half a height, nor fired, nor reloaded, nor cast for 1.6 s becomes *restless* for 4 s: she drops her cover claim, cover scores 30%, advance gets +0.5, and she walks straight at the last known enemy (to one side, so she does not end up staring at the same crate). The usual causes were "advancing" to the spot she already stood on, and sitting at her preferred range with no line of sight.
* **Advance really advances.** In `move_to_cover("advance")` a spot that does not gain at least 0.8 heights toward the enemy (and gives no shot) is not a candidate, nor is the spot she is standing on. With nobody known at all she sweeps toward the far side of the field.
* **No cover beside the enemy.** Every spot is checked against every enemy she sees *or remembers*: a spot within 1.3 heights of an enemy with nothing between them is skipped outright, and anything within 2.2 heights (1.1 for shotguns / flamethrowers) is penalised. Spots open to visible enemies outside her top three threats lose protection too. If an enemy is already within 1.6 heights, taking cover scores a quarter and she shoots or falls back to something farther instead. Both the 0.12 s reaction loop and the think loop drop a spot an enemy has walked up to. Cover that was destroyed (or a window that closed) is forgotten immediately.
* **Breaching** (`ai.Brain.breach_score`, new tactic `breach`). When her target sits behind a breakable prop she can break within ~6.5 s with her own gun (crates, vending machines; `CombatProfile.box_dps`), or whenever an enemy stands next to a **barrel**, she aims at the prop instead (`Fighter.target_box`, `Battle.fire_box`: full damage to the prop, not the 35% of a stray round). She will not breach her own or an ally's cover, nor shoot a barrel that has an ally (or herself) in its blast. Grenade / strike EX aims get a bonus when the blast also tears up breakable cover. A student shooting into solid cover for more than 2.5 s now flanks even if the commander did not pick her.
* Students who are reloading with an empty magazine no longer wait for "safe" cover first.

## Iroha's EX: Toramaru, Deploy! (`babattlearena/tank.py`)

Iroha (any character whose profile has `ride` clips) gets a unique EX instead of the artillery strike: she **summons her tank and drives it** for 11 s. All numbers are in `tank.TANK`; the rules below are fixed.

* **Invulnerable** while riding (IMMUNE, bullets ricochet, no suppression). Her EX gauge does not charge during the ride, and starts the match capped at 15%, so the first tank comes no sooner than ~25 s and then roughly every 40 s (`ex_cost` 30 s).
* **Crush.** Anything on its feet inside the hull capsule (0.5 heights wide, 0.7 ahead/behind) while the tank is rolling is ragdolled instantly - one life, like every ragdoll - and flung (`crush_knock` 1250). Allies included. A parked tank is a wall, not a crusher.
* **Shells** (`Battle.fire_shell` / `tank_blast`). A flat, visible, dodgeable shell (6.3 heights/s, 7 heights range, 2.4 s between shots, 3 per magazine, 3.2 s reload). Where it lands, **every** student within 1.0 height is ragdolled - both teams, friendly fire regardless of the setting. Props in the blast take damage; lying bodies are shoved.
* **A taller, wider body.** The hull catches shots aimed past it (`block_r` 0.8 heights vs 0.17 for a student) and counts as 0.85 cover for whoever stands behind it, so allies have a real reason to shelter behind her.
* Crates and barrels she drives into are flattened (barrels explode - on everyone). Barriers, containers, vending machines and windows stop her. She dismounts with 0.8 s of invulnerability where she stopped.
* **Everyone knows.** Enemies never shoot the tank, hide from its shells like any heavy weapon, side-step out of its path when it is rolling toward them (`Brain.dodge` / `avoid_tanks`), and never pick a cover spot it is about to roll over. Allies use it as a living shield from *behind* (1.5 heights back), keep out of the 1.6-height cone in front of it, and - friend or foe - nobody stands inside the blast circle of whatever it is aiming at.
* **The driver** (`Brain.think_tank`). She shells the biggest cluster she can hit with no ally in the blast (checked again every 0.12 s and once more as the shell leaves the barrel); with nothing worth a shell she drives for the nearest enemy to crush her, steering around allies; in the last 1.6 s she heads back toward her team so the ride does not end in the middle of the enemy.
* HUD: an orange hull ring with a heading arrow, a TANK countdown over her head, "TANK ON THE FIELD" banner, the landing circle of every shell in flight, and a target icon over anyone breaching.

`python test_arena_ai.py` runs the brains headless (no Qt / numpy) through three scenarios and checks: no idling, no cover beside an enemy, breaching happens, students evade the tank, the tank never aims a shell onto an ally, no exceptions.
