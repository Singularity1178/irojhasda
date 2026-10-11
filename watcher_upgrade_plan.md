# Plan: Expand system detection and app-specific dialogue

Target project: the Blue Archive multi-pet desktop app (`dialogue/` package: `system_watcher.py`, `engine.py`, `conversation.py`, `data/`).

Goal: detect much more about what the user is doing (specific apps, sites and games, plus richer system and session state), and let characters, archetypes and the default pool have specific lines for each. Keep the existing architecture: the watcher only publishes tags, the engine only picks lines, and editing lines never needs Python.

**Before starting:** read `engine.py` and `conversation.py` in full. They were not available when this plan was written, so every engine-side step below must be checked against how the engine actually resolves pools, handles priority and dedupes lines. Keep the lookup order table in `dialogue/README.md` correct.

---

## 0. Problems in the current watcher (fix first)

1. **Substring false positives in `TITLE_TAGS`.** `"obs"` matches "jobs", `"edge"` matches "knowledge", `"vim"` matches "vimeo", `"steam"` matches "steamed", `"riot"` matches "patriot". Replace with process-name matching plus word-boundary regex on titles.
2. **`"code.exe"` and `"cmd.exe"` are process names, but only the window title is checked.** They never match. Read the foreground process name (step 1).
3. **`notepad` counts as `coding`.** Make it its own `text_editor` tag, or drop it.
4. **`fullscreen` is guessed from the title.** A YouTube tab is not fullscreen. Detect it by comparing the window rectangle to its monitor rectangle (step 2).
5. **`afternoon` covers 08:00-17:00, so mornings are mislabelled.** Split into `morning` (08-12), `afternoon` (12-17), and keep `evening` (17-24).
6. **Idle fires while watching fullscreen video.** `user_idle` sits above `fullscreen` in the priority list. Suppress `user_idle` while media is playing or a fullscreen video or game is in front (see 3.5).
7. **`psutil.cpu_percent(interval=None)` returns 0.0 on its first call.** Prime it once in `__init__`. Also add hysteresis so a single spike does not trigger `cpu_high` (see 3.4).
8. **ctypes hygiene.** Set `argtypes` and `restype` for `GetForegroundWindow` and similar calls (64-bit handles). Use `GetTickCount64` and a `c_uint` `dwTime`. The current `GetTickCount` wraps at about 49 days.
9. **Battery tags flicker around thresholds.** Add a small hysteresis band (enter at 25, leave at 28).
10. **Edge flapping.** `edges` is produced on any tag change, so a tag toggling every poll would spam pets. Add a debounce (a tag must be stable for 2 polls before it counts, except `user_back`).

---

## 1. Foreground app identification (the core change)

Add `_foreground()` returning a small record: `hwnd`, `title`, `pid`, `exe` (lowercased basename, e.g. `chrome.exe`), `rect`.

- `GetWindowThreadProcessId(hwnd, byref(pid))`, then `psutil.Process(pid).name()` (wrapped in try/except, because access-denied is common for elevated or game-protected processes). If psutil is missing, fall back to `OpenProcess` + `QueryFullProcessImageNameW`, or just leave `exe` empty.
- Cache `exe` by pid so psutil is not queried every poll.
- Keep the 3 s interval. Everything here is cheap.
- Non-Windows: return an empty record. No tags, no tracebacks (the existing forgiving rule).

## 2. Data-driven rules file: `data/watcher_rules.json`

Move the hard-coded `TITLE_TAGS` and `FULLSCREEN_TITLES` out of Python. The loader should ignore `_`-prefixed keys like the other data files, and a missing or broken file must fall back to a minimal built-in rule set (never a traceback).

```jsonc
{
  "_note": "Rules are checked top to bottom. A rule matches when ANY listed exe matches OR title_regex matches, subject to exclude. Each match adds ALL of its tags.",
  "apps": [
    { "id": "blue_archive",
      "exe": ["bluearchive.exe", "bluearchive_jp.exe"],
      "emulator_title_regex": ["blue ?archive", "ブルーアーカイブ", "블루 ?아카이브"],
      "tags": ["app_blue_archive", "gaming"] },
    { "id": "genshin",
      "exe": ["genshinimpact.exe", "yuanshen.exe"],
      "tags": ["app_genshin", "gaming"] }
  ],
  "sites": [
    { "id": "youtube", "browser_only": true,
      "title_regex": ["\\byoutube\\b"], "tags": ["site_youtube", "video"] }
  ],
  "fullscreen_ignore_exe": ["explorer.exe", "searchhost.exe", "shellexperiencehost.exe"]
}
```

Semantics the agent must implement:

- **Specific plus general tags.** A match emits the specific tag (`app_genshin`) and the category (`gaming`). This keeps old pools working and allows pinpoint lines.
- **Browser handling.** If `exe` is in a browser list (`chrome.exe`, `msedge.exe`, `firefox.exe`, `brave.exe`, `opera.exe`, `vivaldi.exe`, `arc.exe`), emit `browser` and then run `sites` rules against the title. Browser titles look like `<page title> - YouTube - Google Chrome`, so match on the site suffix or keyword, not just the start.
- **Emulator handling (BlueStacks `hd-player.exe`, LDPlayer `dnplayer.exe`, MuMu `mumuplayer.exe` / `nemuplayer.exe`, Nox `nox.exe`, MEmu `memu.exe`, Google Play Games `googleplaygames`).** The exe alone only says "an emulator" (tag `emulator`). Use `emulator_title_regex` against the window title to promote it to the specific game tag. Many emulators title the window with the app name, so verify against real titles and let the user add patterns.
- **Priority between rules:** the first matching `apps` rule wins for the app slot; `sites` rules only run when the foreground is a browser.
- **Fullscreen** is a separate boolean computed from the rect: window rect covers its monitor (`MonitorFromWindow` + `GetMonitorInfoW`, tolerance of a few px), the window is not the desktop or shell (`fullscreen_ignore_exe`), and it is not the pet app itself. Emit `fullscreen`. Also detect borderless-windowed games the same way.
- The agent should **verify exe names** from official installs rather than trusting the list below blindly. Treat the list as a starting set that the user can edit.

### Starting app and site coverage (put these in the rules file)

Games (tag `gaming` plus specific): Blue Archive (PC client and emulators), Genshin Impact (`GenshinImpact.exe`, `YuanShen.exe`), Honkai: Star Rail (`StarRail.exe`), Zenless Zone Zero (`ZenlessZoneZero.exe`), Wuthering Waves (`Wuthering Waves.exe`, `Client-Win64-Shipping.exe`), Honkai Impact 3rd, Arknights (emulator or PC), Fate/Grand Order (emulator), Valorant (`VALORANT-Win64-Shipping.exe`), League of Legends (`LeagueClient.exe`, `League of Legends.exe`), Minecraft (`javaw.exe` with "Minecraft" in the title), osu! (`osu!.exe`), Steam client (`steam.exe`, as `app_steam`, a launcher, not a game), Epic launcher, a generic `game_unknown` fallback if a fullscreen exe comes from a Steam library path (optional, see 3.9).

Video and music: YouTube, Twitch, Netflix, Bilibili, Crunchyroll, Disney+, niconico, VLC (`vlc.exe`), MPV (`mpv.exe`), OBS (`obs64.exe`, tag `app_obs` plus `streaming`), Spotify (`spotify.exe`, tag `music`), foobar2000, YouTube Music (site).

Social and chat: Discord (`discord.exe`, site discord.com), Twitter/X, Reddit, Facebook, Messenger, Telegram, Slack, Zoom (`zoom.exe`), Teams, Google Meet (site, tag `meeting`).

Work and study: VS Code (`code.exe`), PyCharm, IntelliJ, Android Studio, Visual Studio (`devenv.exe`), Windows Terminal / cmd / PowerShell / Git Bash, GitHub (site), Stack Overflow (site), Notion, Google Docs/Sheets/Slides, Microsoft Word/Excel/PowerPoint (`winword.exe`, `excel.exe`, `powerpnt.exe`, tag `office`), Anki, ChatGPT / Claude / Gemini (site, tag `ai_chat`).

Creative and fan: Photoshop, Clip Studio Paint, Blender, Krita, Pixiv (site), Pixiv/Danbooru-style gallery sites should map to a neutral tag like `art_browsing` only. **Do not create tags for adult content.**

System: File Explorer (`explorer.exe` with a non-desktop window), Task Manager (`taskmgr.exe`, a good pairing with `cpu_high`), Settings, Windows Update, installer windows (`setup`, `installer`, `msiexec.exe`), the lock screen (see 3.7).

---

## 2.5 What the watcher should publish besides tags

Add `watcher.context`, a dict refreshed each sample, so the engine can fill placeholders:

```
app        human-readable name from the rule ("Genshin Impact", "YouTube")
exe        foreground exe
site       site id when in a browser
battery    percent (int) or None
time       "14:05" local
focus_minutes   minutes in the current app/category without a >2 min gap
session_minutes minutes since user_back / since the watcher started
```

Keep `tags` and `edges` working exactly as before so nothing else breaks. Add `context` as new, optional.

---

## 3. New signals to detect (beyond app identification)

Add each as a small detector method like the existing `_power_tags` and `_load_tags`, each wrapped in try/except so a failure means one fewer tag.

### 3.1 Time and calendar
- `morning` (08-12), `afternoon` (12-17), `evening` (17-22), `night` (22-24), `late_night` (00-05), `early_morning` (05-08).
- `lunch_time` (12:00-13:30), `weekend`, `weekday`, `monday_morning`, `friday_evening`.
- Optional: `birthday` / `new_year` / `christmas` style date tags from a `data/calendar.json` (e.g. date -> tag). Also a user-configurable list for character birthdays or Blue Archive anniversaries. Keep it data-only.

### 3.2 Battery and power transitions
- Keep `charging`, `battery_low`, `battery_critical`.
- Add `battery_full` (>=98 and plugged), `on_battery` (unplugged).
- Edge events: unplugged and plugged-in are already visible in `edges` (`+on_battery`, `+charging`), so these become one-shot reactions (see 5).
- Add `battery_saver` only if `psutil` or the Windows API exposes it cheaply. Skip otherwise.

### 3.3 Session and time-on-task
- `long_session`: the user has been active (no idle gap > 5 min) for more than 2 hours. Add `very_long_session` at 4 hours. Reset when a real break happens.
- `long_focus_coding`, `long_focus_gaming`, `long_focus_video`: same category in front for more than 90 min.
- `just_started_<category>`: optional edge only.
- `break_taken`: `user_back` after more than 10 minutes idle. Distinguish short (`user_back`) from long (`user_back_long`, 30+ min) absences.

### 3.4 Load with hysteresis
- `cpu_high` only after 3 consecutive samples above threshold, clears below 70.
- `memory_high` likewise.
- New: `disk_low` (system drive under 10% free, checked rarely, once a minute), `network_offline` (no non-loopback interface up, or a cheap socket check; once per 10 s, not every poll), `hot_cpu` only if a temperature sensor is exposed (`psutil.sensors_temperatures` is not available on Windows, so skip it).
- `high_uptime` (machine up more than 3 days, from `psutil.boot_time()`).

### 3.5 Audio and media
- `audio_playing` using an optional dependency (`pycaw` / Windows Core Audio peak meter). Optional, guarded import. Without it, infer from the app (YouTube site, Spotify, VLC).
- `muted` is only worth it if it comes for free with pycaw.
- **Idle suppression:** do not emit `user_idle` while `audio_playing`, a `video` tag is active, or `fullscreen` is on with a media or game app. Instead emit `watching_idle` (passively watching). That makes lines like "Enjoying the show, Sensei?" possible instead of "Are you still there?".

### 3.6 Window behavior
- `app_switching`: more than N foreground-app changes in the last 60 s (restless, distracted). N configurable, default 8.
- `multi_monitor` (count monitors, static).
- `many_windows` optional, only if cheap to count visible top-level windows.
- `minimized_all` / desktop visible: foreground is the shell with the desktop in front.

### 3.7 Session lock and display
- `locked` / `screen_off`: the foreground is `LockApp.exe` or the foreground handle is null for several polls. A pet could say something on return (`+user_back` after `locked`).
- Treat the watcher as paused while locked so idle timers do not accumulate misleadingly.

### 3.8 Peripherals (optional, low priority)
- Headphones plugged and USB device plug events are doable but fiddly. Leave as a stretch goal, behind a feature flag.

### 3.9 Game awareness (optional)
- If a fullscreen exe lives under a known Steam library path (`...\steamapps\common\...`) or is on a user list, emit `gaming` plus `app_unknown_game` with the exe's friendly name in `context.app`.
- Allow the user to add exes to a `custom_apps` list in the rules file without touching code.

### Privacy rules (hard requirements)
- No keystroke or mouse-content logging. Idle time via `GetLastInputInfo` only.
- Window titles are matched in memory and **never written to disk or logs**. Do not store video titles. Only the matched tag, the rule name and the rule's display name leave `_foreground()`.
- Add a settings switch in the rules file: `"enabled_categories"` / `"disabled_tags"`, so the user can switch off whole classes (for example `site_*`) and the watcher drops them before publishing.

---

## 4. Updating tag priority

`states.json` → `_priority_order` decides which tag's line pool wins. The watcher's `priority` list comes from the same file. Rewrite it so specific beats general beats ambient:

```
urgent system:   battery_critical, battery_low, disk_low, cpu_high, memory_high, network_offline
transitions:     user_back_long, user_back, locked
specific apps:   app_blue_archive, app_genshin, app_star_rail, app_zzz, app_wuwa, app_valorant,
                 app_league, app_minecraft, app_steam, app_discord, app_obs, app_spotify,
                 site_youtube, site_twitch, site_netflix, site_bilibili, site_twitter,
                 site_reddit, site_github, site_stackoverflow, site_pixiv, site_google_docs, ...
sessions:        very_long_session, long_session, long_focus_*
categories:      watching_idle, user_idle, fullscreen, meeting, streaming, music,
                 coding, gaming, video, office, ai_chat, browser, emulator, text_editor
ambient:         charging, battery_full, on_battery, app_switching, high_uptime,
                 lunch_time, weekend, late_night, early_morning, morning, afternoon, evening, night
```

Notes:
- `_priority` currently returns `len(priority)` for unknown tags, so any tag missing from the list is silently demoted. Add a debug check that logs (once at startup, not per poll) any tag the watcher can emit that is absent from `_priority_order`.
- Decide, and document, whether `user_idle` should rank above or below specific apps. Recommended: below `app_*` (a character should say something about the game they are watching you play) but above general ambient tags.
- The engine uses "the first active tag that has a line pool". If it does not currently fall through to the next active tag when the first has no pool for this event, **verify this in `engine.py`**. The README implies it does. If it does not, change it, because specific tags like `site_youtube` will often have pools only for `idle`.

---

## 5. Engine and dialogue changes

(Confirm each against the real `engine.py` first.)

1. **Enter and exit reactions.** Use `drain_edges()` (already implemented, currently unused by anything described). Add new events the engine can ask for: `state_enter` and `state_exit`, scoped per tag: `{"app_genshin": {"state_enter": ["Oh, Genshin again, Sensei?"]}}`. The pet manager should consume edges once per poll and make one randomly chosen pet speak, not all pets.
2. **Cooldowns.** Per-tag cooldown for enter reactions (default 10 min) so alt-tabbing does not spam. Per-pet cooldown so one pet is not always the speaker. Respect the existing "do not repeat the last few lines" memory.
3. **Placeholders** from `watcher.context`: `{app}`, `{site}`, `{battery}`, `{time}`, `{focus_minutes}`, `{session_minutes}`. Substitution stays a plain replace, and unknown placeholders are left as typed (the existing rule).
4. **Multiple pets.** Specific tags should be able to trigger a short pet-to-pet exchange via `ChatDirector`, for example one pet sees `app_blue_archive` and another reacts. Add optional `chat_topics` keyed by tag, and let `conversation.py` start one when a high-interest edge fires and no conversation is active. Keep it opt-in per tag (`"chat": true` in the line data).
5. **Scoping lines to events.** Keep the README warning: use the object form `{ "idle": [...], "state_enter": [...] }` so a poke does not return an idle line.
6. **Fallback chain unchanged.** Rows 1-9 in the lookup table stay as is. Only the tag vocabulary and priority list grow.

## 6. Data files to create

- `data/watcher_rules.json` (apps, sites, categories, browsers, emulators, `fullscreen_ignore_exe`, `custom_apps`, `disabled_tags`, thresholds).
- Extend `data/states.json` with starter pools for the new tags. Keep them generic and in the default Sensei voice, and write at least:
  - `app_blue_archive`, `site_youtube`, `app_genshin` (the three the user named), each with `idle` and `state_enter` lines.
  - `long_session`, `very_long_session`, `user_back_long`, `battery_full`, `on_battery`, `watching_idle`, `app_switching`, `meeting`, `high_uptime`.
- Add per-character and per-archetype examples (one for a sleepy and one for a tsundere archetype) for `site_youtube` and `app_blue_archive` to prove the override order works. Blue Archive characters talking about the game itself can be self-aware and playful ("They made a game about us, Sensei?").
- Update `data/README.md` and `dialogue/README.md` with: the new tags, the new `state_enter` / `state_exit` events, the placeholders, and the rules file format.
- `_template.json` additions showing `state_enter`.

## 7. Implementation order

1. Fix section 0 items 1-10 in `system_watcher.py` (no new features yet). Ensure behavior is identical for the old tags.
2. Add `_foreground()`, process-name lookup and the monitor-rect fullscreen check.
3. Add the rules loader and `data/watcher_rules.json` with Blue Archive, Genshin and YouTube first, then fill the rest of the coverage list.
4. Add `context`, session/focus timers, idle suppression, and the new system/time tags (sections 3.1-3.7).
5. Rewrite `_priority_order`, add the startup check for missing tags.
6. Engine: `state_enter` / `state_exit`, cooldowns, placeholders, fallthrough verification.
7. Starter dialogue and README updates.
8. Optional extras: audio detection, game path heuristics, calendar tags, pet-to-pet reactions.

## 8. Testing and acceptance

- Make `SystemWatcher` testable: let the foreground record, `psutil` data, clock and idle seconds be injected (constructor args or overridable methods) so tests need no real Windows.
- Unit tests, each a fake sample producing the expected tags:
  - `chrome.exe` + "Some Video - YouTube - Google Chrome" → `browser`, `site_youtube`, `video`.
  - "Jobs and Careers - Google Chrome" must not produce `obs`-related tags; "Knowledge Base - Chrome" must not match `edge`.
  - `GenshinImpact.exe` fullscreen → `app_genshin`, `gaming`, `fullscreen`.
  - `HD-Player.exe` titled "Blue Archive" → `emulator`, `app_blue_archive`, `gaming`.
  - Fullscreen video with 120 s idle → `watching_idle`, not `user_idle`.
  - CPU above threshold for 1 sample → no `cpu_high`; 3 samples → `cpu_high`; below 70 → cleared.
  - 08:30 → `morning`; 14:00 → `afternoon`.
  - Same tag flapping in alternate polls produces no edges.
  - Battery hysteresis around 25/28.
  - Missing psutil, non-Windows, a missing rules file and a corrupt rules file all return a tag list without raising.
- Engine tests: a `site_youtube` line is used for idle when YouTube is active; a poke while on YouTube still gets a poke line; a character file overrides the default; the enter reaction fires once and respects its cooldown; with several pets only one speaks.
- Manual check: add a `--debug` / print mode that shows the current tags, the matched rule and `context` every poll (titles shown only in the console, never logged to a file).
- Performance: one sample must stay under about 10 ms on a typical machine, and the pet render loop must never block on the watcher (keep polling on the existing interval, ideally on a worker thread if any step proves slow).

## 9. Out of scope / do not do

- No keyloggers, screenshots, OCR, clipboard reading or reading page contents.
- No network calls to identify apps.
- No tags or lines about adult or sensitive content.
- No hard dependency on psutil, pycaw or any Windows-only API.
- Do not change the nine-row lookup order or the file naming rules for characters and archetypes.
