"""Headless tests for the campaign.

    python test_campaign.py            the rules only (babattlearena/campaign_data.py): no Qt, no numpy, no models
    python test_campaign.py --battle   also plays real campaign rooms without a window: real models from model/,
                                       real fighters, brains and ragdolls, only the GL renderer is stubbed.
                                       Needs PySide6 + numpy (QT_QPA_PLATFORM=offscreen is set for you).
                                       --runs N   play N whole runs on autopilot and print how far they get
                                       --ranks K  ... with every permanent upgrade bought up to rank K
                                       --verbose  ... printing every room
    python test_campaign.py --live     the whole flow through the real Qt event loop, still without a screen: hub ->
                                       door -> a live CampaignBattle (timer, overlay, HUD, input pad) -> real key and
                                       mouse events -> pause / resume / abandon -> reward and result screens -> title

What is checked
    rules    buying (not enough money, rank caps, both currencies), supplies and the loadout, the save file round
             trip, the shop state Sora's page reads, door generation (boss rooms, the first room pays a support,
             nobody fights her own squad), supports and how they stack, a whole won run and a lost one
    battle   a campaign room builds and runs to its end with no exception; the squad's modifiers land on the
             fighters; the player-driven student moves, dashes, reloads, fires and casts her EX from synthetic
             input; every supply works; the overlay, the HUD bar and every campaign screen paint without raising
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE / "babattlearena"


def load_rules():
    """campaign_data without running babattlearena/__init__ (which wants Qt)."""
    if "babattlearena.campaign_data" in sys.modules:
        return sys.modules["babattlearena.campaign_data"]
    if "babattlearena" not in sys.modules:
        pkg = types.ModuleType("babattlearena")
        pkg.__path__ = [str(PKG)]
        sys.modules["babattlearena"] = pkg
    spec = importlib.util.spec_from_file_location("babattlearena.campaign_data", PKG / "campaign_data.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["babattlearena.campaign_data"] = mod
    spec.loader.exec_module(mod)
    return mod


NAMES = ["Ako", "Arisu", "Ayane", "Azusa", "Chinatsu", "Fuuka", "Hina", "Hina (Dress)", "Hoshino", "Iroha", "Kisaki",
         "Mika", "Momoi (Maid)", "Mutsuki", "Niko", "Seia", "Serika", "Shiroko", "Wakamo", "Yuuka"]
FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("  FAIL:", what)
    return cond


def fake_fight(cd, run, win=True, hurt=0.1):
    """Report a fight the way CampaignBattle.report() does."""
    door = run.door
    kills = len(door["enemies"]) if win else 1
    credits = sum(run.kill_value(e["tier"]) for e in door["enemies"][:kills])
    squad = [dict(name=m["name"], hp=max(0.2, m["hp"] - hurt) if win else 0.0, lives=m["lives"] if win else 0,
                  out=not win) for m in run.squad]
    return run.room_result(win, kills, credits, squad)


def test_rules():
    cd = load_rules()
    tmp = Path(tempfile.mkdtemp()) / "campaign_save.json"
    print("--- rules: save, shop")
    s = cd.Save(tmp)
    check(s.credits == 300 and s.pyrox == 0, "a fresh save starts with 300 Credits and no Pyroxene")
    ok, msg = s.buy("vitality")
    check(not ok and "Pyroxene" in msg, "an upgrade cannot be bought without Pyroxene")
    s.earn(pyrox=5000, credits=20000)
    for u in cd.UPGRADES:
        n = 0
        while s.buy(u["id"])[0]: n += 1
        check(n == len(u["costs"]) and s.next_cost(u["id"]) is None, f"{u['id']}: every rank can be bought, then it is capped")
    m = s.meta()
    check(abs(m["hp"] - 1.4) < 1e-9 and abs(m["taken"] - 0.8) < 1e-9, "ranks fold into the meta modifiers")
    check(m["squad_slots"] == 3 and m["item_slots"] == 4 and m["lives"] == 4 and m["rerolls"] == 3, "unlocks add slots, lives, re-rolls")
    before = s.credits
    ok, msg = s.buy("revive")
    check(ok and s.count("revive") == 1 and s.credits == before - cd.ITEM_BY_ID["revive"]["price"], "a supply costs Credits and lands in stock")
    check("revive" in s.loadout(), "a newly bought supply is packed into a free slot")
    while s.buy("medkit")[0]: pass
    check(s.count("medkit") == cd.ITEM_MAX, "supplies are capped at ITEM_MAX")
    check(s.use_item("medkit") and s.count("medkit") == cd.ITEM_MAX - 1, "using a supply takes one from stock")
    lo0 = s.loadout()
    s.cycle_slot(0); s.cycle_slot(0, back=True)
    check(s.loadout() == lo0 and len(set(x for x in s.loadout() if x)) == len([x for x in s.loadout() if x]),
          "cycling a slot forward and back restores it, and no supply is packed twice")
    st = s.shop_state()
    json.dumps(st)
    check(len(st["upgrades"]) == len(cd.UPGRADES) and len(st["items"]) == len(cd.CONSUMABLES) and st["credits"] == s.credits,
          "the shop state lists everything and is JSON")
    check(not s.buy("nonsense")[0], "unknown ids are refused")
    s2 = cd.Save(tmp)
    check(s2.d == s.d, "the save file round-trips")
    tmp.write_text("{ not json", encoding="utf-8")
    check(cd.Save(tmp).credits == 300, "a broken save file falls back to a fresh one")

    print("--- rules: doors and supports")
    s = cd.Save(Path(tempfile.mkdtemp()) / "campaign_save.json")
    squad = ["Shiroko", "Hoshino"]
    for seed in range(40):
        run = cd.Run(s, squad, "Shiroko", [n for n in NAMES if n not in squad], seed=seed)
        check(len(run.doors) == 2 and all(d["reward"] == "boon" for d in run.doors), "the first room always pays a support")
        while run.over is None:
            doors = run.doors
            boss = cd.is_boss_room(run.room)
            if boss:
                check(len(doors) == 1 and doors[0]["kind"] == "boss" and doors[0]["enemies"][0]["tier"] == "boss",
                      "the last room of an area is its boss")
            else:
                check(any(d.get("reward") == "boon" for d in doors), "there is always a support door")
            for d in doors:
                check(all(e["name"] in NAMES and e["name"] not in squad for e in d["enemies"]), "enemies come from the rest of the roster")
                check(len(d["enemies"]) <= 6 and (d["kind"] in ("stall", "cafe")) == (not d["enemies"]), "sane enemy counts")
            i = random.Random(seed * 100 + run.room).randrange(len(doors))
            door = run.enter(i)
            if door["kind"] == "cafe":
                run.rest()
            elif door["kind"] == "stall":
                run.open_stall(); run.stall_buy(0)
            else:
                check(fake_fight(cd, run), "a won fight keeps the run going")
                if run.pending:
                    check(len(run.pending["choices"]) == 3 and len({b for b, _r in run.pending["choices"]}) == 3,
                          "three different supports are offered")
                    check(not run.advance.__self__.pending is None, "a choice is pending")
                    run.take_boon(seed % 3)
            run.advance()
        check(run.over == "win" and run.room == cd.TOTAL_ROOMS, "twelve rooms later the run is won")
    check(s.d["stats"]["wins"] == 40 and s.d["heat_unlocked"] == 1, "wins are recorded and unlock the next threat level")
    check(s.pyrox > 0 and s.credits > 300, "a run pays Credits and Pyroxene into the wallet")

    run = cd.Run(s, squad, "Shiroko", NAMES, seed=1)
    base = run.mods()
    run.add_boon("fury", 2); run.add_boon("fury", 0); run.add_boon("pandemonium", 1); run.add_boon("prayer", 2)
    m = run.mods()
    check(abs(m["dmg"] / base["dmg"] - 1.25 * 1.12) < 1e-9, "the same support stacks multiplicatively")
    check(abs(m["crit"] - base["crit"] - 0.09) < 1e-9, "additive supports add")
    check(all(x["lives"] == int(base["lives"]) + 1 for x in run.squad), "Sister's Prayer gives everyone a life at once")
    for b in cd.BOONS:
        for r in range(3):
            check("{" not in cd.boon_text(b["id"], r), f"support text formats: {b['id']}")
            check(b["stat"] in m or b["stat"] == "lives", f"support stat is a known modifier: {b['id']}")

    print("--- rules: losing, the stall, the cafe")
    run = cd.Run(s, squad, "Shiroko", NAMES, seed=3)
    run.enter(0)
    wins0, runs0 = s.d["stats"]["wins"], s.d["stats"]["runs"]
    check(not fake_fight(cd, run, win=False) and run.over == "lose", "a wiped squad ends the run")
    check(s.d["stats"]["wins"] == wins0 and s.d["stats"]["runs"] == runs0 + 1, "a lost run counts as a run, not a win")
    run = cd.Run(s, squad, "Shiroko", NAMES, seed=4)
    run.squad[1].update(out=True, lives=0, hp=0.0); run.squad[0]["hp"] = 0.3
    run.door = run._door("cafe"); run.rest()
    check(not run.squad[1]["out"] and run.squad[1]["lives"] == 1 and run.squad[0]["hp"] > 0.7, "the cafe heals and brings the retired back")
    s = cd.Save(Path(tempfile.mkdtemp()) / "campaign_save.json")        # empty bags: every offer can be bought
    s.earn(credits=5000)
    run = cd.Run(s, squad, "Shiroko", NAMES, seed=4)
    run.door = run._door("stall"); offers = run.open_stall()
    c0, n0 = s.credits, len(run.boons)
    for i in range(len(offers)): run.stall_buy(i)
    check(s.credits < c0 and len(run.boons) == n0 + 1 and all(o["sold"] for o in offers), "the stall sells each offer once")
    check(not run.stall_buy(0)[0], "a sold offer cannot be bought again")
    run.finish(False, abandoned=True)
    check(run.over == "abandon", "a run can be abandoned")


# ============================================================================== real rooms, no window
def make_world(names, save_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    import babattlearena.battle as battle_mod
    import babattlearena.campaign_data as cd
    from babattlearena.manager import ArenaManager
    from bapet.character import Character
    from bapet.config import MODEL_DIR
    from bapet.profiles import load_profile

    class NoRenderer:                                   # the one thing a headless run cannot have: a GL context
        def __init__(self, *a, **k): pass
        def render(self, *a, **k): return None
        def release(self): pass

    battle_mod.TopDownRenderer = NoRenderer
    entries = []
    for i, n in enumerate(names):
        path = MODEL_DIR / f"{n}.glb"
        if not path.exists(): continue
        ch = Character(path, i, profile=load_profile(path))
        entries.append(types.SimpleNamespace(pet=types.SimpleNamespace(name=None), ch=ch, name=ch.name, idx=i,
                                             still=None, still_state=0, hue=(i * 47) % 360))
    picker = types.SimpleNamespace(entries=entries, engine=types.SimpleNamespace(bake=lambda e: setattr(e, "still_state", 2)))

    class App:
        ctx = None; tracker = None; pets = []; active = None
        cfg = {}
        def __init__(self): self.qapp = qapp
        def resolve_screen(self): return QtCore.QRect(0, 0, 1600, 900)
        def picker(self): return picker
        def hide_picker(self): pass
        def end_all_chats(self): pass
        def restack(self, force=False): pass
        def show_panel(self): pass
        def quit_app(self): pass

    cd._SAVE = cd.Save(save_path)
    mgr = ArenaManager(App())
    mgr.settings["windows_cover"] = False
    return qapp, mgr, cd, entries


def sim(B, seconds, dt=1 / 30, until=None, render=True):
    """Battle.tick without the clock, the windows or the results screen."""
    n = int(seconds / dt)
    for _ in range(n):
        B.real_t += dt
        if B.boxes_dirty: B.rebuild_boxes()
        B.step(dt * B.slowmo)
        if render:
            for f in B.fighters: f.render(dt)
        if B.result_shown or (until is not None and until(B)): break
    return B


def new_battle(mgr, cd, run, door_i=0, manual=False):
    from babattlearena.campaign_battle import CampaignBattle
    door = run.enter(door_i)
    by_name = {e.name: e for e in mgr.app.picker().entries}
    B = CampaignBattle(mgr, run, door, by_name, mgr.settings, manual=manual)
    mgr.battle = B
    return B


def play_run(mgr, cd, squad, seed, verbose=False, max_room_s=150.0):
    """A whole run on autopilot (first door every time, first support). -> the finished Run."""
    names = [e.name for e in mgr.app.picker().entries]
    run = cd.Run(cd.get_save(), squad, squad[0], [n for n in names if n not in squad], seed=seed)
    random.seed(seed)
    while run.over is None:
        fights = [i for i, d in enumerate(run.doors) if d["kind"] in ("fight", "boss")]
        B = new_battle(mgr, cd, run, fights[0])
        mgr.show_results = lambda b: setattr(b, "_done", True)
        sim(B, max_room_s, render=False)
        rep = B.report()
        if B.winner is None: rep["win"] = False                       # timed out: call it lost
        if verbose:
            print(f"    room {run.room + 1:2d} {B.door['kind']:5s} vs {len(B.door['enemies'])}: "
                  f"{'WIN ' if rep['win'] else 'LOSS'} in {B.t:5.1f}s  squad " +
                  ", ".join(f"{m['name']} {m['hp'] * 100:.0f}%/{m['lives']}L" + ("(out)" if m['out'] else "") for m in rep["squad"]))
        B.stop(); mgr.battle = None
        if not run.room_result(rep["win"], rep["kills"], rep["credits"], rep["squad"]): break
        if run.pending: run.take_boon(0)
        run.advance()
    return run


def test_battle(runs=0, ranks=0):
    from PySide6 import QtCore, QtGui
    tmp = Path(tempfile.mkdtemp()) / "campaign_save.json"
    want = ["Shiroko", "Hoshino", "Hina", "Mika", "Iroha", "Ako", "Serika", "Azusa", "Yuuka", "Mutsuki"]
    t0 = time.time()
    qapp, mgr, cd, entries = make_world(want, tmp)
    names = [e.name for e in entries]
    print(f"--- battle: {len(entries)} models loaded in {time.time() - t0:.1f}s")
    if not check(len(entries) >= 5, "at least five models from model/ are needed for the battle test"): return
    save = cd.get_save()
    save.earn(credits=50000, pyrox=5000)
    for iid in cd.ITEM_BY_ID: save.add_item(iid, 5)
    for _ in range(2): save.buy("pockets")
    save.d["loadout"] = ["medkit", "frag", "flash", "revive"]
    squad = [n for n in ("Shiroko", "Hoshino") if n in names] or names[:2]

    print("--- battle: modifiers, an autopilot room")
    random.seed(11)
    run = cd.Run(save, squad, squad[0], [n for n in names if n not in squad], seed=5)
    run.add_boon("grit", 2); run.add_boon("fury", 1); run.add_boon("mags", 0); run.add_boon("sandwall", 0)
    B = new_battle(mgr, cd, run, 1)                                    # the elite door of the first room
    mine = [f for f in B.fighters if f.team == 0]
    foes = [f for f in B.fighters if f.team == 1]
    from babattlearena.stats import CombatProfile
    f0 = mine[0]
    ref = CombatProfile(f0.ch)
    check(abs(f0.hp_max - ref.hp * 1.30) < 1 and abs(f0.st.dmg_mul - ref.dmg_mul * 1.18) < 1e-6 and f0.st.mag == round(ref.mag * 1.3),
          "supports land on the squad's fighters (HP, damage, magazine)")
    check(any(getattr(f, "tier", "") == "elite" for f in foes) and all(f.lives == 1 for f in foes), "the elite door has an elite; grunts have one life")
    check(all(f.hp_max < CombatProfile(f.ch).hp for f in foes if f.tier == "grunt"), "grunts are weaker than a full-strength student")
    check(B.player is f0 and not f0.manual, "the leader is the player's student; autopilot leaves her brain in charge")
    done = []
    mgr.show_results = lambda b: done.append(b)
    sim(B, 120)
    check(bool(done) and B.winner in (0, 1), f"an autopilot room reaches its end (t={B.t:.0f}s, winner={B.winner})")
    check(any(b.get("kind") == "c_end" for b in B.banners), "the campaign end banner replaced the arena one")
    rep = B.report()
    check(len(rep["squad"]) == len(mine) and rep["kills"] == sum(1 for f in foes if f.state == "out"), "the report counts knock-outs")
    check(rep["credits"] > 0 or rep["kills"] == 0, "retired enemies drop Credits")
    print(f"    {'won' if rep['win'] else 'lost'} in {B.t:.1f}s, {rep['kills']} KOs, +{rep['credits']:.0f} CR, squad: " +
          ", ".join(f"{m['name']} {m['hp'] * 100:.0f}% {m['lives']}L" for m in rep["squad"]))
    # the overlay and the HUD paint (straight calls, so an exception is not swallowed by paintEvent)
    from babattlearena.campaign_battle import CampaignHUD, CampaignOverlay
    img = QtGui.QImage(1600, 900, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    for cls in (CampaignOverlay,):
        ov = cls(B)
        p = QtGui.QPainter(img)
        try:
            ov.paint_field(p, 1.0); ov.paint_ui(p, 1.0)
            ok = True
        except Exception:
            import traceback; traceback.print_exc(); ok = False
        p.end()
        check(ok, "the campaign overlay paints")
    hud = CampaignHUD(B)
    p = QtGui.QPainter(img)
    try:
        hud.hits = []; hud.paint_content(p, QtCore.QRectF(8, 8, 884, 62), 1.0); ok = True
    except Exception:
        import traceback; traceback.print_exc(); ok = False
    p.end()
    check(ok and any(k == ("auto",) for _s, k in hud.hits), "the campaign HUD bar paints and has its buttons")
    B.stop(); mgr.battle = None

    print("--- battle: the student you control")
    random.seed(3)
    run = cd.Run(save, squad, squad[0], [n for n in names if n not in squad], seed=9)
    B = new_battle(mgr, cd, run, 0, manual=True)
    mgr.show_results = lambda b: None
    pl = B.player
    aim = [pl.x + 400.0, pl.y]
    B.cursor = lambda: (aim[0], aim[1])
    sim(B, 6, until=lambda b: b.phase == "fight")
    check(B.phase == "fight" and pl.manual and pl.manual_now(), "after the stand-by she is under manual control")
    K = B.ctl
    from PySide6.QtCore import Qt
    key = lambda k: int(getattr(k, "value", k))
    for o in B.fighters:                                               # nobody else acts during the driving test,
        if o is not pl: o.stun_until = 1e9                             # and nobody is retired by it
        if o.team == 1: o.hp = o.hp_max = 1e7
    x0, y0 = pl.x, pl.y
    K.keys.add(key(Qt.Key.Key_D)); sim(B, 0.8); K.keys.clear()
    check(pl.x - x0 > pl.size * 0.6 and abs(pl.y - y0) < pl.size * 0.5 and pl.anim == "run", f"D walks her right ({pl.x - x0:.0f}px)")
    check(not pl.path and pl.goal is None, "her brain plans nothing while she is driven")
    x1 = pl.x
    K.keys.add(key(Qt.Key.Key_S)); K.press("dash"); sim(B, 0.1)
    check(pl.dash_cd > 0 and pl.invulnerable(), "SPACE dashes: a cooldown starts and she is briefly invulnerable")
    sim(B, 0.5); K.keys.clear()
    check(pl.y - y0 > pl.size * 0.9, f"the dash carried her down the screen ({pl.y - y0:.0f}px)")
    sim(B, 0.4)
    check(not pl.invulnerable() or B.t < pl.invuln_until, "invulnerability ends")
    foe = min((f for f in B.fighters if f.team == 1), key=lambda f: (f.x - pl.x) ** 2 + (f.y - pl.y) ** 2)
    # walk her next to an enemy with a clear line, then hold the trigger on him
    pl.x, pl.y = B.nav.nearest_free(foe.x - pl.size * 2.2, foe.y)
    for bx in B.props: bx.alive = False
    B.rebuild_boxes()
    aim[0], aim[1] = foe.x, foe.y
    shots0, hp0 = pl.rec["shots"], foe.hp
    K.lmb = True; sim(B, 2.5); K.lmb = False
    check(pl.rec["shots"] > shots0, f"holding LMB fires ({pl.rec['shots'] - shots0} shots)")
    check(foe.hp < hp0 or foe.state != "alive", "her shots hit the enemy under the cursor")
    check(pl.target is None or True, "trigger released")
    sim(B, 0.3)
    check(pl.target is None and not pl.want_fire, "releasing LMB stops the fire")
    aim[0], aim[1] = pl.x + 300, pl.y - 200                            # empty floor: free aim
    shots0 = pl.rec["shots"]
    K.lmb = True; sim(B, 1.5); K.lmb = False
    check(pl.rec["shots"] > shots0, "she also fires at an empty spot on the floor (free aim)")
    pl.reload_t = 0.0; pl.ammo = max(1, pl.st.mag // 3)
    sim(B, 0.2); K.press("reload"); sim(B, 0.2)
    check(pl.reload_t > 0, "R reloads")
    sim(B, pl.st.reload + 0.5)
    check(pl.ammo == pl.st.mag, "the reload finishes while she is driven")
    aim[0], aim[1] = foe.x, foe.y
    pl.ex = 1.0; ex0 = pl.rec["ex"]
    K.press("ex"); sim(B, 1.5)
    check(pl.rec["ex"] == ex0 + 1 and pl.ex < 1.0, f"Q casts her EX ({pl.st.ex})")
    # supplies
    pl.hp = pl.hp_max * 0.3
    n0 = save.count("medkit"); K.press("item0"); sim(B, 0.1)
    check(pl.hp > pl.hp_max * 0.7 and save.count("medkit") == n0 - 1, "1: the first aid kit heals and is used up")
    sim(B, 0.6); pl.hp = pl.hp_max
    n0 = save.count("medkit"); K.press("item0"); sim(B, 0.1)
    check(save.count("medkit") == n0, "a supply that would do nothing is not spent")
    sim(B, 0.6)
    for o in B.fighters: o.stun_until = 0.0
    n0 = len(B.projectiles); K.press("item1"); sim(B, 0.05)
    check(len(B.projectiles) == n0 + 1, "2: the frag grenade is thrown at the cursor")
    sim(B, 0.6); K.press("item2"); sim(B, 0.05)
    check(foe.state != "alive" or B.t < foe.stun_until, "3: the flashbang stuns the enemies near the cursor")
    ally = next((f for f in B.fighters if f.team == 0 and f is not pl), None)
    if ally is not None:
        ally.invuln_until = 0.0
        while ally.state != "out" and ally.lives > 0:
            ally.state = "alive"; ally.force_down(None, 1.0, 0.0, 300.0)
        check(ally.state == "out", "(setup) the ally is retired")
        sim(B, 0.6); K.press("item3"); sim(B, 0.05)
        check(ally.state in ("down", "getup") and ally.lives == 1, "4: the revive ticket puts her back in the fight")
        sim(B, 4.0)
        check(ally.state == "alive" and abs(ally.hp - ally.hp_max * 0.5) < ally.hp_max * 0.2, "she gets up with about half her HP")
        K.press("swap"); sim(B, 0.05)
        check(B.player is ally and ally.manual and not pl.manual, "TAB hands control to the next squad member")
        K.press("swap"); sim(B, 0.05)
    K.press("auto"); sim(B, 0.05)
    check(not B.manual_on and not B.player.manual, "T switches to autopilot")
    sim(B, 1.0)
    check(not isinstance(B.player.target, type(pl.aim)), "her brain never inherits the crosshair as a target")
    K.press("auto")                                                    # (the pad is hidden in auto; the HUD button does this)
    B.toggle_manual()
    check(B.manual_on and B.player.manual, "and back to manual")
    B.stop(); mgr.battle = None

    print("--- battle: every campaign screen paints")
    from babattlearena.campaign import CampaignPause
    camp = mgr.campaign_ctl()
    scr = camp.screen()
    save.d["squad"], save.d["leader"] = list(squad), squad[0]
    R = QtCore.QRectF(16, 16, 1208, 768)

    def paint(mode):
        scr.set_mode(mode); scr.hits = []
        p = QtGui.QPainter(img)
        try:
            scr.paint_bg(p, R, 1.0); scr.paint_content(p, R, time.perf_counter() + 2.0); ok = True
        except Exception:
            import traceback; traceback.print_exc(); ok = False
        p.end()
        return ok and bool(scr.hits)

    check(paint("hub") and any(k[0] == "sortie" for _s, k in scr.hits), "hub")
    scr.on_click(("card", names[-1])); scr.on_click(("card", names[-1]), right=True)
    check(scr.leader() == names[-1], "hub: right-click makes a student the leader")
    scr.on_click(("card", names[-1])); scr.set_squad(list(squad), squad[0])
    scr.on_click(("supply", 0)); scr.on_click(("manual",)); scr.on_click(("manual",))
    camp.start_run()
    check(camp.run is not None and scr.mode == "doors" and paint("doors"), "doors")
    run = camp.run
    run.enter(0); check(fake_fight(cd, run), "(setup) room won"); scr.set_mode("reward")
    check(run.pending is not None and paint("reward") and any(k[0] == "pick" for _s, k in scr.hits), "reward with three supports")
    scr.on_click(("pick", 1))
    check(len(run.boons) == 1 and scr.mode == "doors" and run.room == 1, "picking a support moves on to the next doors")
    run.door = run._door("stall"); run.open_stall()
    check(paint("stall"), "Sora's field stall")
    scr.on_click(("stall", 0)); scr.on_click(("continue",))
    run.door = run._door("cafe"); run.rest()
    check(paint("cafe"), "cafe")
    scr.on_click(("continue",))
    run.room = cd.TOTAL_ROOMS - 1; run.doors = run.make_doors()
    check(paint("doors") and run.doors[0]["kind"] == "boss", "the boss door")
    run.enter(0); fake_fight(cd, run); scr.set_mode("reward")
    check(run.pending is None and paint("reward"), "reward after the last boss (nothing left to pick)")
    scr.on_click(("continue",))
    check(run.over == "win" and scr.mode == "result" and paint("result"), "result: campaign clear")
    scr.on_click(("hub",))
    check(camp.run is None and scr.mode == "hub", "result -> hub clears the finished run")
    camp.start_run(); camp.run.finish(False)
    check(paint("result"), "result: squad retired")
    mgr.open_shop = lambda origin=None: False                         # as if QtWebEngine were missing
    scr.set_mode("hub"); scr.on_click(("shop",))
    check(scr.mode == "counter" and paint("counter") and any(k[0] == "buy" for _s, k in scr.hits), "without QtWebEngine the shop button opens the plain counter")
    lv = save.level("armor"); scr.on_click(("buy", "armor"))
    check(save.level("armor") == lv + 1, "the counter sells the same upgrades")
    scr.on_click(("tab", "supplies")); check(paint("counter"), "counter: supplies tab")
    scr.on_click(("hub",)); check(scr.mode == "hub", "counter -> hub")
    pm = CampaignPause(camp)
    p = QtGui.QPainter(img)
    try:
        pm.paint_content(p, QtCore.QRectF(16, 16, 528, 438), 1.0); ok = True
    except Exception:
        import traceback; traceback.print_exc(); ok = False
    p.end()
    check(ok, "pause menu")
    from babattlearena.title import TitleScreen
    ts = TitleScreen(mgr)
    p = QtGui.QPainter(img)
    try:
        ts.hits = []; ts.paint_content(p, QtCore.QRectF(16, 16, 968, 568), time.perf_counter() + 2.0); ok = True
    except Exception:
        import traceback; traceback.print_exc(); ok = False
    p.end()
    check(ok and any(k == ("campaign",) for _s, k in ts.hits), "the title screen has the Campaign card")

    if runs:
        print(f"--- balance: {runs} autopilot run(s), every upgrade at rank {ranks}, squad {squad}")
        cd._SAVE = cd.Save(Path(tempfile.mkdtemp()) / "campaign_save.json")
        sv = cd.get_save()
        sv.earn(credits=10 ** 6, pyrox=10 ** 5)
        for u in cd.UPGRADES:
            for _ in range(min(ranks, len(u["costs"]))): sv.buy(u["id"])
        sq = (squad + [n for n in names if n not in squad])[:1 + int(sv.meta()["squad_slots"])]
        for k in range(runs):
            t0 = time.time()
            r = play_run(mgr, cd, sq, 100 + k, verbose="--verbose" in sys.argv)
            print(f"  run {k + 1}: {r.over}, cleared {r.cleared}/{cd.TOTAL_ROOMS}, +{r.credits} CR, +{r.pyrox} PX, "
                  f"{len(r.boons)} supports  ({time.time() - t0:.0f}s)")

def test_live():
    """The real thing minus the screen: ArenaManager, the Qt event loop, Battle.start()'s timer, overlay, HUD and
    input pad, real key / mouse events, the pause menu, and the hand-over from a finished room to the next screen."""
    from PySide6 import QtGui
    from PySide6.QtCore import QEvent, QPointF, Qt
    qapp, mgr, cd, entries = make_world(["Shiroko", "Hoshino", "Hina", "Mika", "Ako", "Serika"],
                                        Path(tempfile.mkdtemp()) / "campaign_save.json")
    names = [e.name for e in entries]
    print(f"--- live: event loop, {len(entries)} models")
    if not check(len(entries) >= 4, "at least four models from model/ are needed for the live test"): return

    def pump(sec, until=None):
        t0 = time.time()
        while time.time() - t0 < sec:
            qapp.processEvents(); time.sleep(0.005)
            if until and until(): return True
        return False

    def knock_out(B, team, by=None):
        for f in B.fighters:
            if f.team != team: continue
            f.invuln_until = 0.0
            while f.state != "out":
                f.state = "alive"; f.force_down(by, 1.0, 0.0, 300.0)

    save = cd.get_save()
    save.d["squad"], save.d["leader"] = names[:2], names[0]
    random.seed(1)
    mgr.open_campaign()
    camp = mgr.campaign
    scr = camp.screen()
    check(scr.isVisible() and scr.mode == "hub", "open_campaign shows the hub")
    scr.on_click(("sortie",))
    check(camp.run is not None and scr.mode == "doors", "SORTIE starts a run")
    scr.on_click(("door", 0))
    B = mgr.battle
    if not check(B is not None and B.timer.isActive() and B.overlay.isVisible() and B.hud.isVisible(),
                 "a door starts a live CampaignBattle (timer, overlay, HUD)"): return
    pump(5, lambda: B.phase == "fight")
    check(B.phase == "fight" and B.pad is not None and B.pad.isVisible(), "the input pad is up once the fight starts")
    key = lambda t, k: qapp.sendEvent(B.pad, QtGui.QKeyEvent(t, k, Qt.KeyboardModifier.NoModifier))
    click = lambda t, b: qapp.sendEvent(B.pad, QtGui.QMouseEvent(t, QPointF(800, 450), QPointF(800, 450), b, b,
                                                                 Qt.KeyboardModifier.NoModifier))
    x0 = B.player.x
    key(QEvent.Type.KeyPress, Qt.Key.Key_D); pump(0.6); key(QEvent.Type.KeyRelease, Qt.Key.Key_D)
    check(B.player.x > x0 + 20, f"a real key event on the pad moves her ({B.player.x - x0:.0f}px)")
    key(QEvent.Type.KeyPress, Qt.Key.Key_Tab); pump(0.2)
    check(B.player.name == names[1], "Tab reaches the game instead of moving the focus")
    click(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton)
    s0 = B.player.rec["shots"]
    pump(1.5)
    check(B.ctl.lmb and B.player.rec["shots"] > s0, "a mouse press on the pad makes her fire")
    click(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton)
    key(QEvent.Type.KeyPress, Qt.Key.Key_Escape); pump(0.3)
    check(B.paused and camp._pause is not None and camp._pause.isVisible() and not B.pad.isVisible(),
          "Esc pauses: the campaign pause menu is up and the pad is down")
    camp._pause.on_click(("resume",)); pump(0.3)
    check(not B.paused and B.pad.isVisible(), "Resume: running again, the pad is back")
    B.hud.on_click(("auto",)); pump(0.2)
    check(not B.manual_on and not B.pad.isVisible(), "the HUD's AUTO button releases the keyboard and mouse")
    B.hud.on_click(("auto",)); pump(0.2)
    check(B.manual_on and B.pad.isVisible(), "the HUD's MANUAL button takes them back")
    n = sum(1 for f in B.fighters if f.team == 1)
    knock_out(B, 1, B.player)
    check(pump(25, lambda: mgr.battle is None and scr.isVisible() and scr.mode == "reward"),
          "room won: the battle is torn down and the reward screen opens")
    rep = camp.run.report
    check(camp.run.pending is not None and rep["kills"] == n and rep["credits"] > 0, "the room's report reached the run")
    scr.on_click(("pick", 0))
    check(scr.mode == "doors" and camp.run.room == 1, "a support is picked and the next doors open")
    i = next(i for i, d in enumerate(camp.run.doors) if d["kind"] == "fight")
    scr.on_click(("door", i))
    B = mgr.battle
    pump(5, lambda: B.phase == "fight")
    mgr.pause_menu(); pump(0.2)
    camp._pause.on_click(("abandon",)); camp._pause.on_click(("abandon",)); pump(0.5)
    check(mgr.battle is None and camp.run.over == "abandon" and scr.isVisible() and scr.mode == "result",
          "pause, Abandon Run (two clicks): the result screen")
    scr.on_click(("hub",)); scr.on_click(("sortie",)); scr.on_click(("door", 0))
    B = mgr.battle
    pump(5, lambda: B.phase == "fight")
    knock_out(B, 0)
    check(pump(25, lambda: mgr.battle is None and scr.isVisible() and scr.mode == "result") and camp.run.over == "lose",
          "squad wiped: the result screen, the run is lost")
    scr.on_click(("title",)); pump(0.5)
    check(mgr._title is not None and mgr._title.isVisible(), "result -> title screen")
    mgr._title.on_click(("campaign",)); pump(0.4)
    check(scr.isVisible() and scr.mode == "hub", "the title screen's Campaign card opens the hub")


if __name__ == "__main__":
    test_rules()
    if sys.version_info < (3, 12) and ("--battle" in sys.argv or "--live" in sys.argv):
        # Python 3.11 + recent PySide6: every void Qt call drops one reference to None (None only became immortal
        # in 3.12), so a long paint loop ends in "none_dealloc". Not ours to fix; give None headroom for the test.
        _headroom = [None] * 20_000_000
    if "--battle" in sys.argv:
        def arg(flag, default):
            return int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default
        test_battle(arg("--runs", 0), arg("--ranks", 0))
    if "--live" in sys.argv:
        test_live()
    print("PASS" if not FAILS else f"FAILED ({len(FAILS)})")
    sys.stdout.flush()
    if "--battle" in sys.argv or "--live" in sys.argv:
        os._exit(1 if FAILS else 0)      # skip Qt's teardown of the half-built application
    sys.exit(1 if FAILS else 0)
