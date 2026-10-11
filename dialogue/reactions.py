"""One-off reactions to computer-state changes: "you opened Genshin again".

The watcher already produces an edge list (``("+", tag)`` when a tag starts
being active). This module turns those edges into at most one spoken line, and
only when the conditions are right:

    * a pool actually exists for ``state_enter`` / ``state_exit``
    * that tag is not on its cooldown, so alt-tabging does not spam
    * the chosen pet is not on its own cooldown, so the same one is not
      always the speaker

Deliberately no PySide and no Pet import: the caller passes in objects that
can ``say(text)`` and have a ``name``. That keeps this testable on its own and
means one randomly chosen pet speaks per event, not all of them.
"""
from __future__ import annotations

import random
import time

#: the events a tag can be asked to react to
ENTER = "state_enter"
EXIT = "state_exit"

#: default per-tag cooldown, so opening a game twice in an hour is not a speech
#: every time. Per-character files can shorten or lengthen this.
DEFAULT_TAG_COOLDOWN = 600.0

#: default per-pet cooldown, so the same character is not the speaker twice in
#: a row. Only applies while more than one pet is eligible.
DEFAULT_PET_COOLDOWN = 120.0

#: how long the "somebody else is talking" lock lasts, in seconds
PET_BUSY = 3.0

#: optional per-tag override for the cooldown, read from states.json. The
#: leading underscore marks it as a note rather than an event name, the same
#: convention every other data file uses.
COOLDOWN_KEY = "_reaction_cooldown"


class StateReactor:
    """Turns watcher edges into reactions, respecting cooldowns.

    ``engine`` is a DialogueEngine, ``watcher`` a SystemWatcher and ``pets``
    anything iterable of objects with ``.name`` and ``.say(text)``.
    """

    def __init__(self, engine, watcher, pets=None, tag_cooldown=None,
                 pet_cooldown=None, clock=None):
        self.engine = engine
        self.watcher = watcher
        self.pets = pets if pets is not None else []
        self.clock = clock or time.monotonic
        self.tag_cooldown = DEFAULT_TAG_COOLDOWN if tag_cooldown is None \
            else float(tag_cooldown)
        self.pet_cooldown = DEFAULT_PET_COOLDOWN if pet_cooldown is None \
            else float(pet_cooldown)
        self._tag_at = {}          # tag -> when it last spoke
        self._pet_at = {}          # pet name -> when it last spoke
        self._busy_until = 0.0

    # ------------------------------------------------------------------ state
    def reconfigure(self, pets=None):
        """Point at a new pet list (the panel adds and removes characters)."""
        if pets is not None:
            self.pets = list(pets)

    def cooldown_for(self, tag):
        """Seconds this tag wants to stay quiet after speaking.

        The per-tag override lives in ``states.json`` next to the tag's own
        lines - that is the file that already owns everything about a tag, and
        it is shared rather than per-character.
        """
        block = self.engine.state_pools.get(tag)
        custom = block.get(COOLDOWN_KEY) if isinstance(block, dict) else None
        try:
            return float(custom) if custom is not None else self.tag_cooldown
        except (TypeError, ValueError):
            return self.tag_cooldown

    def ready(self, tag, now=None):
        now = self.clock() if now is None else now
        last = self._tag_at.get(tag)
        return last is None or (now - last) >= self.cooldown_for(tag)

    def forget(self, tag):
        """Drop the cooldown on a tag (used when the rules change)."""
        self._tag_at.pop(tag, None)

    # ---------------------------------------------------------------- choices
    def _eligible(self, now):
        """Pets that could speak right now, in their existing order."""
        out = []
        for pet in self.pets:
            # speech_ok lets a pet opt out (muted, mid-bubble, off screen)
            # without the reactor knowing anything about the pet code.
            ok = getattr(pet, "speech_ok", True)
            if callable(ok):
                try:
                    ok = ok()
                except Exception:
                    ok = False
            if not ok:
                continue
            if not callable(getattr(pet, "say", None)):
                continue
            name = getattr(pet, "name", "")
            if name and (now - self._pet_at.get(name, -1e9)) < self.pet_cooldown:
                continue
            out.append(pet)
        return out

    def _pick_pet(self, now):
        """One pet, chosen at random - never all of them together."""
        pool = self._eligible(now)
        if not pool:
            return None
        return random.choice(pool)

    # ----------------------------------------------------------------- events
    def poll(self, force=False):
        """Consume edges and speak at most one line.

        Returns the ``(tag, event, line)`` it decided to say, or None. Safe to
        call every frame: it does nothing until the watcher reports a change.

        Edges are drained on every call, so nothing queues up while a pet is
        busy - a burst of alt-tabbing produces one reaction, not ten.
        """
        now = self.clock()
        edges = self.watcher.drain_edges()
        if not edges:
            return None
        if now < self._busy_until and not force:
            return None

        # Most important change first: edges arrive in no particular order.
        # Prefer the document's own priority order so the tag that outranks the
        # rest is the one that speaks, falling back to the list order.
        order = self.engine.state_order
        rank = {t: i for i, t in enumerate(order)}

        def weight(edge):
            tag = edge[1]
            return (0 if edge[0] == "+" else 1, rank.get(tag, len(rank)), tag)

        for sign, tag in sorted(edges, key=weight):
            event = ENTER if sign == "+" else EXIT
            if not self.ready(tag, now):
                continue
            pet = self._pick_pet(now)
            if pet is None:
                return None
            line = self.engine.get(pet.name, event, [tag])
            if not line:
                continue                     # no pool here: try the next edge
            self._tag_at[tag] = now
            self._pet_at[pet.name] = now
            self._busy_until = now + PET_BUSY
            try:
                pet.say(line)
            except Exception:
                # Nothing was actually said, so do not let the cooldowns stand
                # - otherwise one broken pet silences this tag for ten minutes.
                self._tag_at.pop(tag, None)
                self._pet_at.pop(pet.name, None)
                self._busy_until = 0.0
                return None
            return (tag, event, line)
        return None

    # ------------------------------------------------------------------ debug
    def reset(self):
        self._tag_at.clear()
        self._pet_at.clear()
        self._busy_until = 0.0