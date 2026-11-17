"""Campaign rules and data: the roguelite layer on top of the Battle Arena. Pure Python (no Qt, no numpy)
so Sora's shop server, the screens, the battle and the headless test all share one copy.

    Save        campaign_save.json: wallet (Credits + Pyroxene), permanent upgrades, supply stock, loadout,
                squad, records. Sora's shop buys through Save.buy(); it is thread-safe (the shop's HTTP
                server runs on its own thread).
    Run         one attempt: 3 areas x 4 rooms (the 4th is the area boss). Before every room the player picks
                a DOOR (what the room pays out, who is waiting inside); after a cleared room the reward is
                granted - usually one of three academy SUPPORTS (boons) that last until the run ends.
                HP and lives carry over from room to room. Earnings are banked the moment they drop, so a
                failed run still pays for the next visit to Sora.

Everything a designer would tune lives in the tables below.
"""
from __future__ import annotations

import json
import os
import random
import threading
from pathlib import Path

SAVE_PATH = Path(__file__).resolve().parent.parent / "campaign_save.json"
SAVE_VERSION = 1
_LOCK = threading.RLock()

ROOMS_PER_AREA = 4
AREAS = [
    dict(id="abydos", name="Abydos Outskirts", jp="\u30a2\u30d3\u30c9\u30b9\u90ca\u5916", diff="rookie",
         color=(255, 176, 60), bosses=["Hoshino", "Shiroko", "Serika", "Ayane"]),
    dict(id="gehenna", name="Gehenna Back Streets", jp="\u30b2\u30d8\u30ca\u88cf\u901a\u308a", diff="veteran",
         color=(255, 76, 104), bosses=["Hina", "Iroha", "Ako", "Mutsuki", "Hina (Dress)"]),
    dict(id="trinity", name="Trinity Sanctum", jp="\u30c8\u30ea\u30cb\u30c6\u30a3\u8056\u5802", diff="elite",
         color=(150, 110, 255), bosses=["Mika", "Seia", "Wakamo", "Azusa", "Kisaki"]),
]
TOTAL_ROOMS = ROOMS_PER_AREA * len(AREAS)
MAX_HEAT = 3

BASE = dict(lives=2, squad_slots=1, item_slots=2, heal_between=0.20, dash_cd=1.8)
ITEM_MAX = 9

# ------------------------------------------------------------------ permanent upgrades (Sora's shop)
# stat: which modifier a rank adds `per` to (see Save.meta). costs: one price per rank.


def _u(uid, tab, name, tag, hue, desc, costs, cur, stat, per):
    return dict(id=uid, tab=tab, name=name, tag=tag, hue=hue, desc=desc, costs=costs, cur=cur, stat=stat, per=per)


UPGRADES = [
    _u("vitality", "training", "Physical Training", "HP", 350, "+8% max HP for the whole squad per rank.",
       [12, 20, 32, 48, 70], "pyrox", "hp", 0.08),
    _u("firepower", "training", "Live-Fire Drills", "ATK", 15, "+6% damage dealt by the whole squad per rank.",
       [12, 20, 32, 48, 70], "pyrox", "dmg", 0.06),
    _u("armor", "training", "Ballistic Vest", "DEF", 210, "-4% damage taken per rank.",
       [10, 18, 28, 42, 60], "pyrox", "taken", -0.04),
    _u("crit", "training", "Marksmanship", "CRT", 45, "+3% critical hit chance per rank.",
       [10, 18, 28, 42], "pyrox", "crit", 0.03),
    _u("ex", "training", "EX Tuning", "EX", 55, "EX gauges charge 10% faster per rank.",
       [10, 18, 28, 42], "pyrox", "ex", 0.10),
    _u("footwork", "training", "Footwork", "DSH", 175, "-12% dash cooldown per rank (the student you control).",
       [8, 16, 28], "pyrox", "dash_cd", -0.12),
    _u("rations", "training", "Field Rations", "MED", 140, "+5% HP healed between rooms per rank.",
       [8, 16, 28], "pyrox", "heal_between", 0.05),
    _u("accounting", "training", "Accounting Class", "CR", 40, "+10% Credits earned per rank.",
       [6, 12, 20, 30, 45], "pyrox", "greed", 0.10),
    _u("halo", "unlocks", "Halo Resilience", "+1UP", 195, "Every squad member starts each run with +1 life.",
       [40, 90], "pyrox", "lives", 1),
    _u("squad", "unlocks", "Squad Slot", "ALLY", 205, "Bring one more ally on every run.",
       [25, 70], "pyrox", "squad_slots", 1),
    _u("pockets", "unlocks", "Bigger Pockets", "BAG", 30, "One more supply slot in your loadout.",
       [1500, 4000], "credits", "item_slots", 1),
    _u("rethink", "unlocks", "Tactical Rethink", "RE", 265, "+1 re-roll of the offered supports per run.",
       [15, 30, 50], "pyrox", "rerolls", 1),
    _u("headstart", "unlocks", "Head Start", "GO", 110, "Begin every run with a random support already active.",
       [60], "pyrox", "start_boon", 1),
    _u("connections", "unlocks", "Sora's Connections", "LUCK", 300, "Rare and Epic supports show up more often.",
       [20, 40, 65], "pyrox", "rarity", 1),
]
UPGRADE_BY_ID = {u["id"]: u for u in UPGRADES}

# ------------------------------------------------------------------ consumables (bought with Credits)
CONSUMABLES = [
    dict(id="medkit", name="First Aid Kit", tag="AID", hue=350, price=120,
         desc="Heals the student you control (or whoever is hurt most) for 50% HP."),
    dict(id="rations", name="Team Rations", tag="FOOD", hue=30, price=220,
         desc="Heals every standing squad member for 25% HP."),
    dict(id="frag", name="Frag Grenade", tag="FRAG", hue=95, price=150,
         desc="Throws a grenade at the cursor: heavy damage in a wide blast."),
    dict(id="flash", name="Flashbang", tag="STUN", hue=55, price=140,
         desc="Stuns every enemy near the cursor for 2.5 s (bosses: 1 s)."),
    dict(id="drink", name="Energy Drink", tag="EX", hue=180, price=180,
         desc="Instantly fills the EX gauge of the student you control."),
    dict(id="barrier", name="Barrier Generator", tag="WALL", hue=200, price=200,
         desc="The whole squad takes 70% less damage for 6 s."),
    dict(id="beacon", name="Artillery Beacon", tag="ARTY", hue=15, price=320,
         desc="Calls six shells down around the cursor."),
    dict(id="revive", name="Revive Ticket", tag="REV", hue=280, price=450,
         desc="Brings a retired squad member back on her feet with one life."),
]
ITEM_BY_ID = {c["id"]: c for c in CONSUMABLES}

# ------------------------------------------------------------------ supports (boons, last one run)
# op: 'mul' multiplies the stat, 'add' adds to it. vals: Common / Rare / Epic. show: how {v} is printed.
RARITY = ("Common", "Rare", "Epic")
SCHOOL_COL = {"Abydos": (255, 176, 60), "Gehenna": (255, 76, 104), "Trinity": (240, 190, 90),
              "Millennium": (30, 161, 255), "Hyakkiyako": (255, 143, 199), "SRT": (58, 200, 140)}


def _b(bid, school, name, text, stat, op, vals, show):
    return dict(id=bid, school=school, name=name, text=text, stat=stat, op=op, vals=vals, show=show)


BOONS = [
    _b("grit", "Abydos", "Desert Grit", "+{v}% max HP for the squad.", "hp", "mul", (1.15, 1.22, 1.30), "up"),
    _b("oasis", "Abydos", "Oasis Break", "Heal {v}% more HP after every room.", "heal_between", "add",
       (0.06, 0.09, 0.12), "pct"),
    _b("sandwall", "Abydos", "Sand Wall", "Every fight starts with a {v}s barrier on the squad.", "start_shield",
       "add", (3.0, 4.5, 6.0), "raw"),
    _b("fury", "Gehenna", "Prefect's Fury", "+{v}% damage dealt.", "dmg", "mul", (1.12, 1.18, 1.25), "up"),
    _b("havoc", "Gehenna", "Havoc", "Explosions deal +{v}% damage.", "expl", "mul", (1.25, 1.40, 1.60), "up"),
    _b("pandemonium", "Gehenna", "Pandemonium", "+{v}% critical hit chance.", "crit", "add", (0.06, 0.09, 0.13),
       "pct"),
    _b("grace", "Trinity", "Tea Party's Grace", "The squad regenerates {v}% HP every second.", "regen", "add",
       (0.006, 0.009, 0.013), "pct1"),
    _b("justice", "Trinity", "Justice Task Force", "+{v}% damage against elites and bosses.", "vs_elite", "mul",
       (1.20, 1.30, 1.45), "up"),
    _b("prayer", "Trinity", "Sister's Prayer", "Every standing squad member gains +{v} life.", "lives", "add",
       (1, 1, 1), "raw"),
    _b("overclock", "Millennium", "Overclock", "+{v}% rate of fire.", "rof", "mul", (1.12, 1.18, 1.25), "up"),
    _b("mags", "Millennium", "Extended Mags", "+{v}% magazine size.", "mag", "mul", (1.30, 1.45, 1.60), "up"),
    _b("hands", "Millennium", "Quick Hands", "-{v}% reload time.", "reload", "mul", (0.80, 0.70, 0.60), "down"),
    _b("budget", "Millennium", "Seminar Budget", "+{v}% Credits earned.", "greed", "mul", (1.25, 1.40, 1.60), "up"),
    _b("step", "Hyakkiyako", "Festival Step", "+{v}% movement speed.", "speed", "mul", (1.10, 1.15, 1.20), "up"),
    _b("blink", "Hyakkiyako", "Shinobi Blink", "-{v}% dash cooldown.", "dash_cd", "mul", (0.80, 0.70, 0.60), "down"),
    _b("foxfire", "Hyakkiyako", "Fox Fire", "Retiring an enemy heals the squad for {v}% HP.", "lifesteal", "add",
       (0.05, 0.08, 0.12), "pct"),
    _b("drills", "SRT", "Rabbit Drills", "EX gauges charge {v}% faster.", "ex", "mul", (1.20, 1.30, 1.45), "up"),
    _b("plates", "SRT", "Plate Carrier", "-{v}% damage taken.", "taken", "mul", (0.90, 0.85, 0.80), "down"),
    _b("breach", "SRT", "Breaching Charge", "Your dash sets off a blast for {v} damage.", "dash_blast", "add",
       (900, 1400, 2000), "raw"),
]
BOON_BY_ID = {b["id"]: b for b in BOONS}
FIXED_RARITY = {"prayer": 2}                       # always offered at this rarity

REWARDS = {
    "boon": dict(name="Academy Support", desc="Choose 1 of 3 supports for this run.", w=5.0),
    "credits": dict(name="Credit Cache", desc="A pile of Credits for Sora's shop.", w=2.0),
    "pyrox": dict(name="Pyroxene", desc="Pyroxene: buys permanent upgrades.", w=2.0),
    "supply": dict(name="Supply Crate", desc="Two random supplies for your stock.", w=1.6),
    "heal": dict(name="Medical Tent", desc="Patches the squad up after the fight.", w=1.4),
    "halo": dict(name="Halo Fragment", desc="+1 life for whoever needs it most.", w=0.8),
}
LAYOUTS = ("left_right", "left_right", "top_bottom", "corners")


def boon_value(bid, rarity):
    return BOON_BY_ID[bid]["vals"][max(0, min(2, int(rarity)))]


def boon_text(bid, rarity):
    b = BOON_BY_ID[bid]
    v = boon_value(bid, rarity)
    if b["show"] == "up": s = f"{(v - 1.0) * 100:.0f}"
    elif b["show"] == "down": s = f"{(1.0 - v) * 100:.0f}"
    elif b["show"] == "pct": s = f"{v * 100:.0f}"
    elif b["show"] == "pct1": s = f"{v * 100:.1f}"
    else: s = f"{v:g}"
    return b["text"].format(v=s)


def area_of(room):
    return min(len(AREAS) - 1, max(0, room) // ROOMS_PER_AREA)


def is_boss_room(room):
    return room % ROOMS_PER_AREA == ROOMS_PER_AREA - 1


# ============================================================================== save file
class Save:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else SAVE_PATH
        self.d = self._fresh()
        self.load()

    @staticmethod
    def _fresh():
        return dict(version=SAVE_VERSION, credits=300, pyrox=0, upgrades={}, items={"medkit": 2, "frag": 1},
                    loadout=["medkit", "frag"], squad=[], leader=None, manual=True, heat=0, heat_unlocked=0,
                    stats=dict(runs=0, wins=0, best_room=0, kills=0, credits_earned=0, pyrox_earned=0))

    # ------------------------------------------------------------------ disk
    def load(self):
        with _LOCK:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(raw, dict): return
            d = self.d
            for k in ("credits", "pyrox", "heat", "heat_unlocked"):
                try: d[k] = max(0, int(raw.get(k, d[k])))
                except Exception: pass
            d["manual"] = bool(raw.get("manual", True))
            ups = raw.get("upgrades")
            if isinstance(ups, dict):
                d["upgrades"] = {}
                for k, v in ups.items():
                    if k in UPGRADE_BY_ID:
                        try: d["upgrades"][k] = max(0, min(len(UPGRADE_BY_ID[k]["costs"]), int(v)))
                        except Exception: pass
            items = raw.get("items")
            if isinstance(items, dict):
                d["items"] = {}
                for k, v in items.items():
                    if k in ITEM_BY_ID:
                        try: d["items"][k] = max(0, min(ITEM_MAX, int(v)))
                        except Exception: pass
            lo = raw.get("loadout")
            if isinstance(lo, list):
                d["loadout"] = [x if x in ITEM_BY_ID else None for x in lo][:8]
            sq = raw.get("squad")
            if isinstance(sq, list):
                d["squad"] = [str(x) for x in sq if isinstance(x, str)][:8]
            d["leader"] = raw.get("leader") if isinstance(raw.get("leader"), str) else None
            st = raw.get("stats")
            if isinstance(st, dict):
                for k in d["stats"]:
                    try: d["stats"][k] = max(0, int(st.get(k, 0)))
                    except Exception: pass
            d["heat_unlocked"] = min(MAX_HEAT, d["heat_unlocked"])
            d["heat"] = min(d["heat"], d["heat_unlocked"])

    def save(self):
        with _LOCK:
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except Exception:
                import traceback; traceback.print_exc()

    # ------------------------------------------------------------------ queries
    @property
    def credits(self): return int(self.d["credits"])

    @property
    def pyrox(self): return int(self.d["pyrox"])

    def level(self, uid):
        return int(self.d["upgrades"].get(uid, 0))

    def next_cost(self, uid):
        u = UPGRADE_BY_ID[uid]
        lv = self.level(uid)
        return u["costs"][lv] if lv < len(u["costs"]) else None

    def count(self, iid):
        return int(self.d["items"].get(iid, 0))

    def meta(self):
        """Every permanent modifier, with the upgrade ranks folded in."""
        m = dict(hp=1.0, dmg=1.0, taken=1.0, crit=0.0, ex=1.0, dash_cd=1.0, greed=1.0, rerolls=0, start_boon=0,
                 rarity=0, heal_between=BASE["heal_between"], lives=BASE["lives"], squad_slots=BASE["squad_slots"],
                 item_slots=BASE["item_slots"])
        for u in UPGRADES:
            lv = self.level(u["id"])
            if lv: m[u["stat"]] += u["per"] * lv
        return m

    def loadout(self):
        """The equipped supply ids, one per unlocked slot (None = empty)."""
        n = int(self.meta()["item_slots"])
        lo = list(self.d.get("loadout") or [])[:n]
        lo += [None] * (n - len(lo))
        seen = set()
        for i, x in enumerate(lo):
            if x is not None and (x in seen or x not in ITEM_BY_ID): lo[i] = None
            seen.add(lo[i])
        return lo

    # ------------------------------------------------------------------ changes
    def cycle_slot(self, i, back=False):
        """Hub: click a supply slot to put the next owned supply in it (then empty, then round again)."""
        with _LOCK:
            lo = self.loadout()
            if not (0 <= i < len(lo)): return
            ring = [None] + [c["id"] for c in CONSUMABLES if self.count(c["id"]) > 0 and (c["id"] not in lo or c["id"] == lo[i])]
            k = ring.index(lo[i]) if lo[i] in ring else 0
            lo[i] = ring[(k + (-1 if back else 1)) % len(ring)]
            self.d["loadout"] = lo
            self.save()

    def earn(self, credits=0, pyrox=0):
        with _LOCK:
            c, p = max(0, int(credits)), max(0, int(pyrox))
            self.d["credits"] += c; self.d["pyrox"] += p
            self.d["stats"]["credits_earned"] += c; self.d["stats"]["pyrox_earned"] += p
            self.save()

    def spend(self, credits=0):
        with _LOCK:
            if self.d["credits"] < credits: return False
            self.d["credits"] -= int(credits)
            self.save()
            return True

    def add_item(self, iid, n=1):
        with _LOCK:
            if iid not in ITEM_BY_ID: return 0
            have = self.count(iid)
            got = max(0, min(ITEM_MAX - have, int(n)))
            self.d["items"][iid] = have + got
            lo = self.loadout()
            if got and iid not in lo and None in lo:            # a free slot: pack it straight away
                lo[lo.index(None)] = iid
                self.d["loadout"] = lo
            self.save()
            return got

    def use_item(self, iid):
        with _LOCK:
            if self.count(iid) <= 0: return False
            self.d["items"][iid] = self.count(iid) - 1
            self.save()
            return True

    def buy(self, pid):
        """Sora's shop. -> (ok, message)."""
        with _LOCK:
            if pid in UPGRADE_BY_ID:
                u = UPGRADE_BY_ID[pid]
                cost = self.next_cost(pid)
                if cost is None: return False, "Already at max rank"
                key = "pyrox" if u["cur"] == "pyrox" else "credits"
                if self.d[key] < cost:
                    return False, "Not enough " + ("Pyroxene" if key == "pyrox" else "Credits")
                self.d[key] -= cost
                self.d["upgrades"][pid] = self.level(pid) + 1
                self.save()
                return True, f"{u['name']} - rank {self.level(pid)}"
            if pid in ITEM_BY_ID:
                c = ITEM_BY_ID[pid]
                if self.count(pid) >= ITEM_MAX: return False, f"You can't carry more than {ITEM_MAX}"
                if self.d["credits"] < c["price"]: return False, "Not enough Credits"
                self.d["credits"] -= c["price"]
                self.add_item(pid, 1)
                return True, f"{c['name']} x{self.count(pid)}"
            return False, "Sora doesn't stock that"

    def shop_state(self):
        """What Sora's shop page draws (JSON-able)."""
        with _LOCK:
            lo = self.loadout()
            ups = []
            for u in UPGRADES:
                lv, mx = self.level(u["id"]), len(u["costs"])
                ups.append(dict(id=u["id"], tab=u["tab"], name=u["name"], tag=u["tag"], hue=u["hue"], desc=u["desc"],
                                level=lv, max=mx, price=u["costs"][lv] if lv < mx else None, cur=u["cur"]))
            items = [dict(id=c["id"], tab="supplies", name=c["name"], tag=c["tag"], hue=c["hue"], desc=c["desc"],
                          level=self.count(c["id"]), max=ITEM_MAX, price=c["price"] if self.count(c["id"]) < ITEM_MAX else None,
                          cur="credits", equipped=c["id"] in lo) for c in CONSUMABLES]
            return dict(credits=self.credits, pyrox=self.pyrox, upgrades=ups, items=items, stats=dict(self.d["stats"]))


_SAVE = None


def get_save():
    global _SAVE
    with _LOCK:
        if _SAVE is None: _SAVE = Save()
        return _SAVE


# ============================================================================== one run
class Run:
    def __init__(self, save, squad, leader, pool, heat=0, seed=None):
        """squad: student names (leader included). pool: every other student name - they are the enemies."""
        self.save = save
        self.rng = random.Random(seed)
        self.meta = save.meta()
        self.heat = max(0, min(MAX_HEAT, int(heat)))
        self.leader = leader if leader in squad else (squad[0] if squad else None)
        lives = int(self.meta["lives"])
        self.squad = [dict(name=n, hp=1.0, lives=lives, out=False) for n in squad]
        self.pool = [n for n in pool if n not in squad] or list(squad)
        self.room = 0
        self.boons = []                     # [(boon id, rarity)]
        self.rerolls = int(self.meta["rerolls"])
        self.credits = self.pyrox = self.kills = self.cleared = 0
        self.door = None                    # the door being played
        self.pending = None                 # dict(type='boon', choices=[(id, rarity)]) while a choice is open
        self.report = None                  # what the last room paid (for the reward screen)
        self.stall = None                   # Sora's field stall offers while inside one
        self.over = None                    # 'win' / 'lose' / 'abandon'
        self.recent = []
        self.seen_rest = set()
        self.win_bonus = 0                  # Pyroxene paid for finishing the whole run
        if self.meta["start_boon"]:
            self.boons.append(self.roll_boons(1)[0])
        self.doors = self.make_doors()

    # ------------------------------------------------------------------ modifiers
    def mods(self):
        """The squad's modifiers right now: permanent upgrades x this run's supports."""
        m = dict(self.meta)
        m.update(rof=1.0, reload=1.0, mag=1.0, speed=1.0, regen=0.0, lifesteal=0.0, expl=1.0, vs_elite=1.0,
                 dash_blast=0.0, start_shield=0.0)
        m.setdefault("lives", BASE["lives"])
        for bid, rar in self.boons:
            b = BOON_BY_ID[bid]
            if b["stat"] == "lives": continue               # applied to the squad once, when it is taken
            v = boon_value(bid, rar)
            if b["op"] == "mul": m[b["stat"]] = m.get(b["stat"], 1.0) * v
            else: m[b["stat"]] = m.get(b["stat"], 0.0) + v
        m["taken"] = max(0.25, m["taken"])
        m["dash_cd"] = max(0.3, m["dash_cd"])
        return m

    def greed(self):
        return self.mods()["greed"]

    def loadout(self):
        return [x for x in self.save.loadout() if x is not None]

    def living(self):
        return [m for m in self.squad if not m["out"]]

    def area(self):
        return AREAS[area_of(self.room)]

    # ------------------------------------------------------------------ doors
    def _names(self, n, avoid=()):
        pool = [x for x in self.pool if x not in avoid]
        fresh = [x for x in pool if x not in self.recent] or pool
        self.rng.shuffle(fresh)
        out = fresh[:n]
        while len(out) < n and pool:                         # tiny rosters: the same student twice is fine
            out.append(self.rng.choice(pool))
        self.recent = (self.recent + out)[-max(2, len(self.pool) // 2):]
        return out

    def _enemies(self, boss=False, elite=False):
        a, s = divmod(self.room, ROOMS_PER_AREA)
        a = min(a, len(AREAS) - 1)
        hp = (0.44 + 0.045 * self.room) * (1.0 + 0.15 * self.heat)
        dmg = (0.46 + 0.04 * self.room) * (1.0 + 0.12 * self.heat)
        if boss:
            cands = [b for b in AREAS[a]["bosses"] if b in self.pool]
            name = cands[0] if cands else self._names(1)[0]
            out = [dict(name=name, tier="boss", hp=(2.4 + 0.5 * a) * (1.0 + 0.15 * self.heat),
                        dmg=(0.75 + 0.1 * a) * (1.0 + 0.12 * self.heat), lives=2 + (1 if a == len(AREAS) - 1 else 0),
                        ex=1.4, scale=1.25)]
            for i, nm in enumerate(self._names(1 + a, avoid=(name,))):
                tier = "elite" if (a == len(AREAS) - 1 and i == 0) else "grunt"
                out.append(dict(name=nm, tier=tier, hp=hp * (1.9 if tier == "elite" else 1.0),
                                dmg=dmg * (1.15 if tier == "elite" else 1.0), lives=1))
            return out
        n = min(6, 2 + a + (1 if s >= 2 else 0))
        out = [dict(name=nm, tier="grunt", hp=hp, dmg=dmg, lives=1) for nm in self._names(n)]
        if elite and out:
            out[0].update(tier="elite", hp=hp * 1.9, dmg=dmg * 1.15, ex=1.2, scale=1.1)
        return out

    def _door(self, kind, reward=None, elite=False):
        a = area_of(self.room)
        d = dict(kind=kind, reward=reward, elite=bool(elite), area=a, room=self.room, diff=AREAS[a]["diff"],
                 layout=self.rng.choice(LAYOUTS), enemies=[])
        if kind == "boss":
            d["enemies"] = self._enemies(boss=True)
            d["title"] = "Area Boss"
            d["desc"] = f"{d['enemies'][0]['name']} holds {AREAS[a]['name']}. Pyroxene, Credits and a strong support."
        elif kind == "fight":
            d["enemies"] = self._enemies(elite=elite)
            d["title"] = REWARDS[reward]["name"]
            d["desc"] = REWARDS[reward]["desc"] + (" Elite guard: the reward is doubled / upgraded." if elite else "")
        elif kind == "stall":
            d["title"] = "Sora's Field Stall"
            d["desc"] = "No fight. Sora followed you with a cart: spend Credits on a meal, supplies or a support."
        else:
            d["title"] = "Caf\u00e9 Break"
            d["desc"] = "No fight. The squad rests: +45% HP, and retired students get back up with one life."
        return d

    def make_doors(self):
        a, s = divmod(self.room, ROOMS_PER_AREA)
        if is_boss_room(self.room):
            return [self._door("boss")]
        n = 2 if self.room == 0 else (3 if self.rng.random() < 0.6 else 2)
        keys = [k for k in REWARDS if k != "boon"]
        picks = ["boon"]
        while len(picks) < n:
            k = self.rng.choices(keys, [REWARDS[x]["w"] for x in keys])[0]
            if k not in picks or (k == "boon"): picks.append(k)
        if self.room == 0: picks = ["boon", "boon"][:n]          # the first room always pays a support
        doors = []
        for i, k in enumerate(picks):
            elite = self.room > 0 and self.rng.random() < 0.2 + 0.06 * a
            if self.room == 0 and i == 1: elite = True         # ... and shows what an elite door is
            doors.append(self._door("fight", k, elite))
        hurt = any(m["out"] or m["hp"] < 0.5 or m["lives"] <= 1 for m in self.squad)
        if s in (1, 2) and len(doors) >= 2 and self.rng.random() < (0.55 if hurt else 0.35):
            kind = "cafe" if (hurt and self.rng.random() < 0.55 and a not in self.seen_rest) else "stall"
            doors[-1] = self._door(kind)
        return doors

    def enter(self, i):
        self.door = self.doors[i]
        if self.door["kind"] == "cafe": self.seen_rest.add(self.door["area"])
        return self.door

    # ------------------------------------------------------------------ supports
    def roll_rarity(self, bump=0):
        lv = int(self.meta.get("rarity", 0))
        w = [max(10.0, 70.0 - 8.0 * lv), 24.0 + 5.0 * lv, 6.0 + 3.0 * lv]
        r = self.rng.choices((0, 1, 2), w)[0]
        return min(2, r + bump)

    def roll_boons(self, n=3, bump=0):
        ids = [b["id"] for b in BOONS]
        self.rng.shuffle(ids)
        return [(bid, FIXED_RARITY.get(bid, self.roll_rarity(bump))) for bid in ids[:n]]

    def add_boon(self, bid, rar):
        self.boons.append((bid, rar))
        if BOON_BY_ID[bid]["stat"] == "lives":
            for m in self.living(): m["lives"] += int(boon_value(bid, rar))

    def take_boon(self, i):
        p = self.pending
        if not p or p.get("type") != "boon" or not (0 <= i < len(p["choices"])): return False
        self.add_boon(*p["choices"][i])
        self.pending = None
        return True

    def reroll(self):
        p = self.pending
        if not p or p.get("type") != "boon" or self.rerolls <= 0: return False
        self.rerolls -= 1
        p["choices"] = self.roll_boons(len(p["choices"]), p.get("bump", 0))
        return True

    # ------------------------------------------------------------------ rewards
    def _earn(self, credits=0, pyrox=0):
        c, p = max(0, int(round(credits))), max(0, int(round(pyrox)))
        self.credits += c; self.pyrox += p
        if self.report is not None:
            self.report["credits"] += c; self.report["pyrox"] += p
        self.save.earn(c, p)
        return c, p

    def heal(self, frac):
        for m in self.living(): m["hp"] = min(1.0, m["hp"] + frac)

    def give_life(self, n=1):
        """+1 life to whoever needs it most (a retired student first: she comes back). -> names."""
        got = []
        for _ in range(n):
            order = sorted(self.squad, key=lambda m: (not m["out"], m["lives"]))
            if not order: break
            m = order[0]
            if m["out"]:
                m.update(out=False, lives=1, hp=0.5)
            else:
                m["lives"] += 1
            got.append(m["name"])
        return got

    def kill_value(self, tier):
        """Credits a retired enemy drops."""
        base = {"grunt": 22, "elite": 60, "boss": 180}.get(tier, 20) + 2 * self.room
        return base * self.greed()

    def room_result(self, win, kills=0, credits=0, squad=None):
        """A fight ended. squad: [dict(name, hp, lives, out)] as the battle left them. -> True if the run goes on."""
        for st in squad or []:
            for m in self.squad:
                if m["name"] == st["name"]:
                    m.update(hp=max(0.05, min(1.0, float(st["hp"]))), lives=max(0, int(st["lives"])), out=bool(st["out"]))
                    if m["out"]: m["lives"] = 0
        self.report = dict(win=bool(win), kills=int(kills), credits=0, pyrox=0, notes=[], door=self.door)
        self.kills += int(kills)
        self._earn(credits=credits)
        if not win or not self.living():
            self.finish(False)
            return False
        self.cleared += 1
        self._grant(self.door)
        return True

    def _grant(self, door):
        notes = self.report["notes"]
        a = door["area"]
        mult = 2 if door.get("elite") else 1
        hot = 1.0 + 0.25 * self.heat
        r = door.get("reward")
        if door["kind"] == "boss":
            c, p = self._earn(credits=(250 + 150 * a) * self.greed(), pyrox=(15, 25, 45)[a] * hot)
            notes.append(f"Boss bounty: +{c} Credits, +{p} Pyroxene")
            if self.room < TOTAL_ROOMS - 1:
                self.pending = dict(type="boon", choices=self.roll_boons(3, 1), bump=1)
        elif r == "boon":
            self.pending = dict(type="boon", choices=self.roll_boons(3, mult - 1), bump=mult - 1)
        elif r == "credits":
            c, _p = self._earn(credits=(110 + 22 * self.room) * mult * self.greed())
            notes.append(f"Credit cache: +{c} Credits")
        elif r == "pyrox":
            _c, p = self._earn(pyrox=(5 + 2 * a) * mult * hot)
            notes.append(f"Pyroxene: +{p}")
        elif r == "supply":
            got = {}
            for _ in range(2 * mult):
                iid = self.rng.choice(CONSUMABLES)["id"]
                if self.save.add_item(iid, 1): got[iid] = got.get(iid, 0) + 1
            notes.append("Supply crate: " + (", ".join(f"{ITEM_BY_ID[k]['name']} x{v}" for k, v in got.items())
                                             or "your bags are full"))
        elif r == "heal":
            frac = 0.35 if mult == 1 else 0.6
            self.heal(frac)
            notes.append(f"Medical tent: the squad recovers {frac * 100:.0f}% HP")
        elif r == "halo":
            names = self.give_life(mult)
            notes.append("Halo fragment: +1 life for " + ", ".join(names))
        if door["kind"] == "fight":                           # every cleared room moves the long game forward a little
            _c, p = self._earn(pyrox=(2 + a) * hot)
            notes.append(f"Room cleared: +{p} Pyroxene")
        if door.get("elite") and door["kind"] == "fight":
            _c, p = self._earn(pyrox=(2 + a) * hot)
            notes.append(f"Elite guard defeated: +{p} Pyroxene")

    def advance(self):
        """Leave the room. -> True if there is a next one (False: the run is won)."""
        self.pending = None; self.stall = None; self.door = None
        self.room += 1
        if self.room >= TOTAL_ROOMS:
            self.finish(True)
            return False
        self.heal(self.mods()["heal_between"])
        self.doors = self.make_doors()
        return True

    # ------------------------------------------------------------------ rooms without a fight
    def rest(self):
        """Cafe break. -> lines for the screen."""
        notes = []
        back = [m for m in self.squad if m["out"]]
        for m in back: m.update(out=False, lives=1, hp=0.5)
        self.heal(0.45)
        notes.append("The squad recovers 45% HP.")
        if back: notes.append("Back on their feet: " + ", ".join(m["name"] for m in back))
        self.report = dict(win=True, kills=0, credits=0, pyrox=0, notes=notes, door=self.door)
        return notes

    def open_stall(self):
        r = self.room
        offers = [dict(type="heal", name="Hot Meal", tag="MEAL", hue=30, price=90 + 12 * r,
                       desc="The squad recovers 35% HP."),
                  dict(type="boon", name="Sora's Pick", tag="PICK", hue=265, price=240 + 18 * r,
                       desc="A random Rare-or-better support, on the spot.")]
        for c in self.rng.sample(CONSUMABLES, 2):
            offers.append(dict(type="item", item=c["id"], name=c["name"], tag=c["tag"], hue=c["hue"],
                               price=int(c["price"] * 0.8), desc=c["desc"]))
        offers.append(dict(type="life", name="Halo Polish", tag="+1UP", hue=195, price=360 + 20 * r,
                           desc="+1 life for whoever needs it most (a retired student comes back)."))
        for o in offers: o["sold"] = False
        self.stall = offers
        self.report = dict(win=True, kills=0, credits=0, pyrox=0, notes=[], door=self.door)
        return offers

    def stall_buy(self, i):
        """-> (ok, message)."""
        if not self.stall or not (0 <= i < len(self.stall)): return False, ""
        o = self.stall[i]
        if o["sold"]: return False, "Sold out"
        if o["type"] == "item" and self.save.count(o["item"]) >= ITEM_MAX: return False, "Your bags are full"
        if not self.save.spend(o["price"]): return False, "Not enough Credits"
        o["sold"] = True
        if o["type"] == "heal":
            self.heal(0.35); return True, "The squad digs in: +35% HP"
        if o["type"] == "boon":
            bid, rar = self.roll_boons(1, 1)[0]
            self.add_boon(bid, rar)
            return True, f"{RARITY[rar]} support: {BOON_BY_ID[bid]['name']}"
        if o["type"] == "item":
            self.save.add_item(o["item"], 1); return True, f"{o['name']} packed"
        names = self.give_life(1)
        return True, "+1 life: " + ", ".join(names)

    # ------------------------------------------------------------------ the end
    def finish(self, win, abandoned=False):
        if self.over is not None: return
        self.over = "win" if win else ("abandon" if abandoned else "lose")
        st = self.save.d["stats"]
        with _LOCK:
            st["runs"] += 1
            st["kills"] += self.kills
            st["best_room"] = max(st["best_room"], min(TOTAL_ROOMS, self.cleared if not win else TOTAL_ROOMS))
            if win:
                st["wins"] += 1
                if self.heat >= self.save.d["heat_unlocked"] and self.save.d["heat_unlocked"] < MAX_HEAT:
                    self.save.d["heat_unlocked"] += 1
        if win:
            rep = self.report
            self.report = None
            c, p = self._earn(pyrox=30 * (1.0 + 0.25 * self.heat))
            self.report = rep
            self.win_bonus = p
        self.save.save()
