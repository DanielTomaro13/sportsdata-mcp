# Squiggle API Documentation

Unofficial reference for [api.squiggle.com.au](https://api.squiggle.com.au), the API
behind Max Barry's **Squiggle** — an AFL model aggregator. Probed live 2026-08-10.

> **What makes this different from the `afl` provider.** [AFL.md](AFL.md) is the
> official competition: fixtures, results, player stats. Squiggle is the **market of
> opinions about** those games — 41 independent forecasting models, what each tipped,
> how confident it was, and how it has scored. That's the natural counterpart to a
> bookmaker's price: a model consensus you can hold a market up against.

## Contents

- [Etiquette — read before you call it](#etiquette--read-before-you-call-it)
- [The one-endpoint shape](#the-one-endpoint-shape)
- [The id model](#the-id-model)
- [Tools](#tools)
- [Reading a tip](#reading-a-tip)
- [Projected vs actual ladder](#projected-vs-actual-ladder)
- [Gotchas](#gotchas)
- [Cross-provider comparison](#cross-provider-comparison)

## Etiquette — read before you call it

Squiggle is **one person's volunteer-run server**, not a company's API. Its usage
notes ask callers to identify themselves with a contact address, and the operator has
blocked anonymous scrapers.

This provider therefore ships an honest `User-Agent`:

```
sportsdata-mcp (+https://github.com/DanielTomaro13/sportsdata-mcp)
```

**Do not replace it with a browser string**, and don't raise `rate_limit_rps` above
the default 2. Being a good citizen here is the difference between having this
provider and being blocked — and unlike a commercial API, there is no support queue
to appeal to.

## The one-endpoint shape

Every call is `GET /` with a `q=` selecting the resource. The site's own documentation
writes filters with **semicolons** (`?q=games;year=2026;round=1`), which is unusual and
worth knowing when you read their docs — but ordinary query params work identically
(verified live), so the tools here just send `?q=games&year=2026&round=1`.

The response is always a single-key object whose key matches `q`:

```jsonc
{ "games": [ … ] }      // q=games
{ "tips":  [ … ] }      // q=tips
```

## The id model

```
squiggle_teams    → teams[].id      (1–18, stable AFL club ids)
squiggle_sources  → sources[].id    (a forecasting MODEL, e.g. 1 = Squiggle)
squiggle_games    → games[].id      (a single match)
     └─ squiggle_tips(game=<id>)    → every model's view of that one match
```

`sourceid` is the one people miss: **tips and projected ladders are per-model**, so
without a `source` filter you get every model's opinion stacked together — 277 rows
for a single round.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `squiggle_teams` | 18 clubs with ids, abbreviations, debut/retirement years | `ref.teams` |
| `squiggle_games` | Fixture + results, scored by goals/behinds | `sport.fixtures_by_date`, `sport.match_score` |
| `squiggle_sources` | The 41 tracked models — **call first** to get `sourceid`s | — |
| `squiggle_tips` | Per-model tipped winner, margin, confidence, correctness | `stats.model_predictions` |
| `squiggle_standings` | The **actual** AFL ladder | `stats.ladder` |
| `squiggle_ladder` | Per-model **projected** end-of-season ladder | `stats.model_predictions`, `stats.ladder` |

## Reading a tip

A `tips` row is one model's view of one game:

| Field | Meaning |
|---|---|
| `source` / `sourceid` | Which model tipped this |
| `tip` / `tipteamid` | The team it tipped to win |
| `margin` | Predicted winning margin, in points |
| `confidence` | Probability it assigns its tipped team, as a **percent** (e.g. `71.93`) |
| `hconfidence` / `hmargin` | The same two, always stated from the **home** team's side |
| `correct` | `1`/`0` once played — **`null` before the game**, not `0` |
| `bits` | Information score: how much the tip beat a coin flip. Negative = worse than nothing |
| `err` | Absolute margin error once played |

`confidence` is the field to compare against a bookmaker: convert a price to implied
probability, de-vig it, and you have two independent estimates of the same event.

**`correct` is null, not false, for unplayed games.** Filtering on `correct == 0` to
find wrong tips silently includes nothing from the future — but a truthiness test
(`if not correct`) sweeps every unplayed game in with the misses.

## Projected vs actual ladder

Two tools return something called a ladder, and confusing them produces confidently
wrong answers:

- **`squiggle_standings`** — what actually happened. `rank`, `wins`, `percentage` are
  facts.
- **`squiggle_ladder`** — what a model *projects* for the end of the season, as at a
  given round. `rank` here is a prediction, and `mean_rank` is the average finishing
  position across simulations.

`squiggle_ladder` also carries **`swarms`**: an array of simulated finishing positions
for that team — the distribution behind `mean_rank`. That's where "8th but with a real
tail into the top four" lives, and it's the most interesting number Squiggle publishes.

## Gotchas

| Symptom | Cause |
|---|---|
| **277 rows for one round** | No `source` filter — you got all 41 models. Pass `source` for one. |
| **~100 KB response** | No `round` filter on `games`/`tips`/`ladder`. A whole season is large; narrow it. |
| **`correct` is null everywhere** | The games haven't been played. Add `complete=100` for played games only. |
| **Empty `games`** | Wrong `year`, or the season hasn't been published yet. |
| **Blocked / no response** | Almost certainly the User-Agent. Restore the honest one and slow down. |
| **Semicolon params look wrong** | Both forms work; the site documents semicolons, this provider sends normal params. |

## Cross-provider comparison

- `stats.ladder` → `squiggle_standings` alongside `afl_ladders`, and the official
  ladders from `premierleague`, `laliga`, `seriea`, `nrl`.
- `sport.fixtures_by_date` / `sport.match_score` → `squiggle_games` alongside
  `afl_matches_list` and the ESPN scoreboard.
- `stats.model_predictions` is Squiggle-only today. The composition worth building:
  pull `squiggle_tips` for a round, pull the same games from `sportsbet` / `tab` /
  `betfair`, convert prices to de-vigged implied probability, and compare the model
  consensus against the market. Disagreement between a 41-model consensus and a book
  is exactly the signal this server exists to surface.

## Not modelled

- **`q=virtual`** (Squiggle's live in-game win-probability feed) — updates only during
  a live match and returns an empty set otherwise, so it can't be contract-tested.
- The site's HTML pages and images (`logo` fields point at WordPress asset paths).
