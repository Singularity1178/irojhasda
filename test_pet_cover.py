#!/usr/bin/env python3
"""Headless tests for PetCover: which windows and students count as cover, and why not.

No Qt, no GL, no .glb. A fake student with the handful of attributes PetCover
reads, driven against a fake window list and a fake opponent. Plain
`python test_pet_cover.py`; each test prints what it checked.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bapet.combat_config import (      # noqa: E402
    COVER_WIN_GAP, COVER_WIN_GROUND_GAP, COVER_WIN_MIN_H, COVER_WIN_MIN_W)
from bapet.pet_cover import PetCover   # noqa: E402

SCREEN_L, SCREEN_T, SCREEN_R, SCREEN_B = 0.0, 0.0, 1920.0, 1040.0
FLOOR = SCREEN_B                       # her feet when she stands on the screen bottom
BODY = 151.0                          # a student's body height at panel scale 0.5
CHAR = BODY                           # no vehicle, so char_h() == rag_h()


class FakeTracker:
    def __init__(self, wins):
        self.enabled = True
        self.wins = list(wins)                      # [(hwnd, l, t, r, b)]

    def rect(self, hwnd):
        for w in self.wins:
            if w[0] == hwnd:
                return w[1:]
        return None

    def surface_visible(self, hwnd, fx):
        r = self.rect(hwnd)
        return r is not None and r[0] + 4 <= fx <= r[2] - 4


class FakeApp:
    def __init__(self, tracker):
        self.tracker = tracker
        self.pets = []

    class _G:
        left = staticmethod(lambda: SCREEN_L)
        right = staticmethod(lambda: SCREEN_R)

    def resolve_screen(self):
        return self._G


class FakeStudent(PetCover):
    """Just what window_ok / pick_window / cover_stances read."""

    def __init__(self, fx, fy, tracker, support=None, W=190.0):
        self.A = FakeApp(tracker)
        self.cfg = {}
        self.W = W
        self.fx, self.fy = fx, fy
        self.support = support
        self.grounded = True

    def feet_pos(self):
        return (self.fx, self.fy)

    def char_h(self):
        return CHAR

    def rag_h(self):
        return BODY

    def move_span(self):
        m = self.W * 0.18
        return (SCREEN_L + m, max(SCREEN_L + m, SCREEN_R - m))


def window(hwnd, l, t, r, b):
    return (hwnd, l, t, r, b)


def rise_ok(pet, hwnd, rise, q):
    """A window standing `rise` px above her ground, tall enough otherwise."""
    trk = pet.A.tracker
    rect = trk.rect(hwnd)
    l, _t, r, _b = rect
    trk.wins = [window(hwnd, l, pet.fy - rise, r, pet.fy + 48.0)]
    return pet.window_ok(hwnd, q)


class TestWindowCover(unittest.TestCase):
    def test_a_window_taller_than_her_is_cover_at_any_height(self):
        """The bug report: at panel scale 0.5 a taskbar terminal rising 242 px (1.6x her)
        was rejected by an upper bound. There is none now - only the lower bound."""
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 700.0, 1200.0, FLOOR)]))
        q = FakeStudent(1500.0, FLOOR, pet.A.tracker)

        floor_px = COVER_WIN_MIN_H * BODY
        self.assertAlmostEqual(floor_px, 83.0, delta=0.5)
        for rise in (floor_px + 1.0, 151.0, 242.0, 400.0, 900.0, SCREEN_B):
            with self.subTest(rise=round(rise, 1)):
                self.assertTrue(rise_ok(pet, 1, rise, q),
                                f"a window rising {rise:.0f}px was rejected")

        # and it is still found, not merely accepted
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 790.0, 1200.0, FLOOR)]))
        h, d = pet.pick_window(q)
        self.assertEqual(h, 1, f"pick_window did not choose the tall window: {h}")
        self.assertLess(abs(d - 167.0), 1.0, f"unexpected spot distance {d:.0f}")

    def test_the_lower_bound_still_rejects_a_slit(self):
        """Only the lower bound matters: a 40px toolbar is not a wall."""
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 900.0, 1200.0, FLOOR)]))
        q = FakeStudent(1500.0, FLOOR, pet.A.tracker)
        for rise in (10.0, 40.0, 60.0, COVER_WIN_MIN_H * BODY - 1.0):
            with self.subTest(rise=rise):
                self.assertFalse(rise_ok(pet, 1, rise, q),
                                 f"a {rise:.0f}px sliver was accepted as cover")

    def test_it_must_rise_from_her_ground(self):
        """A window floating above her head leaves daylight under it: not a wall."""
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 400.0, 1200.0, 700.0)]))
        q = FakeStudent(1500.0, FLOOR, pet.A.tracker)
        self.assertFalse(pet.window_ok(1, q), "a floating window was accepted")
        self.assertGreater(FLOOR - 700.0, COVER_WIN_GROUND_GAP * CHAR)

    def test_it_must_be_wide_enough(self):
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 800.0, 600.0 + 20, FLOOR)]))
        q = FakeStudent(1500.0, FLOOR, pet.A.tracker)
        self.assertFalse(pet.window_ok(1, q), "a 20px-wide strip was accepted")
        self.assertLess(20.0, COVER_WIN_MIN_W * CHAR)

    def test_the_opponent_must_not_stand_on_it_or_in_front_of_it(self):
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 800.0, 1200.0, FLOOR)]))
        q = FakeStudent(1500.0, FLOOR, pet.A.tracker)
        self.assertTrue(pet.window_ok(1, q), "the plain case should pass")

        q.support = 1                          # the opponent is standing ON it
        self.assertFalse(pet.window_ok(1, q), "the opponent standing on it was accepted")
        q.support = None

        q.fx = 900.0                            # the opponent is in front of it
        self.assertFalse(pet.window_ok(1, q), "the opponent in front of it was accepted")

    def test_she_needs_room_past_the_window(self):
        """Her spot is just past the far edge; if that is off her floor there is no cover."""
        trk = FakeTracker([window(1, 600.0, 800.0, 1900.0, FLOOR)])
        pet = FakeStudent(400.0, FLOOR, trk)
        q = FakeStudent(100.0, FLOOR, trk)      # opponent to the left -> spot is past the right edge
        self.assertGreater(pet.win_spot(trk.rect(1), q)[0], pet.move_span()[1])
        self.assertFalse(pet.window_ok(1, q), "an unreachable spot was accepted")

    def test_the_window_she_stands_on_is_never_her_cover(self):
        trk = FakeTracker([window(1, 600.0, 800.0, 1200.0, FLOOR)])
        pet = FakeStudent(900.0, 800.0, trk, support=1)     # perched on it
        q = FakeStudent(1500.0, 800.0, trk)
        self.assertFalse(pet.window_ok(1, q), "the window she stands on was accepted")

    def test_cover_windows_is_empty_with_no_tracker(self):
        pet = FakeStudent(400.0, FLOOR, FakeTracker([window(1, 600.0, 800.0, 1200.0, FLOOR)]))
        pet.A.tracker.enabled = False
        self.assertEqual(pet.cover_windows(), [], "windows offered with the tracker off")

    def test_a_taller_window_intercepts_shots_a_short_one_cannot(self):
        """Why there is no upper bound: cover is honest, not a flat bonus. A round is
        stopped only when its path crosses the window rect, so height buys real
        protection - and the lower bound is exactly the point where a window starts
        covering her chest."""
        from bapet.pet_cover import seg_rect_t
        shooter_x, target_x = 1500.0, 567.0          # window (600..1200) sits between them

        def blocked(rise, aim_frac):
            """Does a LEVEL shot at `aim_frac` of her body height cross the window? A level
            shot is the honest probe: it is blocked exactly when the window stands that far
            up, so this measures the protection height for nothing."""
            ty = FLOOR - aim_frac * BODY
            rect = (600.0, FLOOR - rise, 1200.0, FLOOR + 48.0)
            return seg_rect_t(shooter_x, ty, target_x, ty, rect) is not None

        chest, head = 0.5, 0.76
        # the lower bound is where the window stops being a sliver and starts covering her
        self.assertTrue(blocked(COVER_WIN_MIN_H * BODY, chest),
                        "a window at the minimum height did not cover her chest")
        self.assertFalse(blocked(COVER_WIN_MIN_H * BODY, head),
                         "a window only just covering her reached her head")
        # and each extra increment of height buys exactly that much more of her
        self.assertTrue(blocked(0.76 * BODY, head), "a window at head height missed her head")
        self.assertFalse(blocked(0.76 * BODY - 1.0, head), "1px of window covered her head")
        for mult in (1.0, 2.0, 4.0, 6.0):
            with self.subTest(window=f"{mult:.0f}x her height"):
                self.assertTrue(blocked(mult * BODY, head),
                                f"a window {mult:.0f}x her height did not cover her head")

        print(f"\n  [a] window cover: at least {COVER_WIN_MIN_H:.2f}x her height, no maximum "
              f"({COVER_WIN_MIN_H * BODY:.0f}px at body {BODY:.0f}); gap "
              f"{COVER_WIN_GAP * CHAR:.0f}px, min width {COVER_WIN_MIN_W * CHAR:.0f}px")


if __name__ == "__main__":
    unittest.main(verbosity=1)
