"""`{{today}}` tokens in spec examples, and the lint rule that requires them.

A literal date in an example is wrong the day after it is written. On 2026-08-10 the
nightly drift check went red for Sportsbet because two examples asked for 2026-07-02 —
five weeks past, which Sportsbet answers with HTTP 400. The provider was perfectly
healthy; the example had rotted.

The same staleness reaches the MODEL, which is shown the example in the tool description
and learns to ask for a window the provider will reject.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from sportsdata_mcp import dates
from sportsdata_mcp.spec_loader import load_all_specs

TODAY = datetime.now(tz=UTC).date()


@pytest.mark.parametrize("token,expected", [
    ("{{today}}", TODAY),
    ("{{today+1}}", TODAY + timedelta(days=1)),
    ("{{today-1}}", TODAY - timedelta(days=1)),
    ("{{today+30}}", TODAY + timedelta(days=30)),
])
def test_tokens_render_to_iso_dates(token, expected):
    assert dates.render(token) == expected.isoformat()


def test_tokens_render_inside_a_larger_string():
    """Providers want times and suffixes around the date — a bare-date-only substitution
    would not have covered PointsBet's '-am' session token or TAB's naive datetimes."""
    assert dates.render("{{today}}T10:00:00") == f"{TODAY.isoformat()}T10:00:00"
    assert dates.render("{{today}}T23:59:59.000Z") == f"{TODAY.isoformat()}T23:59:59.000Z"
    assert dates.render("{{today-1}}-am") == f"{(TODAY - timedelta(days=1)).isoformat()}-am"


def test_two_tokens_in_one_string_render_independently():
    got = dates.render("{{today}}..{{today+2}}")
    assert got == f"{TODAY.isoformat()}..{(TODAY + timedelta(days=2)).isoformat()}"


@pytest.mark.parametrize("value", ["2024-08-16", "", "no tokens here", "{{tomorrow}}", "{{TODAY}}"])
def test_everything_else_passes_through_untouched(value):
    assert dates.render(value) == value


def test_non_strings_pass_through():
    assert dates.render(7) == 7
    assert dates.render(True) is True
    assert dates.render(None) is None


def test_nested_structures_are_rendered():
    """`string_csv` params arrive as lists, so a token inside one must still render."""
    got = dates.render({"dates": ["{{today}}", "x"], "n": 1})
    assert got == {"dates": [TODAY.isoformat(), "x"], "n": 1}


# ─── against the real specs ─────────────────────────────────────────────


def test_no_spec_example_carries_a_rotting_date():
    """The condition that broke the drift check. Enforced by `sportsdata-mcp lint` too,
    but pinned here so it fails in the normal test run rather than only in CI's lint
    step."""
    offenders = []
    for spec in load_all_specs():
        for ep in spec.endpoints:
            for ex in ep.examples:
                for key, value in (ex.params or {}).items():
                    for item in value if isinstance(value, list) else [value]:
                        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(item))
                        if not m:
                            continue
                        age = (TODAY - date(*map(int, m.groups()))).days
                        if 0 < age < 400:
                            offenders.append(f"{spec.provider.id}/{ep.name}: {key}={item} ({age}d)")
    assert not offenders, "examples with dates that rot:\n  " + "\n  ".join(offenders)


def test_the_providers_that_broke_now_use_tokens():
    """Named explicitly: these are the ones that actually failed, and a regression here
    would be a silent return to a red drift check."""
    by_id = {s.provider.id: s for s in load_all_specs()}
    for pid, tool in [
        ("sportsbet", "sportsbet_racing_allracing"),
        ("sportsbet", "sportsbet_sports_classes"),
        ("tab", "tab_racing_meetings"),
        ("pointsbet", "pointsbet_racing_meetings"),
    ]:
        ep = next(e for e in by_id[pid].endpoints if e.name == tool)
        params = str(ep.examples[0].params)
        assert "{{today" in params, f"{pid}/{tool} no longer uses a date token: {params}"


def test_rendered_example_params_are_usable_dates():
    """A token that rendered to something a provider cannot parse would just move the
    breakage. Every rendered value must start with a real ISO date."""
    for spec in load_all_specs():
        for ep in spec.endpoints:
            for ex in ep.examples:
                for key, value in dates.render_params(ex.params).items():
                    if not dates.has_token(str((ex.params or {}).get(key))):
                        continue
                    for item in value if isinstance(value, list) else [value]:
                        assert re.match(r"^\d{4}-\d{2}-\d{2}", str(item)), f"{ep.name}.{key}={item}"
