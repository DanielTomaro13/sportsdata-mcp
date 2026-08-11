"""What a model actually receives when it lists our tools.

Every parameter in every spec carries a `description:`, written carefully and reviewed —
and for the entire life of the project none of them reached the JSON schema. FastMCP
derives the schema from `__annotations__` via pydantic, so a bare `int` produced
`{"type": "integer"}` and the prose was dropped on the floor.

Nobody noticed because the specs looked right and the tools worked. It surfaced only when
an external MCP directory scored the server and reported "0% schema parameter coverage" —
i.e. the documentation we maintain most carefully was invisible to its only real reader.

These tests assert the contract from the model's side, not the spec's.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.server import build_server


@pytest.fixture(scope="module")
async def all_tools():
    mcp, reg = build_server(Config(enabled_groups=["*"]))
    try:
        yield await mcp.list_tools()
    finally:
        await reg.aclose()


async def test_every_parameter_has_a_description(all_tools):
    """The regression that started this file. A parameter with no description leaves a
    model guessing at valid values — and ours are rarely guessable (`compseason` is a
    competition-season id, not a year; `referenceExpression` is a Pulse filter)."""
    missing = [
        f"{t.name}.{name}"
        for t in all_tools
        for name, prop in ((t.parameters or {}).get("properties", {})).items()
        if not prop.get("description")
    ]
    assert not missing, f"{len(missing)} parameters with no description: {missing[:10]}"


async def test_every_tool_has_a_description(all_tools):
    thin = [t.name for t in all_tools if len((t.description or "").strip()) < 40]
    assert not thin, f"tools with a near-empty description: {thin}"


async def test_every_tool_carries_annotations(all_tools):
    """`readOnlyHint` / `idempotentHint` / `openWorldHint` tell a client it can call this
    without confirming with the user. Every tool here is a GET against a third party."""
    bare = [t.name for t in all_tools if t.annotations is None]
    assert not bare, f"tools with no annotations: {bare[:10]}"


async def test_read_only_hints_are_honest(all_tools):
    """The annotation is a promise. `sportsdata_feedback` mutates local state, so it must
    NOT claim to be read-only — a client that trusts the hint would call it freely."""
    for t in all_tools:
        if t.name == "sportsdata_feedback":
            assert t.annotations.readOnlyHint is False
        elif t.annotations is not None:
            assert t.annotations.readOnlyHint is True, f"{t.name} claims to write"


async def test_enum_parameters_expose_their_options(all_tools):
    """An enum in the spec must reach the schema, or a model has to guess a value the
    provider will reject."""
    from sportsdata_mcp.spec_loader import load_all_specs

    by_name = {t.name: t for t in all_tools}
    checked = 0
    for spec in load_all_specs():
        for ep in spec.endpoints:
            for p in ep.params:
                if not p.enum or ep.name not in by_name:
                    continue
                prop = (by_name[ep.name].parameters or {}).get("properties", {}).get(p.name)
                if prop is None:
                    continue
                blob = str(prop)
                assert all(str(v) in blob for v in p.enum), f"{ep.name}.{p.name} lost its enum"
                checked += 1
    assert checked > 50, f"expected many enum params, only checked {checked}"


async def test_required_parameters_are_marked_required(all_tools):
    """A required parameter that the schema lists as optional produces a confident call
    that 400s."""
    from sportsdata_mcp.spec_loader import load_all_specs

    by_name = {t.name: t for t in all_tools}
    for spec in load_all_specs():
        for ep in spec.endpoints:
            required = {p.name for p in ep.params if p.required and p.default is None}
            if not required or ep.name not in by_name:
                continue
            schema_required = set((by_name[ep.name].parameters or {}).get("required", []))
            assert required <= schema_required, (
                f"{ep.name}: {sorted(required - schema_required)} required in the spec but "
                f"optional in the schema"
            )
