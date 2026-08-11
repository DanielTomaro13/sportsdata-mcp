"""Templated-REST dispatcher.

One tool serves a family of parametric REST paths that share a base URL + auth
(e.g. AFL CFS premium, AFL StatsPro). The model supplies an operation name plus
path/query param maps; the catalogue resource lists valid operations.
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

PATH_PARAMS_HELP = (
    "Values for the operation's URL path placeholders, as an object keyed by placeholder "
    "name. The catalogue resource lists which each operation needs."
)
QUERY_PARAMS_HELP = (
    "Query-string parameters for the operation, as an object. Optional for most "
    "operations; the catalogue resource documents the accepted keys."
)



def make_templated_rest_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in disp.operations}

    async def handler(
        *,
        operation: Annotated[str, Field(description=OPERATION_HELP)],
        path_params: Annotated[dict | None, Field(description=PATH_PARAMS_HELP)] = None,
        query_params: Annotated[dict | None, Field(description=QUERY_PARAMS_HELP)] = None,
    ):
        op = ops_by_name.get(operation)
        if not op:
            raise ToolError(
                f"Unknown operation '{operation}'. Read the {disp.catalog_resource} resource "
                f"to list valid operations.",
                recoverable=True,
                code="UNKNOWN_OPERATION",
            )
        path_params = path_params or {}
        for required in op.path_params:
            if required not in path_params:
                raise ToolError(
                    f"operation '{operation}' requires path_param '{required}'",
                    recoverable=True,
                    code="MISSING_PATH_PARAM",
                )
        url = op.path.format(**path_params)
        # Per-op defaults underlay the caller's query_params: the model overrides
        # only the fields it cares about, the rest go up as their (often empty) default.
        merged_query = {**op.query_defaults, **(query_params or {})}
        return await http.request_json(
            method=disp.method,
            base=disp.base or "default",
            url=url,
            params=merged_query,
            headers=disp.default_headers,
            auth_key=disp.auth,
        )

    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter("operation", inspect.Parameter.KEYWORD_ONLY, annotation=str),
            inspect.Parameter("path_params", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
            inspect.Parameter("query_params", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
        ]
    )
    handler.__name__ = disp.name
    handler.__doc__ = disp.summary
    return handler
