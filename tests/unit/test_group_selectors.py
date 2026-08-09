"""Group selectors: presets, provider globs, bare provider ids, and exclusions.

The selector language is the first thing a new user meets — with 88 groups, nobody
should have to enumerate them by hand. It is also load-bearing for tooling: the drift
workflow builds a selector from a list of provider ids, and a selector that silently
matches NOTHING is the dangerous failure (a job then "passes" over an empty tool set),
so several tests below pin exactly that.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.spec_loader import PRESETS, expand_wildcard_groups, load_all_specs, resolve_groups

GROUPS = ["afl.public.core", "afl.premium.cfs", "espn.scores", "espn.core", "mlb.reference", "twitter.tweets"]


# ─── the pure resolver ──────────────────────────────────────────────────


def test_star_selects_everything():
    assert resolve_groups(["*"], GROUPS) == sorted(GROUPS)


def test_literal_group_selects_itself():
    assert resolve_groups(["mlb.reference"], GROUPS) == ["mlb.reference"]


def test_bare_provider_id_selects_all_its_groups():
    assert resolve_groups(["espn"], GROUPS) == ["espn.core", "espn.scores"]


def test_provider_glob_selects_all_its_groups():
    """`espn.*` reads as 'every espn group' to anyone who has used a shell. Before this
    it was treated as a literal group name and matched nothing — which made doctor exit
    0 having probed nothing at all."""
    assert resolve_groups(["espn.*"], GROUPS) == ["espn.core", "espn.scores"]


def test_deeper_glob_works():
    assert resolve_groups(["afl.public.*"], GROUPS) == ["afl.public.core"]


def test_exclusion_subtracts():
    out = resolve_groups(["*", "-twitter"], GROUPS)
    assert "twitter.tweets" not in out
    assert len(out) == len(GROUPS) - 1


def test_exclusion_applies_regardless_of_order():
    """Additions are resolved before exclusions, so '-x,*' means the same as '*,-x'."""
    assert resolve_groups(["-twitter", "*"], GROUPS) == resolve_groups(["*", "-twitter"], GROUPS)


def test_exclusion_accepts_globs_and_literals():
    assert "espn.core" not in resolve_groups(["*", "-espn.*"], GROUPS)
    assert "espn.core" not in resolve_groups(["*", "-espn.core"], GROUPS)
    assert "espn.scores" in resolve_groups(["*", "-espn.core"], GROUPS)


def test_unknown_token_selects_nothing_not_everything():
    """A typo must not silently widen the tool set."""
    assert resolve_groups(["nosuchprovider"], GROUPS) == []


def test_empty_and_whitespace_tokens_ignored():
    assert resolve_groups(["", "  ", "mlb.reference"], GROUPS) == ["mlb.reference"]


def test_result_is_sorted_and_deduped():
    assert resolve_groups(["espn", "espn.*", "espn.core"], GROUPS) == ["espn.core", "espn.scores"]


# ─── against the real specs ─────────────────────────────────────────────


def test_every_preset_resolves_to_something():
    """A preset that resolves to nothing would start a server with no tools."""
    specs = load_all_specs()
    for name in PRESETS:
        assert expand_wildcard_groups([name], specs), f"preset '{name}' resolved to no groups"


def test_free_preset_needs_no_user_supplied_key():
    """`free` is the zero-setup promise: every provider in it must work with an empty
    environment. datagolf and twitter are the only two that genuinely don't — laliga
    ships a public key and afl.premium mints its token from a public endpoint."""
    specs = load_all_specs()
    provs = {g.split(".")[0] for g in expand_wildcard_groups(["free"], specs)}
    assert "datagolf" not in provs and "twitter" not in provs
    assert {"laliga", "afl", "espn", "sportsbet"} <= provs


def test_free_is_a_strict_subset_of_all():
    specs = load_all_specs()
    free = set(expand_wildcard_groups(["free"], specs))
    every = set(expand_wildcard_groups(["all"], specs))
    assert free < every


def test_backwards_compatible_with_plain_group_lists():
    """Existing configs pass literal group names — they must keep resolving to themselves."""
    specs = load_all_specs()
    assert expand_wildcard_groups(["mlb.reference"], specs) == ["mlb.reference"]
    assert expand_wildcard_groups([], specs) == []


@pytest.mark.parametrize("preset,must_include", [
    ("racing", "sportsbet.racing"),
    ("arb", "betfair.exchange"),
    ("fantasy", "espnfantasy.league"),
    ("au-books", "tab.sports"),
    ("official-stats", "mlb.reference"),
])
def test_presets_contain_their_headline_group(preset, must_include):
    specs = load_all_specs()
    assert must_include in expand_wildcard_groups([preset], specs)


def test_official_stats_preset_has_no_bookmakers():
    """The preset promises official league feeds — a bookmaker leaking in would break
    that promise for anyone using it to avoid gambling surfaces."""
    specs = load_all_specs()
    provs = {g.split(".")[0] for g in expand_wildcard_groups(["official-stats"], specs)}
    books = {"sportsbet", "tab", "betr", "pointsbet", "unibet", "entain", "dabble", "betfair", "pinnacle", "fanduel"}
    assert not (provs & books), f"bookmakers in official-stats: {provs & books}"
