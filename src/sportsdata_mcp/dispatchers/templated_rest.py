"""Templated-REST dispatcher.

One tool serves a family of parametric REST paths that share a base URL + auth
(e.g. AFL CFS premium, AFL StatsPro). The model supplies an operation name plus
path/query param maps; the catalogue resource lists valid operations.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable

from ..errors import ToolError
from ..http_client import HTTPClient
from ..spec import Dispatcher, Spec


def make_templated_rest_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in disp.operations}

    async def handler(*, operation: str, path_params: dict | None = None, query_params: dict | None = None):
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
