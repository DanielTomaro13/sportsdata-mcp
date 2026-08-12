"""UFC — registration (offline) + live probes against ufc.com's JSON:API.

This provider exists because the obvious source does not work: ufcstats.com serves a
JavaScript proof-of-work bot challenge with zero data rows in the HTML. ufc.com runs
Drupal with JSON:API exposed, and `athlete_stat` carries the same FightMetric dataset —
officially, keylessly, and from paths robots.txt permits.

The live tests are deliberately few and slow. robots.txt asks for `crawl-delay: 15` and
the provider is capped at 0.5 rps; a test suite that hammers a courtesy-rate-limited
public endpoint is a good way to lose access to it.

Run with::

    pytest -m live tests/integration/test_ufc.py
"""

from __future__ import annotations

import json

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server
from sportsdata_mcp.spec_loader import load_all_specs


@pytest.fixture
async def server():
    mcp, reg = build_server(Config(enabled_groups=["ufc.events", "ufc.athletes", "ufc.stats", "ufc.records"]))
    try:
        yield mcp
    finally:
        await reg.aclose()


def _payload(result):
    return json.loads(result.content[0].text)


# ─── offline ────────────────────────────────────────────────────────────


async def test_all_tools_register(server):
    names = {t.name for t in await server.list_tools()}
    assert {
        "ufc_events", "ufc_event_card", "ufc_fights", "ufc_search_athletes",
        "ufc_athlete", "ufc_athlete_stats", "ufc_rankings", "ufc_round_records",
        "ufc_jsonapi_index",
    } <= names


def test_rate_limit_respects_the_crawl_delay():
    """robots.txt asks for crawl-delay: 15. The cap is a deliberate courtesy, and a
    future edit raising it "to make things faster" should have to argue with a test."""
    spec = next(s for s in load_all_specs() if s.provider.id == "ufc")
    assert spec.provider.defaults.rate_limit_rps <= 0.5


def test_no_custom_entity_tool_exposes_a_filter():
    """Filtering works on `node/*` resources and SILENTLY RETURNS 0 ROWS on every custom
    entity collection here — verified with ids present on page 1 of each. A parameter
    that quietly yields an empty list is worse than no parameter: a model reports "no
    ranking" for a ranked fighter.

    Derived from the path rather than listed per tool. The first version of this test
    named athlete_stat and fight_roundboard explicitly — and missed athlete_ranking,
    which shipped in v0.25.0 with exactly the broken parameter this was meant to prevent.
    A rule that has to be remembered for each new endpoint is not a rule.
    """
    spec = next(s for s in load_all_specs() if s.provider.id == "ufc")
    for ep in spec.endpoints:
        if ep.path.startswith("/node/") or ep.path == "/":
            continue  # node resources DO support filtering; /  is the index
        offenders = [p.wire_name for p in ep.params if p.wire_name.startswith("filter[")]
        assert not offenders, (
            f"{ep.name} ({ep.path}) exposes {offenders}; filters on custom entities "
            f"return 0 rows rather than erroring"
        )


def test_the_provider_is_keyless():
    spec = next(s for s in load_all_specs() if s.provider.id == "ufc")
    assert spec.provider.requires_user_key is False
    assert spec.provider.shapes_verified is True


# ─── live ───────────────────────────────────────────────────────────────


@pytest.mark.live
async def test_events_carry_card_times_and_location(server):
    data = _payload(await server.call_tool("ufc_events", {"limit": 3}))["data"]
    assert data
    attrs = data[0]["attributes"]
    assert attrs["title"]
    # The three segment times are the reason to use this over a generic fixture feed.
    assert any(k in attrs for k in ("fight_card_time_main", "fight_card_time_prelims"))


@pytest.mark.live
async def test_an_event_card_arrives_in_included_not_inline(server):
    """The JSON:API gotcha, pinned: the bouts are NOT on the event object."""
    body = _payload(await server.call_tool("ufc_event_card", {"title": "UFC 330"}))
    assert body["data"], "no such event"
    assert body.get("included"), "include= returned nothing — the card would be invisible"
    assert any(r["type"] == "node--fight" for r in body["included"])


@pytest.mark.live
async def test_athlete_stats_are_the_fightmetric_table(server):
    """The whole point of the provider. If these fields vanish, the value does too."""
    body = _payload(await server.call_tool("ufc_athlete", {"title": "Ilia Topuria"}))
    stats = [r for r in body.get("included", []) if r["type"].startswith("athlete_stat")]
    assert stats, "no athlete_stat included — a fighter with no statistics"
    a = stats[0]["attributes"]
    for field in (
        "sig_strikes_landed", "sig_strikes_attempted", "sig_strikes_accuracy",
        "stand_str_land", "clinch_str_land", "ground_str_land",
        "head_str_land", "body_str_land", "leg_str_land",
        "takedowns_landed", "takedown_defense", "submission_average",
        "sig_str_land_min", "sig_str_abs_min", "sig_str_def", "knockdown_average",
        "career_fights", "career_wins", "win_ko", "win_sub", "win_dec",
    ):
        assert field in a, f"lost the {field} field"
    # Misspelled UPSTREAM. Correcting it in the spec would return nothing.
    assert "takedown_acuracy" in a


@pytest.mark.live
async def test_stats_sort_produces_a_real_leaderboard(server):
    """Sorting is the substitute for the filtering this collection cannot do, so it has
    to actually sort."""
    data = _payload(await server.call_tool(
        "ufc_athlete_stats", {"sort": "-sig_strikes_landed", "limit": 5}
    ))["data"]
    landed = [int(r["attributes"]["sig_strikes_landed"]) for r in data]
    assert landed == sorted(landed, reverse=True), landed
    assert landed[0] > 1000, "top striker should have four figures of significant strikes"


@pytest.mark.live
async def test_search_finds_a_fighter_by_partial_name(server):
    data = _payload(await server.call_tool("ufc_search_athletes", {"name": "Adesanya"}))["data"]
    assert data and "Adesanya" in data[0]["attributes"]["title"]
    assert data[0]["attributes"]["fightmetric_id"], "no id to join stats with"


@pytest.mark.live
async def test_rankings_and_round_records_return_rows(server):
    ranks = _payload(await server.call_tool("ufc_rankings", {"limit": 5}))["data"]
    assert ranks and "weight_class_rank" in ranks[0]["attributes"]

    records = _payload(await server.call_tool("ufc_round_records", {"limit": 10}))["data"]
    assert records
    a = records[0]["attributes"]
    assert {"round", "statname", "value", "rank"} <= set(a)
