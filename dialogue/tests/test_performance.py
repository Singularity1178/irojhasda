"""Performance and privacy checks for the watcher.

The pet render loop must never stall on a sample, and a window title must
never be stored anywhere it could be recovered from.
"""
from __future__ import annotations

import gc
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dialogue import DialogueEngine, SystemWatcher                       # noqa: E402
from dialogue.reactions import StateReactor                             # noqa: E402
from dialogue.system_watcher import Probes, Rules, load_rules            # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_watcher_rules import FakeProbes, Harness, window               # noqa: E402


#: the budget the plan sets for a single sample
SAMPLE_BUDGET_MS = 10.0


class TestPerformance(unittest.TestCase):
    def test_a_fake_sample_is_far_under_budget(self):
        h = Harness()
        h.settle()
        times = []
        for i in range(60):
            h.fg.update(window("chrome.exe", f"Page {i} - Example Site"))
            start = time.perf_counter()
            h.watcher.tick(force=True)
            times.append((time.perf_counter() - start) * 1000.0)
        worst = max(times)
        self.assertLess(worst, SAMPLE_BUDGET_MS,
                        f"slowest fake sample was {worst:.2f} ms")

    def test_the_real_foreground_read_is_cheap(self):
        """The one call that touches Windows, timed on its own."""
        from dialogue.system_watcher import _foreground
        if sys.platform != "win32":
            self.skipTest("Windows only")
        _foreground()                                   # warm up
        start = time.perf_counter()
        for _ in range(50):
            _foreground()
        each = (time.perf_counter() - start) / 50.0 * 1000.0
        self.assertLess(each, SAMPLE_BUDGET_MS,
                        f"foreground read took {each:.2f} ms")

    def test_a_real_sample_is_under_budget(self):
        watcher = SystemWatcher(priority=DialogueEngine().state_order)
        watcher.tick(force=True)                        # warm up / prime
        start = time.perf_counter()
        for _ in range(20):
            watcher.tick(force=True)
        each = (time.perf_counter() - start) / 20.0 * 1000.0
        self.assertLess(each, SAMPLE_BUDGET_MS,
                        f"real sample took {each:.2f} ms")

    def test_the_slow_probes_are_actually_rate_limited(self):
        """Disk, network and uptime must not run on every poll."""
        probes = FakeProbes()
        h = Harness(probes=probes)
        h.settle()
        baseline = (probes.disk_calls, probes.network_calls)
        for _ in range(20):                             # 60 seconds of polling
            h.advance(3.0)
            h.watcher.tick(force=True)
        # 60s at disk_every=60 and network_every=10 is at most 1 + 6 calls
        self.assertLessEqual(probes.disk_calls - baseline[0], 1)
        self.assertLessEqual(probes.network_calls - baseline[1], 6)

    def test_a_sample_does_not_allocate_without_bound(self):
        """A long run must not leak: watch the object count, not the tracers."""
        h = Harness()
        h.settle()
        gc.collect()
        before = len(gc.get_objects())
        for i in range(300):
            h.fg.update(window("chrome.exe", f"Page {i} - Example"))
            h.watcher.tick(force=True)
        gc.collect()
        growth = len(gc.get_objects()) - before
        self.assertLess(growth, 500, f"object count grew by {growth}")

    def test_the_exe_cache_is_bounded(self):
        h = Harness()
        for pid in range(2000):
            h.watcher._exe_for(pid)
        self.assertLessEqual(len(h.watcher._exe_cache), 513)

    def test_tick_is_cheap_when_not_due(self):
        h = Harness()
        h.watcher.tick(force=True)
        start = time.perf_counter()
        for _ in range(10000):
            h.watcher.tick()
        each = (time.perf_counter() - start) / 10000.0 * 1e6
        self.assertLess(each, 200.0, f"a no-op tick took {each:.1f} us")


class TestPrivacy(unittest.TestCase):
    SECRET = "SECRET-DOCUMENT-TITLE-9f3a"

    def setUp(self):
        gc.collect()

    def test_no_title_is_kept_in_any_watcher_attribute(self):
        h = Harness()
        h.settle(**window("chrome.exe", f"{self.SECRET} - Google Chrome"))
        self.assertNotIn(self.SECRET, repr(h.watcher.__dict__))

    def test_no_title_is_kept_in_a_rule_or_a_match_result(self):
        rules = load_rules()
        fg = {"exe": "chrome.exe", "title": f"{self.SECRET} - Google Chrome",
              "hwnd": 1}
        rule = rules.match_site(fg)
        self.assertNotIn(self.SECRET, repr(rule))
        self.assertNotIn(self.SECRET, repr(rules.match_app(fg)))

    def test_a_debug_line_shows_the_rule_not_the_title(self):
        import io
        import contextlib
        h = Harness()
        h.watcher.debug = True
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            h.settle(**window("chrome.exe",
                              f"{self.SECRET} - YouTube - Google Chrome"))
        out = buffer.getvalue()
        self.assertIn("site_youtube", out)
        self.assertNotIn(self.SECRET, out)

    def test_a_debug_line_prints_nothing_sensitive_when_nothing_matches(self):
        import io
        import contextlib
        h = Harness()
        h.watcher.debug = True
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            h.settle(**window("chrome.exe",
                              f"{self.SECRET} - Some Intranet Page"))
        out = buffer.getvalue()
        self.assertNotIn(self.SECRET, out)

    def test_edges_never_carry_a_title(self):
        h = Harness()
        h.settle(**window("chrome.exe", f"{self.SECRET} - Google Chrome"))
        h.advance(idle=200.0)
        h.settle(idle=200.0)
        self.assertNotIn(self.SECRET, repr(h.watcher.edges))
        self.assertNotIn(self.SECRET, repr(h.watcher.drain_edges()))

    def test_the_engine_never_receives_a_title(self):
        """The context handed to the engine is the only channel, and it is clean."""
        h = Harness()
        h.settle(**window("chrome.exe", f"{self.SECRET} - Google Chrome"))
        context = h.watcher.current_context()
        self.assertNotIn(self.SECRET, repr(context))
        self.assertEqual(sorted(context), ["app", "battery", "exe", "focus_minutes",
                                           "session_minutes", "site", "time"])

    def test_only_a_rule_display_name_reaches_the_context(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", f"{self.SECRET}"))
        self.assertEqual(h.watcher.context["app"], "Genshin Impact")

    def test_nothing_writes_a_title_to_disk(self):
        """Sample a fake secret-bearing title and check no file grew."""
        before = {}
        folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                before[path] = os.path.getsize(path)
        h = Harness()
        h.settle(**window("chrome.exe", f"{self.SECRET} - Google Chrome"))
        for path, size in before.items():
            self.assertEqual(os.path.getsize(path), size,
                             f"{path} changed size while sampling")


class TestNoForbiddenFeatures(unittest.TestCase):
    """The out-of-scope list, checked against the source rather than trusted."""

    @staticmethod
    def source(name):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, name), encoding="utf-8") as fh:
            return fh.read()

    def test_no_keyboard_or_mouse_content_reading(self):
        """Only the idle *duration* from GetLastInputInfo is allowed."""
        text = self.source("system_watcher.py")
        for banned in ("GetAsyncKeyState", "GetKeyState", "GetKeyboardState",
                       "SetWindowsHookEx", "GetClipboardData", "keybd_event",
                       "SendInput"):
            self.assertNotIn(banned, text)

    def test_no_screenshots_or_ocr(self):
        text = self.source("system_watcher.py")
        for banned in ("BitBlt", "PrintWindow", "GetDC", "ImageGrab", "pytesseract"):
            self.assertNotIn(banned, text)

    def test_no_network_calls_to_identify_apps(self):
        text = self.source("system_watcher.py")
        for banned in ("urlopen", "requests", "socket.gethostbyname",
                       "http.client", "aiohttp"):
            self.assertNotIn(banned, text)

    def test_psutil_is_still_optional(self):
        text = self.source("system_watcher.py")
        self.assertIn("psutil = None", text)

    def test_the_real_probes_survive_without_psutil(self):
        probes = Probes()
        for name in ("battery", "cpu_percent", "memory_percent",
                     "disk_free_percent", "network_up", "boot_time",
                     "monitor_count"):
            self.assertTrue(callable(getattr(probes, name)))
        # disk_free_percent uses shutil, so it works with no psutil at all
        free = probes.disk_free_percent()
        self.assertTrue(free is None or 0.0 <= free <= 100.0)


class FakeEdges:
    """A watcher stand-in that only has edges, for the reactor."""

    def __init__(self):
        self.edges = []

    def drain_edges(self):
        e, self.edges = self.edges, []
        return e


class FakeSpeaker:
    def __init__(self, name="Ako"):
        self.name = name

    def speech_ok(self):
        return True

    def say(self, text, dur=None):
        pass


class TestReactorOverhead(unittest.TestCase):
    def test_a_poll_with_no_edges_is_cheap(self):
        engine = DialogueEngine()
        reactor = StateReactor(engine, FakeEdges(), [FakeSpeaker()])
        start = time.perf_counter()
        for _ in range(10000):
            reactor.poll()
        each = (time.perf_counter() - start) / 10000.0 * 1e6
        self.assertLess(each, 50.0, f"an empty poll took {each:.1f} us")


if __name__ == "__main__":
    unittest.main(verbosity=2)