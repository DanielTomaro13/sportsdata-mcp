# Jolpica F1 API Documentation

Reference for **`api.jolpi.ca/ergast/f1`** — the community-maintained successor to
**Ergast**, the canonical open F1 dataset since 2009. Ergast was deprecated at the end
of 2024; Jolpica took it over with a drop-in compatible API, so every Ergast tutorial
and query still applies. Probed live 2026-08-10.

> **This does not overlap `openf1`.** They cover disjoint eras and granularities:
>
> | | `openf1` | `jolpicaf1` |
> |---|---|---|
> | Era | 2023 → | **1950 →** |
> | Granularity | Live telemetry, car by car, sub-second | Session results, laps, pit stops |
> | Answers | "What lap is Verstappen on right now?" | "Who won the 1976 Japanese GP?" |
>
> Neither can answer the other's question. Enable both.

## Contents

- [The double envelope](#the-double-envelope)
- [Everything is a string](#everything-is-a-string)
- [Pagination will silently truncate you](#pagination-will-silently-truncate-you)
- [The id model](#the-id-model)
- [Tools](#tools)
- [Gotchas](#gotchas)
- [Cross-provider comparison](#cross-provider-comparison)

## The double envelope

This is the one thing that trips every new caller. Responses are wrapped twice, and
**the inner table name changes with the endpoint**:

```jsonc
// races, results, qualifying, sprint, laps, pitstops
{"MRData": {"total": "24", "RaceTable": {"Races": [ … ]}}}

// standings — note the EXTRA StandingsLists layer
{"MRData": {"StandingsTable": {"StandingsLists": [{"DriverStandings": [ … ]}]}}}

// reference data
{"MRData": {"DriverTable":      {"Drivers":      [ … ]}}}
{"MRData": {"ConstructorTable": {"Constructors": [ … ]}}}
{"MRData": {"CircuitTable":     {"Circuits":     [ … ]}}}
{"MRData": {"SeasonTable":      {"Seasons":      [ … ]}}}
```

So the path is always `MRData.<Something>Table.<Something>s` — never a flat list. The
standings endpoints add one more level (`StandingsLists[0].DriverStandings`) because a
single request can return standings after several rounds.

Also note: `format=json` is sent by default on every tool here. **The API defaults to
XML** — omit it and you get a document this engine can't decode.

## Everything is a string

Positions, points, lap numbers, grid slots — all strings:

```jsonc
{"position": "1", "points": "25", "grid": "2", "laps": "57"}
```

Sorting on `position` lexically puts `"10"` before `"2"`. Cast before you compare.
Times are strings too, in their own formats: `"1:29.347"` for a lap, `"+5.234"` for a
gap, `"23.2"` for a pit-stop duration.

## Pagination will silently truncate you

Ergast pagination: `limit` (default **30**, max **100**) and `offset`, with the real
count in `MRData.total`.

The trap is `jolpicaf1_laps`. A full race is thousands of timing rows, so a default
call returns the first 30 and looks complete. **Always read `MRData.total`** and page
if it exceeds what you received.

## The id model

```
jolpicaf1_seasons            → season ("2024")
   └─ jolpicaf1_races(season)          → round ("1".."24")
         ├─ jolpicaf1_results(season, round)
         ├─ jolpicaf1_qualifying(season, round)
         ├─ jolpicaf1_sprint(season, round)      — empty when no sprint that weekend
         ├─ jolpicaf1_laps(season, round)
         └─ jolpicaf1_pitstops(season, round)
jolpicaf1_drivers(season)     → driverId ("max_verstappen")
jolpicaf1_constructors(season)→ constructorId ("red_bull")
```

`season` accepts **`current`**, and `round` accepts **`last`** — so "the most recent
race result" is `season=current, round=last` without looking anything up.

## Tools

### `jolpicaf1.reference`

| Tool | Returns | Capability |
|---|---|---|
| `jolpicaf1_seasons` | Every season 1950 → | `ref.seasons` |
| `jolpicaf1_drivers` | Drivers, all-time or per season | `ref.players` |
| `jolpicaf1_constructors` | Teams | `ref.teams` |
| `jolpicaf1_circuits` | Circuits with coordinates | `ref.venues` |

### `jolpicaf1.schedule`

| Tool | Returns | Capability |
|---|---|---|
| `jolpicaf1_races` | A season's calendar, with per-session times from 2021 | `sport.fixtures_by_date` |

### `jolpicaf1.results`

| Tool | Returns | Capability |
|---|---|---|
| `jolpicaf1_results` | Finishing order, grid, status, points, fastest lap | `sport.match_detail`, `stats.player_match` |
| `jolpicaf1_qualifying` | Q1/Q2/Q3 times | `sport.match_detail` |
| `jolpicaf1_sprint` | Sprint results (2021 →) | `sport.match_detail` |
| `jolpicaf1_laps` | Lap-by-lap timings — **large, paginate** | `stats.advanced_metrics` |
| `jolpicaf1_pitstops` | Stop lap, clock time, stationary duration | `stats.advanced_metrics` |

### `jolpicaf1.standings`

| Tool | Returns | Capability |
|---|---|---|
| `jolpicaf1_driver_standings` | Drivers' championship | `stats.ladder` |
| `jolpicaf1_constructor_standings` | Constructors' championship | `stats.ladder` |

## Gotchas

| Symptom | Cause |
|---|---|
| **Can't find the data in the response** | It's under `MRData.<X>Table.<X>s`. Standings add a `StandingsLists` layer. |
| **Got XML / decode error** | `format=json` was dropped. The API defaults to XML. |
| **`"10"` sorts before `"2"`** | Every numeric field is a string. Cast first. |
| **Laps look truncated** | Default `limit` is 30. Check `MRData.total` and page. |
| **`Races: []` from `sprint`** | That weekend had no sprint. Not an error. |
| **No `Q2`/`Q3` for a driver** | They were eliminated in the earlier segment. |
| **Pre-2021 sessions missing times** | Session-level date/time only exists from 2021; older races carry the race date only. |
| **HTTP 429** | Jolpica is volunteer-run and free. The provider is capped at 3 rps — don't raise it. |

## Cross-provider comparison

- `stats.ladder` → both standings tools alongside `nhl_standings`, `mlb_standings`,
  `premierleague`, `laliga`, `seriea`, `afl_ladders`, `squiggle_standings`.
- `sport.fixtures_by_date` → `jolpicaf1_races` alongside `openf1_sessions`. The natural
  pairing: Jolpica for the calendar and historical results, OpenF1 for what's happening
  in the current session.
- `ref.players` / `ref.teams` → drivers and constructors. Ids are Ergast-style slugs
  (`max_verstappen`, `red_bull`) and do **not** match OpenF1's numeric driver numbers —
  join on surname plus season.
- Betting composition: pull a season's results here to build a form line, then price
  the next race against `sportsbet` / `pinnacle` futures markets.

## Not modelled

- **`/status`** — the finishing-status code table (`Finished`, `+1 Lap`, `Collision`).
  Codes already appear inline in results, so the lookup adds little.
- **Driver/constructor-filtered result paths** (`/drivers/{id}/results/`) — the same
  data reachable by filtering a season's results client-side.
- **XML output** — this engine decodes JSON.
