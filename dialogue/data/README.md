# data/

The lines, and the rules. Nothing in here is code - edit and restart (or reload
the engine) and that is the whole workflow.

```
default.json               fallback lines, chat topics and audience lines
states.json                fallback lines per computer state + tag priority
watcher_rules.json         which app / site / game means which tags
archetypes/<name>.json     shared personality pool; characters point at one
characters/<name>.json     one character; file name = its .glb, normalised
```

A file whose name starts with `_` is a template and is never loaded, so
`_template.json` in both folders is there to copy from. Keys inside any file
that start with `_` are notes to yourself and are ignored as data.

## Which line is used

For `DialogueEngine.get(character, event, states)`:

| # | pool                     | example                        |
|---|--------------------------|--------------------------------|
| 1 | character + state + event| Hoshino, poked, battery low   |
| 2 | character + state        | Hoshino, battery low          |
| 3 | archetype + state + event| whoever is sleepy, battery low|
| 4 | archetype + state        | whoever is sleepy, battery low|
| 5 | default + state + event  | everyone, battery low         |
| 6 | default + state          | everyone, battery low         |
| 7 | character + event        | Hoshino, poked                |
| 8 | archetype + event        | whoever is sleepy, poked      |
| 9 | default + event          | the plain `POKE_LINES`        |

The first pool with a line wins, and the chain walks down until one has a line -
so a specific tag with only `idle` lines still lets a poke fall through to
row 9. Tags are tried in `_priority_order`, most important first.

## Events

The pet code asks for: `poke` `petting` `idle` `hover` `drag` `land` `lost`
`jump` `cutin` `summon` `perch` `tactical` `tactical_first` `launch`.

Two more come from the watcher rather than the user:

| event | when |
|-------|------|
| `state_enter` | the tag just became active - Sensei opened Genshin |
| `state_exit`  | it stopped - Genshin closed |

`state_enter` is where a tag's best line usually belongs. Reactions are
one-shot, so opening a game can produce a comment without making that the
answer to every poke for the rest of the session.

**A plain list answers every event**, not just idle chatter - while `battery_low`
is active, a poke and a jump would both answer with that line. Scope it:

```jsonc
"battery_low": ["Charge it, Sensei."]                        // any event
"battery_low": { "idle": ["Charge it, Sensei."] }            // idle only
"battery_low": { "*": ["Charge it, Sensei."],
                  "idle": ["Sensei, my... your battery."] }  // both
```

Inside a tag's object you may also add `"_reaction_cooldown": 900` - how long
that tag stays quiet after a reaction, in seconds (default 600). It is a note,
so it is never spoken.

## Placeholders

`{name}` and `{me}` are the speaker, `{other}` the listener, `{pronoun}` is
whatever `pronoun` says in the character file (`she` unless changed).

From the watcher's `context`:

| placeholder | example |
|-------------|---------|
| `{app}`     | `Genshin Impact`, `YouTube` |
| `{site}`    | `youtube` |
| `{exe}`     | `genshinimpact.exe` |
| `{battery}` | `42%` |
| `{time}`    | `14:05` |
| `{focus_minutes}`  | `35 minutes` in the current app |
| `{session_minutes}`| `200 minutes` since a real break |

Substitution is a plain replace, so a stray `{` in a line is spoken as typed and
an unknown placeholder is left exactly as written. An empty value is skipped
rather than speaking a blank.

## states.json

`states` maps a tag to a list or to an object keyed by event, `*` being the
general lines. `_priority_order` decides which active tag wins.

Anything **not** in `_priority_order` is ranked below everything listed, which
is almost never what you want - the watcher prints a startup note naming the
tags it can emit that the list omits. Put a tag in the list when you add a pool.

### Tags the watcher can produce

`system_watcher.py` detects all of these; which ones are in `_priority_order`
today is visible in the file.

| group | tags |
|-------|------|
| time of day | `late_night` `early_morning` `morning` `afternoon` `evening` `night` |
| calendar | `lunch_time` `weekday` `weekend` `monday_morning` `friday_evening` |
| power | `charging` `battery_low` `battery_critical` `battery_full` `on_battery` |
| load | `cpu_high` `memory_high` `disk_low` `network_offline` `high_uptime` |
| session | `long_session` `very_long_session` `long_focus_coding` `long_focus_gaming` `long_focus_video` `long_focus_office` `long_focus_browser` |
| away | `user_idle` `watching_idle` `user_back` `user_back_long` `break_taken` |
| window | `fullscreen` `app_switching` `multi_monitor` `minimized_all` |
| lock | `locked` `screen_off` |
| specific apps | `app_blue_archive` `app_genshin` `app_star_rail` `app_zzz` `app_wuwa` `app_honkai_3` `app_arknights` `app_fgo` `app_valorant` `app_league` `app_minecraft` `app_osu` `app_steam` `app_epic` `app_obs` `app_spotify` `app_vlc` `app_mpv` `app_discord` `app_telegram` `app_slack` `app_zoom` `app_teams` `app_foobar2000` |
| specific sites | `site_youtube` `site_youtube_music` `site_twitch` `site_netflix` `site_bilibili` `site_crunchyroll` `site_disney_plus` `site_niconico` `site_twitter` `site_reddit` `site_facebook` `site_discord` `site_github` `site_stackoverflow` `site_notion` `site_google_docs` `site_google_sheets` `site_google_slides` `site_chatgpt` `site_claude` `site_gemini` `site_meet` `site_pixiv` `art_browsing` |
| categories | `gaming` `video` `coding` `music` `office` `streaming` `meeting` `ai_chat` `browser` `emulator` `text_editor` `creative` `audio_playing` |
| system apps | `task_manager` `file_explorer` `installer` `system` |

`psutil` is optional; without it the battery / cpu / ram / network tags simply
never appear. Nothing Windows-only is required either.

A specific tag always arrives together with its category
(`app_genshin` **and** `gaming`), so a pool for `gaming` keeps working while
`app_genshin` gets the pinpoint lines. `audio_playing` is *inferred* from having
a video or music app in front, not measured - see the note in
`watcher_rules.json`.

## watcher_rules.json

This is what tells the watcher which program is which. Adding a game never
means editing Python.

```jsonc
{
  "apps": [
    { "id": "blue_archive", "name": "Blue Archive",
      "exe": ["BlueArchive.exe"],
      "emulator_title_regex": ["blue ?archive"],
      "tags": ["app_blue_archive", "gaming"] }
  ],
  "sites": [
    { "id": "youtube", "name": "YouTube", "browser_only": true,
      "title_regex": ["\\byoutube\\b"], "tags": ["site_youtube", "video"] }
  ],
  "custom_apps": [],              // same shape as "apps", for your own
  "browsers": ["chrome.exe", ...],
  "emulators": ["hd-player.exe", ...],
  "fullscreen_ignore_exe": ["explorer.exe", ...],
  "disabled_tags": [],            // e.g. ["site_*"] to switch a class off
  "enabled_categories": [],       // a whitelist, e.g. ["app_", "site_"]
  "thresholds": { "idle_after": 90.0, ... }
}
```

**Matching.** Rules are checked top to bottom and the **first** `apps` rule that
matches wins, so put specific rules above general ones. A rule matches when
**any** listed `exe` matches **or** any `title_regex` matches, subject to
`exclude_exe` / `exclude_title_regex`. Every rule needs an `id` and at least one
tag.

| key | effect |
|-----|--------|
| `require_title_regex` | exe alone is not enough, the title must match too. For generic hosts like `javaw.exe` or `Client-Win64-Shipping.exe`, which would otherwise claim every Java or Unreal game on the machine |
| `skip_browser` | do not fire on a browser tab that merely mentions the name, so a Blue Archive wiki page is not read as playing the game |
| `emulator_title_regex` | an emulator's exe only says "an emulator" (`emulator`); this promotes it to the real game from the window title |
| `browser_only` (sites) | only match when the foreground exe is a listed browser |

**Exe names are a starting set, not gospel.** They came from official installs
and community documentation and some are worth confirming on your own machine.
If a game does not register, start the app and check what the window is actually
called, then add it. Emulator titles vary by emulator and language - run the app
with `--debug-tags` and add a pattern if `emulator_title_regex` does not fire.

**`thresholds`** moves the watcher's numbers without touching code. Values
outside a sane range are ignored rather than trusted, so a typo cannot wedge the
watcher. `fullscreen_tolerance` is how many pixels the window may miss the
monitor edge by; `debounce_polls` is how many polls a tag must hold steady before
it counts.

**Privacy.** Window titles are matched in memory and thrown away. Only the
matched rule's id, its display name and its tags are ever published - never a
title, never to a log file. Idle time comes from `GetLastInputInfo` and nothing
else: no keystrokes, no mouse contents, no screenshots, no network lookups.
`disabled_tags` / `enabled_categories` let you switch off whole classes, such
as every `site_*` tag.

## characters/<name>.json

File name is the `.glb` name lowercased with everything non-alphanumeric
removed, so `Hoshino.glb` -> `hoshino.json` and `Hina (Dress).glb` ->
`hinadress.json`. Loaded on first use, so you only need one for a character you
actually want to change.

```jsonc
{
  "archetype": "sleepy",
  "pronoun": "she",
  "reactions": { "poke": ["...Five more minutes, Sensei."] },
  "states":    { "battery_low": ["Sensei, my... your battery. Charge it."] },
  "chat_topics": { "naps": [["Have you tried sleeping on a title bar, {other}?", "plain"]] },
  "pair_lines": { "shiroko": { "greeting": [["Oh, it is you, {other}.", "warm"]] } }
}
```

`archetype` names a file in `archetypes/`. `chat_topics` are extra topics only
she starts. `pair_lines` is banter for one specific pairing and falls back to
the shared topics when the other character has no file.

## archetypes/<name>.json

Same shape, but shared: `"archetype": "sleepy"` in a character file makes her
use it. Several characters can point at the same one. `sleepy` and `tsundere`
ship as worked examples of `site_youtube` and `app_blue_archive`; `hoshino.json`
uses the first.

A pet-to-pet conversation can be started by a computer state too, by giving a
tag a `chat_topics` block here. It is opt-in per tag - without one, nothing is
said.

## Running the tests

```
python -m unittest discover -s dialogue -p "test_*.py" -t .
```

Nothing touches the real machine: the foreground window, idle seconds, both
clocks and every system probe are injected, so the whole tag sequence runs on
any platform. There are also tests asserting the privacy rules and the sample
timing.