"""Detects what the computer is doing and turns it into state tags.

Kept apart from the dialogue on purpose: this module decides *what is going
on*, engine.py decides *what to say about it*, and neither knows about the
other. Nothing here speaks - it only publishes ``tags`` (and ``context``).

Everything it knows about apps, sites and games comes from
``data/watcher_rules.json``, so adding a game never means editing Python. A
missing or broken rules file falls back to a small built-in set instead of
raising.

Polls every few seconds (not every frame) and is deliberately forgiving:
psutil is optional, the Windows-only bits are skipped elsewhere, and any one
detector failing just means one fewer tag, never a traceback.

Privacy: window titles are matched in memory and never stored, logged or
written anywhere. Idle time comes from ``GetLastInputInfo`` and nothing else -
no keystrokes, no mouse contents, no screenshots, no network lookups.

Tags produced:
    time of day   late_night early_morning morning afternoon evening night
                   weekday weekend lunch_time monday_morning friday_evening
    power         charging battery_low battery_critical battery_full on_battery
    load          cpu_high memory_high disk_low network_offline high_uptime
    session       long_session very_long_session long_focus_<category>
                   user_idle watching_idle user_back user_back_long break_taken
    window        app_<id> site_<id>, plus the category tags they carry
                   (gaming / video / coding / music / office / browser /
                    emulator / streaming / meeting / ai_chat / text_editor)
    behaviour     fullscreen app_switching multi_monitor minimized_all
    session lock  locked screen_off
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from pathlib import Path

try:                                        # optional, like the platform checks
    import psutil
except Exception:                           # pragma: no cover
    psutil = None


# =============================================================================
#  Windows bits.  Every call declares argtypes/restype so 64-bit handles and
#  structures survive the round trip, and GetTickCount64 avoids the ~49 day wrap
#  of its 32-bit little brother.
# =============================================================================
WINDOWS = sys.platform == "win32"

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _DWORD = wintypes.DWORD
    _HWND = wintypes.HWND
    _HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", _DWORD), ("dwTime", _DWORD)]

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = _HWND
    _user32.GetWindowTextLengthW.argtypes = [_HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [_HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [_HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [_HWND, ctypes.POINTER(_DWORD)]
    _user32.GetWindowThreadProcessId.restype = _DWORD
    _user32.GetWindowRect.argtypes = [_HWND, ctypes.POINTER(_RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.MonitorFromWindow.argtypes = [_HWND, _DWORD]
    _user32.MonitorFromWindow.restype = _HMONITOR
    _user32.GetMonitorInfoW.argtypes = [_HMONITOR, ctypes.POINTER(_MONITORINFO)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [_HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    _user32.GetLastInputInfo.restype = wintypes.BOOL

    _kernel32.GetTickCount64.argtypes = []
    _kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    _kernel32.OpenProcess.argtypes = [_DWORD, wintypes.BOOL, _DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, _DWORD,
                                                    wintypes.LPWSTR,
                                                    ctypes.POINTER(_DWORD)]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _MONITOR_DEFAULTTONEAREST = 0x00000002
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SM_CMONITORS = 80

    def _idle_seconds():
        """Seconds since the last keyboard / mouse input (Windows only)."""
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not _user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return (_kernel32.GetTickCount64() - info.dwTime) / 1000.0

    def _window_text(hwnd):
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _class_name(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _process_path(pid):
        """Full image path of `pid` through the Win32 API (psutil-free)."""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = _DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                       ctypes.byref(size)):
                return ""
            return buf.value
        finally:
            try:
                _kernel32.CloseHandle(handle)
            except Exception:
                pass

    def _monitor_count():
        try:
            return int(_user32.GetSystemMetrics(_SM_CMONITORS)) or None
        except Exception:
            return None

else:                                       # pragma: no cover - other platforms
    _idle_seconds = None
    _process_path = None
    _monitor_count = None


#: every key a foreground record may carry, so a caller cannot smuggle in more
_FG_KEYS = ("hwnd", "title", "pid", "exe", "path", "rect", "cls",
            "fullscreen", "iconic")


def _empty_foreground():
    """The record used wherever the real one is unavailable."""
    return {"hwnd": None, "title": "", "pid": 0, "exe": "", "path": "",
            "rect": None, "cls": "", "fullscreen": False, "iconic": False}


def _foreground():
    """What is in front right now: handle, title, owning process, rectangle.

    The only place a window title is ever read. Everything downstream compares
    it against the rules in memory and then throws it away - it is never
    stored, logged or written to disk. Only the matched rule id, its display
    name and its tags are allowed to leave this function.
    """
    info = _empty_foreground()
    if not WINDOWS:
        return info
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return info
        info["hwnd"] = hwnd
        info["title"] = _window_text(hwnd)
        info["cls"] = _class_name(hwnd)
        pid = _DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info["pid"] = int(pid.value)
        rect = _RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            info["rect"] = (rect.left, rect.top, rect.right, rect.bottom)
        info["iconic"] = bool(_user32.IsIconic(hwnd))
    except Exception:
        return _empty_foreground()
    return info


# =============================================================================
#  Rules: which exe / window title means which tags.  Loaded from JSON so that
#  adding an app is a data edit.  A broken file falls back to RULES_FALLBACK.
# =============================================================================
RULES_FALLBACK = {
    "apps": [
        {"id": "blue_archive", "name": "Blue Archive",
         "exe": ["bluearchive.exe"],
         "emulator_title_regex": ["blue ?archive", "ブルーアーカイブ", "블루 ?아카이브"],
         "tags": ["app_blue_archive", "gaming"]},
        {"id": "genshin", "name": "Genshin Impact",
         "exe": ["genshinimpact.exe", "yuanshen.exe"],
         "tags": ["app_genshin", "gaming"]},
    ],
    "sites": [
        {"id": "youtube", "name": "YouTube",
         "title_regex": [r"\byoutube\b"], "tags": ["site_youtube", "video"]},
    ],
    "browsers": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                 "opera.exe", "vivaldi.exe", "arc.exe"],
    "emulators": [],
    "fullscreen_ignore_exe": ["explorer.exe", "searchhost.exe",
                              "shellexperiencehost.exe", "lockapp.exe"],
}

DEFAULT_BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
                    "opera.exe", "vivaldi.exe", "arc.exe")
DEFAULT_EMULATORS = ("hd-player.exe", "dnplayer.exe", "mumuplayer.exe",
                     "nemuplayer.exe", "nox.exe", "memu.exe",
                     "googleplaygames.exe")


def _compile(patterns):
    """Compile a list of regex sources, skipping any that do not compile."""
    out = []
    for src in patterns or ():
        if not isinstance(src, str) or not src:
            continue
        try:
            out.append(re.compile(src, re.IGNORECASE | re.UNICODE))
        except re.error:
            continue
    return out


def _names(values):
    """A set of lowercased exe basenames, ignoring anything else."""
    out = set()
    for value in values or ():
        if isinstance(value, str) and value.strip():
            out.add(os.path.basename(value.strip().lower()))
    return {v for v in out if v}


class Rule:
    """One app or site: what to match on, and which tags a match adds.

    A rule matches when ANY listed ``exe`` matches OR ``title_regex`` matches,
    subject to ``exclude_exe`` / ``exclude_title_regex``. Two flags refine
    that: ``require_title_regex`` turns it into "exe AND title_regex", which
    generic hosts such as ``javaw.exe`` or ``Client-Win64-Shipping.exe`` need so
    they do not claim every Java or Unreal game on the machine; ``skip_browser``
    keeps a title rule from firing on a browser tab that merely mentions the
    game.
    """

    __slots__ = ("id", "name", "exe", "title_regex", "emulator_title_regex",
                 "exclude_exe", "exclude_title_regex", "require_title_regex",
                 "skip_browser", "browser_only", "tags")

    def __init__(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        self.id = str(raw.get("id") or "")
        self.name = str(raw.get("name") or self.id)
        self.exe = _names(raw.get("exe"))
        self.title_regex = _compile(raw.get("title_regex"))
        self.emulator_title_regex = _compile(raw.get("emulator_title_regex"))
        self.exclude_exe = _names(raw.get("exclude_exe"))
        self.exclude_title_regex = _compile(raw.get("exclude_title_regex"))
        self.require_title_regex = bool(raw.get("require_title_regex"))
        self.skip_browser = bool(raw.get("skip_browser"))
        self.browser_only = bool(raw.get("browser_only", True))
        self.tags = [t for t in (raw.get("tags") or ()) if isinstance(t, str)]

    def excluded(self, exe, title):
        if exe and exe in self.exclude_exe:
            return True
        return any(rx.search(title) for rx in self.exclude_title_regex)

    def matches(self, exe, title, is_browser=False):
        if self.skip_browser and is_browser:
            return False
        if self.excluded(exe, title):
            return False
        by_exe = bool(exe) and exe in self.exe
        by_title = any(rx.search(title) for rx in self.title_regex)
        if self.require_title_regex:
            return by_exe and by_title
        return by_exe or by_title

    def matches_emulator(self, exe, title):
        """Only reachable from a known emulator; promotes it to a real game."""
        if self.excluded(exe, title):
            return False
        return any(rx.search(title) for rx in self.emulator_title_regex)

    def __repr__(self):                          # pragma: no cover - debug aid
        return f"<Rule {self.id or self.name} {sorted(self.tags)}>"


class Rules:
    """The whole rules document, validated once at startup."""

    def __init__(self, doc=None):
        doc = doc if isinstance(doc, dict) else {}
        apps = [r for r in (doc.get("apps") or ()) if isinstance(r, dict)]
        apps += [r for r in (doc.get("custom_apps") or ()) if isinstance(r, dict)]
        self.apps = [Rule(r) for r in apps]
        self.sites = [Rule(r) for r in (doc.get("sites") or ()) if isinstance(r, dict)]
        self.browsers = _names(doc.get("browsers")) or set(DEFAULT_BROWSERS)
        self.emulators = _names(doc.get("emulators")) or set(DEFAULT_EMULATORS)
        self.fullscreen_ignore = _names(doc.get("fullscreen_ignore_exe")) or {
            "explorer.exe", "searchhost.exe", "shellexperiencehost.exe", "lockapp.exe"}
        self.thresholds = dict(doc.get("thresholds") or {})
        self.disabled_tags = [str(t) for t in (doc.get("disabled_tags") or ())
                              if isinstance(t, str) and t]
        self.enabled_categories = [str(t) for t in (doc.get("enabled_categories") or ())
                                  if isinstance(t, str) and t]
        self.notes = [str(v) for k, v in doc.items() if str(k).startswith("_")]

    # -------------------------------------------------------------- matching
    def match_app(self, fg):
        """First matching apps rule wins, so order the file most-specific first."""
        exe, title = fg.get("exe") or "", fg.get("title") or ""
        is_browser = exe in self.browsers
        for rule in self.apps:
            if rule.matches(exe, title, is_browser):
                return rule
        return None

    def match_emulator(self, fg):
        """Promote 'some emulator' to the game its window title names."""
        exe, title = fg.get("exe") or "", fg.get("title") or ""
        if exe not in self.emulators:
            return None
        for rule in self.apps:
            if rule.emulator_title_regex and rule.matches_emulator(exe, title):
                return rule
        return None

    def match_site(self, fg):
        exe, title = fg.get("exe") or "", fg.get("title") or ""
        is_browser = exe in self.browsers
        for rule in self.sites:
            if rule.browser_only and not is_browser:
                continue
            if rule.matches(exe, title):
                return rule
        return None

    # --------------------------------------------------------------- privacy
    def allows(self, tag):
        """False when the user switched this tag, or a whole class, off."""
        for pattern in self.disabled_tags:
            if pattern.endswith("*"):
                if tag.startswith(pattern[:-1]):
                    return False
            elif pattern == tag:
                return False
        if self.enabled_categories:
            return any(tag.startswith(p) for p in self.enabled_categories)
        return True

    def all_tags(self):
        out = set()
        for rule in self.apps + self.sites:
            out.update(rule.tags)
        return out


def load_rules(path=None):
    """Read ``data/watcher_rules.json``. Never raises, never returns None."""
    path = (Path(path) if path else
            Path(__file__).resolve().parent / "data" / "watcher_rules.json")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("watcher_rules.json must hold a JSON object")
        return Rules(doc)
    except Exception:
        return Rules(RULES_FALLBACK)


# =============================================================================
#  Probes: every question about the machine, asked in one place.
#
#  ``SystemWatcher(probes=...)`` takes a stand-in with the same method names, so
#  a whole fake sample sequence can be built on any machine - or on none.
# =============================================================================
class Probes:
    """The real thing: psutil where it exists, cheap shutil/Win32 fallbacks."""

    def battery(self):
        """{'percent': int, 'plugged': bool}, or None when there is no battery."""
        if psutil is None:
            return None
        try:
            b = psutil.sensors_battery()
        except Exception:
            return None
        if b is None:
            return None
        try:
            return {"percent": float(b.percent), "plugged": bool(b.power_plugged)}
        except Exception:
            return None

    def cpu_percent(self):
        """Percent since the previous call - prime it once before trusting it."""
        if psutil is None:
            return None
        try:
            return float(psutil.cpu_percent(interval=None))
        except Exception:
            return None

    def memory_percent(self):
        if psutil is None:
            return None
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            return None

    def disk_free_percent(self):
        """Free space on the system drive as a percentage of its size."""
        try:
            drive = (os.environ.get("SystemDrive") or "C:").rstrip("\\/")
            usage = shutil.disk_usage(drive + os.sep)
            return (100.0 * usage.free / usage.total) if usage.total else None
        except Exception:
            return None

    def network_up(self):
        """True when some non-loopback interface is up."""
        if psutil is None:
            return None
        try:
            return any(s.isup for name, s in psutil.net_if_stats().items()
                       if name != "lo")
        except Exception:
            return None

    def boot_time(self):
        if psutil is None:
            return None
        try:
            return float(psutil.boot_time())
        except Exception:
            return None

    def monitor_count(self):
        return _monitor_count() if _monitor_count else None


# =============================================================================
#  The watcher
# =============================================================================
#: every tag this module can emit, so the startup check can spot one the
#: priority list has never heard of
BUILTIN_TAGS = (
    "late_night", "early_morning", "morning", "afternoon", "evening", "night",
    "lunch_time", "weekday", "weekend", "monday_morning", "friday_evening",
    "charging", "battery_low", "battery_critical", "battery_full", "on_battery",
    "cpu_high", "memory_high", "disk_low", "network_offline", "high_uptime",
    "long_session", "very_long_session",
    "long_focus_coding", "long_focus_gaming", "long_focus_video",
    "long_focus_office", "long_focus_browser",
    "user_idle", "watching_idle", "user_back", "user_back_long", "break_taken",
    "fullscreen", "app_switching", "multi_monitor", "minimized_all",
    "locked", "screen_off",
    "browser", "emulator", "coding", "gaming", "video", "music", "office",
    "streaming", "meeting", "ai_chat", "text_editor", "audio_playing",
)

#: categories a long focus can be reported for
FOCUS_CATEGORIES = ("coding", "gaming", "video", "office", "browser")

#: the startup priority note is printed once per process, not per watcher
_WARNED = False

#: tags that mean "the user is watching / listening, not away"
PASSIVE_TAGS = ("audio_playing", "video", "music", "streaming")


class SystemWatcher:
    """Maintains the set of active tags. Cheap; call it as often as you like,
    it only re-checks when its own interval has elapsed.

    Every input is injectable - the foreground record, idle seconds, both
    clocks, the system probes and the rules - so a test can drive a whole
    sample sequence on a machine that has none of the real thing.
    """

    #: seconds between real checks
    interval = 3.0

    #: idle seconds that count as 'user_idle' / came back as 'user_back'
    idle_after = 90.0
    #: an absence of this long is a break rather than a blink
    break_after = 600.0
    #: ...and of this long is a proper 'user_back_long'
    back_long_after = 1800.0
    #: an idle gap longer than this ends the session / focus timer
    session_gap = 300.0
    focus_gap = 120.0

    #: thresholds
    battery_low = 25.0
    battery_low_clear = 28.0          # hysteresis: enter at 25, leave at 28
    battery_critical = 12.0
    battery_critical_clear = 15.0
    battery_full = 98.0
    cpu_high = 85.0
    cpu_high_clear = 70.0
    memory_high = 88.0
    memory_high_clear = 75.0
    cpu_high_samples = 3              # one spike is not a trend
    memory_high_samples = 3
    disk_low = 10.0
    high_uptime = 3 * 24 * 3600.0

    #: a tag must survive this many polls before it counts (stops edge spam)
    debounce_polls = 2
    #: ...except these, which are one-shot events by nature
    instant_tags = ("user_back", "user_back_long", "break_taken")

    #: window behaviour
    app_switch_window = 60.0
    app_switch_max = 8
    screen_off_polls = 3
    fullscreen_tolerance = 4.0

    #: slow checks, so one sample stays well under a millisecond or two
    disk_every = 60.0
    network_every = 10.0
    uptime_every = 600.0

    def __init__(self, interval=None, priority=None, rules_path=None,
                 foreground=None, idle_source=None, clock=None, wall_clock=None,
                 probes=None, rules=None, debug=False, threaded=False):
        if interval is not None:
            self.interval = interval
        self.priority = list(priority or [])    # most important tag first
        self.tags = []                          # kept in that same order
        self.edges = []                         # ('+'/'-', tag) since the last drain
        self.rules = rules if isinstance(rules, Rules) else load_rules(rules_path)
        self.probes = probes if probes is not None else Probes()
        self.debug = bool(debug)
        self._apply_thresholds()

        # ---- injectable inputs
        self._foreground_source = foreground
        self._idle_source = idle_source if idle_source is not None else _idle_seconds
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time

        # ---- state
        self._next = 0.0
        self._prev = set()
        self._on = {}                    # tag -> consecutive polls it was seen
        self._off = {}                   # tag -> consecutive polls it was absent
        self._last_idle = 0.0
        self._away_since = None          # when the current idle stretch began
        self._session_since = None
        self._focus_key = ""
        self._focus_since = None
        self._focus_category = ""
        self._switches = deque()
        self._last_app = ""
        self._exe_cache = {}             # pid -> exe, so psutil is not polled
        self._cpu_streak = 0
        self._mem_streak = 0
        self._screen_off_streak = 0
        self._disk_low = False
        self._network_offline = False
        self._high_uptime = False
        self._multi_monitor = False
        self._monitor_checked = False
        self._disk_at = None
        self._network_at = None
        self._uptime_at = None
        self.has_battery = False         # False = no psutil / no battery
        self.matched_rule = ""           # id of the rule that fired, for --debug
        self.matched_site = ""
        self.context = self._blank_context()
        self._own_exe = os.path.basename(
            sys.executable or "python.exe").lower() or "python.exe"

        self._warn_unknown_tags()
        self._prime_cpu()

        # Polling off the render thread: the pet loop calls tick() every frame,
        # and a sample that blocks would stutter the animation.
        self._lock = threading.RLock()
        self._thread = None
        if threaded:
            self._start_thread()

    # ---------------------------------------------------------------- set-up
    @staticmethod
    def _blank_context():
        """The placeholder values the engine can fill lines from."""
        return {"app": "", "exe": "", "site": "", "battery": None, "time": "",
                "focus_minutes": 0, "session_minutes": 0}

    #: thresholds the rules file is allowed to move, and the sanity bounds
    THRESHOLD_BOUNDS = {
        "idle_after": (10.0, 3600.0), "break_after": (10.0, 86400.0),
        "back_long_after": (10.0, 86400.0), "session_gap": (10.0, 86400.0),
        "focus_gap": (10.0, 86400.0), "battery_low": (1.0, 100.0),
        "battery_low_clear": (1.0, 100.0), "battery_critical": (0.0, 100.0),
        "battery_critical_clear": (0.0, 100.0), "battery_full": (0.0, 100.0),
        "cpu_high": (1.0, 100.0), "cpu_high_clear": (0.0, 100.0),
        "memory_high": (1.0, 100.0), "memory_high_clear": (0.0, 100.0),
        "cpu_high_samples": (1, 60), "memory_high_samples": (1, 60),
        "disk_low": (0.0, 100.0), "high_uptime": (0.0, 1e9),
        "debounce_polls": (1, 30), "app_switch_window": (5.0, 3600.0),
        "app_switch_max": (1, 1000), "screen_off_polls": (1, 60),
        "fullscreen_tolerance": (0.0, 200.0), "interval": (0.1, 3600.0),
        "disk_every": (1.0, 86400.0), "network_every": (1.0, 86400.0),
        "uptime_every": (1.0, 86400.0),
    }

    def _apply_thresholds(self):
        """Let ``watcher_rules.json`` move the thresholds, within sane bounds.

        Values arrive from a hand-edited file, so anything out of range, of the
        wrong type, or simply unknown is ignored rather than trusted.
        """
        source = self.rules.thresholds
        if not isinstance(source, dict):
            return
        for name, (low, high) in self.THRESHOLD_BOUNDS.items():
            value = source.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not (low <= value <= high):
                continue
            setattr(self, name, type(getattr(self, name, 0))(value))

    def _start_thread(self):
        """Run the polling on a daemon thread that sleeps between samples."""
        stop = threading.Event()
        self._stop = stop

        def loop():
            while not stop.is_set():
                try:
                    self._poll()
                except Exception:
                    pass                   # a bad sample must not kill the thread
                stop.wait(max(0.05, self.interval))

        self._thread = threading.Thread(target=loop, name="system-watcher",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        """Ask the polling thread to finish. Harmless if there is not one."""
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _own_exes(self):
        """Our own process, so the pet window is never read as fullscreen."""
        return {self._own_exe, "python.exe", "pythonw.exe"} | _names(
            self.rules.thresholds.get("self_exe"))

    def _prime_cpu(self):
        """``cpu_percent(interval=None)`` answers 0.0 on its very first call."""
        try:
            self.probes.cpu_percent()
        except Exception:
            pass

    def _warn_unknown_tags(self):
        """Once per process: tags we can emit that the priority list omits.

        ``_priority`` demotes anything it does not recognise to the bottom, so
        a typo in ``_priority_order`` silently loses a line pool. Says nothing
        per poll, and nothing at all when the list is already complete.
        """
        global _WARNED
        if _WARNED:
            return
        _WARNED = True
        if not self.priority:
            print("[dialogue] states.json has no _priority_order; "
                  "every tag ranks equal.")
            return
        missing = sorted((set(BUILTIN_TAGS) | self.rules.all_tags())
                         - set(self.priority))
        if missing:
            print("[dialogue] states.json _priority_order does not list: "
                  + ", ".join(missing))

    # ------------------------------------------------------------------ poll
    def tick(self, force=False):
        """Poll if it is due. Returns the current tags.

        With ``threaded=True`` the polling already happens on a worker thread at
        its own interval, so this only reads the latest result - the caller can
        call it every frame without ever blocking on a sample.
        """
        if self._thread is not None:
            return self.current_tags()
        return self._poll(force)

    def _poll(self, force=False):
        """One sample on the calling thread."""
        now = self._clock()
        with self._lock:
            if not force and now < self._next:
                return list(self.tags)
            self._next = now + self.interval
        return self._sample(now)

    def current_tags(self):
        """The published tags. Only ever holds the lock for a list copy."""
        with self._lock:
            return list(self.tags)

    def current_context(self):
        with self._lock:
            return dict(self.context)

    def _sample(self, now):
        """One poll, then publish.

        The detectors only touch state that belongs to whoever is sampling -
        there is just one of those, the polling thread - so nothing here needs
        the lock. Only the three published values (`tags`, `context`, `edges`)
        do, and those are swapped in at the end in one go. That is what keeps a
        slow foreground read from stalling the reader.
        """
        if self._session_since is None:
            self._session_since = now
        if self._focus_since is None:
            self._focus_since = now

        raw = set()
        for detector in (self._time_tags, self._calendar_tags, self._power_tags,
                         self._load_tags, self._slow_tags):
            try:
                raw.update(detector() or ())
            except Exception:
                pass                            # one broken detector, one fewer tag

        # Detectors that need to see the others' output (idle suppression reads
        # the app and fullscreen tags) are run after, one at a time, each fed
        # everything collected so far.
        current = set(raw)
        for detector in (self._window_tags, self._behavior_tags,
                         self._session_tags, self._idle_tags):
            try:
                got = set(detector(current) or ())
            except Exception:
                got = set()
            current.update(got)

        # The user switches a whole class off here, before anything is published.
        raw = {t for t in current if self.rules.allows(t)}

        # Debounce what actually leaves, then reconcile against what did last
        # time. `_debounce` is the only thing allowed to add or drop a tag here,
        # so the debounced set is what `tags` and `context` must be built from.
        found = self._debounce(raw)
        new_edges = [("+", tag) for tag in sorted(found - self._prev)]
        new_edges += [("-", tag) for tag in sorted(self._prev - found)]
        self._prev = found
        tags = sorted(found, key=lambda t: (self._priority(t), t))
        # The window detectors filled context from the raw tag set, which may
        # include a tag the debounce has not confirmed yet, so trim it to what
        # is actually being published.
        self._prune_context(found)
        self._refresh_context(now)

        with self._lock:
            self.tags = tags
            if new_edges:
                self.edges.extend(new_edges)
            if self.debug:
                self._print_debug()
            return list(self.tags)

    # ------------------------------------------------------------- foreground
    def _foreground_record(self):
        """The foreground window, plus the pid -> exe name the rules match on.

        A `fullscreen` flag supplied by an injected record is taken as given -
        otherwise it is computed from the rectangle against the monitor, which is
        the only honest way to tell (a maximised browser is not fullscreen).
        """
        record = _empty_foreground()
        given_fullscreen = None
        if self._foreground_source is not None:
            try:
                given = self._foreground_source() or {}
            except Exception:
                given = {}
            if isinstance(given, dict):
                given_fullscreen = given.get("fullscreen")
                record.update({k: v for k, v in given.items() if k in _FG_KEYS})
        else:
            try:
                record = _foreground()
            except Exception:
                record = _empty_foreground()
        pid = int(record.get("pid") or 0)
        exe = (record.get("exe") or "").lower()
        if pid and not exe:
            exe = self._exe_for(pid)
        record["exe"] = exe
        if given_fullscreen is not None:
            record["fullscreen"] = bool(given_fullscreen)
        elif not record.get("hwnd"):
            record["fullscreen"] = False
        else:
            record["fullscreen"] = bool(self._covers_monitor(record))
        return record

    def _exe_for(self, pid):
        """psutil by preference, cached by pid so it is not asked every poll.

        Access denied is the common case for elevated and anti-cheat protected
        processes, so every step falls back to the Win32 API and then to ''.
        """
        cached = self._exe_cache.get(pid)
        if cached:
            return cached
        name = ""
        if psutil is not None:
            try:
                name = psutil.Process(pid).name() or ""
            except Exception:
                name = ""
        if not name and _process_path is not None:
            try:
                name = os.path.basename(_process_path(pid) or "")
            except Exception:
                name = ""
        name = name.lower()
        if len(self._exe_cache) > 512:
            self._exe_cache.clear()
        self._exe_cache[pid] = name
        return name

    def _covers_monitor(self, fg):
        """Real fullscreen: the window covers its whole monitor.

        Computed from the rectangle against ``MonitorFromWindow``, so a YouTube
        tab in a maximised window is not fullscreen, and borderless-windowed
        games are caught by the same test.
        """
        rect = fg.get("rect")
        if not rect or not fg.get("hwnd") or fg.get("iconic"):
            return False
        exe = fg.get("exe") or ""
        if exe and (exe in self.rules.fullscreen_ignore or exe in self._own_exes()):
            return False
        try:
            monitor = _user32.MonitorFromWindow(fg["hwnd"], _MONITOR_DEFAULTTONEAREST)
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return False
            mon = info.rcMonitor
        except Exception:
            return False
        left, top, right, bottom = rect
        tol = float(self.rules.thresholds.get("fullscreen_tolerance",
                                              self.fullscreen_tolerance))
        return (left <= mon.left + tol and top <= mon.top + tol
                and right >= mon.right - tol and bottom >= mon.bottom - tol)

    # ---------------------------------------------------------------- shaping
    def _priority(self, tag):
        """Known tags first (the priority list lives in data/states.json)."""
        try:
            return self.priority.index(tag)
        except ValueError:
            return len(self.priority)

    def _debounce(self, raw):
        """A tag has to hold steady for a couple of polls before it counts.

        Both directions are debounced, so a tag flapping on alternate polls
        never becomes confirmed and therefore never produces an edge.
        """
        n = max(1, int(self.debounce_polls))
        out = set()
        for tag in set(raw) | set(self._prev):
            if tag in self.instant_tags:
                self._on.pop(tag, None)
                self._off.pop(tag, None)
                if tag in raw:
                    out.add(tag)
                continue
            if tag in raw:
                seen = self._on.get(tag, 0) + 1
                self._on[tag] = seen
                self._off.pop(tag, None)
                if tag in self._prev or seen >= n:
                    out.add(tag)
            else:
                gone = self._off.get(tag, 0) + 1
                self._off[tag] = gone
                self._on.pop(tag, None)
                if tag in self._prev and gone < n:
                    out.add(tag)
        for tag in list(self._on):
            if tag not in raw and tag not in self._prev:
                self._on.pop(tag, None)
        for tag in list(self._off):
            if tag not in raw and tag not in self._prev:
                self._off.pop(tag, None)
        return out

    # -------------------------------------------------------------- detectors
    def _time_tags(self):
        """morning / afternoon / evening / night / late_night, plus lunch."""
        now = time.localtime(self._wall_clock())
        hour, minute = now.tm_hour, now.tm_min
        if hour < 5:
            return {"late_night"}
        if hour < 8:
            return {"early_morning"}
        if hour < 12:
            out = {"morning"}
        elif hour < 17:
            out = {"afternoon"}
        elif hour < 22:
            out = {"evening"}
        else:
            out = {"night"}
        if hour == 12 and minute < 30:
            out.add("lunch_time")
        return out

    def _calendar_tags(self):
        """weekday / weekend, and the two named combinations."""
        now = time.localtime(self._wall_clock())
        weekday = now.tm_wday                      # 0 = Monday
        hour = now.tm_hour
        out = {"weekend" if weekday >= 5 else "weekday"}
        if weekday == 0 and 8 <= hour < 12:
            out.add("monday_morning")
        if weekday == 4 and 17 <= hour < 22:
            out.add("friday_evening")
        return out

    def _power_tags(self):
        """charging / low / critical / full / on battery, with hysteresis.

        A battery sitting right on 25% used to flicker its tag on and off every
        poll; it now has to climb back to 28% before it lets go.
        """
        try:
            b = self.probes.battery()
        except Exception:
            b = None
        if not b:
            return set()
        self.has_battery = True
        pct = float(b.get("percent"))
        plugged = bool(b.get("plugged"))
        was = self._prev
        if pct <= self.battery_critical or ("battery_critical" in was
                                            and pct < self.battery_critical_clear):
            out = {"battery_critical"}
        elif pct <= self.battery_low or ("battery_low" in was
                                         and pct < self.battery_low_clear):
            out = {"battery_low"}
        else:
            out = set()
        if plugged:
            out.add("charging")
            if pct >= self.battery_full:
                out.add("battery_full")
        else:
            out.add("on_battery")
        self.context["battery"] = int(round(pct))
        return out

    def _hysteresis(self, value, high, clear, samples, tag):
        """A load tag with a proper dead band.

        Above ``high`` for ``samples`` polls running -> the tag goes on. Below
        ``clear`` -> straight off. In between, it stays exactly as it was, so a
        reading hovering at the threshold cannot flap the tag every poll.
        """
        if value is None:
            return set()
        streak_key = "_%s_streak" % tag
        if value >= high:
            streak = getattr(self, streak_key, 0) + 1
            setattr(self, streak_key, streak)
            return {tag} if streak >= samples else set()
        setattr(self, streak_key, 0)
        if value < clear:
            return set()
        return {tag} if tag in self._prev else set()

    def _load_tags(self):
        """cpu / memory, each needing samples in a row before they count."""
        out = self._hysteresis(self.probes.cpu_percent(), self.cpu_high,
                               self.cpu_high_clear, self.cpu_high_samples,
                               "cpu_high")
        out |= self._hysteresis(self.probes.memory_percent(), self.memory_high,
                                self.memory_high_clear, self.memory_high_samples,
                                "memory_high")
        return out

    def _slow_tags(self):
        """Disk, network and uptime - far too slow to ask on every poll."""
        now = self._clock()
        out = set()
        if self._disk_at is None or now - self._disk_at >= self.disk_every:
            self._disk_at = now
            free = self.probes.disk_free_percent()
            if free is not None:
                self._disk_low = free < self.disk_low
        if self._disk_low:
            out.add("disk_low")
        if self._network_at is None or now - self._network_at >= self.network_every:
            self._network_at = now
            up = self.probes.network_up()
            if up is not None:
                self._network_offline = not up
        if self._network_offline:
            out.add("network_offline")
        if self._uptime_at is None or now - self._uptime_at >= self.uptime_every:
            self._uptime_at = now
            boot = self.probes.boot_time()
            if boot is not None:
                self._high_uptime = (self._wall_clock() - boot) > self.high_uptime
        if self._high_uptime:
            out.add("high_uptime")
        return out

    def _window_tags(self, current=()):
        """app_<id> / site_<id> / category tags, from the rules file."""
        fg = self._foreground_record()
        out = set()
        self.matched_rule = ""
        self.matched_site = ""

        exe = fg.get("exe") or ""
        if exe == "lockapp.exe":
            out.add("locked")
        if fg.get("hwnd"):
            self._screen_off_streak = 0
        else:
            # A null foreground handle is only a screen-off signal once it
            # persists; a window can vanish mid-switch.
            self._screen_off_streak += 1
            if self._screen_off_streak > self.screen_off_polls:
                out.add("screen_off")
        if fg.get("cls") in ("Progman", "WorkerW") and exe == "explorer.exe":
            out.add("minimized_all")

        # The container tags come from the exe alone, so a browser or an
        # emulator still gets its general pool even when no site or game rule
        # fires on top of it.
        if exe in self.rules.browsers:
            out.add("browser")
        if exe in self.rules.emulators:
            out.add("emulator")

        rule = self.rules.match_app(fg) or self.rules.match_emulator(fg)
        if rule is not None:
            out.update(rule.tags)
            self.matched_rule = rule.id
            self.context["app"] = rule.name or rule.id

        site = self.rules.match_site(fg)
        if site is not None:
            out.update(site.tags)
            self.matched_site = site.id
            self.context["site"] = site.id
            self.context["app"] = site.name or site.id   # "YouTube" is the app too

        if fg.get("fullscreen"):
            out.add("fullscreen")
        # Audio is inferred from what is in front, not measured - see data/README.
        if out & set(PASSIVE_TAGS):
            out.add("audio_playing")

        self.context["exe"] = exe
        self._note_app_change(fg, rule, out)
        return out

    def _note_app_change(self, fg, rule, tags):
        """Track the switch rate, and reset the focus timer when the app moves."""
        now = self._clock()
        key = rule.id if rule is not None else (fg.get("exe") or "")
        if key and key != self._last_app:
            self._last_app = key
            self._switches.append(now)
        while self._switches and now - self._switches[0] > self.app_switch_window:
            self._switches.popleft()
        category = next((c for c in FOCUS_CATEGORIES if c in tags), "")
        if category != self._focus_key:
            self._focus_key = category
            self._focus_category = category
            self._focus_since = now

    def _behavior_tags(self, current=()):
        """app_switching and multi_monitor."""
        out = set()
        if len(self._switches) > self.app_switch_max:
            out.add("app_switching")
        if not self._monitor_checked:
            self._monitor_checked = True
            try:
                count = self.probes.monitor_count()
            except Exception:
                count = None
            self._multi_monitor = bool(count and count > 1)
        if self._multi_monitor:
            out.add("multi_monitor")
        return out

    def _session_tags(self, current=()):
        """long_session / very_long_session / long_focus_<category>."""
        now = self._clock()
        out = set()
        minutes = (now - self._session_since) / 60.0
        if minutes > 240.0:
            out.add("very_long_session")
        elif minutes > 120.0:
            out.add("long_session")
        if self._focus_category and (now - self._focus_since) / 60.0 >= 90.0:
            out.add("long_focus_" + self._focus_category)
        return out

    def _idle_tags(self, current=()):
        """user_idle, watching_idle, and the short / long break split."""
        try:
            idle = float(self._idle_source()) if self._idle_source else None
        except Exception:
            idle = None
        if idle is None:
            return set()
        now = self._clock()
        out = set()
        was_idle = self._last_idle >= self.idle_after

        if idle >= self.idle_after:
            if not was_idle:
                self._away_since = now
        elif was_idle and self._away_since is not None:
            # Coming back from an idle stretch. Only a *confirmed* idle counts:
            # a reading that flapped without ever settling must not announce a
            # return either, or every blip would fire user_back.
            if "user_idle" in self._prev or "watching_idle" in self._prev:
                away = now - self._away_since
                out.add("user_back")
                if away >= self.back_long_after:
                    out.add("user_back_long")
                if away >= self.break_after:
                    out.add("break_taken")
                if away >= self.session_gap:
                    self._session_since = now
                # the focus clock only restarts on the way back from a real
                # idle stretch; while the user is simply working it runs on
                self._focus_since = now
            self._away_since = None
        self._last_idle = idle

        if idle >= self.idle_after:
            passive = bool(set(current) & set(PASSIVE_TAGS)) or (
                "fullscreen" in set(current)
                and bool(set(current) & {"gaming", "video", "streaming"}))
            # Watching something is not the same as being away: a pet must not
            # ask "are you still there?" over a fullscreen cutscene.
            out.add("watching_idle" if passive else "user_idle")
        return out

    # ------------------------------------------------------------------ misc
    def drain_edges(self):
        """Hand over the state changes since the last call and forget them."""
        with self._lock:
            edges, self.edges = self.edges, []
            return edges

    def describe(self):
        tags = self.current_tags()
        return ", ".join(tags) if tags else "nothing unusual"

    def _prune_context(self, published):
        """Keep context in step with the tags actually published.

        `context.app` / `context.site` name what is in front, so they must not
        survive the app leaving - otherwise `{app}` in a line would still say
        "Genshin Impact" after the user closed it. Titles are never here, only
        the rule's own display name, which is exactly what the privacy rule
        allows to leave the matcher.
        """
        # A site also names the app ("YouTube"), so it fills `app` when no app rule
        # claimed the foreground. Either way `app` must not survive the thing it
        # names having gone away - otherwise `{app}` would keep saying
        # "Genshin Impact" long after the game was closed.
        if not (self.matched_rule or self.matched_site):
            self.context["app"] = ""
        if not self.matched_site or not any(t.startswith("site_")
                                            for t in published):
            self.context["site"] = ""

    def _refresh_context(self, now):
        self.context["time"] = time.strftime("%H:%M",
                                             time.localtime(self._wall_clock()))
        self.context["focus_minutes"] = int(max(0.0, (now - self._focus_since) // 60))
        self.context["session_minutes"] = int(max(0.0, (now - self._session_since) // 60))

    def _print_debug(self):
        """Console only - window titles are shown here and nowhere else."""
        ctx = " ".join(f"{k}={v!r}" for k, v in self.context.items() if v != "")
        print(f"[watcher] {self.describe() or 'nothing unusual'} | "
              f"rule={self.matched_rule or '-'} site={self.matched_site or '-'}"
              + (f" | {ctx}" if ctx else ""))