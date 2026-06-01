"""Offline unit tests for doctor's pure probe-selection helpers."""

from __future__ import annotations

from sportsdata_mcp.doctor import (
    _full_url,
    _payload_shape,
    _pick_endpoint_probe,
    _zero_variable_op,
)
from sportsdata_mcp.spec import (
    Endpoint,
    Example,
    GraphQLBlock,
    GraphQLOperation,
    Provider,
    Spec,
)


def _ep(name: str, path: str, *, params=None, examples=None) -> Endpoint:
    return Endpoint(
        name=name,
        group="demo.public.core",
        summary="x",
        base="default",
        path=path,
        params=params or [],
        examples=examples or [],
    )


# ─── _payload_shape ────────────────────────────────────────────────────


def test_payload_shape_dict():
    assert _payload_shape({"a": 1, "b": 2}) == "dict, 2 keys"


def test_payload_shape_list():
    assert _payload_shape([1, 2, 3]) == "list, 3 items"


def test_payload_shape_scalar():
    assert _payload_shape("hi") == "str"


# ─── _full_url ─────────────────────────────────────────────────────────


def _provider() -> Provider:
    return Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test/", "alt": "https://alt.demo.test"},
    )


def test_full_url_strips_trailing_slash():
    assert _full_url(_provider(), "default", "/v2/x") == "https://api.demo.test/v2/x"


def test_full_url_alt_base():
    assert _full_url(_provider(), "alt", "/y") == "https://alt.demo.test/y"


# ─── _pick_endpoint_probe ──────────────────────────────────────────────


def test_pick_prefers_example():
    """An endpoint carrying an example is chosen first, with its example params."""
    ex = _ep("demo_with_example", "/v2/matches/{matchId}", examples=[
        Example(description="d", params={"matchId": "CD_M1"})
    ], params=[{"name": "matchId", "in": "path", "type": "string"}])
    plain = _ep("demo_plain", "/v2/teams")
    ep, args = _pick_endpoint_probe([plain, ex])
    assert ep.name == "demo_with_example"
    assert args == {"matchId": "CD_M1"}


def test_pick_falls_back_to_no_required_param():
    """With no examples, an endpoint needing no required params is probed with {}."""
    needs_param = _ep("needs", "/v2/matches/{matchId}", params=[
        {"name": "matchId", "in": "path", "type": "string"}
    ])
    free = _ep("free", "/v2/teams", params=[
        {"name": "detail", "in": "query", "type": "boolean", "default": False}
    ])
    ep, args = _pick_endpoint_probe([needs_param, free])
    assert ep.name == "free"
    assert args == {}


def test_pick_all_need_params_returns_none_args():
    """When every endpoint needs params and none has an example: (first, None)."""
    a = _ep("a", "/v2/matches/{matchId}", params=[{"name": "matchId", "in": "path", "type": "string"}])
    b = _ep("b", "/v2/teams/{teamId}", params=[{"name": "teamId", "in": "path", "type": "string"}])
    ep, args = _pick_endpoint_probe([a, b])
    assert ep.name == "a"
    assert args is None


def test_pick_empty_returns_none_none():
    assert _pick_endpoint_probe([]) == (None, None)


# ─── _zero_variable_op ─────────────────────────────────────────────────


def _spec_with_ops(*ops: GraphQLOperation) -> Spec:
    return Spec(provider=_provider(), graphql=GraphQLBlock(operations=list(ops)))


def _op(name: str, *, verified: bool, variables: str = "") -> GraphQLOperation:
    return GraphQLOperation(name=name, sha256="a" * 64, variables=variables, verified=verified)


def test_zero_variable_op_picks_verified_no_vars():
    spec = _spec_with_ops(
        _op("HasVars", verified=True, variables="{ id: 1 }"),
        _op("Unverified", verified=False),
        _op("Good", verified=True),
    )
    op = _zero_variable_op(spec)
    assert op is not None
    assert op.name == "Good"


def test_zero_variable_op_none_when_all_need_vars_or_unverified():
    spec = _spec_with_ops(
        _op("HasVars", verified=True, variables="{ id: 1 }"),
        _op("Unverified", verified=False),
    )
    assert _zero_variable_op(spec) is None


def test_zero_variable_op_none_without_graphql_block():
    assert _zero_variable_op(Spec(provider=_provider())) is None
