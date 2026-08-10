"""`metrics.py --html` must render from whatever the collectors managed to fetch.

Every upstream here is best-effort: pypistats rate-limits unauthenticated callers, and
the GitHub traffic API is unavailable unless the token has admin read. A report that
raised on a missing section would turn "one API was slow" into "no report", which is the
opposite of useful.

No network in these tests — they feed `html_report` fixed dicts, which is the only part
that has to be right.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "metrics", pathlib.Path(__file__).resolve().parents[2] / "scripts" / "metrics.py"
)
metrics = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(metrics)

FULL = {
    "collected_at": "2026-08-11T09:38:00+10:00",
    "downloads_recent": {"last_day": 37, "last_week": 239, "last_month": 686},
    "downloads_without_mirrors": {"last_7d": 225, "prev_7d": 88, "last_30d": 671, "prev_30d": 1000},
    "pypi": {"latest": "0.24.0", "releases": 11},
    "github": {
        "stars": 3, "forks": 2, "open_issues": 0,
        "clones": {"count": 218, "uniques": 93},
        "views": {"count": 468, "uniques": 111},
        "referrers": [{"source": "github.com", "views": 133, "uniques": 17}],
    },
}


def test_a_full_report_contains_every_section():
    html = metrics.html_report(FULL)
    for expected in ("Reach", "People", "Where they come from", "239 this week", "93", "v0.24.0", "github.com"):
        assert expected in html


def test_the_report_declares_utf8():
    """The body is full of em dashes and middle dots. Without an explicit charset a
    client that guesses latin-1 renders them as "â€" — which is what the first version
    did when previewed."""
    html = metrics.html_report(FULL)
    assert html.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in html
    assert "—" in html


def test_no_external_resources():
    """Email clients block remote images and strip stylesheets. Everything must be
    inline, or the report arrives as unstyled soup with a 'load images?' banner."""
    html = metrics.html_report(FULL)
    for banned in ("<img", "<script", "<link", "http://", "background-image"):
        assert banned not in html


@pytest.mark.parametrize("drop", ["downloads_recent", "downloads_without_mirrors", "pypi", "github"])
def test_a_missing_section_does_not_break_the_email(drop):
    """pypistats 429s readily and the traffic API needs admin read. Losing one source
    must cost one section, not the whole email."""
    data = {k: v for k, v in FULL.items() if k != drop}
    html = metrics.html_report(data)
    assert html.startswith("<!doctype html>")
    assert "sportsdata-mcp" in html


def test_a_traffic_error_is_reported_not_hidden():
    """If the token cannot read traffic, the email should say so — otherwise a silently
    missing People section reads as 'nobody visited this week'."""
    data = {**FULL, "github": {"error": "gh CLI unavailable, not authenticated, or not a repo admin"}}
    html = metrics.html_report(data)
    assert "unavailable" in html


def test_an_empty_report_still_renders():
    html = metrics.html_report({"collected_at": "2026-08-11T09:38:00+10:00"})
    assert html.startswith("<!doctype html>")
    assert "</html>" in html


@pytest.mark.parametrize("now,before,expect", [
    (225, 88, "+156%"), (671, 1000, "-33%"), (100, 100, "+0%"), (5, 0, "no prior window"),
])
def test_trend_arithmetic(now, before, expect):
    assert expect in metrics._trend(now, before)

