# OpenLigaDB API Documentation

Reference for **`api.openligadb.de`** — community-maintained German football data.
Free, keyless, no rate limit published. Probed live 2026-08-10.

Fills the hole in big-five coverage: the server already carries the Premier League, La
Liga and Serie A from official sources, but had nothing for the **Bundesliga**.

> **Crowd-maintained, like a wiki.** Results are entered by volunteers. Top-flight
> Bundesliga data is reliable and quick; obscure competitions in the long tail can lag
> or have gaps. Treat it accordingly — this is not an official federation feed.

## Three conventions to know

**1. League shortcut + season year address everything.** `bl1` is the 1. Bundesliga,
`bl2` the second tier, `bl3` the third, `dfb` the cup — plus a long tail (819
league-seasons in total). Call `openligadb_leagues` to discover valid shortcuts.

**A wrong shortcut returns HTTP 404**, which surfaces as a clean tool error rather than
silently empty data (verified live).

**2. Season is the STARTING year.** The 2024/25 season is `2024`.

**3. A matchday is called a "group".** `getavailablegroups` returns matchdays, and
`groupOrderID` is the matchday number. German labels leak through in the data:
`groupName` reads `"1. Spieltag"`.

## The id model

```
openligadb_leagues                    → leagueShortcut ("bl1") + leagueSeason ("2024")
   ├─ openligadb_teams(league, season)      → teamId
   ├─ openligadb_matchdays(league, season)  → groupOrderID (matchday number)
   │     └─ openligadb_matchday_matches(league, season, matchday) → matchID
   │             └─ openligadb_match(matchId)
   ├─ openligadb_current_matchday(league)   → which matchday is live now
   └─ openligadb_table(league, season)
```

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `openligadb_leagues` | Every competition + season (~819) | `sport.competitions_list` |
| `openligadb_teams` | Clubs in a season | `ref.teams` |
| `openligadb_matchdays` | Matchdays with their date windows | — |
| `openligadb_current_matchday` | Which matchday is current (single object) | — |
| `openligadb_season_matches` | Every match in a season (**~550 KB**) | `sport.fixtures_by_date`, `sport.match_score` |
| `openligadb_matchday_matches` | One matchday (~9 matches) — the everyday call | `sport.fixtures_by_date`, `sport.match_score` |
| `openligadb_match` | One match with goals and scorers | `sport.match_detail` |
| `openligadb_table` | League table | `stats.ladder` |

## Reading a result

Scores are **not** top-level fields. They live in `matchResults`, which holds *two*
entries per finished match:

```jsonc
"matchResults": [
  {"resultName": "Halbzeit",    "pointsTeam1": 1, "pointsTeam2": 0},  // half time
  {"resultName": "Endergebnis", "pointsTeam1": 2, "pointsTeam2": 1}   // full time
]
```

Taking `matchResults[0]` gives you the **half-time** score in many cases. Select on
`resultName == "Endergebnis"` (or the highest `resultOrderID`) for the final result.

`goals[]` carries the scoring sequence with `matchMinute`, `goalGetterName`,
`isPenalty` and `isOwnGoal`.

In the table, `goals` means **scored** and `opponentGoals` means **conceded** — an easy
misread when both appear on the same object.

## Gotchas

| Symptom | Cause |
|---|---|
| **Empty array, HTTP 200** | Wrong league shortcut or season. Not a 404 — check `openligadb_leagues`. |
| **Wrong scores** | You read `matchResults[0]`, which is often half time. Filter on `Endergebnis`. |
| **Season looks off by one** | Season is the STARTING year: 2024/25 → `2024`. |
| **"group" makes no sense** | It means matchday (Spieltag). |
| **~550 KB response** | A whole season. Use `openligadb_matchday_matches`. |
| **Sparse data in a minor competition** | Volunteer-entered; the long tail is patchy. |

## Cross-provider comparison

- `stats.ladder` → `openligadb_table` alongside `premierleague`, `laliga`, `seriea`,
  and now `nhl_standings`, `squiggle_standings`, the F1 championships.
- `sport.fixtures_by_date` / `sport.match_score` → the two match tools alongside every
  other league feed, so a "what's on in football today" question spans four countries.
- Bookmaker composition: the AU books price the Bundesliga, so a matchday's fixtures
  here line up against `sportsbet` / `pinnacle` markets for the same games.
- Team ids are OpenLigaDB's own and don't join to ESPN or the official league feeds —
  match on club name.

## Not modelled

- **`/getgoalgetters/{league}/{season}`** — top scorers. Useful, but thin next to the
  match data; add if a scoring-race question comes up.
- **`/getlastchangedate`** — a cache-invalidation helper, not data.
- **Write endpoints** — OpenLigaDB accepts crowd-sourced result submissions. Out of
  scope for a read-only server.
