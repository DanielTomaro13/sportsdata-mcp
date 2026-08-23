"""Offline unit tests for `coverage`'s classification.

The interesting branch — a geo-blocked provider — cannot be exercised by running the
command, because the machine that developed it is in Australia and every AU book answers
happily. So the wire outcomes are injected here instead. Without these tests the blocked
path would ship having literally never executed.
"""

from __future__ import annotations

import asyncio

import pytest

from sportsdata_mcp.coverage import (
    CoverageReport,
    ProviderStatus,
    _name,
    _probe,
    _probe_endpoint,
)
from sportsdata_mcp.spec import Endpoint, Param, Provider, Spec


def _ep(name: str, *, params=None, method: str = "GET") -> Endpoint:
    return Endpoint(
        name=name,
        group="demo.public.core",
        summary="x",
        method=method,
        path="/thing",
        params=params or [],
    )


def _spec(*endpoints: Endpoint, region=None, requires_user_key: bool = False) -> Spec:
    return Spec(
        provider=Provider(
            id="demo",
            display_name="Demo (Australia)",
            base_urls={"default": "https://example.invalid"},
            region=region,
            requires_user_key=requires_user_key,
        ),
        endpoints=list(endpoints),
    )


# ── probe selection ────────────────────────────────────────────────────────────

def test_prefers_the_endpoint_with_fewest_params():
    few = _ep("few")
    many = _ep("many", params=[Param(name="a", **{"in": "query"}, type="string")])
    assert _probe_endpoint(_spec(many, few)) is few


def test_skips_endpoints_needing_an_invented_id():
    """A 404 from a made-up race id says nothing about reachability."""
    needs_id = _ep("needs_id", params=[Param(name="race_id", **{"in": "path"}, type="string", required=True)])
    assert _probe_endpoint(_spec(needs_id)) is None


def test_a_defaulted_required_param_is_still_probeable():
    defaulted = _ep(
        "defaulted",
        params=[Param(name="jurisdiction", **{"in": "query"}, type="string", required=True, default="NSW")],
    )
    assert _probe_endpoint(_spec(defaulted)) is defaulted


def test_non_get_endpoints_are_never_probed():
    assert _probe_endpoint(_spec(_ep("post", method="POST"))) is None


# ── classification ─────────────────────────────────────────────────────────────

def _run(spec: Spec, monkeypatch, *, status_code=None, raises=None):
    """Drive _probe with the wire outcome injected."""

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    class _FakeHTTP:
        def __init__(self, *a, **k):
            pass

        async def request(self, **kwargs):
            if raises is not None:
                raise raises
            return _Resp(status_code)

        async def aclose(self):
            pass

    monkeypatch.setattr("sportsdata_mcp.coverage.HTTPClient", _FakeHTTP)
    monkeypatch.setattr("sportsdata_mcp.coverage._interpolate_path", lambda ep, args: "/thing")
    monkeypatch.setattr("sportsdata_mcp.coverage._build_query", lambda ep, args: {})
    monkeypatch.setattr("sportsdata_mcp.coverage._build_headers", lambda ep, args: {})
    return asyncio.run(_probe(spec, object(), asyncio.Semaphore(1)))


def test_200_is_ok(monkeypatch):
    assert _run(_spec(_ep("e")), monkeypatch, status_code=200).status == "ok"


def test_451_is_blocked_even_without_region(monkeypatch):
    """451 Unavailable For Legal Reasons is unambiguous on the wire."""
    assert _run(_spec(_ep("e")), monkeypatch, status_code=451).status == "blocked"


def test_403_is_blocked_only_when_the_provider_claims_a_market(monkeypatch):
    with_region = _run(_spec(_ep("e"), region=["AU"]), monkeypatch, status_code=403)
    without = _run(_spec(_ep("e")), monkeypatch, status_code=403)
    assert with_region.status == "blocked"
    # No declared market means we have no business calling it a geo-block.
    assert without.status == "down"


def test_connection_failure_reads_as_blocked_for_a_regional_provider(monkeypatch):
    """An edge block refuses the connection; nothing replies to explain why."""
    blocked = _run(_spec(_ep("e"), region=["AU"]), monkeypatch, raises=OSError("refused"))
    plain = _run(_spec(_ep("e")), monkeypatch, raises=OSError("refused"))
    assert blocked.status == "blocked"
    assert plain.status == "down"


def test_byo_key_provider_is_never_probed(monkeypatch):
    r = _run(_spec(_ep("e"), requires_user_key=True), monkeypatch, raises=AssertionError("must not call"))
    assert r.status == "needs_key"


def test_unprobeable_provider_is_not_reported_as_down(monkeypatch):
    """Betfair and ESPN are dispatcher-based. Calling them broken would be a lie."""
    needs_id = _ep("needs_id", params=[Param(name="id", **{"in": "path"}, type="string", required=True)])
    r = _run(_spec(needs_id), monkeypatch, status_code=200)
    assert r.status == "unprobed"


# ── report shaping ─────────────────────────────────────────────────────────────

def test_usable_tools_counts_only_reachable_providers():
    report = CoverageReport(results=[
        ProviderStatus(id="a", display_name="A", status="ok", tools=10),
        ProviderStatus(id="b", display_name="B", status="blocked", tools=44, region=["AU"]),
        ProviderStatus(id="c", display_name="C", status="needs_key", tools=5),
    ])
    assert report.usable_tools == 10
    assert report.counts["blocked"] == 1


def test_by_status_orders_by_tool_count():
    report = CoverageReport(results=[
        ProviderStatus(id="small", display_name="S", status="ok", tools=1),
        ProviderStatus(id="big", display_name="B", status="ok", tools=50),
    ])
    assert [r.id for r in report.by_status("ok")] == ["big", "small"]


@pytest.mark.parametrize("name,expected_len", [("short", 5), ("x" * 80, 38)])
def test_long_display_names_are_truncated_so_columns_hold(name, expected_len):
    assert len(_name(name)) == expected_len
