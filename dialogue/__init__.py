"""Dialogue: everything the pets say, kept out of the pet code.

    DialogueEngine   give me a line for (character, event, computer states)
    ChatDirector     which two characters talk, and for how long
    Conversation     one character's side of a conversation
    SystemWatcher    what the computer is doing -> state tags
    StateReactor     one-off reactions when a tag starts or stops

The lines themselves live as JSON under ``data/``:

    data/default.json                 everyone's fallback lines and topics
    data/states.json                  default lines per computer state
    data/watcher_rules.json           which app/site/game means which tags
    data/archetypes/<name>.json       shared personality pools
    data/characters/<name>.json       one character, named after its .glb

Nothing in this package imports PySide, the renderer or the Pet class, so it
can be imported and tested on its own.
"""
from .engine import DialogueEngine, as_lines, fill, display_name, load_json, read_json, load_folder
from .conversation import Conversation, ChatDirector, ConversationField, turn
from .reactions import StateReactor
from .system_watcher import SystemWatcher

__all__ = [
    "DialogueEngine",
    "ChatDirector",
    "Conversation",
    "ConversationField",
    "StateReactor",
    "SystemWatcher",
    "turn",
    "as_lines",
    "fill",
    "display_name",
    "load_json",
    "read_json",
    "load_folder",
]