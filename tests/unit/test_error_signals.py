"""A 200 that carries an error body must not reach the model as data.

Two providers in this catalogue never use HTTP status codes for failures:

    api-tennis   HTTP 200  {"error":"1","result":[{"param":"APIkey","msg":"…mandatory"}]}
    cricketdata  HTTP 200  {"status":"failure","reason":"Invalid API Key"}

Both verified live on 2026-08-10. Without `error_signals` the engine sees a 2xx, decodes
the JSON and hands the object straight to the model — which then reports the validation
complaint as though it were a tennis draw or a cricket scorecard. That is the worst
failure this codebase has: not an error, but a confident wrong answer. Hence a dedicated
test module.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec_loader import load_all_specs


def _client(provider, monkeypatch, body, status=200):
    def handler(request):
        return httpx.Response(status, json=body)

    c = HTTPClient(provider, Config())
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._cache_ttl = 0.0  # a cached error would mask the assertion
    return c


def _provider(pid):
    return next(s.provider for s in load_all_specs() if s.provider.id == pid)


@pytest.mark.anyio
async def test_apitennis_error_one_becomes_a_tool_error(monkeypatch):
    p = _provider("apitennis")
    body = {"error": "1", "result": [{"param": "APIkey", "msg": "The field is mandatory", "cod": 1005}]}
    c = _client(p, monkeypatch, body)
    with pytest.raises(ToolError) as e:
        await c.request_json(method="GET", base="default", url="/tennis/", auth_key="default")
    assert "error body" in str(e.value)


@pytest.mark.anyio
async def test_cricketdata_status_failure_becomes_a_tool_error(monkeypatch):
    p = _provider("cricketdata")
    c = _client(p, monkeypatch, {"status": "failure", "reason": "Invalid API Key"})
    with pytest.raises(ToolError) as e:
        await c.request_json(method="GET", base="default", url="/currentMatches", auth_key="default")
    # The upstream's own `reason` is the most useful thing we can show, so surface it.
    assert "Invalid API Key" in str(e.value)


@pytest.mark.anyio
async def test_the_error_names_the_env_var_to_set(monkeypatch):
    """The user's next action is 'set this variable' — say which one."""
    monkeypatch.delenv("CRICKETDATA_API_KEY", raising=False)
    p = _provider("cricketdata")
    c = _client(p, monkeypatch, {"status": "failure", "reason": "Invalid API Key"})
    with pytest.raises(ToolError) as e:
        await c.request_json(method="GET", base="default", url="/currentMatches", auth_key="default")
    assert "CRICKETDATA_API_KEY" in str(e.value)
    assert e.value.code == "AUTH_REQUIRED"


@pytest.mark.anyio
async def test_success_bodies_pass_through_untouched(monkeypatch):
    """The signal must be exact-match. cricketdata's happy path is status='success', and
    api-tennis returns success:1 with NO `error` key at all — neither may be caught."""
    cd = _client(_provider("cricketdata"), monkeypatch, {"status": "success", "data": [{"id": "abc"}]})
    got = await cd.request_json(method="GET", base="default", url="/currentMatches", auth_key="default")
    assert got["data"] == [{"id": "abc"}]

    at = _client(_provider("apitennis"), monkeypatch, {"success": 1, "result": [{"event_key": 1}]})
    got = await at.request_json(method="GET", base="default", url="/tennis/", auth_key="default")
    assert got["result"] == [{"event_key": 1}]


@pytest.mark.anyio
async def test_error_zero_is_not_an_error(monkeypatch):
    """api-tennis uses the STRING "1" for failure. A hypothetical error:"0" — or the
    integer 1 in a different field — must not trip the signal by accident."""
    c = _client(_provider("apitennis"), monkeypatch, {"error": "0", "result": [{"event_key": 1}]})
    got = await c.request_json(method="GET", base="default", url="/tennis/", auth_key="default")
    assert got["result"]


@pytest.mark.anyio
async def test_providers_without_signals_are_unaffected(monkeypatch):
    """Most providers use status codes properly. A body that happens to contain a
    `status` field must not be reinterpreted for them."""
    c = _client(_provider("nhl"), monkeypatch, {"status": "failure", "games": []})
    got = await c.request_json(method="GET", base="default", url="/schedule/now", auth_key="default")
    assert got["status"] == "failure"  # passed through as ordinary data


@pytest.mark.anyio
async def test_list_bodies_are_not_probed(monkeypatch):
    """Signals are top-level dict keys; a JSON array body must short-circuit cleanly
    rather than raising a TypeError inside the engine."""
    c = _client(_provider("apitennis"), monkeypatch, [{"error": "1"}])
    got = await c.request_json(method="GET", base="default", url="/tennis/", auth_key="default")
    assert got == [{"error": "1"}]


#: Keyless providers that legitimately need an error signal, and why.
#
# The rule below asked for "a deliberate look" the first time a keyless provider needed
# one. MyFantasyLeague is that case, and it is a different reason from every other entry:
# it answers HTTP 200 with an error document for EVERYTHING — a bad league id on a fully
# public call, not merely an auth failure — so the signal is not about credentials at all.
# Marking it `requires_user_key` to satisfy the rule would have been a lie that leaks into
# the BYO-tier UX, since its reference endpoints work with nothing configured.
KEYLESS_WITH_SIGNALS = {
    "myfantasyleague": "answers 200 + an error document for every failure, auth or not",
}


def test_every_declared_signal_is_justified():
    """Not a rule of the engine, but a rule of this catalogue: a signal is declared either
    because the API reports AUTH failures with a 200 (the BYO case), or because it reports
    ALL failures that way and the exemption is written down above. A silent third reason
    is what this is here to prevent."""
    for spec in load_all_specs():
        if not spec.provider.error_signals:
            continue
        pid = spec.provider.id
        assert spec.provider.requires_user_key or pid in KEYLESS_WITH_SIGNALS, (
            f"{pid} declares an error signal but needs no key — if that is correct, add it "
            f"to KEYLESS_WITH_SIGNALS with the reason"
        )


def test_the_keyless_exemptions_still_declare_signals():
    """An exemption that outlives its signal is stale documentation."""
    by_id = {s.provider.id: s for s in load_all_specs()}
    for pid in KEYLESS_WITH_SIGNALS:
        assert pid in by_id, f"{pid} is exempted but no longer exists"
        assert by_id[pid].provider.error_signals, f"{pid} no longer declares a signal"


# ─── presence mode and the string-zero trap ─────────────────────────────


@pytest.mark.parametrize("value", [0, "0", "", "0.0", "false", None, [], {}])
@pytest.mark.anyio
async def test_presence_mode_treats_these_as_success(monkeypatch, value):
    """iSportsAPI signals success with `code: 0`, and JSON APIs flip between `0` and
    `"0"` without warning — but Python calls the STRING "0" truthy. Before this, a
    provider that started quoting its status code would have had every SUCCESSFUL call
    raised as an error."""
    c = _client(_provider("isportsapi"), monkeypatch, {"code": value, "data": [{"id": 1}]})
    got = await c.request_json(method="GET", base="default", url="/x", auth_key="default")
    assert got["data"] == [{"id": 1}]


@pytest.mark.parametrize("value", [2, "2", 1, "failure", ["something"]])
@pytest.mark.anyio
async def test_presence_mode_still_catches_real_failures(monkeypatch, value):
    """The loosening must not blunt the guard — a non-zero code is still an error
    whether it arrives as a number or a string."""
    c = _client(_provider("isportsapi"), monkeypatch, {"code": value, "message": "Invalid [api_key]"})
    with pytest.raises(ToolError):
        await c.request_json(method="GET", base="default", url="/x", auth_key="default")
