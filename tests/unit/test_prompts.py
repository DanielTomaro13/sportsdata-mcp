"""Curated prompts, and the gating that keeps them honest.

A prompt is a promise about what the server can do. Registering "compare odds across
every book" on an install with no bookmakers enabled sends the model hunting for tools
that don't exist, so the gating below is the actual feature — not the prompt text.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs


async def _prompts(selector: list[str]) -> set[str]:
    specs = load_all_specs()
    mcp, reg = build_server(Config(enabled_groups=expand_wildcard_groups(selector, specs)))
    try:
        return {p.name for p in await mcp.list_prompts()}
    finally:
        await reg.aclose()


async def test_full_install_registers_every_prompt():
    assert await _prompts(["all"]) == {
        "compare-odds",
        "arb-scan",
        "racing-next-to-go",
        "whats-on-today",
        "team-deep-dive",
        "fantasy-waiver-wire",
    }


async def test_official_stats_gets_no_betting_prompts():
    """Someone who deliberately picked the no-bookmaker preset must not be offered
    odds workflows."""
    names = await _prompts(["official-stats"])
    assert names == {"whats-on-today", "team-deep-dive"}


async def test_arb_scan_needs_a_sharp_reference():
    """Measuring books against a de-vigged line is meaningless without an exchange or
    prediction market to de-vig, so the prompt must not appear for books alone."""
    books_only = await _prompts(["sportsbet", "tab"])
    assert "compare-odds" in books_only
    assert "arb-scan" not in books_only
    assert "arb-scan" in await _prompts(["sportsbet", "betfair"])


async def test_racing_prompt_requires_racing_groups():
    assert "racing-next-to-go" not in await _prompts(["mlb.reference"])
    assert "racing-next-to-go" in await _prompts(["racing"])


async def test_motorsport_does_not_trigger_the_horse_racing_prompt():
    """motogp.racing / formulae.racing / nascar.racing all end in ".racing" but have no
    tote pools, scratchings or next-to-go. The original gate was a name heuristic and
    started offering the horse-racing workflow to MotoGP installs the moment motorsport
    landed — this pins the fix."""
    names = await _prompts(["motorsport"])
    assert "racing-next-to-go" not in names


async def test_fantasy_prompt_requires_a_fantasy_provider():
    assert "fantasy-waiver-wire" not in await _prompts(["official-stats"])
    assert "fantasy-waiver-wire" in await _prompts(["fantasy"])


async def test_universal_prompts_survive_a_minimal_install():
    """These two need only the meta-tools, so they should always be there — a server
    with one group enabled still answers 'what's on'."""
    names = await _prompts(["mlb.reference"])
    assert {"whats-on-today", "team-deep-dive"} <= names


@pytest.fixture(scope="module")
async def full_server():
    """One fully-loaded server for the render tests — building a 522-tool server per
    parametrised case made this file a 20-second unit test."""
    specs = load_all_specs()
    mcp, reg = build_server(Config(enabled_groups=expand_wildcard_groups(["all"], specs)))
    try:
        yield mcp
    finally:
        await reg.aclose()


@pytest.mark.parametrize("name,args", [
    ("compare-odds", {"event": "Parramatta v Penrith"}),
    ("arb-scan", {"competition": "NRL"}),
    ("racing-next-to-go", {}),
    ("whats-on-today", {}),
    ("team-deep-dive", {"team": "Hawthorn"}),
    ("fantasy-waiver-wire", {}),
])
async def test_every_prompt_renders(full_server, name, args):
    prompt = await full_server.get_prompt(name)
    out = await prompt.render(args)
    assert len(out.messages[0].content.text) > 120, f"{name} rendered suspiciously short"


async def test_prompts_insist_on_tool_provenance(full_server):
    """The point of this server is that numbers trace to a tool result. A prompt that
    let the model answer from memory would quietly undo that — and for arb-scan, an
    edge computed from a remembered price is the error that costs real money."""
    for name in ("compare-odds", "arb-scan"):
        prompt = await full_server.get_prompt(name)
        text = (await prompt.render({"event": "x", "competition": "x"})).messages[0].content.text
        assert "memory" in text.lower() and "tool result" in text.lower()
