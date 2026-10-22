"""Third-party imports that can fail, checked once, with the original friendly messages.

Importing this module (the package __init__ does it first) means every other module can
import PySide6 / moderngl / numpy / dialogue without repeating the checks.
"""
from __future__ import annotations

import os
import sys

if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"          # window positioning needs X11

try:
    import numpy as np  # noqa: F401
    import moderngl  # noqa: F401
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
except ImportError as _e:                           # pragma: no cover
    print("Missing dependency:", _e)
    print('Run:  pip install PySide6 moderngl numpy "pymunk>=7,<8"')
    sys.exit(1)

# Sora's shop (sorashop/shop.py) shows the Spine scene in a QtWebEngine view. QtWebEngineWidgets has to
# be imported before the QApplication exists, so it is done here. Optional: without it the shop icon on
# the main menu just prints a hint and the rest of the app is unaffected.
try:
    from PySide6 import QtWebEngineWidgets  # noqa: F401
    HAVE_WEBENGINE = True
except ImportError as _e:                           # pragma: no cover
    HAVE_WEBENGINE = False
    print("QtWebEngine not available, Sora's shop is disabled:", _e)

# The articulated ragdoll is optional: without pymunk every pet falls back to the
# legacy rod ragdoll, so the app still runs (cfg ragdoll_engine="legacy").
try:
    import ragphys
    from ragphys import RagWorld, HAVE_PYMUNK
except ImportError as _e:                           # pragma: no cover
    ragphys = None
    RagWorld = None
    HAVE_PYMUNK = False
    print("pymunk not available, falling back to the rod ragdoll:", _e)

# The fully 3D ragdoll (cfg ragdoll_engine="3d") is pure Python - no pymunk needed -
# so it is always there unless ragphys3d.py itself is missing from the folder.
try:
    import ragphys3d
    from ragphys3d import Rag3DWorld
except ImportError as _e:                           # pragma: no cover
    ragphys3d = None
    Rag3DWorld = None
    print("ragphys3d.py not found next to the script; the 3D ragdoll is unavailable:", _e)

# Dialogue lives in its own package (no PySide import, so no cycle). It must sit in the
# same folder as the main script.
try:
    from dialogue import (DialogueEngine, ChatDirector, Conversation,  # noqa: F401
                          ConversationField, SystemWatcher, StateReactor)
except ImportError as _e:                           # pragma: no cover
    print("Missing package:", _e)
    print("dialogue/ must sit in the same folder as this script.")
    sys.exit(1)

# Audio is optional: the pets never need it, so a Qt build without the multimedia
# plugins must still start (it just loses the "nothing under the cursor" sound).
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAVE_AUDIO = True
except ImportError:                                # pragma: no cover
    QAudioOutput = QMediaPlayer = None
    HAVE_AUDIO = False
