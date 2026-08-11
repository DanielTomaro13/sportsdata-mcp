"""Telemetry: off by default, and structurally incapable of leaking arguments.

The claims in docs/TELEMETRY.md are only worth making if they are enforced. Prose in a
privacy doc rots the moment someone adds a field "just for debugging"; these tests are
what stop that being a silent change.

The strongest guarantee here is not a filter — it is that `Telemetry.record` HAS NO
PARAMETER capable of accepting a tool's arguments or its response. A filter can be
bypassed by the next person to touch the call site; a signature cannot.
"""

from __future__ import annotations

import inspect
import json

import pytest

from sportsdata_mcp import telemetry


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Never touch the developer's real ~/.sportsdata-mcp while testing."""
    monkeypatch.setenv("SPORTSDATA_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SPORTSDATA_TELEMETRY", raising=False)
    monkeypatch.delenv("SPORTSDATA_TELEMETRY_ENDPOINT", raising=False)


# ─── opt-in ─────────────────────────────────────────────────────────────


def test_sharing_is_off_by_default():
    assert telemetry.is_enabled() is False
    assert telemetry.endpoint() is None


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_consent_accepts_the_obvious_spellings(monkeypatch, value):
    monkeypatch.setenv("SPORTSDATA_TELEMETRY", value)
    assert telemetry.is_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  ", "maybe"])
def test_anything_ambiguous_is_treated_as_no(monkeypatch, value):
    """Consent must fail CLOSED. 'maybe' is not yes."""
    monkeypatch.setenv("SPORTSDATA_TELEMETRY", value)
    assert telemetry.is_enabled() is False


def test_consent_cannot_come_from_a_config_file():
    """Deliberate design constraint, worth pinning: a config file can be committed to a
    repo, pasted into a gist or baked into a Docker image, none of which is the person at
    the keyboard agreeing. Only the env var counts.

    Asserted on the SIGNATURE rather than by scanning the source, because the source
    mentions "config file" in the comment explaining exactly this — and a test that trips
    on its own explanation is a test nobody keeps.
    """
    assert not inspect.signature(telemetry.is_enabled).parameters
    assert not inspect.signature(telemetry.endpoint).parameters


@pytest.mark.anyio
async def test_no_endpoint_means_no_send_even_when_enabled(monkeypatch):
    """A typo'd endpoint variable must not fall back to some default host."""
    monkeypatch.setenv("SPORTSDATA_TELEMETRY", "1")
    tel = telemetry.Telemetry()
    tel.record("nhl_schedule", ok=True, seconds=0.1)
    assert await telemetry.flush(tel) is False


@pytest.mark.anyio
async def test_disabled_flush_sends_nothing_even_with_an_endpoint(monkeypatch):
    monkeypatch.setenv("SPORTSDATA_TELEMETRY_ENDPOINT", "https://example.invalid/t")
    tel = telemetry.Telemetry()
    tel.record("nhl_schedule", ok=True, seconds=0.1)
    assert await telemetry.flush(tel) is False


@pytest.mark.anyio
async def test_flush_never_raises(monkeypatch):
    """The person enabled this as a favour; it must not be able to break their session."""
    monkeypatch.setenv("SPORTSDATA_TELEMETRY", "1")
    monkeypatch.setenv("SPORTSDATA_TELEMETRY_ENDPOINT", "https://this-host-does-not-exist.invalid/t")
    tel = telemetry.Telemetry()
    tel.record("nhl_schedule", ok=True, seconds=0.1)
    assert await telemetry.flush(tel) is False  # not an exception


# ─── what cannot be recorded ────────────────────────────────────────────


def test_record_cannot_accept_arguments_or_results():
    """The central guarantee. If someone later adds `args` or `result` here, this fails —
    which is the point. Tool arguments in this catalogue are not innocuous: an ESPN
    Fantasy league id identifies a league and its members, and a Sleeper username IS a
    username."""
    params = set(inspect.signature(telemetry.Telemetry.record).parameters)
    assert params == {"self", "tool", "ok", "seconds", "code", "empty"}
    for banned in ("args", "kwargs", "params", "result", "response", "body", "query", "url"):
        assert banned not in params


def test_payload_contains_no_identifying_fields():
    tel = telemetry.Telemetry()
    tel.record("nhl_schedule", ok=True, seconds=0.4)
    blob = json.dumps(tel.payload(enabled_providers=3)).lower()
    for banned in ("hostname", "ip", "path", "home", "user", "email", "token", "apikey", "api_key", "secret"):
        assert banned not in blob, f"payload mentions {banned}"


def test_install_id_is_random_not_derived(monkeypatch, tmp_path):
    """Two installs on the same machine must not collide, and the id must not be
    reversible into anything about the machine."""
    first = telemetry.install_id()
    assert len(first) == 32
    (tmp_path / "install-id").unlink()
    assert telemetry.install_id() != first  # deleting it genuinely makes a new install


def test_install_id_survives_a_read_only_home(monkeypatch):
    monkeypatch.setenv("SPORTSDATA_STATE_DIR", "/proc/nonexistent-and-unwritable")
    got = telemetry.install_id()
    assert got.startswith("ephemeral-")  # degraded, not crashed


# ─── the counters themselves ────────────────────────────────────────────


def test_error_rate_is_what_it_claims():
    tel = telemetry.Telemetry()
    for _ in range(3):
        tel.record("t", ok=True, seconds=0.1)
    tel.record("t", ok=False, seconds=0.1, code="AUTH_REQUIRED")
    snap = tel.snapshot()
    assert snap["calls"] == 4
    assert snap["errors"] == 1
    assert snap["error_rate"] == 0.25
    assert snap["tools"]["t"]["codes"] == {"AUTH_REQUIRED": 1}


def test_latency_is_bucketed_not_exact():
    """An exact millisecond figure is a weak fingerprint of a network path; a bucket is
    enough to notice a provider getting slow."""
    tel = telemetry.Telemetry()
    tel.record("t", ok=True, seconds=0.1)
    tel.record("t", ok=True, seconds=42.0)
    buckets = tel.snapshot()["tools"]["t"]["latency"]
    assert buckets == {"<250ms": 1, ">=10s": 1}
    assert all(isinstance(k, str) for k in buckets)


def test_feedback_note_is_truncated():
    tel = telemetry.Telemetry()
    tel.record_feedback("t", helpful=False, note="x" * 5000)
    assert len(tel.snapshot()["feedback"][0]["note"]) == 500


def test_empty_flag_is_only_a_boolean():
    tel = telemetry.Telemetry()
    tel.record("t", ok=True, seconds=0.1, empty=True)
    stats = tel.snapshot()["tools"]["t"]
    assert stats["empty"] == 1
    assert "size" not in stats and "bytes" not in stats


# ─── local persistence ──────────────────────────────────────────────────


def test_local_stats_round_trip(tmp_path):
    tel = telemetry.Telemetry()
    tel.record("nhl_schedule", ok=False, seconds=0.2, code="UPSTREAM_TIMEOUT")
    assert telemetry.save_local(tel) is not None
    sessions = telemetry.load_local()
    assert sessions and sessions[-1]["tools"]["nhl_schedule"]["errors"] == 1


def test_an_idle_session_writes_nothing():
    """Starting and stopping the server without calling a tool should not accumulate
    empty rows forever."""
    assert telemetry.save_local(telemetry.Telemetry()) is None


def test_history_is_bounded(tmp_path):
    for i in range(60):
        tel = telemetry.Telemetry()
        tel.record(f"t{i}", ok=True, seconds=0.1)
        telemetry.save_local(tel)
    assert len(telemetry.load_local()) == 50


# ─── the emptiness heuristic ────────────────────────────────────────────


@pytest.mark.parametrize("value,expected", [
    (None, True), ([], True), ({}, True),
    ({"data": []}, True), ({"response": []}, True), ({"events": []}, True),
    ([{"id": 1}], False), ({"data": [{"id": 1}]}, False),
    ({"status": "ok"}, False),
    (0, False),  # a legitimate scalar result is not "empty"
])
def test_looks_empty(value, expected):
    from sportsdata_mcp.registry import _looks_empty

    assert _looks_empty(value) is expected


def test_feedback_is_bounded():
    """Per-tool counters are bounded by the tool count, but feedback is free text a
    caller can send any number of times. Unbounded, a long-running HTTP deployment grows
    forever and eventually POSTs a multi-megabyte payload — 5,000 notes measured at
    2.96 MB before this cap."""
    tel = telemetry.Telemetry()
    for i in range(5000):
        tel.record_feedback("t", helpful=False, note=f"note {i}")
    feedback = tel.snapshot()["feedback"]
    assert len(feedback) == 200
    # The most RECENT notes are the ones worth keeping.
    assert feedback[-1]["note"] == "note 4999"
    assert len(str(tel.payload())) < 500_000
