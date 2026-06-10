"""Load specs from the package and validate them against the capability catalogue.

Specs ship *inside* the package (``src/sportsdata_mcp/specs/``) and are resolved via
``importlib.resources`` — never a cwd-relative ``./specs/`` — so the server works
identically from a source checkout, an installed wheel, or ``uvx``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from importlib import resources
from pathlib import Path

import yaml
from pydantic import ValidationError

from .errors import SpecValidationError
from .spec import CapabilityCatalogue, Spec

log = logging.getLogger("sportsdata_mcp.specs")

# Highest spec_version this build understands. A spec declaring a higher number
# loads with a warning (forward-compatible), never a hard failure.
CURRENT_SPEC_VERSION = 1


def packaged_specs_dir() -> Path:
    """Filesystem path to the packaged ``specs/`` directory (source checkout or unzipped wheel)."""
    return Path(str(resources.files("sportsdata_mcp") / "specs"))


def load_capabilities(path: Path | None = None) -> CapabilityCatalogue:
    if path is None:
        path = packaged_specs_dir() / "_capabilities.yaml"
    raw = yaml.safe_load(path.read_text())
    try:
        return CapabilityCatalogue.model_validate(raw)
    except ValidationError as e:
        raise SpecValidationError(f"{path.name}: {e}") from e


def load_spec(path: Path) -> Spec:
    raw = yaml.safe_load(path.read_text())
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as e:
        raise SpecValidationError(f"{path.name}: {e}") from e
    if spec.spec_version > CURRENT_SPEC_VERSION:
        log.warning(
            "%s declares spec_version=%d but this build understands up to %d; "
            "loading anyway — newer fields may be ignored.",
            path.name,
            spec.spec_version,
            CURRENT_SPEC_VERSION,
        )
    return spec


def load_all_specs(specs_dir: Path | None = None) -> list[Spec]:
    """Load every {provider}.yaml (skipping files starting with _) from the packaged specs dir."""
    if specs_dir is None:
        specs_dir = packaged_specs_dir()
    specs: list[Spec] = []
    seen_names: dict[str, str] = {}  # tool name -> spec filename
    for path in sorted(specs_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        spec = load_spec(path)
        for tool in spec.all_tools():
            if tool.name in seen_names:
                raise SpecValidationError(
                    f"duplicate tool name '{tool.name}' between {seen_names[tool.name]} and {path.name}"
                )
            seen_names[tool.name] = path.name
        specs.append(spec)
    return specs


def lint(specs_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """Validate every spec and cross-check against the capability catalogue.

    Returns (errors, warnings). Empty errors list = pass.
    """
    if specs_dir is None:
        specs_dir = packaged_specs_dir()
    errors: list[str] = []
    warnings: list[str] = []

    cap_path = specs_dir / "_capabilities.yaml"
    if not cap_path.exists():
        return [f"missing {cap_path}"], []

    try:
        catalogue = load_capabilities(cap_path)
    except SpecValidationError as e:
        return [str(e)], []

    cap_by_id = catalogue.by_id()

    # Duplicate description guard
    desc_seen: dict[str, str] = {}
    for cap in catalogue.capabilities:
        if cap.description in desc_seen:
            errors.append(
                f"duplicate capability description (typo guard): '{cap.id}' and "
                f"'{desc_seen[cap.description]}' share the same description"
            )
        desc_seen[cap.description] = cap.id

    # Load specs
    try:
        specs = load_all_specs(specs_dir)
    except SpecValidationError as e:
        return [str(e)], []

    # Capability references must exist; build provider index
    provider_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for spec in specs:
        for tool in spec.all_tools():
            for cap_id in tool.capabilities:
                if cap_id not in cap_by_id:
                    errors.append(
                        f"{spec.provider.id}/{tool.name}: capability '{cap_id}' not in _capabilities.yaml"
                    )
                else:
                    provider_index[cap_id].append((spec.provider.id, tool.name))

    # Single-provider warning
    for cap in catalogue.capabilities:
        providers = {p for p, _ in provider_index.get(cap.id, [])}
        if len(providers) == 1 and not cap.single_provider:
            warnings.append(
                f"capability '{cap.id}' is exposed by only one provider ({next(iter(providers))}). "
                f"Mark it `single_provider: true` or add another provider."
            )
        if len(providers) == 0 and not cap.single_provider:
            warnings.append(f"capability '{cap.id}' is not used by any spec yet.")

    return errors, warnings


def expand_wildcard_groups(enabled_groups: list[str], specs: list[Spec]) -> list[str]:
    """Resolve the ``"*"`` wildcard to every group across the given specs.

    Shared by every consumer of ``Config.enabled_groups`` (server, doctor) so the
    wildcard means the same thing everywhere.
    """
    if "*" not in enabled_groups:
        return enabled_groups
    return sorted({t.group for s in specs for t in s.all_tools()})


def build_provider_index(specs: list[Spec], enabled_groups: set[str]) -> dict[str, list[tuple[str, str]]]:
    """capability_id → [(provider_id, tool_name), …] limited to enabled groups."""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for spec in specs:
        for tool in spec.all_tools():
            if tool.group not in enabled_groups:
                continue
            for cap_id in tool.capabilities:
                index[cap_id].append((spec.provider.id, tool.name))
    return index


def all_groups(specs: list[Spec]) -> dict[str, dict]:
    """group → {provider, tool_count, description}."""
    out: dict[str, dict] = {}
    for spec in specs:
        for tool in spec.all_tools():
            entry = out.setdefault(
                tool.group,
                {"provider": spec.provider.id, "tools": 0, "description": ""},
            )
            entry["tools"] += 1
            if not entry["description"]:
                entry["description"] = tool.summary[:120]
    return out
