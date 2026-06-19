"""Tool registration: only enabled groups register; meta-tools always do."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.registry import _guard
from sportsdata_mcp.server import build_server

META_TOOLS = {"list_available_groups", "list_tools_by_capability", "list_resources"}


async def _tool_names(mcp) -> set[str]:
    return {t.name for t in await mcp.list_tools()}


async def test_meta_tools_always_registered(specs_dir):
    mcp, _reg = build_server(Config(enabled_groups=[]), specs_dir)
    names = await _tool_names(mcp)
    assert META_TOOLS <= names
    # no provider tools when nothing enabled
    assert "demo_match_get" not in names


async def test_enabled_group_registers_its_tools(specs_dir):
    mcp, reg = build_server(Config(enabled_groups=["demo.public.core"]), specs_dir)
    names = await _tool_names(mcp)
    assert "demo_match_get" in names
    assert reg.tools == ["demo_match_get"]


async def test_disabled_group_registers_nothing(specs_dir):
    _mcp, reg = build_server(Config(enabled_groups=["nonexistent.group"]), specs_dir)
    assert reg.tools == []
    assert reg.http_clients == []  # no client built for a provider with no enabled group


async def test_list_tools_by_capability_finds_enabled_tool(specs_dir):
    mcp, _reg = build_server(Config(enabled_groups=["demo.public.core"]), specs_dir)
    res = await mcp.call_tool("list_tools_by_capability", {"capability": "sport.match_detail"})
    data = res.structured_content
    tools = data["tools"]
    assert any(t["tool"] == "demo_match_get" and t["provider"] == "demo" for t in tools)
    assert tools[0]["args_required"] == ["matchId"]


async def test_capabilities_resource_lists_providers(specs_dir):
    mcp, _reg = build_server(Config(enabled_groups=["demo.public.core"]), specs_dir)
    result = await mcp.read_resource("sportsdata://capabilities")
    payload = json.loads(result.contents[0].content)
    by_id = {c["id"]: c for c in payload["capabilities"]}
    md = by_id["sport.match_detail"]
    assert md["providers"] == [{"provider": "demo", "tool": "demo_match_get"}]
    assert md["comparable"] is False  # only one provider


async def test_dynamic_signature_exposes_typed_params(specs_dir):
    mcp, _reg = build_server(Config(enabled_groups=["demo.public.core"]), specs_dir)
    tool = await mcp.get_tool("demo_match_get")
    schema = tool.parameters
    props = schema["properties"]
    assert "matchId" in props
    assert "detail" in props
    assert set(schema.get("required", [])) == {"matchId"}


# ─── _guard (transport-error catch-all) ────────────────────────────────


def _fake_handler(raises: Exception):
    async def inner(**kwargs):
        raise raises

    inner.__signature__ = inspect.Signature(
        parameters=[inspect.Parameter("eventId", inspect.Parameter.KEYWORD_ONLY, annotation=int)]
    )
    inner.__annotations__ = {"eventId": int, "return": dict}
    inner.__name__ = "fake_tool"
    inner.__doc__ = "fake"
    return inner


async def test_guard_converts_timeout_to_recoverable():
    guarded = _guard(_fake_handler(httpx.ConnectTimeout("slow")), "fake_tool", "test.group")
    with pytest.raises(ToolError) as ei:
        await guarded(eventId=1)
    assert ei.value.code == "UPSTREAM_TIMEOUT"
    assert ei.value.recoverable is True


async def test_guard_converts_transport_error_to_recoverable():
    guarded = _guard(_fake_handler(httpx.ConnectError("refused")), "fake_tool", "test.group")
    with pytest.raises(ToolError) as ei:
        await guarded(eventId=1)
    assert ei.value.code == "TRANSPORT_ERROR"
    assert ei.value.recoverable is True


async def test_guard_passes_our_toolerror_through_untouched():
    original = ToolError("boom", recoverable=True, code="UNKNOWN_OPERATION")
    guarded = _guard(_fake_handler(original), "fake_tool", "test.group")
    with pytest.raises(ToolError) as ei:
        await guarded(eventId=1)
    assert ei.value is original  # not re-wrapped — envelope preserved verbatim


def test_guard_preserves_signature_and_annotations():
    inner = _fake_handler(RuntimeError())
    guarded = _guard(inner, "fake_tool", "test.group")
    assert list(inspect.signature(guarded).parameters) == ["eventId"]
    assert guarded.__annotations__ == {"eventId": int, "return": dict}
