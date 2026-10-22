#!/usr/bin/env python3
"""
Multi Pet - Single Screen - Blue Archive 3D pets (one per .glb)
===================================================================

Same as multi_pet.py, but every character is locked to ONE screen: they only
ever spawn on it, walk on it, jump on windows that sit on it, and are clamped
if you try to drag them off the edge.

Loads EVERY *.glb file in the model/ folder next to this script, creates one
independent character (own model, own rig, own animations, own dialogue) for
each of them, renders them with moderngl using a Blue-Archive-style toon
shader, and shows them in transparent always-on-top PySide6 windows.

    pip install PySide6 moderngl numpy "pymunk>=7"

Start-up: the TITLE SCREEN (babattlearena/title.py)
    Two choices:
        Desktop Pets   -> Student Select (below) and the desktop pets as before
        Battle Arena   -> the arena lobby: build two teams from avatar cards, change the rules
                          (gear button), BEGIN BATTLE. The students fight top-down with your
                          screen as the floor - real 3D models, real ragdolls (one life lost per
                          ragdoll, 3 lives by default), props and your actual windows as cover.
                          Pause / stop any time from the bar at the top or the tray icon.
        --arena       go straight to the Battle Arena lobby

Desktop Pets / Student Select
    The app no longer throws everybody onto the desktop at once. It opens the
    Student Select screen (bapet/picker.py): a Blue Archive style formation
    screen with every model in model/ shown live, playing Formation_Idle.
    Click students to put them in the formation, press DEPLOY and they drop
    onto your desktop. The screen can be closed and re-opened any time:
        * right-click any student -> Student Select...
        * the tray icon: left-click, or right-click -> Student Select...
    The tray icon's right-click menu is the full right-click menu of the
    active student (plus everything the old tray menu had), and still works
    when no student is on the desktop - so the app can always be reached
    and closed.
        --no-picker   skip the screen this run (last team comes straight back)
        --picker      show it even if "Open at startup" is switched off

Interaction (unchanged)
    cursor            head/body look at it; light follows it
    click             poke (Cafe_Reaction)
    double-click      EX cut-in (Exs_Cutin + screen banner)
    drag / throw      Formation_Pickup, pendulum swing, gravity, bounce
    right-click       the menu for that character (Ragdoll, Shoot, ...)
    Ctrl + 1          ragdoll whoever is under the cursor
    wheel             resize; shift+wheel / middle-drag / ctrl+drag spin 3D
    tray icon + panel for the rest

Picking the screen
    --screen N        use screen number N (0 = first in Qt's screen list)
    --screen cursor   use the screen the mouse is on at startup (default)
    --screen primary  use the primary screen
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from PySide6 import QtWidgets

from bapet.app import App
from babattlearena import install as install_arena
from bapet.config import MODEL_DIR
from bapet.panel import QSS
from bapet.picker import LoadingSplash
from bapet.profiles import load_profile
from voicelines import start_background_sync


def find_models(args):
    """Every .glb in the model/ folder becomes a character.

    --model still limits or overrides the list: give it a file, or a folder to
    take every .glb from, and neither has to be model/. A model whose profile
    says `pet=False` is left out of the desktop even when it sits in model/:
    that is how a PART lives next to the characters (see iroha.py).
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
    ap.add_argument("--anim-debug", action="store_true",
                    help="TEST ONLY: write the exact animation playing on each character over her - "
                         "clip name, time, state, phase, cross-fade (run_anim_debug.bat does this for you)")
    ap.add_argument("--rag-trace", type=int, nargs="?", const=60, default=0, metavar="N",
                    help="print per-frame ragdoll physics for the first N frames (default 60)")
    ap.add_argument("--rag-diag", type=int, nargs="?", const=180, default=0, metavar="N",
                    help="verbose per-character ragdoll diagnosis to the terminal: entry "
                         "state, spawn overlaps muted, every new contact + impulse, per-body "
                         "speeds, and a settled/still-moving verdict (default 180 frames)")
    ap.add_argument("--scale", type=float, default=None)
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--screen", default=None,
                    help="lock every character to one screen: 0, 1, ... / 'cursor' (default) / 'primary'")
    ap.add_argument("--no-picker", action="store_true",
                    help="skip the Student Select screen this run (the last team comes straight back)")
    ap.add_argument("--picker", action="store_true",
                    help="show the start screen even if 'Open at startup' is switched off")
    ap.add_argument("--arena", action="store_true",
                    help="skip the title screen and open the Battle Arena lobby")
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

    # Dialogue / voice line text for every student (voicelines/data/<Student>.wiki, from the wiki's
    # audio page). Already-saved students are skipped. Runs in the background and never blocks or
    # breaks start-up. Text only: no audio files are downloaded.
    try:
        start_background_sync([p.stem for p in paths])
    except Exception:
        traceback.print_exc()

    # A "Now Loading" card while every model is read and uploaded (that is the slow part).
    splash = None
    try:
        splash = LoadingSplash([p.stem for p in paths])
        splash.show_now(qapp)
    except Exception:
        traceback.print_exc(); splash = None

    try:
        # start_hidden: the students stay invisible for the whole load; they are shown (or handed
        # to the start screen) only once the splash has gone.
        app = App(qapp, paths, args,
                  progress=splash.set_progress if splash is not None else None,
                  start_hidden=True)
    except Exception as e:
        if splash is not None: splash.close()
        traceback.print_exc()
        QtWidgets.QMessageBox.critical(None, "Desktop Pets - startup failed",
                                       f"{type(e).__name__}: {e}\n\nSee the console for details.\n"
                                       "Make sure your GPU drivers support OpenGL 3.3.")
        return 1
    if splash is not None:
        splash.set_progress(1.0, "Ready!")      # make sure the bar ends full
        splash.close()

    # The Battle Arena (babattlearena/) hangs off the App; a failure there never blocks the pets.
    try:
        install_arena(app)
    except Exception:
        traceback.print_exc()

    # Title screen first (Desktop Pets / Battle Arena): everybody is held back until a choice is made.
    want_picker = args.picker or args.arena or (not args.no_picker and bool(app.cfg.get("picker_on_start", True)))
    if want_picker:
        try:
            if args.arena and getattr(app, "arena", None) is not None:
                app.start_with_title()
                app.arena.open_lobby()
            else:
                app.start_with_title()
        except Exception:
            traceback.print_exc()        # never block the pets because of the start screens

    # No start screen took the team (picker switched off): bring the held-back students up now.
    # A no-op when the title screen / Student Select already has them.
    app.reveal_students()

    code = qapp.exec()
    app.watcher.stop()                   # the polling thread is a daemon,
    return code                          # but stop it properly anyway


if __name__ == "__main__":
    sys.exit(main())
