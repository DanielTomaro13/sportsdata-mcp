"""`sportsdata-mcp setup` — self-register into an AI client's config (Phase 3 installer
'set it up for me'): merge our server, preserve others, never clobber bad JSON."""

import json

import pytest
from click.testing import CliRunner

from sportsdata_mcp import setup_client
from sportsdata_mcp.cli import cli


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_server_block_carries_only_the_key():
    block = setup_client.server_block("sd_live_abc", "/path/to/bin")
    assert block == {"command": "/path/to/bin", "args": ["serve"], "env": {"SPORTSDATA_LICENSE": "sd_live_abc"}}


def test_register_creates_and_writes(home):
    path = setup_client.register("cursor", "sd_live_abc", "sportsdata-mcp")
    assert path == home / ".cursor" / "mcp.json"
    data = json.loads(path.read_text())
    assert data["mcpServers"]["sportsdata"]["env"]["SPORTSDATA_LICENSE"] == "sd_live_abc"


def test_register_preserves_other_servers(home):
    cfg = home / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}))
    setup_client.register("cursor", "sd_live_abc", "cmd")
    data = json.loads(cfg.read_text())
    assert data["keep"] == 1
    assert data["mcpServers"]["other"] == {"command": "x"}  # untouched
    assert data["mcpServers"]["sportsdata"]["env"]["SPORTSDATA_LICENSE"] == "sd_live_abc"


def test_register_is_idempotent(home):
    setup_client.register("cursor", "sd_live_1", "cmd")
    setup_client.register("cursor", "sd_live_2", "cmd")  # re-run updates in place
    data = json.loads((home / ".cursor" / "mcp.json").read_text())
    assert list(data["mcpServers"]) == ["sportsdata"]
    assert data["mcpServers"]["sportsdata"]["env"]["SPORTSDATA_LICENSE"] == "sd_live_2"


def test_register_refuses_malformed_json(home):
    cfg = home / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        setup_client.register("cursor", "sd_live_abc", "cmd")
    assert cfg.read_text() == "{ not json"  # left untouched


def test_unknown_client_raises():
    with pytest.raises(ValueError, match="unsupported client"):
        setup_client.client_config_path("notepad")


# ── CLI ──


def test_cli_print_does_not_write(home):
    res = CliRunner().invoke(cli, ["setup", "--license", "sd_live_abc", "--client", "cursor", "--print"])
    assert res.exit_code == 0
    assert "mcpServers" in res.output and "sd_live_abc" in res.output
    assert not (home / ".cursor" / "mcp.json").exists()


def test_cli_writes_explicit_client(home):
    res = CliRunner().invoke(cli, ["setup", "--license", "sd_live_abc", "--client", "cursor"])
    assert res.exit_code == 0
    assert (home / ".cursor" / "mcp.json").exists()
    assert "✓ cursor" in res.output


def test_cli_both_targets_only_installed_clients(home):
    (home / ".cursor").mkdir()  # cursor "installed", Claude Desktop not
    res = CliRunner().invoke(cli, ["setup", "--license", "sd_live_abc", "--client", "both"])
    assert res.exit_code == 0
    assert (home / ".cursor" / "mcp.json").exists()
    claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert not claude.exists()  # not littered for an uninstalled client
