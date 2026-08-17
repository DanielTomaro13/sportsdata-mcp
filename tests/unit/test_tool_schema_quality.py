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
from sportsdata_mcp.spec import auth_env_names
from sportsdata_mcp.spec_loader import load_all_specs


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
    """The annotation is a promise a client acts on. Anything that changes state — local
    (`sportsdata_feedback`) or remote (a `.write` group tool) — must not claim otherwise.

    The write side is covered in depth by tests/unit/test_write_tools.py; this asserts the
    complement, that everything ELSE still reads as read-only.
    """
    writes = {t.name for s in load_all_specs() for t in s.all_tools() if t.group.endswith(".write")}
    for t in all_tools:
        if t.name == "sportsdata_feedback" or t.name in writes:
            assert t.annotations.readOnlyHint is False, f"{t.name} should not claim read-only"
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


# ─── what the description tells a model beyond the shape ────────────────


async def test_every_tool_states_its_auth_requirement(all_tools):
    """An agent that knows a call needs API_TENNIS_KEY can say so instead of retrying,
    and one that knows a provider is keyless will not ask the user for a key it does not
    need. Both are answerable without a round trip."""
    silent = [t.name for t in all_tools if "Auth:" not in (t.description or "")]
    # Meta-tools touch no provider, so they have nothing to declare.
    silent = [n for n in silent if not n.startswith(("list_", "sportsdata_"))]
    assert not silent, f"tools that do not state their auth requirement: {silent[:10]}"


async def test_byo_tools_name_the_env_var_in_their_description(all_tools):
    from sportsdata_mcp.spec_loader import load_all_specs

    byo = {s.provider.id: s for s in load_all_specs() if s.provider.requires_user_key}
    for t in all_tools:
        spec = byo.get(t.name.split("_")[0])
        if spec is None:
            continue
        envs = sorted(auth_env_names(spec.provider))
        # A description names the variable(s) a user must set. For OAuth providers the
        # engine reports the whole trio, so matching ANY of them is the right assertion —
        # requiring all three would demand noise in every tool description.
        assert any(e in (t.description or "") for e in envs), (
            f"{t.name} names none of {envs}"
        )


async def test_alternatives_are_only_listed_when_they_are_actionable(all_tools):
    """Naming three of sixty-eight is alphabetical bias dressed as advice, and repeating
    "go compare" on every tool cost ~12k tokens a session to say one thing 758 times.
    Specific names appear only for a short list; the general guidance lives once, in the
    server instructions."""
    for t in all_tools:
        line = next((ln for ln in (t.description or "").splitlines() if ln.startswith("Also answers this:")), None)
        if line:
            assert line.count(",") <= 2, f"{t.name} lists too many alternatives to be useful: {line}"
        assert "list_tools_by_capability` compares them" not in (t.description or "")


async def test_the_server_carries_instructions():
    """The place to say "several providers answer the same question" once."""
    mcp, reg = build_server(Config(enabled_groups=["nhl.*"]))
    try:
        text = mcp.instructions or ""
        assert "list_tools_by_capability" in text
        assert "capability" in text
        assert 200 < len(text) < 2000, f"instructions are {len(text)} chars"
    finally:
        await reg.aclose()


async def test_alternatives_never_point_at_an_unregistered_tool():
    """A suggestion the server did not register sends the model hunting for something
    that does not exist — worse than offering no alternative at all."""
    mcp, reg = build_server(Config(enabled_groups=["nhl.*", "mlb.*"]))
    try:
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        for t in tools:
            for ln in (t.description or "").splitlines():
                if ln.startswith("Also answers this:"):
                    for ref in ln.split(":", 1)[1].strip().rstrip(".").split(", "):
                        assert ref in names, f"{t.name} points at unregistered {ref}"
    finally:
        await reg.aclose()
