# dialogue

Everything the pets say, split out of `multi_single_screen_pet_ba.py`.

```
engine.py            DialogueEngine  - "give me a line for (character, event, states)"
conversation.py      Conversation / ChatDirector - pet-to-pet talking
reactions.py         StateReactor - one-off lines when a computer state starts
system_watcher.py    SystemWatcher - what the computer is doing -> state tags
wikilines.py         WikiLines - a student's own wiki voice lines (voicelines/data/*.wiki)
data/
  default.json                     fallback lines + chat topics, for everyone
  states.json                      fallback lines per state + tag priority
  watcher_rules.json               which app / site / game means which tags
  archetypes/<name>.json           shared personality pools (tsundere, sleepy, ...)
  characters/<name>.json           one character, file named after its .glb
  README.md                        the formats, in detail
  tests/                           unittest, no real machine needed
```

Editing lines never means touching Python. Drop a `characters/hoshino.json` next
to `Hoshino.glb` and only Hoshino changes; everything else falls through to
`default.json`. Adding a game means adding a rule to `watcher_rules.json`, not
code. Nothing here imports PySide, so it can be imported and tested on its own.

## Her own wiki voice lines come first

Before any of the pools below, `DialogueEngine.get` asks `wikilines.py` for the student's own lines
from `voicelines/data/<Student>.wiki`:

| event                  | wiki row           |
|------------------------|--------------------|
| `tactical_first` (spawn) | `Gachaget`       |
| `idle`                 | `Cafe_monolog_N`   |
| `poke`, `petting`      | `Lobby_N`          |

If she has any, one of those is spoken and the pools below are skipped (watcher states included).
With no file, an unreadable file, or no such row, or for any other event, the chain below runs as before.
A line made of several `<p>` paragraphs comes back as `part<p>part`; `Pet.say` shows the parts one after another with a pause.

## Where a line comes from

`DialogueEngine.get(character, event, states)` tries these pools in order and
speaks the first one that has a line left:

| # | pool                                        | example                        |
|---|---------------------------------------------|--------------------------------|
| 1 | character + state + event                   | Hoshino, poked, battery low    |
| 2 | character + state                           | Hoshino, battery low           |
| 3 | archetype + state + event                   | whoever is sleepy, battery low |
| 4 | archetype + state                           | whoever is sleepy, battery low |
| 5 | default + state + event                     | everyone, battery low          |
| 6 | default + state                             | everyone, battery low          |
| 7 | character + event                           | Hoshino, poked                 |
| 8 | archetype + event                           | whoever is sleepy, poked       |
| 9 | default + event                             | the old `POKE_LINES`           |

Because almost every pool is empty, this normally lands on row 9. That is why
adding one line for one character in one situation leaves everything else
alone. Rows 1-6 are also how ambient computer state works: fill in
`states.json` and the pets pick it up with no extra code.

**The chain falls through.** If the most important active tag has no line for
this event, the next tag is tried, and eventually the plain event pools. That
matters because specific tags like `site_youtube` usually carry only `idle`
lines: without the fall-through, a poke while YouTube was open would find the
first tag, find nothing for `poke`, and stay silent.

`event` is what just happened to the character - the string passed to
`Pet.line(...)`: `poke` (clicked), `petting`, `hover`, `drag`, `idle`
(standing around), `jump`, `land`, `perch`, `lost`, `cutin`, `tactical`,
`tactical_first`, `summon`, `launch`, plus `state_enter` and `state_exit` from
the watcher. The `state` half is the watcher's tag (`battery_low`,
`app_genshin`, ...). So row 5 is "everyone's lines for being poked while the
battery is low" and row 6 is "everyone's lines for low battery, whatever she
happens to be doing".

Rows are tried most-important-state first. `states.json` -> `_priority_order`
decides which that is: urgent machine problems at the top, then transitions,
then specific apps, then general categories, and time of day last because it is
always on. Anything missing from that list ranks below all of it, so
`system_watcher.py` prints a startup note naming tags it can emit that the list
omits.

Watch out: a `states` entry written as a plain list answers **every** event,
not just idle chatter - a pet being poked at 2am would say the low-battery
line instead of a poke line. Scope it to the events you mean:

```jsonc
"battery_low": ["Charge it, Sensei."]                       // any event - usually not what you want
"battery_low": { "idle": ["Charge it, Sensei."] }           // idle chatter only
"battery_low": { "*": ["Charge it, Sensei."],
                  "idle": ["Sensei, my... your battery."] } // both
```

The engine also remembers the last few lines it used per character and event,
so it will not say the same thing twice in a row. A pool too small to avoid
that is used as-is rather than going silent.

## Entering and leaving a state

`state_enter` and `state_exit` are ordinary events, asked for by `StateReactor`
from the watcher's edge list. Opening Genshin raises `+app_genshin`, and one
randomly chosen pet says that tag's `state_enter` line once:

```jsonc
"app_genshin": {
  "idle":        ["Teyvat again, Sensei?"],
  "state_enter": ["Oh, Genshin again, Sensei? Mind the primogems."]
}
```

One pet speaks per change, not all of them. Two cooldowns keep it from getting
repetitive: a per-tag cooldown (default 10 minutes, override it with
`"_reaction_cooldown": 900` inside the tag's block in `states.json`) so
alt-tabbing does not spam, and a per-pet cooldown (2 minutes) so the same
character is not always the one talking. `App.tick` drains the edges once per
frame and the "do not repeat recent lines" memory still applies.

## Placeholders

`{name}` and `{me}` are the speaker, `{other}` the listener, `{pronoun}` is
whatever `pronoun` says in that character's file (`she` unless changed).

From `watcher.context`: `{app}` (`Genshin Impact`), `{site}` (`youtube`),
`{exe}`, `{battery}` (`42%`), `{time}` (`14:05`), `{focus_minutes}` and
`{session_minutes}` (both rendered with "minutes").

Substitution is a plain replace, so a stray `{` in a line is spoken as typed and
an unknown placeholder is left exactly as written.

## What the watcher notices

`SystemWatcher` polls every 3 seconds on its own thread and publishes a set of
tags plus a `context` dict. It works out what is in front by matching the
foreground **process name** and, for browsers, the window title against
`data/watcher_rules.json` - not by hunting for substrings in a title, which is
how `"obs"` used to match "jobs".

Highlights:

- **specific plus general.** `app_blue_archive` arrives together with `gaming`,
  so old pools keep working and pinpoint lines are possible on top.
- **emulators.** The exe alone says "an emulator" (`emulator`); the window title
  promotes it to the real game via `emulator_title_regex`.
- **fullscreen** is computed from the window rectangle against its monitor, so a
  maximised YouTube window is not fullscreen and a borderless game is.
- **idle suppression.** While video or music is in front, an idle user is
  `watching_idle`, not `user_idle` - "Enjoying the show, Sensei?" instead of
  "Are you still there?". And `user_idle` ranks below the specific app tags, so
  a character comments on the game rather than on the silence.
- **hysteresis.** Battery tags need a band to leave as well as to enter, cpu and
  memory need samples in a row, and a tag must hold steady for two polls before
  it counts - so a tag toggling every poll never fires a reaction.

**Privacy.** Window titles are matched in memory and discarded. Only the matched
rule's id, its display name and its tags are published - never a title, never to
a log file. Idle time comes from `GetLastInputInfo` and nothing else: no
keystrokes, no mouse contents, no screenshots, no OCR, no network lookups.
`watcher_rules.json` has `disabled_tags` / `enabled_categories` to switch whole
classes off, such as every `site_*` tag.

### Debugging

```
run_ba_pets.bat --debug-tags
```

prints the current tags, the matched rule and the context on every poll. The
title itself is never printed, and nothing is written to a file.

## Privacy between the pets

A character never observes another directly. What one says the other can only
hear through a small, explicit set of hooks in `Conversation` -
`Conversation.topic_lines(topic, other=None)` (a topic with a per-pair version),
`Conversation.pair_topics(other)` (banter written for one specific pairing), and
`Conversation.audience(verb="poke")` (a nearby character's comment on what the
user just did). `own_topics()` is her own and shared; `pick_topic(other)` only
*excludes* topics the other used recently, it does not read her lines.

## Pet-to-pet conversations

`conversation.py` decides who talks to whom and for how long. `Conversation` is
one character's side of a chat - the turn list, whose turn it is, who she is
talking to, how long she has left, and per-topic cooldowns. `ChatDirector` owns
the decisions involving more than two pets: which pair, the round-robin
introduction, ending everything.

A chat can be started by the user (or the panel), by two characters brushing
past each other, or spontaneously. It can also be started by a computer state,
by giving a tag a `chat_topics` block - opt-in per tag, and nothing happens
without one.

## Tests

```
python -m unittest discover -s dialogue -p "test_*.py" -t .
```

Every input is injectable - the foreground record, idle seconds, both clocks,
the system probes, the rules - so the whole tag sequence runs on any platform,
including one with no Windows and no `psutil`. There are also tests asserting
the privacy rules, the sample timing, and that the shipped data files stay
consistent with the code.