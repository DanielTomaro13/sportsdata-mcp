"""Dispatcher handlers: templated-rest path/query building + error paths,
plus the graphql-persisted not-found path and Entain hash-refresh extraction."""

from __future__ import annotations

import pytest

from sportsdata_mcp.dispatchers.graphql_persisted import make_graphql_dispatcher
from sportsdata_mcp.dispatchers.templated_rest import make_templated_rest_dispatcher
from sportsdata_mcp.errors import PersistedQueryNotFoundError, ToolError
from sportsdata_mcp.spec import (
    Dispatcher,
    GraphQLBlock,
    GraphQLOperation,
    Provider,
    Spec,
    TemplatedOperation,
)

_HASH = "a" * 64


class _RecordingHTTP:
    """Stand-in HTTPClient that records the request_json call instead of making it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request_json(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


def _dispatcher() -> Dispatcher:
    return Dispatcher(
        name="afl_cfs_call",
        group="afl.premium.cfs",
        kind="templated_rest",
        summary="CFS dispatcher",
        base="premium",
        auth="premium",
        catalog_resource="afl://cfs/operations",
        operations=[
            TemplatedOperation(
                name="matchItem",
                path="/cfs/afl/matchItem/{matchProviderId}",
                path_params=["matchProviderId"],
            ),
            TemplatedOperation(
                name="statsCentre_players",
                path="/cfs/afl/statsCentre/players",
                query_params=["competitionId", "teamIds"],
            ),
        ],
    )


def _spec() -> Spec:
    return Spec(
        provider=Provider(
            id="afl",
            display_name="AFL",
            base_urls={"premium": "https://api.afl.com.au"},
        )
    )


async def test_templated_rest_interpolates_path():
    http = _RecordingHTTP()
    handler = make_templated_rest_dispatcher(_dispatcher(), _spec(), http)
    out = await handler(operation="matchItem", path_params={"matchProviderId": "CD_M1"})
    assert out == {"ok": True}
    call = http.calls[0]
    assert call["url"] == "/cfs/afl/matchItem/CD_M1"
    assert call["base"] == "premium"
    assert call["auth_key"] == "premium"


async def test_templated_rest_passes_query_params():
    http = _RecordingHTTP()
    handler = make_templated_rest_dispatcher(_dispatcher(), _spec(), http)
    await handler(
        operation="statsCentre_players",
        query_params={"competitionId": "CD_S2026014", "teamIds": "CD_T130,CD_T80"},
    )
    call = http.calls[0]
    assert call["url"] == "/cfs/afl/statsCentre/players"
    assert call["params"] == {"competitionId": "CD_S2026014", "teamIds": "CD_T130,CD_T80"}


async def test_unknown_operation_is_recoverable():
    http = _RecordingHTTP()
    handler = make_templated_rest_dispatcher(_dispatcher(), _spec(), http)
    with pytest.raises(ToolError) as ei:
        await handler(operation="nope")
    assert ei.value.code == "UNKNOWN_OPERATION"
    assert ei.value.recoverable is True
    assert "afl://cfs/operations" in str(ei.value)
    assert not http.calls  # never reached the network


async def test_missing_path_param_is_recoverable():
    http = _RecordingHTTP()
    handler = make_templated_rest_dispatcher(_dispatcher(), _spec(), http)
    with pytest.raises(ToolError) as ei:
        await handler(operation="matchItem")  # no path_params
    assert ei.value.code == "MISSING_PATH_PARAM"
    assert ei.value.recoverable is True
    assert not http.calls


# ─── GraphQL persisted dispatcher ──────────────────────────────────────


def _graphql_dispatcher() -> Dispatcher:
    return Dispatcher(
        name="entain_graphql_call",
        group="entain.graphql",
        kind="graphql_persisted",
        summary="Entain GraphQL dispatcher",
        endpoint="/gql/router",
        auth="default",
        catalog_resource="entain://graphql/operations",
    )


def _graphql_spec() -> Spec:
    return Spec(
        provider=Provider(id="entain", display_name="Entain", base_urls={"default": "https://api.ladbrokes.com.au"}),
        graphql=GraphQLBlock(operations=[GraphQLOperation(name="HomeSportsScreen", sha256=_HASH)]),
    )


class _ApolloHTTP:
    """Returns whatever body it is constructed with, recording the request."""

    def __init__(self, body: object) -> None:
        self.body = body
        self.calls: list[dict] = []

    async def request_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.body


async def test_graphql_unknown_operation_is_recoverable():
    http = _ApolloHTTP({"data": {}})
    handler = make_graphql_dispatcher(_graphql_dispatcher(), _graphql_spec(), http)
    with pytest.raises(ToolError) as ei:
        await handler(operation="NotARealOp")
    assert ei.value.code == "UNKNOWN_OPERATION"
    assert "entain://graphql/operations" in str(ei.value)
    assert not http.calls  # never reached the network


async def test_graphql_persisted_not_found():
    """A stale hash → Apollo HTTP-200 errors[] envelope → PERSISTED_QUERY_NOT_FOUND."""
    envelope = {"errors": [{"message": "PersistedQueryNotFound", "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"}}]}
    http = _ApolloHTTP(envelope)
    handler = make_graphql_dispatcher(_graphql_dispatcher(), _graphql_spec(), http)
    with pytest.raises(PersistedQueryNotFoundError) as ei:
        await handler(operation="HomeSportsScreen", variables={})
    assert ei.value.code == "PERSISTED_QUERY_NOT_FOUND"
    assert ei.value.recoverable is True
    assert "refresh-hashes entain" in str(ei.value)
    # The hash + extensions were sent before the gateway rejected it.
    sent = http.calls[0]["params"]
    assert sent["operationName"] == "HomeSportsScreen"
    assert _HASH in sent["extensions"]


async def test_graphql_success_passes_body_through():
    http = _ApolloHTTP({"data": {"featuredEvents": {"nodes": []}}})
    handler = make_graphql_dispatcher(_graphql_dispatcher(), _graphql_spec(), http)
    out = await handler(operation="HomeSportsScreen", variables={"includeFeaturedEvents": True})
    assert out == {"data": {"featuredEvents": {"nodes": []}}}
    assert http.calls[0]["url"] == "/gql/router"
