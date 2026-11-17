# Campaign: Operation Kivotos Gauntlet

A roguelite built on the Battle Arena. The title screen has a third card, **Campaign** (also `run_campaign.bat`, `--campaign`, and *Campaign…* in the tray menu).

You lead a small squad through **3 areas x 4 rooms**; the fourth room of every area is its boss. Between rooms you pick a door, after a room you take its reward, and when the squad is wiped the run is over. What you earned stays, you spend it at **Sora's shop**, and the next run starts stronger.

## The loop

1. **Hub.** Pick a leader and her allies from the roster, pack supplies, choose manual control or autopilot, press **SORTIE**. Everyone you did *not* pick is the opposition: every enemy is one of the students' own `.glb` models, drawn by the same renderer and ragdolled by the same physics as in the arena.
2. **Doors.** Each door shows what the room pays and who is waiting inside.
   * *Academy Support* (blue): choose 1 of 3 supports. The first room always offers these.
   * *Credit Cache*, *Pyroxene*, *Supply Crate*, *Medical Tent*, *Halo Fragment* (+1 life).
   * **Elite** doors add an elite guard (more HP, more damage, a little bigger) and double or upgrade the reward.
   * *Sora's Field Stall* and *Café Break* are rooms without a fight: spend Credits on a meal, a support, supplies or a life; or rest for +45% HP and get retired students back.
   * The last door of an area is the **boss**: a named student with several HP bars (one per life), a faster EX gauge and an escort.
3. **The room** is a Battle Arena match with uneven sides (see below).
4. **Reward**, then the next doors. HP and lives carry over; a little HP comes back between rooms.
5. **Result.** Squad wiped, run abandoned, or the third boss down. Clearing the campaign unlocks the next **threat level** (tougher enemies, more Pyroxene), up to 3.

## Playing a room

The room uses your arena settings for student size, fps, HP bars, damage numbers, obstacle amount, barrels and desktop windows as cover. Lives, damage, layout and AI level are set by the campaign (rookie in area 1, veteran in area 2, elite in area 3).

With **manual control** on you drive the leader yourself; everybody else, friend and foe, keeps her own tactical brain.

| Input | Action |
| --- | --- |
| WASD / arrows | move |
| LMB (hold) | fire at the cursor. It snaps to an enemy under the cursor, otherwise she shoots at that spot on the floor. A healer heals a hurt ally under the cursor. |
| RMB, Q or E | EX skill, aimed at the cursor (grenade / strike land there, a barrage picks the enemy nearest to it, Iroha's tank is driven by her own brain) |
| Space, Shift or MMB | dash: a short burst with a moment of invulnerability, 1.8 s cooldown |
| R | reload (she also reloads by herself when the magazine runs dry) |
| 1 - 4 | use the supply in that slot |
| Tab | take control of the next squad member |
| T | manual / autopilot |
| Esc | pause (Resume / Abandon Run / Title Screen) |

While you are in control an invisible full-screen window takes the keyboard and mouse, so clicks do not land on your desktop. Switch to autopilot (T, or the MANUAL / AUTO button on the top bar) and the desktop is yours again: move windows around and the students use them as cover, as in the arena. The supply buttons on the top bar work in both modes.

If the student you control is retired, control moves to the next one who is still standing.

## Currencies

* **Credits**: every retired enemy drops some (elites and bosses more), plus Credit Cache doors and boss bounties. They buy supplies, the stall's offers, and the Bigger Pockets unlock.
* **Pyroxene**: a little for every cleared room, more from elite guards, Pyroxene doors and bosses (15 / 25 / 45), and 30 for clearing the campaign. It buys the permanent upgrades.

Both are banked the moment they drop. A failed or abandoned run keeps everything it earned.

## Sora's shop

The shop icon on the title screen and the **Sora's Shop** button in the campaign open the same shop. Its first three tabs are the campaign's, and the wallet in its top bar is the campaign wallet. Hover a card to read what it does; Sora says thank you when you buy.

**Training** (permanent, Pyroxene, several ranks each)

| Upgrade | Per rank | Ranks |
| --- | --- | --- |
| Physical Training | +8% max HP | 5 |
| Live-Fire Drills | +6% damage | 5 |
| Ballistic Vest | -4% damage taken | 5 |
| Marksmanship | +3% critical chance | 4 |
| EX Tuning | +10% EX charge | 4 |
| Footwork | -12% dash cooldown | 3 |
| Field Rations | +5% HP healed between rooms (base 20%) | 3 |
| Accounting Class | +10% Credits | 5 |

**Unlocks** (permanent)

| Unlock | Effect | Ranks |
| --- | --- | --- |
| Halo Resilience | +1 life for every squad member (base 2) | 2 |
| Squad Slot | +1 ally (base: the leader and 1 ally) | 2 |
| Bigger Pockets | +1 supply slot (base 2), paid in Credits | 2 |
| Tactical Rethink | +1 re-roll of the offered supports per run | 3 |
| Head Start | begin every run with a random support | 1 |
| Sora's Connections | Rare and Epic supports show up more often | 3 |

**Supplies** (consumables, Credits, up to 9 of each in stock). Pack one kind per slot in the hub; using one takes it from your stock.

| Supply | Effect |
| --- | --- |
| First Aid Kit | heals the student you control (or whoever is hurt most) for 50% HP |
| Team Rations | heals every standing squad member for 25% HP |
| Frag Grenade | a grenade at the cursor |
| Flashbang | stuns the enemies near the cursor for 2.5 s (bosses 1 s) |
| Energy Drink | fills the EX gauge of the student you control |
| Barrier Generator | the squad takes 70% less damage for 6 s |
| Artillery Beacon | six shells around the cursor |
| Revive Ticket | a retired squad member gets up with one life and half her HP |

On autopilot the aimed supplies go to the enemy nearest the leader. A supply that would do nothing (full HP, nobody to revive) is not spent.

If QtWebEngine is not installed the animated shop cannot open. The campaign's shop button then opens a plain counter inside the campaign window with the same stock and prices.

## Supports

Nineteen supports from six academies, each in Common / Rare / Epic strength. They last until the run ends and the same one can be taken again (multipliers multiply, additions add).

* **Abydos**: Desert Grit (max HP), Oasis Break (healing between rooms), Sand Wall (a barrier at the start of every fight)
* **Gehenna**: Prefect's Fury (damage), Havoc (explosion damage), Pandemonium (critical chance)
* **Trinity**: Tea Party's Grace (regeneration), Justice Task Force (damage to elites and bosses), Sister's Prayer (+1 life for everyone standing; always Epic)
* **Millennium**: Overclock (rate of fire), Extended Mags, Quick Hands (reload), Seminar Budget (Credits)
* **Hyakkiyako**: Festival Step (move speed), Shinobi Blink (dash cooldown), Fox Fire (retiring an enemy heals the squad)
* **SRT**: Rabbit Drills (EX charge), Plate Carrier (damage taken), Breaching Charge (your dash sets off a blast)

## Files

| File | What it is |
| --- | --- |
| `babattlearena/campaign_data.py` | The rules, pure Python: save file, upgrade / supply / support tables, door and enemy generation, rewards. Everything tunable is in the tables at the top. |
| `babattlearena/campaign_battle.py` | One room: `CampaignBattle` (a `Battle`), `CampaignFighter` / `PlayerFighter`, the input pad, the campaign overlay and top bar. |
| `babattlearena/campaign.py` | The controller (`ArenaManager.campaign`) and the screens: hub, doors, reward, stall, café, result, pause, fallback counter. |
| `babattlearena/battle.py` | Three small hooks (`make_fighter`, `make_overlay`, `make_hud`) and a `campaign` argument. Arena matches are unchanged. |
| `babattlearena/effects.py` | One fix: the summon beam's colour (it raised on every frame of every match intro). |
| `babattlearena/manager.py`, `title.py` | The Campaign card, `open_campaign()`, the shop returning to wherever it was opened from, the campaign's pause menu and room results. |
| `sorashop/shop.py`, `assets/shop_ui.js`, `assets/shop_ui.css` | `GET /__campaign` and `POST /__buy`, the three campaign tabs and the real wallet. |
| `campaign_save.json` | Written at runtime next to the main script (git-ignored). Delete it to start over. |
| `test_campaign.py` | `python test_campaign.py` checks the rules with nothing installed. `--battle` also plays real rooms without a window (real models, fighters, brains and ragdolls; only the GL renderer is stubbed), drives a student from synthetic input, uses every supply and paints every screen. `--battle --runs N --ranks K` plays N whole runs on autopilot with every upgrade at rank K and prints how far each got. `--live` runs the whole flow through the real Qt event loop (still no screen): real key and mouse events on the input pad, pause, abandon, the reward and result screens. |

## Balance notes

The numbers were set with `test_campaign.py --battle --runs 8 --ranks K`: autopilot, no supplies used, always the first fight door, a squad of Shiroko and Hoshino plus whatever allies the Squad Slot ranks allow.

| Every upgrade at rank | Result of 8 runs |
| --- | --- |
| 0 | all lost, between room 2 and room 7 (6 to 30 Pyroxene each) |
| 1 | 1 clear, the rest lost between rooms 7 and 11 |
| 2 | 3 clears |
| 3 | 5 clears |
| max | 7 clears |

That is the autopilot. A player who dashes, picks doors and uses supplies has not been measured: no one has played this build by hand yet, so expect to adjust the enemy curve in `Run._enemies` and the prices in `UPGRADES` after real play.
