#!/usr/bin/env python3
"""Headless tests for voicelines: URLs, skip-if-saved, bad replies, offline. No network, no Qt.

Plain `python test_voicelines.py`.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import voicelines as vl      # noqa: E402

URL = "https://bluearchive.wiki/wiki/Iroha/audio?action=raw"
WIKITEXT = "{{AudioTable|...}}\n== Lobby ==\nHello, Sensei.\n"


class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def quiet(*_a, **_k):
    pass


class TestUrls(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(vl.audio_url("Iroha"), "https://bluearchive.wiki/wiki/Iroha/audio?action=raw")

    def test_name_with_parentheses(self):
        self.assertEqual(vl.audio_url("Hina (Dress)"),
                         "https://bluearchive.wiki/wiki/Hina_(Dress)/audio?action=raw")

    def test_every_model_in_the_folder_gets_a_url(self):
        names = [p.stem for p in sorted(Path(HERE, "model").glob("*.glb"))]
        self.assertTrue(names)
        for n in names:
            u = vl.audio_url(n)
            self.assertTrue(u.endswith("/audio?action=raw") and " " not in u, u)


class TestSync(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "data"          # does not exist yet: sync creates it
    def tearDown(self):
        self._tmp.cleanup()

    def run_sync(self, names, fetch):
        return vl.sync(names, data_dir=self.dir, fetch=fetch, pause=0, log=quiet)

    def test_downloads_and_saves_raw_text(self):
        urls = []
        def fetch(u): urls.append(u); return WIKITEXT
        r = self.run_sync(["Iroha", "Hina (Dress)"], fetch)
        self.assertEqual(r["downloaded"], ["Iroha", "Hina (Dress)"])
        self.assertEqual((self.dir / "Iroha.wiki").read_text(encoding="utf-8"), WIKITEXT)
        self.assertTrue((self.dir / "Hina (Dress).wiki").is_file())
        self.assertEqual(urls[1], "https://bluearchive.wiki/wiki/Hina_(Dress)/audio?action=raw")
        self.assertEqual(list(self.dir.glob("*.part")), [])

    def test_second_run_skips_everything(self):
        self.run_sync(["Iroha", "Ako"], lambda u: WIKITEXT)
        def boom(u): raise AssertionError("must not download again")
        r = self.run_sync(["Iroha", "Ako"], boom)
        self.assertEqual(r["downloaded"], [])
        self.assertEqual(r["skipped"], ["Iroha", "Ako"])

    def test_only_missing_students_are_fetched(self):
        self.run_sync(["Iroha"], lambda u: WIKITEXT)
        got = []
        def fetch(u): got.append(u); return WIKITEXT
        r = self.run_sync(["Iroha", "Ako"], fetch)
        self.assertEqual(r["skipped"], ["Iroha"])
        self.assertEqual(r["downloaded"], ["Ako"])
        self.assertEqual(len(got), 1)

    def test_empty_file_is_not_satisfied(self):
        self.dir.mkdir(parents=True)
        (self.dir / "Iroha.wiki").write_text("", encoding="utf-8")
        r = self.run_sync(["Iroha"], lambda u: WIKITEXT)
        self.assertEqual(r["downloaded"], ["Iroha"])

    def test_http_404_fails_that_student_only_and_saves_nothing(self):
        def fetch(u):
            if "Ako" in u:
                raise urllib.error.HTTPError(u, 404, "Not Found", {}, None)
            return WIKITEXT
        r = self.run_sync(["Ako", "Iroha"], fetch)
        self.assertEqual(r["failed"], {"Ako": "HTTP 404"})
        self.assertEqual(r["downloaded"], ["Iroha"])
        self.assertFalse((self.dir / "Ako.wiki").exists())

    def test_no_network_stops_the_rest(self):
        calls = []
        def fetch(u): calls.append(u); raise vl.NoNetwork("dns")
        r = self.run_sync(["A", "B", "C"], fetch)
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(r["failed"]), {"A", "B", "C"})

    def test_duplicates_and_blanks_ignored(self):
        calls = []
        def fetch(u): calls.append(u); return WIKITEXT
        self.run_sync(["Iroha", "iroha", " ", ""], fetch)
        self.assertEqual(len(calls), 1)


class TestFetchText(unittest.TestCase):
    def opener(self, body: bytes):
        return lambda req, timeout=None: FakeResp(body)

    def test_returns_text(self):
        self.assertEqual(vl.fetch_text(URL, self.opener(WIKITEXT.encode())), WIKITEXT)

    def test_html_challenge_page_is_rejected(self):
        for body in (b"<!DOCTYPE html><html>Just a moment...</html>", b"  <html><body>403</body></html>"):
            with self.assertRaises(ValueError):
                vl.fetch_text(URL, self.opener(body))

    def test_empty_body_is_rejected(self):
        with self.assertRaises(ValueError):
            vl.fetch_text(URL, self.opener(b"  \n"))

    def test_unreachable_host_is_no_network(self):
        def opener(req, timeout=None): raise urllib.error.URLError("Name or service not known")
        with self.assertRaises(vl.NoNetwork):
            vl.fetch_text(URL, opener)

    def test_http_error_passes_through(self):
        def opener(req, timeout=None): raise urllib.error.HTTPError(URL, 403, "Forbidden", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            vl.fetch_text(URL, opener)


class TestBackground(unittest.TestCase):
    def test_runs_on_a_daemon_thread_and_finishes(self):
        with tempfile.TemporaryDirectory() as d:
            t = vl.start_background_sync(["Iroha"], data_dir=Path(d), fetch=lambda u: WIKITEXT, pause=0, log=quiet)
            self.assertTrue(t.daemon)
            t.join(5)
            self.assertFalse(t.is_alive())
            self.assertTrue((Path(d) / "Iroha.wiki").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
