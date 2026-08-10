# Sportmonks (`sportmonks`) — football, with a genuinely free tier

**8 tools · BYO key · shapes unverified**

From [sportmonks.com](https://sportmonks.com). Host and refusal probed live 2026-08-10.

## Why it is worth carrying

Its free tier is **real** — no trial clock — covering the Danish Superliga and Scottish
Premiership. Within those two leagues it is the only football provider here that will
give you lineups, match events and per-player statistics for free. Treat it as a place
to develop against before paying anyone.

```bash
export SPORTMONKS_TOKEN=your_token_here
```

## `include` is the whole API

Almost every response is skeletal by default. A fixture comes back with ids and little
else; you ask for the rest by naming relations:

```
?include=participants;scores;events;lineups.player;statistics
```

- **semicolon** separates relations
- **dot** nests them
- the free tier caps how deep you may nest

**If a field you expected is missing, you almost certainly did not include it.** This is
the single most common complaint about the API, and it is not a bug.

Two specific cases worth memorising:

| Tool | Without `include` you get | Add |
|---|---|---|
| `sportmonks_fixtures_by_date` | no team names, no score | `participants;scores` |
| `sportmonks_standings` | team **IDs only** | `participant` |

## Tools

| Tool | What it gives you |
|---|---|
| `sportmonks_leagues` | Leagues your plan can see |
| `sportmonks_fixtures_by_date` | Fixtures on one date |
| `sportmonks_fixture` | One fixture — events, lineups, statistics, depending on `include` |
| `sportmonks_standings` | League table for a season |
| `sportmonks_teams` | Clubs |
| `sportmonks_players` | Players, with season statistics when included |
| `sportmonks_livescores` | Fixtures in progress now |
| `sportmonks_types` | **The type catalogue — read this one** |

## `sportmonks_types` is not optional

Events, player statistics and standings details are all keyed by **numeric `type_id`**.
A fixture's events look like this:

```json
{"type_id": 14, "minute": 23, "player_name": "..."}
```

Without the type catalogue that is unreadable. Fetch it once, keep the mapping, and the
rest of the API becomes legible.

## Reading a score

`scores` is a **list of period scores**, not a single number:

```json
[{"score": {"goals": 1, "participant": "home"}, "description": "1ST_HALF"},
 {"score": {"goals": 2, "participant": "home"}, "description": "CURRENT"}]
```

Filter on `description == "CURRENT"` for the live or final figure.

## See also

- [FootballDataOrg.md](FootballDataOrg.md) — more competitions, less depth per match
- `premierleague`, `laliga`, `seriea` — official and keyless for those three leagues
