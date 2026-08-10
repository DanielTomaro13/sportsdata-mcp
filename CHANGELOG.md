# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org),
with the caveat that **provider additions are minor bumps** — new tools appear, existing
ones do not change.

Full history is in `git log`; this file covers what a user would notice.

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
