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
| `datagolf_in_play` | `/preds/in-play?tour=` | `sport.in_play` (live win probabilities) |
| `datagolf_skill_ratings` | `/preds/skill-ratings` | `stats.advanced_metrics` (strokes-gained) |
| `datagolf_live_tournament_stats` | `/preds/live-tournament-stats?stats=&round=` | `stats.advanced_metrics`, `stats.player_match` |

## Betting — group `datagolf.betting`

| Tool | Path | Capability |
|---|---|---|
| `datagolf_outrights` | `/betting-tools/outrights?tour=&market=` | `sport.event_markets`, `sport.prices` |
| `datagolf_matchups` | `/betting-tools/matchups?tour=&market=` | `sport.event_markets`, `sport.prices` |

`datagolf_outrights` returns the current event's **win / top-5/10/20 / make-cut**
odds across ~13 sportsbooks (`bet365`, `pinnacle`, `draftkings`, `fanduel`,
`betmgm`, `caesars`, …) **plus Data Golf's own model line** — so you can compare a
model price against the market in one call. `datagolf_matchups` does the same for
tournament / round / 3-ball matchups.

## Cross-provider comparison

Golf odds slot into the same capability tags as the other books:

- `sport.prices` / `sport.event_markets` → `datagolf_outrights` carries Pinnacle,
  FanDuel and others inline, and composes with the live `pinnacle_matchup_markets`,
  `betfair_market_prices`, `tab_match`, etc. via `list_tools_by_capability`.
- `stats.advanced_metrics` → `datagolf_skill_ratings` / `datagolf_live_tournament_stats`
  alongside the NBA stats surface.

## Notes

- Some endpoints (historical raw data, DFS, archived predictions) require a higher
  Data Golf tier and aren't modelled here; add them the same way if your plan covers
  them. `betting-tools/matchups` returns an empty `match_list` when the book hasn't
  posted that market for the current event.
