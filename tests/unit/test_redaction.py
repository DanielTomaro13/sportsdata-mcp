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
import os

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


def test_secrets_from_a_config_file_are_redacted_too(monkeypatch, tmp_path, caplog):
    """A key kept OUT of the environment must still be scrubbed from logs.

    The logger is configured before any config file is read, so config secrets
    can only arrive on a later install() call. That call used to be skipped
    whenever a filter was already attached — which meant the safest place to
    put a key was the one place it would not be redacted.
    """
    import logging

    from sportsdata_mcp import redact

    monkeypatch.delenv("DATAGOLF_KEY", raising=False)

    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        # installed first, knowing nothing (as at start-up)
        monkeypatch.setenv("SPORTSDATA_LICENSE", "licence-value-1234")
        redact.install()

        secret = "datagolf-secret-key-987654"
        filt = redact.install(extra_secrets={"DATAGOLF_KEY": secret})
        assert filt is not None

        scrubbed = filt._scrub(f"GET https://feeds.datagolf.com/preds?key={secret}")
        assert secret not in scrubbed
        assert "***REDACTED***" in scrubbed
        # the earlier secret must survive the extension, not be replaced by it
        assert "***REDACTED***" in filt._scrub("licence licence-value-1234")
    finally:
        root.removeHandler(handler)


def test_loading_a_config_registers_its_secrets(monkeypatch, tmp_path):
    """load_config wires its own secrets in, so no call site has to remember."""
    import logging

    from sportsdata_mcp import redact
    from sportsdata_mcp.config import load_config

    secret = "config-file-key-abcdef123456"
    path = tmp_path / "sportsdata-mcp.yaml"
    path.write_text(f'secrets:\n  DATAGOLF_KEY: "{secret}"\n')

    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        redact.install()
        load_config(explicit_path=path)
        filters = [f for h in root.handlers for f in h.filters if isinstance(f, redact.RedactingFilter)]
        assert filters, "loading a config with secrets must install a redactor"
        assert secret not in filters[0]._scrub(f"?key={secret}")
    finally:
        root.removeHandler(handler)


def test_a_handler_added_after_install_still_gets_covered(monkeypatch):
    """Reinstalling must cover NEW handlers, not just extend the old filter.

    The first attempt at config-secret support returned early whenever any
    filter already existed, which quietly left a handler added later — the
    normal case when a host application configures logging in stages —
    completely unredacted.
    """
    monkeypatch.setenv("THE_ODDS_API_KEY", "a-real-looking-secret")
    root = logging.getLogger()
    first = logging.StreamHandler()
    root.addHandler(first)
    second = None
    try:
        redact.install()
        second = logging.StreamHandler()
        root.addHandler(second)
        redact.install(extra_secrets={"DATAGOLF_KEY": "second-secret-value-1234"})

        for handler in (first, second):
            filters = [f for f in handler.filters if isinstance(f, redact.RedactingFilter)]
            assert len(filters) == 1, "every handler needs exactly one redactor"
            scrubbed = filters[0]._scrub("a-real-looking-secret second-secret-value-1234")
            assert "a-real-looking-secret" not in scrubbed
            assert "second-secret-value-1234" not in scrubbed
    finally:
        root.removeHandler(first)
        if second is not None:
            root.removeHandler(second)


# ─── the blind spot this file keeps rediscovering ───────────────────────


def test_every_auth_env_var_is_redacted_whatever_the_auth_type(monkeypatch):
    """Derived from the spec, not from a hand-written attribute list.

    That list has now been wrong three times, and the third was the worst: `redact.py`
    knew five of the six auth attributes and missed `refresh_token_env`, so Yahoo's
    REFRESH TOKEN — the single most durable credential in the system, granting a season
    of access to someone's fantasy account — was the one thing not scrubbed from a
    verbose log.

    Asserting over `AUTH_ENV_ATTRS` means a new auth type is covered the day it lands.
    """
    from sportsdata_mcp.spec import AUTH_ENV_ATTRS, auth_env_names
    from sportsdata_mcp.spec_loader import load_all_specs

    every_var = {name for s in load_all_specs() for name in auth_env_names(s.provider)}
    assert every_var, "no auth env vars found — has the spec model changed?"

    # Give each one a distinctive value, then assert redaction sees all of them.
    for i, name in enumerate(sorted(every_var)):
        monkeypatch.setenv(name, f"secret-value-for-{name.lower()}-{i:04d}")

    values = redact.secret_values()
    missed = [n for n in every_var if os.environ[n] not in values]
    assert not missed, f"these auth env vars would leak into logs: {sorted(missed)}"

    # And the attribute list itself must be the shared one.
    assert "refresh_token_env" in AUTH_ENV_ATTRS


def test_an_oauth_refresh_token_is_scrubbed_from_a_token_exchange_log(monkeypatch):
    """The concrete case: the refresh grant POSTs the token, and httpx logs the request."""
    monkeypatch.setenv("YAHOO_REFRESH_TOKEN", "AHR9-a-refresh-token-worth-a-whole-season")
    filt = redact.RedactingFilter(redact.secret_values())
    line = filt._scrub("POST /oauth2/get_token grant_type=refresh_token&refresh_token=AHR9-a-refresh-token-worth-a-whole-season")
    assert "AHR9" not in line
    assert "***REDACTED***" in line
