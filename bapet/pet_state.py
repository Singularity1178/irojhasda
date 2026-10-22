"""Pet mixin: animation playback, state changes and the user-triggered actions."""
from __future__ import annotations

import random

from PySide6 import QtWidgets

from .config import ANIM_KEYS
from .mathutil import clamp


class PetState:
    def spawn(self, index=0, show=True):
        """Put her on her spot. show=False places her but leaves her window hidden (start-up loading)."""
        g = self.A.resolve_screen()
        saved = self.cfg["positions"].get(self.name) if isinstance(self.cfg.get("positions"), dict) else None
        if saved is None and index == 0:
            saved = self.cfg["pos_x"]
        if saved is None:                                       # spread them out on the one screen
            n = max(1, len(self.A.pets))
            frac = 0.9 - index * min(0.75 / n, 0.25)
            saved = g.left() + (g.right() - g.left()) * frac
        fx = self.A.clamp_x(saved, self.W)
        self.rag_clear()
        self.set_feet(fx, self.A.floor_y(fx)); self.grounded = True
        if show: self.show()
        self.do_tactical(first=True)

    # ---------------- animation / state ----------------
    def play(self, key, restart=True):
        name, loop = ANIM_KEYS[key]
        prev, self.anim_key = self.anim_key, key
        self.rig.play(self.clips.get(key), loop, 1.0, self.blend_time(prev, key), restart)

    CALM = ("idle", "walk", "alert")
    @classmethod
    def blend_time(cls, a, b):
        """How long the cross-fade into clip `b` from clip `a` should take.

        Slow, calm changes (idle <-> walk <-> alert) get a long blend so the legs and
        torso ease over; an action the player triggered (poke, cut-in, pickup) has to
        feel immediate, so it gets a short one; settling out of being held takes a bit
        longer than going in.
        """
        if b == "pickup": return 0.10
        if a == b: return 0.10                       # restarting the same clip (second poke)
        if a == "pickup": return 0.24
        if b in ("react", "cutin", "tactical"): return 0.12
        if a in cls.CALM and b in cls.CALM: return 0.26
        return 0.20

    def enter(self, state, key=None, dur=0.0):
        prev_key = self.anim_key
        if state != "shoot": self.atk = None
        if state != "flee": self.flee = None
        # Fighting is the only time she is in her vehicle, and every other state
        # (idle, walk, carried, airborne, knocked down) stows it again.
        # The one exception is the reload that follows a fight: she tops up from
        # the seat, in her tank, and the vehicle is only put away when that clip
        # ends and behave() puts her back in idle (see begin_reload). Gated on
        # ride_on so a reload asked for while she is on her feet stays on her
        # feet, and on the reload key so poke / cutin / tactical still stow it.
        keep = state in ("shoot", "flee") or (state == "shot" and key == "reload" and self.ride_on)
        self.set_ride(keep)
        if state in ("shoot", "flee"):
            # driven phase by phase by atk_phase() / flee_step(), not by ANIM_KEYS
            self.state, self.state_t, self.state_dur = state, 0.0, dur
            return
        self.state, self.state_t, self.state_dur = state, 0.0, dur
        if state == "shot": self.shot_key = key; k = key
        elif state == "drag": k = "pickup"
        elif state == "fall": k = "pickup"   # jumps and throws share the pickup anim
        else: k = state
        self.play(k, restart=(state not in self.LOOPS or k != prev_key))

    def plan_next(self): self.plan_t = random.uniform(2.5, 7.0)

    # ---- actions (used by menu / panel / mouse) ----
    def poke(self):
        if self.ragdoll: self.rag_shove(); return
        if not self.grounded or self.dragging: return
        self.enter("shot", "react"); self.say(self.line("poke")); self.emit("star", 7)
        self.sq_v += 1.2
        # BA cafe tap: the touch ripple where she was clicked, and an emote balloon
        self.emit_tap()
        self.emote(random.choices(("heart", "exclaim", "question", "surprise"), (0.4, 0.3, 0.18, 0.12))[0], 1.5)
        self.audience("poke")

    def pet(self):
        if not self.grounded or self.dragging: return
        self.enter("shot", "react"); self.say(self.line("petting")); self.emit("heart", 9); self.bow = 1.0
        self.emote("shy", 2.0)
        self.emit_sparkles(6, spread=110, colors=((255, 255, 255), (255, 170, 205)))
        self.audience("petting")

    def do_cutin(self):
        if not self.grounded or self.dragging: return
        self.chat_abort()
        self.enter("shot", "cutin"); self.say(self.line("cutin"), 3.0)
        scr = self.screen().geometry() if self.screen() else QtWidgets.QApplication.primaryScreen().geometry()
        c = self.clips.get("cutin"); dur = clamp(c.duration if c else 2.0, 1.8, 4.0)
        self.A.cutin.start(scr, self.px + self.head_px[0], self.py + self.head_px[1], dur, self.name)
        self.emit("star", 14, spread=160)
        # EX burst at her feet: double halo ring + triangles + sparkles (the aura is drawn by pet_render)
        self.emit_ring(size=self.W * 0.42, life=0.8)
        self.emit_ring(size=self.W * 0.3, color=(255, 255, 255), life=0.7, delay=0.1)
        fx_, fy_ = self.feet_local()
        self.emit_shards(12, fx_, fy_ - self.char_h() * 0.5, spread=self.W * 0.4, speed=(200, 460))
        self.emit_sparkles(10, fx_, fy_ - self.char_h() * 0.6, spread=self.W * 0.5)

    def do_tactical(self, first=False):
        if not self.grounded or self.dragging: return
        self.enter("shot", "tactical")
        if first and not self.isVisible():
            # spawned while the loading card / title screen still holds her back: keep her spawn
            # line (the wiki "Gachaget" one) until she is actually on screen, see Pet.tick
            self.intro_line = self.line("tactical_first")
        else:
            self.say(self.line("tactical_first" if first else "tactical"), 3.6)
        self.emit_spawn()                                       # BA tactical start: halo rings + rising light

    def spin(self): self.spin_t = 0.0

    # ---- teleport in (summon / student select deploy) ----
    WARP_DUR = 0.95          # seconds the materialise effect runs (see PetRender.paint_warp_*)

    def teleport_in(self, fx, near_y=None):
        """Arrive by BA-style teleport instead of falling: she is placed standing on the
        surface under (fx, near_y) - a window she can perch on, or the screen floor - and
        materialises there in a column of pale-blue light. No fall, no landing, no ragdoll."""
        A = self.A
        try: self.rag_clear()
        except Exception: pass
        self.dragging = False; self.vx = self.vy = 0.0; self.bounces = 0
        try: self.chat_abort()
        except Exception: pass
        self.meet_target = None
        fx = A.clamp_x(fx, self.W)
        top, h = A.floor_y(fx), None
        if near_y is not None:
            try:
                for t, hh in A.surfaces(fx, self.cfg.get("perch", True)):     # sorted top -> bottom
                    if t >= near_y - 8: top, h = t, hh; break
            except Exception: pass
        self.set_feet(fx, top)
        self.grounded = True; self.support = h; self.air_kind = None
        self.sq = 0.0; self.sq_v = 0.0
        self.warp_t = 0.0; self.mask_dirty = True
        self.enter("shot", "tactical")
        self.emit_warp()

    def warp_alpha(self):
        """0..1 progress of the teleport effect, or None when she is not materialising."""
        t = getattr(self, "warp_t", -1.0)
        if t is None or t < 0: return None
        return min(1.0, t / self.WARP_DUR)

    def launch(self):
        if self.ragdoll: self.rag_shove(2.0); return
        self.ragdoll = False; self.rig.rag_post = []; self.rig.dangle_on = True
        self.recall_say = False
        self.grounded = False; self.support = None; self.dragging = False
        self.vx = random.choice([-1, 1]) * random.uniform(500, 1400) * self.cfg["scale"]
        self.vy = -random.uniform(1500, 2300) * self.cfg["scale"]
        self.air_kind = "thrown"; self.bounces = 0; self.enter("fall"); self.say(self.line("launch"), 1.8)
        self.emote("surprise", 1.4)
        fx_, fy_ = self.feet_local(); self.emit_impact(fx_, fy_, 1.0)

    def recall(self):
        """Called when the user summons this specific character (student select, "Summon to cursor").

        With a wiki file her "summon" line is her own Gachaget voice line instead of "<name> is here.".
        No fixed duration: a wiki line can be long or in several parts, so say() sizes the bubble to it.
        recall_say tells land() to leave the bubble alone when she arrives by falling, so the
        landing line does not replace this one a moment after it appeared. A teleport arrival
        is already standing, so there is no landing to guard against.
        """
        self.say(self.line("summon"))
        # only keep the guard while she really is in the air
        self.recall_say = not self.grounded

    def play_anim(self, key):
        if self.dragging or not self.grounded: return
        if key == "cutin": self.do_cutin()
        elif key == "reload": self.begin_reload(force=True)
        elif key == "idle": self.enter("idle"); self.plan_t = 8
        elif key == "walk": self.pick_walk_heading(); self.enter("walk", dur=5.0)
        elif key == "alert": self.enter("alert", dur=6.0)
        else: self.enter("shot", key)
