# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org),
with the caveat that **provider additions are minor bumps** — new tools appear, existing
ones do not change.

Full history is in `git log`; this file covers what a user would notice.

## Unreleased

### Added
- **`betr_sgm_price`** — the fourth Australian book that will price a same game multi you
  choose, joining `sportsbet_sgm_price`, `tab_sgm_price` and `pointsbet_sgm_price`.
  Verified live with the correlation adjustment running both ways: Bulldogs (1.95) with
  Under 139.5 (6.25) prices 11.00 against a naive 12.19, while the same 1.95 with Under
  201.5 (1.10) prices 2.25 against a naive 2.145.

  BetR is the best-behaved of the four on redundancy — it *refuses* a leg another leg
  implies rather than silently dropping it — and the worst on everything else. It takes a
  `FixedWin` from the client and uses it as a FLOOR on the answer, so sending 99.0 returns
  `{Price: 99.0, ErrorNo: 0}`: a fabricated quote reported as a clean success. The spec
  does not expose the field. `MarketType` is likewise required but unvalidated — dropping
  it turns a correct 2.20 into 21. Both are documented at the parameter, not just in the
  provider page.

- **Dabble was surveyed and deliberately got no SGM tool.** It sells same game multis and
  the fixture payload carries the machinery around them — `isSgmAllowed` marks the eligible
  legs, and every fixture declares an SGM market group that `marketGroupMappings` never
  fills — but Dabble has no web betting UI, so the browser capture that solved the other
  four books has nothing to drive. ~40 candidate routes were probed against a clean 404
  baseline; all 404. Documented in `documentation/Dabble.md` and
  `docs/SGM-AND-PLACEMENT-SCOPE.md`, including the one request worth saving if the app's
  traffic is ever captured. This is a gap in what can be OBSERVED, unlike Pinnacle, which
  simply does not sell the product.

- **`unibet_sgm_price`** — the fifth and best-behaved book. Unibet runs on Kambi, so this
  is Kambi's `onDemandPricing`, and it is the only pricer of the five that is a plain GET,
  the only one that echoes back the exact legs it priced (`selectedOutcomeIds`), and the
  only one that refuses with a real HTTP 400 and a typed body instead of a 200 carrying a
  zero. Verified live: Bulldogs head-to-head (1.92) with Over 170.5 (1.88) prices 3.40
  against a naive 3.6096.

  It also has the loudest wrong answer in the catalogue: **Kambi reports odds in
  thousandths**, so `decimal: 3400` is 3.40. A comparator that misses this reports one book
  at 1000x the others. Two more, both pinned: 1001.0 is a payout ceiling rather than a
  price (six through fourteen legs all returned exactly it), and `combinableOutcomeIds` is
  bet-builder ELIGIBILITY, not compatibility with what you have already picked. The
  endpoint declares `response_pick` because the upstream repeats the event's whole
  bet-offer book — 647 KB of a 610 KB response — which `event_betoffer` already serves.
- **`tests/unit/test_sgm_comparator.py`** — the six pricers pinned as a SET: that they
  exist, that they stay findable by one capability query, that no POST among them loses
  `read_only`, that every hint still states the price is not the product and says when it
  was verified, and that each book declares an `error_signals` rule exactly when it fakes a
  price on refusal. Each book's own file pins its own traps; nothing else was checking that
  the five still work together, which is the whole reason for building them.

- **`entain_sgm_price`** — the sixth and last Australian book, completing the set. Not a
  GraphQL operation despite Entain's persisted-query registry already carrying
  `SportingEventPopularSameGameMultis`; the pricer is on the plain REST gateway, and its
  envelope is a map keyed by event id, so several events price in one call. Verified live:
  Melbourne (2.15) with Over 173.5 (1.88) prices 3.70 against a naive 4.042.

  Entain has the best refusal in the catalogue and the worst hole. `conflicting_selections`
  names the exact clashing pair, where other books manage a sentence — but on a sample of
  22 two-entrant markets, **four had their mutually exclusive pair quoted as `available:
  true`, at 70 to 146**. A bet that cannot win, priced at 146.51, is indistinguishable from
  a longshot with enormous edge, which is exactly what an automated screener hunts for.
  Prices are also fractional with **decimal = numerator/denominator + 1** — the quiet
  mirror of Unibet's thousandths, since forgetting it makes the book merely look worse than
  it is rather than raising an alarm.

  With this, every Australian book in the catalogue has been surveyed: six price a
  combination you choose, Pinnacle needs nothing built because its parlay price is the
  product of its legs, and Dabble is blocked on observation. See
  `docs/SGM-AND-PLACEMENT-SCOPE.md` for the four rules a cross-book comparator has to
  carry, each traceable to a specific book's behaviour.

### Changed
- **A 200-with-an-error-body now finds its message whatever the vendor calls it.** The
  detail lookup was lowercase-only, so BetR's `Message` was invisible and "Same Game Multi
  must have at least two legs" would have reached the caller as a bare error number.
  `reason` / `message` / `errormessage` are matched case-insensitively now, in that
  priority order rather than in whatever order the provider serialised.

## 0.30.0 — 2026-08-27

### Added
- **Every tool now declares what question it answers.** 173 tools carried no
  `capabilities` key at all — not waived, never considered — and since a capability tag
  is how tools are discovered across providers, those were unreachable rather than
  merely deprioritised. All 829 now carry a tag or an explicit `capabilities: []` with a
  comment saying why nothing fits, and a test makes omitting the key a build failure, so
  the decision gets made when a tool is written. `list_tools_by_capability` covers the
  catalogue for the first time.
- **Ten capability tags** for questions that had none: `ref.rounds`, `ref.officials`,
  `sport.lineups`, `sport.awards`, `sport.cash_out`, `racing.form_guide`, `racing.pools`,
  `racing.price_history`, `racing.track_conditions`, `content.photo`. Chosen on
  substitutability — a tag means "these tools answer the same question", so provider
  plumbing (navigation, CMS copy, a provider's own id decoders, one book's editorial
  tips) is deliberately left untagged rather than grouped by topic.

- **Same game multi pricing at three Australian books** — `sportsbet_sgm_price`,
  `tab_sgm_price` and `pointsbet_sgm_price`. Each takes legs you choose from one event and
  returns the book's own correlation-adjusted price for the combination, unauthenticated.
  This is the number you cannot compute: on a verified AFL fixture, Bulldogs head-to-head
  (1.96) with Bulldogs +1.5 (1.90) multiplies to 3.724 and prices at **1.96** on PointsBet,
  because a win already implies the line. Anything that multiplies legs is wrong by tens of
  percent. Pinnacle was surveyed too and deliberately got no tool: it prices a parlay as
  the product of its legs, which makes it the fair-value benchmark rather than an SGM
  venue. See `docs/SGM-AND-PLACEMENT-SCOPE.md`.
- **Dotted wire names on body params.** `api_name: clientDetails.jurisdiction` nests a
  scalar into an envelope, so TAB's pricer can take one string instead of making the caller
  hand-build the whole body. It has to be the wire name — a dot cannot be a Python
  parameter name.

### Changed
- **`racing.form_guide` retags three tools** that sat on `racing.race_card`. A card says
  who is in the race at what price; a form guide says how each runner has been going —
  different questions, so different tags.
- **A 200-with-an-error-body now names what failed, not just that it failed.** The error
  detail took `message` alone, so PointsBet's "Selection Suspended" arrived without saying
  which of ten selections was suspended — a recoverable failure reaching the caller as a
  dead end. Non-empty sibling collections (`invalidSelections`) are now appended. Scalars
  are deliberately excluded: PointsBet's refusals carry `price: 0`, and that is the one
  value that must never be repeated back as though it were a quote.

### Fixed
- README's catalogue totals were stale (801 tools / 63 providers against an actual
  829 / 64).

## 0.29.0 — 2026-08-24

### Added
- **`sleeper_players`** — the player id → name table, which nothing else in Sleeper's
  surface provides. This reverses an earlier decision to keep it out; that decision held
  that "draft picks and trending players cover player identity instead", and they do not.
  Draft picks carry names, but a ROSTER and the TRENDING list — the two things read every
  week — are bare ids. An agent could see 148,925 leagues add player 13602 and have no
  way to say who that was.
- **Nested field projection.** `response_fields` now accepts dotted paths
  (`team.abbrev`, `player_stats.price`), applied per item when the value is a list.
  Flat-only picking could not reach the fields that matter on the fattest feeds:
  SuperCoach ships 812 players with 124 stat fields each — 2.7 MB, of which four fields
  are useful. Asking for both a key and a leaf beneath it keeps the whole key, because
  narrowing it would discard data the spec asked for by name.
- **`response_map`** — declares that a body is a map of ROWS keyed by id, so
  `response_fields` applies to every value. Explicit rather than inferred: a table keyed
  by player id and an object with named sections are indistinguishable from outside, and
  projecting the second would be silent data loss. Sleeper's table needs it — without it
  the projection is a no-op and the tool ships 14.6 MB instead of 1.1 MB.

## 0.28.1 — 2026-08-24

### Fixed
- **CI: an invented capability slug.** `mfl_live_scoring` declared `sport.live_scores`,
  which is not in `_capabilities.yaml`. Caught by the spec-lint step — a *separate* CI
  step from pytest, so a green local suite said nothing about it. A test now lints the
  specs that actually ship, so this class of mistake fails on the machine that made it
  rather than eight minutes into CI.
- **Nightly drift: MFL read examples named a league that does not exist.** The drift
  check probes each group's first example, and MFL answers a bad league id with HTTP 200
  and an error body — so a placeholder was not "unprobeable", it was a guaranteed red
  that trains everyone to ignore the check. The read examples now name a real public
  league, which makes the probe mean something: if MFL's shapes move, drift says so.
  Write examples keep a placeholder deliberately — a documented write example should not
  point at a live team.
- **MFL rate limit lowered to 1 rps / burst 2.** It drops the connection rather than
  returning 429: four probes in three seconds produced "Server disconnected without
  sending a response", which reads as drift and is really just impatience.

## 0.28.0 — 2026-08-22

### Added
- **MyFantasyLeague** (`myfantasyleague`) — 20 tools, **6 of them writes**, and the first
  fantasy write contract in this catalogue that is *documented by the vendor* rather than
  transcribed from minified JavaScript. Reads cover the league, rosters, free agents,
  standings, schedule, league-scored player points, projections and live scoring; writes
  cover lineups, immediate add/drops, waiver claims, blind bids, injured reserve and trade
  responses. `myfantasyleague.write` is reachable only by exact group name.
- **`response_format: xml`** on the engine. MFL's `/import` endpoints answer XML even when
  asked for JSON, and answer HTTP 200 whether a write succeeded or failed — so without a
  decoder an ordinary rejection surfaced as "the body did not parse", and a success looked
  identical to it. XML decodes to the same shape the provider's own JSON mode produces, so
  one `error_signals` rule covers both. Repeated child tags always collapse to a list, so a
  one-row document and a many-row document never differ in shape.
- `sportsdata-mcp connect mfl`.

### Fixed
- **`connect` called any HTTP 200 a working credential.** Each provider disagrees about
  what a failure looks like, and the FPL-shaped check passed every MFL cookie. Verification
  is now per connector, and a test asserts that any connector with a `verify_url` has one —
  MFL in particular says no by returning `{"leagues": {}}`: 200, no error field, and
  indistinguishable from success unless you decide what you meant by it.

## 0.27.3 — 2026-08-22

### Fixed
- **A refresh diff crashed on a newly-added GraphQL operation.** `HashChange.old` was
  typed `str` but holds `op.sha256`, which is legitimately `None` for an operation that
  never carried a hash — and the CLI printed `c.old[:8]`, so the first refresh after
  adding one died with `TypeError: 'NoneType' object is not subscriptable`, at exactly
  the moment it had something useful to report.
- **A `None` hash was subscripted while RAISING `PersistedQueryNotFoundError`**, turning
  a clear "run refresh-hashes" message into a traceback pointing at the wrong thing.
- `serve_http` now rejects an unknown transport by name. It is importable, so the CLI's
  own `click.Choice` was not the only way in, and an unknown string surfaced as an error
  from deep inside FastMCP.

### Changed
- **mypy is now a CI gate**, and the tree is clean. It found both crashes above. Several
  `type: ignore` comments named error codes mypy was not raising, so they silenced
  nothing while implying the code had been checked; those are now real narrowing.
  `types-PyYAML` and `mypy` join the dev extra.

## 0.27.2 — 2026-08-21

### Added
- **ESPN Fantasy writes** (`espnfantasy.write`): `espnfantasy_set_lineup` and
  `espnfantasy_add_drop`. Reachable only by exact group name, never by `*`, `all`, a
  preset or `espnfantasy.*`. The contract was transcribed from ESPN's own public JS
  bundle and is documented in `documentation/ESPNFantasy.md`; both carry
  `shapes_verified: false` until a live 200 confirms them.
- `shapes_verified` is now settable **per endpoint**. ESPN's 27 reads are confirmed
  against live responses while its 2 writes are not, and flipping the provider flag would
  have put an "unverified" warning on 27 good tools to be honest about 2.

### Fixed
- **`connect` read only Chrome's `Default` profile.** For anyone with a work and a
  personal profile that is the wrong one, and the failure was indistinguishable from
  being logged out — "nothing found (…or not logged in)" while the cookie sat in
  `Profile 1`. Every profile is now searched, largest first, and a partial hit in one is
  never merged with a partial hit in another.
- **`connect espnfantasy` saved to an env var nothing reads** (`ESPN_S2` vs the spec's
  `ESPN_FANTASY_COOKIE`). It reported success and every private-league call carried on
  401'ing. A test now asserts every connector targets an env var its provider reads.
- **The response-size cap measured the raw body, before projection.** Endpoints exist
  specifically to shrink a large payload; four FPL tools served from a 1.4MB
  bootstrap-static were rejected for the size of what they were about to discard. The
  projected result is now what the cap measures.

## 0.27.0 — 2026-08-17

### Fixed (security)

- **The OAuth refresh token was the one credential the log redaction missed.** Several
  providers authenticate in the URL and `httpx` logs the composed URL, so `redact.py`
  scrubs known secrets from every log record. It built its list from a hand-written set
  of five auth attributes and omitted the sixth — `refresh_token_env`. The refresh token
  is the durable credential (it mints access tokens roughly hourly, forever) and is the
  value most likely to appear in a log, so the one worth protecting most was the only one
  unprotected. It now derives from `spec.AUTH_ENV_ATTRS`, and a test asserts redaction
  covers **every** env var **every** provider declares — this was the third time a
  hand-written copy of that list was wrong, and the last time it can be.

### Added

- **`yahoo` — Yahoo Fantasy Sports, 24 tools, the only fantasy platform with a
  SANCTIONED write API.** Discovery, league/team/player reads, standings, scoreboards
  with projected points, transactions with winning FAAB bids, drafts, ownership — plus
  officially supported `yahoo_set_lineup` (PUT), `yahoo_add_drop` and
  `yahoo_propose_trade`.

  **Access is approval-gated** — apply at `sports.yahoo.com/developer`. Self-registration
  does not grant the scope (verified: `fspt-w` → `invalid_scope` on two separately
  registered apps), so the provider is complete but inert until Yahoo approves an
  application. `scripts/yahoo-oauth-setup.py` walks the OAuth dance and preflights that
  check in one request.

- **Write tools are opt-in by exact name.** A `.write` group is never enabled by `*`, by
  a preset, or even by a provider glob like `yahoo.*` — "enable everything" must not
  quietly mean "and you may change my team".

- **Honest tool annotations.** `readOnlyHint` is a promise a client acts on, and every
  tool claimed it unconditionally — so the first write tool inherited a claim that it
  changes nothing. Annotations now derive from the endpoint, with a `read_only` override
  for the POSTs that only read (FanDuel's promotions endpoint, and GraphQL queries,
  which travel by POST).

- **Raw request bodies** (`request_body_format: raw`) — Yahoo's writes accept XML only,
  and a dict-to-XML serialiser would bake one provider's document shape into shared code.

## 0.26.0 — 2026-08-13

### Added

- **`fpl` — Fantasy Premier League's official API, keyless, 16 tools.** The world's
  most-played fantasy game (4,085,510 registered squads), public except for your own
  squad: every player with price/form/ownership/xG, one player's full gameweek history,
  clubs with strength ratings, all 38 gameweek **deadlines**, fixtures with difficulty
  ratings, live per-player scoring with point-by-point `explain`, dream teams, official
  set-piece takers, any manager's squad and picks, classic and H2H leagues, and — with
  your own session cookie — `fpl_my_team` for `selling_price`, free transfers and chip
  availability.

- **Reductive response projection** (`response_pick`, `response_fields`) — the engine's
  second declared exception to passthrough after `classify`, and the first that
  *removes*. It exists because FPL returns one 1.37 MB blob holding six unrelated
  datasets, of which the player rows alone are **~362,000 tokens** — more than any
  context window holds, with no server-side field selection and no narrower route. Four
  tools now hit that URL and return one slice each; `fpl_players` lands at ~58k tokens.
  Nothing is invented, renamed or coerced — only removed, and only where an endpoint
  declares it.

## 0.25.1 — 2026-08-11

### Fixed

- **`ufc_rankings` exposed a filter that silently returned nothing.** Like the other
  custom-entity collections on ufc.com, `athlete_ranking` answers
  `filter[fightmetric_id]` with 0 rows rather than an error — so asking for one fighter's
  ranking reported "not ranked" for a ranked fighter. The parameter is gone.

  The test meant to prevent exactly this listed the two tools it knew about and missed
  the third. It now derives the rule from the endpoint path — every non-`/node/`
  collection is checked — because a rule that has to be remembered for each new endpoint
  is not a rule.

## 0.25.0 — 2026-08-11

### Added

- **`ufc` — the official ufc.com JSON:API, keyless, 9 tools.** Events with per-segment
  card times and venue, full fight cards, bouts back to UFC 1, fighter profiles,
  divisional rankings, the single-round record book, and — the reason it exists — the
  **complete FightMetric career statistics table**: significant strikes split by
  position (standing/clinch/ground) *and* target (head/body/leg), takedowns landed,
  attempted, accuracy and defence, submission and knockdown averages, strikes landed and
  absorbed per minute, and career records by finish method.

  This is the same dataset ufcstats.com publishes, with the same `fightmetric_id`
  identifiers — obtained officially rather than by scraping. **ufcstats.com itself was
  ruled out**: it serves a JavaScript proof-of-work bot challenge with `noindex` and zero
  data rows in the HTML, so reading it would mean building bot-detection evasion.

  Two traps documented and designed around. Filtering works on `node/*` resources but
  **silently returns 0 rows** on the stat collections — even for an id on page 1 — so
  those parameters are not exposed at all, and a test forbids re-adding them; use
  `ufc_athlete` for one fighter and sorting for leaderboards. And `takedown_acuracy` is
  misspelled upstream, so spelling it correctly returns nothing.

  Rate-limited to 0.5 rps because `robots.txt` asks for `crawl-delay: 15` — a courtesy,
  pinned by a test.

### Fixed

- **Presence-mode error signals raised on a successful call when a provider quoted its
  status code.** iSportsAPI signals success with `code: 0`, and Python calls the STRING
  `"0"` truthy — so a provider switching from `0` to `"0"` would have had every good call
  reported as an error. Numeric-zero strings now read as success; a non-zero code still
  raises whether it arrives as a number or a string.
- **Telemetry's feedback list was unbounded.** Per-tool counters are capped by the tool
  count, but `sportsdata_feedback` is free text a caller can send any number of times: a
  long-running HTTP deployment would grow forever and eventually POST a multi-megabyte
  payload (5,000 notes measured at 2.96 MB). Capped at the most recent 200.

## 0.24.1 — 2026-08-11

Quality of the tool definitions themselves, prompted by an external MCP directory
scoring the server and reporting "0% schema parameter coverage".

### Fixed

- **Every parameter description was being dropped from the JSON schema.** FastMCP
  derives each tool's schema from Python annotations, so a bare `int` produced
  `{"type": "integer"}` and the `description:` written in every spec never reached the
  model — the documentation this project maintains most carefully was invisible to its
  only real reader. Parameters now carry `Annotated[T, Field(description=...)]`, so
  descriptions **and** enums land in the schema. Coverage went **0% → 100%** (1,878 of
  1,878), which also required documenting 64 AFL parameters that genuinely had none and
  the dispatcher/meta tools whose parameters are defined in Python rather than YAML.

### Added

- **Tools state their auth requirement**: `Auth: none needed.` /
  `Auth: needs your own key in API_TENNIS_KEY.` An agent that knows a call needs a key
  can say so instead of retrying.
- **Server `instructions`** explaining how to choose between overlapping providers, said
  once rather than repeated on 758 tool descriptions — inlining it cost ~12k tokens a
  session to say the same thing 758 times. Specific alternatives are still named on the
  45 tools where the list is short enough to be the answer.

## 0.24.0 — 2026-08-11

**32 new providers (28 → 60) and 753 tools.** The largest release so far: a complete
bring-your-own-key tier, fifteen new keyless providers, four engine features, and a
drift check that no longer lies in either direction.

### Added

- **17 bring-your-own-key providers** in a new opt-in tier, excluded from the `free`
  preset and from the defaults. `apisports` (10 sports on one key, and the only rugby
  union here), `theoddsapi`, `oddsapiio` (274 bookmakers, 34 sports),
  `sportsgameodds` (player props with stable market ids), `sportsdataio` (DFS salaries
  and projections), `sportmonks`, `cfbd`, `footballdataorg`, `balldontlie`,
  `pandascore`, `apitennis` (ATP and ITF), `cricketdata`, `mysportsfeeds`,
  `isportsapi` (Asian handicap), `highlightly` (highlight video), `entitysport`
  (ball-by-ball cricket), `golfcourseapi`.
- **15 keyless providers**: `squiggle`, `nhl`, `sleeper`, `jolpicaf1`, `lichess`,
  `chesscom`, `opendota`, `openligadb`, `euroleague`, `ncaa`, `motogp`, `formulae`,
  `nascar`, `footballdatauk`, `espnfantasy`.
- **`error_signals`** — a provider may declare which response fields mean "this HTTP 200
  is actually an error". Four providers need it: `apitennis` (`error: "1"`),
  `cricketdata` (`status: "failure"`), `isportsapi` (non-zero `code`) and `apisports`
  (a populated `errors` object). Without it a blown quota or a bad key reaches the model
  as data — `apisports` in particular answers an exhausted daily quota with `200`, a
  populated `errors`, and an **empty `response`**, which reads as "no games today".
- **`static_basic` auth** for HTTP Basic providers, so nobody has to base64-encode a
  credential pair by hand.
- **Group presets and selector syntax**: `free`, `all`, `racing`, `arb`, `fantasy`,
  `au-books`, `official-stats`, `motorsport`, `esports`; provider globs (`espn.*`), bare
  provider ids, and exclusions (`all,-twitter`).
- **MCP prompts** — six curated workflows, each gated on the providers actually enabled.
- **HTTP/SSE transport** (`serve --transport http|sse`) with a health endpoint, for
  remote clients and hosting.
- **Tool annotations** (`readOnlyHint`, `idempotentHint`, `openWorldHint`) on every tool.
- **Short-lived GET cache**, keyed to include the auth key so no response crosses tiers.
- **`response_format: csv`** for datasets published only as CSV downloads
  (`footballdatauk`); the model still receives JSON.
- **`shapes_verified`** — providers we could not probe are flagged, and every one of
  their tool descriptions tells the model to inspect the payload rather than trust the
  documented shape.
- `manifest.json` (Claude Desktop extension) and `smithery.yaml`, both defaulting to the
  `free` preset so an empty configuration is a working install.
- **Relative date tokens** (`{{today}}`, `{{today+N}}`) in spec examples, rendered as a
  real date when probing and as `<today>` in tool descriptions, so neither can rot.
- **`sportsdata-mcp stats`** and the `sportsdata_session_stats` tool: per-tool call
  counts, error rates and empty-result counts, recorded locally and never transmitted.
- **`sportsdata_feedback`** for reporting a wrong or useless answer.
- **Opt-in telemetry** — off by default, needing two explicit acts, with tool arguments
  structurally impossible to record. See [docs/TELEMETRY.md](docs/TELEMETRY.md).
- **`scripts/metrics.py`** — adoption figures from PyPI and GitHub, touching no user.

### Fixed

- The `free` preset silently became a lie when the BYO tier landed — new providers join
  `*` automatically. It is now **computed** from `requires_user_key` rather than listed,
  with a test that derives the expected set independently.
- `espn.*` matched nothing: only a bare `*` was treated as a wildcard, so a glob resolved
  to an empty tool set and `doctor` exited 0 having probed nothing.
- The racing prompt gate matched `*.racing` group names, which quietly swept in MotoGP,
  Formula E and NASCAR when those landed.
- ESPN began 403ing any `Mozilla/…` User-Agent; the client now identifies itself
  honestly.
- `doctor` reported SKIP rather than FAIL for providers with no auth configured.
- `server.json` advertised "~500 tools, 28 providers" at version 0.22.1 while the package
  was 0.23.1 with far more of both. Version lockstep and count accuracy are now tested.
- **Credential leak in verbose mode.** `sportsdata-mcp -v` printed API keys: seven
  providers authenticate with a query parameter, and httpx logs the fully-composed URL.
  A redaction filter now scrubs known secrets from every log record, whichever library
  emitted it.
- **The drift check was wrong in both directions.** It reported ✓ passed for three
  providers that were returning auth errors inside HTTP 200 (doctor never applied
  `error_signals`), failed 13 healthy BYO providers for correctly refusing an
  unauthenticated probe, and called `footballdatauk`'s CSV a bot challenge.
- **Ten spec examples had hardcoded dates** that providers now reject — Sportsbet answers
  a five-week-old racing date with HTTP 400 — turning healthy providers red on the
  nightly check. `sportsdata-mcp lint` now rejects any example date under 400 days old.
- **Four providers had no documentation at all** while their `doc_url` — rendered into
  every one of their tool descriptions — pointed at a GitHub 404. NBA and NRL had
  documentation that nothing linked to.
- **api-sports advertised ten sports and delivered eight**; handball and volleyball had
  hosts declared but no endpoints behind them.

### Excluded on purpose

- **SportDevs** — no DNS record on any host; the service no longer exists.
- **Live Golf API** — host resolves, every path returns "Application not found".
- **Fighting Tomatoes** — documented API paths return the site's 404 page.
- **TheSportsDB** — the free tier returns silently truncated data (an EPL table comes
  back with 5 rows of 20, with nothing marking it partial). A provider that quietly
  answers with a fifth of the table is worse than no provider.

## 0.23.1

- Spec fixes reach users only through a release: the OTA spec channel is not operational
  (no signing keys baked, no feed URL, no asset ever published).

## 0.23.0

- **ESPN Fantasy** — 27 tools across all five fantasy games, including the undocumented
  `allon` mega-view. Public leagues work with no credentials; private ones read an
  optional cookie.

## 0.22.x

- Entain APQ self-heals via a document-carrying retry when the persisted-query hash
  drifts.
- Token bucket debits before sleeping, so concurrent waiters cannot form a thundering
  herd at the upstream the limiter exists to protect.

## 0.21.x

- `tab_tournament` for tournament-nested competition events; `tab_racing_runner_form`;
  `betr_master_event` GroupTypeCode for full per-event market boards.

## 0.20.x

- `entain_racing_racecard` — the priced Ladbrokes racecard route.
- Keyless optional-OAuth degrades to anonymous instead of raising.

## 0.18.x

- DNS-over-HTTPS resolver lifecycle and connection-limit fixes (Polymarket).
