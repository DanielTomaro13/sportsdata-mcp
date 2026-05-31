# sportsdata-mcp — Implementation Plan

A FastMCP server that exposes sports-data APIs documented in `documentation/*.md` as MCP tools, configurable so the user only loads the tool groups they need.

> **Source of truth.** Every endpoint is declared once in `specs/{provider}.yaml`. The Python code is generic — it loads specs, registers tools, and dispatches HTTP requests. Adding a new provider should require zero Python changes (only a new YAML).

> **Scope is sports data, not just bookmakers.** "Provider" covers any JSON sports API: bookmaker price feeds (Sportsbet, Ladbrokes), league/governing-body data (AFL.com.au, NHL, NRL, Cricket Australia), aggregators (ESPN, The Sports DB), fantasy platforms (AFL Fantasy), and analytics sites. The capability-tag system makes them interchangeable wherever they answer the same question — comparing odds across bookies and comparing stats across data sources use the exact same mechanism.

## Table of contents

- [Decisions locked in](#decisions-locked-in)
- [Repository layout](#repository-layout)
- [Spec format](#spec-format)
- [Capability tags & multi-provider composition](#capability-tags--multi-provider-composition)
- [Provider taxonomy](#provider-taxonomy)
- [Group naming convention](#group-naming-convention)
- [Pydantic models](#pydantic-models)
- [Tool registration flow](#tool-registration-flow)
- [HTTP client](#http-client)
- [Auth providers](#auth-providers)
- [Dispatcher patterns](#dispatcher-patterns)
- [Resources](#resources)
- [Config resolution](#config-resolution)
- [CLI commands](#cli-commands)
- [Error contract](#error-contract)
- [Implementation phases](#implementation-phases)
- [Testing strategy](#testing-strategy)
- [Adding a new provider](#adding-a-new-provider)
- [Distribution](#distribution)
- [Open questions deferred to v2](#open-questions-deferred-to-v2)

---

## Decisions locked in

| Topic | Decision |
|---|---|
| **Language** | Python 3.11+, FastMCP |
| **Tool selection** | Config file (`sportsdata-mcp.yaml`) + env vars (`SPORTSDATA_MCP_GROUPS`) at startup. Only matching tools are registered. No runtime toggling. |
| **High-cardinality APIs** | One dispatcher tool + MCP resource catalogue, not one tool per operation. Applies to Entain GraphQL (127 ops), AFL CFS premium (27 ops), AFL StatsPro (9 ops). |
| **Spec source** | Parallel YAML per provider in `specs/`. Markdown docs in `documentation/` stay human-only. |
| **Multi-provider composition** | First-class via `capabilities` tags on every endpoint + a `list_tools_by_capability` meta-tool. The MCP makes cross-provider discovery cheap; the model composes the comparison itself (no built-in normalisation). |
| **Entain hash drift** | Fail loudly with actionable error. Refresh via `sportsdata-mcp refresh-hashes entain` CLI. |
| **AFL auth** | Anonymous token minted from `POST /cfs/afl/WMCTok`. Cached in-memory, refreshed on 401. No Playwright, no env var required. |
| **Caching** | None for tool calls — each = one fresh HTTP request. Only exception: `reference_resources` (static id-maps) cache once per server session. |
| **HTTP client** | `httpx.AsyncClient`, one per provider with shared connection pool. All decoding goes through `request_json` (size guard, status guard, non-JSON guard) — never a bare `r.json()`. |
| **Response handling** | Defensive: oversize → `RESPONSE_TOO_LARGE`, 429 → `RATE_LIMITED`, 403 → `BLOCKED`, non-JSON/HTML challenge → `NON_JSON_RESPONSE`. Size cap (default 512 KB) protects the model's context. |
| **Spec packaging** | Specs ship **inside** the package (`src/sportsdata_mcp/specs/`), loaded via `importlib.resources` — never a cwd-relative `./specs/`. Required for `uvx`/`pip install` to work. |
| **Transport** | MCP stdio. (HTTP / SSE deferred to v2.) Server is client-agnostic; non-MCP clients (OpenAI/Azure/etc.) use an external bridge — see v2. |

---

## Repository layout

```
sportsdata-mcp/
├── PLAN.md                              # this file
├── README.md                            # quickstart + per-provider notes
├── pyproject.toml                       # package, deps, entry points
├── .env.example                         # documented env vars (none required for v1)
├── .gitignore
│
├── documentation/                       # existing — human-readable API docs
│   ├── Sportsbet.md
│   ├── Entain.md
│   └── AFL.md
│
├── src/
│   └── sportsdata_mcp/
│       ├── __init__.py                  # __version__
│       ├── __main__.py                  # `python -m sportsdata_mcp` → cli.main()
│       ├── cli.py                       # argparse: serve / lint / doctor / refresh-hashes
│       ├── server.py                    # FastMCP bootstrap; serve_stdio()
│       ├── config.py                    # load YAML + env, resolve enabled_groups
│       ├── spec.py                      # pydantic models: Provider, Endpoint, Dispatcher, Operation
│       ├── spec_loader.py               # load packaged specs via importlib.resources, parse, validate
│       ├── registry.py                  # spec → tool/resource registration
│       ├── http_client.py               # httpx wrapper, provider routing, auth injection, response decoding
│       │
│       ├── specs/                       # machine-readable, source of truth — SHIPS INSIDE THE PACKAGE
│       │   ├── _schema.yaml             # pydantic-validated spec schema
│       │   ├── _template.yaml           # starter for new providers
│       │   ├── _capabilities.yaml       # canonical capability catalogue
│       │   ├── sportsbet.yaml
│       │   ├── entain.yaml
│       │   └── afl.yaml
│       │
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── base.py                  # AuthProvider protocol
│       │   ├── none.py                  # NullAuthProvider
│       │   ├── header.py                # StaticHeaderAuthProvider (e.g. Content-Type)
│       │   └── afl.py                   # AFLTokenProvider (WMCTok minter)
│       │
│       ├── dispatchers/
│       │   ├── __init__.py
│       │   ├── base.py                  # Dispatcher protocol
│       │   ├── graphql_persisted.py     # Apollo persisted-query dispatcher
│       │   └── templated_rest.py        # parametric REST dispatcher
│       │
│       ├── resources/
│       │   ├── __init__.py
│       │   └── builders.py              # spec → MCP resource registrations
│       │
│       ├── refresh/
│       │   ├── __init__.py
│       │   └── entain_hashes.py         # fetches latest bundle, extracts hashes, diffs spec
│       │
│       └── errors.py                    # ToolError, AuthMissingError, PersistedQueryNotFoundError, …
│
├── tests/
│   ├── conftest.py                      # fixtures: temp spec dir, mock httpx
│   ├── unit/
│   │   ├── test_spec_load.py
│   │   ├── test_config.py
│   │   ├── test_registry.py
│   │   ├── test_url_builder.py
│   │   ├── test_auth_afl.py             # WMCTok flow with mocked httpx
│   │   └── test_dispatchers.py
│   ├── integration/                     # marked @pytest.mark.live, opt-in
│   │   ├── test_afl_public.py
│   │   ├── test_afl_premium.py
│   │   ├── test_sportsbet.py
│   │   └── test_entain.py
│   └── fixtures/
│       ├── specs/                       # tiny test specs
│       └── responses/                   # canned JSON responses for unit tests
│
└── examples/
    ├── sportsdata-mcp.yaml                  # commented config showing every option
    ├── claude-desktop-config.json       # MCP server entry for Claude Desktop
    └── claude-code-mcp.json             # MCP server entry for Claude Code
```

> **Why specs live *inside* the package** (`src/sportsdata_mcp/specs/`, not at repo root). The server is distributed via `uvx sportsdata-mcp` / `pip install` and run from an arbitrary working directory — there is no `./specs/` to walk at runtime. `spec_loader.py` therefore loads them with `importlib.resources.files("sportsdata_mcp.specs")`, which works identically from a source checkout, an installed wheel, or a zipped app. The hatch build config explicitly includes `src/sportsdata_mcp/specs/*.yaml` in the wheel. (Editing specs during development still just means editing files in that directory.)

---

## Spec format

A spec file has up to five top-level keys: `provider`, `endpoints`, `dispatchers`, `graphql`, `reference_resources`. All except `provider` are optional.

> The fifth key, `reference_resources`, declares the small static lookup tables exposed as MCP resources (e.g. `afl://teams/idmap`, `sportsbet://classes`). It is fully specified under [Resources](#resources). Earlier drafts referenced a `resources` key but never defined its shape or wired it into the `Spec` model — this is the corrected, modelled version.

### `provider`

```yaml
provider:
  id:           afl                                   # unique slug, lowercase
  display_name: "AFL (Australian Football League)"
  doc_url:      "https://github.com/.../documentation/AFL.md"

  base_urls:
    public:  https://aflapi.afl.com.au
    premium: https://api.afl.com.au

  default_headers:                                     # sent on every request to this provider
    User-Agent: "Mozilla/5.0 (compatible; sportsdata-mcp/0.1)"

  auth:                                                # one block per base_url that needs it
    public:
      type: none
    premium:
      type: afl_wmctok                                 # references auth/afl.py
      mint_url: https://api.afl.com.au/cfs/afl/WMCTok
      mint_headers:                                    # required for WMCTok to mint
        Origin:  https://www.afl.com.au
        Referer: https://www.afl.com.au/
      header: x-media-mis-token                        # the header to attach to subsequent calls

  hash_refresh:                                        # optional — used by `sportsdata-mcp refresh-hashes`
    bundle_url_pattern: "/assets/vendor-graphql-ops-web-*.js"   # currently only Entain
    bundle_host:        "https://www.ladbrokes.com.au"
```

### `endpoints`

```yaml
endpoints:
  - name:    afl_competitions_list
    group:   afl.public.core
    capabilities: [sport.competitions_list]            # see capabilities catalogue below
    summary: "List all AFL competitions (16 known: AFL, AFLW, VFL, …)"
    method:  GET
    base:    public                                    # references provider.base_urls.public
    path:    /afl/v2/competitions
    auth:    public                                    # references provider.auth.public
    params:
      - { name: pageSize, in: query, type: integer, default: 50, description: "Items per page" }
      - { name: page,     in: query, type: integer, default: 0,  description: "Page index (0-based)" }
    response_hint: |
      {
        "meta":         {"code":200, "pagination":{...}},
        "competitions": [{"id":<int>, "providerId":"CD_C014", "code":"AFL", "name":"..."}]
      }
    examples:
      - description: "All 16 competitions"
        params:      {pageSize: 50}

  - name:    afl_match_get
    group:   afl.public.core
    capabilities: [sport.match_detail, sport.match_score]
    summary: "Get a single match by integer ID"
    method:  GET
    base:    public
    path:    /afl/v2/matches/{matchId}
    auth:    public
    params:
      - { name: matchId, in: path, type: integer, required: true, description: "AFL match `id` (not providerId)" }
    response_hint: "{meta, matches:[{id, providerId, compSeason, round, home, away, venue, utcStartTime, status, score?}]}"
```

#### `params[*]` schema

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✓ | Param name in the URL or query. Becomes the tool argument name. |
| `in` | enum: `path`, `query`, `header`, `body`, `dispatch` | ✓ | Where the value goes. `body` serialises the value into the JSON request body (only valid on `POST`/`PUT`/`PATCH`). `dispatch` is reserved for dispatcher tools. |
| `type` | enum: `string`, `integer`, `number`, `boolean`, `string_csv`, `json`, `object` | ✓ | JSON-schema type. `string_csv` accepts a list and joins with comma. `json` accepts an object and URL-encodes its JSON (for query params). `object` is a free-form dict (used for `body` params and dispatcher `variables`/`path_params`). |
| `required` | bool | – | Default `false`. Path params force `true`. |
| `default` | any | – | Used when the model omits the param. |
| `description` | string | – | Per-arg description shown in the tool schema. |
| `enum` | list | – | If set, the tool's JSON-schema restricts to these values. |

> **`body` params.** Multiple `body` params on one endpoint are merged into a single JSON object keyed by param name; a single `body` param of type `object` is sent as the whole body. If an endpoint declares any `body` param, the client sets `Content-Type: application/json` (unless the provider's `default_headers` already set it) and sends the serialised body. v1 has no `POST`-with-body REST endpoints across AFL/Sportsbet/Entain (their POSTs are the WMCTok mint, which is body-less, and GraphQL, which goes through the dispatcher), but the mechanism exists so a future provider needs zero Python changes.

### `dispatchers`

```yaml
dispatchers:
  - name:    entain_graphql_call
    group:   entain.graphql
    kind:    graphql_persisted
    summary: |
      Call any of Entain/Ladbrokes' 127 persisted GraphQL operations.
      Use the entain://graphql/operations resource to list valid operation names and their variable shapes.
    endpoint:         https://api.ladbrokes.com.au/gql/router
    method:           GET
    auth:             none
    default_headers:  {Content-Type: application/json, Origin: https://www.ladbrokes.com.au, Referer: "https://www.ladbrokes.com.au/"}
    catalog_resource: "entain://graphql/operations"
    catalog_source:   graphql.operations                # references graphql.operations block below
    params:
      - { name: operation, in: dispatch, type: string,  required: true,  description: "Operation name (must exist in catalogue)" }
      - { name: variables, in: dispatch, type: object,  required: false, description: "GraphQL variables (operation-specific)" }
```

### `graphql.operations`

```yaml
graphql:
  operations:
    - name:      HomeSportsScreen
      sha256:    50fab92cd64e6c71f6c1f8048e9d95529369add40bc3af425949fa7e4d1bc8fb
      variables: "includeMajorEvents:Boolean, includeFeaturedEvents:Boolean, featuredEventsEventCount:Int, …"
      verified:  true
    - name:      RacingRaceCardScreenWeb
      sha256:    d59b563bacb7984ed87e6a843669aa7f02d03e93a0cc98f505f859c6190cbbc7
      variables: "id:ID!, isLoggedIn:Boolean!, includePlaceExtra:Boolean!"
      verified:  false
    # … 125 more (extracted by `sportsdata-mcp refresh-hashes entain`)
```

### `dispatchers[*].kind: templated_rest`

For provider-specific multi-endpoint families that share auth and base URL (AFL StatsPro, AFL CFS premium):

```yaml
dispatchers:
  - name:    afl_statspro_call
    group:   afl.premium.statspro
    kind:    templated_rest
    summary: "Call any of the AFL StatsPro endpoints."
    base:    premium
    auth:    premium
    method:  GET
    catalog_resource: "afl://statspro/operations"
    params:
      - { name: operation,    in: dispatch, type: string, required: true, enum: [leadingPlayerStats_season, leadingPlayerMatchTotals_round, …] }
      - { name: path_params,  in: dispatch, type: object, required: true, description: "Map of path-parameter values (e.g. {seasonProviderId: 'CD_S2026014'})" }
      - { name: query_params, in: dispatch, type: object, required: false }
    operations:
      - name:   leadingPlayerStats_season
        path:   /statspro/leadingPlayerStats/season/{seasonProviderId}
        path_params:  [seasonProviderId]
        query_params: [limit]
      - name:   leadingPlayerMatchTotals_round
        path:   /statspro/leadingPlayerMatchTotals/round/{roundProviderId}
        path_params:  [roundProviderId]
      - name:   playersStats_seasons
        path:   /statspro/playersStats/seasons/{seasonProviderId}
        path_params:  [seasonProviderId]
        query_params: [includeBenchmarks, playerNameLike, playerPosition, teamId]
      # … 6 more
```

### `_schema.yaml`

A self-documenting reference of the above, used by:
- `sportsdata-mcp lint` to validate every spec
- The README to show contributors the contract

---

## Capability tags & multi-provider composition

**The headline use case for this MCP is comparing across bookies.** A user asks "best odds for tonight's Storm vs Cowboys" and the model should be able to fan out to every enabled provider, gather snapshots, and report the comparison. The MCP makes that *discovery* cheap; the model does the composition (no built-in normaliser).

### `capabilities` field

Every endpoint and dispatcher may declare a list of capability tags — short slugs that name **the question this endpoint answers**, intentionally provider-agnostic. The same tag on Sportsbet's `event_markets` tool and Entain's GraphQL `SportingEventScreen` op tells the model "these are interchangeable for this question."

```yaml
- name: sportsbet_event_markets
  capabilities: [sport.event_markets, sport.prices]

- name: entain_graphql_call
  capabilities: [sport.event_markets, sport.competition_screen, racing.race_card, sport.prices]

- name: afl_match_get
  capabilities: [sport.match_detail, sport.match_score]
```

### Canonical capability catalogue

Lives at `specs/_capabilities.yaml` and is validated by `sportsdata-mcp lint` (a typo like `racing.race_card` vs `racing.racecard` would silently split tools across providers — the linter catches it).

```yaml
# specs/_capabilities.yaml
capabilities:
  # Racing
  - id: racing.meetings_by_date
    description: "List all race meetings (track + races) for a given date."
  - id: racing.race_card
    description: "Full racecard for one race: runners, prices, jockeys, scratchings."
  - id: racing.race_results
    description: "Final placings + dividends for a resulted race."
  - id: racing.next_to_jump
    description: "Next races about to start, sorted by start time."
  - id: racing.futures
    description: "Long-running futures markets (Cup outrights, season-long props)."
  - id: racing.same_race_multi
    description: "Same Race Multi (SRM) suggestions or popular combinations."

  # Sport (cross-code)
  - id: sport.competitions_list
    description: "List sport competitions / leagues / tours."
  - id: sport.competition_screen
    description: "Competition page: leagues, events, optional futures."
  - id: sport.match_detail
    description: "Single sport event/match including teams, venue, start time."
  - id: sport.match_score
    description: "Current scoreboard / period state for a match."
  - id: sport.event_markets
    description: "All markets + selections + prices for one event."
  - id: sport.prices
    description: "Live or last prices for selections."
  - id: sport.same_game_multi
    description: "Same Game Multi (SGM) suggestions or popular combinations."
  - id: sport.in_play
    description: "Events currently in-play / live."
  - id: sport.live_video
    description: "Live video stream URLs."
  - id: sport.live_audio
    description: "Live audio stream URLs."
  - id: sport.commentary
    description: "Text or play-by-play commentary for a match."

  # Stats — basic
  - id: stats.player_match
    description: "Per-player stats for a single match / game / fixture."
  - id: stats.player_season
    description: "Per-player stats over a season."
  - id: stats.player_game_log
    description: "Game-by-game stat line for one player across a date range or season."
  - id: stats.player_career
    description: "Per-season totals across a player's career."
  - id: stats.player_profile
    description: "Biographical + career-summary view of one player (height, weight, debut, draft)."
  - id: stats.team_match
    description: "Per-team aggregate stats for a single match."
  - id: stats.team_season
    description: "Per-team aggregate stats over a season."
  - id: stats.team_game_log
    description: "Game-by-game results / form for one team."
  - id: stats.leaders_season
    description: "Season leaders per stat (Coleman, Brownlow, top scorers, MVP, etc.)."
  - id: stats.ladder
    description: "Current ladder / standings / conference standings for a competition."
  - id: stats.head_to_head
    description: "Head-to-head history between two teams."

  # Stats — advanced / sport-specific
  - id: stats.advanced_metrics
    description: "Advanced / synergy / tracking stats not in basic box scores (PER, true shooting, xG, etc.)."
  - id: stats.shot_chart
    description: "Shot location / spatial data (basketball, soccer, hockey)."
    single_provider: true
  - id: stats.play_by_play
    description: "Event-level play-by-play log of a game."
  - id: stats.fantasy_projections
    description: "Fantasy-points projections / DFS pricing."
    single_provider: true

  # Sport — fixtures (for non-betting data sources)
  - id: sport.fixtures_by_date
    description: "All scheduled fixtures / games on a given date across one league."
  - id: sport.match_boxscore
    description: "Detailed game box score (quarter/period scores, team totals, leaders)."
  - id: sport.season_summary
    description: "End-of-season / current-state league summary (champion, top scorer, awards)."

  # Catalogue / reference
  - id: ref.teams
    description: "Team catalogue (id, name, club, colours)."
  - id: ref.players
    description: "Player catalogue (id, name, dob, draft info)."
  - id: ref.venues
    description: "Venue catalogue (id, name, location, timezone)."
  - id: ref.seasons
    description: "Season / competition-season catalogue."

  # Content / editorial
  - id: content.news
    description: "Text articles, news index."
  - id: content.video
    description: "Editorial video content (highlights, replays, press conferences)."
  - id: content.promo
    description: "Promo / marketing cards from CMS."

  # Broadcast
  - id: broadcast.schedule
    description: "Broadcast schedule (who shows what, when, where)."
  - id: broadcast.channels
    description: "Broadcast channel catalogue."
```

This list grows as new providers are added — every new bookie either reuses existing tags or declares new ones in `_capabilities.yaml` (which is reviewed in the same PR).

### `list_tools_by_capability` meta-tool

Always registered alongside `list_available_groups`. The model calls it to discover comparable tools across enabled providers:

```python
@mcp.tool
def list_tools_by_capability(capability: str | None = None) -> dict:
    """
    Discover tools by capability — the unit of cross-provider comparison.

    Given a capability slug like 'sport.event_markets', returns every enabled tool
    that exposes that capability across all configured providers. Pass no argument
    to see the full capability → tools map.

    The model uses this to fan out a single user question across enabled bookies.
    """
```

Example return:

```jsonc
{
  "capability": "racing.race_card",
  "tools": [
    {
      "provider":      "sportsbet",
      "tool":          "sportsbet_racecard_with_context",
      "summary":       "Full racecard incl. context (sibling meetings/events/pools)",
      "args_required": ["eventId", "classId"]
    },
    {
      "provider":      "entain",
      "tool":          "entain_graphql_call",
      "summary":       "Call a Ladbrokes GraphQL persisted query — use operation='RacingRaceCardScreenWeb'",
      "args_required": ["operation", "variables"]
    }
  ],
  "hint": "Call all tools concurrently and compare the snapshots; do not assume normalised schemas."
}
```

`list_tools_by_capability()` (no arg) returns the full map — useful as a "what comparators are available?" first call from the model.

### Worked comparator example

A typical model interaction once a user enables `sportsbet.racing` + `entain.graphql` + `afl.public.core`:

```
User: "Compare odds for Race 4 at Caulfield across my bookies."

Model: → list_tools_by_capability("racing.race_card")
       → {tools: [sportsbet_racecard_with_context, entain_graphql_call]}

       → sportsbet_racing_allracing(eventDate="2026-05-28")            # find Caulfield eventId
       → entain_racing_meeting(date="2026-05-28", timezone="...")      # find Caulfield raceId

       (in parallel:)
       → sportsbet_racecard_with_context(eventId=10523658, classId=1)
       → entain_graphql_call(operation="RacingRaceCardScreenWeb",
                             variables={"id":"RacingRaceCard:179247bf-...",
                                        "isLoggedIn":false, "includePlaceExtra":true})

       → composes: "Sportsbet has Can't Be Reel at $1.55 win / $1.05 place.
                    Ladbrokes has the same horse at $1.60 win / $1.10 place.
                    Ladbrokes is better."
```

The MCP never sees "comparison" as a concept — it just exposes the parts.

### CI lint rule

`sportsdata-mcp lint` enforces:

1. Every capability mentioned on any endpoint exists in `_capabilities.yaml`.
2. No two capabilities have identical descriptions (typo guard).
3. Optionally (warning, not error): every capability has ≥2 providers exposing it — otherwise it's not a "comparison" capability, and either (a) more providers need to be added or (b) the capability should be marked `single_provider: true`.

### Resource catalogue

A single resource exposes the full capability list, so the model can browse without invoking tools:

| Resource URI | Content |
|---|---|
| `sportsdata://capabilities` | The full `_capabilities.yaml` rendered as JSON, plus a `providers` field per capability listing which enabled providers expose it. |

This resource is cheap (a few KB) and answers "what kinds of questions can my MCP answer?" in one read.

### What this design *doesn't* do

- **No automatic normalisation.** Sportsbet returns `{ winPrice: 1.55, winPriceNum: 11, winPriceDen: 20 }`; Ladbrokes returns `{ odds: { formatted: "4.40", decimal: 4.4, numerator: 17, denominator: 5 } }`. AFL returns league-shaped JSON; ESPN returns nested events. Don't unify them — the model handles it. Normalisation would mean fighting every provider's schema on every release.
- **No best-odds (or best-stats) tool inside the MCP.** That composition is the model's job — and "best" varies per question (best price? best line? most generous bonus? deepest historical data?).
- **No cross-call orchestration.** Each tool call is one HTTP request to one provider. The model fans out using Claude's native parallel tool calls.

---

## Provider taxonomy

"Provider" in this MCP means any JSON sports API — bookmakers and non-bookmakers alike. The spec format makes no distinction. Four broad classes are anticipated:

| Class | Examples | Typical capabilities |
|---|---|---|
| **Bookmakers / wagering** | Sportsbet, Ladbrokes (Entain), TAB, Pointsbet, Bet365 | `racing.race_card`, `sport.event_markets`, `sport.prices`, `sport.same_game_multi`, `racing.next_to_jump`, `racing.futures` |
| **League / governing-body data** | AFL.com.au, NRL.com, NHL.com, Cricket Australia | `sport.fixtures_by_date`, `sport.match_detail`, `sport.match_boxscore`, `stats.ladder`, `stats.player_season`, `broadcast.schedule`, `content.news` |
| **Aggregator / multi-sport** | ESPN, The Sports DB, Sportradar (where free) | `sport.fixtures_by_date`, `sport.match_score`, `stats.ladder`, `ref.teams`, `ref.players` |
| **Analytics / fantasy / specialist** | AFL Fantasy, FantasyPros, AFLTables | `stats.advanced_metrics`, `stats.fantasy_projections`, `stats.player_game_log`, `stats.shot_chart` |

The capability tags are the **only** thing that makes cross-class comparison possible. A user with Sportsbet + Ladbrokes + AFL.com.au enabled can ask "give me Buddy Franklin's last-10-game averages **and** the line for tonight's Swans v Hawks" in one prompt; the model calls:

- `afl_player_game_log(playerId=..., lastN=10)` (Class 2 — league data)
- `sportsbet_event_markets(eventId=...)` + `entain_graphql_call(operation="SportingEventScreen", ...)` (Class 1 — bookies, comparing the line)

Different tools, completely different schemas — but discovered by the same `list_tools_by_capability()` call. The same pattern applies to any future Class-2 provider plugged in via [Adding a new provider](#adding-a-new-provider).

---

## Group naming convention

Format: `{provider}.{surface}.{category}` (lowercase, dot-separated, max 3 segments).

| Provider | Group | Tools | Notes |
|---|---|---|---|
| Sportsbet | `sportsbet.racing`         | 15  | `/sportsbook-racing/...` |
| Sportsbet | `sportsbet.sports`         | 14  | `/sportsbook-sports/...` |
| Sportsbet | `sportsbet.results`        | 2   | `/sportsbook-results/...` |
| Sportsbet | `sportsbet.cross`          | 12  | sports-form, media previews, trending SGM, promos, page-content, CMS |
| Sportsbet | `sportsbet.graphql`        | 1   | Dispatcher (only `EventStats` known so far) |
| Entain    | `entain.rest`              | 13  | `/v2/...` REST |
| Entain    | `entain.graphql`           | 1   | Dispatcher, 127 ops via resource |
| Entain    | `entain.cdn`               | 1   | Contentful CMS proxy (form guide is HTML, not a JSON tool) |
| AFL       | `afl.public.core`          | 22  | `/afl/v2/...` |
| AFL       | `afl.public.broadcasting`  | 9   | `/broadcasting/...` |
| AFL       | `afl.public.content`       | 8   | `/content/afl/...` |
| AFL       | `afl.premium.cfs`          | 1   | Dispatcher, 26 ops via resource |
| AFL       | `afl.premium.statspro`     | 1   | Dispatcher, 9 ops via resource |
| AFL       | `afl.premium.keyserver`    | 1   | HLS URL signing |

**Total with everything enabled: 101 tools** (+ 3 always-on meta-tools). Realistic default (`afl.public.core` + `sportsbet.racing` + `entain.graphql`) is ~40 tools.

---

## Pydantic models

`src/sportsdata_mcp/spec.py`:

```python
from __future__ import annotations
from typing import Literal, Annotated
from pydantic import BaseModel, Field, model_validator

# ─── Provider ────────────────────────────────────────────────────────────

class AuthNone(BaseModel):
    type: Literal["none"] = "none"

class AuthStaticHeader(BaseModel):
    type: Literal["static_header"]
    header: str
    value: str | None = None        # if None, value comes from env var below
    env: str | None = None

class AuthAFLWMCTok(BaseModel):
    type: Literal["afl_wmctok"]
    mint_url: str
    mint_headers: dict[str, str] = {}
    header: str = "x-media-mis-token"

AuthSpec = Annotated[AuthNone | AuthStaticHeader | AuthAFLWMCTok, Field(discriminator="type")]

class HashRefresh(BaseModel):
    bundle_host: str
    bundle_url_pattern: str

class Provider(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    doc_url: str | None = None
    base_urls: dict[str, str]                     # e.g. {"public": "...", "premium": "..."}
    default_headers: dict[str, str] = {}
    auth: dict[str, AuthSpec] = {"default": AuthNone()}
    hash_refresh: HashRefresh | None = None

# ─── Endpoints ───────────────────────────────────────────────────────────

ParamLocation = Literal["path", "query", "header", "body", "dispatch"]
ParamType     = Literal["string", "integer", "number", "boolean", "string_csv", "json", "object"]

class Param(BaseModel):
    name: str
    in_:  ParamLocation = Field(alias="in")
    type: ParamType
    required: bool = False
    default: object | None = None
    description: str = ""
    enum: list[object] | None = None

class Example(BaseModel):
    description: str
    params: dict[str, object]

class Endpoint(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    group: str
    capabilities: list[str] = []                   # references entries in _capabilities.yaml
    summary: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET"
    base: str = "default"                          # key into Provider.base_urls
    path: str
    auth: str = "default"                          # key into Provider.auth
    params: list[Param] = []
    response_hint: str | None = None
    examples: list[Example] = []

    @model_validator(mode="after")
    def _path_params_required(self):
        path_param_names = {seg.strip("{}") for seg in self.path.split("/") if seg.startswith("{")}
        for p in self.params:
            if p.in_ == "path" and p.name in path_param_names:
                p.required = True
        return self

# ─── Dispatchers ─────────────────────────────────────────────────────────

class GraphQLOperation(BaseModel):
    name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    variables: str = ""                            # human-readable signature
    verified: bool = False

class TemplatedOperation(BaseModel):
    name: str
    path: str
    path_params:  list[str] = []
    query_params: list[str] = []

class Dispatcher(BaseModel):
    name: str
    group: str
    capabilities: list[str] = []                   # references entries in _capabilities.yaml
    kind: Literal["graphql_persisted", "templated_rest"]
    summary: str
    method: Literal["GET", "POST"] = "GET"
    base: str | None = None                        # for templated_rest
    endpoint: str | None = None                    # for graphql_persisted (full URL)
    auth: str = "default"
    default_headers: dict[str, str] = {}
    catalog_resource: str                          # MCP resource URI
    catalog_source: str | None = None              # ref to graphql.operations etc.
    params: list[Param] = []
    operations: list[TemplatedOperation] = []      # for templated_rest

class GraphQLBlock(BaseModel):
    operations: list[GraphQLOperation] = []

# ─── Reference resources (small static lookup tables) ───────────────────

class ReferenceResource(BaseModel):
    """A static lookup table exposed as an MCP resource, fetched lazily on first read.
    Backed by a normal endpoint call (no params) so it reuses the HTTP client + auth."""
    uri: str                                       # e.g. "afl://teams/idmap"
    summary: str
    base: str = "default"                          # key into Provider.base_urls
    path: str                                      # e.g. "/afl/v2/teams/idmap"
    auth: str = "default"
    mime_type: str = "application/json"

# ─── Capabilities catalogue (loaded once, separately) ───────────────────

class Capability(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")  # e.g. "racing.race_card"
    description: str
    single_provider: bool = False                  # if True, lint won't warn when only one provider exposes it

class CapabilityCatalogue(BaseModel):
    capabilities: list[Capability]

# ─── Top-level spec ─────────────────────────────────────────────────────

class Spec(BaseModel):
    spec_version: int = 1                          # bumped if the spec schema makes a breaking change;
                                                   # loader warns (not fails) on an unknown future version
    provider: Provider
    endpoints:           list[Endpoint] = []
    dispatchers:         list[Dispatcher] = []
    graphql:             GraphQLBlock | None = None
    reference_resources: list[ReferenceResource] = []
```

---

## Tool registration flow

`src/sportsdata_mcp/registry.py`:

```python
async def register_all(mcp: FastMCP, specs: list[Spec], cfg: Config) -> Registered:
    """Walk specs, register only tools whose group matches cfg.enabled_groups."""
    registered = Registered()
    enabled = set(cfg.enabled_groups)

    for spec in specs:
        provider = spec.provider
        auth_mgr = build_auth_manager(provider, cfg)            # one per provider
        http     = HTTPClient(provider, auth_mgr, cfg)

        for endpoint in spec.endpoints:
            if endpoint.group not in enabled:
                continue
            handler = make_endpoint_handler(endpoint, http)
            mcp.tool(name=endpoint.name, description=_describe(endpoint))(handler)
            registered.tools.append(endpoint.name)

        for dispatcher in spec.dispatchers:
            if dispatcher.group not in enabled:
                continue
            handler = make_dispatcher_handler(dispatcher, spec, http)
            mcp.tool(name=dispatcher.name, description=_describe(dispatcher))(handler)
            registered.tools.append(dispatcher.name)
            register_catalog_resource(mcp, dispatcher, spec)
            registered.resources.append(dispatcher.catalog_resource)

    return registered
```

### `make_endpoint_handler`

```python
def make_endpoint_handler(ep: Endpoint, http: HTTPClient) -> Callable:
    # Build a JSON-schema-typed signature dynamically so FastMCP can derive the tool schema
    sig_params = [
        inspect.Parameter(
            p.name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=p.default if not p.required else inspect.Parameter.empty,
            annotation=_python_type(p),
        )
        for p in ep.params
    ]
    sig = inspect.Signature(parameters=sig_params)

    async def handler(**kwargs):
        url    = _interpolate_path(ep, kwargs)
        query  = _build_query(ep, kwargs)
        header = _build_headers(ep, kwargs)
        body   = _build_body(ep, kwargs)         # None unless the endpoint declares `in: body` params
        # request_json applies the size/status/content-type guards (see HTTP client) instead of a bare r.json()
        return await http.request_json(
            method=ep.method, base=ep.base, url=url,
            params=query, headers=header, json_body=body, auth_key=ep.auth,
        )

    handler.__signature__ = sig
    handler.__name__      = ep.name
    handler.__doc__       = _describe(ep)
    return handler
```

The dynamic signature is critical — FastMCP introspects it to generate the JSON-schema the MCP client sees. Without it the tool schema would have no parameter types.

### `_describe`

Renders the tool description shown to the model. Keep terse to save tokens:

```
{summary}

Returns: {response_hint or "(JSON object)"}

Example: {first example.description}
```

No multiline blob — every line costs tokens × N tools.

---

## HTTP client

`src/sportsdata_mcp/http_client.py`:

```python
MAX_RESPONSE_BYTES_DEFAULT = 512_000   # ~128K tokens worst case; configurable per provider

class HTTPClient:
    def __init__(self, provider: Provider, auth_mgr: AuthManager, cfg: Config):
        self._provider = provider
        self._auth     = auth_mgr
        self._max_bytes = cfg.max_response_bytes_for(provider.id)   # default MAX_RESPONSE_BYTES_DEFAULT
        self._client   = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            headers=provider.default_headers,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()          # called on server shutdown (see server.py lifespan)

    async def request(self, *, method, base, url, params=None, headers=None, json_body=None, auth_key="default"):
        full_url = self._provider.base_urls[base] + url
        merged_headers = {**(headers or {})}

        # Inject auth
        auth_spec = self._provider.auth.get(auth_key) or AuthNone()
        if not isinstance(auth_spec, AuthNone):
            token_header_name, token_value = await self._auth.get(auth_key)
            merged_headers[token_header_name] = token_value

        # One retry on 401 — invalidate auth, refetch, retry
        for attempt in (0, 1):
            r = await self._client.request(method, full_url, params=params, headers=merged_headers, json=json_body)
            if r.status_code == 401 and attempt == 0 and not isinstance(auth_spec, AuthNone):
                self._auth.invalidate(auth_key)
                token_header_name, token_value = await self._auth.get(auth_key)
                merged_headers[token_header_name] = token_value
                continue
            break
        return r

    async def request_json(self, **kwargs) -> dict | list:
        """Request + defensive decode. This — not r.json() — is what tool handlers call."""
        r = await self.request(**kwargs)
        return self._decode(r)

    def _decode(self, r: httpx.Response) -> dict | list:
        # 1. Size guard — refuse to dump megabytes into the model's context.
        body = r.content
        if len(body) > self._max_bytes:
            raise ToolError(
                f"Response from {self._provider.id} was {len(body):,} bytes "
                f"(limit {self._max_bytes:,}). Narrow the query (date range, pageSize, filters) and retry.",
                recoverable=True, code="RESPONSE_TOO_LARGE",
            )

        # 2. Status guard — surface bot-blocks / rate-limits / server errors as clean ToolErrors.
        if r.status_code == 429:
            raise ToolError(
                f"{self._provider.id} rate-limited the request (HTTP 429). Wait and retry; "
                f"the per-provider rate limiter normally prevents this.",
                recoverable=True, code="RATE_LIMITED",
            )
        if r.status_code == 403:
            raise ToolError(
                f"{self._provider.id} blocked the request (HTTP 403) — likely bot detection or geo-block. "
                f"Body starts: {_snippet(r)}",
                recoverable=False, code="BLOCKED",
            )
        if r.status_code >= 400:
            raise ToolError(
                f"{self._provider.id} returned HTTP {r.status_code}. Body starts: {_snippet(r)}",
                recoverable=r.status_code >= 500, code=f"HTTP_{r.status_code}",
            )

        # 3. Content-type / decode guard — Akamai/Cloudflare challenges return HTML, not JSON.
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            raise ToolError(
                f"{self._provider.id} returned non-JSON ({ctype or 'unknown'}; HTTP {r.status_code}). "
                f"Often a bot-challenge page. Body starts: {_snippet(r)}",
                recoverable=False, code="NON_JSON_RESPONSE",
            )
        try:
            return r.json()
        except json.JSONDecodeError:
            raise ToolError(
                f"{self._provider.id} sent a JSON content-type but the body did not parse. "
                f"Body starts: {_snippet(r)}",
                recoverable=False, code="JSON_DECODE_ERROR",
            )

def _snippet(r: httpx.Response, n: int = 200) -> str:
    return r.text[:n].replace("\n", " ").strip()
```

Retry policy: one retry on **401** (auth invalidation). **429** → clean `RATE_LIMITED` ToolError (no auto-retry — the model decides). **403** → `BLOCKED` (bot/geo). **4xx/5xx** → status-coded ToolError (5xx flagged recoverable). **Non-JSON / unparseable** bodies (Akamai/Cloudflare challenge pages) → `NON_JSON_RESPONSE` rather than a raw `JSONDecodeError`. A **size guard** (default 512 KB, per-provider configurable) prevents a single huge payload from blowing the model's context. No 5xx auto-retry, no timeout retry, no caching. Single-flight inside the auth provider only.

---

## Auth providers

`src/sportsdata_mcp/auth/base.py`:

```python
class AuthProvider(Protocol):
    async def get(self) -> tuple[str, str]: ...    # returns (header_name, header_value)
    def invalidate(self) -> None: ...
```

### `auth/none.py`

```python
class NullAuthProvider:
    async def get(self):       raise RuntimeError("NullAuthProvider.get called")
    def invalidate(self):      pass
```

### `auth/header.py`

```python
class StaticHeaderAuthProvider:
    """For auth that's just a header-and-value pair (e.g. Ladbrokes Content-Type, or an env-var-supplied API key)."""
    def __init__(self, spec: AuthStaticHeader):
        if spec.env:
            value = os.environ.get(spec.env)
            if not value:
                raise AuthMissingError(f"Env var {spec.env} not set; required for {spec.header}")
        else:
            value = spec.value
        self._header = spec.header
        self._value  = value

    async def get(self):     return self._header, self._value
    def invalidate(self):    pass
```

### `auth/afl.py`

```python
class AFLTokenProvider:
    """Mints anonymous x-media-mis-token from /cfs/afl/WMCTok and caches it in memory."""
    def __init__(self, spec: AuthAFLWMCTok, http: httpx.AsyncClient):
        self._spec  = spec
        self._http  = http
        self._token: str | None = None
        self._lock  = asyncio.Lock()

    async def get(self):
        if self._token:
            return self._spec.header, self._token
        async with self._lock:
            if self._token:
                return self._spec.header, self._token
            r = await self._http.post(self._spec.mint_url, headers=self._spec.mint_headers)
            r.raise_for_status()
            self._token = r.json()["token"]
            return self._spec.header, self._token

    def invalidate(self):
        self._token = None
```

---

## Dispatcher patterns

### `dispatchers/graphql_persisted.py`

```python
def make_graphql_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in (spec.graphql.operations if spec.graphql else [])}

    async def handler(*, operation: str, variables: dict | None = None):
        op = ops_by_name.get(operation)
        if not op:
            raise ToolError(
                f"Unknown operation '{operation}'. "
                f"Read the {disp.catalog_resource} resource to list valid operations.",
                recoverable=True,
            )
        params = {
            "operationName": operation,
            "variables":  json.dumps(variables or {}),
            "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": op.sha256}}),
        }
        # persisted-query-not-found comes back as HTTP 200 + JSON error envelope, so request_json handles it;
        # bot-challenge / 5xx are converted to ToolErrors by the client's decode guards.
        body = await http.request_json(method=disp.method, base="default", url=disp.endpoint,
                                       params=params, headers=disp.default_headers, auth_key=disp.auth)
        if _is_persisted_query_not_found(body):
            raise PersistedQueryNotFoundError(
                operation=operation, hash_prefix=op.sha256[:16],
                refresh_cmd=f"sportsdata-mcp refresh-hashes {spec.provider.id}",
            )
        return body

    handler.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter("operation", inspect.Parameter.KEYWORD_ONLY, annotation=str),
            inspect.Parameter("variables", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
        ]
    )
    handler.__name__ = disp.name
    handler.__doc__  = disp.summary
    return handler
```

### `dispatchers/templated_rest.py`

```python
def make_templated_rest_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in disp.operations}

    async def handler(*, operation: str, path_params: dict, query_params: dict | None = None):
        op = ops_by_name.get(operation)
        if not op:
            raise ToolError(f"Unknown operation '{operation}'. Read {disp.catalog_resource}.", recoverable=True)
        for required in op.path_params:
            if required not in path_params:
                raise ToolError(f"operation '{operation}' requires path_param '{required}'", recoverable=True)
        url = op.path.format(**path_params)
        return await http.request_json(method=disp.method, base=disp.base, url=url,
                                       params=query_params or {}, headers=disp.default_headers, auth_key=disp.auth)

    handler.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter("operation",    inspect.Parameter.KEYWORD_ONLY, annotation=str),
            inspect.Parameter("path_params",  inspect.Parameter.KEYWORD_ONLY, annotation=dict),
            inspect.Parameter("query_params", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
        ]
    )
    handler.__name__ = disp.name
    handler.__doc__  = disp.summary
    return handler
```

---

## Resources

Three categories of resources are registered:

1. **Capability catalogue** (`sportsdata://capabilities`) — always registered, lists every capability and which enabled providers expose it.
2. **Dispatcher catalogues** — one per dispatcher (e.g. `entain://graphql/operations`, `afl://cfs/operations`).
3. **Reference data** — small, stable lookup tables (`afl://teams/idmap`, `sportsbet://classes`, `entain://categories/sport`) populated lazily on first read.

`src/sportsdata_mcp/resources/builders.py`:

```python
def register_graphql_catalog(mcp: FastMCP, disp: Dispatcher, spec: Spec) -> None:
    @mcp.resource(disp.catalog_resource, mime_type="application/json")
    async def _catalog() -> str:
        ops = [{"name": op.name, "variables": op.variables, "verified": op.verified}
               for op in (spec.graphql.operations if spec.graphql else [])]
        return json.dumps({
            "provider":   spec.provider.id,
            "dispatcher": disp.name,
            "operations": ops,
            "note":       f"Call {disp.name}(operation=<name>, variables={{...}}) to invoke. Hashes are managed server-side.",
        }, indent=2)

def register_templated_rest_catalog(mcp: FastMCP, disp: Dispatcher) -> None:
    @mcp.resource(disp.catalog_resource, mime_type="application/json")
    async def _catalog() -> str:
        return json.dumps({
            "dispatcher": disp.name,
            "operations": [op.model_dump() for op in disp.operations],
        }, indent=2)

def register_capabilities_resource(mcp: FastMCP, catalogue: CapabilityCatalogue, specs: list[Spec], enabled_groups: set[str]) -> None:
    """Always-on resource. Returns the capability catalogue with which enabled providers expose each one."""
    @mcp.resource("sportsdata://capabilities", mime_type="application/json")
    async def _capabilities() -> str:
        provider_index = _build_provider_index(specs, enabled_groups)   # cap_id → [(provider, tool_name), …]
        out = []
        for cap in catalogue.capabilities:
            providers = provider_index.get(cap.id, [])
            out.append({
                "id":            cap.id,
                "description":   cap.description,
                "providers":     [{"provider": p, "tool": t} for p, t in providers],
                "comparable":    len(providers) >= 2,
            })
        return json.dumps({"capabilities": out}, indent=2)

def register_reference_resource(mcp: FastMCP, ref: ReferenceResource, http: HTTPClient) -> None:
    """Lazily-populated static lookup table. First read does one GET (with the size/decode guards);
    the result is cached in-process for the life of the server (these tables are stable)."""
    cache: dict[str, object] = {}
    @mcp.resource(ref.uri, mime_type=ref.mime_type)
    async def _ref() -> str:
        if "data" not in cache:
            cache["data"] = await http.request_json(method="GET", base=ref.base, url=ref.path, auth_key=ref.auth)
        return json.dumps(cache["data"], indent=2)
```

`reference_resources` are only registered for providers that have **at least one enabled group** (so a disabled provider exposes no resources). Sha256 hashes are intentionally **not** in the dispatcher catalogue resources — they're never useful to the model and add bulk. The one-shot in-process cache here is the *only* caching in the system, and it's justified: these tables (team/venue/class id-maps) effectively never change within a server session, and re-fetching them on every read would be wasteful.

---

## Config resolution

`src/sportsdata_mcp/config.py`:

### Resolution order

1. `--config PATH` CLI flag (highest priority)
2. `SPORTSDATA_MCP_CONFIG` env var
3. `./sportsdata-mcp.yaml` (cwd)
4. `~/.config/sportsdata-mcp/config.yaml`
5. Defaults (no groups enabled)

### Groups can be set three ways (in order of precedence)

1. `SPORTSDATA_MCP_GROUPS` env var (comma-separated)
2. `enabled_groups:` in the config file
3. Empty (server starts with no functional tools, only `list_available_groups`)

### Example `sportsdata-mcp.yaml`

```yaml
# Tool groups to expose. Each maps to a chunk of providers/endpoints.
# Run `sportsdata-mcp list-groups` to see all available groups.
enabled_groups:
  - afl.public.core
  - afl.public.broadcasting
  - afl.premium.cfs              # uses anonymous WMCTok token automatically
  - sportsbet.racing
  - entain.graphql               # 1 dispatcher tool, 127 ops via resource

# Optional per-provider tweaks
providers:
  afl:
    request_timeout_seconds: 30
    max_response_bytes: 512000     # guard against dumping huge payloads into the model's context
    rate_limit_rps: 10             # per-provider token bucket (see Phase 6)

# Optional secrets — most providers need nothing. Env vars take precedence over this section.
secrets: {}
```

`max_response_bytes` defaults to 512 KB and can be raised per provider (e.g. for a bulk stats endpoint you knowingly want whole) or lowered globally. Over-limit responses raise a recoverable `RESPONSE_TOO_LARGE` ToolError telling the model to narrow its query.

### Meta-tools (always registered)

Three meta-tools are always exposed, regardless of which groups are enabled:

#### `list_available_groups()`

Returns the catalogue of all groups across all specs and which are currently enabled:

```json
{
  "enabled": ["afl.public.core", "sportsbet.racing"],
  "available": {
    "afl.public.core":         {"tools": 22, "description": "..."},
    "afl.public.broadcasting": {"tools": 9,  "description": "..."},
    "entain.graphql":          {"tools": 1,  "description": "Dispatcher for 127 GraphQL operations"}
  },
  "hint": "Edit sportsdata-mcp.yaml `enabled_groups` and restart the server."
}
```

On a fresh install (no groups enabled) this is the only functional tool the model has, so it can guide the user to enable what they want.

#### `list_tools_by_capability(capability: str | None = None)`

Discovers comparable tools across enabled providers. See [Capability tags & multi-provider composition](#capability-tags--multi-provider-composition) for the full design. This is the entry point for any cross-provider question.

#### `list_resources()`

Lists all registered MCP resources (dispatcher catalogues, capability map, reference data). The model uses this when it isn't sure which catalogue resource to read.

---

## CLI commands

`src/sportsdata_mcp/cli.py`:

| Command | Behaviour |
|---|---|
| `sportsdata-mcp serve` (default) | Start the MCP stdio server. Optional `--config PATH`. |
| `sportsdata-mcp list-groups` | Print every group across every spec, with tool count and description. Exit 0. |
| `sportsdata-mcp lint [SPEC ...]` | Validate one or more YAML specs against `_schema.yaml`. Default: all of `specs/*.yaml`. Exit nonzero on any failure. |
| `sportsdata-mcp doctor` | Per-provider sanity check. For each enabled group: pings the base URL, mints auth tokens if required, reports OK/FAIL with HTTP code and error body. |
| `sportsdata-mcp refresh-hashes PROVIDER` | Fetches the latest deployed front-end bundle, extracts operation→sha256 pairs, diffs against the spec, writes the updated spec, prints a coloured diff. |
| `sportsdata-mcp version` | Print `sportsdata-mcp 0.1.0 (FastMCP X.Y.Z, httpx X.Y)`. |

### `sportsdata-mcp doctor` example output

```
$ sportsdata-mcp doctor
Loading config: /Users/dan/.config/sportsdata-mcp/config.yaml
Enabled groups: afl.public.core, afl.premium.cfs, entain.graphql

[afl/public]              GET https://aflapi.afl.com.au/afl/v2/competitions
                          → 200 OK, 16 competitions
[afl/premium]             Minting x-media-mis-token via /cfs/afl/WMCTok
                          → token acquired, expires unknown
[afl/premium]             GET https://api.afl.com.au/cfs/afl/matchItem/CD_M20260141201
                          → 200 OK
[entain/default]          GET https://api.ladbrokes.com.au/v2/racing/search
                          → 200 OK
[entain/graphql]          POST-stub https://api.ladbrokes.com.au/gql/router (HomeSportsScreen)
                          → 200 OK, payload 99 KB

✅ All checks passed.
```

### `sportsdata-mcp refresh-hashes entain` example output

```
$ sportsdata-mcp refresh-hashes entain
🔍 Fetching https://www.ladbrokes.com.au/
🔍 Locating /assets/vendor-graphql-ops-web-*.js
   → /assets/vendor-graphql-ops-web-D59Og4AP.js
🔍 Downloading bundle (967 KB) … done
🔍 Extracting [name, sha256] pairs from minified AST
   → 127 operations

📋 Diff against specs/entain.yaml:
   • RacingRaceCardScreenWeb:        7085b5be…eedff81 → d59b563b…190cbbc7  ✏️
   • SportingIconSets:               830e8f22…521b6e  → 13dbe345…ae3ab510  ✏️
   • SportingCompetitionScreen:      13650ba9…ededed8c → 1a346cbe…dc81c93e ✏️
   • 124 unchanged

✅ specs/entain.yaml updated (3 hashes refreshed)
   Restart the MCP server for changes to take effect.
```

---

## Error contract

`src/sportsdata_mcp/errors.py`:

```python
class ToolError(Exception):
    """Base error returned to the MCP client. Includes a recoverable flag so the model knows whether to retry."""
    def __init__(self, message: str, *, recoverable: bool = False, code: str | None = None):
        self.message = message
        self.recoverable = recoverable
        self.code = code

class AuthMissingError(ToolError):
    """Raised when an auth secret (env var) is required and missing."""

class PersistedQueryNotFoundError(ToolError):
    """Raised when a GraphQL persisted hash is no longer registered with the gateway."""
    def __init__(self, *, operation: str, hash_prefix: str, refresh_cmd: str):
        super().__init__(
            f"GraphQL operation '{operation}' (hash {hash_prefix}…) is no longer registered "
            f"with the gateway. Run `{refresh_cmd}` and restart the MCP server.",
            recoverable=True,
            code="PERSISTED_QUERY_NOT_FOUND",
        )
```

All ToolErrors are caught by a top-level handler in `server.py` and serialised to MCP's standard error envelope so the model sees a structured `{message, code, recoverable}`.

---

## Implementation phases

Each phase is 1-2 days of focused work. Acceptance criteria are concrete and testable.

### Phase 1 — Bones + capability framework (2 days)

> **Status: ✅ Complete (2026-05-30).** All models, loader, config, HTTP client, auth scaffolding, CLI (`serve`/`list-groups`/`lint`/`version`), server + 3 meta-tools, capabilities resource, and unit tests landed. `lint` green, server boots.

**Tasks:**
1. `pyproject.toml` with deps: `fastmcp >= 0.4`, `httpx[http2] >= 0.27`, `pydantic >= 2.5`, `pyyaml >= 6.0`, `click >= 8.1` (CLI).
2. `spec.py` — all pydantic models above, including `ReferenceResource`, `Capability`, `CapabilityCatalogue`, and the `spec_version` field (loader logs a warning, not an error, on an unknown future version).
3. `spec_loader.py` — enumerate packaged specs via `importlib.resources.files("sportsdata_mcp.specs")` (NOT a cwd glob), parse into `Spec` objects, raise on duplicate `name` across all specs. Load `_capabilities.yaml` from the same package dir.
4. `config.py` — load + merge config from CLI/env/file in the documented order; expose `max_response_bytes_for(provider_id)` and `rate_limit_rps_for(provider_id)`.
5. `http_client.py` — `HTTPClient` with the `request` / `request_json` / `_decode` split: size guard, status guard (401 retry, 429/403 surfacing, 4xx/5xx), and non-JSON/decode guards. `aclose()` for lifecycle.
6. `auth/none.py` + `auth/header.py` + `auth/base.py` protocol.
7. `cli.py` — `serve`, `list-groups`, `lint`, `version` commands. `doctor` and `refresh-hashes` are stubs for later.
8. `server.py` — FastMCP bootstrap, registers `list_available_groups`, `list_tools_by_capability`, `list_resources` meta-tools, calls `registry.register_all`, registers `sportsdata://capabilities` resource.
9. `registry.py` — `make_endpoint_handler`, `_describe`, dynamic signatures, capability index builder.
10. `resources/builders.py` — `register_capabilities_resource` implementation.
11. `specs/_capabilities.yaml` — initial catalogue (the ~30 entries listed above).
12. **Lint rules:**
    - Every `capabilities:` entry on an endpoint exists in `_capabilities.yaml`.
    - No duplicate `Capability.description` (typo guard).
    - Warning when a capability has only one provider exposing it AND isn't marked `single_provider: true`.
13. Tests: `tests/unit/test_spec_load.py`, `test_config.py`, `test_url_builder.py`, `test_capabilities.py` (lint rules, capability index build), `test_http_decode.py` (size guard, 429/403, non-JSON → ToolError).

**Acceptance:**
- `sportsdata-mcp lint` passes with one stub spec (`specs/_template.yaml` with one fake endpoint tagged with one capability).
- `sportsdata-mcp lint` fails with a clear message when a spec references an undefined capability.
- `sportsdata-mcp version` prints expected.
- `python -m sportsdata_mcp serve` starts and `list_available_groups` returns `{"enabled": [], "available": {...}}`, `list_tools_by_capability()` returns `{}` (no enabled tools yet).
- Reading `sportsdata://capabilities` returns the full catalogue with empty `providers` arrays.
- Specs load via `importlib.resources` — confirmed by running `list-groups` from a directory with no `./specs/`.
- A mocked oversized / non-JSON / 429 response each raises the expected coded `ToolError`.
- `pytest tests/unit/` passes.

### Phase 2 — AFL public end-to-end (1-2 days)

> **Status: ✅ Complete (2026-05-30).** `specs/afl.yaml` ships 39 public endpoints (core 22 / broadcasting 9 / content 8). `enabled_groups: [afl.public.core]` exposes exactly 22 tools (+3 meta). Lint green; `examples/claude-desktop-config.json` added; `tests/integration/test_afl_public.py` (7 live tests) collects clean.

**Tasks:**
1. `specs/afl.yaml` with `provider`, all `afl.public.core` (22 endpoints), `afl.public.broadcasting` (9), `afl.public.content` (8) — total ~39 endpoints. Every endpoint tagged with appropriate `capabilities:`.
2. Run `sportsdata-mcp lint specs/afl.yaml` until clean.
3. Manual verify against live `aflapi.afl.com.au` via the integration tests.
4. Add `examples/claude-desktop-config.json` + smoke-test inside Claude Desktop.
5. Tests: `tests/integration/test_afl_public.py` covering at least: competitions list, ladders, single match, broadcasting events, text articles.

**Acceptance:**
- With `enabled_groups: [afl.public.core]`, server exposes exactly 22 tools (+ 3 meta-tools).
- All `afl_*` tools return real JSON when called via MCP test client against live API.
- `list_tools_by_capability("sport.match_detail")` returns the AFL tools that expose it.
- Reading `sportsdata://capabilities` now shows AFL as a provider on every capability it implements.
- Integration tests pass with `pytest -m live`.

### Phase 3 — AFL premium auth + CFS dispatcher (1-2 days)

> **Status: ✅ Complete (2026-05-30).** `auth/afl.py` WMCTok provider (lock + 401 re-mint) wired into `HTTPClient`. `afl.yaml` gained `base_urls.premium` + `auth.premium`, an `afl_cfs_call` dispatcher (26 ops → `afl://cfs/operations`) and an `afl_statspro_call` dispatcher (9 ops → `afl://statspro/operations`). Tests: `test_auth_afl.py` (9), `test_dispatchers.py` (4), `test_afl_premium.py` (live, xfails when anon WMCTok unavailable). `doctor`'s premium probe is deferred to Phase 6 (where `doctor` is fully built).

**Tasks:**
1. `auth/afl.py` — AFLTokenProvider, with async lock and 401 retry.
2. Add `auth.premium` block to `specs/afl.yaml`.
3. `dispatchers/templated_rest.py`.
4. Add the `afl.premium.cfs` dispatcher with all ~27 CFS endpoints from `documentation/AFL.md` as templated operations.
5. Add the `afl.premium.statspro` dispatcher with all 9 StatsPro endpoints.
6. Resource builders: `afl://cfs/operations`, `afl://statspro/operations`.
7. Tests: `tests/unit/test_auth_afl.py` (mocked WMCTok), `tests/integration/test_afl_premium.py` (live, anonymous).

**Acceptance:**
- `sportsdata-mcp doctor` reports `afl/premium → token acquired, GET matchItem/... 200 OK`.
- Calling `afl_cfs_call(operation="matchItem", path_params={"matchProviderId": "CD_M20260141201"})` via MCP returns real data.
- Calling with a bogus operation name returns a recoverable ToolError mentioning the catalogue resource.
- Reading the `afl://cfs/operations` resource lists 27 operations with paths + param lists.

### Phase 4 — Entain dispatcher + refresh-hashes CLI (1-2 days)

> **Status: ✅ Complete (2026-05-30).** `specs/entain.yaml` ships 13 `entain.rest` endpoints + the `entain_graphql_call` dispatcher + all 127 persisted ops. `refresh/entain_hashes.py` extracts the live bundle's `[`name`,`hash`]` tuples (verified against `vendor-graphql-ops-web-Bq27dXtq.js`); `refresh-hashes entain` ran live and refreshed 3 drifted hashes. `entain://graphql/operations` lists all 127 ops (no hashes). Live `entain_graphql_call(HomeSportsScreen)` returned real gateway data. Unit + offline integration tests green (74 passed); `PersistedQueryNotFoundError` path covered.

**Tasks:**
1. `specs/entain.yaml` — `provider` block, ~16 REST endpoints under `entain.rest`, the GraphQL dispatcher under `entain.graphql`, full `graphql.operations` block with all 127 sha256+variable pairs.
2. `dispatchers/graphql_persisted.py`.
3. `refresh/entain_hashes.py` — fetches bundle, extracts pairs, diffs spec, writes back.
4. `cli.py` — implement `refresh-hashes PROVIDER` command using `refresh/`.
5. `errors.py` — `PersistedQueryNotFoundError`.
6. Resource builder: `entain://graphql/operations`.
7. Tests: `tests/unit/test_dispatchers.py::test_graphql_persisted_not_found`, `tests/integration/test_entain.py`.

**Acceptance:**
- `sportsdata-mcp refresh-hashes entain` runs against the live bundle and prints a diff.
- Calling `entain_graphql_call(operation="HomeSportsScreen", variables={...})` returns real data from `api.ladbrokes.com.au/gql/router`.
- Calling with a stale-hash op returns `PERSISTED_QUERY_NOT_FOUND` error with `refresh-hashes` hint.
- Reading `entain://graphql/operations` resource returns JSON list of all 127 ops (without hashes).

### Phase 5 — Sportsbet + remaining surfaces + comparator demo (1-2 days)

> **Status: ✅ Complete (2026-05-31).** `specs/sportsbet.yaml` ships 44 tools across `sportsbet.racing` (15), `sportsbet.sports` (14), `sportsbet.results` (2), `sportsbet.cross` (12) + the `sportsbet_graphql_call` dispatcher (`EventStats`). Capabilities overlap Entain where it counts: `racing.race_card`, `racing.same_race_multi`, `sport.event_markets`, `sport.prices`, `sport.same_game_multi`, `sport.in_play`, `content.promo` all now resolve to ≥2 providers (verified via `list_tools_by_capability`). Added `entain.cdn` (Contentful proxy on the www host — form guide is HTML, not modeled) + the `racing.same_race_multi`/`sport.same_game_multi` tags on `entain_graphql_call`, and `afl.premium.keyserver` (HLS URL signing). `tests/integration/test_sportsbet.py` green (offline suite 77 passed); a live `sportsbet_racing_allracing` probe returned real data. Comparator demo shipped: `examples/comparator-config.yaml` (Sportsbet + Entain) + `examples/comparator-prompt.md` (worked "Storm v Cowboys odds" flow). `racing.race_results` remains Sportsbet-only (lint warning, acceptable — Entain exposes no clean results endpoint).

**Tasks:**
1. `specs/sportsbet.yaml` covering `sportsbet.racing`, `sportsbet.sports`, `sportsbet.results`, `sportsbet.cross`, `sportsbet.graphql` (single dispatcher with the `EventStats` op). **Every endpoint tagged with capabilities that overlap with Entain where appropriate** — that's the whole point of the capability system.
2. `entain.cdn` group for Contentful proxy.
3. `afl.premium.keyserver` single-tool group for `/keyserver/urlSigning`.
4. Tests: `tests/integration/test_sportsbet.py`.
5. **Comparator demo** in `examples/`:
   - `examples/comparator-prompt.md` — a worked Claude prompt that asks "compare odds for Storm v Cowboys across my bookies", showing the expected tool-call sequence.
   - `examples/comparator-config.yaml` — `sportsdata-mcp.yaml` that enables Sportsbet + Entain for cross-bookie comparison.
6. Lint pass: confirm every "comparable" capability now has ≥2 providers exposing it (or is marked `single_provider: true`).

**Acceptance:**
- All groups in the [group table](#group-naming-convention) are populated.
- Total tool count matches table when all groups enabled.
- `list_tools_by_capability("racing.race_card")` returns both `sportsbet_racecard_with_context` and `entain_graphql_call` (the Entain dispatcher serves `RacingRaceCardScreenWeb`).
- `list_tools_by_capability("sport.event_markets")` returns both Sportsbet's markets tool and Entain's GraphQL dispatcher.
- Running the comparator-demo prompt against a real Claude session produces a sensible side-by-side comparison.

### Phase 6 — Quality & DX (1 day)

> **Status: ✅ Complete (2026-05-31).** (1) `doctor` was built in Phase 5's tail — per-provider auth-mint + one representative probe per enabled group (examples → no-required-param → SKIP), GraphQL probed via a zero-variable verified op, transport/non-JSON/≥400 all FAIL, exit nonzero on any failure; ran live (4 ok, 0 failed, exit 0). (2) Logging: `http_client._decode` now logs WARNING on 429/403/oversize, ERROR on 5xx/non-JSON/decode-fail (request INFO + 401 WARNING already existed); `cli.py` silences `httpx`/`httpcore` to WARNING unless `-v`. (3) Token-bucket rate limiter (`_TokenBucket`, per-provider `rate_limit_rps`) already shipped in Phase 1's HTTP client. (4) `registry._guard` wraps every endpoint/dispatcher handler: `httpx.TimeoutException` → `UPSTREAM_TIMEOUT`, other `httpx.HTTPError` → `TRANSPORT_ERROR` (both recoverable, actionable message that survives FastMCP's masking), our own `ToolError` passes through untouched; signature/annotations preserved so the JSON-schema is unchanged. Verified empirically that FastMCP converts exceptions *before* middleware sees them, so a handler-level guard (not middleware) is required. (5) Server lifecycle: `build_server` attaches a FastMCP `lifespan` that `await reg.aclose()`s every provider `HTTPClient` on shutdown (clients stay eagerly built so `build_server` callers/tests work without a lifespan); confirmed clients close on lifespan exit. (6) README rewritten with quickstart, configuration, full group catalogue, capability/comparison flow, per-provider notes, CLI reference, and a contributing guide. Offline suite 81 passed (4 new `_guard` tests), ruff clean.

**Tasks:**
1. `sportsdata-mcp doctor` — full implementation per the example output above. Doctor doubles as the **REST contract check**: for non-GraphQL providers there is no hash-refresh, so `doctor` hitting each base URL + a representative endpoint per group is how silent path/param drift is caught.
2. Structured stderr logging using stdlib `logging`. Levels: INFO (tool invocations), WARNING (auth invalidations, retries, 429s), ERROR (5xx, unrecoverable, non-JSON bodies).
3. Per-provider token-bucket rate limiter (default 10 RPS, configurable per provider via `rate_limit_rps`). This is the first line of defence against the 429/403 paths handled in the HTTP client.
4. Top-level error handler in `server.py` that catches `httpx.HTTPError` (timeouts, connection errors) and `ToolError`, serialising both to the MCP error envelope `{message, code, recoverable}`. The HTTP client's decode guards already convert status/content-type problems into `ToolError`; this handler is the catch-all for transport-level failures.
5. **Server lifecycle**: FastMCP `lifespan` that builds one `HTTPClient` per provider on startup and `await client.aclose()` for each on shutdown, so connection pools and the AFL token are released cleanly.
6. README with quickstart, group catalogue, per-provider notes, contributing.

**Acceptance:**
- `sportsdata-mcp doctor` exits 0 with all groups enabled, and exits nonzero (with the offending path) if a previously-working REST endpoint now 404s — proving it catches drift.
- README renders correctly on GitHub.
- Rate-limit test: 100 rapid calls to one provider don't trigger Akamai.
- A mocked HTML bot-challenge response surfaces as a `NON_JSON_RESPONSE` ToolError, not a stack trace.

### Phase 7 — Distribution (½ day)

> **Status: ✅ Complete (2026-05-31), PyPI publish deferred.** (1) `pyproject.toml` already carried the `sportsdata-mcp = "sportsdata_mcp.cli:main"` entry point, MIT licence, and `[tool.hatch.build]` include of `src/sportsdata_mcp/specs/*.yaml`; added the 3.11/3.12/**3.13** classifiers to match the runtime + CI matrix. (2) `.github/workflows/ci.yml`: a `test` matrix (3.11/3.12/3.13) running `ruff check`, `sportsdata-mcp lint`, and `pytest -m "not live"` (live tests never run in CI), plus a `package` job that builds the wheel and runs the CLI from `/tmp` on a clean venv. (3) **uvx/packaging verified locally**: `pip wheel .` produced a wheel containing all 6 `specs/*.yaml`; installed into a fresh venv and ran `sportsdata-mcp version` + `list-groups` from `/tmp` with no cwd `./specs/` — proving `importlib.resources` loads specs from the package. (4) PyPI publish intentionally deferred. (5) `examples/claude-code-mcp.json` added (uvx + `claude mcp add` instructions) alongside the existing `claude-desktop-config.json`.

**Tasks:**
1. `pyproject.toml`: entry point `sportsdata-mcp = "sportsdata_mcp.cli:main"`, classifiers, MIT licence, and **`[tool.hatch.build]` include of `src/sportsdata_mcp/specs/*.yaml`** so the specs ship in the wheel.
2. GitHub Actions CI: lint specs, run unit tests on push.
3. `uvx sportsdata-mcp` works (test on a clean machine) — including that `importlib.resources` finds the packaged specs (not a cwd `./specs/`).
4. Publish to PyPI as `sportsdata-mcp`.
5. `examples/claude-desktop-config.json` + `examples/claude-code-mcp.json` with copy-paste-ready blocks.

**Acceptance:**
- `pip install sportsdata-mcp && sportsdata-mcp version` works on a clean Python 3.11 install.
- `pip install` into a fresh venv, `cd /tmp`, then `sportsdata-mcp list-groups` lists all AFL/Sportsbet/Entain groups — proving specs load from the package, not the working directory.
- Adding the example JSON to Claude Desktop / Claude Code makes the tools appear after a restart.

---

## Testing strategy

| Layer | Tool | What it covers |
|---|---|---|
| Spec validation | pydantic | All YAML specs parse, no duplicate names within or across specs. |
| Spec linting | `sportsdata-mcp lint` in CI | Every group referenced by an endpoint matches `{provider}.{surface}.{category?}`. Every path param appears in `params`. |
| URL builder | pytest unit | Path interpolation, query-string encoding, CSV joining, JSON-encoding-then-URL-encoding. |
| Tool registration | pytest unit | With `enabled_groups: [X]`, only matching tools are registered. Disabled groups produce zero tools. Always-on meta-tools still registered. |
| Auth | pytest unit | WMCTok flow with mocked httpx: cache hit, cache miss, 401 invalidation, single-flight under contention. |
| Dispatcher | pytest unit | Unknown op → recoverable error. Persisted-query-not-found path. Templated-rest with missing path_params. |
| Response decoding | pytest unit | Over-`max_response_bytes` → `RESPONSE_TOO_LARGE`. 429 → `RATE_LIMITED`, 403 → `BLOCKED`, 5xx → recoverable. Non-JSON / HTML challenge → `NON_JSON_RESPONSE` (not a stack trace). `in: body` params serialise into the request body. |
| Packaging | pytest unit | `spec_loader` finds specs via `importlib.resources` with no `./specs/` on disk (run from a tmp cwd). |
| Integration | pytest `-m live` | Real HTTP to each provider's public base URL. Skipped by default to keep CI fast. Run locally via `make test-live`. |
| MCP protocol | FastMCP test client | `list_tools` returns expected names. `call_tool` round-trips. `read_resource` returns valid JSON. |

CI runs unit tests on every push. Integration tests are manual / local only (they hit live third-party endpoints and shouldn't gate merges). **Contract drift for REST providers** (AFL, Sportsbet) has no automatic hash-style detector the way Entain's GraphQL does — `sportsdata-mcp doctor` is the intended periodic check, and the live integration suite is the deeper one. A red `doctor` run is the signal a spec needs updating.

---

## Adding a new provider

Adding new providers is the **primary forward-looking work** for this project — and "provider" means any sports JSON API (bookmaker, league, aggregator, fantasy, analytics). The capability-tag system means each new provider plugs into existing comparisons automatically — tag an endpoint `racing.race_card` and it shows up in `list_tools_by_capability("racing.race_card")` next to Sportsbet and Ladbrokes immediately. Concrete checklist:

1. **Document the API.** Reverse-engineer endpoints into `documentation/{Provider}.md`, same format as the existing AFL/Sportsbet/Entain docs.
2. **Copy the template.** `cp src/sportsdata_mcp/specs/_template.yaml src/sportsdata_mcp/specs/{provider}.yaml`.
3. **Fill in `provider:`** — id, display name, base URLs, auth blocks (most public endpoints are `type: none`; token endpoints reuse `type: static_header` or one of the existing auth providers).
4. **Add `endpoints:` entries.** One per documented endpoint. **Crucial:** tag each with `capabilities:` using existing tags from `_capabilities.yaml` where the endpoint answers a question another provider already answers. Don't invent new tags for variants of an existing capability.
5. **Add new capabilities** to `_capabilities.yaml` if the provider exposes something genuinely novel (e.g. `gambling.bet_history` for a punter-account integration). Mark single-provider capabilities `single_provider: true` if you don't expect another bookie to expose them.
6. **High-cardinality surfaces** — if the provider has a GraphQL gateway or templated REST family, use a `dispatchers:` block + catalogue resource rather than registering one tool per operation.
7. **New auth scheme** (rare) — drop a class in `src/sportsdata_mcp/auth/{provider}.py` implementing the `AuthProvider` protocol. Reference it from the spec via `auth.type: {provider_token}`.
8. **Update README** group table with new group names.
9. `sportsdata-mcp lint {provider}` — must pass clean (lint resolves spec names against the packaged `specs/` dir). Lint enforces capability consistency.
10. `sportsdata-mcp doctor` — confirms reachability and auth.
11. PR. CI lints specs and runs unit tests; reviewer eyeballs docstring quality and verifies new capabilities are sensibly named (no `racing.racecard` when `racing.race_card` already exists).

### Providers to add next (suggested priority)

Mixed list of bookies (Class 1) and stats/league data (Class 2 + 3). Priority weighting: each new provider should plug into ≥1 existing capability so it immediately becomes useful in cross-provider comparisons.

| Provider | URL | Class | Why prioritise |
|---|---|---|---|
| **TAB** | `tab.com.au` | Bookmaker | Largest Australian wagering operator. Tote pools fill in a major gap (we currently only have fixed-odds bookies). |
| **Pointsbet** | `pointsbet.com.au` | Bookmaker | Different oddsmaker, often outliers on specials/exotics. |
| **NRL.com** | `nrl.com` | League data | Australian rugby league — Pulse Platform, likely 80% similar to AFL.com.au. Tests rapid-fan-out of the spec format. |
| **NHL.com** | `api-web.nhle.com` | League data | Modern REST API, no auth. Brings ice hockey into the catalogue. |
| **ESPN** | `site.api.espn.com` | Aggregator | Multi-sport scoreboard / standings / news. One provider, many sports. |
| **Cricket Australia** | `cricket.com.au` | League data | Likely Pulse Platform like AFL. Adds T20 / ODI / Test coverage. |
| **Bet365** | `bet365.com.au` | Bookmaker | Largest international, broadest sport coverage — but heavily bot-protected; expect more reverse-engineering effort. |
| **AFL Fantasy** | `fantasy.afl.com.au` | Fantasy / specialist | Adds `stats.fantasy_projections` capability. Single-provider for AFL fantasy. |
| **bet.com.au** | `bet.com.au` | Bookmaker | Smaller AU bookie, often value on AU racing. |
| **The Sports DB** | `thesportsdb.com` | Aggregator | Free, multi-sport reference data (teams, leagues, logos). Cheap to add, fills `ref.*` gaps. |

**Zero Python changes** expected for any new provider unless they use a novel auth scheme. Even then, one file (`auth/{provider}.py`) is added; no other code changes.

---

## Distribution

### `pyproject.toml` skeleton

```toml
[project]
name = "sportsdata-mcp"
version = "0.1.0"
description = "MCP server for Australian sports betting and AFL data APIs"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [{name = "Daniel Tomaro"}]
dependencies = [
  "fastmcp>=0.4",
  "httpx[http2]>=0.27",
  "pydantic>=2.5",
  "pyyaml>=6.0",
  "click>=8.1",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21", "ruff>=0.4"]

[project.scripts]
sportsdata-mcp = "sportsdata_mcp.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sportsdata_mcp"]

# Specs live inside the package and MUST ship in the wheel — the server loads them
# via importlib.resources, never from a cwd-relative ./specs/.
[tool.hatch.build]
include = ["src/sportsdata_mcp/specs/*.yaml"]
```

### `examples/claude-desktop-config.json`

```json
{
  "mcpServers": {
    "sportsdata-mcp": {
      "command": "uvx",
      "args": ["sportsdata-mcp", "serve"],
      "env": {
        "SPORTSDATA_MCP_GROUPS": "afl.public.core,sportsbet.racing,entain.graphql"
      }
    }
  }
}
```

### `examples/claude-code-mcp.json`

Same shape, placed under `~/.claude/mcp.json` or per-project `.claude/mcp.json`.

---

## Open questions deferred to v2

These don't block v1 but should be tracked:

| Topic | Plan |
|---|---|
| **Sportsbet GraphQL ops beyond `EventStats`** | Currently only one persisted hash is known. As more are sniffed from live traffic, append to `sportsbet.yaml`'s `graphql.operations` — same dispatcher serves them all. No code change needed. |
| **AFL Okta device flow** | For premium endpoints under `/cfs-premium/users/...` that need a logged-in AFL iD (favourites, watch history, AFL Live Pass entitlements). v1 only does the anonymous `WMCTok` flow, which covers the vast majority of premium endpoints. |
| **Token-bucket rate limiter persistence** | The MCP runs a token-bucket limiter per provider to avoid hammering Cloudflare/Akamai (e.g. 5 requests/sec sustained, burst of 10). v1 keeps the bucket state in process memory. When the server restarts, the bucket resets to full — so the very first burst of calls after restart could in theory hit 10 immediately. In practice restarts are rare and 10 calls don't trip anything; persisting the bucket to SQLite/Redis would add a dependency for no real benefit. |
| **SSE / HTTP MCP transports** | FastMCP supports them. v1 ships stdio only because every supported client (Claude Desktop, Claude Code) prefers stdio. |
| **WebSocket pricing feeds (Sportsbet, Ladbrokes Price Kinetics, etc.)** | Sportsbet responses include `topicLink` fields like `Sportsbet/Sportsbook/Sports/16/Competitions/6927/Events/10502542/Markets/.../Selections/.../Prices/L`. These are not URLs to GET — they're topic identifiers for a pub/sub WebSocket channel the site uses to push live price changes. MCP tools are call → return (no streaming primitive) and the model runs turn-by-turn (no use for a live stream), so this is out of scope. Pricing snapshots remain available via REST (`Event Markets`, `event-card`, etc.) — that returns the same number the WebSocket would have pushed two seconds ago, which is what the model actually needs. |
| **Cross-provider schema normalisation** | Explicitly NOT planned. The capability system surfaces comparable tools; the model handles schema differences. Normalisation is a moving target (every provider release breaks it) and hides bugs more than it helps. |
| **Cross-provider entity resolution** | For a comparison the model must first find the *same* event/runner under each provider's IDs (Sportsbet eventId vs Ladbrokes raceId vs AFL providerId) — i.e. one lookup call per provider before the comparison call. This is a deliberate cost of "no normalisation," not a bug. A future helper (`resolve_event(name, date, sport) → {provider: id}` backed by fuzzy name+date matching) could collapse those lookups, but it's a normalisation-adjacent foot-gun (wrong match → confidently wrong comparison) so it's deferred until the friction is proven painful in real use. |
| **Non-MCP clients (OpenAI / Azure OpenAI / DeepSeek / Gemini)** | These don't speak MCP natively. The server is deliberately client-agnostic (it's just MCP-over-stdio), so the supported path is an external bridge that re-exposes MCP tools as that vendor's function-calling schema — e.g. `mcp-bridge`, `litellm`, or a thin custom adapter. We will **not** ship our own bridge or a second tool-serialisation path in the server; the README will point at existing bridges. Pydantic/FastMCP already give every tool a clean JSON-schema, which is exactly what a bridge consumes. |

---

## Project naming

The project was originally scoped as bookmaker-only and named `Bookie-MCP`. As the spec format proved it could accommodate league/governing-body data (AFL.com.au is a Class-2 provider, not a bookie), aggregators (ESPN), stats APIs and fantasy platforms, the name was changed to `sportsdata-mcp` before any code landed.

Reserved naming conventions across the codebase:

| Surface | Name |
|---|---|
| GitHub repo / directory | `sportsdata-mcp` |
| PyPI package | `sportsdata-mcp` |
| Python package (`src/`) | `sportsdata_mcp` |
| CLI command | `sportsdata-mcp` |
| Config file | `sportsdata-mcp.yaml` |
| Config dir | `~/.config/sportsdata-mcp/` |
| Env vars | `SPORTSDATA_MCP_GROUPS`, `SPORTSDATA_MCP_CONFIG` |
| MCP resource scheme | `sportsdata://capabilities` (project-wide), `entain://`, `afl://`, `sportsbet://` (per-provider) |

Provider-prefixed resource URIs (`entain://`, `afl://`, etc.) **do not** carry the project name — they're scoped to the provider whose data they describe. This means provider specs are portable: lifting `specs/afl.yaml` into a different MCP server doesn't require URI rewrites.

---

## Concrete first commit

If we proceed, Phase 1's deliverable is one commit that:
- Adds `pyproject.toml`, the empty `src/sportsdata_mcp/` package, `specs/_template.yaml`, `specs/_schema.yaml`, `specs/_capabilities.yaml`.
- Implements `spec.py`, `config.py`, `cli.py` (commands: `version`, `list-groups`, `lint`).
- Has `python -m sportsdata_mcp serve` start a server that exposes only `list_available_groups`, `list_tools_by_capability`, `list_resources` meta-tools and the `sportsdata://capabilities` resource.
- Has CI green (unit tests, lint specs, capability-consistency check).

After that, Phase 2 lands `specs/afl.yaml` (a Class-2 league-data provider — proof the spec format works for non-betting), and Phases 3-5 land the bookies and remaining surfaces. Additional non-betting providers (NBA Stats, NRL.com, NHL, ESPN, etc.) plug in later via [Adding a new provider](#adding-a-new-provider) — zero Python changes, just a new YAML and any new capability tags.

---

*Plan version 1.2. Update this file whenever a phase ships or a decision changes.*
