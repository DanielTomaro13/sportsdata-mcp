"""Self-register the MCP into an AI client's config — the "set it up for me" generator
(commerce Phase 3). Given a licence key it writes the ``mcpServers`` block into Claude
Desktop / Cursor, preserving any other servers, pointing ``command`` at this binary (the
bundled installer binary when frozen, otherwise the ``sportsdata-mcp`` on PATH). The
licence *is* the feed list, so the block carries only the key — adding feeds later never
touches it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

SERVER_NAME = "sportsdata"
CLIENTS = ("claude-desktop", "cursor")


def default_command() -> str:
    """How an MCP client should launch this server. A PyInstaller bundle runs its own
    binary; a normal install uses the ``sportsdata-mcp`` console script on PATH."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("sportsdata-mcp") or sys.argv[0] or "sportsdata-mcp"


def client_config_path(client: str) -> Path:
    """Absolute path of a client's MCP config file. Raises for an unknown client."""
    home = Path.home()
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "claude-desktop":
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if os.name == "nt":
            base = os.environ.get("APPDATA")
            if not base:
                raise ValueError("APPDATA is not set; cannot locate Claude Desktop config")
            return Path(base) / "Claude" / "claude_desktop_config.json"
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    raise ValueError(f"unsupported client: {client!r} (expected one of {', '.join(CLIENTS)})")


def server_block(license_key: str, command: str) -> dict:
    # Free product: no licence needed. The env block carries a key only when one is
    # supplied (dormant premium-feed machinery) — an empty env{} would be noise.
    block: dict = {"command": command, "args": ["serve"]}
    if license_key:
        block["env"] = {"SPORTSDATA_LICENSE": license_key}
    return block


def full_config(license_key: str, command: str) -> dict:
    return {"mcpServers": {SERVER_NAME: server_block(license_key, command)}}


def register(client: str, license_key: str, command: str) -> Path:
    """Merge our server into the client's config (creating it if needed), preserving any
    other ``mcpServers``. Returns the path written. Raises ``ValueError`` on a malformed
    existing config so we never clobber a file we can't safely parse."""
    path = client_config_path(client)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if path.exists() and path.read_text().strip():
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON ({exc}); fix or remove it and retry") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        data = loaded

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        # ValueError, not TypeError: the user's config FILE has a bad value — the
        # message is meant to be read by the person fixing that file.
        raise ValueError(f"{path} has a non-object 'mcpServers' key")  # noqa: TRY004
    servers[SERVER_NAME] = server_block(license_key, command)

    path.write_text(json.dumps(data, indent=2) + "\n")
    return path
