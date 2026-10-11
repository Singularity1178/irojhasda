"""Pet-to-pet conversations: who talks to whom, in which order, for how long.

This used to live as methods on Pet and as a little trio on App. It only ever
needs a small surface on a pet - ``say``, ``enter``, ``emit``, ``free``,
``feet_pos``, ``isVisible``, ``W`` / ``H``, ``peers`` - so it never has to know
anything about rendering.

A ``Conversation`` owns one character's side of a chat: the turn list, whose
turn it is, who it is talking to and how long they have left. ``ChatDirector``
sits above that and owns the decisions that involve more than two pets: which
pair to pair up, the round-robin introduction, ending everything.
"""
from __future__ import annotations

import random
import time

try:                                   # a Conversation can be used stand-alone
    from .engine import display_name
except ImportError:                    # pragma: no cover
    from engine import display_name

# how long a topic is avoided after it was used, per chat kind
COOL_SHORT = (60, 150)                    # greeting
COOL_LONG = (90, 240)                     # a real conversation

# first turn comes fast, later turns breathe
FIRST_GAP = (0.2, 0.7)
LATER_GAP = (2.6, 5.0)
FIRST_TURN_SHORTER = 1.4


def turn(text, tag="plain"):
    """One line of a conversation: the text plus how the listener reacts.

    tag: "plain"  nothing special
          "reply" a normal answer
          "warm"   the listener sometimes answers with a heart
    """
    return (text, tag)


class Conversation:
    """One character's side of a pet-to-pet chat."""

    def __init__(self, pet, dialogue=None):
        self.pet = pet
        self.dialogue = dialogue             # optional, only used for topics
        self.lines = None                   # [(text, tag), ...] or None
        self.other = None
        self.index = 0
        self.next_t = 0.0
        self.until = 0.0
        self.lead = False                   # exactly one pet drives the turns
        self.topic = ""
        self.meet_target = None             # walking over to start talking
        self.avoid = {}                     # topic -> cool-down time
        self.last_topic = ""

    # ------------------------------------------------------------- eligibility
    def free(self):
        """True when she can start / continue a conversation (not busy, not mid-shot).

        A pet that is ragdolling is never free: `grounded` is already False while
        she tumbles, and `ragdoll` also keeps her out once she is back on her feet.
        """
        cfg = self.pet.cfg
        return (cfg["chat"] and not self.pet.dragging and self.pet.grounded
                and not getattr(self.pet, "ragdoll", False)
                and self.pet.state != "shot" and self.pet.bubble is None)

    def in_chat(self, now=None):
        now = time.time() if now is None else now
        return now < self.until and self.other is not None

    def busy(self):
        """True while a conversation is running (or about to) - blocks wander plans."""
        return self.lines is not None or self.meet_target is not None

    # ------------------------------------------------------------------ topics
    def own_topics(self):
        """Shared topics, plus any this character brings along."""
        base = dict(self.dialogue.topics()) if self.dialogue is not None else {}
        base.update(self.dialogue.character(self.pet.name).get("chat_topics") or {})
        return base

    def pair_topics(self, other):
        """Banter written for this exact pairing, or {} to use the shared topics."""
        if self.dialogue is None or other is None:
            return {}
        mine = self.dialogue.character(self.pet.name).get("pair_lines") or {}
        return mine.get(self.dialogue.normalize(other.name)) or {}

    def topic_lines(self, topic, other=None):
        """The turns for one topic: this pair's own lines, else the general ones."""
        pair = self.pair_topics(other)
        if topic in pair:
            raw = pair[topic]
            if isinstance(raw, str):
                return [turn(raw)]
            return [turn(t) if isinstance(t, str) else tuple(t) for t in raw]
        return list(self.own_topics().get(topic) or ())

    def pick_topic(self, other=None):
        """A topic neither of them used recently."""
        now = time.time()
        topics = self.own_topics()
        topics.update(self.pair_topics(other))
        if not topics:
            return ""
        pool = [t for t in topics
                if self.avoid.get(t, 0.0) <= now
                and (other is None or other.conv.avoid.get(t, 0.0) <= now)]
        return random.choice(pool) if pool else random.choice(list(topics))

    # ------------------------------------------------------------- turn taking
    def say(self, text, listener=None):
        """Speak a pet-to-pet line, resolving {me} / {other} / {name}.

        Names are spoken without their costume qualifier: a pet-to-pet line reads
        "Hi Momoi.", never "Hi Momoi (Maid)." - normalize() still keys off the full
        name, so pairing and line lookup are unaffected.
        """
        short = getattr(self.dialogue, "display_name", display_name)
        me = short(self.pet.name)
        other = short(listener.name) if listener is not None else me
        text = (text.replace("{me}", me).replace("{other}", other).replace("{name}", me))
        self.pet.say(text)
        self.pet.gaze_peer = listener if listener is not None else None
        self.pet.gaze_left = max(self.pet.gaze_left, 3.4)
        if listener is not None and not listener.conv.in_chat() \
                and listener.state in ("idle", "walk", "alert"):
            listener.gaze_peer = self.pet
            listener.gaze_left = max(listener.gaze_left, 3.4)

    def step(self, now):
        """Say the next line of the conversation. Returns False once it is over."""
        if self.lines is None:
            return False
        other = self.other
        if other is None or not self.lead:
            return False                                     # the follower just listens
        if not other.isVisible() or not self.pet.isVisible():
            self.end(); return False
        if now < self.next_t:
            return True
        if self.index >= len(self.lines):
            self.end(); return False
        text, tag = self.lines[self.index]
        # even turn = self speaks, odd turn = the other pet replies
        speak, listen = (self.pet, other) if self.index % 2 == 0 else (other, self.pet)
        self.index += 1
        gap = FIRST_TURN_SHORTER if self.index == 1 else random.uniform(*LATER_GAP)
        self.next_t = now + gap
        speak.conv.say(text, listen)
        if listen.state in ("idle", "alert", "walk"):
            listen.enter("alert", dur=gap + 2.6)
        if tag == "warm" and random.random() < 0.5:
            listen.emit("heart", 3)
        if random.random() < 0.35:
            speak.emit("star", 2)
        # both stay locked in for the whole conversation
        for p in (self.pet, other):
            p.conv.until = max(p.conv.until, self.next_t + 1.2)
        return True

    # ------------------------------------------------------------ start / stop
    def _begin(self, other, topic, lines, cool_range):
        """Shared setup for both ways a chat can start."""
        now = time.time()
        cool = now + random.uniform(*cool_range)
        self.avoid[topic] = other.conv.avoid[topic] = cool
        self.last_topic = other.conv.last_topic = topic
        for p in (self.pet, other):
            p.conv.lines = lines
            p.conv.index = 0
            p.conv.next_t = now + random.uniform(*FIRST_GAP)
            p.conv.other = other if p is self.pet else self.pet
            p.conv.lead = p.conv.other is other       # exactly one pet drives the turns
            p.conv.topic = topic

    def greet_near(self, other):
        """Short two-line hello between this pet and `other` (no distance check)."""
        if other is None or other is self.pet:
            return False
        if self.busy() or other.conv.busy():
            return False
        if not (self.free() and other.conv.free()):
            return False
        topic = "greeting"
        pool = self.topic_lines(topic, other) or [turn("Hello, {other}.", "plain")]
        self._begin(other, topic, random.sample(pool, min(2, len(pool))), COOL_SHORT)
        self.pet.gaze_peer = other; self.pet.gaze_left = 5.0
        other.gaze_peer = self.pet; other.gaze_left = 5.0
        return True

    def start(self, other):
        """Begin a conversation with `other` immediately (no approach step)."""
        if other is None or other is self.pet:
            return False
        if self.busy() or other.conv.busy():
            return False
        if not (self.free() and other.conv.free()):
            return False
        topic = self.pick_topic(other)
        lines = self.topic_lines(topic, other)
        if not lines:
            return False
        self._begin(other, topic, lines, COOL_LONG)
        # face each other for the whole conversation
        self.pet.gaze_peer = other; self.pet.gaze_left = 99.0
        other.gaze_peer = self.pet; other.gaze_left = 99.0
        return True

    def greet(self):
        """One-line hello to whoever is nearest - used when two characters pass."""
        for q in self.pet.peers(max_dist=self.pet.W * 0.85):
            if q.conv.in_chat() or q.conv.busy() or q.dragging:
                continue
            return self.greet_near(q)
        return False

    def end(self):
        """Finish the conversation and let both get back to normal."""
        other = self.other
        for p in (self.pet, other):
            if p is None:
                continue
            p.conv.lines = None; p.conv.other = None; p.conv.index = 0; p.conv.next_t = 0.0
            p.conv.lead = False; p.conv.until = 0.0; p.conv.meet_target = None
            if p.gaze_peer is self.pet:
                p.gaze_peer = None; p.gaze_left = 0.0
            if p.state == "alert" and not p.dragging and p.grounded:
                p.enter("idle"); p.plan_next()
        self.lines = None; self.other = None; self.topic = ""

    def abort(self, why=""):
        """Something else happened (drag / poke / cut-in) - drop out of the chat."""
        if not (self.lines is not None or self.other is not None or self.meet_target is not None):
            return
        if why and self.pet.cfg["speech"]:
            self.pet.say(why, 2.0)
        self.end(); self.meet_target = None

    def stop(self):
        """User-driven stop (menu / panel)."""
        self.abort()

    # -------------------------------------------------------------- per frame
    def converse(self, dt, now):
        """Continue an ongoing conversation, or let one start."""
        cfg = self.pet.cfg
        if self.lines is not None:
            # a chat survives a bubble or a wander tick, but not a drag / fall / cut-in
            if self.pet.dragging or not self.pet.grounded or self.pet.state == "shot":
                self.abort(); return
            self.step(now)
            return
        if not cfg["chat"]:
            return
        if self.meet_target is not None:
            self.meet(now); return
        # roll for a spontaneous conversation
        if not cfg["chat_rate"] or not self.pet.grounded or self.pet.dragging \
                or self.pet.state != "idle":
            return
        if self.pet.bubble is not None:
            return
        if random.random() > dt * 0.012 * cfg["chat_rate"]:
            return
        for q in self.pet.peers(max_dist=self.pet.W * 3.0):
            if q.conv.free() and not q.conv.busy():
                # optionally walk over before talking
                if cfg["chat_meetup"] and abs(q.feet_pos()[0] - self.pet.feet_pos()[0]) \
                        > (self.pet.W + q.W) * 0.5:
                    self.meet_target = q
                    self.pet.enter("walk", dur=8.0)
                    return
                self.start(q)
                return

    def meet(self, now):
        """The 'walk over to talk' step: approach, then begin."""
        other = self.meet_target
        if other is None or not other.isVisible() or not self.pet.grounded or self.pet.dragging:
            self.meet_target = None
            return
        gap = abs(other.feet_pos()[0] - self.pet.feet_pos()[0])
        if gap < max(1.0, (self.pet.W + other.W) * 0.45):
            self.meet_target = None
            if self.pet.state == "walk":
                self.pet.enter("idle"); self.pet.plan_next()
            self.start(other)
            return
        if self.pet.state != "walk":
            self.pet.enter("walk", dur=8.0)
        self.pet.walk_dir = 1 if other.feet_pos()[0] > self.pet.feet_pos()[0] else -1
        self.pet.gaze_peer = other; self.pet.gaze_left = 0.4

    def pass_greet(self, dt):
        """Proximity greet: two characters brushing past each other say hello."""
        cfg = self.pet.cfg
        if not cfg["chat"] or not cfg["chat_rate"] or self.pet.dragging:
            return
        if self.pet.state != "walk" or not self.pet.grounded:
            return
        if self.busy() or self.meet_target is not None:
            return
        if random.random() > dt * 0.12 * cfg["chat_rate"]:
            return
        for q in self.pet.peers(max_dist=self.pet.W * 0.8):
            if q.conv.busy() or q.dragging or not q.isVisible():
                continue
            if abs(q.feet_pos()[1] - self.pet.feet_pos()[1]) > self.pet.H * 0.35:
                continue                                          # not on the same level
            self.greet()
            return

    # ----------------------------------------------------------------- audience
    def audience(self, verb="poke"):
        """A nearby pet comments on what the user just did to this one."""
        pet = self.pet
        pool = self.dialogue.audience(verb) if self.dialogue is not None else ()
        if not pool or not pet.cfg["chat"] or len(pet.A.pets) < 2:
            return False
        now = time.time()
        for q in pet.peers(max_dist=pet.W * 2.6):
            if q.dragging or not q.grounded or q.conv.in_chat(now) or q.state == "shot":
                continue
            q.conv.say(random.choice(pool), pet)
            if q.state in ("idle", "walk", "alert"):
                q.enter("alert", dur=4.0)
            q.gaze_left = max(q.gaze_left, 3.4)
            if verb == "petting" and random.random() < 0.45:
                q.emit("heart", 3)
            elif random.random() < 0.2:
                q.emit("star", 2)
            return True
        return False


class ChatDirector:
    """Decisions that need more than one pet's conversation state."""

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ pairs
    def start(self, a=None, b=None):
        """Kick off a conversation, either between two given pets or a free pair."""
        if not self.app.cfg["chat"]:
            return None
        if a is None:
            cand = [p for p in self.app.pets
                    if p.isVisible() and p.conv.free() and not p.conv.busy()]
            if len(cand) < 2:
                return None
            a = random.choice(cand)
        if b is None:
            ps = [q for q in self.app.peers_of(a) if q.conv.free() and not q.conv.busy()]
            if not ps:
                return None
            b = ps[0]
        if a is b or not (a.conv.free() and b.conv.free()):
            return None
        if a.conv.busy() or b.conv.busy():
            return None                                  # nobody is in two chats
        # "walk over to talk": send the further one over first
        if self.app.cfg["chat_meetup"] and abs(a.feet_pos()[0] - b.feet_pos()[0]) \
                > (a.W + b.W) * 0.5:
            near, far = (a, b) if a.feet_pos()[0] < b.feet_pos()[0] else (b, a)
            far.conv.meet_target = near
            if far.state not in ("walk", "shot") and not far.dragging:
                far.enter("walk", dur=8.0)
            return (near, far)
        return (a, b) if a.conv.start(b) else None

    def introduce_all(self):
        """Round-robin greeting: everyone says hi to the next one."""
        live = [p for p in self.app.pets if p.isVisible() and not p.dragging]
        if len(live) < 2:
            return
        random.shuffle(live)
        for i, p in enumerate(live):
            q = live[(i + 1) % len(live)]
            if p.conv.free() and q.conv.free():
                p.conv.greet_near(q)

    def end_all(self):
        for p in self.app.pets:
            p.conv.abort(); p.conv.meet_target = None


class ConversationField:
    """Keeps ``pet.chat_lines`` and friends working as plain attributes.

    The state itself lives on the Conversation; this only forwards reads and
    writes so the rest of the pet file did not have to be rewritten all at once.
    """

    __slots__ = ("attr",)

    def __init__(self, attr):
        self.attr = attr

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        return getattr(obj.conv, self.attr)

    def __set__(self, obj, value):
        setattr(obj.conv, self.attr, value)