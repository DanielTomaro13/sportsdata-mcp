"""SPORTSDATA_MCP_GROUPS="*" enables every group (used by agent runtimes that filter
by capability tag rather than by group)."""

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server


def test_wildcard_enables_all_groups() -> None:
    mcp, reg = build_server(Config(enabled_groups=["*"]))
    assert len(reg.tools) > 300
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" in reg.tools


def test_explicit_groups_still_scope() -> None:
    mcp, reg = build_server(Config(enabled_groups=["mlb.reference"]))
    assert "mlb_teams" in reg.tools
    assert "openf1_sessions" not in reg.tools
