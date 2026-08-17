"""`sportsdata-mcp connect` — the credential wizard's safety properties.

This feature reads a session cookie out of the local browser, which is a capability that
has to be tightly bounded to be worth having. The bounds are: one host, never printed,
verified before it is stored, and written 0600 outside any repo. Those are the tests.

The alternative it replaces — a human copying a session credential through a clipboard,
a terminal and possibly a chat window — is the thing to compare against, and is why
reading locally is the safer path rather than the riskier one.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import httpx
import pytest

from sportsdata_mcp import connect


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for c in connect.CONNECTORS.values():
        monkeypatch.delenv(c.env_var, raising=False)


# ─── host scoping: the property that makes this acceptable ──────────────


def _fake_cookie_db(tmp_path: Path) -> Path:
    """A Chrome-shaped cookie DB holding cookies for several sites."""
    db = tmp_path / "Cookies"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)")
    con.executemany(
        "INSERT INTO cookies VALUES (?,?,?)",
        [
            (".fantasy.premierleague.com", "sessionid", b"fpl-session-value"),
            (".fantasy.premierleague.com", "pl_profile", b"fpl-profile-value"),
            (".mybank.example", "sessionid", b"BANK-SESSION-MUST-NEVER-APPEAR"),
            (".espn.com", "espn_s2", b"espn-value"),
        ],
    )
    con.commit()
    con.close()
    return db


def test_only_the_named_host_is_read(tmp_path, monkeypatch):
    """The whole justification. Connecting FPL must not be able to see another site's
    session cookie, even one with an identical NAME."""
    db = _fake_cookie_db(tmp_path)
    monkeypatch.setattr(connect, "_chrome_cookie_db", lambda: db)
    monkeypatch.setattr(connect, "_chrome_key", lambda: b"\x00" * 16)
    monkeypatch.setattr(connect, "_decrypt", lambda v, k: v.decode())

    got = connect.read_browser_cookies("fantasy.premierleague.com", ("sessionid", "pl_profile"))
    assert set(got) == {"sessionid", "pl_profile"}
    assert got["sessionid"] == "fpl-session-value"
    assert "BANK-SESSION-MUST-NEVER-APPEAR" not in str(got)


def test_a_cookie_name_not_asked_for_is_not_returned(tmp_path, monkeypatch):
    db = _fake_cookie_db(tmp_path)
    monkeypatch.setattr(connect, "_chrome_cookie_db", lambda: db)
    monkeypatch.setattr(connect, "_chrome_key", lambda: b"\x00" * 16)
    monkeypatch.setattr(connect, "_decrypt", lambda v, k: v.decode())
    got = connect.read_browser_cookies("fantasy.premierleague.com", ("sessionid",))
    assert set(got) == {"sessionid"}


def test_no_browser_is_not_an_error(monkeypatch):
    """A user without Chrome must fall through to the manual path, not crash."""
    monkeypatch.setattr(connect, "_chrome_cookie_db", lambda: None)
    assert connect.read_browser_cookies("fantasy.premierleague.com", ("sessionid",)) == {}


def test_declining_the_keychain_prompt_is_not_an_error(tmp_path, monkeypatch):
    """The prompt is the user's chance to say no, and saying no must be graceful."""
    monkeypatch.setattr(connect, "_chrome_cookie_db", lambda: _fake_cookie_db(tmp_path))
    monkeypatch.setattr(connect, "_chrome_key", lambda: None)
    assert connect.read_browser_cookies("fantasy.premierleague.com", ("sessionid",)) == {}


# ─── verify before storing ──────────────────────────────────────────────


def test_a_signed_out_cookie_is_rejected(monkeypatch):
    """FPL answers 200 with {"player": null} when signed out. A status-code check alone
    would store an expired cookie and call it connected — the failure a user would only
    discover at a deadline."""
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: httpx.Response(200, json={"player": None, "watched": []})
    )
    ok, why = connect.verify(connect.CONNECTORS["fpl"], "sessionid=stale")
    assert ok is False
    assert "signed out" in why


def test_a_working_cookie_is_accepted(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: httpx.Response(200, json={"player": {"id": 1}})
    )
    ok, why = connect.verify(connect.CONNECTORS["fpl"], "sessionid=good")
    assert ok is True and "verified" in why


def test_a_rejected_cookie_is_not_stored(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(403, text="nope"))
    ok, _ = connect.verify(connect.CONNECTORS["fpl"], "sessionid=bad")
    assert ok is False


def test_an_unreachable_provider_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    ok, why = connect.verify(connect.CONNECTORS["fpl"], "sessionid=x")
    assert ok is False and "could not reach" in why


# ─── storage ────────────────────────────────────────────────────────────


def test_the_secret_file_is_owner_only(tmp_path):
    path = connect.save_secret("FPL_SESSION_COOKIE", "sessionid=abc123")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


def test_saving_preserves_other_secrets(tmp_path):
    connect.save_secret("FPL_SESSION_COOKIE", "one")
    connect.save_secret("ESPN_S2", "two")
    import yaml

    data = yaml.safe_load(connect.config_path().read_text())
    assert data["secrets"] == {"FPL_SESSION_COOKIE": "one", "ESPN_S2": "two"}


def test_it_writes_where_the_loader_actually_reads(tmp_path):
    """A wizard that saves somewhere the server never looks is worse than no wizard."""
    from sportsdata_mcp.config import _candidate_paths

    connect.save_secret("FPL_SESSION_COOKIE", "sessionid=abc")
    assert connect.config_path() in _candidate_paths(None)


def test_the_saved_secret_is_actually_loaded(tmp_path):
    from sportsdata_mcp.config import load_config

    connect.save_secret("FPL_SESSION_COOKIE", "sessionid=abc123")
    cfg = load_config(connect.config_path())
    assert cfg.secrets["FPL_SESSION_COOKIE"] == "sessionid=abc123"


# ─── never print a credential ───────────────────────────────────────────


def test_fingerprint_does_not_reveal_the_value():
    secret = "sessionid=super-secret-value"
    fp = connect.fingerprint(secret)
    assert len(fp) == 8
    assert secret not in fp
    assert connect.fingerprint(secret) == fp  # stable, so it can identify a credential
    assert connect.fingerprint(secret + "x") != fp


def test_status_reports_connection_without_exposing_anything(tmp_path):
    connect.save_secret("FPL_SESSION_COOKIE", "sessionid=abc123")
    rows = connect.status()
    assert ("fpl", "Fantasy Premier League", True) in rows
    assert "abc123" not in str(rows)


def test_every_connector_names_a_single_host_and_a_login_url():
    """A connector without a host would be an unbounded cookie read."""
    for c in connect.CONNECTORS.values():
        assert c.cookie_host and "," not in c.cookie_host
        assert c.cookie_names
        assert c.login_url.startswith("https://")
