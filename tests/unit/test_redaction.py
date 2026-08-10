"""Credentials must not reach the logs, whichever library does the logging.

Seven providers here authenticate with a QUERY PARAMETER, so the secret is part of the
URL. Our own log line prints the base URL and passes params separately — but httpx logs
the fully-composed URL at INFO, and `sportsdata-mcp -v doctor` printed:

    INFO httpx: HTTP Request: GET https://api.the-odds-api.com/v4/sports?apiKey=SECRETKEY12345

Verbose mode is what people turn on when a provider misbehaves, and its output is what
they paste into a bug report. Found in a full-codebase review; these tests keep it fixed.
"""

from __future__ import annotations

import logging

import pytest

from sportsdata_mcp import redact


@pytest.fixture
def caplog_root(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def _filtered(values, msg, *args):
    """Run one record through the filter and return the formatted result."""
    filt = redact.RedactingFilter(set(values))
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    filt.filter(record)
    return record.getMessage()


def test_a_secret_in_the_message_is_redacted():
    assert "SECRETKEY12345" not in _filtered({"SECRETKEY12345"}, "key=SECRETKEY12345")


def test_a_secret_in_a_string_arg_is_redacted():
    out = _filtered({"SECRETKEY12345"}, "url=%s", "https://x/y?apiKey=SECRETKEY12345")
    assert "SECRETKEY12345" not in out
    assert "***REDACTED***" in out


def test_a_secret_in_a_NON_string_arg_is_redacted():
    """The bug that made the first version of this filter useless: httpx passes the URL
    as an httpx.URL object, so an isinstance(str) check skipped exactly the leak the
    filter existed to stop."""

    class UrlLike:
        def __str__(self):
            return "https://api.the-odds-api.com/v4/sports?apiKey=SECRETKEY12345"

    out = _filtered({"SECRETKEY12345"}, 'HTTP Request: %s %s "%s"', "GET", UrlLike(), "200 OK")
    assert "SECRETKEY12345" not in out
    assert "***REDACTED***" in out


def test_dict_args_are_redacted():
    out = _filtered({"SECRETKEY12345"}, "%(u)s", {"u": "k=SECRETKEY12345"})
    assert "SECRETKEY12345" not in out


def test_ordinary_records_are_untouched():
    assert _filtered({"SECRETKEY12345"}, "GET %s -> %d", "https://x/y", 200) == "GET https://x/y -> 200"


def test_numeric_args_survive_formatting():
    """A %d arg must stay an int — coercing everything to str would raise here."""
    assert _filtered({"SECRETKEY12345"}, "count=%d", 42) == "count=42"


def test_longer_secrets_are_redacted_first():
    """If one secret contains another, redacting the short one first would leave a
    recognisable fragment of the long one in the log."""
    out = _filtered({"ABCD1234", "ABCD1234EFGH5678"}, "k=ABCD1234EFGH5678")
    assert "EFGH5678" not in out


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    """Redacting a 2-character value would mangle every unrelated line."""
    monkeypatch.setenv("THE_ODDS_API_KEY", "ab")
    assert "ab" not in redact.secret_values()


def test_secret_names_come_from_the_specs_not_a_hardcoded_list(monkeypatch):
    """A provider added later must be covered without editing redact.py."""
    monkeypatch.setenv("CRICKETDATA_API_KEY", "cricket-secret-value")
    monkeypatch.setenv("MYSPORTSFEEDS_API_KEY", "basic-auth-username-secret")
    values = redact.secret_values()
    assert "cricket-secret-value" in values
    assert "basic-auth-username-secret" in values  # username_env, i.e. HTTP Basic


def test_a_filter_with_no_secrets_passes_everything(monkeypatch):
    filt = redact.RedactingFilter(set())
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "anything", None, None)
    assert filt.filter(record) is True
    assert record.getMessage() == "anything"


def test_install_is_idempotent(monkeypatch):
    """Called twice, it must not stack duplicate filters onto every handler."""
    monkeypatch.setenv("THE_ODDS_API_KEY", "a-real-looking-secret")
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        redact.install()
        redact.install()
        count = sum(isinstance(f, redact.RedactingFilter) for f in handler.filters)
        assert count == 1
    finally:
        root.removeHandler(handler)
