"""Tests for line lookup: the chain, the fall-through, overrides and reactions.

Runs against the real data files plus temporary folders, so what is checked
here is what the pets actually say. No PySide, no Pet, no real machine.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dialogue import DialogueEngine, StateReactor, as_lines, fill, load_json  # noqa: E402
from dialogue.engine import read_json                                       # noqa: E402


DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data")


class FakePet:
    """The smallest thing a pet has to be for the reactor to talk to it."""

    def __init__(self, name, speech_ok=True):
        self.name = name
        self.said = []
        self._ok = speech_ok

    def speech_ok(self):
        return self._ok

    def say(self, text, dur=None):
        self.said.append(text)


class FakeWatcher:
    """Just the edges the reactor drains."""

    def __init__(self, edges=None):
        self.edges = list(edges or [])
        self.tags = []
        self.context = {}

    def drain_edges(self):
        e, self.edges = self.edges, []
        return e


def temp_data(states=None, characters=None, archetypes=None, default=None):
    """A throwaway copy of data/ with the given files overridden."""
    root = tempfile.mkdtemp(prefix="dialogue_data_")
    os.makedirs(os.path.join(root, "characters"), exist_ok=True)
    os.makedirs(os.path.join(root, "archetypes"), exist_ok=True)
    if default is None:
        default = read_json(os.path.join(DATA, "default.json"))
    if states is None:
        states = read_json(os.path.join(DATA, "states.json"))
    write(os.path.join(root, "default.json"), default)
    write(os.path.join(root, "states.json"), states)
    for name, doc in (characters or {}).items():
        write(os.path.join(root, "characters", name + ".json"), doc)
    for name, doc in (archetypes or {}).items():
        write(os.path.join(root, "archetypes", name + ".json"), doc)
    return root


def write(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


# ================================================================== basics
class TestHelpers(unittest.TestCase):
    def test_as_lines_accepts_a_list_or_a_string(self):
        self.assertEqual(as_lines(["a", "b"]), ["a", "b"])
        self.assertEqual(as_lines("a"), ["a"])
        self.assertEqual(as_lines(None), [])

    def test_as_lines_flattens_turns(self):
        self.assertEqual(as_lines([["a", "warm"], "b"]), ["a", "b"])

    def test_fill_leaves_unknown_placeholders_alone(self):
        self.assertEqual(fill("hi {nope}", {"name": "x"}), "hi {nope}")

    def test_fill_tolerates_a_stray_brace(self):
        self.assertEqual(fill("a { b", {}), "a { b")

    def test_fill_skips_none(self):
        self.assertEqual(fill("{a}!", {"a": None}), "{a}!")

    def test_load_json_returns_the_default_on_a_bad_file(self):
        self.assertEqual(load_json("no/such/file.json", default={"d": 1}), {"d": 1})

    def test_read_json_returns_none_on_a_bad_file(self):
        self.assertIsNone(read_json("no/such/file.json"))

    def test_a_broken_data_file_does_not_break_the_engine(self):
        root = tempfile.mkdtemp(prefix="dialogue_broken_")
        write(os.path.join(root, "default.json"), {"reactions": {"poke": ["Hi"]}})
        with open(os.path.join(root, "states.json"), "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        engine = DialogueEngine(root=root)
        self.assertEqual(engine.get("Hoshino", "poke", []), "Hi")

    def test_a_missing_data_folder_is_survivable(self):
        engine = DialogueEngine(root=os.path.join(tempfile.gettempdir(), "nope_x"))
        self.assertIsNone(engine.get("Hoshino", "poke", []))


# ============================================================== the chain
class TestChain(unittest.TestCase):
    def build(self):
        return DialogueEngine(root=temp_data(
            states={"_priority_order": ["app_x", "battery_low"],
                    "states": {
                        "app_x": {"idle": ["default app_x idle"]},
                        "battery_low": {"idle": ["default battery_low idle"]}}},
            characters={"hoshino": {
                "states": {"battery_low": {"idle": ["hoshino battery idle"]}}}},
            archetypes={"sleepy": {
                "states": {"battery_low": {"idle": ["sleepy battery idle"]}}}}))

    def test_a_character_pool_beats_the_default(self):
        engine = self.build()
        self.assertEqual(engine.get("Hoshino", "idle", ["battery_low"]),
                         "hoshino battery idle")

    def test_the_default_is_used_when_no_character_pool_exists(self):
        engine = self.build()
        self.assertEqual(engine.get("Shiroko", "idle", ["battery_low"]),
                         "default battery_low idle")

    def test_the_most_important_tag_wins(self):
        engine = self.build()
        self.assertEqual(engine.get("Shiroko", "idle", ["app_x", "battery_low"]),
                         "default app_x idle")

    def test_the_engine_falls_through_when_the_top_tag_has_no_pool(self):
        """The whole point of a chain: a specific tag with nothing for this
        event must not silence the line entirely."""
        engine = self.build()
        line = engine.get("Shiroko", "poke", ["app_x", "battery_low"])
        self.assertIsNotNone(line)

    def test_fallthrough_reaches_the_event_pools_at_the_bottom(self):
        engine = self.build()
        line = engine.get("Shiroko", "poke", ["app_x"])
        # compared after filling, since a default line may carry {name}
        self.assertIn(fill(line, {"name": "Shiroko", "me": "Shiroko"}),
                      [fill(l, {"name": "Shiroko", "me": "Shiroko"})
                       for l in engine.reactions["poke"]])

    def test_fallthrough_survives_every_tag_having_a_pool_but_none_for_the_event(self):
        engine = DialogueEngine(root=temp_data(
            states={"_priority_order": ["a", "b"],
                    "states": {"a": {"idle": ["a idle"]}, "b": {"idle": ["b idle"]}}}))
        self.assertIsNotNone(engine.get("Shiroko", "poke", ["a", "b"]))

    def test_the_archetype_pool_is_used_when_the_character_has_none(self):
        root = temp_data(
            states={"states": {"battery_low": {"idle": ["default"]}}},
            characters={"hoshino": {"archetype": "sleepy"}},
            archetypes={"sleepy": {"states": {"battery_low": {"idle": ["sleepy"]}}}})
        engine = DialogueEngine(root=root)
        self.assertEqual(engine.get("Hoshino", "idle", ["battery_low"]), "sleepy")

    def test_the_general_star_pool_answers_any_event(self):
        engine = DialogueEngine(root=temp_data(
            states={"states": {"battery_low": {"*": ["general"],
                                               "idle": ["idle only"]}}}))
        self.assertEqual(engine.get("Shiroko", "jump", ["battery_low"]), "general")
        self.assertEqual(engine.get("Shiroko", "idle", ["battery_low"]), "idle only")

    def test_a_plain_list_answers_every_event(self):
        engine = DialogueEngine(root=temp_data(
            states={"states": {"battery_low": ["any event"]}}))
        for event in ("poke", "jump", "idle"):
            self.assertEqual(engine.get("Shiroko", event, ["battery_low"]),
                             "any event")

    def test_silence_when_nothing_is_defined(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {}}, states={"states": {}}))
        self.assertIsNone(engine.get("Hoshino", "poke", ["battery_low"]))

    def test_get_any_merges_several_events(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"poke": ["p"], "hover": ["h"]}}))
        line = engine.get_any("Shiroko", ["poke", "hover"], [])
        self.assertIn(line, ("p", "h"))

    def test_get_any_accepts_a_single_event_string(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"poke": ["p"]}}))
        self.assertEqual(engine.get_any("Shiroko", "poke", []), "p")

    def test_unknown_tags_keep_their_relative_order(self):
        engine = DialogueEngine(root=temp_data(
            states={"states": {"zzz": {"idle": ["z"]}}}))
        self.assertEqual(engine.order_states(["aaa", "zzz"]), ["aaa", "zzz"])


# ================================================================ no repeats
class TestRepeatAvoidance(unittest.TestCase):
    def test_a_line_is_not_repeated_back_to_back(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["a", "b", "c", "d"]}}))
        seen = [engine.get("Shiroko", "idle", []) for _ in range(4)]
        self.assertEqual(len(set(seen)), 4)

    def test_a_small_pool_is_used_rather_than_going_silent(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["only"]}}))
        self.assertEqual([engine.get("Shiroko", "idle", []) for _ in range(3)],
                         ["only"] * 3)

    def test_the_memory_is_per_character(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["a", "b"]}}))
        engine.get("Shiroko", "idle", [])
        line = engine.get("Ako", "idle", [])
        self.assertIsNotNone(line)

    def test_the_memory_is_per_event(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"poke": ["p"], "idle": ["i"]}}))
        engine.get("Shiroko", "idle", [])
        self.assertEqual(engine.get("Shiroko", "poke", []), "p")


# ============================================================= placeholders
class TestPlaceholders(unittest.TestCase):
    def test_name_and_pronoun_come_from_the_character_file(self):
        root = temp_data(characters={"hoshino": {"pronoun": "she",
                                                 "reactions": {"poke": ["{name}/{pronoun}"]}}})
        engine = DialogueEngine(root=root)
        self.assertEqual(engine.get("Hoshino", "poke", []), "Hoshino/she")

    def test_explicit_values_win_over_context(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"poke": ["{app}"]}}))
        engine.set_context({"app": "Genshin"})
        self.assertEqual(engine.get("S", "poke", [], app="YouTube"), "YouTube")

    def test_context_placeholders_are_filled(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["{app} / {site} / {time}"]}}))
        engine.set_context({"app": "Genshin Impact", "site": "youtube",
                             "time": "14:05"})
        self.assertEqual(engine.get("S", "idle", []), "Genshin Impact / youtube / 14:05")

    def test_battery_reads_as_a_percentage(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["{battery}"]}}))
        engine.set_context({"battery": 42})
        self.assertEqual(engine.get("S", "idle", []), "42%")

    def test_minutes_read_as_minutes(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["{focus_minutes} / {session_minutes}"]}}))
        engine.set_context({"focus_minutes": 12, "session_minutes": 200})
        self.assertEqual(engine.get("S", "idle", []), "12 minutes / 200 minutes")

    def test_an_unknown_placeholder_is_left_as_typed(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["{nope}"]}}))
        engine.set_context({"app": "x"})
        self.assertEqual(engine.get("S", "idle", []), "{nope}")

    def test_an_empty_context_value_is_skipped(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"idle": ["a{app}b"]}}))
        engine.set_context({"app": ""})
        self.assertEqual(engine.get("S", "idle", []), "a{app}b")

    def test_set_context_never_raises_on_junk(self):
        engine = DialogueEngine(root=temp_data())
        self.assertEqual(engine.set_context({"battery": "n/a",
                                             "focus_minutes": None,
                                             "x": 1})["battery"], "n/a")

    def test_the_name_is_never_left_blank(self):
        engine = DialogueEngine(root=temp_data(
            default={"reactions": {"poke": ["{me}"]}}))
        self.assertEqual(engine.get("Ako", "poke", []), "Ako")

    def test_context_can_be_cleared(self):
        engine = DialogueEngine(root=temp_data())
        engine.set_context({"app": "x"})
        engine.set_context({})
        self.assertEqual(engine.context(), {})


# ================================================================ reactions
class TestReactions(unittest.TestCase):
    def build(self, states=None, characters=None):
        root = temp_data(
            states=states or {"_priority_order": ["app_genshin"],
                             "states": {"app_genshin": {"state_enter": ["Oh, Genshin again?"]}}},
            characters=characters)
        engine = DialogueEngine(root=root)
        watcher = FakeWatcher()
        pets = [FakePet("Hoshino"), FakePet("Ako")]
        reactor = StateReactor(engine, watcher, pets, clock=lambda: 1000.0)
        return engine, watcher, pets, reactor

    def test_an_enter_edge_speaks(self):
        engine, watcher, pets, reactor = self.build()
        watcher.edges = [("+", "app_genshin")]
        said = reactor.poll()
        self.assertIsNotNone(said)
        self.assertEqual(said[0], "app_genshin")
        self.assertEqual(said[1], "state_enter")

    def test_only_one_pet_speaks(self):
        engine, watcher, pets, reactor = self.build()
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        speakers = [p for p in pets if p.said]
        self.assertEqual(len(speakers), 1)
        self.assertEqual(speakers[0].said[0], "Oh, Genshin again?")

    def test_the_same_tag_does_not_repeat_within_the_cooldown(self):
        engine, watcher, pets, reactor = self.build()
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        first = [p.said[0] for p in pets if p.said][0]
        watcher.edges = [("-", "app_genshin"), ("+", "app_genshin")]
        self.assertIsNone(reactor.poll())
        self.assertEqual(sum(len(p.said) for p in pets), 1)
        self.assertIn(first, [l for p in pets for l in p.said])

    def test_the_cooldown_expires(self):
        now = [1000.0]
        engine, watcher, pets, reactor = self.build()
        reactor.clock = lambda: now[0]
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        now[0] += 1200.0
        watcher.edges = [("-", "app_genshin"), ("+", "app_genshin")]
        self.assertIsNotNone(reactor.poll())

    def test_a_per_tag_cooldown_is_honoured(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["hi"],
                                               "_reaction_cooldown": 60.0}}})
        self.assertEqual(reactor.cooldown_for("app_genshin"), 60.0)

    def test_a_nonsense_cooldown_falls_back_to_the_default(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["hi"],
                                               "_reaction_cooldown": "soon"}}})
        self.assertEqual(reactor.cooldown_for("app_genshin"),
                         reactor.tag_cooldown)

    def test_the_cooldown_key_is_never_spoken(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["hi"],
                                               "_reaction_cooldown": 60.0}}})
        watcher.edges = [("+", "app_genshin")]
        self.assertEqual(reactor.poll()[2], "hi")

    def test_an_exit_edge_asks_for_state_exit(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin"],
                    "states": {"app_genshin": {"state_exit": ["Leaving Genshin?"]}}})
        watcher.edges = [("-", "app_genshin")]
        said = reactor.poll()
        self.assertEqual(said[1], "state_exit")
        self.assertEqual(said[2], "Leaving Genshin?")

    def test_enter_beats_exit_when_both_arrive(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["in"],
                                               "state_exit": ["out"]}}})
        watcher.edges = [("-", "app_genshin"), ("+", "app_genshin")]
        self.assertEqual(reactor.poll()[2], "in")

    def test_no_edges_means_silence(self):
        engine, watcher, pets, reactor = self.build()
        self.assertIsNone(reactor.poll())
        self.assertEqual(sum(len(p.said) for p in pets), 0)

    def test_a_tag_with_no_pool_is_skipped_for_the_next_edge(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["battery_low", "app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["genshin"]},
                               "battery_low": {"idle": ["low"]}}})
        watcher.edges = [("+", "battery_low"), ("+", "app_genshin")]
        self.assertEqual(reactor.poll()[0], "app_genshin")

    def test_edges_are_consumed_even_when_nothing_is_said(self):
        engine, watcher, pets, reactor = self.build()
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        self.assertEqual(watcher.edges, [])

    def test_the_most_important_edge_wins(self):
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["battery_low", "app_genshin"],
                    "states": {"app_genshin": {"state_enter": ["genshin"]},
                               "battery_low": {"state_enter": ["low"]}}})
        watcher.edges = [("+", "app_genshin"), ("+", "battery_low")]
        self.assertEqual(reactor.poll()[0], "battery_low")

    def test_a_tag_on_cooldown_does_not_block_the_next_edge(self):
        """A cooled-down tag must be skipped, not swallow the whole poll."""
        now = [1000.0]
        engine, watcher, pets, reactor = self.build(
            states={"_priority_order": ["app_genshin", "battery_low"],
                    "states": {"app_genshin": {"state_enter": ["genshin"]},
                               "battery_low": {"state_enter": ["low"]}}})
        reactor.clock = lambda: now[0]
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        self.assertEqual(reactor._tag_at.get("app_genshin"), 1000.0)

        now[0] += 10.0
        watcher.edges = [("+", "app_genshin"), ("+", "battery_low")]
        self.assertEqual(reactor.poll()[0], "battery_low")

    def test_a_muted_pet_is_not_chosen(self):
        engine, watcher, pets, reactor = self.build()
        pets[0]._ok = False
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        self.assertEqual(pets[0].said, [])
        self.assertEqual(len(pets[1].said), 1)

    def test_no_eligible_pet_means_no_line(self):
        engine, watcher, pets, reactor = self.build()
        for pet in pets:
            pet._ok = False
        watcher.edges = [("+", "app_genshin")]
        self.assertIsNone(reactor.poll())

    def test_the_pet_cooldown_spreads_speakers(self):
        """With several pets, one pet speaking must not make it always her."""
        now = [1000.0]
        engine, watcher, pets, reactor = self.build()
        reactor.clock = lambda: now[0]
        reactor.pet_cooldown = 100.0
        reactor.tag_cooldown = 0.0                 # so the tag is free each time
        speakers = set()
        for step in range(12):
            now[0] += 200.0
            watcher.edges = [("+", "app_genshin")]
            reactor.poll()
            speakers.update(p.name for p in pets if len(p.said) > 0)
        self.assertEqual(speakers, {"Hoshino", "Ako"})

    def test_a_pet_whose_say_raises_does_not_break_the_poll(self):
        class Angry(FakePet):
            def say(self, text, dur=None):
                raise RuntimeError("no")

        engine, watcher, pets, reactor = self.build()
        pets[:] = [Angry("Ako"), Angry("Hoshino")]
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()                   # must not propagate

    def test_a_failing_pet_does_not_stop_the_others(self):
        class Angry(FakePet):
            def say(self, text, dur=None):
                raise RuntimeError("no")

        engine, watcher, pets, reactor = self.build()
        good = FakePet("Hoshino")
        pets[:] = [Angry("Ako"), good]
        for _ in range(8):
            watcher.edges = [("+", "app_genshin")]
            reactor.poll()
            if good.said:
                break
            reactor._busy_until = 0.0
        self.assertTrue(good.said)

    def test_reconfigure_follows_the_pet_list(self):
        engine, watcher, pets, reactor = self.build()
        reactor.reconfigure([FakePet("Ako")])
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        self.assertEqual(len(reactor.pets), 1)

    def test_reset_clears_every_cooldown(self):
        engine, watcher, pets, reactor = self.build()
        watcher.edges = [("+", "app_genshin")]
        reactor.poll()
        reactor.reset()
        self.assertTrue(reactor.ready("app_genshin", 1000.0))


# ============================================================ real data files
class TestShippedData(unittest.TestCase):
    def setUp(self):
        self.engine = DialogueEngine()

    def test_a_youtube_idle_line_is_chosen_while_youtube_is_active(self):
        states = self.engine.state_pools["site_youtube"]
        self.assertIn("idle", states)
        line = self.engine.get("Shiroko", "idle", ["site_youtube", "browser"])
        self.assertIn(line, as_lines(states["idle"]))

    def test_a_poke_during_youtube_is_still_a_poke(self):
        """While site_youtube is active, a poke must not return an idle line.

        Both pools are compared after placeholder filling, because a default
        line may contain {name}.
        """
        line = self.engine.get("Shiroko", "poke", ["site_youtube"])
        self.assertIsNotNone(line)
        idle = {fill(l, {"name": "Shiroko", "me": "Shiroko", "other": "Shiroko"})
                for l in as_lines(self.engine.state_pools["site_youtube"]["idle"])}
        self.assertNotIn(line, idle)

    def test_blue_archive_has_enter_lines(self):
        self.assertIn("state_enter", self.engine.state_pools["app_blue_archive"])

    def test_genshin_has_enter_lines(self):
        self.assertIn("state_enter", self.engine.state_pools["app_genshin"])

    def test_the_plan_specific_tags_all_have_pools(self):
        for tag in ("app_blue_archive", "site_youtube", "app_genshin",
                    "long_session", "very_long_session", "user_back_long",
                    "battery_full", "on_battery", "watching_idle",
                    "app_switching", "meeting", "high_uptime"):
            self.assertIn(tag, self.engine.state_pools, f"no pool for {tag}")

    def test_every_state_pool_is_scoped_to_events(self):
        """A plain list would answer a poke with the idle line."""
        for tag, pool in self.engine.state_pools.items():
            self.assertNotIsInstance(pool, list, f"{tag} answers every event")

    def test_every_state_pool_is_non_empty(self):
        for tag, pool in self.engine.state_pools.items():
            self.assertTrue(as_lines(pool), f"{tag} has an empty pool")

    def test_the_sleepy_and_tsundere_archetypes_override_as_documented(self):
        for archetype in ("sleepy", "tsundere"):
            doc = read_json(os.path.join(DATA, "archetypes", archetype + ".json"))
            self.assertIsNotNone(doc, f"{archetype}.json is missing")
            for tag in ("site_youtube", "app_blue_archive"):
                self.assertIn(tag, doc["states"], f"{archetype} has no {tag}")
                self.assertIn("idle", doc["states"][tag])

    def test_a_character_file_overrides_the_default_pool(self):
        doc = read_json(os.path.join(DATA, "characters", "hoshino.json"))
        self.assertIsNotNone(doc, "characters/hoshino.json is missing")
        line = self.engine.get("Hoshino", "idle", ["site_youtube"])
        self.assertNotIn(line,
                         as_lines(self.engine.state_pools["site_youtube"]["idle"]))

    def test_the_character_override_beats_the_archetype(self):
        line = self.engine.get("Hoshino", "idle", ["app_blue_archive"])
        char = read_json(os.path.join(DATA, "characters", "hoshino.json"))
        self.assertIn(line, as_lines(char["states"]["app_blue_archive"]["idle"]))

    def test_the_templates_document_state_enter(self):
        for folder in ("characters", "archetypes"):
            with open(os.path.join(DATA, folder, "_template.json"),
                      encoding="utf-8") as fh:
                raw = fh.read()
            self.assertIn("state_enter", raw)

    def test_the_templates_document_the_new_placeholders(self):
        for folder in ("characters", "archetypes"):
            with open(os.path.join(DATA, folder, "_template.json"),
                      encoding="utf-8") as fh:
                raw = fh.read()
            self.assertIn("{app}", raw)
            self.assertIn("{battery}", raw)

    def test_template_files_are_never_loaded_as_data(self):
        self.assertNotIn("_template", self.engine.archetypes)
        self.assertEqual(self.engine.character("_template"), {})

    def test_the_rules_file_parses_and_names_its_games(self):
        doc = read_json(os.path.join(DATA, "watcher_rules.json"))
        self.assertIsNotNone(doc)
        names = [a.get("name") for a in doc["apps"]]
        for wanted in ("Blue Archive", "Genshin Impact"):
            self.assertIn(wanted, names)

    def test_no_tag_in_the_rules_file_is_missing_from_the_priority_list(self):
        from dialogue.system_watcher import BUILTIN_TAGS, load_rules
        known = set(BUILTIN_TAGS) | load_rules().all_tags()
        self.assertEqual(sorted(known - set(self.engine.state_order)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)