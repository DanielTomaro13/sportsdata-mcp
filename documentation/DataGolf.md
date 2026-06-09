# Data Golf API Documentation

Reference for the [Data Golf](https://datagolf.com/api-access) feeds —
`feeds.datagolf.com` — golf analytics, model predictions and cross-book betting
odds. Verified against live traffic (probed 2026-06-05).

> **Auth (your key, kept secret).** Every endpoint authenticates with a personal
> `?key=` query parameter tied to a paid subscription. This provider sources it
> from the **`DATAGOLF_KEY`** env var via the `static_query` auth scheme — the key
> is **never** stored in the spec or committed. Set it before running:
> ```bash
> export DATAGOLF_KEY=your_key_here
> ```
> (Or put it in the config `secrets` block keyed `DATAGOLF_KEY`.) A 403/permission
> error means your plan doesn't include that particular feed (some are higher-tier).

## Conventions

- **Tours:** `pga`, `euro` (DP World), `kft` (Korn Ferry), `alt`, `liv`.
- **Player id:** `dg_id` (Data Golf's stable id); `get-player-list` is the catalogue.
- **`odds_format`:** `decimal` / `american` / `fraction` / `percent`.
- Most endpoints accept `file_format=json` (carried as a default).

## General — group `datagolf.general`

| Tool | Path | Capability |
|---|---|---|
| `datagolf_player_list` | `/get-player-list` | `ref.players` |
| `datagolf_schedule` | `/get-schedule?tour=` | `ref.seasons` |
| `datagolf_field_updates` | `/field-updates?tour=` | `sport.match_detail` (current event field + tee times) |

## Predictions + stats — group `datagolf.predictions`

| Tool | Path | Capability |
|---|---|---|
| `datagolf_rankings` | `/preds/get-dg-rankings` | — (DG rank, skill estimate, OWGR rank) |
| `datagolf_pre_tournament` | `/preds/pre-tournament?tour=` | — (win / top-N / make-cut probabilities) |
| `datagolf_pre_tournament_archive` | `/preds/pre-tournament-archive?event_id=&year=` | — (historical snapshots of the pre-tournament model) |
| `datagolf_in_play` | `/preds/in-play?tour=` | `sport.in_play` (live win probabilities) |
| `datagolf_skill_ratings` | `/preds/skill-ratings` | `stats.advanced_metrics` (strokes-gained) |
| `datagolf_approach_skill` | `/preds/approach-skill?period=` | `stats.advanced_metrics` (SG/proximity/GIR by yardage + lie bucket) |
| `datagolf_player_decompositions` | `/preds/player-decompositions?tour=` | `stats.advanced_metrics` (player-by-player SG breakdown of the model) |
| `datagolf_live_strokes_gained` | `/preds/live-strokes-gained?sg=` | `stats.advanced_metrics`, `sport.in_play` (live SG, raw or model-relative; PGA only) |
| `datagolf_live_tournament_stats` | `/preds/live-tournament-stats?stats=&round=` | `stats.advanced_metrics`, `stats.player_match` |
| `datagolf_live_hole_stats` | `/preds/live-hole-stats?tour=` | `stats.advanced_metrics` (live hole-by-hole scoring distributions) |
| `datagolf_fantasy_projections` | `/preds/fantasy-projection-defaults?tour=&site=` | `stats.fantasy_projections` (DFS points projections) |

## Betting — group `datagolf.betting`

| Tool | Path | Capability |
|---|---|---|
| `datagolf_outrights` | `/betting-tools/outrights?tour=&market=` | `sport.event_markets`, `sport.prices` |
| `datagolf_matchups` | `/betting-tools/matchups?tour=&market=` | `sport.event_markets`, `sport.prices` |
| `datagolf_matchups_all_pairings` | `/betting-tools/matchups-all-pairings?tour=` | `sport.event_markets`, `sport.prices` |

`datagolf_outrights` returns the current event's **win / top-5/10/20 / make-cut**
odds across ~13 sportsbooks (`bet365`, `pinnacle`, `draftkings`, `fanduel`,
`betmgm`, `caesars`, …) **plus Data Golf's own model line** — so you can compare a
model price against the market in one call. `datagolf_matchups` does the same for
tournament / round / 3-ball matchups, and `datagolf_matchups_all_pairings` returns
Data Golf's model odds for **every** possible player-vs-player pairing in the field.

## Historical — group `datagolf.historical`

Archived raw scoring, bookmaker odds and DFS results for past events. The two
`*event_list` feeds are catalogues: call them first to get the `event_id` + `year`
(`calendar_year`) to pass to the detail feeds.

| Tool | Path | Capability |
|---|---|---|
| `datagolf_hist_event_list` | `/historical-raw-data/event-list?tour=` | — (catalogue of events with raw round data) |
| `datagolf_hist_rounds` | `/historical-raw-data/rounds?event_id=&year=` | `stats.player_match` (round-by-round SG per player) |
| `datagolf_hist_results_event_list` | `/historical-event-data/event-list?tour=` | — (catalogue of events with results data; PGA only) |
| `datagolf_hist_results` | `/historical-event-data/events?event_id=&year=` | — (finishes, earnings, FedExCup + DG points; PGA only) |
| `datagolf_hist_odds_event_list` | `/historical-odds/event-list?tour=` | — (catalogue of events with archived odds) |
| `datagolf_hist_outrights` | `/historical-odds/outrights?event_id=&year=&market=&book=` | — (opening/closing outright odds from one book) |
| `datagolf_hist_matchups` | `/historical-odds/matchups?event_id=&year=&book=` | — (historical matchup / 3-ball odds from one book) |
| `datagolf_hist_dfs_event_list` | `/historical-dfs-data/event-list?site=` | — (catalogue of events with DFS data; keys off `site`, not `tour`) |
| `datagolf_hist_dfs_points` | `/historical-dfs-data/points?site=&event_id=&year=` | `stats.fantasy_projections` (actual DFS points + salary + ownership) |

> **Event ids are per-tour and per-feed.** An `event_id`/`year` from
> `datagolf_hist_event_list` (raw data) is not guaranteed to exist in the odds or
> DFS archives, and not every event has outright odds for every market/book. A
> `400 … not available in <year>` simply means that combination isn't archived —
> pick another from the matching `*event_list` catalogue.

## Cross-provider comparison

Golf odds slot into the same capability tags as the other books:

- `sport.prices` / `sport.event_markets` → `datagolf_outrights` carries Pinnacle,
  FanDuel and others inline, and composes with the live `pinnacle_matchup_markets`,
  `betfair_market_prices`, `tab_match`, etc. via `list_tools_by_capability`.
- `stats.advanced_metrics` → `datagolf_skill_ratings` / `datagolf_live_tournament_stats`
  alongside the NBA stats surface.

## Notes

- **Every documented Data Golf feed is modelled** (26 tools across the four groups
  above), including the higher-tier archived predictions, decompositions, approach
  skill, live strokes-gained, DFS projections, historical raw data, historical
  event results, historical odds and historical DFS. A 403/permission error on any
  of them means your plan doesn't cover that feed. (The approach-skill,
  live-strokes-gained and historical-event-data tools were added from the official
  endpoint docs but not yet shape-verified live — needs a DATAGOLF_KEY.)
- `betting-tools/matchups` returns an empty `match_list` when the book hasn't posted
  that market for the current event.
