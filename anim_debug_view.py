#!/usr/bin/env python3
"""
Animation debugger - the whole app, with the animation written over each character.

Every .glb in model/ becomes a character and she lives her normal life: she wanders,
looks at the cursor, gets petted, cut-ins, fights, kneels for cover, ragdolls and
gets back up. The only difference is the black panel in the top-left corner of her
own window, which says what she is playing right now:

    Ayane  [shoot]                       <- her name, and her state in its colour
    clip  Normal_Attack_Ing              <- the clip actually on screen, by its own
    t  0.84/1.36s once x1.00             <- time / duration, loop, speed, ENDED
    state=shoot key=alert in-state 2.4s  <- the state machine's own numbers
    atk=ing Normal ammo 4/30 FIRED       <- the event driving her (combat / flee / cover)
    DRAGGING / air=thrown / on-window    <- how she is being moved
    fade 0.35 <- Cafe_Walk               <- the clip she is cross-fading out of
    recent Cafe_Walk > Exs_Cutin         <- the last few clips that started

A key that cannot find its clip says so (`(key wanted Normal_Reload)`), because a
substitute clip is the usual reason a beat does not look like the beat you asked for.

Everything else is untouched: this is a viewer, not a different app. Options are
passed straight through, e.g.

    run_anim_debug.bat --screen primary
    run_anim_debug.bat --model model\\Ayane.glb --scale 1.4
    run_anim_debug.bat --rag-debug          (both overlays at once)

The same thing is available in a normal run with --anim-debug, or by ticking
"Label the animation" in the panel's Debug section.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import multi_single_screen_pet_ba as pets
from bapet.pet_animdbg import legend


def main(argv):
    # The real entry point, with the flag forced on. Everything it does - loading
    # the models, the panel, the tray, dialogue, combat - is the same run.
    sys.argv = [str(HERE / "multi_single_screen_pet_ba.py"), "--anim-debug", *argv]
    print("=" * 78)
    print("[anim-debug] ON - the clip playing on each character is written over her.")
    print(f"[anim-debug] state colours: {legend()}")
    print("[anim-debug] options are passed through, e.g. --screen primary --rag-debug")
    print("=" * 78, flush=True)
    return pets.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))