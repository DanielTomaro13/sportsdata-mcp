# Formula E API Documentation

Reference for **`api.formula-e.pulselive.com/formula-e/v1`** — the official API behind
fiaformulae.com. The all-electric championship from its first season (2014-15). No key.
Probed live 2026-08-10.

> **Unofficial and undocumented**, same as [MotoGP](MotoGP.md) — both run on the
> Pulselive platform and are the sites' own backends.

## Championship, not season

Formula E calls a season a **championship**, each with a uuid. There is **no
`/seasons` endpoint** (verified 404), so `formulae_championships` is always the first
call and every other tool takes its `championshipId`.

Each championship carries `status`: `Past`, `Live` or `Future` — useful for picking a
completed season when you want stable data.

## Two response shapes, and they disagree

This is the parsing trap:

```jsonc
// races — WRAPPED
{"pageInfo": {…}, "races": [ … ]}

// standings — TOP-LEVEL ARRAY
[{"driverPosition": 1, "driverLastName": "Rowland", …}]
```

Assuming one shape for both is the usual error here.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `formulae_championships` | Every season with uuid and status | `ref.seasons` |
| `formulae_races` | Race calendar (all seasons, or one championship) | `sport.fixtures_by_date` |
| `formulae_race` | One race's detail | `sport.match_detail` |
| `formulae_driver_standings` | Drivers' championship | `stats.ladder` |
| `formulae_team_standings` | Teams' championship + per-race points | `stats.ladder` |

## There are no per-race results here

`/races/{id}/results` **404s** (verified), and the race detail object advertises
`hasRaceResults: true` while carrying no results payload. That data is served by a
different backend than this host.

The closest available substitute is **`formulae_team_standings`**, whose
`teamRaceStandings` gives each team's points race by race:

```jsonc
{"teamName": "TAG HEUER PORSCHE", "teamPoints": 256,
 "teamRaceStandings": [{"raceSequence": 13, "raceCountry": "DE", "racePoints": 28}]}
```

That reconstructs the shape of a season without giving you finishing positions. If
per-race classifications matter, `jolpicaf1` (for F1) and `motogp` both have them, and
ESPN carries some Formula E coverage.

## Gotchas

| Symptom | Cause |
|---|---|
| **404 on `/seasons`** | There isn't one — use `formulae_championships`. |
| **HTTP 400 on standings** | `championshipId` is required. |
| **Standings have no `data` key** | They're top-level arrays; only races are wrapped. |
| **No race results** | Not on this host — see above. |
| **A championship with no standings** | `status: "Future"` — it hasn't started. |

## Cross-provider comparison

- `stats.ladder` → both standings tools alongside `motogp_standings` and
  `jolpicaf1_driver_standings`. The `motorsport` preset enables F1, MotoGP, Formula E
  and NASCAR together.
- `sport.fixtures_by_date` → `formulae_races` alongside the other three motorsport
  calendars.
- Driver ids are Formula E uuids. Several drivers appear in F1 history too, but the
  ids don't join — match on surname.

## Not modelled

- **Session results** (practice/qualifying) — the `hasSessionResults` flag exists but
  the payload isn't served on this host, same as race results.
- **Live timing** — a separate real-time surface.
- **News and media** — not sports data.
