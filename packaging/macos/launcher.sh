#!/bin/sh
# Bundle entry point: exec the bundled MCP binary, forwarding any args. The AI client
# launches the inner binary directly (its absolute path is what `setup` writes), so this
# launcher only matters for a double-click — it just runs the server.
DIR="$(cd "$(dirname "$0")/../Resources/sportsdata-mcp" && pwd)"
exec "$DIR/sportsdata-mcp" "$@"
