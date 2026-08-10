# Football-Data.co.uk Documentation

Reference for **`football-data.co.uk`** — decades of football results published as CSV
downloads, each row carrying **closing odds from ~10 bookmakers**. Free, keyless.
Probed live 2026-08-10.

## Tool

| Tool | What it gives you |
|---|---|
| `footballdatauk_season` | One league season as JSON: every match with result, shots, corners, cards and closing prices from ~10 bookmakers |

The provider registers exactly one tool — the dataset is one CSV per league-season, and
`season` + `division` select which.

## Why this is here, and it isn't "another results feed"

Every other football provider in this catalogue tells you *what happened*. This one
tells you **what the market thought would happen**, match by match, back to the 1990s:
Bet365, Pinnacle, William Hill, Betfair-style maxima and averages, plus Asian handicaps
and over/under lines — both opening and **closing**.

That makes it the only source here you can **backtest** against. Pull a season, compare
closing prices to actual results, and you have a CLV baseline to measure today's live
prices from `sportsbet` / `pinnacle` / `betfair` against. It's the historical half of
what the rest of this server does live.

## The only CSV provider

This is the sole provider using `response_format: csv`. The engine parses the body into
row objects keyed by the header line, so the model receives ordinary JSON — you never
handle raw CSV.

Two things the decoder handles that would otherwise bite:

- **UTF-8 BOM.** The files are Windows-authored and start with a BOM. Left in, it
  becomes part of the first column name (`﻿Div`) and every lookup of that column
  silently misses.
- **Trailing blank lines**, which would otherwise appear as phantom matches with every
  field empty.

The status and size guards from the JSON path still apply first — a 404 HTML page never
reaches the CSV parser, where it would become one garbage row instead of an error.

## Addressing a file

There are no query parameters. Season and division are path segments:

```
/mmz4281/{season}/{division}.csv
```

**Season is four digits**, start and end year without century: `2425` = 2024/25,
`1516` = 2015/16.

| Code | League | Code | League |
|---|---|---|---|
| `E0` | Premier League | `SP1` / `SP2` | La Liga / Segunda |
| `E1`–`E3` | Championship → League Two | `F1` / `F2` | Ligue 1 / 2 |
| `EC` | National League | `N1` | Eredivisie |
| `SC0` | Scottish Premiership | `B1` | Belgian Pro League |
| `D1` / `D2` | Bundesliga / 2. Bundesliga | `P1` | Primeira Liga |
| `I1` / `I2` | Serie A / B | `T1`, `G1` | Turkey, Greece |

## Reading a row

~120 columns per match. The names are terse (the site's `notes.txt` is authoritative):

| Column | Meaning |
|---|---|
| `FTHG` / `FTAG` / `FTR` | Full-time home goals, away goals, result (`H`/`D`/`A`) |
| `HTHG` / `HTAG` / `HTR` | Half time |
| `HS` / `AS` / `HST` / `AST` | Shots, shots on target |
| `HC` / `AC`, `HY` / `AY`, `HR` / `AR` | Corners, yellows, reds |
| `B365H` / `B365D` / `B365A` | Bet365 home / draw / away |
| `PSH` / `PSD` / `PSA` | Pinnacle |
| `WHH` / `WHD` / `WHA` | William Hill |
| `MaxH` / `AvgH` | Best and average price across the market |
| **`B365CH`, `PSCH`, `MaxCH`…** | A **`C`** before the outcome letter means **CLOSING** |

That `C` is the important detail: `B365H` is an early price, `B365CH` is Bet365's
closing price. **Closing odds are the ones worth measuring against** — they're the
market's final, most informed estimate, and the standard CLV benchmark.

**Every value is a string** (it's CSV), and **dates are `DD/MM/YYYY`**. Cast before
doing arithmetic or sorting.

## Gotchas

| Symptom | Cause |
|---|---|
| **`KeyError: 'Div'`** | A BOM leaked into the header. The decoder strips it — if you see this, something bypassed the decoder. |
| **Phantom empty matches** | Trailing blank lines; the decoder drops them. |
| **`"10" < "2"`** | Everything is a string. Cast first. |
| **Dates parsed wrong** | `DD/MM/YYYY`, not US order. |
| **Comparing the wrong price** | `B365H` is an opening-ish price; use `B365CH` for closing. |
| **404** | The DIVISION code is wrong. Note an odd-looking season rarely errors: codes are two-digit year pairs, so `9999` is a real 1998/99 file, not a sentinel. |
| **Missing odds columns** | Bookmaker coverage varies by era; older seasons have fewer columns. |

## Cross-provider comparison

- `stats.closing_odds` is unique to this provider. The composition it unlocks:
  pull a completed season here, compute each bookmaker's closing overround and accuracy,
  then measure a **live** price from `sportsbet` / `pinnacle` / `betfair` against that
  baseline. That's a real CLV workflow, and nothing else in the catalogue can supply
  the historical half of it.
- `sport.match_score` → historical results alongside `openligadb`, `premierleague`,
  `laliga`, `seriea`.
- Team names are the site's own short forms (`Man United`, `Ipswich`) and do **not**
  match the official feeds' names — join with care, or by fuzzy match.

## Not modelled

- **The `notes.txt` column glossary** — a text file, not data; summarised above instead.
- **Fixture files for upcoming matches** (`fixtures.csv`) — the live books in this
  server already cover forthcoming prices far better.
- **The multi-season "all data" archives** — large zips, not per-season CSVs.
