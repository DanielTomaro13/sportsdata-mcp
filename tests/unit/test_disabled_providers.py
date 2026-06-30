"""Operator global off-switch (workbench B1): SPORTSDATA_MCP_DISABLED_PROVIDERS drops a
provider's groups entirely — even under the "*" wildcard — so its tools never register."""

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server


def _afl_groups(cfg: Config) -> list[str]:
    return [g for g in cfg.enabled_groups if g.startswith("afl.")]


def test_disabled_provider_dropped_under_wildcard(monkeypatch):
    monkeypatch.delenv("SPORTSDATA_MCP_DISABLED_PROVIDERS", raising=False)
    base = Config(enabled_groups=["*"])
    build_server(base)
    assert _afl_groups(base), "afl should have groups when nothing is disabled"

    monkeypatch.setenv("SPORTSDATA_MCP_DISABLED_PROVIDERS", "afl")
    off = Config(enabled_groups=["*"])
    build_server(off)
    assert _afl_groups(off) == [], "afl groups must be dropped when afl is disabled"
    # other providers untouched
    assert any(not g.startswith("afl.") for g in off.enabled_groups)


def test_multiple_disabled_and_whitespace(monkeypatch):
    monkeypatch.setenv("SPORTSDATA_MCP_DISABLED_PROVIDERS", " afl , nba ")
    cfg = Config(enabled_groups=["*"])
    build_server(cfg)
    assert not [g for g in cfg.enabled_groups if g.startswith(("afl.", "nba."))]


def test_unknown_disabled_provider_is_noop(monkeypatch):
    monkeypatch.setenv("SPORTSDATA_MCP_DISABLED_PROVIDERS", "doesnotexist")
    cfg = Config(enabled_groups=["*"])
    build_server(cfg)
    assert cfg.enabled_groups  # nothing dropped, server still has groups
