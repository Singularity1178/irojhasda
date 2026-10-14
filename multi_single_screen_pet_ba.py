#!/usr/bin/env python3
"""
Multi Pet - Single Screen  -  Blue Archive 3D pets (one per .glb)
===================================================================
Same as multi_pet.py, but every character is locked to ONE screen: they
only ever spawn on it, walk on it, jump on windows that sit on it, and are
clamped if you try to drag them off the edge.
================================================================
Loads EVERY *.glb file in the model/ folder next to this script, creates
one independent character (own model, own rig, own animations, own dialogue)
for each of them, renders them with moderngl using a Blue-Archive-style
toon shader (cel ramp, tinted shadows, rim light, spec ticks, inverted-hull
outline), and shows them in transparent always-on-top PySide6 windows.

pip install PySide6 moderngl numpy "pymunk>=7,<8"

What lives where
  this file       entry point only: argument parsing, find_models(), main()
  bapet/          the app, one topic per module (map below)
  ragphys.py      the articulated ragdoll (pymunk). No Qt, no GL, so it can be
                    imported and tested on its own: `python test_ragphys.py`
  model/          the *.glb files, one character each
  dialogue/       everything they say, and who says it to whom
                    engine.py            look up one line for a character + event
                    conversation.py      pet-to-pet talking
                    system_watcher.py    computer-state tags (battery, cpu, ...)
                    data/*.json          the lines themselves
  Dialogue has no PySide import, so there is no import cycle and the lines can
  be edited as JSON without touching any code here.

Where to look in bapet/   ("I want to change ...")
  settings, presets, defaults ........ config.py
  shooting / combat numbers .......... combat_config.py   (+ combat_data.py for combat_index.json)
  ragdoll numbers .................... ragdoll_config.py
  loading a .glb, bones, clips ....... gltf.py, model.py
  animation blending, head look ...... rig.py
  toon shader, outline, drawing ...... shaders.py, renderer.py
  per-model overrides (iroha.py) ..... profiles.py, character.py
  control panel ...................... panel.py
  tray, menu, screen, z-order ........ app.py + app_*.py
  one pet (class Pet) ................ pet.py + the pet_* mixins:
      pet_state.py      animation playback, state changes, poke / pet / cut-in / launch
      pet_behavior.py   idle / walk / jump decisions, flying, landing
      pet_heading.py    3D heading, hand rotation, look-around, heights
      pet_window.py     window size, flags, click-through, riding a vehicle
      pet_speech.py     bubbles, particles, pet-to-pet chat hooks
      pet_input.py      hover, head-pat, mouse and wheel
      pet_render.py     per-frame procedural motion, drawing, click-through mask
      pet_attack.py     the shooting event: clips, ammo, tracers, hits
      pet_combat.py     combat AI: range, nerve, reload, retaliate, flee
      pet_cover.py      taking cover behind another student
      pet_ragdoll.py    going limp, shove, get up, edge slam
      pet_rag_step.py   per-frame ragdoll stepping (rod + pymunk)
      pet_rag_pose.py   physics pose -> bone rotations
      pet_skeleton.py   ragdoll bone lookup and pymunk skeleton spec
  Every pet_* / app_* file is a mixin: its methods use `self` exactly as before, and
  Pet / App just list them as base classes, so nothing else changed.

Uses ONLY these animations per model:
  Cafe_Idle, Cafe_Walk, Cafe_Reaction, Formation_Idle, Formation_Pickup,
  Exs_Cutin, Tactical_Start
plus Normal_Reload (the reload clip; optional - a model without it reloads from Formation_Idle)
and the attack / move clips used by the shooting event.

Interaction
  cursor            head/body look at it everywhere, light follows it
  together          they glance at each other and hold conversations of their
                    own (topics, reactions, greetings); a nearby cursor always
                    wins over looking at another character
  click             poke  (Cafe_Reaction)
  double-click      EX cut-in (Exs_Cutin + screen banner)
  drag / throw      Formation_Pickup, pendulum swing, gravity, bounce, squash
  ragdoll           right-click -> Ragdoll: she goes limp, tumbles, lands on the floor
                    or a window top, flops about, lies there, then stands back up.
                    Two cheap layers (see the RAG_* block), no physics engine.
  Ctrl + 1          the same, from anywhere in Windows, aimed at whoever is under
                    the cursor. A character also gets a short sound; bare desktop
                    is silent.
  blow mode         double-middle-click gusts wind from the cursor (hair physics)
  stroke over head  petting (move the cursor back and forth over her head)
  shooting          every so often a student opens fire on another student and keeps
                    firing at that same student until she ragdolls. Uses the model's own
                    <Stance>_Attack_Start / Ing / End clips (the Delay clip is no longer
                    played, so shots come back to back; see ATTACK_ANIMATIONS.md). A bullet
                    that crosses a different student on the way can hit her instead. A hit
                    student is only occasionally ragdolled, in the direction of the shot.
                    Right-click -> Shoot a student, or the Interact tab, to trigger it by hand.
  cover             a student whose model has Kneel_Attack_* clips (same names as Normal_Attack_*) may, when a
                    fight starts, run to another student standing on her side of the opponent, kneel just behind
                    her (Move_End_Kneel ends the run) and shoot from the kneel clips, using her as a shield:
                    she is much harder to hit while she does. See the COVER block of constants.
  ammo              combat_index.json gives every character "ammo_per_attack" (bullets fired during ONE
                    attack animation, spread across it) and "ammo_to_reload" (her magazine). Every bullet
                    costs one round; at 0 she plays Normal_Reload and refills. When a fight is over, a student
                    who is still on her feet and has spent rounds plays Normal_Reload and reloads too.
  combat AI         a student who is shot at fights or runs according to the situation, not dice
                    (see the "combat AI" block of constants): she keeps a preferred range, closes
                    in or backs off, relocates after a few shots, reloads, loses her nerve under
                    heavy fire, and aims worse at long range or while flinching. A runner heads for
                    the far end of her floor / window, never back through the shooter, and turns to
                    fight only when she is cornered or out of breath.
  3D walking        she moves the way she faces: rotate her to look left and she walks
                    left, face her toward / away from you and she walks into the screen
                    (nearer = bigger, farther = smaller). Turns at screen / depth ends.
                    Untick "Walk the way she faces" in the panel for the old behaviour.
  wheel             resize      shift+wheel / middle-drag / ctrl+drag  spin 3D
                    (rotate-drag: left/right = yaw, up/down = lean forward/back;
                     hold Shift as you start: left/right = lean sideways)
  right-click       menu for that character   tray icon + panel for the rest
  (Windows) they walk / jump / ride on top of your open windows, but only
            the ones on their screen

Picking the screen
  --screen N        use screen number N (0 = first in Qt's screen list)
  --screen cursor   use the screen the mouse is on at startup (default)
  --screen primary  use the primary screen
  Change it any time in the control panel (Characters tab).
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from PySide6 import QtWidgets

from bapet.app import App
from bapet.config import MODEL_DIR
from bapet.panel import QSS
from bapet.profiles import load_profile


def find_models(args):
    """Every .glb in the model/ folder becomes a character.

    --model still limits or overrides the list: give it a file, or a folder to
    take every .glb from, and neither has to be model/.

    A model whose profile says `pet=False` is left out of the desktop even when
    it sits in model/: that is how a PART lives next to the characters - Iroha's
    tank is exported as its own rigged .glb because that is the only copy with
    the hull texture in it, and it would otherwise stand around on the desktop
    as an eighth pet. It is still read, just as a texture source (see iroha.py).
    """
    if args.model:
        paths = []
        for part in args.model:
            p = Path(part)
            paths.extend(sorted(p.glob("*.glb")) if p.is_dir() else ([p] if p.exists() else []))
    else:
        paths = sorted(MODEL_DIR.glob("*.glb"), key=lambda q: q.name.lower())
    keep = [q for q in paths if load_profile(q)["pet"]]
    if len(keep) != len(paths):
        print(f"Skipped {len(paths) - len(keep)} part file(s), not a pet.")
    return keep


def main():
    ap = argparse.ArgumentParser(description="Single-screen desktop pets (one character per .glb in model/)")
    ap.add_argument("--model", nargs="*", help="glb file(s) or folder(s) to use (default: every *.glb in model/)")
    ap.add_argument("--dump", action="store_true", help="print bones / animations / materials for every model")
    ap.add_argument("--no-mask", action="store_true", help="disable click-through mask (whole window clickable)")
    ap.add_argument("--debug-tags", action="store_true",
                    help="print the watcher's tags, matched rule and context every poll "
                         "(console only - window titles are never written to a file)")
    ap.add_argument("--rag-debug", action="store_true",
                    help="draw the ragdoll capsules, joints and window colliders over each character")
    ap.add_argument("--rag-trace", type=int, nargs="?", const=60, default=0, metavar="N",
                    help="print per-frame ragdoll physics for the first N frames (default 60)")
    ap.add_argument("--rag-diag", type=int, nargs="?", const=180, default=0, metavar="N",
                    help="verbose per-character ragdoll diagnosis to the terminal: entry "
                         "state, spawn overlaps muted, every new contact + impulse, per-body "
                         "speeds, and a settled/still-moving verdict (default 180 frames)")
    ap.add_argument("--scale", type=float, default=None); ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--screen", default=None,
                    help="lock every character to one screen: 0, 1, ... / 'cursor' (default) / 'primary'")
    args = ap.parse_args()
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False); qapp.setStyleSheet(QSS)
    paths = find_models(args)
    if not paths:
        QtWidgets.QMessageBox.critical(
            None, "Desktop Pets",
            f"No .glb models found in:\n{MODEL_DIR}\n\n"
            f"Put your character models in that folder (it should already exist).")
        return 1
    try:
        app = App(qapp, paths, args)
    except Exception as e:
        traceback.print_exc()
        QtWidgets.QMessageBox.critical(None, "Desktop Pets - startup failed",
                                       f"{type(e).__name__}: {e}\n\nSee the console for details.\n"
                                       "Make sure your GPU drivers support OpenGL 3.3.")
        return 1
    code = qapp.exec()
    app.watcher.stop()                       # the polling thread is a daemon,
    return code                              # but stop it properly anyway


if __name__ == "__main__":
    sys.exit(main())
