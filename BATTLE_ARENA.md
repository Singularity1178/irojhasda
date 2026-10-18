# Battle Arena

Startup now opens a **title screen** with two options:

* **Desktop Pets**: Student Select and the desktop pets, same as before. The back arrow in Student Select returns to the title.
* **Battle Arena**: a team builder that uses avatar cards (the baked Student Select portraits, not live 3D previews).
  * Left-click a card to add it to the highlighted team. Right-click adds it to the other team. Click a team header to make it the active one.
  * Random / Balance / Clear buttons.
  * Gear button opens the arena settings.
  * **BEGIN BATTLE** starts the match.

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
