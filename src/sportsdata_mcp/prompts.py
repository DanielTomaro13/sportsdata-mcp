"""Curated slash-command workflows over the tool catalogue.

A prompt here is a *recipe*: it tells the model which tools to reach for, in what
order, and — the part that matters most for this server — how to compare results
across providers without inventing numbers.

Two rules make these different from a generic prompt pack:

1. **A prompt is only registered when the tools it drives are enabled.** Offering
   "compare odds across every book" to someone running the ``official-stats`` preset
   would be a promise the server can't keep, and the model would flail looking for
   tools that aren't there.
2. **They insist on provenance.** Every number the model reports has to come from a
   tool result. That's the whole point of this server, and a prompt that lets the
   model fill gaps from memory would quietly undermine it.
"""

from __future__ import annotations

from collections.abc import Callable

# group prefix → what it unlocks. A prompt declares which of these it needs.
_BOOKS = ("sportsbet", "tab", "betr", "pointsbet", "unibet", "entain", "dabble", "fanduel", "pinnacle")
_EXCHANGE = ("betfair",)
_PREDICTION = ("kalshi", "polymarket")


def _providers(enabled: set[str]) -> set[str]:
    return {g.split(".", 1)[0] for g in enabled}


def _has(enabled: set[str], *providers: str) -> bool:
    return bool(_providers(enabled) & set(providers))


def _racing_groups(enabled: set[str]) -> bool:
    return any(g.endswith(".racing") or g.startswith("racingandsports") for g in enabled)


# ─── the prompts ────────────────────────────────────────────────────────
# Each returns (name, description, fn, applies) where `applies` decides whether the
# prompt is registered for the current group selection.


def _register_compare_odds(mcp, enabled: set[str]) -> bool:
    if not _has(enabled, *_BOOKS):
        return False

    @mcp.prompt(
        name="compare-odds",
        description="Compare prices for one event across every enabled bookmaker and report the spread.",
    )
    def compare_odds(event: str, market: str = "head to head") -> str:
        return (
            f"Compare prices for: {event} — market: {market}.\n\n"
            "1. Call list_tools_by_capability('sport.event_markets') to see which books are enabled.\n"
            "2. For each book, find the event and read its prices. Books name teams differently "
            "(e.g. 'GWS Giants' vs 'Greater Western Sydney'), so match on the pairing, not the exact string.\n"
            "3. Build one table: a row per book, a column per selection, best price in each column marked.\n"
            "4. State the spread — best vs worst on the same selection — as a percentage.\n\n"
            "Rules: every number must come from a tool result; never fill a gap from memory. "
            "If a book has no market for this event, show it as unavailable rather than omitting the row — "
            "a missing book and a short-priced book are different facts. Note the time you read the prices, "
            "because they move."
        )

    return True


def _register_arb_scan(mcp, enabled: set[str]) -> bool:
    # Needs at least one book AND a sharp reference to measure against.
    if not (_has(enabled, *_BOOKS) and _has(enabled, *_EXCHANGE, *_PREDICTION)):
        return False

    @mcp.prompt(
        name="arb-scan",
        description="Measure enabled bookmakers against a de-vigged sharp line (exchange / prediction market).",
    )
    def arb_scan(competition: str, when: str = "today") -> str:
        return (
            f"Find price disagreement in {competition} ({when}).\n\n"
            "1. Establish the sharp line first: read the exchange (Betfair) and/or prediction markets "
            "(Kalshi, Polymarket) for the same events.\n"
            "2. De-vig it — convert prices to implied probability and normalise so they sum to 1. "
            "Show the overround you removed.\n"
            "3. Read every enabled bookmaker for the same events.\n"
            "4. Report only where a book's price implies a LOWER probability than the de-vigged line "
            "(i.e. it is paying more than fair), with the edge in percent.\n\n"
            "Every price must come from a tool result — never from memory, and never an estimate "
            "of what a book 'usually' pays. An arb computed from a remembered price is a fabrication, "
            "and it is the one error here that costs the user money.\n\n"
            "Be conservative and explicit about why an edge may not be real: stale prices, a market that "
            "has since moved, thin exchange liquidity behind the sharp line, or different settlement rules "
            "between venues. Show the matched volume where the exchange reports it — an edge against a "
            "line with no money behind it is not an edge. Do not present this as betting advice."
        )

    return True


def _register_racing_next(mcp, enabled: set[str]) -> bool:
    if not _racing_groups(enabled):
        return False

    @mcp.prompt(
        name="racing-next-to-go",
        description="The next races to jump, with prices across the enabled books.",
    )
    def racing_next_to_go(race_type: str = "all", limit: int = 5) -> str:
        return (
            f"Show the next {limit} races to jump (type: {race_type}).\n\n"
            "1. Use a next-to-go tool to get upcoming races with their jump times.\n"
            "2. For the soonest few, pull the racecard: runners, numbers, and prices.\n"
            "3. Where more than one book is enabled, compare the same runner across books.\n\n"
            "Report jump times in the user's local timezone and say which timezone you used. "
            "Flag scratchings clearly — a scratched runner changes the deductions on every other price. "
            "Distinguish fixed odds from tote/parimutuel: they are not comparable, and mixing them "
            "produces a spread that isn't real."
        )

    return True


def _register_whats_on(mcp, enabled: set[str]) -> bool:
    @mcp.prompt(
        name="whats-on-today",
        description="What's on today across the enabled sports feeds.",
    )
    def whats_on_today(sport: str = "all") -> str:
        return (
            f"Summarise what's on today (sport: {sport}).\n\n"
            "1. Call list_available_groups to see what's enabled — only report on those.\n"
            "2. Use fixtures/schedule tools (capability 'sport.fixtures_by_date') for each relevant league.\n"
            "3. Group by competition, ordered by start time, in the user's local timezone.\n\n"
            "Mark anything already in progress or finished with its current score. If a league has no "
            "fixtures today, say so briefly rather than omitting it — 'nothing on' is an answer."
        )

    return True


def _register_team_deep_dive(mcp, enabled: set[str]) -> bool:
    @mcp.prompt(
        name="team-deep-dive",
        description="Form, ladder position and recent results for one team, from official feeds.",
    )
    def team_deep_dive(team: str) -> str:
        return (
            f"Build a picture of {team} from the enabled data.\n\n"
            "1. Find the team via a reference/teams tool to get its id — don't guess ids.\n"
            "2. Pull: current ladder/standings position, last five results, and next fixture.\n"
            "3. Add player-level detail (injuries, leaders) where a tool provides it.\n\n"
            "Prefer the official league feed over an aggregator where both are enabled, and say which "
            "source each number came from. If the season hasn't started or the team is between seasons, "
            "say that instead of reporting a stale ladder as current."
        )

    return True


def _register_fantasy(mcp, enabled: set[str]) -> bool:
    if not _has(enabled, "espnfantasy", "supercoach"):
        return False

    @mcp.prompt(
        name="fantasy-waiver-wire",
        description="Waiver-wire candidates for a fantasy league, ranked with the reasoning shown.",
    )
    def fantasy_waiver_wire(league_id: str = "", scoring_period: str = "current") -> str:
        return (
            f"Find waiver-wire adds (league: {league_id or 'ask the user'}, period: {scoring_period}).\n\n"
            "1. Read the league's settings first — scoring rules decide who is actually valuable, "
            "and a PPR league ranks differently from standard.\n"
            "2. Pull the free-agent / available pool, filtered to available players.\n"
            "3. Cross-reference the user's roster for positional need — a great player at a position "
            "they're already deep in is not a pickup.\n"
            "4. Rank candidates and show the reasoning: recent output, upcoming matchup, ownership trend, "
            "injury status.\n\n"
            "If the league is private and the call fails with a 401, tell the user they need to set the "
            "cookie rather than guessing at the roster."
        )

    return True


_REGISTRARS: tuple[Callable[..., bool], ...] = (
    _register_compare_odds,
    _register_arb_scan,
    _register_racing_next,
    _register_whats_on,
    _register_team_deep_dive,
    _register_fantasy,
)


def register_prompts(mcp, enabled: set[str]) -> list[str]:
    """Register the prompts whose tools are enabled. Returns the names registered."""
    registered: list[str] = []
    for fn in _REGISTRARS:
        name = fn.__name__.removeprefix("_register_").replace("_", "-")
        if fn(mcp, enabled):
            registered.append(name)
    return registered
