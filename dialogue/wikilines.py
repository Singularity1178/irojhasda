"""Reads a student's own voice lines out of voicelines/data/<Student>.wiki.

Those files are the raw wikitext of the wiki's ``<Student>/audio`` page, downloaded by the
``voicelines`` package. Every table row is one voice line::

    | Gachaget
    | [[File:Iroha_Gachaget.ogg]]
    | (Japanese text)
    | (English text)

A long line is split into several parts with ``<p>...</p>`` paragraphs. The parts are kept apart
and handed on joined by ``PART_SEP``; the pet shows them one after another with a pause.

Which wiki line answers which event (``EVENT_KEYS``):

    tactical_first   Gachaget        she has just spawned in
    idle             Cafe_monolog_N  standing around
    poke / petting   Lobby_N         she was tapped

Anything this module cannot supply - no file, an unreadable file, no such row - returns None, and the
caller falls back to the generic lines in dialogue/data. No Qt, no network, never raises.
"""
from __future__ import annotations

import html
import re
import time
from pathlib import Path

#: joins the parts of one line; Pet.say splits on it and waits between the parts
PART_SEP = "<p>"

#: engine event -> wiki row key (the Name column, minus the trailing ``_<n>`` variant number)
EVENT_KEYS = {
    "tactical_first": "Gachaget",
    "idle": "Cafe_monolog",
    "poke": "Lobby",
    "petting": "Lobby",
}

FILE_SUFFIX = ".wiki"
DATA_DIR = Path(__file__).resolve().parent.parent / "voicelines" / "data"

#: how long a missing / unusable file is believed before the folder is looked at again (the wiki
#: files are downloaded in the background, so one can show up while the app is running)
RECHECK_S = 30.0

_SPLIT = re.compile(r"<\s*/?\s*p\b[^>]*>", re.I)       # paragraph = one part
_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.I)          # a soft line break inside a part: just a space
_TAG = re.compile(r"<[^>]+>")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_ATTRS = re.compile(r"^\s*(?:[\w-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s|]+)\s*)+\|(?!\|)")
_NAME = re.compile(r"^[A-Za-z0-9_()\-]+$")


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _strip_attrs(cell):
    """``style="x" | text`` -> ``text`` (a table cell with formatting attributes)."""
    return _ATTRS.sub("", cell, count=1)


def clean_parts(cell):
    """One table cell -> its readable parts, split on <p>. A <br> inside a part becomes a space.
    Wiki markup is removed."""
    out = []
    for piece in _SPLIT.split(_BREAK.sub(" ", cell or "")):
        for _ in range(3):                                   # nested templates
            piece = _TEMPLATE.sub("", piece)
        piece = _LINK.sub(r"\1", piece)
        piece = _TAG.sub("", piece)
        piece = html.unescape(piece).replace("\xa0", " ")
        piece = piece.replace("'''", "").replace("''", "")
        piece = re.sub(r"\s+", " ", piece).strip()
        if piece:
            out.append(piece)
    return out


def _rows(text):
    """Yield each table row as a list of raw cell strings."""
    cells = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.lstrip()
        if s.startswith(("{|", "|}", "|+")):
            if cells:
                yield cells
            cells = None
            continue
        if s.startswith("|-"):
            if cells:
                yield cells
            cells = []
            continue
        if s.startswith("!"):                                # header row
            cells = None
            continue
        if s.startswith("|"):
            if cells is None:
                cells = []
            for part in s[1:].split("||"):
                cells.append(part)
            continue
        if cells:                                            # continuation of the last cell
            cells[-1] += "\n" + line
    if cells:
        yield cells


def parse(text):
    """Wikitext -> {lowercase row name: [line, ...]} where a line is a list of parts.

    The first cell of a row is its name; the English text is the last cell. Rows that link no
    text are skipped.
    """
    book = {}
    for cells in _rows(text or ""):
        cells = [_strip_attrs(c) for c in cells]
        if len(cells) < 3:
            continue
        name = re.sub(r"\s+", " ", _TAG.sub("", cells[0])).strip().replace(" ", "_")
        if not name or not _NAME.match(name) or name.lower() == "name":
            continue
        parts = clean_parts(cells[-1])
        if parts:
            book.setdefault(name.lower(), []).append(parts)
    return book


def pool(book, key):
    """Every line for a row key: ``Lobby`` collects Lobby, Lobby_1, Lobby_2 ... (never
    MemorialLobby_1 or EventLobby_1). Each entry is its parts joined with PART_SEP."""
    pat = re.compile(r"^" + re.escape(key.lower()) + r"(?:_\d+)?$")
    out = []
    for name, lines in (book or {}).items():
        if pat.match(name):
            out.extend(PART_SEP.join(parts) for parts in lines)
    return out


class WikiLines:
    """Loads and caches each student's wiki file. ``lines(name, event)`` is the only call needed."""

    def __init__(self, folder=None, recheck=RECHECK_S, clock=time.monotonic):
        self.folder = Path(folder) if folder else DATA_DIR
        self.recheck = float(recheck)
        self.clock = clock
        self._books = {}          # normalized name -> (file signature, book, checked_at)

    def _find(self, name):
        exact = self.folder / f"{str(name).strip()}{FILE_SUFFIX}"
        try:
            if exact.is_file():
                return exact
            want = _norm(name)
            for f in self.folder.glob("*" + FILE_SUFFIX):
                if _norm(f.stem) == want:
                    return f
        except OSError:
            pass
        return None

    def book(self, name):
        """That student's parsed lines, or {} when there is no usable file (cached, rechecked
        now and then so a file that arrives later is picked up)."""
        key = _norm(name)
        now = self.clock()
        cached = self._books.get(key)
        if cached is not None:
            sig, book, at = cached
            if book or now - at < self.recheck:
                return book
        path = self._find(name)
        sig, book = None, {}
        if path is not None:
            try:
                st = path.stat()
                sig = (st.st_mtime_ns, st.st_size)
                if cached is not None and cached[0] == sig:
                    book = cached[1]
                else:
                    book = parse(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                book = {}
        self._books[key] = (sig, book, now)
        return book

    def lines(self, name, event):
        """Her wiki lines for `event`, or [] (no mapping, no file, or no such row)."""
        key = EVENT_KEYS.get(event)
        if key is None:
            return []
        try:
            return pool(self.book(name), key)
        except Exception:
            return []
