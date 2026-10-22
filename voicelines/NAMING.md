# Voice line naming scheme

The files in `data/` are the raw wikitext of each student's
`https://bluearchive.wiki/wiki/<Student>/audio` page. Every table row names one
voice line and links its audio file(s):

```
| LogIn_1
| [[File:Iroha_LogIn_1.ogg]]
```

The wiki's **Name** column is the audio file name minus the student prefix, and
the audio file names follow one scheme across all students:

```
<Student>_<Key>[_<n>][_<part>].ogg
```

## `<Student>`

The wiki page title, with spaces replaced by underscores:

| Page title     | Audio prefix        |
| -------------- | ------------------- |
| `Iroha`        | `Iroha_`            |
| `Hina (Dress)` | `Hina_(Dress)_`     |
| `Momoi (Maid)` | `Momoi_(Maid)_`     |

## `<Key>`

One fixed token per line type. The same keys recur on every student's page.

### Normal lines

| Key | Meaning |
| --- | --- |
| `Title` | Title-screen line |
| `Gachaget` | Obtained from the gacha |
| `LogIn` | Login greeting |
| `Lobby` | Lobby tap |
| `Cafe_monolog` | Cafe monologue |
| `Cafe_Act` | Cafe interaction |
| `Season_Birthday` | Her own birthday |
| `Season_Birthday_Player` | Sensei's birthday |
| `Season_NewYear` | New Year |
| `Season_Xmas` | Christmas |
| `Season_Halloween` | Halloween |
| `ExWeapon_Get` | Unique weapon obtained |

### Memorial lobby

| Key | Meaning |
| --- | --- |
| `MemorialLobby` | Memorial-lobby lines (numbered; some students start at `_0`) |

### Event lines

| Key | Meaning |
| --- | --- |
| `EventLogin` | Event login |
| `EventLogin_Season` | Seasonal event login |
| `EventLogin_Season_End` | Seasonal event ended |
| `EventLobby` | Event lobby |
| `EventShop`, `EventShop_Login`, `EventShop_Buy`, `EventShop_End` | Event shop |
| `EventMission`, `EventMission_Login`, `EventMission_Get`, `EventMission_Day_End` | Event missions |
| `EventTreasure`, `EventTreasure_Login`, `EventTreasure_Find`, `EventTreasure_Get`, `EventTreasure_End`, `EventTreasure_RoundRenewal` | Event treasure hunt |
| `ST<code>_MiniGame_<Action>` | Mini-game lines, e.g. `ST0004_MiniGame_Start`, `ST0004_MiniGame_Select`, `ST0004_MiniGame_Shout`, `ST0004_MiniGame_GeasGet` |

### Tactics and growth

| Key | Meaning |
| --- | --- |
| `Formation_Select`, `Formation_In` | Formation |
| `Tactic_In`, `Tactic_Victory`, `Tactic_Defeat` | Tactics (map) start / win / lose |
| `ExSkill`, `ExSkill_Level` | EX skill use / level-up |
| `Growup` | Stat growth |
| `Relationship_Up` | Bond level-up |
| `Battle_In` | Battle start |
| `Battle_Move` | Unit moved |
| `Battle_Shout` | Attack shout |
| `Battle_Damage` | Taking damage |
| `Battle_Defense` | Guarding |
| `Battle_Recovery` | Healing |
| `Battle_BuffSelf` / `Battle_Buffed` | Self buff / receiving a buff |
| `Battle_Covered` | Taking cover |
| `Battle_Victory`, `Battle_Retire`, `Battle_Supply` | Victory / retreat / supply |
| `Battle_TacticalAction` | Tactical action |
| `Battle_Entrance` / `Battle_TSA` | Battle entrance / Tactical Support Action (alternates: `Entrance` is used by Wakamo, `_TSA` by e.g. Arisu, Azusa, Fuuka, Hina, Mutsuki) |

## `_<n>` and `_<part>`

- Numbered variants are 1-indexed: `Lobby_1` … `Lobby_5`.
- A long line split into several audio files gets a second number: the wiki
  Name is `MemorialLobby_2` while the files are `MemorialLobby_2_1.ogg` and
  `MemorialLobby_2_2.ogg` (same for `EventLobby`, `EventShop`,
  `EventTreasure`, `Season_Birthday_1_1`, …). A row may therefore link several
  files separated by `<br>`.
- A few lines use a letter instead of a number: `Cafe_Act_3_a`,
  `GL_Battle_Buffed_1_b`.

## `GL_` (Seia)

Seia has a separate Global voice pack, marked by a `GL_` prefix after the
student name: `Seia_GL_Title.ogg` next to the Japanese `Seia_Title.ogg`. Her
table rows list both files, so the same Name maps to two audio files.

## Section headers

Each page groups the rows under these headers, which correspond to the key
groups above:

- `=Normal lines=`
- `=Memorial lobby=`
- `=Event lines=` (occasionally `=Extra event lines=`)
- `=Tactics and growth=`
