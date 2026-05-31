"""Config resolution: CLI flag > env var > cwd file > user config dir > defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# No response-size cap by default (0 = unlimited). A positive value can still be set
# per provider (providers.<id>.max_response_bytes) or globally (SPORTSDATA_MCP_MAX_BYTES)
# to protect the model's context window; see max_response_bytes_for().
MAX_RESPONSE_BYTES_DEFAULT = 0
RATE_LIMIT_RPS_DEFAULT = 10.0


@dataclass
class Config:
    enabled_groups: list[str] = field(default_factory=list)
    providers: dict[str, dict] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    config_path: Path | None = None
    specs_dir: Path | None = None
    # Global response-size cap (bytes) applied to every provider that doesn't set its own.
    # 0 (or negative) disables the cap entirely. None = fall back to MAX_RESPONSE_BYTES_DEFAULT.
    max_bytes_override: int | None = None

    def request_timeout(self, provider_id: str, default: float = 30.0) -> float:
        return float(self.providers.get(provider_id, {}).get("request_timeout_seconds", default))

    def max_response_bytes_for(self, provider_id: str) -> int:
        """Per-provider response size cap (bytes); 0 or negative means no cap.

        Precedence: ``providers.<id>.max_response_bytes`` > the global override
        (``SPORTSDATA_MCP_MAX_BYTES`` env / ``max_bytes_override``) > the default.
        """
        prov = self.providers.get(provider_id, {})
        if prov.get("max_response_bytes") is not None:
            return int(prov["max_response_bytes"])
        if self.max_bytes_override is not None:
            return int(self.max_bytes_override)
        return MAX_RESPONSE_BYTES_DEFAULT

    def rate_limit_rps_for(self, provider_id: str) -> float:
        """Per-provider token-bucket sustained rate (requests/sec)."""
        prov = self.providers.get(provider_id, {})
        # Accept the documented `rate_limit_rps`, falling back to the legacy `rate_per_sec`.
        return float(prov.get("rate_limit_rps", prov.get("rate_per_sec", RATE_LIMIT_RPS_DEFAULT)))


def _candidate_paths(explicit: Path | None) -> list[Path]:
    if explicit:
        return [explicit]
    env_path = os.environ.get("SPORTSDATA_MCP_CONFIG")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / "sportsdata-mcp.yaml")
    candidates.append(Path.home() / ".config" / "sportsdata-mcp" / "config.yaml")
    return candidates


def load_config(explicit_path: Path | None = None, specs_dir: Path | None = None) -> Config:
    cfg = Config(specs_dir=specs_dir)

    for path in _candidate_paths(explicit_path):
        if path and path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            cfg.enabled_groups = list(data.get("enabled_groups") or [])
            cfg.providers = dict(data.get("providers") or {})
            cfg.secrets = dict(data.get("secrets") or {})
            cfg.config_path = path
            break

    # Env var overrides
    env_groups = os.environ.get("SPORTSDATA_MCP_GROUPS")
    if env_groups:
        cfg.enabled_groups = [g.strip() for g in env_groups.split(",") if g.strip()]

    # SPORTSDATA_MCP_MAX_BYTES sets the global response-size cap; 0 disables it.
    env_max = os.environ.get("SPORTSDATA_MCP_MAX_BYTES")
    if env_max:
        try:
            cfg.max_bytes_override = int(env_max)
        except ValueError:
            pass  # ignore a malformed value; fall back to per-provider / default

    return cfg
