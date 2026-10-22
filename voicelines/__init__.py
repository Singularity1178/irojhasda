"""voicelines - downloads each student's dialogue / voice line data from the Blue Archive wiki.

On every start the app calls `start_background_sync(names)` with the student names taken from the
.glb files in model/ ("Iroha.glb" -> "Iroha", "Hina (Dress).glb" -> "Hina (Dress)"). For each one the
raw wikitext of its audio page is saved into `voicelines/data/`:

    https://bluearchive.wiki/wiki/Iroha/audio?action=raw          -> data/Iroha.wiki
    https://bluearchive.wiki/wiki/Hina_(Dress)/audio?action=raw   -> data/Hina (Dress).wiki

* A student whose file is already there (and not empty) is skipped, so after the first successful
  run nothing is downloaded again. Delete a file to fetch it afresh.
* Only the TEXT is fetched (the dialogue, the voice line names, the audio file names). No audio
  files are downloaded; the file names are in the saved text for when that is added.
* The text is stored exactly as the wiki serves it. Nothing is parsed here yet.
* Nothing in here can stop the app: it runs on a daemon thread, every failure is caught and
  printed, and a failed student is simply retried on the next start. If the network is down the
  remaining students are not tried (no point waiting out a timeout for each one).

This module stays free of Qt imports (it is plain urllib + threading).
"""
from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

WIKI_BASE = "https://bluearchive.wiki/wiki/"
DATA_DIR = Path(__file__).resolve().parent / "data"       # one <Student>.wiki file per student
FILE_SUFFIX = ".wiki"

TIMEOUT_S = 20.0            # per request
PAUSE_S = 0.5               # between two requests: be gentle with the wiki
USER_AGENT = "Mozilla/5.0 (compatible; irojhasda-desktop-pets; +https://github.com/Singularity1178/irojhasda)"


def page_title(name: str) -> str:
    """'Hina (Dress)' -> 'Hina_(Dress)': the wiki writes spaces as underscores."""
    return name.strip().replace(" ", "_")


def audio_url(name: str) -> str:
    """The raw-wikitext URL of a student's audio page. Parentheses and underscores stay as they are."""
    return f"{WIKI_BASE}{quote(page_title(name), safe='()_')}/audio?action=raw"


def data_path(name: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / f"{name.strip()}{FILE_SUFFIX}"


def is_satisfied(name: str, data_dir: Path | None = None) -> bool:
    """True when this student's data is already saved (a file that is not empty)."""
    p = data_path(name, data_dir)
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


class NoNetwork(Exception):
    """The wiki could not be reached at all (DNS / refused / timeout), so trying the rest is pointless."""


def fetch_text(url: str, opener=urllib.request.urlopen) -> str:
    """GET the url and return the body as text. Raises urllib.error.HTTPError for a bad status
    (404 = no such page), NoNetwork when the host cannot be reached, ValueError for a reply that
    is not wikitext (an HTML challenge / error page, or an empty body)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"})
    try:
        with opener(req, timeout=TIMEOUT_S) as resp:
            body = resp.read()
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise NoNetwork(str(getattr(e, "reason", e))) from e
    text = body.decode("utf-8", errors="replace").lstrip("\ufeff")
    if not text.strip():
        raise ValueError("empty reply")
    # ?action=raw returns wikitext. A bot-check or error page comes back as HTML instead:
    # never save that as if it were the data (it would then count as 'already downloaded').
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        raise ValueError("got an HTML page instead of wikitext (blocked or an error page)")
    return text


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + rename so an interrupted run never leaves a half file that would
    later count as 'already downloaded'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def sync(names, data_dir: Path | None = None, fetch=fetch_text, pause: float = PAUSE_S, log=print) -> dict:
    """Download the audio page of every student in `names` that is not saved yet.

    Returns {"downloaded": [...], "skipped": [...], "failed": {name: reason}}. Never raises.
    """
    result = {"downloaded": [], "skipped": [], "failed": {}}
    seen = set()
    todo = []
    for raw in names:
        name = str(raw).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        if is_satisfied(name, data_dir):
            result["skipped"].append(name)
        else:
            todo.append(name)

    for i, name in enumerate(todo):
        url = audio_url(name)
        try:
            text = fetch(url)
            _write_atomic(data_path(name, data_dir), text)
            result["downloaded"].append(name)
            log(f"[voicelines] {name}: saved ({len(text):,} chars)")
        except NoNetwork as e:
            for rest in todo[i:]:
                result["failed"][rest] = f"no network: {e}"
            log(f"[voicelines] wiki not reachable ({e}); will try again next start")
            break
        except urllib.error.HTTPError as e:
            result["failed"][name] = f"HTTP {e.code}"
            log(f"[voicelines] {name}: HTTP {e.code} for {url}")
        except Exception as e:                     # a bad reply or a disk error: this student only
            result["failed"][name] = f"{type(e).__name__}: {e}"
            log(f"[voicelines] {name}: {type(e).__name__}: {e}")
        if pause and i < len(todo) - 1:
            time.sleep(pause)

    if todo or result["skipped"]:
        log(f"[voicelines] {len(result['downloaded'])} downloaded, {len(result['skipped'])} already saved, "
            f"{len(result['failed'])} failed")
    return result


def start_background_sync(names, **kw) -> threading.Thread:
    """Run sync(names) on a daemon thread so start-up (and the Now Loading bar) never waits on the network."""
    names = list(names)

    def run():
        try:
            sync(names, **kw)
        except Exception as e:                     # pragma: no cover - sync() already catches everything
            print(f"[voicelines] sync crashed: {type(e).__name__}: {e}")

    t = threading.Thread(target=run, name="voicelines-sync", daemon=True)
    t.start()
    return t
