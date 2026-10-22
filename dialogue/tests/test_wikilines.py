"""Tests for the wiki voice lines: parsing, which event uses which row, and the generic fallback.

No PySide, no network: the .wiki files are written into a temporary folder.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dialogue import DialogueEngine, WikiLines, PART_SEP    # noqa: E402
from dialogue.wikilines import parse, pool, clean_parts     # noqa: E402

WIKI = """\
{{Something}}
=Normal lines=
{| class="wikitable"
! Name !! Audio !! Transcription / Japanese !! Transcription / English
|-
| Title
| [[File:Iroha_Title.ogg]]
| はぁ……
| *sigh*... Blue Archive!
|-
| Gachaget
| [[File:Iroha_Gachaget.ogg]]
| はあ
| <p>How did it come to this?</p><p>Well, I'll just have to deal with it.</p>
|-
| Cafe_monolog_1
| [[File:Iroha_Cafe_monolog_1.ogg]]
| 静かに
| Is there a quiet place to read?
|-
| Cafe_monolog_2
| [[File:Iroha_Cafe_monolog_2.ogg]]
| あぁ
| Ugh. What a &nbsp;nuisance...
|-
| LogIn_1
| [[File:Iroha_LogIn_1.ogg]]
| ああ
| Welcome back, Sensei.
|-
| Cafe_Act_1
| [[File:Iroha_Cafe_Act_1.ogg]]
| うん
| Sit down for a bit.
|-
| Cafe_Act_3_a
| [[File:Iroha_Cafe_Act_3_a.ogg]]
| えっ
| Is that a letter variant?
|-
| EventLogin_1
| [[File:Iroha_EventLogin_1.ogg]]
| x
| event login only
|-
| Lobby_1
| [[File:Iroha_Lobby_1.ogg]]
| ふぅ
| <p>'''Hmm'''... [[Sensei|Sensei]]?</p><p>Let's slack off.</p>
|-
| Lobby_2
| [[File:Iroha_Lobby_2.ogg]]
| 何ですか
| ...What?
|-
| MemorialLobby_1
| [[File:Iroha_MemorialLobby_1.ogg]]
| x
| memorial only
|-
| EventLobby_1
| [[File:Iroha_EventLobby_1.ogg]]
| x
| event only
|}
"""

ONE_LINE_ROWS = """\
{| class="wikitable"
|-
| Lobby_1 || [[File:A_Lobby_1.ogg]] || jp || Inline cells work too.
|-
| style="x" | Lobby_2
| [[File:A_Lobby_2.ogg]]
| jp
| style="y" | Attributes are dropped.
|}
"""


class TestParse(unittest.TestCase):
    def test_rows_become_named_lines(self):
        book = parse(WIKI)
        self.assertEqual(book["title"], [["*sigh*... Blue Archive!"]])
        self.assertEqual(book["gachaget"], [["How did it come to this?", "Well, I'll just have to deal with it."]])

    def test_markup_is_stripped(self):
        book = parse(WIKI)
        self.assertEqual(book["lobby_1"], [["Hmm... Sensei?", "Let's slack off."]])
        self.assertEqual(book["cafe_monolog_2"], [["Ugh. What a nuisance..."]])

    def test_header_row_is_not_a_line(self):
        self.assertNotIn("name", parse(WIKI))

    def test_inline_cells_and_attributes(self):
        book = parse(ONE_LINE_ROWS)
        self.assertEqual(book["lobby_1"], [["Inline cells work too."]])
        self.assertEqual(book["lobby_2"], [["Attributes are dropped."]])

    def test_garbage_gives_an_empty_book(self):
        for text in ("", "<html>nope</html>", "just some text\nno table", None):
            self.assertEqual(parse(text), {})

    def test_clean_parts_splits_on_p_only(self):
        self.assertEqual(clean_parts("<p>a</p><p>b</p>c<P>d"), ["a", "b", "c", "d"])
        self.assertEqual(clean_parts("<p>one<br>two<BR />three</p>"), ["one two three"])

    def test_pool_matches_only_its_own_key(self):
        lobby = pool(parse(WIKI), "Lobby")
        self.assertEqual(len(lobby), 2)
        self.assertNotIn("memorial only", lobby)
        self.assertNotIn("event only", lobby)
        self.assertIn("Hmm... Sensei?" + PART_SEP + "Let's slack off.", lobby)

    def test_pool_takes_letter_variants_but_not_look_alikes(self):
        book = parse(WIKI)
        act = pool(book, "Cafe_Act")
        self.assertEqual(sorted(act), ["Is that a letter variant?", "Sit down for a bit."])
        login = pool(book, "LogIn")
        self.assertEqual(login, ["Welcome back, Sensei."])      # not EventLogin_1


class Folder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text=WIKI):
        (self.dir / f"{name}.wiki").write_text(text, encoding="utf-8")


class TestWikiLines(Folder):
    def test_event_to_row_mapping(self):
        self.write("Iroha")
        w = WikiLines(self.dir)
        self.assertEqual(w.lines("Iroha", "tactical_first"),
                         ["How did it come to this?" + PART_SEP + "Well, I'll just have to deal with it."])
        self.assertEqual(len(w.lines("Iroha", "idle")), 2)
        # clicked: Cafe_monolog (2) + Cafe_Act (2) + LogIn (1)
        self.assertEqual(len(w.lines("Iroha", "poke")), 5)
        self.assertEqual(w.lines("Iroha", "poke"), w.lines("Iroha", "petting"))

    def test_clicked_never_uses_lobby(self):
        self.write("Iroha")
        lobby = set(pool(parse(WIKI), "Lobby"))
        self.assertTrue(lobby)
        w = WikiLines(self.dir)
        for event in ("poke", "petting"):
            self.assertFalse(lobby & set(w.lines("Iroha", event)))

    def test_summon_uses_gachaget(self):
        self.write("Iroha")
        w = WikiLines(self.dir)
        self.assertEqual(w.lines("Iroha", "summon"), w.lines("Iroha", "tactical_first"))
        self.assertEqual(len(w.lines("Iroha", "summon")), 1)

    def test_clicked_without_cafe_act_still_works(self):
        self.write("Iroha", "{|\n|-\n| LogIn_1\n| [[File:a.ogg]]\n| jp\n| Hi.\n|-\n"
                            "| Cafe_monolog_1\n| [[File:b.ogg]]\n| jp\n| Hm.\n|}")
        self.assertEqual(sorted(WikiLines(self.dir).lines("Iroha", "poke")), ["Hi.", "Hm."])

    def test_unmapped_event_has_no_wiki_lines(self):
        self.write("Iroha")
        self.assertEqual(WikiLines(self.dir).lines("Iroha", "drag"), [])

    def test_name_with_parentheses(self):
        self.write("Hina (Dress)")
        self.assertTrue(WikiLines(self.dir).lines("Hina (Dress)", "poke"))

    def test_no_file(self):
        self.assertEqual(WikiLines(self.dir).lines("Nobody", "poke"), [])

    def test_missing_folder(self):
        self.assertEqual(WikiLines(self.dir / "nope").lines("Iroha", "poke"), [])

    def test_unreadable_file(self):
        self.write("Iroha", "<!DOCTYPE html><html>blocked</html>")
        self.assertEqual(WikiLines(self.dir).lines("Iroha", "poke"), [])

    def test_file_without_that_row(self):
        self.write("Iroha", "{|\n|-\n| Title\n| [[File:a.ogg]]\n| jp\n| Hello\n|}")
        self.assertEqual(WikiLines(self.dir).lines("Iroha", "poke"), [])

    def test_a_file_downloaded_later_is_picked_up(self):
        now = [0.0]
        w = WikiLines(self.dir, recheck=30, clock=lambda: now[0])
        self.assertEqual(w.lines("Iroha", "poke"), [])
        self.write("Iroha")
        self.assertEqual(w.lines("Iroha", "poke"), [])      # still inside the recheck window
        now[0] = 31
        self.assertTrue(w.lines("Iroha", "poke"))


class TestEngine(Folder):
    def engine(self):
        return DialogueEngine(voicelines=self.dir)

    def test_wiki_lines_are_used_alone(self):
        self.write("Iroha")
        e = self.engine()
        book = parse(WIKI)
        wiki = set(pool(book, "Cafe_monolog")) | set(pool(book, "Cafe_Act")) | set(pool(book, "LogIn"))
        lobby = set(pool(book, "Lobby"))
        for _ in range(30):
            line = e.get("Iroha", "poke", ["battery_low"])
            self.assertIn(line, wiki)
            self.assertNotIn(line, lobby)

    def test_idle_uses_cafe_monolog_even_with_a_state_active(self):
        self.write("Iroha")
        e = self.engine()
        wiki = set(pool(parse(WIKI), "Cafe_monolog"))
        for _ in range(30):
            self.assertIn(e.get("Iroha", "idle", ["late_night", "app_genshin"]), wiki)

    def test_spawn_uses_gachaget(self):
        self.write("Iroha")
        self.assertEqual(self.engine().get("Iroha", "tactical_first"),
                         "How did it come to this?" + PART_SEP + "Well, I'll just have to deal with it.")

    def test_summon_uses_gachaget_instead_of_the_generic_line(self):
        self.write("Iroha")
        gacha = "How did it come to this?" + PART_SEP + "Well, I'll just have to deal with it."
        e = self.engine()
        for _ in range(10):
            self.assertEqual(e.get("Iroha", "summon"), gacha)

    def test_summon_is_generic_without_a_file(self):
        generic = {l.replace("{name}", "Nobody") for l in DialogueEngine(voicelines=False).reactions.get("summon") or []}
        self.assertTrue(generic)
        self.assertIn(self.engine().get("Nobody", "summon"), generic)

    def test_falls_back_to_generic_without_a_file(self):
        e = self.engine()
        generic = {l.replace("{name}", "Nobody") for l in DialogueEngine(voicelines=False).reactions.get("poke") or []}
        self.assertTrue(generic)
        self.assertIn(e.get("Nobody", "poke"), generic)

    def test_falls_back_to_generic_for_a_missing_row(self):
        self.write("Iroha", "{|\n|-\n| Title\n| [[File:a.ogg]]\n| jp\n| Hello\n|}")
        generic = {l.replace("{name}", "Iroha") for l in DialogueEngine(voicelines=False).reactions.get("poke") or []}
        self.assertTrue(generic)
        self.assertIn(self.engine().get("Iroha", "poke"), generic)

    def test_unmapped_events_stay_generic(self):
        self.write("Iroha")
        generic = DialogueEngine(voicelines=False).get("Iroha", "drag")
        if generic is not None:
            self.assertNotIn(PART_SEP, self.engine().get("Iroha", "drag") or "")

    def test_get_any_prefers_wiki_lines(self):
        self.write("Iroha")
        book = parse(WIKI)
        wiki = set(pool(book, "Cafe_monolog")) | set(pool(book, "Cafe_Act")) | set(pool(book, "LogIn"))
        for _ in range(20):
            self.assertIn(self.engine().get_any("Iroha", ["idle", "poke"]), wiki)

    def test_both_lines_of_a_pool_of_two_are_used_before_any_repeats(self):
        self.write("Iroha")
        e = self.engine()
        self.assertEqual(len({e.get("Iroha", "idle"), e.get("Iroha", "idle")}), 2)


REAL = Path(__file__).with_name("Iroha.sample.wiki")


class TestRealFile(Folder):
    """A page saved straight from the wiki (lang attributes, <p> paragraphs, header rows)."""

    def test_real_page(self):
        (self.dir / "Iroha.wiki").write_text(REAL.read_text(encoding="utf-8"), encoding="utf-8")
        w = WikiLines(self.dir)
        self.assertEqual(w.lines("Iroha", "tactical_first"),
                         ["*sigh* How did it come to this? Well, I'll just have to deal with it."])
        self.assertEqual(len(w.lines("Iroha", "idle")), 5)
        clicked = w.lines("Iroha", "poke")                  # Cafe_monolog 1-5 + LogIn 1-2 (no Cafe_Act rows)
        self.assertEqual(len(clicked), 7)
        self.assertIn("*sigh* What? Student duty?" + PART_SEP + "Okay. I'll do my best to fulfill your request.", clicked)
        self.assertNotIn("*sigh*" + PART_SEP + "Do you wanna slack off somewhere?", clicked)     # a Lobby line
        self.assertTrue(all("<" not in l.replace(PART_SEP, "") and "[[" not in l for l in clicked))


if __name__ == "__main__":
    unittest.main()
