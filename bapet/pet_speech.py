"""Pet mixin: bubbles, particles, and the pet-to-pet conversation entry points."""
from __future__ import annotations

import math
import random
import time

from .combat_config import COMBAT_LINE_COOLDOWN
from .config import GUST_RADIUS, GUST_SPEED
from .mathutil import clamp


class PetSpeech:
    # ---------------- dialogue ----------------
    def line(self, *events):
        """One line for `event` ("poke", "idle", ...), or drawn from several.

        The pools themselves live in the dialogue package; this only asks for one
        line and fills in who is speaking.
        """
        tags = self.A.watcher.current_tags()
        if len(events) == 1:
            return self.A.dialogue.get(self.name, events[0], tags)
        return self.A.dialogue.get_any(self.name, events, tags)

    def speech_ok(self):
        """True when she can start a new line right now.

        Read by StateReactor, which otherwise has to know nothing about the pet
        code. False while she is mid-bubble, off screen or lying limp, so a
        reaction does not cut off a line she is already saying or stand her
        back up mid-tumble.
        """
        return bool(self.cfg["speech"]) and self.bubble is None and self.isVisible() \
            and not self.ragdoll

    def say(self, text, dur=None):
        if not self.cfg["speech"] or not text: return
        self.bubble = (text, time.time(), dur or (2.4 + 0.05 * len(text))); self.mask_dirty = True
        self.lift_bubble()

    def say_combat(self, text, dur=None, force=False):
        """Say a reactive combat line - being hit, a bullet going past, reloading - and report whether
        she actually spoke.

        These are the lines that pile up: a student being shot at collects several hits a second, and
        say() overwrites whatever is already in her bubble, so without a gate she changes text several
        times a second and looks like she is babbling instead of reacting. A reactive line is therefore
        dropped if she said one less than COMBAT_LINE_COOLDOWN ago; the rest of the fight (stress, the
        flinch, the ragdoll roll) is untouched, only the chatter is rationed.

        force  beats that only happen once - being knocked over, giving up on a tank - speak anyway, so
        the cooldown can never swallow the one line that actually mattered.
        """
        if not text: return False
        now = time.time()
        if not force and now < self.say_lock: return False
        self.say_lock = now + COMBAT_LINE_COOLDOWN
        self.say(text, dur); return True

    def lift_bubble(self):
        """Put this character's window - and therefore her bubble - on top.

        Every character draws her own bubble inside her own window, so when two of
        them overlap it is the *window* z-order that decides which line is readable.
        Raising the window as soon as a line starts makes the newest speech the one
        on top, and it stays there until somebody else talks.
        """
        # The stacking order is fixed (see App.restack): speaking no longer moves a window.
        if self.dragging or not self.isVisible(): return
        try:
            self.A.touch_zorder(self)
        except Exception:
            pass

    def emit(self, kind, n, x=None, y=None, spread=70):
        if not self.cfg["particles"]: return
        if x is None: x, y = self.head_px
        sc = self.cfg["scale"]
        for _ in range(n):
            ang = random.uniform(-math.pi * 0.95, -math.pi * 0.05); sp = random.uniform(40, 170) * sc
            self.parts.append(dict(kind=kind, x=x + random.uniform(-spread, spread) * 0.5 * sc, y=y + random.uniform(-10, 10),
                                   vx=math.cos(ang) * sp, vy=math.sin(ang) * sp, life=0.0, max=random.uniform(0.9, 1.6),
                                   size=random.uniform(7, 13) * math.sqrt(sc), rot=random.uniform(-0.5, 0.5)))

    def emit_wind(self, cx, cy, strength):
        """Wind streaks flowing straight away from the gust origin (screen px),
        using the same direction and falloff the hair uses in gust_wind_at()."""
        if not self.cfg["particles"]: return
        sc = self.cfg["scale"]
        for _ in range(int(22 * clamp(strength, 0.3, 2.5))):
            lx, ly = random.uniform(0, self.W), random.uniform(0, self.H)   # spot in this window
            dx, dy = self.px + lx - cx, self.py + ly - cy                   # same vector the hair sees
            d = math.hypot(dx, dy)
            if d > GUST_RADIUS or d < 20: continue
            ux, uy = dx / d, dy / d
            spd = GUST_SPEED * 0.35 * strength * (1 - d / GUST_RADIUS) ** 0.5
            self.parts.append(dict(
                kind="wind", x=lx, y=ly, vx=ux * spd, vy=uy * spd,
                life=-d / (GUST_SPEED * 0.5),            # negative = waits, so a wavefront sweeps outward
                max=random.uniform(0.35, 0.6),
                size=random.uniform(1.2, 2.4) * math.sqrt(sc), rot=0.0,
                ang=math.atan2(uy, ux), len=clamp(spd * 0.08, 14, 90) * math.sqrt(sc),
                ph=random.uniform(0, math.tau)))

    # ---- pet-to-pet ----
    # All of the conversation logic lives in dialogue/conversation.py. Only the
    # entry points this class and the panel still use are kept here.
    def peers(self, max_dist=None, same_surface=False):
        """Other visible pets, nearest first. same_surface = perched on the same window."""
        return self.A.peers_of(self, max_dist, same_surface)

    def free(self):
        """True when she can start / continue a conversation."""
        return self.conv.free()

    def in_chat(self, now=None):
        return self.conv.in_chat(now)

    def busy_chat(self):
        """True while a conversation is running (or about to) - blocks wander plans."""
        return self.conv.busy()

    def greet(self):
        """One-line hello to whoever is nearest - used when two characters pass."""
        return self.conv.greet()

    def greet_near(self, other):
        return self.conv.greet_near(other)

    def start_chat(self, other):
        """Begin a conversation with `other` immediately (no approach step)."""
        return self.conv.start(other)

    def chat_abort(self, why=""):
        """Something else happened (drag / poke / cut-in) - drop out of the chat."""
        return self.conv.abort(why)

    def chat_stop(self):
        """User-driven stop (menu / panel)."""
        self.conv.stop()

    def chat_logic(self, dt, now):
        """Continue an ongoing conversation, or let one start."""
        return self.conv.converse(dt, now)

    def audience(self, verb="poke"):
        """A nearby pet comments on what the user just did to this one."""
        return self.conv.audience(verb)
