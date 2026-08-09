"""Transport selection for `serve`.

stdio stays the default — it is what Claude Desktop and Cursor spawn, and silently
switching it would break every existing install. The HTTP path exists for remote
clients and hosting, and carries an unauthenticated endpoint, so the tests below pin
both the default and the warning.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from sportsdata_mcp.cli import cli


def _run(args, **env):
    """Invoke `serve` with both server entrypoints stubbed, returning (result, calls)."""
    calls: dict[str, dict] = {}

    def fake_stdio(cfg=None, specs_dir=None):
        calls["stdio"] = {}

    def fake_http(cfg=None, specs_dir=None, *, host="127.0.0.1", port=3000, transport="http"):
        calls["http"] = {"host": host, "port": port, "transport": transport}

    with patch("sportsdata_mcp.server.serve_stdio", fake_stdio), \
         patch("sportsdata_mcp.server.serve_http", fake_http):
        result = CliRunner().invoke(cli, args, env=env or None)
    return result, calls


def test_default_is_stdio():
    """No flags = stdio. Every existing Claude Desktop / Cursor config depends on it."""
    result, calls = _run(["serve"])
    assert result.exit_code == 0, result.output
    assert "stdio" in calls and "http" not in calls


def test_http_flag_switches_transport():
    result, calls = _run(["serve", "--http"])
    assert result.exit_code == 0, result.output
    assert calls["http"]["transport"] == "http"


def test_http_defaults_to_loopback():
    """The default bind must be loopback: this endpoint has no authentication."""
    _result, calls = _run(["serve", "--http"])
    assert calls["http"]["host"] == "127.0.0.1"
    assert calls["http"]["port"] == 3000


def test_explicit_transport_overrides_flag():
    _result, calls = _run(["serve", "--http", "--transport", "sse"])
    assert calls["http"]["transport"] == "sse"


def test_transport_stdio_wins_over_http_flag():
    _result, calls = _run(["serve", "--http", "--transport", "stdio"])
    assert "stdio" in calls and "http" not in calls


def test_host_and_port_are_passed_through():
    _result, calls = _run(["serve", "--http", "--host", "0.0.0.0", "--port", "8080"])
    assert calls["http"] == {"host": "0.0.0.0", "port": 8080, "transport": "http"}


def test_non_loopback_bind_warns_loudly():
    """Binding a public interface publishes every enabled tool AND any provider
    credential in this process. That must never happen quietly."""
    result, _calls = _run(["serve", "--http", "--host", "0.0.0.0"])
    out = result.output.lower()
    assert "unauthenticated" in out
    assert "0.0.0.0" in result.output


def test_loopback_bind_does_not_warn():
    """Don't cry wolf on the safe default, or the real warning stops being read."""
    result, _calls = _run(["serve", "--http"])
    assert "unauthenticated" not in result.output.lower()


def test_env_vars_select_http():
    result, calls = _run(["serve"], SPORTSDATA_MCP_HTTP="1", SPORTSDATA_MCP_PORT="9001")
    assert result.exit_code == 0, result.output
    assert calls["http"]["port"] == 9001
