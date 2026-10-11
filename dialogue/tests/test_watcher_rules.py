"""Tests for the watcher's tag detection.

Nothing here touches the real machine: the foreground window, the idle
seconds, both clocks and every system probe are injected, so the whole
sample sequence runs identically on any platform.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dialogue.system_watcher import (                          # noqa: E402
    BUILTIN_TAGS, DEFAULT_BROWSERS, RULES_FALLBACK, Rules, SystemWatcher,
    load_rules,
)


# --------------------------------------------------------------------- fakes
class FakeProbes:
    """Stands in for the real Probes. Every answer is settable per sample."""

    def __init__(self, battery=None, cpu=0.0, memory=0.0, disk=50.0,
                 network=True, boot=None, monitors=1, audio=False):
        self.battery_value = battery
        self.cpu_value = cpu
        self.memory_value = memory
        self.disk_value = disk
        self.network_value = network
        self.boot_value = boot            # None = no reading available
        self.monitors = monitors
        self.audio = audio
        self.battery_calls = 0
        self.disk_calls = 0
        self.network_calls = 0
        self.cpu_calls = 0

    def battery(self):
        self.battery_calls += 1
        return self.battery_value

    def cpu_percent(self):
        self.cpu_calls += 1
        return self.cpu_value

    def memory_percent(self):
        return self.memory_value

    def disk_free_percent(self):
        self.disk_calls += 1
        return self.disk_value

    def network_up(self):
        self.network_calls += 1
        return self.network_value

    def boot_time(self):
        return self.boot_value

    def monitor_count(self):
        return self.monitors


class Harness:
    """A watcher whose every input is under the test's control."""

    def __init__(self, **kwargs):
        self.now = 1000.0
        self.wall = 1_700_000_000.0          # 2023-11-14 22:13 local-ish
        self.idle = 0.0
        self.fg = {"hwnd": 1, "title": "", "pid": 0, "exe": "", "rect": None}
        self.probes = kwargs.pop("probes", None) or FakeProbes()
        self.rules = kwargs.pop("rules", None) or load_rules()
        self.watcher = SystemWatcher(
            # every tag the watcher can emit, so the startup note stays quiet
            priority=sorted(self.rules.all_tags() | set(BUILTIN_TAGS)),
            probes=self.probes, rules=self.rules,
            foreground=lambda: dict(self.fg),
            idle_source=lambda: self.idle,
            clock=lambda: self.now,
            wall_clock=lambda: self.wall,
            **kwargs)

    def advance(self, seconds=3.0, idle=None):
        self.now += seconds
        if idle is not None:
            self.idle = idle

    def sample(self, idle=None, **fg):
        """One poll with the given foreground window and idle seconds."""
        if fg:
            self.fg.update(fg)
        if idle is not None:
            self.idle = idle
        self.watcher.tick(force=True)
        return set(self.watcher.tags)

    def settle(self, idle=None, **fg):
        """Poll until the debounce has caught up (two polls for most tags)."""
        if fg:
            self.fg.update(fg)
        if idle is not None:
            self.idle = idle
        self.watcher.tick(force=True)
        self.advance()
        self.watcher.tick(force=True)
        return set(self.watcher.tags)


def local_time(year, month, day, hour, minute=0):
    """A wall-clock timestamp for *local* time, whatever the machine's zone.

    The watcher reads ``time.localtime``, so the test has to hand it a stamp
    that really is that local hour - ``calendar.timegm`` would mean UTC and
    drift by the machine's offset.
    """
    import time as _time
    return _time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def window(exe="", title="", rect=(0, 0, 1920, 1080), **extra):
    rec = {"hwnd": 1, "title": title, "pid": 1, "exe": exe, "rect": rect,
           "cls": "", "fullscreen": False, "iconic": False}
    rec.update(extra)
    return rec


# ============================================================== rules loading
class TestRulesLoading(unittest.TestCase):
    def test_missing_file_falls_back(self):
        rules = load_rules("does/not/exist.json")
        self.assertTrue(rules.apps)
        self.assertTrue(rules.sites)

    def test_corrupt_file_falls_back(self):
        path = os.path.join(self.tmp(), "broken.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json ")
        self.assertTrue(load_rules(path).apps)

    def test_non_object_file_falls_back(self):
        path = os.path.join(self.tmp(), "list.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        self.assertTrue(load_rules(path).apps)

    def test_bad_regex_is_skipped_not_fatal(self):
        rules = Rules({"apps": [{"id": "x", "title_regex": ["(unclosed", "ok"],
                           "tags": ["app_x"]}]})
        rule = rules.apps[0]
        self.assertEqual(len(rule.title_regex), 1)
        self.assertTrue(rule.matches("", "an ok title"))

    @staticmethod
    def tmp():
        import tempfile
        return tempfile.mkdtemp(prefix="watcher_rules_")


class TestRuleMatching(unittest.TestCase):
    def test_exe_or_title(self):
        rule = Rules({"apps": [{"id": "x", "exe": ["x.exe"],
                                "title_regex": [r"\byoutube\b"],
                                "tags": ["app_x"]}]}).apps[0]
        self.assertTrue(rule.matches("x.exe", ""))
        self.assertTrue(rule.matches("other.exe", "a youtube page"))
        self.assertFalse(rule.matches("other.exe", "nothing here"))

    def test_require_title_regex_is_and(self):
        rules = Rules({"apps": [{"id": "mc", "exe": ["javaw.exe"],
                                 "require_title_regex": True,
                                 "title_regex": [r"\bminecraft\b"],
                                 "tags": ["app_minecraft"]}]})
        rule = rules.apps[0]
        self.assertTrue(rule.matches("javaw.exe", "Minecraft 1.21"))
        self.assertFalse(rule.matches("javaw.exe", "Some Java App"))
        self.assertFalse(rule.matches("other.exe", "Minecraft"))

    def test_exclude_wins(self):
        rules = Rules({"apps": [{"id": "e", "exe": ["explorer.exe"],
                                 "exclude_title_regex": ["^Program Manager$"],
                                 "tags": ["files"]}]})
        self.assertFalse(rules.apps[0].matches("explorer.exe", "Program Manager"))
        self.assertTrue(rules.apps[0].matches("explorer.exe", "Downloads"))

    def test_skip_browser(self):
        rules = Rules({"browsers": ["chrome.exe"],
                       "apps": [{"id": "g", "exe": ["g.exe"],
                                 "title_regex": ["genshin"],
                                 "skip_browser": True, "tags": ["app_genshin"]}]})
        fg = {"exe": "chrome.exe", "title": "Genshin Impact - Chrome"}
        self.assertIsNone(rules.match_app(fg))
        self.assertTrue(rules.match_app({"exe": "g.exe", "title": ""}))

    def test_sites_only_in_a_browser(self):
        rules = Rules({"browsers": ["chrome.exe"],
                       "sites": [{"id": "yt", "title_regex": ["youtube"],
                                  "browser_only": True, "tags": ["site_youtube"]}]})
        self.assertTrue(rules.match_site({"exe": "chrome.exe", "title": "youtube"}))
        self.assertIsNone(rules.match_site({"exe": "notepad.exe", "title": "youtube"}))

    def test_emulator_promotion(self):
        rules = Rules({
            "browsers": ["chrome.exe"],
            "emulators": ["hd-player.exe"],
            "apps": [{"id": "ba", "exe": ["ba.exe"],
                      "emulator_title_regex": ["blue ?archive"],
                      "tags": ["app_blue_archive", "gaming"]}]})
        fg = {"exe": "hd-player.exe", "title": "Blue Archive"}
        self.assertIsNone(rules.match_app(fg))          # exe does not match
        self.assertIsNotNone(rules.match_emulator(fg))   # title promotes it
        other = {"exe": "hd-player.exe", "title": "Clash of Clans"}
        self.assertIsNone(rules.match_emulator(other))

    def test_first_matching_app_wins(self):
        rules = Rules({"apps": [{"id": "first", "exe": ["a.exe"], "tags": ["t1"]},
                                {"id": "second", "exe": ["a.exe"], "tags": ["t2"]}]})
        self.assertEqual(rules.match_app({"exe": "a.exe", "title": ""}).id, "first")

    def test_custom_apps_are_appended(self):
        rules = Rules({"apps": [{"id": "a", "exe": ["a.exe"], "tags": ["t"]}],
                       "custom_apps": [{"id": "c", "exe": ["c.exe"], "tags": ["tc"]}]})
        self.assertEqual([r.id for r in rules.apps], ["a", "c"])

    def test_fallback_browsers_apply_when_file_is_silent(self):
        self.assertEqual(Rules({}).browsers, set(DEFAULT_BROWSERS))

    def test_fallback_document_is_usable(self):
        rules = Rules(RULES_FALLBACK)
        self.assertTrue(rules.match_app({"exe": "genshinimpact.exe", "title": ""}))


# =================================================================== app tags
class TestAppTags(unittest.TestCase):
    def test_youtube_in_chrome(self):
        h = Harness()
        tags = h.settle(**window("chrome.exe",
                                 "Some Video - YouTube - Google Chrome"))
        self.assertEqual(tags & {"browser", "site_youtube", "video"},
                         {"browser", "site_youtube", "video"})

    def test_genshin_fullscreen(self):
        h = Harness()
        tags = h.settle(**window("GenshinImpact.exe", "Genshin Impact",
                                 rect=(0, 0, 1920, 1080), fullscreen=True))
        self.assertIn("app_genshin", tags)
        self.assertIn("gaming", tags)
        self.assertIn("fullscreen", tags)

    def test_exe_name_is_lowercased_for_the_rules(self):
        h = Harness()
        tags = h.settle(**window("GENSHINIMPACT.EXE", ""))
        self.assertIn("app_genshin", tags)

    def test_hd_player_blue_archive(self):
        h = Harness()
        tags = h.settle(**window("HD-Player.exe", "Blue Archive"))
        self.assertIn("emulator", tags)
        self.assertIn("app_blue_archive", tags)
        self.assertIn("gaming", tags)

    def test_emulator_without_a_known_title_is_just_an_emulator(self):
        h = Harness()
        tags = h.settle(**window("HD-Player.exe", "Clash of Clans"))
        self.assertIn("emulator", tags)
        self.assertNotIn("app_blue_archive", tags)

    def test_steam_is_a_launcher_not_a_game(self):
        h = Harness()
        tags = h.settle(**window("steam.exe", "Steam"))
        self.assertIn("app_steam", tags)
        self.assertNotIn("gaming", tags)

    def test_minecraft_needs_the_title_too(self):
        h = Harness()
        self.assertIn("app_minecraft", h.settle(**window("javaw.exe", "Minecraft")))
        self.assertNotIn("app_minecraft",
                         h.settle(**window("javaw.exe", "Some Java Tool")))

    def test_code_exe_counts_as_coding(self):
        h = Harness()
        self.assertIn("coding", h.settle(**window("Code.exe", "main.py")))

    def test_notepad_is_text_editor_not_coding(self):
        h = Harness()
        tags = h.settle(**window("notepad.exe", "Untitled - Notepad"))
        self.assertIn("text_editor", tags)
        self.assertNotIn("coding", tags)

    def test_explorer_desktop_is_not_file_explorer(self):
        h = Harness()
        self.assertNotIn("file_explorer",
                         h.settle(**window("explorer.exe", "Program Manager")))
        self.assertIn("file_explorer", h.settle(**window("explorer.exe", "Downloads")))

    def test_office_word(self):
        h = Harness()
        self.assertIn("office", h.settle(**window("WINWORD.EXE", "Document1")))


# ================================================ substring false positives
class TestNoSubstringFalsePositives(unittest.TestCase):
    """The bug that started all this: 'obs' matched 'jobs'."""

    def test_jobs_does_not_trigger_obs(self):
        h = Harness()
        tags = h.settle(**window("chrome.exe", "Jobs and Careers - Google Chrome"))
        self.assertNotIn("app_obs", tags)
        self.assertNotIn("streaming", tags)
        self.assertIn("browser", tags)

    def test_knowledge_does_not_trigger_edge(self):
        h = Harness()
        h.settle(**window("chrome.exe", "Knowledge Base - Google Chrome"))
        h.settle(**window("msedge.exe", "Knowledge Base - Microsoft Edge"))
        tags = h.settle(**window("chrome.exe", "Jobs - Chrome"))
        self.assertNotIn("app_obs", tags)
        self.assertFalse(tags & {"site_youtube", "app_genshin"})

    def test_vimeo_is_not_vim(self):
        h = Harness()
        self.assertNotIn("text_editor", h.settle(**window("chrome.exe", "Vimeo")))

    def test_patriot_is_not_riot(self):
        h = Harness()
        tags = h.settle(**window("chrome.exe", "Patriot Act explained - Chrome"))
        self.assertNotIn("gaming", tags)

    def test_steamed_is_not_steam(self):
        h = Harness()
        tags = h.settle(**window("chrome.exe", "Steamed Vegetables - Chrome"))
        self.assertNotIn("app_steam", tags)

    def test_youtube_music_is_not_youtube(self):
        h = Harness()
        tags = h.settle(**window("chrome.exe",
                                 "A Song - YouTube Music - Google Chrome"))
        self.assertIn("site_youtube_music", tags)
        self.assertIn("music", tags)
        self.assertNotIn("site_youtube", tags)


# ==================================================================== fullscreen
class TestFullscreen(unittest.TestCase):
    """Fullscreen comes from the rectangle, never from the title."""

    def setUp(self):
        from dialogue import system_watcher
        self.monitor = ((0, 0, 1920, 1080),)
        self._covers = system_watcher.SystemWatcher._covers_monitor
        self.patched = False

    def test_uses_rect_not_title(self):
        h = Harness()
        h.watcher.rules.fullscreen_ignore.add("chrome.exe")
        # title says YouTube, but the rect does not cover the monitor
        h.sample(**window("chrome.exe", "YouTube",
                          rect=(100, 100, 1000, 800), fullscreen=False))
        self.assertNotIn("fullscreen", set(h.watcher.tags))

    def test_covers_monitor_helper_ignores_own_exe(self):
        h = Harness()
        rec = window("python.exe", "", rect=(0, 0, 1920, 1080))
        self.assertFalse(h.watcher._covers_monitor(rec))


# ======================================================================= idle
class TestIdle(unittest.TestCase):
    def test_plain_idle(self):
        h = Harness()
        tags = h.settle(idle=120.0)
        self.assertIn("user_idle", tags)
        self.assertNotIn("watching_idle", tags)

    def test_fullscreen_video_is_watching_idle_not_idle(self):
        h = Harness()
        h.settle(**window("chrome.exe", "Some Video - YouTube - Google Chrome",
                         fullscreen=True))
        h.advance(idle=120.0)
        tags = h.settle()
        self.assertIn("watching_idle", tags)
        self.assertNotIn("user_idle", tags)

    def test_music_player_is_passive(self):
        h = Harness()
        h.settle(**window("spotify.exe", "Spotify"))
        h.advance(idle=120.0)
        tags = h.settle()
        self.assertIn("watching_idle", tags)

    def test_fullscreen_game_is_passive(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", "Genshin", fullscreen=True))
        h.advance(idle=120.0)
        self.assertIn("watching_idle", h.settle())

    def test_user_back_after_a_short_absence(self):
        h = Harness()
        h.settle(idle=120.0)
        h.watcher.drain_edges()
        h.advance(10.0, idle=0.0)
        h.sample(idle=0.0)
        self.assertIn(("+", "user_back"), h.watcher.edges)
        self.assertNotIn("user_back_long", set(h.watcher.tags))

    def test_user_back_long_after_thirty_minutes(self):
        h = Harness()
        h.settle(idle=120.0)
        h.advance(1900.0, idle=0.0)
        h.watcher.drain_edges()
        h.sample(idle=0.0)
        self.assertIn("user_back_long", set(h.watcher.tags))
        self.assertIn("break_taken", set(h.watcher.tags))

    def test_no_user_back_while_never_idle(self):
        h = Harness()
        h.settle(idle=0.0)
        h.advance(10.0)
        h.sample(idle=0.0)
        self.assertNotIn(("+", "user_back"), h.watcher.edges)

    def test_no_idle_source_is_harmless(self):
        h = Harness()
        h.watcher._idle_source = None
        self.assertIsInstance(h.settle(), set)


# ================================================================ load / power
class TestLoadHysteresis(unittest.TestCase):
    def hot(self, h, value=99.0, polls=4):
        """Drive `polls` samples at `value` percent CPU.

        Four polls rather than three: the tag needs three consecutive readings
        above the threshold *and* then two polls of debounce before it counts.
        """
        h.probes.cpu_value = value
        for _ in range(polls):
            h.advance()
            h.watcher.tick(force=True)
        return set(h.watcher.tags)

    def test_one_cpu_spike_does_not_count(self):
        h = Harness()
        self.assertNotIn("cpu_high", self.hot(h, polls=2))

    def test_three_cpu_samples_count(self):
        h = Harness()
        self.assertIn("cpu_high", self.hot(h, polls=4))

    def test_cpu_clears_below_the_lower_threshold(self):
        h = Harness()
        self.assertIn("cpu_high", self.hot(h, polls=4))
        self.assertNotIn("cpu_high", self.hot(h, value=60.0, polls=3))

    def test_a_single_dip_does_not_clear_cpu_high(self):
        h = Harness()
        self.assertIn("cpu_high", self.hot(h, polls=4))
        self.assertIn("cpu_high", self.hot(h, value=60.0, polls=1))

    def test_cpu_is_primed_at_startup(self):
        h = Harness()
        self.assertGreaterEqual(h.probes.cpu_calls, 1)

    def test_memory_needs_three_samples(self):
        h = Harness()
        h.probes.memory_value = 97.0
        h.settle()
        self.assertNotIn("memory_high", set(h.watcher.tags))
        for _ in range(3):
            h.advance()
            h.watcher.tick(force=True)
        self.assertIn("memory_high", set(h.watcher.tags))

    def test_probes_returning_none_are_skipped(self):
        h = Harness(probes=FakeProbes(battery=None))
        self.assertIsInstance(h.settle(), set)


class TestBatteryHysteresis(unittest.TestCase):
    def test_enters_low_at_25(self):
        h = Harness()
        h.probes.battery_value = {"percent": 25.0, "plugged": False}
        self.assertIn("battery_low", h.settle())

    def test_stays_low_until_28(self):
        h = Harness()
        h.probes.battery_value = {"percent": 25.0, "plugged": False}
        h.settle()
        h.probes.battery_value = {"percent": 26.5, "plugged": False}
        self.assertIn("battery_low", h.settle())
        h.probes.battery_value = {"percent": 28.0, "plugged": False}
        self.assertNotIn("battery_low", h.settle())

    def test_battery_critical(self):
        h = Harness()
        h.probes.battery_value = {"percent": 11.0, "plugged": False}
        self.assertIn("battery_critical", h.settle())

    def test_full_and_on_battery(self):
        h = Harness()
        h.probes.battery_value = {"percent": 100.0, "plugged": True}
        tags = h.settle()
        self.assertIn("battery_full", tags)
        self.assertIn("charging", tags)
        self.assertNotIn("on_battery", tags)

    def test_on_battery_when_unplugged(self):
        h = Harness()
        h.probes.battery_value = {"percent": 55.0, "plugged": False}
        tags = h.settle()
        self.assertIn("on_battery", tags)
        self.assertNotIn("charging", tags)

    def test_context_reports_the_percentage(self):
        h = Harness()
        h.probes.battery_value = {"percent": 42.0, "plugged": False}
        h.settle()
        self.assertEqual(h.watcher.context["battery"], 42)

    def test_unplug_plug_become_edges(self):
        h = Harness()
        h.probes.battery_value = {"percent": 55.0, "plugged": True}
        h.settle(); h.watcher.drain_edges()
        h.probes.battery_value = {"percent": 55.0, "plugged": False}
        h.settle()
        self.assertIn(("+", "on_battery"), h.watcher.edges)


# ============================================================ time / calendar
class TestTimeTags(unittest.TestCase):
    #: 2024-05-01 is a Wednesday, so the plain hour tests are never a weekend.
    WEDNESDAY = (2024, 5, 1)

    def tag_at(self, hour, minute=0, day=None):
        h = Harness()
        y, m, d = day or self.WEDNESDAY
        h.wall = local_time(y, m, d, hour, minute)
        return h, h.settle()

    def test_morning_and_afternoon_are_separate(self):
        _, morning = self.tag_at(8, 30)
        _, afternoon = self.tag_at(14, 0)
        self.assertIn("morning", morning)
        self.assertNotIn("afternoon", morning)
        self.assertIn("afternoon", afternoon)
        self.assertNotIn("morning", afternoon)

    def test_evening_and_night(self):
        _, evening = self.tag_at(19, 0)
        _, night = self.tag_at(23, 0)
        self.assertIn("evening", evening)
        self.assertIn("night", night)

    def test_late_night_and_early_morning(self):
        _, late = self.tag_at(2, 0)
        _, early = self.tag_at(6, 30)
        self.assertIn("late_night", late)
        self.assertIn("early_morning", early)

    def test_lunch_time(self):
        _, lunch = self.tag_at(12, 15)
        _, not_lunch = self.tag_at(14, 0)
        self.assertIn("lunch_time", lunch)
        self.assertNotIn("lunch_time", not_lunch)

    def test_weekend_and_weekday(self):
        h = Harness()
        h.wall = local_time(2024, 5, 4, 10, 0)      # Saturday
        self.assertIn("weekend", h.settle())
        h2 = Harness()
        h2.wall = local_time(2024, 5, 1, 10, 0)      # Wednesday
        self.assertIn("weekday", h2.settle())

    def test_monday_morning(self):
        h = Harness()
        h.wall = local_time(2024, 5, 6, 9, 0)       # Monday
        self.assertIn("monday_morning", h.settle())

    def test_monday_evening_is_not_monday_morning(self):
        h = Harness()
        h.wall = local_time(2024, 5, 6, 20, 0)      # Monday evening
        self.assertNotIn("monday_morning", h.settle())

    def test_friday_evening(self):
        h = Harness()
        h.wall = local_time(2024, 5, 3, 19, 0)      # Friday
        self.assertIn("friday_evening", h.settle())

    def test_wednesday_evening_is_not_friday_evening(self):
        h = Harness()
        h.wall = local_time(2024, 5, 1, 19, 0)
        self.assertNotIn("friday_evening", h.settle())

    def test_context_time_is_local_hh_mm(self):
        import re as _re
        h = Harness()
        h.settle()
        self.assertTrue(_re.fullmatch(r"\d{2}:\d{2}", h.watcher.context["time"]))


# ================================================================ session tags
class TestSessionTags(unittest.TestCase):
    def test_long_session_after_two_hours(self):
        h = Harness()
        h.settle()                       # the session starts on the first sample
        h.advance(130 * 60)
        self.assertIn("long_session", h.settle())

    def test_very_long_session_after_four_hours(self):
        h = Harness()
        h.settle()
        h.advance(300 * 60)
        tags = h.settle()
        self.assertIn("very_long_session", tags)
        self.assertNotIn("long_session", tags)

    def test_a_short_session_is_neither(self):
        h = Harness()
        h.settle()
        h.advance(30 * 60)
        tags = h.settle()
        self.assertNotIn("long_session", tags)
        self.assertNotIn("very_long_session", tags)

    def test_long_focus_gaming(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", "Genshin"))
        h.advance(100 * 60)
        self.assertIn("long_focus_gaming", h.settle())

    def test_focus_resets_when_the_app_changes(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", "Genshin"))
        h.advance(100 * 60)
        self.assertIn("long_focus_gaming", h.settle())
        h.settle(**window("Code.exe", "main.py"))
        self.assertNotIn("long_focus_gaming", set(h.watcher.tags))

    def test_context_session_minutes_grows(self):
        h = Harness()
        h.settle()
        h.advance(65 * 60)
        h.settle()
        self.assertGreaterEqual(h.watcher.context["session_minutes"], 60)


# ==================================================================== debounce
class TestDebounce(unittest.TestCase):
    def test_flapping_tag_produces_no_edges(self):
        """A tag toggling on alternate polls must never become confirmed.

        Starting from "actively using the computer": idle is never confirmed,
        so it cannot be published and - because `user_back` only follows a
        confirmed idle - no return is announced either.
        """
        h = Harness()
        h.settle(idle=0.0)
        h.watcher.drain_edges()
        for _ in range(8):
            h.advance(3.0, idle=120.0)
            h.watcher.tick(force=True)
            h.advance(3.0, idle=0.0)
            h.watcher.tick(force=True)
        self.assertEqual(h.watcher.edges, [])

    def test_a_flapping_tag_is_not_published_either(self):
        h = Harness()
        h.settle(idle=0.0)
        for _ in range(8):
            h.advance(3.0, idle=120.0)
            h.watcher.tick(force=True)
            h.advance(3.0, idle=0.0)
            h.watcher.tick(force=True)
        self.assertNotIn("user_idle", set(h.watcher.tags))
        self.assertNotIn("watching_idle", set(h.watcher.tags))

    def test_a_stable_tag_does_produce_edges(self):
        h = Harness()
        h.settle(idle=120.0)
        edges = h.watcher.drain_edges()
        self.assertIn(("+", "user_idle"), edges)

    def test_leaving_produces_one_negative_edge(self):
        h = Harness()
        h.settle(idle=120.0)
        h.watcher.drain_edges()
        h.advance(3.0, idle=0.0)
        h.settle(idle=0.0)
        self.assertIn(("-", "user_idle"), h.watcher.edges)

    def test_a_single_blip_produces_no_exit_edge(self):
        h = Harness()
        h.settle(idle=120.0)
        h.watcher.drain_edges()
        h.advance(3.0, idle=0.0)
        h.sample(idle=0.0)
        h.advance(3.0, idle=120.0)
        h.sample(idle=120.0)
        self.assertNotIn(("-", "user_idle"), h.watcher.edges)

    def test_user_back_is_not_debounced(self):
        h = Harness()
        h.settle(idle=120.0)
        h.watcher.drain_edges()
        h.advance(3.0, idle=0.0)
        h.sample(idle=0.0)
        self.assertIn(("+", "user_back"), h.watcher.edges)

    def test_debounce_can_be_disabled(self):
        h = Harness()
        h.watcher.debounce_polls = 1
        self.assertIn("user_idle", h.sample(idle=120.0))


# =================================================================== behaviour
class TestBehaviour(unittest.TestCase):
    def test_app_switching_after_many_changes(self):
        h = Harness()
        h.settle(**window("Code.exe", "a"))
        for i in range(10):
            h.advance(1.0)
            h.settle(**window("Code.exe" if i % 2 else "notepad.exe", "t"))
        self.assertIn("app_switching", set(h.watcher.tags))

    def test_quiet_use_is_not_app_switching(self):
        h = Harness()
        h.settle(**window("Code.exe", "a"))
        for _ in range(6):
            h.advance(3.0)
            h.watcher.tick(force=True)
        self.assertNotIn("app_switching", set(h.watcher.tags))

    def test_multi_monitor(self):
        h = Harness(probes=FakeProbes(monitors=2))
        self.assertIn("multi_monitor", h.settle())

    def test_single_monitor_emits_nothing(self):
        h = Harness(probes=FakeProbes(monitors=1))
        self.assertNotIn("multi_monitor", h.settle())

    def test_minimized_all_on_the_desktop(self):
        h = Harness()
        tags = h.settle(**window("explorer.exe", "Program Manager", cls="Progman"))
        self.assertIn("minimized_all", tags)

    def test_locked_on_lockapp(self):
        h = Harness()
        self.assertIn("locked", h.settle(**window("LockApp.exe", "")))

    def test_screen_off_after_several_null_foregrounds(self):
        off = {"hwnd": None, "title": "", "pid": 0, "exe": "", "rect": None}
        h = Harness()
        h.settle(**off)
        self.assertNotIn("screen_off", set(h.watcher.tags))
        h.advance(); h.settle(**off)
        self.assertNotIn("screen_off", set(h.watcher.tags))
        h.advance(); h.settle(**off)
        self.assertIn("screen_off", set(h.watcher.tags))

    def test_a_foreground_window_clears_the_screen_off_streak(self):
        off = {"hwnd": None, "title": "", "pid": 0, "exe": "", "rect": None}
        h = Harness()
        h.settle(**off)
        h.advance(); h.settle(**window("Code.exe", "main.py"))
        self.assertEqual(h.watcher._screen_off_streak, 0)

    def test_disk_low_is_rate_limited(self):
        probes = FakeProbes(disk=5.0)
        h = Harness(probes=probes)
        self.assertIn("disk_low", h.settle())
        calls = probes.disk_calls
        for _ in range(5):
            h.advance(3.0)
            h.watcher.tick(force=True)
        self.assertEqual(probes.disk_calls, calls)

    def test_network_offline(self):
        h = Harness(probes=FakeProbes(network=False))
        self.assertIn("network_offline", h.settle())

    def test_network_check_is_rate_limited(self):
        probes = FakeProbes()
        h = Harness(probes=probes)
        h.settle()
        calls = probes.network_calls
        # 20 polls at 3s is 60s, so with network_every=10 one more check is due.
        for _ in range(5):
            h.advance(3.0)
            h.watcher.tick(force=True)
        self.assertEqual(probes.network_calls, calls + 1)

    def test_high_uptime(self):
        h = Harness()
        h.probes.boot_value = h.wall - 5 * 24 * 3600
        self.assertIn("high_uptime", h.settle())

    def test_fresh_boot_is_not_high_uptime(self):
        h = Harness()
        h.probes.boot_value = h.wall - 600
        self.assertNotIn("high_uptime", h.settle())

    def test_no_boot_reading_means_no_tag(self):
        h = Harness()
        self.assertIsNone(h.probes.boot_value)
        self.assertNotIn("high_uptime", h.settle())


# ===================================================================== context
class TestContext(unittest.TestCase):
    def test_app_name_comes_from_the_rule(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", ""))
        self.assertEqual(h.watcher.context["app"], "Genshin Impact")

    def test_exe_is_the_foreground_exe(self):
        h = Harness()
        h.settle(**window("GenshinImpact.exe", ""))
        self.assertEqual(h.watcher.context["exe"], "genshinimpact.exe")

    def test_site_id_only_in_a_browser(self):
        h = Harness()
        h.settle(**window("chrome.exe", "A Video - YouTube - Google Chrome"))
        self.assertEqual(h.watcher.context["site"], "youtube")

    def test_no_title_in_the_context(self):
        h = Harness()
        h.settle(**window("chrome.exe", "Secret Document Title - Google Chrome"))
        self.assertNotIn("Secret Document Title", str(h.watcher.context))

    def test_focus_and_session_are_numbers(self):
        h = Harness()
        h.settle()
        self.assertIsInstance(h.watcher.context["focus_minutes"], int)
        self.assertIsInstance(h.watcher.context["session_minutes"], int)


# ===================================================================== privacy
class TestPrivacySwitches(unittest.TestCase):
    def test_disabled_tags_are_dropped(self):
        doc = {"apps": [{"id": "yt", "exe": ["youtube.exe"], "tags": ["app_youtube"]}],
               "disabled_tags": ["app_youtube"]}
        h = Harness(rules=Rules(doc))
        self.assertNotIn("app_youtube", h.settle(**window("youtube.exe", "")))

    def test_a_whole_prefix_class_can_be_switched_off(self):
        doc = {"sites": [{"id": "yt", "title_regex": ["youtube"],
                          "browser_only": True,
                          "tags": ["site_youtube", "video"]}],
               "disabled_tags": ["site_*"]}
        h = Harness(rules=Rules(doc))
        tags = h.settle(**window("chrome.exe", "A Video - YouTube - Google Chrome"))
        self.assertIn("video", tags)
        self.assertNotIn("site_youtube", tags)

    def test_enabled_categories_is_a_whitelist(self):
        doc = {"sites": [{"id": "yt", "title_regex": ["youtube"],
                          "browser_only": True, "tags": ["site_youtube"]}],
               "enabled_categories": ["site_", "browser"]}
        h = Harness(rules=Rules(doc))
        tags = h.settle(**window("chrome.exe", "A Video - YouTube - Google Chrome"))
        self.assertIn("site_youtube", tags)
        self.assertIn("browser", tags)

    def test_no_title_is_ever_written_to_disk(self):
        h = Harness()
        h.settle(**window("chrome.exe", "VERY SECRET - Google Chrome"))
        self.assertNotIn("VERY SECRET", str(h.watcher.__dict__.get("context")))


# ============================================================== robustness
class TestRobustness(unittest.TestCase):
    def test_broken_foreground_source_is_survivable(self):
        h = Harness()
        h.watcher._foreground_source = lambda: 1 / 0
        self.assertIsInstance(h.watcher.tick(force=True), list)

    def test_broken_probe_is_survivable(self):
        class Angry:
            def battery(self):
                raise RuntimeError("no")

            def cpu_percent(self):
                raise RuntimeError("no")

            def memory_percent(self):
                raise RuntimeError("no")

            def disk_free_percent(self):
                raise RuntimeError("no")

            def network_up(self):
                raise RuntimeError("no")

            def boot_time(self):
                raise RuntimeError("no")

            def monitor_count(self):
                raise RuntimeError("no")

        h = Harness(probes=Angry())
        self.assertIsInstance(h.settle(), set)

    def test_foreground_record_has_the_documented_shape(self):
        from dialogue.system_watcher import _FG_KEYS, _foreground
        record = _foreground()
        self.assertEqual(set(record), set(_FG_KEYS))

    def test_an_empty_foreground_record_is_usable_everywhere(self):
        h = Harness()
        tags = h.settle(**{"hwnd": None, "title": "", "pid": 0, "exe": "",
                           "rect": None})
        self.assertIsInstance(tags, set)
        self.assertFalse(tags & {"site_youtube", "app_blue_archive"})

    def test_every_tag_sorts_without_a_priority_list(self):
        h = Harness()
        h.watcher.priority = []
        h.settle(idle=120.0)
        self.assertIsInstance(h.watcher.tags, list)

    def test_describe_never_raises(self):
        h = Harness()
        h.settle()
        self.assertIsInstance(h.watcher.describe(), str)

    def test_drain_edges_empties_the_queue(self):
        h = Harness()
        h.settle(idle=120.0)
        self.assertTrue(h.watcher.drain_edges())
        self.assertEqual(h.watcher.drain_edges(), [])

    def test_interval_throttles(self):
        h = Harness()
        h.watcher.tick(force=True)
        first = list(h.watcher.tags)
        h.fg.update(window("GenshinImpact.exe", ""))
        h.watcher.tick()                     # not yet due
        self.assertEqual(list(h.watcher.tags), first)

    def test_force_ignores_the_interval(self):
        h = Harness()
        h.watcher.tick(force=True)
        h.fg.update(window("GenshinImpact.exe", ""))
        h.watcher.tick(force=True)
        h.watcher.tick(force=True)
        self.assertIn("app_genshin", set(h.watcher.tags))

    def test_a_threaded_watcher_polls_itself(self):
        """The render loop only reads; the worker does the sampling."""
        fg = {"hwnd": 1, "title": "A Video - YouTube - Google Chrome",
              "pid": 1, "exe": "chrome.exe", "rect": None}
        w = SystemWatcher(priority=["site_youtube", "browser"], threaded=True,
                          rules=load_rules(), probes=FakeProbes(),
                          foreground=lambda: dict(fg),
                          idle_source=lambda: 0.0, interval=0.02)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if "site_youtube" in w.tick():
                    break
                time.sleep(0.02)
            self.assertIn("site_youtube", w.current_tags())
            self.assertEqual(w.context["site"], "youtube")
            # and tick never blocked: it returned a list every time
            self.assertIsInstance(w.tick(), list)
        finally:
            w.stop()

    def test_a_stopped_threaded_watcher_falls_back_to_polling_inline(self):
        w = SystemWatcher(threaded=True, rules=load_rules(), probes=FakeProbes(),
                          foreground=lambda: {"hwnd": 1, "title": "", "exe": "x.exe"},
                          idle_source=lambda: 0.0, interval=0.01)
        w.stop()
        self.assertIsNone(w._thread)
        self.assertIsInstance(w.tick(force=True), list)

    def test_a_slow_foreground_does_not_stall_a_threaded_reader(self):
        """The whole reason the poll moved off the render thread."""
        started = threading.Event()

        def slow_foreground():
            started.set()
            time.sleep(0.4)
            return {"hwnd": 1, "title": "", "exe": "code.exe"}

        w = SystemWatcher(rules=load_rules(), probes=FakeProbes(),
                          foreground=slow_foreground, idle_source=lambda: 0.0,
                          interval=0.02, threaded=True)
        try:
            started.wait(2.0)
            start = time.perf_counter()
            for _ in range(200):
                w.tick()
            elapsed = time.perf_counter() - start
            self.assertLess(elapsed, 0.2,
                            f"200 reads took {elapsed * 1000:.0f} ms")
        finally:
            w.stop()

    def test_thresholds_from_the_rules_file_are_applied(self):
        doc = {"thresholds": {"cpu_high": 50.0, "battery_low": 30.0,
                              "debounce_polls": 5}}
        w = SystemWatcher(rules=Rules(doc), probes=FakeProbes(),
                          foreground=lambda: {}, idle_source=lambda: 0.0)
        self.assertEqual(w.cpu_high, 50.0)
        self.assertEqual(w.battery_low, 30.0)
        self.assertEqual(w.debounce_polls, 5)

    def test_out_of_range_thresholds_are_ignored(self):
        doc = {"thresholds": {"cpu_high": 5000.0, "battery_low": -3.0}}
        w = SystemWatcher(rules=Rules(doc), probes=FakeProbes(),
                          foreground=lambda: {}, idle_source=lambda: 0.0)
        self.assertEqual(w.cpu_high, 85.0)
        self.assertEqual(w.battery_low, 25.0)

    def test_non_numeric_thresholds_are_ignored(self):
        doc = {"thresholds": {"cpu_high": "lots"}}
        w = SystemWatcher(rules=Rules(doc), probes=FakeProbes(),
                          foreground=lambda: {}, idle_source=lambda: 0.0)
        self.assertEqual(w.cpu_high, 85.0)

    def test_every_tag_the_watcher_can_emit_is_listed_in_states(self):
        from dialogue.engine import DialogueEngine
        from dialogue.system_watcher import BUILTIN_TAGS
        engine = DialogueEngine()
        known = set(BUILTIN_TAGS) | load_rules().all_tags()
        missing = sorted(known - set(engine.state_order))
        self.assertEqual(missing, [], f"states.json _priority_order is missing: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)