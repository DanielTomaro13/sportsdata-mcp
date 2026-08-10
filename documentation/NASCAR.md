# NASCAR API Documentation

Reference for **`cf.nascar.com`** — the public CDN feeds behind nascar.com. All three
national series, no key, no auth. Probed live 2026-08-10.

## These are files, not an API

The feeds are **static JSON on a CDN**, which has two consequences:

1. **There are no query parameters.** Season, series and race id are all path segments,
   so you must know them to address a race.
2. **No filtering.** You fetch the whole file and filter client-side. `race_list_basic`
   is ~430 KB for a season.

The upside is that they're fast, cache-friendly and don't rate-limit aggressively.

## The three series are numbered

`1` = Cup, `2` = Xfinity, `3` = Craftsman Truck. The number appears both as a response
key (`series_1`) and as a path segment in the weekend feed.

## The id chain

```
nascar_race_list(season)  → {series_1: [{race_id, series_id, …}], series_2: […], series_3: […]}
     └─ nascar_weekend_feed(season, series, race_id)
```

Note the race list is **keyed by series**, so "every race in 2024" means walking three
arrays, not one.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `nascar_race_list` | Every race in a season across all series, with winner, track, cautions, lead changes, average speed, margin of victory (~430 KB) | `sport.fixtures_by_date`, `sport.season_summary` |
| `nascar_weekend_feed` | One weekend: finishing order with laps led, points and status, plus every practice and qualifying run | `sport.match_detail`, `stats.player_match` |

`race_list_basic` is unusually rich for a schedule endpoint — it carries the *result*
summary too (winner, cautions, lead changes, attendance), so many questions are
answerable without the weekend feed at all.

The weekend feed splits into `weekend_race` (the race itself) and `weekend_runs`
(practice and qualifying sessions).

**`results` is not sorted, and it includes drivers who never started.** Entries with
`finishing_position: 0` are DNQ/DNS. On the 2024 Daytona 500 the first two array
entries are non-qualifiers and the winner sits third:

```jsonc
[{"finishing_position": 0, "driver_fullname": "BJ McLeod"},     // did not qualify
 {"finishing_position": 0, "driver_fullname": "JJ Yeley"},      // did not qualify
 {"finishing_position": 1, "driver_fullname": "William Byron"}] // actual winner
```

Always select on `finishing_position == 1` rather than taking the first element.

## Gotchas

| Symptom | Cause |
|---|---|
| **404 on a weekend feed** | Wrong `series` for that `race_id` — the series number must match the one on the race. |
| **"Where are the query params?"** | There are none; everything is in the path. |
| **~430 KB response** | The whole season across three series. Expected. |
| **Missing races for a future season** | The file only exists once NASCAR publishes it. |
| **`results[0]` is not the winner** | The array is unsorted and includes non-starters with `finishing_position: 0` (DNQ/DNS). On the 2024 Daytona 500 the first two rows never raced. Select `finishing_position == 1`. |
| **Driver ids without names** | Names arrive in the weekend feed; the 1.4 MB driver catalogue is deliberately not exposed. |

## Cross-provider comparison

- `sport.fixtures_by_date` → `nascar_race_list` alongside `jolpicaf1_races`,
  `motogp_events` and `formulae_races`; the `motorsport` preset enables all four.
- `stats.player_match` → weekend-feed results alongside F1 and MotoGP classifications.
- NASCAR is priced by US books, so a race here pairs with `fanduel` / `pinnacle`
  futures and race markets.
- Driver ids are NASCAR's own and don't join elsewhere.

## Not modelled

- **`/cacher/drivers.json`** — ~1.4 MB of every driver ever. Not a sensible payload for
  a model, and the weekend feed already names the drivers in a race.
- **`live_feed.json`** — live lap-by-lap during a race. Only meaningful while a race is
  running, so it can't be contract-tested; worth adding if live coverage matters.
- **Loop stats / pit stop feeds** — separate paths with per-race availability.
