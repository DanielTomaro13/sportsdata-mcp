# MotoGP API Documentation

Reference for **`api.motogp.pulselive.com/motogp/v1`** — the official results API behind
motogp.com. MotoGP, Moto2, Moto3 and MotoE, back to 1949. No key. Probed live
2026-08-10.

> **Unofficial and undocumented.** This is the site's own backend, not a published API.
> It has been stable for years and the nightly drift check will catch it if that
> changes. Note that `api.motogp.com` is a *different* host and 403s — don't confuse
> them.

## The four-level uuid chain

This is the whole story of using this provider, and there is no shortcut:

```
motogp_seasons                                  → season uuid (+ year)
  └─ motogp_events(seasonUuid)                  → event uuid   (a Grand Prix weekend)
       └─ motogp_categories(eventUuid)          → category uuid (MotoGP/Moto2/Moto3/MotoE)
            └─ motogp_sessions(event, category) → session uuid (FP1, Q2, SPR, RAC)
                 └─ motogp_session_classification(sessionUuid)  → the result
```

**Every id is a uuid.** None can be guessed or constructed, and there is no
"2024 Qatar MotoGP race result" endpoint — you walk the chain. Four calls to get one
race result feels heavy, but the 60-second response cache absorbs the repetition when a
model explores a season.

Standings skip the event level: `motogp_standings(seasonUuid, categoryUuid)`.

## Session types

`motogp_sessions` returns every session of a weekend, keyed by `type`:

| `type` | Session |
|---|---|
| `RAC` | Race |
| `SPR` | Sprint (2023 →) |
| `Q1` / `Q2` | Qualifying |
| `FP1`, `FP2`, `PR` | Practice |

Filter on `type == "RAC"` for the race result. Sessions also carry `condition`
(track/air temperature, humidity, weather), which is the interesting part for form
analysis — a wet race explains an anomalous result.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `motogp_seasons` | Every season with uuid; `current: true` marks the live one | `ref.seasons` |
| `motogp_events` | Grand Prix weekends with circuit and dates | `sport.fixtures_by_date` |
| `motogp_categories` | Classes running at an event | `sport.competitions_list` |
| `motogp_sessions` | Sessions with type and track conditions | — |
| `motogp_session_classification` | Finishing order, rider, team, bike, gaps, points | `sport.match_detail`, `stats.player_match` |
| `motogp_standings` | Championship standings per class | `stats.ladder` |

`motogp_sessions` **requires both** `eventUuid` and `categoryUuid` — one alone returns
HTTP 400.

## Gotchas

| Symptom | Cause |
|---|---|
| **HTTP 400 on events** | You passed a year (`2024`) where a season **uuid** is expected. |
| **HTTP 400 on sessions** | Both `eventUuid` and `categoryUuid` are required. |
| **403 from `api.motogp.com`** | Wrong host — this provider uses `api.motogp.pulselive.com`. |
| **No sprint session** | Sprints only exist from 2023, and not at every round. |
| **Empty classification** | The session hasn't run, or it's a test session (pass `test: true`). |
| **Four calls for one result** | By design — every id is a uuid. The response cache makes the repeats cheap. |

## Cross-provider comparison

- `stats.ladder` → `motogp_standings` alongside `jolpicaf1_driver_standings` and
  `formulae_driver_standings`, so "who leads which motorsport championship" is one
  capability lookup across three series.
- `sport.fixtures_by_date` → `motogp_events` alongside `jolpicaf1_races`,
  `formulae_races` and `nascar_race_list` — the `motorsport` preset enables all four.
- `sport.match_detail` / `stats.player_match` → race classifications alongside F1
  results and NASCAR weekend feeds.
- Rider ids are MotoGP uuids and join to nothing else in the catalogue.

## Not modelled

- **Rider and team profile endpoints** — available, but thin next to results, and every
  classification row already embeds rider, team and constructor.
- **PDF result documents** — `event_files` and `file` fields link to official PDFs.
  Links, not data.
- **Live timing** — a separate real-time surface, not part of the results API.
