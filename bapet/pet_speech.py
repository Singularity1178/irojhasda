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

    # ---- Blue Archive VFX (drawn by pet_render with the vfx kit) ----
    # Every particle below carries "g" (gravity, px/s^2, + = down) and "drag" (1/s), which
    # Pet.tick uses instead of the old float-up rule, and "mask_r" so the click-through mask
    # knows how far it reaches.
    def vfx_on(self):
        return bool(self.cfg.get("ba_vfx", True)) and bool(self.cfg["particles"])

    def emote(self, kind, dur=1.7):
        """Pop a story-mode emoticon over her head: exclaim question surprise heart note dots
        idea sweat angry shy (see vfx.EMOTES)."""
        if not self.cfg.get("emotes", True) or not self.isVisible(): return
        self.emo = (kind, time.time(), dur); self.mask_dirty = True

    def _part(self, **q):
        q.setdefault("vx", 0.0); q.setdefault("vy", 0.0); q.setdefault("life", 0.0)
        q.setdefault("rot", 0.0); q.setdefault("g", 0.0); q.setdefault("drag", 1.0)
        q.setdefault("seed", random.randint(0, 1 << 30))
        self.parts.append(q)
        if len(self.parts) > 220: self.parts = self.parts[-220:]

    def feet_local(self):
        return self.W / 2, self.H * (1 - self.PADB)

    def emit_ring(self, x=None, y=None, size=None, color=(110, 205, 255), life=0.6, flat=0.3, delay=0.0):
        """Expanding ground ring (halo-blue by default) at her feet."""
        if not self.vfx_on(): return
        if x is None: x, y = self.feet_local()
        size = size if size is not None else self.W * 0.3
        self._part(kind="ring", x=x, y=y, max=life, size=size, col=color, flat=flat, life=-delay,
                   mask_r=size + 4, g=0.0, drag=0.0)

    def emit_sparkles(self, n, x=None, y=None, spread=80, colors=((255, 255, 255), (110, 205, 255)), up=1.0):
        """Kira sparkles that pop out and drift up, twinkling."""
        if not self.vfx_on(): return
        if x is None: x, y = self.head_px
        sc = math.sqrt(max(0.3, self.cfg["scale"]))
        for _ in range(n):
            ang = random.uniform(-math.pi * 0.95, -math.pi * 0.05); sp = random.uniform(40, 160) * sc
            self._part(kind="sparkle", x=x + random.uniform(-spread, spread) * 0.5, y=y + random.uniform(-spread, spread) * 0.3,
                       vx=math.cos(ang) * sp, vy=math.sin(ang) * sp * up, max=random.uniform(0.6, 1.2),
                       size=random.uniform(5, 11) * sc, col=random.choice(colors), g=-40.0 * up, drag=2.0,
                       ph=random.uniform(0, math.tau), mask_r=24)

    def emit_shards(self, n, x=None, y=None, spread=60, speed=(150, 380), colors=((255, 255, 255), (110, 205, 255)), g=520.0):
        """BA triangle confetti bursting out and tumbling down."""
        if not self.vfx_on(): return
        if x is None: x, y = self.head_px
        sc = math.sqrt(max(0.3, self.cfg["scale"]))
        for _ in range(n):
            ang = random.uniform(-math.pi, 0.0); sp = random.uniform(*speed) * sc
            self._part(kind="shard", x=x + random.uniform(-spread, spread) * 0.3, y=y, vx=math.cos(ang) * sp,
                       vy=math.sin(ang) * sp, max=random.uniform(0.6, 1.1), size=random.uniform(4, 9) * sc,
                       col=random.choice(colors), rot=random.uniform(-3, 3), g=g, drag=1.6,
                       hollow=random.random() < 0.3, mask_r=16)

    def emit_dust(self, n, x=None, y=None, spread=90, power=1.0):
        """Stylised dust clouds rolling out sideways along the floor."""
        if not self.vfx_on(): return
        if x is None: x, y = self.feet_local()
        sc = math.sqrt(max(0.3, self.cfg["scale"]))
        for i in range(n):
            side = -1 if i % 2 else 1
            self._part(kind="dust", x=x + side * random.uniform(0, spread) * 0.25 * sc, y=y - random.uniform(0, 8),
                       vx=side * random.uniform(60, 190) * sc * power, vy=-random.uniform(10, 50) * sc,
                       max=random.uniform(0.45, 0.8), size=random.uniform(9, 16) * sc * (0.7 + 0.3 * power),
                       g=-20.0, drag=3.5, mask_r=36)

    def emit_tap(self, lx=None, ly=None):
        """The BA touch ripple, where the cursor clicked her (window px)."""
        if not self.vfx_on(): return
        if lx is None:
            from PySide6 import QtGui
            c = QtGui.QCursor.pos(); lx, ly = c.x() - self.px, c.y() - self.py
        self._part(kind="tap", x=lx, y=ly, max=0.45, size=1.0 * math.sqrt(max(0.3, self.cfg["scale"])),
                   g=0.0, drag=0.0, mask_r=60)

    def emit_impact(self, lx, ly, strength=1.0):
        """A body (or the whole of her) slammed into something: dust + a small ring."""
        if not self.vfx_on():
            self.emit("puff", 5, lx, ly, spread=90); return
        self.emit_dust(4 + int(3 * min(1.5, strength)), lx, ly, power=min(1.6, 0.7 + strength * 0.5))
        if strength > 0.6: self.emit_ring(lx, ly, self.W * 0.22 * min(1.6, strength), (230, 240, 255), 0.4, 0.28)

    def emit_spawn(self):
        """Tactical start / arriving on screen: halo rings + rising light + triangles."""
        fx, fy = self.feet_local()
        self.emit_ring(fx, fy, self.W * 0.36, (110, 205, 255), 0.7, 0.28)
        self.emit_ring(fx, fy, self.W * 0.24, (255, 255, 255), 0.6, 0.28, delay=0.12)
        self.emit_sparkles(10, fx, fy - self.char_h() * 0.3, spread=self.W * 0.35, up=1.4)
        self.emit_shards(6, fx, fy - 6, spread=self.W * 0.3, speed=(120, 260), g=260.0)

    def combat_popup(self, text, kind="normal", scale=1.0):
        """Floating combat text over her chest on the shared ShotFX overlay."""
        if not self.cfg.get("damage_numbers", True) or not self.isVisible(): return
        try:
            fx = self.A.shotfx
            from PySide6 import QtWidgets
            scr = self.screen().geometry() if self.screen() else QtWidgets.QApplication.primaryScreen().geometry()
            fx.ensure(scr)
            x = self.px + self.W * 0.5; y = self.py + self.H * (1 - self.PADB) - self.char_h() * 0.78
            fx.popup(x, y, text, kind, scale * math.sqrt(max(0.5, self.cfg["scale"])))
        except Exception:
            pass

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
