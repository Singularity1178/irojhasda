"""Pet mixin: cursor hover, head-pat, mouse and wheel events."""
from __future__ import annotations

import math
import random
import sys
import time

from PySide6.QtCore import QPoint, QPointF, Qt

from .mathutil import clamp


class PetInput:
    # ---------------- input ----------------
    def cursor_logic(self, cur, dt, now):
        lx, ly = cur.x() - self.px, cur.y() - self.py
        over = False
        if self.alpha is not None and 0 <= lx < self.W and 0 <= ly < self.H:
            h, w = self.alpha.shape
            over = self.alpha[min(h - 1, int(ly * h / self.H)), min(w - 1, int(lx * w / self.W))] > 16
        self.hover = over and not self.dragging
        if sys.platform == "win32" and self.cfg["click_through"] and not self.A.args.no_mask:
            bg = self.bubble_geom()
            on_bubble = bg is not None and bg[0].contains(QPointF(lx, ly))
            self.set_passthrough(not (over or on_bubble or self.dragging or self.press_g is not None))
        else:
            self.set_passthrough(False)
        if self.hover: self.hover_time += dt
        else: self.hover_time = 0.0; self.hover_said = False
        if self.hover and self.hover_time > 3.5 and not self.hover_said and self.grounded and not self.bubble:
            self.hover_said = True; self.say(self.line("hover"))
        # head-pat: stroke the cursor back and forth over her head
        # An oval, not a circle: the hand moves side to side, and a stroke wide
        # enough to leave a small circle used to wipe the tally before it could
        # ever reach the threshold.  A stroke only counts once it has actually
        # travelled H*0.10 px, so a resting or twitching cursor cannot pat.
        hx, hy = self.head_px
        rx, ry = self.H * 0.20, self.H * 0.15
        near = ((lx - hx) / rx) ** 2 + ((ly - hy) / ry) ** 2 < 1.0
        if near and not self.dragging and self.press_g is None:
            self.pat_leave = 0.0
            self.gaze_peer = None; self.gaze_left = 0.0     # eyes on the user, not a friend
            self.cur_look = True
            dxm = cur.x() - self.last_cur.x()
            if abs(dxm) > 1:
                s = 1 if dxm > 0 else -1
                if self.pat_sign != 0 and s != self.pat_sign:
                    if self.pat_run >= self.H * 0.10: self.pat_events.append(now)
                    self.pat_run = 0.0
                self.pat_sign = s
                self.pat_run += abs(dxm)
            self.pat_events = [t for t in self.pat_events if now - t < 3.2]
            if len(self.pat_events) >= 3 and now > self.pat_cool:
                self.pat_cool = now + 4.0; self.pat_events = []; self.pet()
            if len(self.pat_events) >= 2: self.bow = min(1.0, self.bow + dt * 2.0)
        else:
            # brief slip-off (a bouncy idle, a body in the way) should not throw
            # the whole gesture away - only a real departure does
            self.pat_leave += dt
            if self.pat_leave > 0.30 or self.dragging or self.press_g is not None:
                self.pat_events = []; self.pat_sign = 0; self.pat_run = 0.0
        self.bow = max(0.0, self.bow - dt * 0.8)
        self.last_cur = QPoint(cur)
        if not self.dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.hover else Qt.CursorShape.ArrowCursor)

    # ---------------- mouse ----------------
    def mousePressEvent(self, e):
        self.A.set_active(self)
        self.A.restack(force=True)          # clicking must not change who is in front
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self.press_g = e.globalPosition().toPoint(); self.press_win = QPoint(int(self.px), int(self.py))
            mods = e.modifiers()
            self.rotating = e.button() == Qt.MouseButton.MiddleButton or bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
            self.rot_yaw0 = self.yaw_user; self.hist.clear(); self.moved = False
            self.rot_pitch0 = self.pitch_user; self.rot_tilt0 = self.tilt_user
            if self.rotating: self.scan = None; self.rot_touch = time.time()
            self.rot_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            self.bubble = None if (self.bubble and self.bubble_geom() and self.bubble_geom()[0].contains(e.position())) else self.bubble

    def mouseMoveEvent(self, e):
        if self.press_g is None: return
        g = e.globalPosition().toPoint(); d = g - self.press_g
        if self.rotating:
            self.moved = True
            # rotate-drag: left/right = yaw, up/down = pitch.  Shift held when the
            # drag started: left/right = tilt (lean sideways) instead of yaw.
            # Only THIS character turns; she eases back to facing you after release.
            pitch = self.rot_pitch0 - d.y() * 0.5
            if self.rot_shift:
                self.nudge_rotation(tilt=self.rot_tilt0 + d.x() * 0.4, pitch=pitch)
            else:
                self.nudge_rotation(yaw=self.rot_yaw0 + d.x() * 0.7, pitch=pitch)
            return
        if not self.dragging and d.manhattanLength() > 6:
            self.dragging = True; self.moved = True; self.grounded = False; self.support = None
            self.chat_abort(); self.meet_target = None
            self.set_ride(False, fade=False)     # picked up: the vehicle comes off now
            self.vx = self.vy = 0.0; self.bounces = 0; self.air_kind = "thrown"
            if self.rag_skel is not None:
                # hold whichever limb is nearest the cursor; she hangs and swings
                # from that, and the physics carries the rest of her along
                self.rag_skel.grab((g.x(), g.y()), (g.x(), g.y()))
                self.rag_state = "fall"; self.rag_rest = 0.0
            self.enter("drag"); self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if random.random() < 0.6: self.say(self.line("drag"), 2.0)
            self.audience("drag")
        if self.dragging:
            if self.rag_skel is not None:
                # While she is limp the physics owns her window position: the
                # grab joint moves the BODY, and ragdoll_step moves the window
                # from wherever the body ended up. Moving the window here too
                # would fight it and she would lag behind the cursor.
                #
                # The cursor TARGET is deliberately not set here either - see
                # rag_pm_cursor, which reads it once per tick instead. Mouse-move
                # events stop arriving when the mouse stops, and arrive bunched
                # up when it moves fast, so feeding them straight to the grab
                # joint means the target jumps in irregular steps. That is what
                # made her judder under the mouse.
                return
            nx = self.press_win.x() + d.x(); ny = self.press_win.y() + d.y()
            # keep her inside the one screen, horizontally
            g_home = self.A.resolve_screen()
            want_x = nx + self.W / 2
            fx = clamp(want_x, g_home.left() + self.W * 0.10, max(g_home.left() + self.W * 0.10,
                                                                              g_home.right() - self.W * 0.90))
            ylo, yhi = g_home.top() - self.H * 0.5, g_home.bottom() - self.H * 0.15
            # Being carried into a screen edge fast enough knocks her over with
            # the button still down. Asked while she is only ABOUT to be clamped
            # - before the window is moved at all - so the ragdoll gets her real
            # position and the cursor's velocity, rather than her being teleported
            # onto the edge first and then going limp there. On a True the
            # ragdoll owns the window, so nothing below may touch it.
            if abs(want_x - fx) > 0.5 or ny < ylo - 0.5 or ny > yhi + 0.5:
                if self.edge_slam(drag=True): return
            nx = fx - self.W / 2
            ny = clamp(ny, ylo, yhi)
            self.px = nx; self.py = ny
            self.move(int(self.px), int(self.py)); self.hist.append((time.time(), g.x(), g.y()))

    def mouseReleaseEvent(self, e):
        self.A.restack(force=True)
        if self.press_g is None: return
        was_drag, rot, moved = self.dragging, self.rotating, getattr(self, "moved", False)
        self.press_g = None; self.rotating = False
        if was_drag:
            self.dragging = False; self.setCursor(Qt.CursorShape.ArrowCursor)
            vx, vy = self.drag_velocity()            # same measurement edge_slam uses
            sp = math.hypot(vx, vy)
            if sp < 150: vx = vy = 0.0
            elif sp > 3000: vx, vy = vx * 3000 / sp, vy * 3000 / sp
            self.vx, self.vy = vx, vy; self.air_kind = "thrown"; self.bounces = 0
            if self.ragdoll:                                # thrown while limp: keep ragdolling
                if self.rag_skel is not None:
                    # Just let go. Her bodies already carry the throw momentum
                    # from being dragged through the world, so overwriting their
                    # velocities here would throw away the swing - but a fling
                    # can still build up more speed than the old rod ever could,
                    # so cap it at the same 3000 px/s the rod used. release_grab
                    # does the capping itself, limb by limb.
                    self.rag_skel.release_grab()
                    self.rag_state = "fall"; self.rag_rest = 0.0; self.rag_strength = 1.0
                    return
                self.rg_vx, self.rg_vy = vx, vy
                self.rg_w = clamp(vx * 0.004, -10, 10)
                self.rag_state = "fall"; self.rag_rest = 0.0; self.rag_strength = 1.0
                return
            self.enter("fall")
        elif not rot and not moved:
            self.poke()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self.do_cutin(); return
        if e.button() == Qt.MouseButton.MiddleButton and self.cfg.get("blow_mode"):
            try: self.A.spawn_gust(e.globalPosition().toPoint())
            except Exception: pass

    def wheelEvent(self, e):
        dy = e.angleDelta().y() / 120.0
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.scan = None
            self.nudge_rotation(yaw=self.yaw_user + dy * 15)       # only the focused student; eases back
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            for q in self.A.pets:                                  # everyone; each eases back by itself
                q.scan = None
                q.nudge_rotation(yaw=q.yaw_user + dy * 15)
        else:
            self.A.set("scale", clamp(self.cfg["scale"] * (1.06 ** dy), 0.5, 2.5), refresh=True)

    def contextMenuEvent(self, e):
        self.A.set_active(self)
        self.A.show_menu(e.globalPos(), self)
