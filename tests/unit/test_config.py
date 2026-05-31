"""Config resolution + per-provider accessors."""

from __future__ import annotations

import textwrap

from sportsdata_mcp.config import (
    MAX_RESPONSE_BYTES_DEFAULT,
    RATE_LIMIT_RPS_DEFAULT,
    Config,
    load_config,
)


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTSDATA_MCP_CONFIG", raising=False)
    monkeypatch.delenv("SPORTSDATA_MCP_GROUPS", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.enabled_groups == []
    assert cfg.providers == {}


def test_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTSDATA_MCP_GROUPS", raising=False)
    p = tmp_path / "sportsdata-mcp.yaml"
    p.write_text(
        textwrap.dedent(
            """
            enabled_groups: [afl.public.core, sportsbet.racing]
            providers:
              afl:
                max_response_bytes: 1024
                rate_limit_rps: 4
            """
        )
    )
    cfg = load_config(explicit_path=p)
    assert cfg.enabled_groups == ["afl.public.core", "sportsbet.racing"]
    assert cfg.max_response_bytes_for("afl") == 1024
    assert cfg.rate_limit_rps_for("afl") == 4.0


def test_env_groups_override_file(tmp_path, monkeypatch):
    p = tmp_path / "sportsdata-mcp.yaml"
    p.write_text("enabled_groups: [afl.public.core]\n")
    monkeypatch.setenv("SPORTSDATA_MCP_GROUPS", "entain.graphql, sportsbet.racing")
    cfg = load_config(explicit_path=p)
    assert cfg.enabled_groups == ["entain.graphql", "sportsbet.racing"]


def test_accessor_defaults_for_unknown_provider():
    cfg = Config()
    assert cfg.max_response_bytes_for("nope") == MAX_RESPONSE_BYTES_DEFAULT
    assert cfg.rate_limit_rps_for("nope") == RATE_LIMIT_RPS_DEFAULT


def test_legacy_rate_per_sec_key():
    cfg = Config(providers={"x": {"rate_per_sec": 7}})
    assert cfg.rate_limit_rps_for("x") == 7.0


def test_env_max_bytes_sets_global_override(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTSDATA_MCP_CONFIG", raising=False)
    monkeypatch.delenv("SPORTSDATA_MCP_GROUPS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPORTSDATA_MCP_MAX_BYTES", "0")
    cfg = load_config()
    assert cfg.max_bytes_override == 0
    assert cfg.max_response_bytes_for("sportsbet") == 0  # 0 → no cap


def test_env_max_bytes_malformed_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("SPORTSDATA_MCP_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPORTSDATA_MCP_MAX_BYTES", "lots")
    cfg = load_config()
    assert cfg.max_bytes_override is None
    assert cfg.max_response_bytes_for("sportsbet") == MAX_RESPONSE_BYTES_DEFAULT
