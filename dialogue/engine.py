"""Line lookup: give me a line for (character, event, computer states).

No PySide, no Pet, no App imports, so this stays testable on its own and can
never build an import cycle with the pet code. Everything it says comes from
the JSON files in ``data/``.

Lookup chain, first pool with a usable line wins:

    character + state + event     Hoshino's own "poked while battery low" lines
    character + state             Hoshino's general low-battery lines
    archetype + state             whoever is sleepy, low battery
    default  + state              everyone's fallback low-battery lines
    character + event             Hoshino's own "poke" lines
    archetype + event
    default  + event              today's POKE_LINES

Because most pools are empty the chain degrades to the plain event lookup, so
adding a single line for one character in one situation leaves everything else
alone.

`state_enter` / `state_exit` are ordinary events, asked for by whoever holds a
``SystemWatcher``. They need no special handling here: a tag's
``state_enter`` pool is simply a pool scoped to that event name.
"""
from __future__ import annotations

import json
import random
import re
from collections import deque
from pathlib import Path

from .wikilines import WikiLines, PART_SEP, EVENT_KEYS

# how many recently used lines to remember per (character, event)
HISTORY = 6

# keys starting with this are comments/notes in the data files
META = "_"

# inside a states/<tag> object, the key holding that tag's general lines
GENERAL = "*"


def load_json(path, default=None):
    """Read a JSON file, returning `default` instead of raising on a bad one."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def read_json(path):
    """Read a JSON file, or None when it is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def load_folder(path):
    """Every *.json in a folder, keyed by file stem. '_'-prefixed files are
    templates and are skipped. A broken file is reported and ignored."""
    out = {}
    try:
        files = sorted(Path(path).glob("*.json"))
    except Exception:
        return out
    for f in files:
        if f.stem.startswith(META):
            continue
        data = read_json(f)
        if data is None:
            print(f"[dialogue] could not read {f.name} - ignoring it.")
            continue
        if isinstance(data, dict):
            out[f.stem] = data
    return out


def as_lines(pool):
    """Accept a list of lines, a single line, or a list of [line, tag] turns."""
    if pool is None:
        return []
    if isinstance(pool, str):
        return [pool]
    out = []
    for item in pool:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
            out.append(item[0])
    return out


def fill(text, values):
    """Substitute {name} / {me} / {other} / {pronoun} and any extra keys.

    Plain replace, never str.format, so a line containing a stray brace or a
    placeholder we do not know about is still spoken verbatim.
    """
    for k, v in values.items():
        if v is None:
            continue
        text = text.replace("{" + k + "}", str(v))
    return text


#: A trailing costume/variant qualifier, e.g. "Hina (Dress)" or "Momoi (Maid)".
#: Model files are named that way, but nobody says "Hina (Dress)" out loud.
_NAME_QUALIFIER = re.compile(r"\s*\([^()]*\)\s*")


def display_name(name):
    """"Hina (Dress)" -> "Hina", "Momoi (Maid)" -> "Momoi".

    Only for text a character speaks or the UI shows - normalize() below still keys
    off the whole name, so her dialogue file is still found. Falls back to the name
    as given when stripping would leave nothing (e.g. a file called "(Dress).glb").
    """
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    stripped = _NAME_QUALIFIER.sub(" ", text).strip(" -_,.")
    return stripped or text


def _fmt_percent(value):
    """42 -> '42%'. A value that is not a number is passed through as typed."""
    try:
        return f"{int(value)}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_minutes(value):
    """12 -> '12 minutes'. Non-numbers are passed through as typed."""
    try:
        return f"{int(value)} minutes"
    except (TypeError, ValueError):
        return str(value)


#: context key -> how it is rendered in a line. The watcher only publishes
#: plain values; the phrasing lives here so lines can read naturally.
CONTEXT_FORMATTERS = {
    "battery": _fmt_percent,
    "focus_minutes": _fmt_minutes,
    "session_minutes": _fmt_minutes,
}


class DialogueEngine:
    """Resolves one line per call. Character and archetype files load lazily,
    so a folder with no per-character files costs nothing."""

    def __init__(self, root=None, history=HISTORY, voicelines=None):
        self.root = Path(root) if root else Path(__file__).resolve().parent / "data"
        self.history_size = history
        # Each student's own wiki voice lines (voicelines/data/<Student>.wiki). For the events in
        # wikilines.EVENT_KEYS these are used on their own; everything else in this file is the
        # fallback for a student / event the wiki data does not cover. voicelines=False turns it off.
        self.wiki = None if voicelines is False else (
            voicelines if isinstance(voicelines, WikiLines) else WikiLines(voicelines))

        default = load_json(self.root / "default.json")
        self.reactions = default.get("reactions") or {}
        self.chat_topics = default.get("chat_topics") or {}
        self.topic_labels = default.get("topic_labels") or {}
        self.audience_lines = default.get("audience_lines") or {}

        states_doc = load_json(self.root / "states.json")
        self.state_pools = states_doc.get("states") or {}
        self.state_order = [t for t in (states_doc.get("_priority_order") or []) if isinstance(t, str)]

        self.archetypes = load_folder(self.root / "archetypes")
        self._chars = {}                        # normalized name -> doc
        self._recent = {}                       # (name, event) -> deque of recent lines
        self._context = {}                      # watcher placeholders, see set_context

    # ------------------------------------------------------------------ data
    def character(self, name):
        """That character's own file, or {} if she does not have one."""
        key = self.normalize(name)
        if key in self._chars:
            return self._chars[key]
        doc = {}
        data = read_json(self.root / "characters" / (key + ".json"))
        if isinstance(data, dict):
            doc = data
        self._chars[key] = doc
        return doc

    def archetype(self, name):
        """The shared personality file this character points at, or {}."""
        key = str((self.character(name) or {}).get("archetype") or "")
        return self.archetypes.get(key, {})

    #: exposed as a method too, so callers holding an engine do not need the module
    display_name = staticmethod(display_name)

    @staticmethod
    def normalize(name):
        """"Hina (Dress)" -> "hinadress". Same rule as norm_name() in the pet
        file, repeated here so this module stays importable on its own."""
        return re.sub(r"[^a-z0-9]", "", str(name).lower())

    def set_context(self, context):
        """Hand over the watcher's context so lines can use ``{app}`` and friends.

        The values are formatted once, here, and then treated as ordinary
        placeholder values. Unknown or empty entries are dropped, so ``{app}``
        with nothing in front stays as typed rather than speaking a blank.
        """
        values = {}
        for key, value in (context or {}).items():
            if value is None or value == "":
                continue
            formatter = CONTEXT_FORMATTERS.get(key)
            values[key] = formatter(value) if formatter else value
        self._context = values
        return values

    def context(self):
        return dict(self._context)

    def order_states(self, states):
        """Watcher tags, most important first. Unknown tags keep their order."""
        states = [s for s in (states or ()) if isinstance(s, str) and s]
        if not states or not self.state_order:
            return list(states)
        rank = {t: i for i, t in enumerate(self.state_order)}
        return sorted(states, key=lambda t: rank.get(t, len(rank)))

    # ---------------------------------------------------------------- lookup
    @staticmethod
    def _pool(mapping, key, event=None):
        """One event pool out of a {event: lines} table.

        A list value is the general pool for that whole scope (a character's
        low-battery lines, say). A dict value can also narrow to one event and
        carries '*' for the general lines.
        """
        value = (mapping or {}).get(key)
        if isinstance(value, dict):
            # '_'-prefixed keys in a tag block are notes (a cooldown override,
            # a reminder to self), never an event pool.
            got = as_lines(value.get(event)) if event and not str(event).startswith(META) else []
            return got or as_lines(value.get(GENERAL))
        return as_lines(value)

    def _chain(self, name, event, states):
        """Candidate pools, best first. Only the pools that exist are returned."""
        char = self.character(name)
        arch = self.archetype(name)
        cs, as_ = char.get("states"), arch.get("states")
        chain = []
        for tag in self.order_states(states):
            chain.append(self._pool(cs, tag, event))          # character + state + event
            chain.append(self._pool(cs, tag))                 # character + state
            chain.append(self._pool(as_, tag, event))         # archetype + state + event
            chain.append(self._pool(as_, tag))                # archetype + state
            chain.append(self._pool(self.state_pools, tag, event))   # default + state + event
            chain.append(self._pool(self.state_pools, tag))          # default + state
        chain.append(as_lines(char.get("reactions", {}).get(event)))
        chain.append(as_lines(arch.get("reactions", {}).get(event)))
        chain.append(as_lines(self.reactions.get(event)))
        return chain

    def _wiki_pool(self, name, event):
        """Her own wiki lines for this event, or [] when there are none to use."""
        if self.wiki is None:
            return []
        try:
            return self.wiki.lines(name, event)
        except Exception:
            return []

    def _choose(self, name, event, chain):
        """First pool with a line we have not just used; small pools may repeat."""
        recent = self._recent.get((name, event)) or ()
        for pool in chain:
            if not pool:
                continue
            fresh = [l for l in pool if l not in recent]
            return random.choice(fresh if fresh else pool)
        return None

    def _speak(self, character, event, line, values):
        """Remember the line so it is not repeated, then fill in the blanks."""
        recent = self._recent.setdefault((character, event),
                                        deque(maxlen=self.history_size))
        recent.append(line)
        char = self.character(character)
        # watcher context first, so an explicit value still wins over it, and
        # name/me/pronoun last so a line can never be spoken with a blank
        # speaker.
        merged = dict(self._context)
        merged.update(values)
        who = display_name(character)
        merged.setdefault("name", who)
        merged.setdefault("me", who)
        merged.setdefault("pronoun", char.get("pronoun"))
        return fill(line, merged)

    def get(self, character, event, states=(), **values):
        """One line for `character` reacting to `event` under `states`.

        `states` is the watcher's tag set; the most important one that has a
        line pool wins, so passing several tags is safe. Returns None when
        nothing at all is defined - callers should cope with silence.
        """
        # her own wiki voice line first and alone; the generic chain only when she has none
        wiki = self._wiki_pool(character, event)
        chain = [wiki] if wiki else self._chain(character, event, states)
        line = self._choose(character, event, chain)
        return self._speak(character, event, line, values) if line else None

    def get_any(self, character, events, states=(), **values):
        """Same, but drawing from several events at once (the panel's 'Say')."""
        events = [events] if isinstance(events, str) else list(events or ())
        pool = []
        for ev in events:
            wiki = self._wiki_pool(character, ev)
            if wiki:
                # events can share wiki rows (idle and poke both use Cafe_monolog): keep one copy
                pool.extend(l for l in wiki if l not in pool)
                continue
            for candidate in self._chain(character, ev, states):
                pool.extend(candidate)
        key = "+".join(events)
        line = self._choose(character, key, [pool])
        return self._speak(character, key, line, values) if line else None

    # -------------------------------------------------------------- chat bits
    def topics(self):
        """Shared conversation topics: name -> [(line, tag), ...]."""
        return self.chat_topics

    def topic_label(self, topic, fallback="chatting"):
        return self.topic_labels.get(topic, fallback)

    def topic_label_text(self):
        return ", ".join(self.topic_labels.values())

    def audience(self, verb):
        """A nearby character's comment on what the user just did."""
        return as_lines(self.audience_lines.get(verb))