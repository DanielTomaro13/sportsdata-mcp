"""Apollo persisted-query dispatcher.

One tool calls any of a provider's persisted GraphQL operations by name. Hashes
are stored server-side in the spec's `graphql.operations` block; the model only
ever supplies an operation name + variables (discovered via the catalogue resource).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable

from ..errors import PersistedQueryNotFoundError, ToolError
from ..http_client import HTTPClient
from ..spec import Dispatcher, Spec


def _is_persisted_query_not_found(body: object) -> bool:
    """Apollo returns HTTP 200 with an errors[] envelope when a hash is unknown."""
    if not isinstance(body, dict):
        return False
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    for err in errors:
        if not isinstance(err, dict):
            continue
        msg = str(err.get("message", "")).lower()
        code = ""
        ext = err.get("extensions")
        if isinstance(ext, dict):
            code = str(ext.get("code", "")).lower()
        if "persistedquerynotfound" in msg.replace(" ", "") or code == "persisted_query_not_found":
            return True
    return False


def make_graphql_dispatcher(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    ops_by_name = {op.name: op for op in (spec.graphql.operations if spec.graphql else [])}

    async def handler(*, operation: str, variables: dict | None = None):
        op = ops_by_name.get(operation)
        if not op:
            raise ToolError(
                f"Unknown operation '{operation}'. "
                f"Read the {disp.catalog_resource} resource to list valid operations.",
                recoverable=True,
                code="UNKNOWN_OPERATION",
            )
        params = {
            "operationName": operation,
            "variables": json.dumps(variables or {}, separators=(",", ":")),
            "extensions": json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": op.sha256}},
                separators=(",", ":"),
            ),
        }
        body = await http.request_json(
            method=disp.method,
            base=disp.base or "default",
            url=disp.endpoint or "",
            params=params,
            headers=disp.default_headers,
            auth_key=disp.auth,
        )
        if _is_persisted_query_not_found(body):
            raise PersistedQueryNotFoundError(
                operation=operation,
                hash_prefix=op.sha256[:16],
                refresh_cmd=(
                    f"sportsdata-mcp refresh-hashes {spec.provider.id}"
                    if spec.provider.hash_refresh is not None
                    else None
                ),
            )
        return body

    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter("operation", inspect.Parameter.KEYWORD_ONLY, annotation=str),
            inspect.Parameter("variables", inspect.Parameter.KEYWORD_ONLY, annotation=dict, default=None),
        ]
    )
    handler.__name__ = disp.name
    handler.__doc__ = disp.summary
    return handler
