# Firecrawl Alexandria: `api.firecrawl.dev` (sports and fantasy data tools, BYO key)

[Firecrawl Alexandria](https://www.firecrawl.dev/alexandria)
([docs](https://docs.firecrawl.dev/features/alexandria))
is a catalogue of structured data tools for agents behind one Firecrawl API key. Its sports category covers fantasy rankings and
projections (CBS Sports, Draft Sharks, FFToday, FantasyData, Fantasy Football Calculator,
StartWho), the NFL.com league feeds, MLB Baseball Savant Statcast data, Yahoo public
fantasy leagues, World Table Tennis, and tools for ESPN, Sleeper and Polymarket.

Provider id `firecrawl_alexandria`, 6 tools across three groups. Shapes probed live with a real key
on 2026-10-27, so this provider ships `shapes_verified: true`.

## Why it is here

Several of these sources already have a native provider in this repo (`espn`, `sleeper`, `polymarket`),
and for those the native provider is the better choice. What Firecrawl Alexandria adds are sources
this server doesn't carry directly: projections and rankings from StartWho, Draft Sharks,
CBS Sports and FFToday, NFL.com's official practice-participation report, and Baseball Savant
leaderboards (expected stats, exit velocity, sprint speed, outs above average, pitch
arsenals). The `player_id` on the Statcast tools is the MLBAM id, so it joins straight onto the
`mlb` provider.

## Auth and cost

`Authorization: Bearer <key>` from `FIRECRAWL_API_KEY`, declared `optional` so a missing key never
breaks startup. Every tool refuses without it, and a bad key gets HTTP 401. Get a key at
[firecrawl.dev](https://www.firecrawl.dev/).

- Discovery (`firecrawl_alexandria_search`) and catalogue browsing (`firecrawl_alexandria_find_tools`) are free.
- Running a tool bills that tool's `creditsCost`, which `firecrawl_alexandria_find_tools` shows before you call
  it and every response repeats. On 2026-10-27 each sports tool cost 5 credits and the
  Polymarket tools cost 0.
- Some providers need an org admin to accept their terms first; those calls answer with
  `THIRD_PARTY_DATA_TERMS_REQUIRED` and a URL.

```bash
export FIRECRAWL_API_KEY=fc-...
sportsdata-mcp serve --groups "free,firecrawl_alexandria.*"
```

## Tools

| Tool | Group | Calls | Capabilities |
|---|---|---|---|
| `firecrawl_alexandria_search` | `firecrawl_alexandria.discovery` | `POST /v2/search` with `sources: ["alexandria"]` | |
| `firecrawl_alexandria_find_tools` | `firecrawl_alexandria.discovery` | `POST /v2/scrape`, `firecrawl/find-tools` | |
| `firecrawl_alexandria_run` | `firecrawl_alexandria.run` | `POST /v2/scrape`, any provider and capability | |
| `firecrawl_alexandria_fantasy_projections` | `firecrawl_alexandria.sports` | `startwho-com`, `fantasy-sports-rankings/projections` | `stats.fantasy_projections` |
| `firecrawl_alexandria_nfl_injury_report` | `firecrawl_alexandria.sports` | `nfl-com`, `sports-league-data/injury_report` | `sport.injuries` |
| `firecrawl_alexandria_statcast_leaderboard` | `firecrawl_alexandria.sports` | `baseballsavant-mlb-com`, `baseball-statcast/get_leaderboard` | `stats.advanced_metrics`, `stats.leaders_season` |

The three `sports` tools are `firecrawl_alexandria_run` with the provider and capability fixed, so they
carry capability tags and show up in `list_tools_by_capability` beside ESPN, SportsDataIO,
MySportsFeeds and the rest. Everything else in the catalogue goes through `firecrawl_alexandria_run`.

## The id model

1. `firecrawl_alexandria_search` with a plain question (`"NFL injury report"`) returns
   `{provider, capability, description}` rows. Pick by provider and capability rather than by
   position in the list; a short list that carries a `warning` is worth one retry.
2. `firecrawl_alexandria_find_tools` with `providers: ["nfl-com"]` and `expand: ["options"]` returns each
   capability's inputs (`name`, `type`, `about`, `required`, `oneOf`, `min`, `max`) and `creditsCost`.
   `level: "providers"` lists the providers in the sports category instead.
3. `firecrawl_alexandria_run` with that provider, capability and an `options` object runs it.

## Response shape

Every run answers the same envelope; the tool's own payload is `data.alexandria[0].data`:

```
{success, scrape_id, data:{alexandria:[{provider, capability, creditsCost, data:{…}, records, upstreamStatus}], creditsCost}}
```

Shapes recorded on 2026-10-27:

- **StartWho projections:** `{week, week_label, position, scoring, count, players:[{name, team, opponent, game_kickoff_at, projected_points, vegas_percent, bookmaker_points:[…], props:[{prop_type, line, odds, projected_points, bookmakers:[{sportsbook, line, over_odds, under_odds}]}]}]}`.
  Projections are built from sportsbook player props; a week with no published
  projections fails rather than returning an empty list.
- **NFL.com injury report:** `{season, season_type, week, report_date, count, reports:[{player, team, injuries, injury_status, practice_status, practice_days:[{date, status}]}]}`.
  League-wide is about 350 rows in mid-season, so pass `team` when you can.
- **Baseball Savant leaderboard:** `{board, season, columns, count, total, next_cursor, rows:[{player_id, name, metrics:{…}}]}`.
  `metrics` keys are the board's own CSV column names, listed in `columns`; page with `cursor`.

## Things that will bite you

- **An unknown capability is a 404 that lists the provider's valid ones.** An unknown provider
  is a 404 with no list, so check the id with `firecrawl_alexandria_find_tools` and
  `level: "providers"`.
- **A bad key is a 401. A 403 can mean no key was sent or the team lacks access**; read the
  error text in the response rather than assuming a geo-block.
- **A timed-out scrape answers 408.** The spec retries 408, 429 and 5xx twice with backoff.
- **Check each result for an `error` field** before reading its `data`: a provider-level failure
  can arrive inside a successful HTTP response.
- **`sportsdata-mcp doctor` spends credits when the key is set**, because its probes for the
  `run` and `sports` groups execute real tools. Without a key it skips all three groups.
- Every request carries `origin: "sportsdata-mcp"`.

## Cross-provider comparison

| Question | Native provider here | Firecrawl Alexandria |
|---|---|---|
| Fantasy projections | `sportsdataio` (DFS), `espnfantasy`, `fpl` | `firecrawl_alexandria_fantasy_projections`; CBS Sports, FFToday and Draft Sharks via `firecrawl_alexandria_run` |
| NFL injuries | `espn`, `sportsdataio`, `mysportsfeeds` | `firecrawl_alexandria_nfl_injury_report` (official practice participation by day) |
| MLB advanced metrics | `mlb` | `firecrawl_alexandria_statcast_leaderboard` (Statcast boards) |
| Scores, rosters, standings | `espn`, `mlb`, `nba`, `nhl` | Prefer the native provider |
