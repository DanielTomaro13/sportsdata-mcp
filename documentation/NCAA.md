# NCAA API Documentation

Reference for **`ncaa-api.henrygd.me`** — a community service that normalises NCAA.com's
own JSON feeds into a stable REST shape. No key. Probed live 2026-08-10.

## What this adds over `espn`

The [ESPN provider](ESPN.md) already returns college scoreboards — `football/college-football`
works today and returned 99 events when tested. So why carry this?

**The NCAA's own polls and conference standings**, normalised the same way across every
college sport. ESPN's slug-parametric dispatchers don't give you the AP and coaches
polls in a consistent shape, and college sport is poll-driven in a way no other
competition here is.

If you only need college scores, ESPN covers it. Enable this for **rankings and
standings**.

> **Third-party dependency.** This is one developer's mirror of NCAA.com, not an NCAA
> service. It can go away or fall behind in a way an official feed wouldn't. The
> nightly drift check will catch it if it does.

## The path is the query

There are no query parameters. Sport, division and report type are all path segments,
mirroring NCAA.com's URLs:

```
/scoreboard/{sport}/{division}
/standings/{sport}/{division}
/rankings/{sport}/{division}/{poll}
```

**Sport slugs are hyphenated and gendered**: `football`, `basketball-men`,
`basketball-women`, `ice-hockey-men`, `lacrosse-men`, `soccer-women`, …

**Divisions**: `fbs` / `fcs` for football, `d1` / `d2` / `d3` for everything else.

## The response shapes are inconsistent — by design of the source

Three tools, three different conventions. This is inherited from NCAA.com and worth
knowing before you parse:

**Scoreboard** wraps each entry in a single-key object:

```jsonc
{"games": [ {"game": {"gameID": …, "home": {…}, "away": {…}}} ]}
```

Note `games[i].game`, not `games[i]`.

**Standings** is **grouped by conference** — `data[]` is one entry *per conference*,
each holding its own `standings` list. The inner column names are human-readable with
spaces, and vary by sport:

```jsonc
{"data": [
  {"conference": "ACC",
   "standings": [
     {"School": "Virginia", "Conference W": "7", "Conference L": "1",
      "Overall W": "11", "Overall L": "3", "Overall STREAK": "Won 1"}
   ]}
]}
```

So a flat list of schools requires flattening one level — reading `data[0]` gets you a
conference, not a team.

**Rankings** uses **UPPERCASE** keys:

```jsonc
{"data": [{"RANK": "1", "SCHOOL": "Ohio St.", "POINTS": "1550", "PREVIOUS": "1", "RECORD": "13-0"}]}
```

Values are strings throughout, including ranks and win counts.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `ncaa_scoreboard` | Games with score, state, clock, conferences | `sport.fixtures_by_date`, `sport.match_score`, `sport.in_play` |
| `ncaa_standings` | Conference standings | `stats.ladder` |
| `ncaa_rankings` | AP / coaches poll | `sport.rankings` |

## Gotchas

| Symptom | Cause |
|---|---|
| **`games[0]` has one key** | Each entry wraps the real object under `game`. |
| **Standings keys have spaces** | `"Conference W"`, `"Overall L"` — and they vary by sport. |
| **Rankings keys are uppercase** | `RANK`, `SCHOOL` — unlike standings. |
| **`"10"` sorts before `"2"`** | Every value is a string. |
| **Error on a sport slug** | Slugs are hyphenated and gendered: `basketball-men`, not `basketball`. |
| **Poll not found** | Poll availability varies by sport; `associated-press` is the safest. |
| **HTTP 429** | The host asks for ≤5 req/s; this provider is capped at 3. |
| **Out-of-season emptiness** | College seasons are short. Empty is normal in the off-season. |

## Cross-provider comparison

- `sport.rankings` → `ncaa_rankings` alongside `lichess_leaderboard` and
  `chesscom_leaderboards`. This un-flagged `sport.rankings` from single-provider.
- `stats.ladder` → `ncaa_standings` alongside every league table in the catalogue.
- `sport.fixtures_by_date` / `sport.in_play` → `ncaa_scoreboard` alongside ESPN's
  college scoreboard. ESPN is the richer source for a single game; this is better for
  a normalised cross-sport sweep.
- College football and basketball are heavily priced by US books — `fanduel` and
  `pinnacle` both carry them, so a ranked matchup here pairs with a market there.

## Not modelled

- **`/game/{id}` detail endpoints** — available on the upstream, but ESPN's college
  coverage gives richer single-game data.
- **Stats leaders** — exist per sport with inconsistent shapes; low value relative to
  the effort of modelling each.
