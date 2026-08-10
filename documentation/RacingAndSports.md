# Racing and Sports (Australia) API Documentation

Unofficial reference for the JSON feeds behind **www.racingandsports.com.au** — the
form/data site for thoroughbred, harness and greyhound racing (plus a sports match
list). No auth.

> **Cloudflare note.** The site sits behind Cloudflare, which JS-challenges most
> paths from **datacenter IPs**. The `/todays-racing-json-v2` feed is whitelisted
> and is verified live (it returns 200 JSON even from a server). The other endpoints
> are reached fine from a normal browser / residential IP but get a **403 challenge
> from a datacenter** — so their tools work for you locally but their live tests
> `xfail` in CI/sandbox environments.

## Host

| Host | Role |
|---|---|
| `www.racingandsports.com.au` | The site's XHR JSON feeds. |

## Tools — group `racingandsports.racing`

| Tool | Path | Capability | Notes |
|---|---|---|---|
| `racingandsports_todays_racing` | `/todays-racing-json-v2` | `racing.meetings_by_date` | **Verified.** Today's meetings across all codes. |
| `racingandsports_match_list` | `/match-list-json` | — | Sports fixtures feed (Cloudflare-challenged from datacenter IPs). |
| `racingandsports_race_odds` | `/FormGuide/GetOdds?raceId=&token=` | — | Bookmaker odds for one race. **Needs a per-race `token`** issued by the form-guide page (not generatable here). |

### `racingandsports_todays_racing` shape

```
[
  { "Discipline": "T", "DisciplineFullText": "THOROUGHBRED",
    "Countries": [
      { "CountryName": "Australia", "countryCode": "AUS", "Flag": "…", "HasResults": false,
        "Meetings": [
          { "Course": "Swan Hill", "RaceNumber": 4, "HasResults": false,
            "Remaining": 0.46, "MeetingClosed": false,
            "FormGuideUrl": "…/form-guide/thoroughbred/australia/swan-hill/2026-06-05/R4",
            "PostMeetingUrl": "…", "PreMeetingUrl": "…", "PDFUrl": "…" } ] } ] },
  { "Discipline": "H", … },   // Harness
  { "Discipline": "G", … }    // Greyhound
]
```

One element per discipline; each meeting carries the URLs to its (HTML) form guide,
results, and PDF race fields. (The `date` query param is accepted but ignored — the
feed always returns today's card.)

## Cross-provider comparison

- `racing.meetings_by_date` → `racingandsports_todays_racing` alongside
  `tab_racing_meetings`, `pointsbet_racing_meetings`, `betr_grouped_racecard`,
  `unibet_racing_call`, `sportsbet_racing_allracing` — a cross-source view of the
  day's race meetings.

## Not modelled

- The race **form / fields / results** are served as **HTML / PDF** pages
  (`FormGuideUrl`, `PostMeetingUrl`, `PDFUrl`) — not JSON, so not modelled.
- `Course/GetCourseImages` — uses repeated `ids=` query keys (an array param the
  engine's CSV serialisation can't reproduce) and is low-value track imagery.
- `UserProfile/GetNotifications`, `FormGuide/GetUserPick` — account/session surfaces.
- `signalr/start…` — the live-odds **SignalR websocket** (not a REST endpoint).

## Where it sits among the racing providers

This catalogue has a lot of racing, and the providers are not interchangeable:

| Provider | Best for |
|---|---|
| `sportsbet`, `tab`, `betr`, `pointsbet`, `entain` | Live prices, racecards, fluctuations |
| `betfair` | Exchange prices — the closest thing to a true market |
| **`racingandsports`** | **Form and ratings as a data feed**, not a betting surface |

Racing and Sports is a form service rather than a bookmaker, so it answers "what does the
past say about this runner" rather than "what is the market saying now". Pair it with a
book for prices.

## Practical notes

Meeting and race identifiers here do **not** match the bookmakers' ids — every AU racing
provider mints its own. Joining across them means matching on date, track name and race
number, and track names vary in spelling ("Flemington" is easy; provincial tracks are
not). The `racing.*` capability tags exist so a model can find the equivalent tool on
another provider, but the join is still yours to do.

Coverage is Australian and New Zealand thoroughbred racing first, with harness and greys
thinner.

## See also

- [Sportsbet.md](Sportsbet.md), [TAB.md](TAB.md) — racecards and prices
- [Betfair.md](Betfair.md) — exchange prices
