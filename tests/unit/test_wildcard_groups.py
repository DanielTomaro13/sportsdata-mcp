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


async def test_wildcard_expands_in_doctor() -> None:
    """`SPORTSDATA_MCP_GROUPS="*"` must mean the same thing in doctor as in serve —
    it previously expanded only in build_server, so doctor silently checked nothing."""
    from sportsdata_mcp.spec_loader import expand_wildcard_groups, load_all_specs

    specs = load_all_specs()
    expanded = expand_wildcard_groups(["*"], specs)
    assert "*" not in expanded
    assert {"mlb.reference", "openf1.reference", "tab.racing"} <= set(expanded)
    # explicit lists pass through untouched
    assert expand_wildcard_groups(["mlb.reference"], specs) == ["mlb.reference"]
