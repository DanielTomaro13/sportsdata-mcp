"""Structural invariants across every spec.

`sportsdata-mcp lint` checks capabilities and example dates. These are the checks a
full-codebase review turned up as worth having permanently — each one corresponds to a
real defect found in the 60-provider catalogue, or to a mistake that would be silent if
made.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from sportsdata_mcp.spec_loader import load_all_specs

SPECS = load_all_specs()
IDS = [s.provider.id for s in SPECS]


def test_tool_names_are_unique_across_providers():
    """MCP tool names are a flat namespace — a collision means one provider's tool
    silently shadows another's, and which one wins depends on registration order."""
    dupes = {n: c for n, c in Counter(t.name for s in SPECS for t in s.all_tools()).items() if c > 1}
    assert not dupes, f"duplicate tool names: {dupes}"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_every_declared_base_url_is_used(spec):
    """An unused base_url is a promise the catalogue does not keep. api-sports declared
    `handball` and `volleyball` hosts with no endpoints behind them, while the README and
    its doc page advertised "ten sports on one key" and delivered eight."""
    used = {ep.base for ep in spec.endpoints} | {d.base for d in spec.dispatchers if d.base}
    unused = set(spec.provider.base_urls) - used
    assert not unused, f"{spec.provider.id}: base_urls with no endpoints: {sorted(unused)}"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_path_placeholders_and_path_params_agree(spec):
    """A `{placeholder}` with no param is an un-fillable URL; a path param absent from
    the path is a value the caller supplies that goes nowhere."""
    for ep in spec.endpoints:
        declared = {p.name for p in ep.params if p.in_ == "path"}
        used = set(re.findall(r"\{(\w+)\}", ep.path))
        assert used <= declared, f"{ep.name}: path uses {sorted(used - declared)} with no `in: path` param"
        assert declared <= used, f"{ep.name}: declares path param(s) {sorted(declared - used)} not in {ep.path}"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_every_referenced_base_and_auth_key_exists(spec):
    for ep in spec.endpoints:
        assert ep.base in spec.provider.base_urls, f"{ep.name}: base '{ep.base}' undefined"
    for tool in spec.all_tools():
        if tool.auth:
            assert tool.auth in spec.provider.auth, f"{tool.name}: auth '{tool.auth}' undefined"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_examples_only_use_declared_params(spec):
    """An example naming a param the tool does not accept is guidance that fails when
    followed — and doctor probes with it, so it also breaks the drift check."""
    for ep in spec.endpoints:
        declared = {p.name for p in ep.params}
        for ex in ep.examples:
            unknown = set(ex.params or {}) - declared
            assert not unknown, f"{ep.name}: example uses undeclared param(s) {sorted(unknown)}"


@pytest.mark.parametrize("spec", SPECS, ids=IDS)
def test_examples_supply_every_required_param(spec):
    """Doctor prefers the first example when probing. One missing required param makes
    that endpoint unprobeable, which quietly shrinks drift coverage."""
    for ep in spec.endpoints:
        if not ep.examples:
            continue
        required = {p.name for p in ep.params if p.required}
        supplied = set(ep.examples[0].params or {}) | {p.name for p in ep.params if p.default is not None}
        assert required <= supplied, f"{ep.name}: example omits required {sorted(required - supplied)}"


def test_no_two_endpoints_share_a_cache_key_with_different_classify():
    """`apply_classify` mutates the response IN PLACE, and the GET cache hands the same
    object to every hit. Two endpoints that collide on (base, path, method) — the cache
    key ignores which tool asked — would therefore leak one's derived tags into the
    other's supposedly pass-through payload.

    No collision exists today; this test is what keeps that true, because the failure
    would look like data appearing from nowhere.
    """
    for spec in SPECS:
        seen: dict[tuple, list] = {}
        for ep in spec.endpoints:
            if "{" in ep.path:  # path params vary by call, so no fixed-key collision
                continue
            seen.setdefault((ep.base, ep.path, ep.method), []).append(ep)
        for key, eps in seen.items():
            if len(eps) < 2:
                continue
            classify_shapes = {tuple(sorted(str(c) for c in (e.classify or []))) for e in eps}
            formats = {e.response_format for e in eps}
            assert len(classify_shapes) == 1, f"{spec.provider.id} {key}: differing classify on a shared path"
            assert len(formats) == 1, f"{spec.provider.id} {key}: differing response_format on a shared path"


# ─── live racing prices must not be cached ──────────────────────────────

#: The endpoints the racing board polls for PRICES, as opposed to for discovery.
#: Each returns a racecard whose numbers move continuously while a race is open.
RACING_PRICE_ENDPOINTS = {
    "tab_racing_race",
    "pointsbet_racing_race",
    "sportsbet_racecard",
    "entain_racing_racecard",
    "dabble_competition_fixtures",
    "dabble_fixture_details",
}


def test_racing_price_endpoints_are_never_cached():
    """THE defect this pins, measured 2026-08-31.

    `CACHE_TTL_DEFAULT` is 60s and applies to every GET. None of these endpoints opted
    out, so the racing board — which polls prices every 8 seconds — was served the same
    bytes for a minute at a time. Five calls to a live meeting over 12 seconds returned an
    identical body hash in 12-25ms, against 311ms cold: every repeat was the cache.

    Nothing errored. The board just showed prices that did not move, and any work to poll
    *faster* was silently pointless, because the second call in a minute can never return
    a new number. That is the same reasoning `entain_sgm_price` was given `never_cache`
    for: a price re-read from cache defeats the comparison, because it is the same number.

    Discovery endpoints (`tab_racing_meetings`, `dabble_active_competitions`, …) keep the
    cache deliberately — they change per day, not per second, and the hit is worth ~100x
    on repeat.
    """
    by_name = {t.name: t for s in SPECS for t in s.all_tools()}
    missing = sorted(
        n for n in RACING_PRICE_ENDPOINTS
        if n in by_name and not getattr(by_name[n], "never_cache", False)
    )
    assert not missing, (
        f"racing price endpoints served from the 60s cache: {missing}. "
        "A cached racecard makes fast polling return identical numbers — set never_cache."
    )
    unknown = sorted(n for n in RACING_PRICE_ENDPOINTS if n not in by_name)
    assert not unknown, f"endpoint renamed or removed — update this list: {unknown}"
