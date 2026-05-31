# Worked example — cross-bookie odds comparison

A demonstration of using `sportsdata-mcp` to answer a natural cross-provider
question. Load the server with [`comparator-config.yaml`](./comparator-config.yaml),
which enables **Sportsbet** and **Entain (Ladbrokes)** side by side.

```
sportsdata-mcp --config examples/comparator-config.yaml serve
```

---

## The prompt

> Compare the head-to-head odds for **Storm v Cowboys** (NRL) across my bookies,
> and tell me which one has the better price for the Storm.

## Why this works

Both bookies are anonymous public APIs with totally different shapes — Sportsbet
is a REST gateway keyed by integer `eventId`, Entain is a persisted-GraphQL
gateway keyed by type-prefixed UUIDs. The model never needs to know that. It
finds the comparable tools through the **capability index**: every tool that
answers "all markets + prices for one event" is tagged `sport.event_markets`,
regardless of provider. That tag is the unit of comparison.

## Expected tool-call sequence

### 1. Discover which tools can answer the question

```jsonc
// tool: list_tools_by_capability
{ "capability": "sport.event_markets" }
```

Returns one entry per provider, e.g.:

```jsonc
{
  "capability": "sport.event_markets",
  "tools": [
    { "provider": "sportsbet", "tool": "sportsbet_event_markets", "args_required": ["eventId"] },
    { "provider": "sportsbet", "tool": "sportsbet_sports_card",    "args_required": ["eventId"] },
    { "provider": "entain",    "tool": "entain_graphql_call",      "args_required": ["operation"] }
  ]
}
```

### 2. Resolve the event id on each provider

**Sportsbet** — find the Rugby League class and NRL competition, then the match:

```jsonc
// tool: sportsbet_sports_classes  → locate the Rugby League class + NRL competition id
{ "fromDate": "2026-05-30", "toDate": "2026-06-06" }

// tool: sportsbet_competition_matches  → find the Storm v Cowboys eventId
{ "competitionId": 6927 }
```

**Entain** — browse the NRL competition screen to find the event UUID
(read `entain://graphql/operations` for the variable signatures):

```jsonc
// tool: entain_graphql_call
{
  "operation": "SportingCompetitionScreen",
  "variables": { "category": "RUGBY_LEAGUE", "competitionSlug": "nrl", "includeUpcomingEvents": true }
}
```

### 3. Pull the markets + prices for that event from each bookie

```jsonc
// tool: sportsbet_event_markets
{ "eventId": 10581234 }

// tool: entain_graphql_call
{ "operation": "SportingEventScreen",
  "variables": { "id": "SportingEvent:339e26d0-72a8-49bc-a85f-a2d02c0a1a70", "includeInfoHub": false, "includeWidgets": false } }
```

### 4. Compare the head-to-head selections side by side

The model lines up the "Match Result / Head to Head" market from each response
and reports the better decimal price for the Storm. Sportsbet prices arrive as
`{winPrice, winPriceNum, winPriceDen}`; Entain prices as decimal odds on each
entrant — both reduce to a decimal for comparison.

## Expected answer shape

> **Melbourne Storm — Head to Head**
> | Bookie | Storm | Cowboys |
> |---|---|---|
> | Sportsbet | $1.62 | $2.35 |
> | Ladbrokes | $1.60 | $2.40 |
>
> **Sportsbet** has the better price on the Storm ($1.62 vs $1.60).

(Exact prices vary by market movement; the point is the side-by-side structure
the capability index makes possible.)

## Other comparable capabilities to try

- `racing.race_card` — `sportsbet_racecard_with_context` vs Entain's `RacingRaceCardScreenWeb`
- `racing.same_race_multi` — `sportsbet_racing_popular_srms` vs Entain's `RacingListPopularSameRaceMultis`
- `sport.same_game_multi` — `sportsbet_trending_sgm` vs Entain's `SportingEventPopularSameGameMultis`
- `content.promo` — Sportsbet CMS vs Entain Contentful proxy
