"""Shared fixtures: temp spec dirs and a minimal config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sportsdata_mcp.config import Config

CAPABILITIES_YAML = textwrap.dedent(
    """
    capabilities:
      - id: sport.match_detail
        description: "Single sport event/match including teams, venue, start time."
      - id: sport.prices
        description: "Live or last prices for selections."
      - id: stats.shot_chart
        description: "Shot location / spatial data."
        single_provider: true
    """
).strip()


def _provider_spec(provider_id: str, *, group: str = "demo.public.core", capability: str = "sport.match_detail") -> str:
    return textwrap.dedent(
        f"""
        provider:
          id: {provider_id}
          display_name: "{provider_id.title()} Demo"
          base_urls:
            default: https://api.{provider_id}.test
          auth:
            default:
              type: none
        endpoints:
          - name: {provider_id}_match_get
            group: {group}
            capabilities: [{capability}]
            summary: "Get a match by id"
            base: default
            path: /v2/matches/{{matchId}}
            params:
              - {{ name: matchId, in: path, type: string }}
              - {{ name: detail, in: query, type: boolean, default: false, description: "verbose" }}
        """
    ).strip()


@pytest.fixture
def specs_dir(tmp_path: Path) -> Path:
    """A temp specs dir with the capability catalogue + one provider spec."""
    d = tmp_path / "specs"
    d.mkdir()
    (d / "_capabilities.yaml").write_text(CAPABILITIES_YAML)
    (d / "demo.yaml").write_text(_provider_spec("demo"))
    return d


@pytest.fixture
def write_spec(tmp_path: Path):
    """Factory: build a specs dir from raw YAML strings keyed by filename."""

    def _make(files: dict[str, str], *, with_capabilities: bool = True) -> Path:
        d = tmp_path / "specs"
        d.mkdir(exist_ok=True)
        if with_capabilities and "_capabilities.yaml" not in files:
            (d / "_capabilities.yaml").write_text(CAPABILITIES_YAML)
        for name, content in files.items():
            (d / name).write_text(textwrap.dedent(content).strip())
        return d

    return _make


@pytest.fixture
def base_config() -> Config:
    return Config(enabled_groups=[], providers={})
