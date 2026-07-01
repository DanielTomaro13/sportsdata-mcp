"""Error types surfaced to the MCP client."""

from __future__ import annotations


class ToolError(Exception):
    """Base error returned to the MCP client.

    `recoverable=True` signals to the model that retrying with different args
    (e.g. a valid operation name from the catalogue resource) may succeed.
    """

    def __init__(self, message: str, *, recoverable: bool = False, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable
        self.code = code

    def to_payload(self) -> dict:
        return {"message": self.message, "code": self.code, "recoverable": self.recoverable}


class AuthMissingError(ToolError):
    """An auth secret (env var) is required and missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False, code="AUTH_MISSING")


class PersistedQueryNotFoundError(ToolError):
    """A GraphQL persisted hash is no longer registered with the gateway."""

    def __init__(self, *, operation: str, hash_prefix: str, refresh_cmd: str | None) -> None:
        # Only providers with a hash_refresh block can self-serve via the CLI; the rest
        # need the hash recaptured from live front-end traffic (see the provider doc).
        fix = (
            f"Run `{refresh_cmd}` and restart the MCP server."
            if refresh_cmd
            else "Recapture the hash from the live site's network traffic (see the provider doc) and update the spec."
        )
        super().__init__(
            f"GraphQL operation '{operation}' (hash {hash_prefix}…) is no longer registered "
            f"with the gateway. {fix}",
            recoverable=True,
            code="PERSISTED_QUERY_NOT_FOUND",
        )


class SpecValidationError(Exception):
    """Raised by spec_loader when YAML fails validation."""
