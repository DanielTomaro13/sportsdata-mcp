"""Full-query GraphQL dispatcher.

One tool calls any of a provider's GraphQL operations by name. Unlike the
persisted-query dispatcher (which sends a server-stored sha256 hash), this sends
the **literal query text** baked into the spec's ``graphql.operations`` block —
the pattern used by APIs like FanDuel Racing that accept full queries over POST.
The model only ever supplies an operation name + variables (discovered via the
catalogue resource); the heavy query string lives in the spec.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated

from pydantic import Field

from ..errors import ToolError
from ..http_client import HTTPClient
from ..spec import Dispatcher, Spec

# Dispatcher parameters are defined here in Python rather than in a spec's `params:`
# block, so they were the last tools whose schema carried no description — an agent saw
# `operation: string` with no hint that the valid values live in a catalogue resource.
OPERATION_HELP = (
    "The operation to run. Valid names come from this provider's catalogue resource "
    "(see `list_resources`) — guessing one returns an error listing the alternatives."
)

VARIABLES_HELP = (
    "Variables for the operation, as an object. Which keys are required depends on the "
    "operation; the catalogue resource documents each one."
)



def make_graphql_query_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in (spec.graphql.operations if spec.graphql else [])}

    async def handler(
        *,
        operation: Annotated[str, Field(description=OPERATION_HELP)],
        variables: Annotated[dict | None, Field(description=VARIABLES_HELP)] = None,
    ):
        op = ops_by_name.get(operation)
        if not op:
            raise ToolError(
                f"Unknown operation '{operation}'. "
                f"Read the {disp.catalog_resource} resource to list valid operations.",
                recoverable=True,
                code="UNKNOWN_OPERATION",
            )
        if not op.query:
            # A graphql_query op must carry its literal query text (lint should catch a
            # missing one, but fail loudly rather than POST a null query).
            raise ToolError(
                f"Operation '{operation}' has no query text in the spec.",
                recoverable=False,
                code="MALFORMED_OPERATION",
            )
        # FanDuel-style endpoints accept the standard GraphQL POST envelope. The op's
        # boilerplate defaults (brand/product/profile/…) fill in under the caller's vars.
        merged_variables = {**op.default_variables, **(variables or {})}
        body = {
            "operationName": operation,
            "variables": merged_variables,
            "query": op.query,
        }
        return await http.request_json(
            method="POST",
            base=disp.base or "default",
            url=disp.endpoint or "",
            json_body=body,
            headers=disp.default_headers,
            auth_key=disp.auth,
        )

    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter("operation", inspect.Parameter.KEYWORD_ONLY, annotation=str),
            inspect.Parameter("variables", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
        ]
    )
    handler.__name__ = disp.name
    handler.__doc__ = disp.summary
    return handler
