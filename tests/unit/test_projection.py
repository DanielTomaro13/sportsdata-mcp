"""Reductive response projection — the engine's second declared exception to passthrough.

It exists because FPL's `bootstrap-static` is one 1.37 MB blob holding six unrelated
datasets, of which the player rows alone are ~362,000 tokens. No context window holds
that, FPL offers no server-side field selection, and there is no narrower route to the
player list — so the choice was a flagship tool that blows the caller's context, or a
declared projection.

The contract that makes it safe is that it can only ever REMOVE. These tests pin that:
nothing is invented, renamed, reordered or coerced, and an endpoint that declares nothing
is untouched.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.project import apply_projection
from sportsdata_mcp.spec_loader import load_all_specs

BODY = {
    "elements": [
        {"id": 1, "web_name": "Raya", "now_cost": 60, "chance_of_playing_next_round": None, "junk": "x" * 50},
        {"id": 2, "web_name": "Salah", "now_cost": 145, "junk": "y" * 50},
    ],
    "teams": [{"id": 1, "name": "Arsenal"}],
    "total_players": 4085510,
}


def test_no_declaration_is_pure_passthrough():
    """The overwhelming majority of endpoints declare neither, and must be untouched —
    same object, not merely an equal copy."""
    assert apply_projection(BODY) is BODY


def test_pick_keeps_only_named_top_level_keys():
    got = apply_projection(BODY, pick=["teams"])
    assert set(got) == {"teams"}
    assert got["teams"] == [{"id": 1, "name": "Arsenal"}]


def test_pick_tolerates_a_key_the_provider_dropped():
    """A section vanishing upstream is drift for the nightly check to catch, not a reason
    to fail the caller's request."""
    got = apply_projection(BODY, pick=["teams", "no_such_section"])
    assert set(got) == {"teams"}


def test_fields_projects_list_items():
    got = apply_projection(BODY, pick=["elements"], fields=["id", "web_name"])
    assert got == {"elements": [{"id": 1, "web_name": "Raya"}, {"id": 2, "web_name": "Salah"}]}


def test_fields_applies_to_a_bare_list_body():
    body = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert apply_projection(body, fields=["a"]) == [{"a": 1}, {"a": 3}]


def test_a_missing_field_is_absent_not_null():
    """A provider that drops a field should look like one that dropped a field, not like
    one returning nulls — those mean different things to a model."""
    got = apply_projection(BODY, pick=["elements"], fields=["id", "chance_of_playing_next_round"])
    assert got["elements"][0] == {"id": 1, "chance_of_playing_next_round": None}
    assert "chance_of_playing_next_round" not in got["elements"][1]


def test_values_are_never_coerced_or_renamed():
    """The point of a REDUCTIVE transform: whatever survives is byte-for-byte upstream."""
    got = apply_projection(BODY, pick=["elements"], fields=["now_cost", "web_name"])
    assert got["elements"][1]["now_cost"] == 145  # still tenths-of-a-million, still int
    assert got["elements"][1]["web_name"] == "Salah"


def test_scalars_and_nested_objects_survive_fields():
    """`fields` targets ROWS. Gutting a metadata object would be the surprising reading."""
    body = {"meta": {"count": 2, "page": 1}, "rows": [{"a": 1, "b": 2}]}
    got = apply_projection(body, fields=["a"])
    assert got["meta"] == {"count": 2, "page": 1}
    assert got["rows"] == [{"a": 1}]


@pytest.mark.parametrize("body", [None, 7, "text", True, []])
def test_non_dict_non_list_bodies_pass_through(body):
    assert apply_projection(body, pick=["x"], fields=["y"]) == body


def test_projection_actually_solves_the_problem_it_was_built_for():
    """The measurement that justified the feature. If a future field set creeps back over
    a context window, this fails rather than the user's conversation."""
    players = [
        {f"field_{i}": "x" * 12 for i in range(105)} | {"id": n, "web_name": f"P{n}"}
        for n in range(581)
    ]
    import json

    full = len(json.dumps({"elements": players}))
    slim = len(json.dumps(apply_projection({"elements": players}, pick=["elements"], fields=["id", "web_name"])))
    assert full > 700_000, "fixture no longer resembles the real payload"
    assert slim < full / 20


# ─── against the real specs ─────────────────────────────────────────────


#: Providers allowed to project, and why. Passthrough is the default and a deviation
#: should be a deliberate, noticed decision rather than a habit — so adding a provider
#: here is the decision, and this comment is where it gets justified.
PROJECTING = {
    "fpl": "bootstrap-static is 1.4MB; fpl_players is ~58k tokens even projected",
    "sleeper": "the player id -> name table is 14.6MB across 12,221 players",
    # A different reason from the other two, and worth distinguishing: this payload is not
    # merely large, it is largely a COPY. Kambi's SGM pricer answers with the event's whole
    # bet-offer book — 626 offers, 647KB of a 610KB response — around a four-field result,
    # and unibet_kambi_call(event_betoffer) already serves exactly that book. Keeping it
    # would spend the entire response budget re-delivering data the caller can already get.
    "unibet": "the SGM pricer echoes the whole 647KB event book around a 4-field answer",
}


def test_projection_is_declared_only_where_it_was_argued_for():
    declaring = {
        s.provider.id
        for s in load_all_specs()
        for ep in s.endpoints
        if ep.response_pick or ep.response_fields
    }
    assert declaring <= set(PROJECTING), (
        f"unexpected providers projecting: {declaring - set(PROJECTING)} — if that is "
        "right, add it to PROJECTING with the reason"
    )


def test_fpl_player_tool_stays_within_a_usable_size():
    """The whole justification. 22 fields measured at ~58k tokens live; a field set that
    doubled would put the flagship tool back out of reach."""
    spec = next(s for s in load_all_specs() if s.provider.id == "fpl")
    players = next(e for e in spec.endpoints if e.name == "fpl_players")
    assert players.response_pick == ["elements"]
    assert 15 <= len(players.response_fields) <= 30, len(players.response_fields)


# ─── nested paths, and maps of rows ─────────────────────────────────────


def test_a_dotted_path_keeps_the_structure_and_picks_the_leaf():
    """Flat-only picking could not reach the fields that matter on the fattest feeds.
    SuperCoach ships 812 players with 124 stat fields each — 2.7MB — and the useful part
    is four of them, nested one level down."""
    item = {"id": 1, "team": {"abbrev": "ADE", "name": "Adelaide"}, "junk": "x"}
    assert apply_projection([item], fields=["id", "team.abbrev"]) == [
        {"id": 1, "team": {"abbrev": "ADE"}}
    ]


def test_a_dotted_path_maps_over_a_list_value():
    """`positions.position` must work whether a player has one position or three."""
    one = {"positions": [{"position": "FWD", "long": "Forward"}]}
    three = {"positions": [{"position": "FWD", "long": "F"}, {"position": "MID", "long": "M"}]}
    assert apply_projection([one], fields=["positions.position"]) == [
        {"positions": [{"position": "FWD"}]}
    ]
    assert apply_projection([three], fields=["positions.position"]) == [
        {"positions": [{"position": "FWD"}, {"position": "MID"}]}
    ]


def test_asking_for_the_whole_key_and_a_leaf_keeps_the_whole_key():
    """The broader request wins. Narrowing it would quietly discard data the spec asked
    for by name."""
    item = {"team": {"abbrev": "ADE", "name": "Adelaide"}}
    assert apply_projection([item], fields=["team", "team.abbrev"]) == [item]


def test_a_scalar_where_a_path_was_expected_is_kept_not_dropped():
    """The spec is then visibly wrong rather than invisibly lossy."""
    assert apply_projection([{"a": 5}], fields=["a.b"]) == [{"a": 5}]


def test_a_dotted_path_for_a_missing_key_is_simply_absent():
    assert apply_projection([{"id": 1}], fields=["id", "team.abbrev"]) == [{"id": 1}]


def test_a_map_of_rows_projects_every_value_but_only_when_declared():
    """Sleeper's player table is keyed by player id, so every VALUE is a row. Without the
    opt-in the projection was a no-op and the tool returned 14.6MB.

    It has to be declared rather than inferred: `{"13602": {...}}` (rows) and
    `{"league": {...}, "settings": {...}}` (sections) are indistinguishable from outside,
    and gutting the second would be silent data loss."""
    body = {
        "13602": {"full_name": "A B", "team": "KC", "college": "X"},
        "8800": {"full_name": "C D", "team": None, "college": "Y"},
    }
    assert apply_projection(body, fields=["full_name", "team"], is_map=True) == {
        "13602": {"full_name": "A B", "team": "KC"},
        "8800": {"full_name": "C D", "team": None},
    }
    # …and without the flag it is left exactly alone.
    assert apply_projection(body, fields=["full_name", "team"]) == body


def test_the_sleeper_player_table_declares_the_map_shape():
    """The bug this pairing exists to prevent: response_fields set, response_map not, and
    a 14.6MB tool that silently ignores its own projection."""
    spec = next(s for s in load_all_specs() if s.provider.id == "sleeper")
    players = next(e for e in spec.endpoints if e.name == "sleeper_players")
    assert players.response_fields, "sleeper_players must project — it is 14.6MB raw"
    assert players.response_map is True, (
        "sleeper_players returns an object keyed by player id, so response_map must be "
        "true or response_fields does nothing at all"
    )
