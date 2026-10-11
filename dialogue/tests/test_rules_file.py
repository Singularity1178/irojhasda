"""Checks on the shipped watcher_rules.json itself.

The file is data the user edits, so these guard against the mistakes that
silently stop a rule firing: no id, no tags, nothing to match on, a duplicate
id, or a rule that can never be reached.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dialogue.system_watcher import (                          # noqa: E402
    Rule, Rules, load_rules,
)

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "watcher_rules.json")

#: rules that legitimately carry an `app_`/`site_` tag and nothing else.
#: A store is not a game (it must not raise `gaming`), and chat is not a
#: category the pets have pools for.
UNCATEGORIZED = {"steam", "epic", "discord", "discord_web", "telegram",
                 "slack", "notion", "twitter", "reddit", "facebook"}


class TestRulesFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATH, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.rules = load_rules(PATH)

    # ------------------------------------------------------------- structure
    def test_every_app_rule_has_an_id_and_tags(self):
        for rule in self.rules.apps:
            self.assertTrue(rule.id, "an app rule has no id")
            self.assertTrue(rule.tags, f"{rule.id} adds no tags")

    def test_every_site_rule_has_an_id_and_tags(self):
        for rule in self.rules.sites:
            self.assertTrue(rule.id, "a site rule has no id")
            self.assertTrue(rule.tags, f"{rule.id} adds no tags")

    def test_no_duplicate_app_ids(self):
        ids = [r.id for r in self.rules.apps]
        self.assertEqual(len(ids), len(set(ids)),
                         "duplicate app rule ids: "
                         + str([i for i in ids if ids.count(i) > 1]))

    def test_no_duplicate_site_ids(self):
        ids = [r.id for r in self.rules.sites]
        self.assertEqual(len(ids), len(set(ids)),
                         "duplicate site rule ids: "
                         + str([i for i in ids if ids.count(i) > 1]))

    def test_every_rule_something_to_match_on(self):
        for rule in self.rules.apps + self.rules.sites:
            self.assertTrue(rule.exe or rule.title_regex or rule.emulator_title_regex,
                            f"{rule.id} can never match anything")

    def test_every_rule_has_a_display_name(self):
        for rule in self.rules.apps + self.rules.sites:
            self.assertTrue(rule.name, f"{rule.id} has no display name")

    def test_the_file_documents_itself(self):
        notes = " ".join(v for k, v in self.doc.items() if str(k).startswith("_"))
        for word in ("exe", "title_regex", "emulator_title_regex",
                     "require_title_regex", "skip_browser", "browser_only"):
            self.assertIn(word, notes, f"the _note never mentions {word}")

    def test_thresholds_are_inside_their_bounds(self):
        from dialogue.system_watcher import SystemWatcher
        bounds = SystemWatcher.THRESHOLD_BOUNDS
        for name, value in self.rules.thresholds.items():
            if name in ("self_exe",):
                continue
            self.assertIn(name, bounds, f"{name} is not a known threshold")
            low, high = bounds[name]
            self.assertIsInstance(value, (int, float))
            self.assertTrue(low <= value <= high,
                            f"{name}={value} is outside {low}-{high}")

    def test_every_tag_the_file_emits_is_in_the_priority_order(self):
        from dialogue import DialogueEngine
        known = set(DialogueEngine().state_order)
        emitted = self.rules.all_tags()
        self.assertEqual(sorted(emitted - known), [],
                         "tags in watcher_rules.json with no priority entry")

    def test_specific_tags_also_carry_their_category(self):
        """A specific tag must never arrive alone: the general pools depend on it."""
        categories = {"gaming", "video", "coding", "music", "office",
                      "streaming", "meeting", "ai_chat", "text_editor",
                      "creative", "art_browsing"}
        for rule in self.rules.apps + self.rules.sites:
            specific = [t for t in rule.tags
                        if t.startswith(("app_", "site_"))]
            if not specific:
                continue
            if rule.id in UNCATEGORIZED:
                self.assertEqual(len(rule.tags), 1, f"{rule.id} should have no category")
                continue
            self.assertTrue(set(rule.tags) & categories,
                            f"{rule.id} adds {specific} with no category tag")

    def test_tags_are_lowercase_and_underscored(self):
        for rule in self.rules.apps + self.rules.sites:
            for tag in rule.tags:
                self.assertEqual(tag, tag.lower(), f"{rule.id}: {tag}")
                self.assertRegex(tag, r"^[a-z][a-z0-9_]*$")

    # --------------------------------------------------------------- coverage
    def test_the_games_the_plan_names_are_present(self):
        wanted = {"blue_archive", "genshin", "star_rail", "zzz", "wuwa",
                  "honkai_impact_3", "arknights", "fgo", "valorant",
                  "league", "minecraft", "osu", "steam"}
        self.assertTrue(wanted <= {r.id for r in self.rules.apps},
                        f"missing games: {wanted - {r.id for r in self.rules.apps}}")

    def test_the_sites_the_plan_names_are_present(self):
        wanted = {"youtube", "twitch", "netflix", "bilibili", "crunchyroll",
                  "disney_plus", "niconico", "twitter", "reddit", "facebook",
                  "discord_web", "github", "stackoverflow", "notion",
                  "google_docs", "chatgpt", "claude", "gemini", "meet", "pixiv"}
        self.assertTrue(wanted <= {r.id for r in self.rules.sites},
                        f"missing sites: {wanted - {r.id for r in self.rules.sites}}")

    def test_the_apps_the_plan_names_are_present(self):
        wanted = {"obs", "vlc", "mpv", "spotify", "foobar2000", "discord",
                  "telegram", "slack", "zoom", "teams", "code", "pycharm",
                  "intellij", "android_studio", "visual_studio", "terminal",
                  "word", "excel", "powerpoint", "photoshop", "clip_studio",
                  "blender", "krita", "explorer", "task_manager"}
        self.assertTrue(wanted <= {r.id for r in self.rules.apps},
                        f"missing apps: {wanted - {r.id for r in self.rules.apps}}")

    def test_the_emulators_the_plan_names_are_listed(self):
        wanted = {"hd-player.exe", "dnplayer.exe", "mumuplayer.exe",
                  "nemuplayer.exe", "nox.exe", "memu.exe", "googleplaygames.exe"}
        self.assertTrue(wanted <= self.rules.emulators,
                        f"missing emulators: {wanted - self.rules.emulators}")

    def test_the_browsers_the_plan_names_are_listed(self):
        wanted = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                  "opera.exe", "vivaldi.exe", "arc.exe"}
        self.assertTrue(wanted <= self.rules.browsers,
                        f"missing browsers: {wanted - self.rules.browsers}")

    def test_privacy_switches_are_present_and_empty_by_default(self):
        self.assertIn("disabled_tags", self.doc)
        self.assertIn("enabled_categories", self.doc)
        self.assertEqual(self.doc["disabled_tags"], [])
        self.assertEqual(self.doc["enabled_categories"], [])

    def test_custom_apps_is_an_empty_list_to_copy_into(self):
        self.assertEqual(self.doc["custom_apps"], [])

    def test_no_rule_creates_a_tag_for_adult_content(self):
        """A deliberately broad check: the vocabulary stays neutral."""
        banned = ("adult", "porn", "nsfw", "xxx", "hentai", "rule34", "onlyfans")
        for rule in self.rules.apps + self.rules.sites:
            blob = " ".join([rule.id, rule.name]).lower()
            for word in banned:
                self.assertNotIn(word, blob, f"{rule.id} is named {word}")

    def test_gallery_sites_map_to_a_neutral_tag_only(self):
        """Pixiv and the booru-style sites: art_browsing, nothing more specific."""
        for rule in self.rules.sites:
            if rule.id == "art_gallery":
                self.assertEqual(rule.tags, ["art_browsing"])

    def test_a_browser_tab_naming_a_game_does_not_fire_the_game_rule(self):
        """skip_browser keeps a wiki page from claiming the game is running."""
        fg = {"exe": "chrome.exe", "title": "Blue Archive Wiki - Google Chrome",
              "hwnd": 1}
        self.assertIsNone(self.rules.match_app(fg))

    def test_the_game_itself_still_fires(self):
        fg = {"exe": "genshinimpact.exe", "title": "Genshin Impact", "hwnd": 1}
        self.assertEqual(self.rules.match_app(fg).id, "genshin")


if __name__ == "__main__":
    unittest.main(verbosity=2)