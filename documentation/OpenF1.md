# OpenF1 API Documentation

Reference for the [OpenF1](https://openf1.org/) Formula 1 data API —
`api.openf1.org/v1` — timing, telemetry, results and race-control data sourced
from the official F1 live-timing service and served as clean JSON arrays.
Verified against live traffic (probed 2026-06-05).

> **No auth.** Every endpoint here is public and needs no key. Historical data
> (2023→) is free; only true real-time streaming requires a paid OpenF1 plan, but
> the REST surface below works without one. The provider ships `auth: none`.

## Scoping model

Almost every feed is filtered by one of:

- **`session_key`** — one session: a Practice / Qualifying / Sprint / Race.
  Accepts an integer key **or the literal `latest`** (current / most-recent session).
- **`meeting_key`** — one Grand Prix *weekend* (groups its sessions). Also accepts
  `latest`.
- **`driver_number`** — the car number (`1`, `44`, `81`, …).

Discover keys with `openf1_sessions` / `openf1_meetings` first, then pass them to
the timing / telemetry / results feeds. Every response is a **top-level JSON array**.

> **Advanced filtering.** The live API also accepts comparison operators appended in
> the raw query string — `date>=2023-09-15`, `speed>=320`, `lap_number<10`. The typed
> tools here expose equality filters (which cover the common case); for operator
> windows, hit the documented REST endpoint directly. This matters most for the two
> high-frequency telemetry feeds.

## Reference — group `openf1.reference`

| Tool | Path | Capability |
|---|---|---|
| `openf1_meetings` | `/meetings?year=&country_name=` | — (Grand Prix weekends) |
| `openf1_sessions` | `/sessions?year=&session_name=` | `sport.fixtures_by_date` |
| `openf1_drivers` | `/drivers?session_key=` | `ref.players` |

## Results — group `openf1.results`

| Tool | Path | Capability |
|---|---|---|
| `openf1_session_result` | `/session_result?session_key=` | `stats.player_match` (final classification) |
| `openf1_starting_grid` | `/starting_grid?session_key=` | — (sparse; 404s when no grid published) |
| `openf1_championship_drivers` | `/championship_drivers?session_key=` | `stats.ladder` |
| `openf1_championship_teams` | `/championship_teams?session_key=` | `stats.ladder` |
| `openf1_overtakes` | `/overtakes?session_key=` | `stats.play_by_play` |

## Timing — group `openf1.timing`

| Tool | Path | Capability |
|---|---|---|
| `openf1_laps` | `/laps?session_key=&driver_number=` | `stats.advanced_metrics` (sector + speed-trap) |
| `openf1_pit` | `/pit?session_key=` | — (pit-stop durations) |
| `openf1_stints` | `/stints?session_key=&driver_number=` | — (tyre compound + age) |
| `openf1_intervals` | `/intervals?session_key=&driver_number=` | `sport.in_play` (gap to leader / interval) |
| `openf1_position` | `/position?session_key=&driver_number=` | `sport.in_play` (track position over time) |

## Telemetry — group `openf1.telemetry`

| Tool | Path | Capability |
|---|---|---|
| `openf1_car_data` | `/car_data?session_key=&driver_number=` | `stats.advanced_metrics` |
| `openf1_location` | `/location?session_key=&driver_number=` | `stats.advanced_metrics` |

> **High volume.** Telemetry is sampled at ~3.7 Hz, so one driver's `car_data` for a
> race can be **tens of thousands of rows** (~35 k / ~5 MB observed). Both tools
> therefore require `session_key` **and** `driver_number`. To window further, use the
> `date>=` / `date<=` operators on the raw API.

## Live — group `openf1.live`

| Tool | Path | Capability |
|---|---|---|
| `openf1_race_control` | `/race_control?session_key=&flag=` | `sport.commentary` (flags, SC, incidents) |
| `openf1_team_radio` | `/team_radio?session_key=&driver_number=` | `sport.live_audio` (radio recording URLs) |
| `openf1_weather` | `/weather?session_key=` | — (air/track temp, wind, rainfall) |

## Cross-provider comparison

The F1 feeds reuse the shared capability tags, so they line up with the other
providers via `list_tools_by_capability`:

- **`stats.ladder`** → `openf1_championship_drivers` / `openf1_championship_teams`
  sit alongside the AFL ladder and other standings feeds.
- **`sport.live_audio`** → `openf1_team_radio` joins the AFL audio feed (this tag is
  no longer single-provider).
- **`ref.players`** → `openf1_drivers` composes with the AFL / NBA / Data Golf player
  catalogues.
- **`sport.fixtures_by_date`** → `openf1_sessions` is the F1 schedule next to the
  other leagues' fixtures.
- **`stats.advanced_metrics`** / **`sport.in_play`** / **`sport.commentary`** /
  **`stats.play_by_play`** → lap timing, telemetry, live gaps, race-control messages
  and overtakes slot into the same tags as the equivalent feeds elsewhere.

## Notes

- **Source.** OpenF1 ingests the official F1 live-timing data and re-publishes it; we
  read OpenF1's normalised REST API directly (not the `openf1` Python package).
- **Empty vs 404.** Most feeds return `[]` for an over-narrow filter; a few (notably
  `starting_grid`) return a `404 No results found` when a session simply has no data
  for that feed.
- **`latest`.** Pass `session_key=latest` / `meeting_key=latest` to follow the live or
  most-recent session without first looking up a key.
