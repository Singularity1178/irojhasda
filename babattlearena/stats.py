"""Per-student combat profile for the arena, from combat_index.json (via bapet.combat_data).

Everything is expressed in student heights ("ch") so the fight plays the same at any
student size. combat_index.json gives each model a role, a row, a weapon type, a firing range
(cm), bullets per attack and a magazine; anything missing falls back to sensible defaults.
"""
from __future__ import annotations

from pathlib import Path

from bapet.combat_data import load_combat_index
from .tank import TANK, TANK_EX_NAME, has_tank

# per weapon: damage per bullet, seconds between bullets, bullets per burst, pause between bursts,
# aim spread (rad, 1 sigma), reload (s), pellets, projectile kind, move speed factor, range factor
WEAPONS = {
    "Handgun":          dict(dmg=(380, 620), rof=0.34, burst=2, gap=0.55, spread=0.050, reload=1.3, mag=10,
                             move=1.05, rng=1.0),
    "Submachine Gun":   dict(dmg=(240, 400), rof=0.085, burst=5, gap=0.55, spread=0.075, reload=1.6, mag=30,
                             move=1.10, rng=0.9),
    "Assault Rifle":    dict(dmg=(420, 680), rof=0.13, burst=3, gap=0.6, spread=0.042, reload=1.8, mag=24,
                             move=1.0, rng=1.0),
    "Machine Gun":      dict(dmg=(260, 440), rof=0.075, burst=7, gap=0.75, spread=0.072, reload=2.8, mag=60,
                             move=0.86, rng=1.0),
    "Shotgun":          dict(dmg=(190, 300), rof=0.85, burst=1, gap=0.15, spread=0.15, reload=2.0, mag=6,
                             pellets=7, move=1.08, rng=0.75),
    "Sniper Rifle":     dict(dmg=(2300, 3500), rof=1.9, burst=1, gap=0.4, spread=0.010, reload=2.4, mag=5,
                             aim=0.55, move=0.92, rng=1.75, beam=True),
    "Railgun":          dict(dmg=(2300, 3500), rof=3.0, burst=1, gap=0.4, spread=0.012, reload=2.8, mag=10,
                             aim=0.8, move=0.9, rng=1.6, beam=True, pierce=True),
    "Grenade Launcher": dict(dmg=(1500, 2300), rof=1.6, burst=1, gap=0.5, spread=0.08, reload=2.6, mag=6,
                             proj="grenade", move=0.95, rng=1.0, radius=1.05),
    "Rocket Launcher":  dict(dmg=(2000, 2900), rof=2.3, burst=1, gap=0.5, spread=0.05, reload=3.0, mag=4,
                             proj="rocket", move=0.9, rng=1.15, radius=1.15),
    "Mortar":           dict(dmg=(1800, 2700), rof=2.4, burst=1, gap=0.5, spread=0.10, reload=3.0, mag=4,
                             proj="mortar", move=0.88, rng=1.5, radius=1.2),
    "Flamethrower":     dict(dmg=(160, 260), rof=0.07, burst=12, gap=0.5, spread=0.20, reload=2.5, mag=80,
                             move=0.95, rng=0.45, flame=True),
}
DEFAULT_WEAPON = "Assault Rifle"

ROLE_HP = {"Tank": 1.6, "Attacker": 1.0, "Support": 1.1, "Healer": 1.0, "Tactical Support": 1.1}
ROLE_DEF = {"Tank": 0.78}                     # damage taken multiplier
POS_RANGE = {"Front": 0.85, "Middle": 1.0, "Back": 1.2}
BASE_HP = 4200.0
BASE_SPEED = 1.75                              # student heights per second when running
EX_NAMES = {
    "grenade": ("Frag Grenade", "\u624b\u69b4\u5f3e"),
    "pierce": ("Piercing Shot", "\u8cab\u901a\u5c04\u6483"),
    "barrage": ("Suppressive Barrage", "\u5236\u5727\u5c04\u6483"),
    "charge": ("Breach & Clear", "\u7a81\u5165"),
    "shield": ("Iron Wall", "\u9244\u58c1\u306e\u5b88\u308a"),
    "mass_heal": ("Field Medic", "\u5168\u4f53\u56de\u5fa9"),
    "buff": ("Tactical Command", "\u6226\u8853\u6307\u63ee"),
    "strike": ("Artillery Strike", "\u7832\u6483\u652f\u63f4"),
    "tank": TANK_EX_NAME,
}


def _entry(path):
    idx = load_combat_index()
    return idx.get(Path(path).name.lower()) or {}


class CombatProfile:
    def __init__(self, ch):
        e = _entry(getattr(ch, "path", ch.name + ".glb"))
        self.role = e.get("role") or "Attacker"
        self.position = e.get("position") or "Middle"
        self.combat_class = e.get("combat_class") or "Striker"
        self.weapon = e.get("weapon_type") if e.get("weapon_type") in WEAPONS else DEFAULT_WEAPON
        self.attacks = bool(e.get("attacks", True))
        w = dict(WEAPONS[self.weapon])
        self.w = w
        fr = float(e.get("firing_range") or 650.0)
        # firing range (cm) -> student heights. 650 cm (an AR) is about 4.6 heights.
        self.range = max(2.4, fr / 650.0 * 4.6 * w.get("rng", 1.0))
        if not self.attacks:                      # healers / supports: range is how far they reach allies
            self.range = min(self.range, 5.0)
        self.pref = self.range * 0.78 * POS_RANGE.get(self.position, 1.0)    # where she likes to stand
        self.pref = min(self.pref, self.range * 0.92)
        apa = int(e.get("ammo_per_attack") or 0)
        mag = int(e.get("ammo_to_reload") or 0)
        self.burst = max(1, apa if apa > 0 else w["burst"])
        if w.get("pellets"): self.burst = 1
        self.mag = mag if mag > 0 else w["mag"]
        self.dmg = w["dmg"]
        self.rof = w["rof"]
        self.gap = w["gap"]
        self.spread = w["spread"]
        self.reload = w["reload"]
        self.pellets = int(w.get("pellets", 1))
        self.proj = w.get("proj")
        self.beam = bool(w.get("beam"))
        self.pierce = bool(w.get("pierce"))
        self.flame = bool(w.get("flame"))
        self.aim_time = float(w.get("aim", 0.12))
        self.radius = float(w.get("radius", 1.0))
        self.hp = BASE_HP * ROLE_HP.get(self.role, 1.0)
        self.defense = ROLE_DEF.get(self.role, 1.0)
        self.speed = BASE_SPEED * w.get("move", 1.0) * (0.92 if self.role == "Tank" else 1.0)
        self.healer = self.role == "Healer"
        self.support = (not self.attacks) and not self.healer
        self.dmg_mul = 1.0 if self.attacks else 0.35      # non-attackers only have a sidearm
        self.heal = 950.0 if self.healer else 0.0
        self.heal_cd = 1.5
        self.has_tank = has_tank(ch)
        self.ex = self._ex_kind()
        self.ex_cost = {"grenade": 14.0, "pierce": 16.0, "barrage": 16.0, "charge": 14.0, "shield": 15.0,
                        "mass_heal": 17.0, "buff": 16.0, "strike": 18.0, "tank": TANK["ex_cost"]}[self.ex]
        # how fast her normal fire breaks a prop, in HP/s (deliberate breaching, see ai.Brain.breach_score)
        self.box_dps = (sum(self.dmg) / 2.0) * self.pellets * self.burst * self.dmg_mul / max(0.2, self.rof * self.burst + self.gap)

    def _ex_kind(self):
        if self.has_tank: return "tank"            # Iroha: she summons and drives her tank
        if self.healer: return "mass_heal"
        if self.role == "Tank": return "shield"
        if self.support: return "buff"
        if self.role == "Tactical Support": return "strike"
        if self.weapon in ("Sniper Rifle", "Railgun"): return "pierce"
        if self.weapon == "Machine Gun": return "barrage"
        if self.weapon == "Shotgun": return "charge"
        if self.role == "Support": return "buff"
        return "grenade"

    @property
    def ex_name(self):
        return EX_NAMES[self.ex]

    def short(self):
        return {"Submachine Gun": "SMG", "Assault Rifle": "AR", "Machine Gun": "MG", "Handgun": "HG",
                "Shotgun": "SG", "Sniper Rifle": "SR", "Railgun": "RG", "Grenade Launcher": "GL",
                "Rocket Launcher": "RL", "Mortar": "MT", "Flamethrower": "FT"}.get(self.weapon, "AR")
