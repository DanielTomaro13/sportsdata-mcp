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
# Short-lived GET response cache. 60s is long enough to absorb the duplicate calls a
# model makes while reasoning over one question, and short enough that live prices
# stay live — the whole point of this server is that odds move.
CACHE_TTL_DEFAULT = 60.0


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
    # GET response cache TTL (seconds). 0 (or negative) disables caching.
    # None = fall back to CACHE_TTL_DEFAULT.
    cache_ttl_override: float | None = None

    def request_timeout(self, provider_id: str, spec_default: float | None = None, default: float = 30.0) -> float:
        """Read-timeout (seconds). User config wins, then the spec default, then ``default``."""
        prov = self.providers.get(provider_id, {})
        if prov.get("request_timeout_seconds") is not None:
            return float(prov["request_timeout_seconds"])
        if spec_default is not None:
            return float(spec_default)
        return float(default)

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

    def cache_ttl_for(self, provider_id: str) -> float:
        """Per-provider GET response cache TTL in seconds; 0 or negative disables it.

        Precedence mirrors ``max_response_bytes_for``: ``providers.<id>.cache_ttl_seconds``
        > the global override (``SPORTSDATA_MCP_CACHE_TTL`` env / ``cache_ttl_override``)
        > the default.
        """
        prov = self.providers.get(provider_id, {})
        if prov.get("cache_ttl_seconds") is not None:
            return float(prov["cache_ttl_seconds"])
        if self.cache_ttl_override is not None:
            return float(self.cache_ttl_override)
        return CACHE_TTL_DEFAULT

    def rate_limit_rps_for(self, provider_id: str, spec_default: float | None = None) -> float:
        """Per-provider token-bucket sustained rate (requests/sec).

        User config wins, then the spec default, then the engine default.
        """
        prov = self.providers.get(provider_id, {})
        # Accept the documented `rate_limit_rps`, falling back to the legacy `rate_per_sec`.
        val = prov.get("rate_limit_rps", prov.get("rate_per_sec"))
        if val is not None:
            return float(val)
        if spec_default is not None:
            return float(spec_default)
        return RATE_LIMIT_RPS_DEFAULT


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

    # Free-by-default: nothing configured anywhere means the FULL catalogue, not an
    # empty server (a fresh install must work out of the box). A config file or env
    # that explicitly names groups still narrows exactly as before.
    if not cfg.enabled_groups:
        cfg.enabled_groups = ["*"]

    # Secrets kept in the config file rather than the environment are invisible to
    # the redaction filter installed at start-up, because the logger is configured
    # before any config is read. Register them here rather than at each call site:
    # the whole point of that module is not depending on someone remembering.
    if cfg.secrets:
        from . import redact

        redact.install(extra_secrets=cfg.secrets)

    # SPORTSDATA_MCP_MAX_BYTES sets the global response-size cap; 0 disables it.
    env_max = os.environ.get("SPORTSDATA_MCP_MAX_BYTES")
    if env_max:
        try:
            cfg.max_bytes_override = int(env_max)
        except ValueError:
            pass  # ignore a malformed value; fall back to per-provider / default

    # SPORTSDATA_MCP_CACHE_TTL sets the global GET cache TTL in seconds; 0 disables it.
    env_ttl = os.environ.get("SPORTSDATA_MCP_CACHE_TTL")
    if env_ttl:
        try:
            cfg.cache_ttl_override = float(env_ttl)
        except ValueError:
            pass  # ignore a malformed value; fall back to per-provider / default

    return cfg
