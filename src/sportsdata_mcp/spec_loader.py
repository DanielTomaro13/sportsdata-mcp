"""Load specs from the package and validate them against the capability catalogue.

Specs ship *inside* the package (``src/sportsdata_mcp/specs/``) and are resolved via
``importlib.resources`` — never a cwd-relative ``./specs/`` — so the server works
identically from a source checkout, an installed wheel, or ``uvx``.
"""

from __future__ import annotations

import fnmatch
import json
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


def documents_path(provider_id: str) -> Path:
    """Path of a provider's printed-documents sidecar (``{provider}.documents.json``)."""
    return packaged_specs_dir() / f"{provider_id}.documents.json"


def load_operation_documents(provider_id: str) -> dict[str, str]:
    """Printed GraphQL query documents keyed by operation name, from the sidecar
    written by ``refresh-hashes``. The graphql_persisted dispatcher uses these for
    the standard Apollo APQ retry when a gateway evicts a hash. Providers without
    a sidecar get an empty map (no self-heal, the not-found error surfaces as before)."""
    path = documents_path(provider_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s (%s) — APQ self-heal disabled for %s", path.name, e, provider_id)
        return {}
    if not isinstance(raw, dict):
        log.warning("%s is not a JSON object — APQ self-heal disabled for %s", path.name, provider_id)
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def load_capabilities(path: Path | None = None) -> CapabilityCatalogue:
    if path is None:
        path = packaged_specs_dir() / "_capabilities.yaml"
    raw = yaml.safe_load(path.read_text())
    try:
        return CapabilityCatalogue.model_validate(raw)
    except ValidationError as e:
        raise SpecValidationError(f"{path.name}: {e}") from e


def load_spec_text(text: str, name: str) -> Spec:
    """Validate one spec's YAML text into a Spec (``name`` is used only for error context).
    Shared by the file loader and the OTA overlay path so both validate identically — a
    malformed-YAML or schema-invalid overlay surfaces as one SpecValidationError, never a
    raw scanner error that could escape the apply path."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecValidationError(f"{name}: not valid YAML ({e})") from e
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as e:
        raise SpecValidationError(f"{name}: {e}") from e
    if spec.spec_version > CURRENT_SPEC_VERSION:
        log.warning(
            "%s declares spec_version=%d but this build understands up to %d; "
            "loading anyway — newer fields may be ignored.",
            name,
            spec.spec_version,
            CURRENT_SPEC_VERSION,
        )
    return spec


def load_spec(path: Path) -> Spec:
    return load_spec_text(path.read_text(), path.name)


def _build_specs(sources: dict[str, str]) -> list[Spec]:
    """Validate a {filename: yaml-text} map into Specs, enforcing tool-name uniqueness
    across the whole set."""
    specs: list[Spec] = []
    seen_names: dict[str, str] = {}  # tool name -> spec filename
    for name in sorted(sources):
        spec = load_spec_text(sources[name], name)
        for tool in spec.all_tools():
            if tool.name in seen_names:
                raise SpecValidationError(
                    f"duplicate tool name '{tool.name}' between {seen_names[tool.name]} and {name}"
                )
            seen_names[tool.name] = name
        specs.append(spec)
    return specs


def load_all_specs(specs_dir: Path | None = None) -> list[Spec]:
    """Load every {provider}.yaml (skipping files starting with _).

    The default (no ``specs_dir``) load is what the running server uses: it reads the
    packaged specs and then lets an applied OTA overlay shadow/add specs by filename (see
    ``ota.overlay_spec_sources``). An explicit ``specs_dir`` (lint, tests) reads ONLY that
    directory — no overlay — so those stay deterministic on the source tree.

    If an applied overlay makes the *merged* set invalid (a cross-spec duplicate tool name,
    or a spec a newer build now rejects), the overlay is dropped and the packaged specs load
    instead — a bad OTA update must never take the server down with no path back.
    """
    use_overlay = specs_dir is None
    if specs_dir is None:
        specs_dir = packaged_specs_dir()

    packaged: dict[str, str] = {}  # filename -> yaml text
    for path in sorted(specs_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        packaged[path.name] = path.read_text()

    if not use_overlay:
        return _build_specs(packaged)

    from . import ota

    overlay = ota.overlay_spec_sources()
    if not overlay:
        return _build_specs(packaged)
    try:
        return _build_specs({**packaged, **overlay})
    except SpecValidationError as e:
        log.warning("applied spec overlay failed to load (%s) — falling back to packaged specs", e)
        return _build_specs(packaged)


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


# Curated group sets, so a newcomer doesn't have to already know 88 group names to
# get a useful server. Values are provider ids and/or literal groups — both are run
# through the same resolver below, so `provider.*` semantics apply here too.
#
# Keep these honest: a preset promises a coherent job ("compare prices across AU
# books"), not a marketing bundle. `free` is the one people will actually start with.
PRESETS: dict[str, list[str]] = {
    # Everything that works with NO user setup. Only datagolf and twitter genuinely
    # need a key the user must go and get: laliga ships a public subscription key as a
    # literal fallback, and afl.premium mints its token from a public endpoint — both
    # verified live returning 200 with an empty environment, so excluding them would
    # hide 20 working tools for no reason.
    "free": ["*", "-datagolf", "-twitter"],
    "all": ["*"],
    # The pitch: cross-book price disagreement on AU markets.
    "au-books": ["sportsbet", "tab", "betr", "pointsbet", "unibet", "entain", "dabble", "betfair"],
    # Books + exchange + prediction markets — everything you'd need to price a market.
    "odds": [
        "sportsbet", "tab", "betr", "pointsbet", "unibet", "entain", "dabble",
        "betfair", "pinnacle", "fanduel", "kalshi", "polymarket", "theoddsapi",
    ],
    # Thoroughbred / greyhound / harness across every book that prices it, plus form.
    "racing": [
        "sportsbet.racing", "tab.racing", "betr.racing", "pointsbet.racing",
        "unibet.racing", "fanduel.racing", "entain.*", "racingandsports", "betfair",
    ],
    # Exchange + prediction markets: the de-vigged "sharp" side of an arb comparison.
    "arb": ["betfair", "pinnacle", "kalshi", "polymarket"],
    "fantasy": ["espnfantasy", "supercoach", "sleeper"],
    "chess": ["lichess", "chesscom"],
    "esports": ["opendota", "pandascore"],
    # Historical closing odds — the backtesting half of the odds story.
    "backtest": ["footballdatauk", "cfbd"],
    # Official league / governing-body feeds only — no bookmakers.
    "official-stats": [
        "afl.public.*", "nrl", "nba", "nbl", "mlb", "premierleague", "laliga",
        "seriea", "wta", "cricketaustralia", "openf1", "espn", "nhl", "jolpicaf1",
        "squiggle", "openligadb", "euroleague", "ncaa", "motogp", "formulae",
        "nascar",
    ],
    # Live telemetry (openf1, 2023→) plus the historical record (jolpicaf1, 1950→):
    # neither answers the other's questions, so the preset carries both.
    "motorsport": ["openf1", "jolpicaf1", "motogp", "formulae", "nascar"],
    "aus": ["afl.public.*", "nrl", "nbl", "supercoach", "cricketaustralia",
            "racingandsports", "squiggle"],
}


def _all_groups(specs: list[Spec]) -> list[str]:
    return sorted({t.group for s in specs for t in s.all_tools()})


def _match_token(token: str, groups: list[str]) -> list[str]:
    """Groups selected by one (already sign-stripped) token.

    Accepts, in order: ``*`` (everything), a preset name, ``provider.*`` or any other
    ``fnmatch`` glob, a bare provider id (all its groups), or a literal group name.
    """
    if token == "*":
        return list(groups)
    if token in PRESETS:
        return resolve_groups(PRESETS[token], groups)
    if any(ch in token for ch in "*?["):
        # `espn.*` reads as "every espn group" to anyone who has used a shell — and
        # silently matching NOTHING (the old behaviour) is the worst possible answer,
        # because doctor/serve then run happily over an empty tool set.
        return [g for g in groups if fnmatch.fnmatch(g, token)]
    if "." not in token:
        return [g for g in groups if g.split(".", 1)[0] == token]
    return [token]


def resolve_groups(tokens: list[str], groups: list[str]) -> list[str]:
    """Resolve group selectors to concrete group names.

    Additions are applied first, then exclusions (``-token``), so the natural
    ``"*,-twitter"`` means "everything except twitter" regardless of order. An
    exclusion accepts every form an addition does, presets included.
    """
    include: set[str] = set()
    exclude: set[str] = set()
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if token.startswith("-"):
            exclude.update(_match_token(token[1:], groups))
        else:
            include.update(_match_token(token, groups))
    return sorted(include - exclude)


def expand_wildcard_groups(enabled_groups: list[str], specs: list[Spec]) -> list[str]:
    """Resolve ``Config.enabled_groups`` selectors against the loaded specs.

    Shared by every consumer (server, doctor) so a selector means the same thing
    everywhere. Historically this only expanded a bare ``"*"``; it now also handles
    presets, provider ids, globs and exclusions, while a plain list of literal group
    names still resolves to itself.
    """
    if not enabled_groups:
        return []
    return resolve_groups(enabled_groups, _all_groups(specs))


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
