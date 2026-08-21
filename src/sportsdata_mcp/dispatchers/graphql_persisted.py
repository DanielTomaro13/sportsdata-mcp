"""Apollo persisted-query dispatcher.

One tool calls any of a provider's persisted GraphQL operations by name. Hashes
are stored server-side in the spec's `graphql.operations` block; the model only
ever supplies an operation name + variables (discovered via the catalogue resource).

Gateways keep APQ registrations in an evictable cache (Entain flushed 113/127
ops on 2026-07-07 with no bundle change), so a not-found answer does NOT mean
the hash is stale. When the provider ships a printed-documents sidecar
(``specs/{provider}.documents.json``, written by ``refresh-hashes``), the
handler self-heals exactly like a browser: retry once as a POST carrying the
full query text + its sha256, which re-registers the pair for everyone.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Callable
from typing import Annotated

from pydantic import Field

from ..errors import PersistedQueryNotFoundError, ToolError
from ..http_client import HTTPClient
from ..spec import Dispatcher, Spec
from ..spec_loader import load_operation_documents

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


log = logging.getLogger("sportsdata_mcp.graphql")


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
    documents: dict[str, str] | None = None  # sidecar loaded lazily, on first not-found

    async def handler(
        *,
        operation: Annotated[str, Field(description=OPERATION_HELP)],
        variables: Annotated[dict | None, Field(description=VARIABLES_HELP)] = None,
    ):
        nonlocal documents
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
        if not _is_persisted_query_not_found(body):
            return body

        # Gateway evicted (or never had) the hash. Self-heal like a browser: POST
        # the full document with its own sha256 — APQ accepts any self-consistent
        # pair and re-registers it, so subsequent hash-only calls succeed again.
        if documents is None:
            documents = load_operation_documents(spec.provider.id)
        query = documents.get(operation)
        if query is not None:
            sha = hashlib.sha256(query.encode()).hexdigest()
            log.warning(
                "persisted query '%s' not registered (provider=%s); re-registering via APQ retry",
                operation,
                spec.provider.id,
            )
            retry_body = await http.request_json(
                method="POST",
                base=disp.base or "default",
                url=disp.endpoint or "",
                headers=disp.default_headers,
                json_body={
                    "operationName": operation,
                    "query": query,
                    "variables": variables or {},
                    "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
                },
                auth_key=disp.auth,
            )
            if not _is_persisted_query_not_found(retry_body):
                # The registered pair is (sha, query); later calls in this process
                # should send that hash rather than re-triggering the retry.
                op.sha256 = sha
                return retry_body

        raise PersistedQueryNotFoundError(
            operation=operation,
            # `or ""` because an operation can carry no hash at all (newly added, never
            # refreshed). Subscripting None here would raise a TypeError *while raising
            # the real error* — replacing a clear "run refresh-hashes" message with a
            # traceback that points at the wrong thing entirely.
            hash_prefix=(op.sha256 or "")[:16],
            refresh_cmd=(
                f"sportsdata-mcp refresh-hashes {spec.provider.id}"
                if spec.provider.hash_refresh is not None
                else None
            ),
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
