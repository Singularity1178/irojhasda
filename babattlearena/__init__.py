"""babattlearena - the Battle Arena mode for the Blue Archive desktop pets.

Students fight in two teams with the computer screen as the floor (top-down). They keep their
real 3D models (rendered by their own toon renderer from above) and real 3D ragdolls (ragphys3d
with the screen turned into the floor). Desktop windows are walls they take cover behind - move
them mid-fight and everybody re-plans.

    install(app)    attach to bapet.App (done by multi_single_screen_pet_ba.py)

Modules
    manager    screen flow (title / lobby / battle / pause / results), pets put away during a match
    title      the title screen: Desktop Pets or Battle Arena
    lobby      team builder with avatar cards, settings, BEGIN BATTLE
    settings   arena rules + the settings screen (battle_arena_settings.json)
    battle     one match: rules, ballistics, explosions, EX skills, windows, match flow
    fighter    one student: animation, movement, shooting, ragdoll knockdown / get-up, lives
    ai         team commanders + per-student tactical brains (cover, flank, retreat, push ...)
    physics    ragphys3d re-labelled for a floor-shaped world, props and windows as colliders
    topdown    the oblique top-down camera
    obstacles  spawnable cover and how it is drawn
    geometry   rays, boxes, nav grid and A*
    effects    tracers, beams, muzzle flashes, explosions, damage numbers ...
    hud        overlay, HUD bar, pause menu, result screen
    theme      the Blue Archive look shared by every screen
"""
from .manager import ArenaManager, install  # noqa: F401
