# SportsGameOdds (`sportsgameodds`) — odds with real player props

**7 tools · BYO key · shapes unverified**

From [sportsgameodds.com](https://sportsgameodds.com). Host and refusal probed live
2026-08-10 (`401 {"success":false,"error":"Missing API key"}` — a proper status code,
unlike some neighbours in this tier).

## Why it is here alongside two other odds aggregators

**Player props.** `theoddsapi` and `oddsapiio` are strongest on match-level markets —
head-to-head, spreads, totals. This one models props as first-class objects with a
structured, stable market id. If the question is "what is the market on this player's
rushing yards", this is the aggregator that answers it.

```bash
export SPORTSGAMEODDS_API_KEY=your_key_here
```

## The `oddID` is the whole idea

Markets are identified by a composite string, roughly:

```
{statID}-{statEntityID}-{periodID}-{betTypeID}-{sideID}

passing_yards-JOSH_ALLEN_1_NFL-game-ou-over
```

Because it is stable, you can follow one prop **across books and across time** by
matching on the id rather than on display names. That join is exactly what breaks when
you diff scraped bookmaker feeds, where the same market is "Josh Allen Passing Yards",
"J. Allen Pass Yds" and "Allen - Passing Yards" depending on the book.

Two lookup tools exist to help you build one:

- `sportsgameodds_stats` → the valid `statID` values for a league
- `sportsgameodds_players` → the `playerID` that forms the `statEntityID`

Guessing either is the usual way to get an empty result.

## Tools

| Tool | What it gives you |
|---|---|
| `sportsgameodds_events` | Events **with odds attached**, including props — the main tool |
| `sportsgameodds_sports` | Sport ids |
| `sportsgameodds_leagues` | League ids (NFL, NBA, MLB, NHL, EPL, NCAAF…) |
| `sportsgameodds_bookmakers` | Bookmaker ids used inside `byBookmaker` |
| `sportsgameodds_teams` | Team ids |
| `sportsgameodds_players` | Player ids — the `statEntityID` half of a prop id |
| `sportsgameodds_stats` | The statistics catalogue — the `statID` half |

## Two levels of dictionary before a price

The event object nests further than most:

```
event.odds            → keyed by oddID   (an OBJECT, not a list)
  └ .byBookmaker      → keyed by bookmakerID
      └ {odds, spread, overUnder, available, lastUpdatedAt}
```

So reaching a number means two key lookups, not an array scan. Code written against the
other aggregators will not transfer.

## See also

- [TheOddsAPI.md](TheOddsAPI.md) — historical snapshots
- [OddsAPIio.md](OddsAPIio.md) — widest bookmaker index
- `sportsbet` / `tab` / `pointsbet` — direct AU feeds, deeper and live
